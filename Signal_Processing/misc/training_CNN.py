import tensorflow as tf
import scipy as scp
import sklearn.model_selection
from sklearn.metrics import classification_report
from sklearn.preprocessing import LabelEncoder
from pathlib import Path
from scipy.io import wavfile
import numpy as np
import random
from collections import defaultdict
import scipy.signal as sig

# preparing the data
path = Path('archive')


def prep_data(path, samples_per_class=8000):  # Increased target to force oversampling
    data_path = Path(path)
    target_labels = {'on', 'off'}

    file_paths_by_class = defaultdict(list)

    if not data_path.exists():
        print(f"Directory {data_path} not found!")
        return [], np.array([])

    for folder in data_path.iterdir():
        if not folder.is_dir():
            continue

        label = folder.name
        new_label = label if label in target_labels else 'rest'
        wav_files = list(folder.glob('*.wav'))
        file_paths_by_class[new_label].extend(wav_files)

    all_data = []
    all_labels = []

    for label, file_paths in file_paths_by_class.items():
        random.shuffle(file_paths)

        if len(file_paths) < samples_per_class:
            print(f"Oversampling '{label}' from {len(file_paths)} to {samples_per_class}")
            multiplier = (samples_per_class // len(file_paths)) + 1
            selected_paths = (file_paths * multiplier)[:samples_per_class]
        else:
            selected_paths = file_paths[:samples_per_class]

        print(f"Loading {len(selected_paths)} files for class '{label}'...")

        for wav_file in selected_paths:
            try:
                fs, audio = wavfile.read(wav_file)
                if np.issubdtype(audio.dtype, np.integer):
                    audio = audio.astype(np.float32) / np.iinfo(audio.dtype).max
                else:
                    audio = audio.astype(np.float32)

                if audio.ndim > 1:
                    audio = audio[:, 0]

                all_data.append(audio)
                all_labels.append(label)
            except Exception as e:
                print(f"Skipping {wav_file}: {e}")

    return all_data, np.array(all_labels)


def make_spec(audio, fs=16000):
    # Filtering
    b, a = sig.butter(3, 6_000, 'low', fs=16_000)
    y_filtered = sig.filtfilt(b, a, audio)  # filters forwards and backwards for near linear phase
    f, t, Sxx = scp.signal.spectrogram(
        y_filtered, fs=fs, window='hann', nperseg=512, noverlap=265
    )
    # 1. Convert to Decibels (dB) - standard for audio processing
    Sxx_db = 10 * np.log10(Sxx + 1e-10)

    # 2. Normalize values to be strictly between 0 and 1
    min_val = np.min(Sxx_db)
    max_val = np.max(Sxx_db)

    # Prevent division by zero just in case of pure silence
    Sxx_norm = (Sxx_db - min_val) / (max_val - min_val + 1e-8)

    return Sxx_norm

def pad_or_truncate(spec, target_shape=(256, 64)): # <--- THIS MUST BE 64 HERE TOO!
    out = np.zeros(target_shape, dtype=np.float32)
    h = min(spec.shape[0], target_shape[0])
    w = min(spec.shape[1], target_shape[1])
    out[:h, :w] = spec[:h, :w]
    return out

def build_spectrograms(audio_list, target_shape=(256, 256)):
    specs = []
    for audio in audio_list:
        spec = make_spec(audio)
        spec = pad_or_truncate(spec, target_shape)
        specs.append(spec)
    return np.array(specs)


def CNN_model(input_shape=(256, 64, 1), num_classes=3):
    model = tf.keras.models.Sequential()
    model.add(tf.keras.layers.Input(shape=input_shape))
    model.add(tf.keras.layers.Conv2D(32, kernel_size=(3, 3), activation='relu'))
    model.add(tf.keras.layers.MaxPooling2D(pool_size=(2, 2)))

    # Adding a second Conv block helps extract better audio features
    model.add(tf.keras.layers.Conv2D(64, kernel_size=(3, 3), activation='relu'))
    model.add(tf.keras.layers.MaxPooling2D(pool_size=(2, 2)))

    model.add(tf.keras.layers.Flatten())
    model.add(tf.keras.layers.Dense(128, activation='relu'))

    # DROPOUT LAYER: Crucial for preventing overfitting on duplicated data
    model.add(tf.keras.layers.Dropout(0.5))

    model.add(tf.keras.layers.Dense(num_classes, activation='softmax'))

    model.compile(
        optimizer='adam',
        loss='sparse_categorical_crossentropy',
        metrics=['accuracy']
    )
    return model


if __name__ == "__main__":
    # Increased to 3000 to force the duplication you requested
    audio_list, labels = prep_data(path, samples_per_class=8000)
    print(f"Loaded {len(audio_list)} audio files.")

    target_shape = (256, 64)
    spectrograms = build_spectrograms(audio_list, target_shape=target_shape)
    spectrograms = spectrograms[..., np.newaxis]

    le = LabelEncoder()
    labels_encoded = le.fit_transform(labels)
    print(f"Classes: {list(le.classes_)}")

    X_train, X_val, Y_train, Y_val = sklearn.model_selection.train_test_split(
        spectrograms, labels_encoded, test_size=0.2, random_state=42
    )

    model = CNN_model(input_shape=target_shape + (1,), num_classes=len(le.classes_))

    # Added class weights to ensure balanced learning if there's any slight imbalance left
    model.fit(X_train, Y_train, validation_data=(X_val, Y_val), epochs=10)
    model.save('model1.keras')

    # --- PRINTING METRICS (Recall, Precision, F1) ---
    print("\nEvaluating model on validation data...")
    # Get the raw probability predictions
    y_pred_probs = model.predict(X_val)
    print(y_pred_probs)
    # Convert probabilities to actual class index (0, 1, or 2)
    y_pred = np.argmax(y_pred_probs, axis=1)

    print("\n--- Classification Report ---")
    print(classification_report(Y_val, y_pred, target_names=le.classes_))
