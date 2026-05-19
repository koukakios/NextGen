import serial
import struct
import time

SERIAL_PORT = '/dev/cu.usbmodem101'
BAUD_RATE = 1_000_000

# We use a global buffer to hold onto half-received packets between function calls
serial_buffer = b''


def get_latest_data(ser):
    global serial_buffer
    emg_data, mic_data = [], []

    bytes_waiting = ser.in_waiting
    if bytes_waiting > 0:
        serial_buffer += ser.read(bytes_waiting)

    while True:
        # 1. Quickly find the next headers using optimized C-level search
        emg_idx = serial_buffer.find(b'\xAA\xAA')
        mic_idx = serial_buffer.find(b'\xBB\xBB')

        # 2. If NO headers are found, the buffer is just garbage noise. Wipe it.
        if emg_idx == -1 and mic_idx == -1:
            # Keep the very last byte just in case it's half of a new header
            serial_buffer = serial_buffer[-1:] if len(serial_buffer) > 0 else b''
            break

        # 3. Figure out which packet type comes first in the buffer
        valid_indices = [idx for idx in [emg_idx, mic_idx] if idx != -1]
        first_idx = min(valid_indices)

        # --- PROCESS EMG ---
        if first_idx == emg_idx:
            if first_idx + 6 <= len(serial_buffer):
                payload = serial_buffer[first_idx + 2 : first_idx + 6]
                emg_data.append(struct.unpack('<f', payload)[0])
                # Chop off the processed packet
                serial_buffer = serial_buffer[first_idx + 6:]
            else:
                # We have half a packet, wait for next function call
                serial_buffer = serial_buffer[first_idx:]
                break

        # --- PROCESS MIC ---
        elif first_idx == mic_idx:
            if first_idx + 4 <= len(serial_buffer):
                payload_length = struct.unpack('<H', serial_buffer[first_idx + 2 : first_idx + 4])[0]
                
                if first_idx + 4 + payload_length <= len(serial_buffer):
                    audio_payload = serial_buffer[first_idx + 4 : first_idx + 4 + payload_length]
                    num_samples = payload_length // 2
                    mic_data.extend(struct.unpack(f'<{num_samples}h', audio_payload))
                    # Chop off the processed packet
                    serial_buffer = serial_buffer[first_idx + 4 + payload_length:]
                else:
                    # We have half a packet, wait for next function call
                    serial_buffer = serial_buffer[first_idx:]
                    break
            else:
                # We only have half the header, wait for next function call
                serial_buffer = serial_buffer[first_idx:]
                break

    return emg_data, mic_data