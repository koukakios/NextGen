import numpy as np
import scipy.signal as sig
import serial
import time
from tensorflow.keras.models import load_model


class Mic:
    def __init__(self, data=0, fs=16_000, port='/dev/cu.usbmodem101', baud=1_000_000, samples=32_000, model=None):
        self.fs = fs
        self.data = data
        self.port = port
        self.baud = baud
        self.samples = samples
        self.duration = None
        self.model = model
        self.output = None

        # Added a timeout so the script never hangs waiting for bytes
        self.serial_conn = serial.Serial(self.port, self.baud, timeout=2.0)
        self.serial_conn.reset_input_buffer()
        self.mic_state = False

    def get_mic_data(self, samples=16_000):
        self.serial_conn.reset_input_buffer()
        start_time = time.time()

        # Read exactly the number of bytes requested (16,000 samples = 32,000 bytes)
        raw_data = self.serial_conn.read(samples * 2)

        # Convert the raw bytes instantly into an array of 16-bit integers
        y_m = np.frombuffer(raw_data, dtype=np.int16)

        # --- FIX 2: Absolute Normalization ---
        data_array = y_m.astype(np.float32)
        if len(data_array) > 0:
            data_array = data_array / 32768.0

            # Failsafe if it disconnected early
        if len(data_array) < samples:
            print(f"Warning: Only got {len(data_array)} samples! Padding with silence.")
            data_array = np.pad(data_array, (0, samples - len(data_array)), 'constant')

        self.data = data_array
        self.duration = time.time() - start_time
        return self.data, self.duration


    def pre_processing(self, data, fs=16_000, samples=16_000):
        # Temporarily comment out the filter to see if the "ff" sound is restored
        b, a = sig.butter(3, 6_000, 'low', fs=fs)
        y_filtered = sig.filtfilt(b, a, data)
        # Padding
        y_padded = np.pad(y_filtered, (0, samples - len(y_filtered)), 'constant')
        return y_padded

    def predict(self, data, fs=16_000):
        if self.model is None:
            print("Error: Model not loaded.")
            return None

        labels = ['off', 'on', 'rest']

        f, t, Sxx = sig.spectrogram(
            data, fs=fs, window='hann', nperseg=512, noverlap=265
        )

        Sxx_db = 10 * np.log10(Sxx + 1e-10)
        min_val = np.min(Sxx_db)
        max_val = np.max(Sxx_db)
        Sxx_norm = (Sxx_db - min_val) / (max_val - min_val + 1e-8)

        target_shape = (256, 64)
        spec_padded = np.zeros(target_shape, dtype=np.float32)
        h = min(Sxx_norm.shape[0], target_shape[0])
        w = min(Sxx_norm.shape[1], target_shape[1])
        spec_padded[:h, :w] = Sxx_norm[:h, :w]

        keras_input = spec_padded.reshape(1, 256, 64, 1)

        # Direct callable to prevent memory leak!
        prediction_tensor = self.model(keras_input, training=False)

        # Extract the 1D array for this specific prediction to avoid the indexing crash
        prediction_array = prediction_tensor.numpy()[0]
        output_idx = np.argmax(prediction_array)
        confidence = prediction_array[output_idx]

        # Cleanly print what the AI thinks you said
        print(f"Confidence: {confidence:.2f} | Prediction: {labels[output_idx]}")

        self.output = labels[output_idx]
        return self.output

    def signal_mic_change(self):
        """
        Change output to a true or false value
        """
        if self.output == 'on':
            self.mic_state = True
        elif self.output == 'off':
            self.mic_state = False
        return


if __name__ == "__main__":
    from tensorflow.keras.models import load_model

    print("Initializing Mic System...")
    # Make sure baud=1_000_000 is set!
    my_mic = Mic(port='/dev/cu.usbmodem101', baud=1_000_000, samples=16_000)

    print("Loading Model...")
    my_mic.model = load_model('model1.keras')
    print("System Ready!")

    while True:
        try:
            # 1. Get exactly 1 second of perfectly timed audio
            my_mic.get_mic_data(samples=16_000)

            # 2. Process it through your Butterworth filter and padding
            processed_data = my_mic.pre_processing(my_mic.data, fs=16_000, samples=16_000)

            # 3. Ask the Keras model what it heard
            my_mic.predict(processed_data, fs=16_000)

        except KeyboardInterrupt:
            print("\nClosing connection...")
            my_mic.serial_conn.close()
            break