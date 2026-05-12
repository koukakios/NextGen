import numpy as np
import scipy.signal as sig
import serial
import time
from utils.collect_data import get_latest_data


class EMG:
    def __init__(self):
        # We removed the internal Serial connection. The main loop handles it now.
        self.data = []  # You can store historical data here if needed
        self.mode = (0, 0, 0)
        self.speed_levels = [
            (0, 0, 0),  # Index 0: 0 km/h
            (0, 0, 1),  # Index 1: 5 km/h
            (0, 1, 0),  # Index 2: 10 km/h
            (1, 0, 0)  # Index 3: 15 km/h
        ]
        self.is_collecting = False
        self.collection_start_time = 0
        self.event_buffer = np.array([])
        self.trigger_threshold = 0.7
        self.previous_mode = None

    def update_mode(self, new_data_list):
        # 1. SAFETY CHECK: Skip if no new data arrived in this loop
        if len(new_data_list) == 0:
            return self.mode

        # Convert the new list to a numpy array
        new_data = np.array(new_data_list)

        # Keep a running log of all data if you need it later
        self.data.extend(new_data_list)

        current_gear = self.speed_levels.index(self.mode)

        # STATE 1: WAITING FOR FIRST PEAK
        if not self.is_collecting:
            if np.max(new_data) > self.trigger_threshold:
                self.is_collecting = True
                self.collection_start_time = time.time()
                self.event_buffer = np.copy(new_data)
            return self.mode

        # STATE 2: COLLECTING DATA FOR 1 SECOND
        else:
            self.event_buffer = np.concatenate((self.event_buffer, new_data))

            if (time.time() - self.collection_start_time) >= 2:
                peaks, _ = sig.find_peaks(self.event_buffer, height=self.trigger_threshold, prominence=0.2)
                num_peaks = len(peaks)

                # STATE 3: ANALYZE AND UPDATE GEAR
                if num_peaks == 1:
                    new_gear = min(current_gear + 1, len(self.speed_levels) - 1)
                    self.mode = self.speed_levels[new_gear]
                elif num_peaks == 2:
                    new_gear = max(current_gear - 1, 0)
                    self.mode = self.speed_levels[new_gear]
                elif num_peaks > 2:
                    self.mode = self.speed_levels[0]

                # STATE 4: RESET THE SYSTEM
                self.is_collecting = False
                self.event_buffer = np.array([])

            if self.mode != self.previous_mode:
                print(f"\n--> GEAR SHIFT: Mode is now {self.mode}")
                self.previous_mode = self.mode

            return self.mode

# --- MAIN TESTING SCRIPT ---
if __name__ == "__main__":
    PORT = '/dev/cu.usbmodem101'
    BAUD = 1_000_000  # Make sure this matches the Arduino setup!

    my_emg = EMG()
    all_mic_data = []  # Store your mic data here!

    print(f"Connecting to Arduino on {PORT}...")

    try:
        with serial.Serial(PORT, BAUD, timeout=1) as ser:
            ser.reset_input_buffer()
            time.sleep(2)  # Give Arduino time to reset

            print("Listening for sensor data... (Press Ctrl+C to stop)")

            while True:
                # 1. Grab everything in the buffer instantly
                latest_emg, latest_mic = get_latest_data(ser)

                # 2. Store mic data if needed
                if latest_mic:
                    all_mic_data.extend(latest_mic)

                # 3. Update the EMG state machine
                my_emg.update_mode(latest_emg)

                # 4. Real-time status bar update
                if latest_emg and not my_emg.is_collecting:
                    print(f"Live Max Signal: {np.max(latest_emg):.3f} | Current Mode: {my_emg.mode}    ", end='\r')

                # Small delay to keep CPU usage low
                time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nProgram stopped.")
        print(f"Total EMG samples recorded: {len(my_emg.data)}")
        print(f"Total Mic samples recorded: {len(all_mic_data)}")