import numpy as np
import scipy.signal as sig
import matplotlib.pyplot as plt
import serial
import time


class ECG:
    def __init__(self, data = 0, mode=(0, 0, 0), port ='/dev/cu.usbmodem101', baud = 1000000, samples=100):
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

    def get_eeg_data(self, port, baud, samples=100):
        '''
        :param port: port that plugs the arduino into laptop
        :param baud: Baud rate of the arduino
        :param samples: number of samples you wish to get
        :return: array of data, duration of signal
        '''
        y_e = np.zeros(self.samples)
        idx = 0
        data = serial.Serial(port, baud)
        data.reset_input_buffer()
        start_time = time.time()
        while idx < samples:
            raw_data = data.readline()
            if raw_data.startswith(b"E:"):
                y_e[idx] = float(raw_data[2:].strip())
                idx += 1
            else:
                print("No data received")
                y_e[idx] = 0
                idx += 1
        self.duration = time.time() - start_time
        self.data = y_e
        return self.data, self.duration

    def update_mode(self, debug=False):
        '''
        Processes the ECG/EMG data to determine the wheelchair mode.
        1 Peak = Speed Up
        2 Peaks = Speed Down (if within max_time)
        '''
        # 1. Access the data using 'self', and normalize it safely
        norm_data = self.data / np.max(self.data)

        # 2. Find the peaks
        peaks, _ = sig.find_peaks(norm_data, height=0.3)

        if debug:
            x = np.linspace(0, self.duration, len(norm_data))
            plt.figure(figsize=(10, 4))
            plt.plot(x, norm_data, label="Signal")
            plt.plot(x[peaks], norm_data[peaks], 'ro', label="Peaks")
            plt.title(f"Peak Detection | Current Mode: {self.mode}")
            plt.legend()
            plt.grid(True)
            plt.show()


        max_time = 0.7 #time when we consider there to be two peaks
        num_peaks = len(peaks)
        current_gear = self.speed_levels.index(self.mode) #Seeing what gear we are in

        if num_peaks == 0:
            self.mode = self.speed_levels[current_gear]
            return self.mode
        elif num_peaks == 1:

            new_gear = min(current_gear + 1, len(self.speed_levels) - 1)
            self.mode = self.speed_levels[new_gear]
            return self.mode
        elif num_peaks == 2:
            time_per_sample = self.duration / len(self.data)
            time_between_peaks = (peaks[1] - peaks[0]) * time_per_sample
            if time_between_peaks < max_time: #there are two peaks and they are a double peak
                new_gear = max(current_gear - 1, 0) #want to go down in speed
                self.mode = self.speed_levels[new_gear]
            elif time_between_peaks >= max_time: #there are two peaks and they are a single peak
                new_gear = min(current_gear + 1, len(self.speed_levels) - 1) #want to go up in speed
                self.mode = self.speed_levels[new_gear]
            return self.mode
        else: #more than 2 peaks
            self.mode = self.speed_levels[0] # EMERGENCY STOP
            return self.mode