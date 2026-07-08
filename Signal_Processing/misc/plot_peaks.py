import numpy as np
import matplotlib.pyplot as plt
import scipy.signal as signal   
# from classes.emg_class import EMG
import serial
import time

def plot_data(data):
    data = np.array(data)
    # Extract the EMG signal for the first channel  
    # Find peaks in the EMG signal
    peaks, _ = signal.find_peaks(data, height=0.5)  # Adjust height threshold as needed
    time = np.arange(len(data))  # Time axis based on sample index
    # Plot the EMG signal and mark the peaks
    plt.figure(figsize=(10, 4))
    plt.plot(time, data, label='EMG Signal')
    plt.plot(time[peaks], data[peaks], "ro", label='Peaks')
    plt.title('EMG Signal with Detected Peaks')
    plt.xlabel('Sample Index')
    plt.ylabel('Amplitude')
    plt.legend()
    plt.grid()
    plt.show()

