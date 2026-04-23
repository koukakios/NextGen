import os
import scipy.io as sio
import numpy as np
from pathlib import Path
from mne.filter import filter_data
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import TensorDataset, DataLoader
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import warnings

# Suppress MNE verbosity for cleaner console output
warnings.filterwarnings('ignore')


# ==========================================
# 1. DATA PROCESSING (Parsing & Filtering)
# ==========================================
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
        MNE expects data in (channels, samples) format.
        """
        signal_transposed = signal.T
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
                # Normalize codes (769-772 -> 1-4)
                label = event_code - 768 if event_code >= 769 else event_code

                if pos + window_samples <= signal.shape[0]:
                    epoch = signal[pos: pos + window_samples, :]
                    epochs.append(epoch)
                    labels.append(label)

        # PyTorch/MNE expect (Trials, Channels, Samples)
        epochs_array = np.array(epochs)
        epochs_array = np.transpose(epochs_array, (0, 2, 1))

        return epochs_array, np.array(labels)


# ==========================================
# 2. THE DEEP LEARNING ARCHITECTURE (EEGNet)
# ==========================================
class EEGNet(nn.Module):
    def __init__(self, n_channels=22, n_samples=1000, n_classes=4):
        super(EEGNet, self).__init__()

        # Block 1: Temporal Convolution (Learns frequency filters)
        self.block1 = nn.Sequential(
            nn.Conv2d(1, 8, (1, 125), padding='same', bias=False),
            nn.BatchNorm2d(8)
        )

        # Block 2: Depthwise Spatial Convolution (Learns spatial CSP-like filters)
        self.block2 = nn.Sequential(
            nn.Conv2d(8, 16, (n_channels, 1), groups=8, bias=False),
            nn.BatchNorm2d(16),
            nn.ELU(),
            nn.AvgPool2d((1, 4)),
            nn.Dropout(0.25)
        )

        # Block 3: Separable Convolution (Mixes features)
        self.block3 = nn.Sequential(
            nn.Conv2d(16, 16, (1, 16), padding='same', bias=False),
            nn.BatchNorm2d(16),
            nn.ELU(),
            nn.AvgPool2d((1, 8)),
            nn.Dropout(0.25)
        )

        # Calculate the dynamic size for the final linear layer
        out_size = self._calculate_out_size(n_channels, n_samples)

        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(out_size, n_classes)
        )

    def _calculate_out_size(self, channels, samples):
        # A dummy pass to calculate the flattened size for the dense layer
        x = torch.randn(1, 1, channels, samples)
        x = self.block1(x)
        x = self.block2(x)
        x = self.block3(x)
        return x.numel()

    def forward(self, x):
        x = self.block1(x)
        x = self.block2(x)
        x = self.block3(x)
        x = self.classifier(x)
        return x


# ==========================================
# 3. THE PYTORCH TRAINING PIPELINE
# ==========================================
class DeepLearningBCI:
    def __init__(self, epochs=150, batch_size=16, lr=0.001):
        # Automatically use GPU if available
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = EEGNet().to(self.device)
        self.criterion = nn.CrossEntropyLoss()
        self.optimizer = optim.Adam(self.model.parameters(), lr=lr)
        self.epochs = epochs
        self.batch_size = batch_size

    def train(self, X_train, y_train):
        # PyTorch Conv2D expects shape (Batch, Channels, Height, Width) -> (Batch, 1, 22, 1000)
        X_train = np.expand_dims(X_train, axis=1)

        # PyTorch CrossEntropyLoss expects 0-indexed labels (0, 1, 2, 3 instead of 1, 2, 3, 4)
        y_train = y_train - 1

        # Convert numpy arrays to PyTorch tensors
        X_tensor = torch.FloatTensor(X_train).to(self.device)
        y_tensor = torch.LongTensor(y_train).to(self.device)

        dataset = TensorDataset(X_tensor, y_tensor)
        dataloader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)

        self.model.train()
        for epoch in range(self.epochs):
            running_loss = 0.0
            for inputs, labels in dataloader:
                self.optimizer.zero_grad()
                outputs = self.model(inputs)
                loss = self.criterion(outputs, labels)
                loss.backward()
                self.optimizer.step()
                running_loss += loss.item()

            # Print progress every 50 epochs to keep the console clean
            if (epoch + 1) % 50 == 0:
                print(f"  Epoch [{epoch + 1}/{self.epochs}] - Loss: {running_loss / len(dataloader):.4f}")

    def evaluate(self, X_test, y_test):
        self.model.eval()

        X_test = np.expand_dims(X_test, axis=1)
        y_test = y_test - 1

        X_tensor = torch.FloatTensor(X_test).to(self.device)
        y_tensor = torch.LongTensor(y_test).to(self.device)

        with torch.no_grad():
            outputs = self.model(X_tensor)
            _, predicted = torch.max(outputs.data, 1)

            y_true = y_tensor.cpu().numpy()
            y_pred = predicted.cpu().numpy()

            acc = accuracy_score(y_true, y_pred)
            return acc


# ==========================================
# 4. MAIN EXECUTION LOOP
# ==========================================
if __name__ == "__main__":
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

            # 1. Open and filter the data
            raw_signal, event_positions, event_types, artifacts = processor.open_data()
            print("Applying 8-30 Hz bandpass filter...")
            filtered_signal = processor.apply_bandpass_filter(raw_signal)

            # 2. Epoch the data
            epochs, labels = processor.epoch_data(filtered_signal, event_positions, event_types, artifacts)
            print(f"Total clean trials extracted: {epochs.shape[0]}")

            # 3. Train/Test Split (80/20)
            X_train, X_test, y_train, y_test = train_test_split(
                epochs, labels, test_size=0.2, random_state=42, stratify=labels
            )

            # 4. Train and Evaluate PyTorch Model
            print("Training PyTorch EEGNet...")

            # Using 150 epochs as a solid baseline for EEGNet
            bci_model = DeepLearningBCI(epochs=150, batch_size=16)
            bci_model.train(X_train, y_train)

            acc = bci_model.evaluate(X_test, y_test)
            print(f"Accuracy: {acc * 100:.2f}%")

            results[file] = acc * 100

        except Exception as e:
            print(f"Failed to process {file}. Error: {e}")
            results[file] = "Failed"

    print("\n\n" + "*" * 30)
    print(" DEEP LEARNING ACCURACY SUMMARY")
    print("*" * 30)
    for subject, accuracy in results.items():
        if isinstance(accuracy, str):
            print(f"Subject {subject}: \t{accuracy}")
        else:
            print(f"Subject {subject}: \t{accuracy:.2f}%")