# mic_class.py
import numpy as np
import scipy.signal as sig


class Mic:
    def __init__(self, fs=16_000, samples=16_000, model=None):
        self.fs = fs
        self.samples = samples
        self.model = model
        self.output = None
        self.mic_state = False

        # This will hold incoming audio chunks until we have 16,000 samples
        self.audio_buffer = []

    def update_mic(self, new_data_list):
        if not new_data_list:
            return

        self.audio_buffer.extend(new_data_list)

        if len(self.audio_buffer) >= self.samples:
            chunk_to_process = self.audio_buffer[:self.samples]
            self.audio_buffer = self.audio_buffer[self.samples:]

            data_array = np.array(chunk_to_process, dtype=np.float32)
            data_array = data_array / 32768.0

            # --- NEW: VOLUME GATE ---
            # Check the maximum volume of this 1-second chunk
            max_volume = np.max(np.abs(data_array))

            # If the volume is lower than 10% of the max mic capability, it's just room noise
            if max_volume < 0.50:
                # Uncomment the print statement below to tune your threshold!
                # print(f"Quiet... (Volume: {max_volume:.3f})")
                return  # Skip the AI entirely

            # 4. Process and Predict (Only runs if someone is actually making noise)
            processed = self.pre_processing(data_array, fs=self.fs, samples=self.samples)
            self.predict(processed, fs=self.fs)
            self.signal_mic_change()

    def pre_processing(self, data, fs=16_000, samples=16_000):
        b, a = sig.butter(3, 6_000, 'low', fs=fs)
        y_filtered = sig.filtfilt(b, a, data)
        y_padded = np.pad(y_filtered, (0, samples - len(y_filtered)), 'constant')
        return y_padded

    def predict(self, data, fs=16_000):
        if self.model is None:
            return None

        labels = ['off', 'on', 'rest']

        f, t, Sxx = sig.spectrogram(data, fs=fs, window='hann', nperseg=512, noverlap=265)
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

        prediction_tensor = self.model(keras_input, training=False)
        prediction_array = prediction_tensor.numpy()[0]
        output_idx = np.argmax(prediction_array)
        confidence = prediction_array[output_idx]
        predicted_label = labels[output_idx]

        # --- NEW: CONFIDENCE THRESHOLD & STATE FILTERING ---
        # Only accept the AI's answer if it's over 75% confident
        if confidence > 0.75:
            # Only print it if it's a NEW state (stops it from spamming "ON, ON, ON")
            if self.output != predicted_label:
                print(f"\nMic Activated -> Command: {predicted_label.upper()} (Confidence: {confidence:.2f})")
                self.output = predicted_label
        else:
            # If you want to see when it gets confused, uncomment below
            # print(f"Ignoring low-confidence sound: {predicted_label} ({confidence:.2f})")
            pass

        return self.output

    def signal_mic_change(self):
        if self.output == 'on':
            self.mic_state = True
        elif self.output == 'off':
            self.mic_state = False