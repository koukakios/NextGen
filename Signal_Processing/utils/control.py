# main.py
import serial
import time
from tensorflow.keras.models import load_model

# Clean Absolute Imports
from classes.emg_class import EMG
from classes.mic_class import Mic
from utils.collect_data import get_latest_data
from utils.signal_to_motor import signal_to_motor


#Camera imports
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

    #initialize camera
    my_cam = Camera(
        proto_path=DNN_PROTO,
        model_path=DNN_MODEL,
        landmark_path=LBF_MODEL,
        camera_index=cam_index,
        deadzone_ratio=deadzone_ratio
    )

    print(f"Connecting to Arduino on {PORT}...")

    try:
        with serial.Serial(PORT, BAUD, timeout=0) as ser:
            ser.reset_input_buffer()
            time.sleep(2)  # Give Arduino time to reset

            print("System Ready! Listening for sensor data... (Press Ctrl+C to stop)")

            while True:
                # 1. Grab everything in the buffer instantly
                latest_emg, latest_mic = get_latest_data(ser)
                my_mic.update_mic(latest_mic)

                if my_mic.mic_state:
                    my_emg.update_mode(latest_emg)

                #get camera direction
                my_cam.update_state()

                #sending to uart:
                uart = 0b000
                turning_mode = False
                uart = signal_to_motor(my_mic.mic_state, my_emg.mode, my_cam.state, turning_mode, uart)
                # 4. Optional UI Update for the console (keeping it clean)
                if latest_emg and not my_emg.is_collecting:
                    print(f"EMG Gear: {my_emg.mode} | Mic State: {my_mic.mic_state}      ", end='\r')

                # Small delay to keep CPU usage low
                time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nProgram stopped safely.")