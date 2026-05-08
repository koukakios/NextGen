import numpy as np
import scipy.signal as sig
import serial
import time


class EMG:
    def __init__(self, data=0, mode=(0, 0, 0), port='/dev/cu.usbmodem101', baud=1000000, samples=100):
        self.data = data
        self.duration = 0
        self.mode = mode
        self.speed_levels = [
            (0, 0, 0),  # Index 0: 0 km/h
            (0, 0, 1),  # Index 1: 5 km/h
            (0, 1, 0),  # Index 2: 10 km/h
            (1, 0, 0)  # Index 3: 15 km/h
        ]
        self.port = port
        self.baud = baud
        self.samples = samples
        self.is_collecting = False
        self.collection_start_time = 0
        self.event_buffer = np.array([])
        self.trigger_threshold = 0.7  # The value the signal must cross to start the timer
        self.previous_mode = None

        self.arduino = serial.Serial(self.port, self.baud, timeout=1)
        time.sleep(2)  # Give the Arduino time to reset
        self.arduino.reset_input_buffer()

    def get_emg_data(self):
        y_e = []
        start_time = time.time()

        while len(y_e) < 20:
            raw_data = self.arduino.readline()
            if raw_data.startswith(b"E:"):
                try:
                    y_e.append(float(raw_data[2:].decode('utf-8').strip()))
                except ValueError:
                    pass

        self.duration = time.time() - start_time
        return np.array(y_e), self.duration

    def update_mode(self, new_data):
        current_gear = self.speed_levels.index(self.mode)

        # STATE 1: WAITING FOR FIRST PEAK
        if not self.is_collecting:
            if np.max(new_data) > self.trigger_threshold:
                # Signal spiked! Start collecting.
                self.is_collecting = True
                self.collection_start_time = time.time()
                self.event_buffer = np.copy(new_data)
            return self.mode

        # STATE 2: COLLECTING DATA FOR 1 SECONDS
        else:
            self.event_buffer = np.concatenate((self.event_buffer, new_data))

            # Snappy 0.8-second window to catch a double-flex
            if (time.time() - self.collection_start_time) >= 1:
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

            # Print ONLY if the mode actually changed
            if self.mode != self.previous_mode:
                print(f"--> GEAR SHIFT: Mode is now {self.mode}")
                self.previous_mode = self.mode

            return self.mode

    def convert_output(self, output):

        return output


# --- MAIN TESTING SCRIPT ---
if __name__ == "__main__":
    mic_out = True
    my_emg = EMG(port='/dev/cu.usbmodem101', baud=1000000)

    while True:
        if not mic_out:
            break

        try:
            ye, duration = my_emg.get_emg_data()
            my_emg.update_mode(ye)

            # Real-time status bar (overwrites itself so it doesn't cause lag)
            if not my_emg.is_collecting:
                print(f"Live Max Signal: {np.max(ye):.3f} | Current Mode: {my_emg.mode}    ", end='\r')

        except KeyboardInterrupt:
            print("\nProgram stopped.")
            break