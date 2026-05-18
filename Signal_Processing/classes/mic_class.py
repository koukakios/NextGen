# mic_class.py
import time
import numpy as np
import scipy.signal as sig


class Mic:
    def __init__(self, fs=16_000, samples=16_000, model=None):
        self.fs = fs
        self.samples = samples
        self.model = model
        self.output = None
        self.mic_state = False

        # If a chunk gets louder than this, we assume a command started.
        # Tune this based on the real mic level: too low triggers on noise,
        # too high misses spoken commands.
        self.trigger_threshold = 0.08

        # While True, we are collecting one 1-second command window.
        self.is_recording = False

        # Holds the current command until it reaches self.samples.
        self.command_buffer = []

        # After one prediction, ignore audio briefly so one word is not
        # classified multiple times.
        self.cooldown_seconds = 0.5
        self.cooldown_until = 0

    def update_mic(self, new_data_list):
        if not new_data_list:
            return

        now = time.time()
        if now < self.cooldown_until:
            return

        data_array = np.array(new_data_list, dtype=np.float32)
        data_array = data_array / 32768.0
        max_volume = np.max(np.abs(data_array))

        # STATE 1: waiting for a loud enough sound to start a command.
        if not self.is_recording:
            if max_volume < self.trigger_threshold:
                return

            # A command probably started, so begin the 1-second capture.
            self.is_recording = True
            self.command_buffer = []

        # STATE 2: recording the command window.
        self.command_buffer.extend(new_data_list)

        # Wait until the command window has exactly 1 second of audio.
        if len(self.command_buffer) < self.samples:
            return

        chunk_to_process = self.command_buffer[:self.samples]

        # Reset before running the model so the next command starts fresh.
        self.is_recording = False
        self.command_buffer = []
        self.cooldown_until = now + self.cooldown_seconds

        data_array = np.array(chunk_to_process, dtype=np.float32)
        data_array = data_array / 32768.0

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
