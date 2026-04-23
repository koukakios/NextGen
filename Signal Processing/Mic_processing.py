import numpy as np
import scipy.signal as sig
import serial
import time

class Mic:
    def __init__(self, data = 0, fs = 16_000, port ='/dev/cu.usbmodem101', baud = 1_000_000, samples=32_000):
        self.fs = fs
        self.data = data
        self.port = port
        self.baud = baud
        self.samples = samples
        self.duration = None
        self.model = None
        self.cost = None

    def get_mic_data(self, port, baud, samples = 32_000):
        data = serial.Serial(port, baud)
        data.reset_input_buffer()
        start_time = time.time()
        raw_data = data.read(samples * 2)
        elapsed_time = time.time() - start_time

        # Convert binary string to 16-bit integers
        y_m = np.frombuffer(raw_data, dtype=np.int16)
        self.duration = elapsed_time
        self.data = y_m
        return self.data, self.duration

    def pre_processing(self, data, fs = 16_000, samples=32_000):
        '''
        :param data: input data that will be used to classify what the person said
        :param fs: sampling frequency
        :param samples: number of samples the data has
        :return: clean data that can be used for classification

        :goal:
        the goal of this function is to clean the data so that the chance of classifying it right is higher

        :pipeline:
        first resampling the data to 16,000 Hz, then filtering the data, then pad the data
        '''

        #Resampling
        fs_new = 16_000
        rate = int(fs / fs_new)
        y = data[::rate] #resampled the data to 16,000 Hz

        #Filtering
        b, a = sig.butter(3, 3_000,'low', fs = fs_new)
        y_filtered = sig.filtfilt(b, a, y) #filters forwards and backwards for near linear phase

        #Padding
        y_padded = np.pad(y_filtered, (0, samples - len(y_filtered)), 'constant') #pads it all to 32,000 samples
        return y_padded


    def model(self, x, w):
        '''
        :param x: input data array
        :param w: weight array
        :return: model for ML
        '''

        a = w[0:] + x.T @ w[1:]
        self.model = a.T
        return self.model

    def cost_function(self, y, a):
        cost = np.sum((a-y)**2)/y.size
        self.cost = cost
        return self.cost

    def ML(self, input_data, model):
