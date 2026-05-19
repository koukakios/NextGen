# main.py (or control.py)
import serial
import time
from tensorflow.keras.models import load_model
import threading
import queue 
import subprocess

def run_parallel_script(script_name):
    subprocess.run(["python", script_name])

# Clean Absolute Imports
from classes.emg_class import EMG
from classes.mic_class import Mic
from utils.collect_data import get_latest_data
from utils.signal_to_motor import signal_to_motor

# Camera imports
from classes.camera_class import Camera
from utils.Config import DNN_PROTO, DNN_MODEL, LBF_MODEL
from utils.Config import deadzone_ratio, cam_index

PORT = '/dev/cu.usbmodem101'
BAUD = 1_000_000

# --- Dedicated Mic Worker Thread ---
def mic_processing_thread(mic_obj, data_queue):
    """Continuously runs the mic AI model in the background."""
    while True:
        mic_data = data_queue.get()
        if mic_data is None:  
            break
            
        try:
            # The safety net!
            mic_obj.update_mic(mic_data)
        except Exception as e:
            # If the AI model fails, print the exact error to the terminal
            print(f"\n[MIC THREAD ERROR]: {e}")
            
        data_queue.task_done()

# --- Dedicated Camera Worker Thread ---
def camera_processing_thread(cam_obj):
    """Continuously processes OpenCV video frames in the background."""
    while True:
        # This handles the heavy OpenCV/DNN frame processing
        # It updates cam_obj.state automatically without blocking the main loop
        cam_obj.update_state()
        
        # A tiny sleep here is okay because it only slows down the camera thread, 
        # NOT the main Serial transmission loop.
        time.sleep(0.01) 
# ------------------------------------------

if __name__ == "__main__":
    print("Initializing Systems...")

    # Initialize EMG
    my_emg = EMG()

    # Initialize Mic and load model
    my_mic = Mic(fs=16_000, samples=16_000)
    print("Loading AI Model...")
    my_mic.model = load_model('model1.keras')

    mic_queue = queue.Queue(maxsize=5) 
    mic_thread = threading.Thread(target=mic_processing_thread, args=(my_mic, mic_queue), daemon=True)
    mic_thread.start()

    # Initialize Camera
    print("Loading Camera and Face Models...")
    my_cam = Camera(
        proto_path=DNN_PROTO,
        model_path=DNN_MODEL,
        landmark_path=LBF_MODEL,
        camera_index=cam_index,
        deadzone_ratio=deadzone_ratio
    )

    # Start Camera Thread
    cam_thread = threading.Thread(target=camera_processing_thread, args=(my_cam,), daemon=True)
    cam_thread.start()
    # ---------------------------------------------

    print(f"Connecting to Arduino on {PORT}...")

    uart = 0  
    last_sent_time = time.time()
    last_sent_uart = None

    try:
        with serial.Serial(PORT, BAUD, timeout=0) as ser:
            ser.reset_input_buffer()
            time.sleep(2)  

            print("\nSystem Ready! Listening for sensor data... (Press Ctrl+C to stop)")
            print("-" * 50)

            while True:
                # 1. Grab all available packets (Must be as fast as possible)
                latest_emg_list, latest_mic_list = get_latest_data(ser)

                # 2. Update Mic (Hand off to background thread)
                if latest_mic_list:
                    try:
                        mic_queue.put_nowait(latest_mic_list)
                    except queue.Full: 
                        pass

                # 3. Update EMG 
                if latest_emg_list and my_mic.mic_state:
                    my_emg.update_mode(latest_emg_list)

                # 4. Get Camera direction
                # REMOVED: my_cam.update_state() is now running in the background thread!
                # We just read `my_cam.state` directly in step 5.

                # 5. Calculate Motor Logic 
                turning_mode = my_emg.turning_mode 
                uart = signal_to_motor(my_mic.mic_state, my_emg.mode, my_cam.state, turning_mode, uart)

                # 6. "Smart Timer" Logic for sending data
                current_time = time.time()
                if (current_time - last_sent_time >= 0.1) or (uart != last_sent_uart):
                    ser.write(uart.to_bytes(1, 'big'))
                    last_sent_time = current_time
                    last_sent_uart = uart

                # 7. UI Update for the console (Clean, single-line update)
                if latest_emg_list and not my_emg.is_collecting:
                    print(f"EMG Gear: {my_emg.mode} | Mic: {my_mic.mic_state} | Cam: {my_cam.state}    ", end='\r')

                # REMOVED: time.sleep(0.01) from main loop so the Serial buffer never overflows.
            
    except KeyboardInterrupt:
        print("\n\nProgram stopped safely.")