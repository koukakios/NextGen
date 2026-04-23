import os
import scipy.io as sio
import numpy as np
from pathlib import Path
from mne.filter import filter_data
from mne.decoding import CSP
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
import warnings

# Suppress MNE verbosity for cleaner console output
warnings.filterwarnings('ignore')


class Processor:
    def __init__(self, file):
        base_path = Path(r"C:\Users\kkouk\desktop")
        file_name = file
        self.path = (base_path / file_name).with_suffix(".mat")

    def open_data(self):
        mat_dict = sio.loadmat(self.path)
        data = mat_dict['data']

        all_signals = []
        all_positions = []
        all_types = []
        all_artifacts = []

        current_sample_offset = 0

        # Loop through all blocks in the mat file
        for count in range(data.shape[1]):
            run_data = data[0, count]
            fields = run_data.dtype.names

            # Check if this block is an actual motor imagery run
            if fields is not None and 'trial' in fields and 'y' in fields:
                # Extract the signal (First 22 are EEG)
                signal = run_data['X'][0][0][:, :22]

                # Offset event positions, cast to int64 to prevent OverflowErrors
                positions = run_data['trial'][0][0].flatten().astype(np.int64) + current_sample_offset
                types = run_data['y'][0][0].flatten().astype(np.int64)
                artifacts = run_data['artifacts'][0][0].flatten().astype(np.int64)

                all_signals.append(signal)
                all_positions.append(positions)
                all_types.append(types)
                all_artifacts.append(artifacts)

                # Update the offset for the next run
                current_sample_offset += signal.shape[0]

        # Combine all runs into single continuous arrays
        continuous_signals = np.vstack(all_signals)
        event_positions = np.concatenate(all_positions)
        event_types = np.concatenate(all_types)
        artifacts = np.concatenate(all_artifacts)

        return continuous_signals, event_positions, event_types, artifacts

    def apply_bandpass_filter(self, signal, fs=250, l_freq=8.0, h_freq=30.0):
        """
        Applies a bandpass filter to isolate mu and beta motor imagery rhythms.
        MNE expects data in (channels, samples) format, so we transpose back and forth.
        """
        signal_transposed = signal.T
        # filter_data automatically applies a zero-phase FIR filter
        filtered_transposed = filter_data(
            signal_transposed,
            sfreq=fs,
            l_freq=l_freq,
            h_freq=h_freq,
            verbose=False
        )
        return filtered_transposed.T

    def epoch_data(self, signal, event_positions, event_types, artifacts, fs=250):
        """
        Epochs the continuous signal into discrete trials based on cue onset,
        while filtering out trials marked as artifacts.
        """
        valid_classes = [1, 2, 3, 4, 769, 770, 771, 772]
        window_samples = int(4.0 * fs)  # 4 seconds of motor imagery

        epochs = []
        labels = []

        for i, pos in enumerate(event_positions):
            # Skip artifacts
            if artifacts[i] == 1:
                continue

            event_code = event_types[i]

            if event_code in valid_classes:
                # Normalize codes
                label = event_code - 768 if event_code >= 769 else event_code

                if pos + window_samples <= signal.shape[0]:
                    epoch = signal[pos: pos + window_samples, :]
                    epochs.append(epoch)
                    labels.append(label)

        # Scikit-learn/MNE expect (Trials, Channels, Samples)
        epochs_array = np.array(epochs)
        epochs_array = np.transpose(epochs_array, (0, 2, 1))

        return epochs_array, np.array(labels)


class BCIClassifier:
    def __init__(self, n_components=4):
        self.csp = CSP(n_components=n_components, reg=None, log=True, norm_trace=False)
        self.log_reg = LogisticRegression(solver='lbfgs', max_iter=1000)

        self.pipeline = Pipeline([
            ('CSP', self.csp),
            ('LogisticRegression', self.log_reg)
        ])

    def train(self, X_train, y_train):
        self.pipeline.fit(X_train, y_train)

    def evaluate(self, X_test, y_test, print_report=False):
        y_pred = self.pipeline.predict(X_test)
        acc = accuracy_score(y_test, y_pred)

        if print_report:
            print(classification_report(y_test, y_pred, zero_division=0))

        return y_pred, acc


if __name__ == "__main__":
    # List of all training datasets
    training_files = [
        "A01T", "A02T", "A03T", "A04T", "A05T",
        "A06T", "A07T", "A08T", "A09T"
    ]

    results = {}

    for file in training_files:
        print(f"\n{'=' * 40}")
        print(f"PROCESSING SUBJECT: {file}")
        print(f"{'=' * 40}")

        try:
            processor = Processor(file)

            # 1. Open the data
            raw_signal, event_positions, event_types, artifacts = processor.open_data()

            # 2. Bandpass Filter (8-30 Hz) to isolate motor cortex signals
            print("Applying 8-30 Hz bandpass filter...")
            filtered_signal = processor.apply_bandpass_filter(raw_signal)

            # 3. Epoch the data
            epochs, labels = processor.epoch_data(filtered_signal, event_positions, event_types, artifacts)
            print(f"Total clean trials extracted: {epochs.shape[0]}")

            # 4. Train/Test Split (80/20)
            X_train, X_test, y_train, y_test = train_test_split(
                epochs, labels, test_size=0.2, random_state=42, stratify=labels
            )

            # 5. Train and Evaluate
            bci_model = BCIClassifier(n_components=4)
            bci_model.train(X_train, y_train)

            # Set print_report=True if you want the full breakdown for every subject
            _, acc = bci_model.evaluate(X_test, y_test, print_report=False)
            print(f"Accuracy: {acc * 100:.2f}%")

            results[file] = acc * 100

        except Exception as e:
            print(f"Failed to process {file}. Error: {e}")
            results[file] = "Failed"

    # Final Dashboard
    print("\n\n" + "*" * 30)
    print(" FINAL ACCURACY SUMMARY")
    print("*" * 30)
    for subject, accuracy in results.items():
        if isinstance(accuracy, str):
            print(f"Subject {subject}: \t{accuracy}")
        else:
            print(f"Subject {subject}: \t{accuracy:.2f}%")