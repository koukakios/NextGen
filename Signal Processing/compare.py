import numpy as np
import scipy.signal as sig
import scipy.io.wavfile as wavfile
import matplotlib.pyplot as plt
import time

# Import your fixed Mic class
from Mic_processing import Mic


def get_spectrogram(audio, fs=16_000):
    """
    Exact replica of your training spectrogram math.
    """
    # 1. Filter
    b, a = sig.butter(3, 6_000, 'low', fs=fs)
    y_filtered = sig.filtfilt(b, a, audio)

    # 2. Spectrogram
    f, t, Sxx = sig.spectrogram(
        y_filtered, fs=fs, window='hann', nperseg=512, noverlap=265
    )

    # 3. Decibels & Normalize
    Sxx_db = 10 * np.log10(Sxx + 1e-10)
    min_val = np.min(Sxx_db)
    max_val = np.max(Sxx_db)
    Sxx_norm = (Sxx_db - min_val) / (max_val - min_val + 1e-8)

    # 4. Pad/Truncate to exactly (256, 64)
    out = np.zeros((256, 64), dtype=np.float32)
    h = min(Sxx_norm.shape[0], 256)
    w = min(Sxx_norm.shape[1], 64)
    out[:h, :w] = Sxx_norm[:h, :w]

    return out


if __name__ == "__main__":
    # --- 1. LOAD TRAINING DATA ---
    wav_file_path = 'archive/on/0a5636ca_nohash_0.wav'  # CHANGE THIS TO A REAL FILE!
    print(f"Loading training file: {wav_file_path}")
    fs_train, wav_data = wavfile.read(wav_file_path)

    # Normalize wav exactly like we do live
    wav_data = wav_data.astype(np.float32)
    if np.max(np.abs(wav_data)) > 1.0:
        wav_data = wav_data / 32768.0

    spec_train = get_spectrogram(wav_data, fs_train)

    # --- 2. RECORD ARDUINO DATA ---
    print("\nConnecting to Arduino...")
    my_mic = Mic(port='/dev/cu.usbmodem101', baud=1_000_000, samples=16_000)

    print("\nGet ready! Say the exact same word as the WAV file.")
    for i in range(3, 0, -1):
        print(f"Recording in {i}...")
        time.sleep(1)

    print(">>> SPEAK NOW! <<<")
    my_mic.get_mic_data(samples=16_000)
    print("Recording finished.")

    spec_arduino = get_spectrogram(my_mic.data, 16_000)

    # --- 3. PLOT SIDE-BY-SIDE ---
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Plot Training
    # origin='lower' puts low frequencies at the bottom, high at the top
    img1 = axes[0].imshow(spec_train, aspect='auto', origin='lower', cmap='viridis')
    axes[0].set_title('Training Data (.wav)')
    axes[0].set_xlabel('Time')
    axes[0].set_ylabel('Frequency')
    fig.colorbar(img1, ax=axes[0], fraction=0.046, pad=0.04)

    # Plot Arduino
    img2 = axes[1].imshow(spec_arduino, aspect='auto', origin='lower', cmap='viridis')
    axes[1].set_title('Arduino Live Data')
    axes[1].set_xlabel('Time')
    axes[1].set_ylabel('Frequency')
    fig.colorbar(img2, ax=axes[1], fraction=0.046, pad=0.04)

    plt.tight_layout()
    plt.show()