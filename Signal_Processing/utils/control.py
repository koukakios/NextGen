# main.py (or control.py)
import serial
import time
from tensorflow.keras.models import load_model
import threading
import queue 
import subprocess
from contextlib import ExitStack
import asyncio
from bleak import BleakClient

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

# --- CHANGED: Serial configuration updated for single port ---
PORT = '/dev/cu.usbmodem101' #port of the arduino with the EMG and Mic 
BAUD = 1_000_000

# --- ADDED: Bluetooth BLE Configuration ---
# Note: macOS uses UUID strings for addresses. Windows/Linux use standard MAC addresses.
BLE_ADDRESS = "B49BD427-B606-4B44-2EDD-B0FD91BF8C58"
BLE_CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8" # The RX characteristic of your receiving board


# --- Dedicated Mic Worker Thread ---
def mic_processing_thread(mic_obj, data_queue):
    """Continuously runs the mic AI model in the background."""
    while True:
        mic_data = data_queue.get()
        if mic_data is None:  
            break
            
        try:
            mic_obj.update_mic(mic_data)
        except Exception as e:
            print(f"\n[MIC THREAD ERROR]: {e}")
            
        data_queue.task_done()

# --- Dedicated Camera Worker Thread ---
def camera_processing_thread(cam_obj):
    """Continuously processes OpenCV video frames in the background."""
    while True:
        cam_obj.update_state()
        time.sleep(0.01) 

# --- ADDED: Dedicated Bluetooth Worker Thread ---
def bluetooth_processing_thread(bt_queue, address, char_uuid):
    """Handles asynchronous BLE communication in a separate thread."""
    async def run_ble():
        while True: # ADDED: Outer loop to keep trying if connection drops
            print(f"[BLUETOOTH] Attempting connection to {address}...")
            try:
                # The timeout helps prevent it from hanging indefinitely on a bad connection
                async with BleakClient(address, timeout=10.0) as client:
                    print(f"\n[BLUETOOTH] Connected to Auxiliary Output!")
                    
                    # ADDED: Loop only while the connection is actively alive
                    while client.is_connected:
                        if not bt_queue.empty():
                            byte_data = bt_queue.get_nowait()
                            
                            # CHANGED: Let Bleak auto-detect the correct write property (response True/False)
                            await client.write_gatt_char(char_uuid, byte_data, response=False)
                            bt_queue.task_done()
                        
                        # Yield control to the event loop
                        await asyncio.sleep(0.01) 
                        
            except Exception as e:
                print(f"\n[BLUETOOTH ERROR]: {e}")
            
            # If it breaks out of the 'async with', the connection died. 
            print("[BLUETOOTH] Disconnected. Retrying in 2 seconds...")
            await asyncio.sleep(2)

    # Run the async loop inside this dedicated thread
    asyncio.run(run_ble())
# ------------------------------------------

if __name__ == "__main__":
    print("Initializing Systems...")

    # Initialize EMG
    my_emg = EMG()

    # Initialize Mic and load model
    print("Loading AI Model...")
    my_mic = Mic(fs=16_000, samples=16_000)
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

    cam_thread = threading.Thread(target=camera_processing_thread, args=(my_cam,), daemon=True)
    cam_thread.start()

    # --- ADDED: Initialize Bluetooth Thread ---
    bt_queue = queue.Queue(maxsize=10)
    bt_thread = threading.Thread(target=bluetooth_processing_thread, args=(bt_queue, BLE_ADDRESS, BLE_CHAR_UUID), daemon=True)
    bt_thread.start()
    # ---------------------------------------------

    print(f"Connecting to Main Input/Output on: {PORT}...")

    uart = 0b000  
    last_sent_time = time.time()
    last_sent_uart = None

    try:
        # --- CHANGED: ExitStack now only manages the single primary serial port ---
        with ExitStack() as stack:
            ser = stack.enter_context(serial.Serial(PORT, BAUD, timeout=0))
            
            ser.reset_input_buffer()
            time.sleep(2)  

            print("\nSystem Ready! Listening for sensor data... (Press Ctrl+C to stop)")
            print("-" * 50)

            while True:
                # 1. Grab all available packets 
                latest_emg_list, latest_mic_list = get_latest_data(ser)

                # 2. Update Mic 
                if latest_mic_list:
                    try:
                        mic_queue.put_nowait(latest_mic_list)
                    except queue.Full: 
                        pass

                # 3. Update EMG - including the stopping feature.
                if my_mic.output == 'stop':
                    my_emg.mode = (0,0,0)
                elif latest_emg_list and my_mic.mic_state:
                    my_emg.update_mode(latest_emg_list)
                
                # 4. Calculate Motor Logic 
                turning_mode = my_emg.turning_mode
                
                uart = signal_to_motor(my_mic.mic_state, my_emg.mode, my_cam.state, turning_mode, uart)

                # 5. "Smart Timer" Logic for sending data to BLE
                current_time = time.time()
                if (current_time - last_sent_time >= 0.05) or (uart != last_sent_uart):
                    byte_data = uart.to_bytes(1, 'big')
                
                    # --- CHANGED: Push byte to Bluetooth queue instead of serial write ---
                    try:
                        bt_queue.put_nowait(byte_data)
                    except queue.Full:
                        pass # Drop packet if BLE is lagging, prioritizing newest data
                    
                    last_sent_time = current_time
                    last_sent_uart = uart

                # 6. UI Update 

                print(f"EMG Gear: {my_emg.mode} | Mic: {my_mic.mic_state} | Cam: {my_cam.state}", end='\r')
            
    except KeyboardInterrupt:
        print("\n\nProgram stopped safely. Serial port closed cleanly.")