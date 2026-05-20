import tensorflow as tf
import scipy as scp
import scipy.signal as sig
import sklearn.model_selection
from sklearn.metrics import classification_report
from sklearn.preprocessing import LabelEncoder
from pathlib import Path
from scipy.io import wavfile
import numpy as np
import random
from collections import defaultdict

# preparing the data
path = Path('archive')

def get_paths_and_labels(data_path):
    """Gathers file paths without loading audio yet, allowing us to safely split data first."""
    data_path = Path(data_path)
    target_labels = {'on', 'off'}

    file_paths = []
    labels = []

    if not data_path.exists():
        print(f"Directory {data_path} not found!")
        return np.array([]), np.array([])

    for folder in data_path.iterdir():
        if not folder.is_dir():
            continue

        label = folder.name
        new_label = label if label in target_labels else 'rest'
        wav_files = list(folder.glob('*.wav'))
        
        for wav_file in wav_files:
            file_paths.append(str(wav_file))
            labels.append(new_label)

    return np.array(file_paths), np.array(labels)

def oversample_train_data(X_paths, y_labels, samples_per_class=8000):
    """Oversamples only the training paths to prevent data leakage into validation."""
    oversampled_X = []
    oversampled_y = []
    
    unique_classes = np.unique(y_labels)
    
    for cls in unique_classes:
        cls_indices = np.where(y_labels == cls)[0]
        cls_paths = X_paths[cls_indices]
        
        current_count = len(cls_paths)
        
        if current_count < samples_per_class:
            print(f"Oversampling '{cls}' from {current_count} to {samples_per_class}")
            multiplier = (samples_per_class // current_count) + 1
            selected_paths = (list(cls_paths) * multiplier)[:samples_per_class]
        else:
            selected_paths = list(cls_paths[:samples_per_class])
            
        oversampled_X.extend(selected_paths)
        oversampled_y.extend([cls] * len(selected_paths))
        
    combined = list(zip(oversampled_X, oversampled_y))
    random.shuffle(combined)
    
    X_shuffled, y_shuffled = zip(*combined)
    return np.array(X_shuffled), np.array(y_shuffled)

def process_audio_file(wav_file, fs_target=16000, target_shape=(256, 64)):
    """Your exact original audio filtering and spectrogram logic."""
    try:
        fs, audio = wavfile.read(wav_file)
        if np.issubdtype(audio.dtype, np.integer):
            audio = audio.astype(np.float32) / np.iinfo(audio.dtype).max
        else:
            audio = audio.astype(np.float32)

        if audio.ndim > 1:
            audio = audio[:, 0]

        # Filtering
        b, a = sig.butter(3, 6_000, 'low', fs=16_000)
        y_filtered = sig.filtfilt(b, a, audio) 
        f, t, Sxx = scp.signal.spectrogram(
            y_filtered, fs=fs, window='hann', nperseg=512, noverlap=265
        )
        
        # Convert to Decibels (dB)
        Sxx_db = 10 * np.log10(Sxx + 1e-10)

        # Normalize values to be strictly between 0 and 1
        min_val = np.min(Sxx_db)
        max_val = np.max(Sxx_db)
        Sxx_norm = (Sxx_db - min_val) / (max_val - min_val + 1e-8)

        # Pad or truncate
        out = np.zeros(target_shape, dtype=np.float32)
        h = min(Sxx_norm.shape[0], target_shape[0])
        w = min(Sxx_norm.shape[1], target_shape[1])
        out[:h, :w] = Sxx_norm[:h, :w]
        
        return out
    except Exception as e:
        print(f"Skipping {wav_file}: {e}")
        return None

def build_spectrograms(file_paths, target_shape=(256, 64)):
    """Generates spectrograms from the list of paths."""
    specs = []
    valid_indices = [] # Keep track of which ones successfully loaded
    
    print(f"Building {len(file_paths)} spectrograms...")
    for i, path in enumerate(file_paths):
        spec = process_audio_file(path, target_shape=target_shape)
        if spec is not None:
            specs.append(spec)
            valid_indices.append(i)
            
    return np.array(specs), valid_indices

def CNN_model(input_shape=(256, 64, 1), num_classes=3):
    """Your exact original CNN architecture."""
    model = tf.keras.models.Sequential()
    model.add(tf.keras.layers.Input(shape=input_shape))
    model.add(tf.keras.layers.Conv2D(32, kernel_size=(3, 3), activation='relu'))
    model.add(tf.keras.layers.MaxPooling2D(pool_size=(2, 2)))

    model.add(tf.keras.layers.Conv2D(64, kernel_size=(3, 3), activation='relu'))
    model.add(tf.keras.layers.MaxPooling2D(pool_size=(2, 2)))

    model.add(tf.keras.layers.Flatten())
    model.add(tf.keras.layers.Dense(128, activation='relu'))
    model.add(tf.keras.layers.Dropout(0.5))
    model.add(tf.keras.layers.Dense(num_classes, activation='softmax'))

    model.compile(
        optimizer='adam',
        loss='sparse_categorical_crossentropy',
        metrics=['accuracy']
    )
    return model

if __name__ == "__main__":
    # 1. Gather all file paths and labels (No duplication yet)
    X_paths, y_labels = get_paths_and_labels(path)
    print(f"Found {len(X_paths)} unique audio files.")

    # 2. Encode labels
    le = LabelEncoder()
    y_encoded = le.fit_transform(y_labels)
    print(f"Classes: {list(le.classes_)}")

    # 3. Train/Test Split FIRST (This solves the data leakage)
    X_train_paths, X_val_paths, Y_train_labels, Y_val_labels = sklearn.model_selection.train_test_split(
        X_paths, y_encoded, test_size=0.2, random_state=42, stratify=y_encoded
    )

    # 4. Oversample ONLY the Training Data
    print("\n--- Applying Oversampling to Training Data ---")
    X_train_paths, Y_train_labels = oversample_train_data(X_train_paths, Y_train_labels, samples_per_class=8000)

    # 5. Build Spectrograms
    target_shape = (256, 64)
    print("\nProcessing Training Data:")
    X_train, valid_train_idx = build_spectrograms(X_train_paths, target_shape=target_shape)
    Y_train = Y_train_labels[valid_train_idx] # Drop labels if any files failed to load

    print("\nProcessing Validation Data:")
    X_val, valid_val_idx = build_spectrograms(X_val_paths, target_shape=target_shape)
    Y_val = Y_val_labels[valid_val_idx]

    # Add channel dimension
    X_train = X_train[..., np.newaxis]
    X_val = X_val[..., np.newaxis]

    # 6. Build and Train Model
    model = CNN_model(input_shape=target_shape + (1,), num_classes=len(le.classes_))
    model.summary()

    print("\nStarting Training...")
    model.fit(X_train, Y_train, validation_data=(X_val, Y_val), epochs=10, batch_size=32)
    model.save('model2.keras')

    # 7. Evaluation
    print("\nEvaluating model on validation data...")
    y_pred_probs = model.predict(X_val)
    y_pred = np.argmax(y_pred_probs, axis=1)

    print("\n--- Classification Report ---")
    print(classification_report(Y_val, y_pred, target_names=le.classes_))




# import os
# import random
# import numpy as np
# import librosa
# import tensorflow as tf
# from pathlib import Path
# from collections import defaultdict
# from sklearn.model_selection import train_test_split
# from sklearn.metrics import classification_report
# from sklearn.preprocessing import LabelEncoder
# from sklearn.utils.class_weight import compute_class_weight

# # --- CONFIGURATION ---
# DATA_PATH = Path('archive')
# SAMPLE_RATE = 16000
# DURATION = 1.0  # seconds
# SAMPLES_PER_TRACK = int(SAMPLE_RATE * DURATION)
# TARGET_LABELS = {'on', 'off'}

# def load_and_pad_audio(file_path):
#     """Loads audio and ensures it is exactly 1 second (16,000 samples) long."""
#     try:
#         # librosa automatically converts to mono and standardizes sample rate
#         audio, _ = librosa.load(file_path, sr=SAMPLE_RATE)
        
#         # Pad with zeros if too short, truncate if too long
#         if len(audio) < SAMPLES_PER_TRACK:
#             pad_length = SAMPLES_PER_TRACK - len(audio)
#             audio = np.pad(audio, (0, pad_length), mode='constant')
#         elif len(audio) > SAMPLES_PER_TRACK:
#             audio = audio[:SAMPLES_PER_TRACK]
            
#         return audio
#     except Exception as e:
#         print(f"Error loading {file_path}: {e}")
#         return None

# def prep_data(path):
#     """Loads file paths and labels without duplicating data."""
#     if not path.exists():
#         raise FileNotFoundError(f"Directory {path} not found!")

#     file_paths = []
#     labels = []

#     for folder in path.iterdir():
#         if not folder.is_dir():
#             continue

#         label = folder.name
#         # Group everything else into 'rest'
#         new_label = label if label in TARGET_LABELS else 'rest'
        
#         wav_files = list(folder.glob('*.wav'))
#         for wav_file in wav_files:
#             file_paths.append(str(wav_file))
#             labels.append(new_label)

#     return np.array(file_paths), np.array(labels)

# def make_mel_spectrograms(file_paths):
#     """Converts a list of audio file paths into normalized Mel-Spectrograms."""
#     specs = []
    
#     print(f"Extracting Mel-Spectrograms from {len(file_paths)} files... (This may take a moment)")
#     for path in file_paths:
#         audio = load_and_pad_audio(path)
#         if audio is None:
#             continue
            
#         # Create Mel-Spectrogram
#         # n_mels=64 and hop_length=256 yields a shape of (64, 63) for 16k samples
#         mel_spec = librosa.feature.melspectrogram(
#             y=audio, sr=SAMPLE_RATE, n_mels=64, hop_length=256, fmax=8000
#         )
        
#         # Convert power to Decibels (log scale)
#         mel_spec_db = librosa.power_to_db(mel_spec, ref=np.max)
        
#         # Normalize to 0-1 range for the neural network
#         min_val = mel_spec_db.min()
#         max_val = mel_spec_db.max()
#         if max_val - min_val > 0:
#             mel_spec_norm = (mel_spec_db - min_val) / (max_val - min_val)
#         else:
#             mel_spec_norm = mel_spec_db - min_val
            
#         specs.append(mel_spec_norm)
        
#     return np.array(specs)

# def build_cnn_model(input_shape, num_classes):
#     """Optimized CNN using GlobalAveragePooling to prevent parameter explosion."""
#     model = tf.keras.models.Sequential([
#         tf.keras.layers.Input(shape=input_shape),
        
#         # Block 1
#         tf.keras.layers.Conv2D(32, kernel_size=(3, 3), activation='relu', padding='same'),
#         tf.keras.layers.MaxPooling2D(pool_size=(2, 2)),
        
#         # Block 2
#         tf.keras.layers.Conv2D(64, kernel_size=(3, 3), activation='relu', padding='same'),
#         tf.keras.layers.MaxPooling2D(pool_size=(2, 2)),
        
#         # Block 3 (Further spatial reduction)
#         tf.keras.layers.Conv2D(128, kernel_size=(3, 3), activation='relu', padding='same'),
#         tf.keras.layers.MaxPooling2D(pool_size=(2, 2)),
        
#         # Collapse spatial dimensions cleanly
#         tf.keras.layers.GlobalAveragePooling2D(),
        
#         # Classifier
#         tf.keras.layers.Dense(128, activation='relu'),
#         tf.keras.layers.Dropout(0.5), # Crucial for regularization
#         tf.keras.layers.Dense(num_classes, activation='softmax')
#     ])

#     model.compile(
#         optimizer='adam',
#         loss='sparse_categorical_crossentropy',
#         metrics=['accuracy']
#     )
#     return model

# if __name__ == "__main__":
#     # 1. Load File Paths & Labels safely (NO DUPLICATION HERE)
#     X_paths, y_labels = prep_data(DATA_PATH)
#     print(f"Found {len(X_paths)} audio files.")

#     # 2. Encode Labels
#     le = LabelEncoder()
#     y_encoded = le.fit_transform(y_labels)
#     print(f"Classes found: {list(le.classes_)}")

#     # 3. Train/Test Split on PATHS (Prevents data leakage)
#     X_train_paths, X_val_paths, y_train, y_val = train_test_split(
#         X_paths, y_encoded, test_size=0.2, random_state=42, stratify=y_encoded
#     )

#     # 4. Convert Paths to Spectrograms
#     X_train = make_mel_spectrograms(X_train_paths)
#     X_val = make_mel_spectrograms(X_val_paths)

#     # Add channel dimension for CNN: (batch, height, width, channels)
#     X_train = X_train[..., np.newaxis]
#     X_val = X_val[..., np.newaxis]
    
#     print(f"Spectrogram shape: {X_train.shape[1:]}")

#     # 5. Handle Class Imbalance dynamically
#     # This replaces the need to duplicate files in your folders
#     class_weights = compute_class_weight(
#         class_weight='balanced', 
#         classes=np.unique(y_train), 
#         y=y_train
#     )
#     class_weight_dict = dict(enumerate(class_weights))
#     print(f"Computed Class Weights: {class_weight_dict}")

#     # 6. Build & Train Model
#     model = build_cnn_model(
#         input_shape=X_train.shape[1:], 
#         num_classes=len(le.classes_)
#     )
#     model.summary()

#     print("\nStarting Training...")
#     history = model.fit(
#         X_train, y_train, 
#         validation_data=(X_val, y_val), 
#         epochs=15, 
#         batch_size=32,
#         class_weight=class_weight_dict  # Forces model to pay attention to minority classes
#     )
    
#     model.save('optimized_audio_model.keras')

#     # 7. Evaluation & Metrics
#     print("\n--- Final Evaluation ---")
#     y_pred_probs = model.predict(X_val)
#     y_pred = np.argmax(y_pred_probs, axis=1)
    
#     print(classification_report(y_val, y_pred, target_names=le.classes_))