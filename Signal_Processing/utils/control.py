# main.py (or control.py)
import serial
import time
from tensorflow.keras.models import load_model

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

if __name__ == "__main__":
    print("Initializing Systems...")

    # Initialize EMG
    my_emg = EMG()

    # Initialize Mic and load model
    my_mic = Mic(fs=16_000, samples=16_000)
    print("Loading AI Model...")
    my_mic.model = load_model('model1.keras')

    # Initialize Camera
    print("Loading Camera and Face Models...")
    my_cam = Camera(
        proto_path=DNN_PROTO,
        model_path=DNN_MODEL,
        landmark_path=LBF_MODEL,
        camera_index=cam_index,
        deadzone_ratio=deadzone_ratio
    )

    print(f"Connecting to Arduino on {PORT}...")

    # --- Initialize State Tracking Variables Before the Loop ---
    uart = 0  # Initial motor state (still = 0)
    last_sent_time = time.time()
    last_sent_uart = None

    try:
        # timeout=0 ensures non-blocking buffer reads
        with serial.Serial(PORT, BAUD, timeout=0) as ser:
            ser.reset_input_buffer()
            time.sleep(2)  # Give Arduino time to reset

            print("System Ready! Listening for sensor data... (Press Ctrl+C to stop)")

            while True:
                # print("get mic and emg")
                # 1. Grab all available packets (These are now lists!)
                latest_emg_list, latest_mic_list = get_latest_data(ser)

                # print("mic shit")
                # 2. Update Mic with all new audio samples
                if latest_mic_list:
                    my_mic.update_mic(latest_mic_list)


                # print("emg shit")
                # 3. Update EMG (using ONLY the single most recent value from the list)
                if latest_emg_list and my_mic.mic_state:
                    my_emg.update_mode(latest_emg_list)

                # print("cam shit")
                # 4. Get Camera direction
                my_cam.update_state()

                # 5. Calculate Motor Logic
                turning_mode = False 
                uart = signal_to_motor(my_mic.mic_state, my_emg.mode, my_cam.state, turning_mode, uart)

                # 6. The "Smart Timer" Logic for sending data
                current_time = time.time()
                # Send if 100ms passed OR if the command actually changed instantly
                if (current_time - last_sent_time >= 0.1) or (uart != last_sent_uart):
                    ser.write(uart.to_bytes(1, 'big'))
                    last_sent_time = current_time
                    last_sent_uart = uart

                # 7. UI Update for the console (Added Camera State)
                if latest_emg_list and not my_emg.is_collecting:
                    print(f"EMG Gear: {my_emg.mode} | Mic: {my_mic.mic_state} | Cam: {my_cam.state}    ", end='\r')

                # Small delay to keep CPU usage low
                time.sleep(0.01)
            print("done")
    except KeyboardInterrupt:
        print("\nProgram stopped safely.")