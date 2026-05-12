import serial
import struct
import time

SERIAL_PORT = '/dev/cu.usbmodem101'
BAUD_RATE = 1_000_000

# We use a global buffer to hold onto half-received packets between function calls
serial_buffer = b''


def get_latest_data(ser):
    """
    Reads all currently available data in the serial buffer,
    parses complete packets, and returns them as two lists.
    """
    global serial_buffer
    emg_data = []
    mic_data = []

    # Grab whatever new bytes are sitting in the computer's serial buffer
    bytes_waiting = ser.in_waiting
    if bytes_waiting > 0:
        serial_buffer += ser.read(bytes_waiting)

    # Hunt for packets in our buffer
    i = 0
    while i < len(serial_buffer) - 1:

        # --- CHECK FOR EMG PACKET (Header: 0xAA 0xAA) ---
        if serial_buffer[i:i + 2] == b'\xAA\xAA':
            # Ensure we have the full 6 bytes (2 header + 4 float)
            if i + 6 <= len(serial_buffer):
                payload = serial_buffer[i + 2:i + 6]
                emg_value = struct.unpack('<f', payload)[0]
                emg_data.append(emg_value)
                i += 6  # Jump forward past this packet
                continue
            else:
                break  # We have half a packet; wait for next function call

        # --- CHECK FOR MIC PACKET (Header: 0xBB 0xBB) ---
        elif serial_buffer[i:i + 2] == b'\xBB\xBB':
            # Ensure we have at least 4 bytes (2 header + 2 length)
            if i + 4 <= len(serial_buffer):
                payload_length = struct.unpack('<H', serial_buffer[i + 2:i + 4])[0]

                # Ensure we have the full audio payload
                if i + 4 + payload_length <= len(serial_buffer):
                    audio_payload = serial_buffer[i + 4: i + 4 + payload_length]
                    num_samples = payload_length // 2

                    audio_samples = struct.unpack(f'<{num_samples}h', audio_payload)
                    mic_data.extend(audio_samples)

                    i += 4 + payload_length  # Jump forward past this packet
                    continue
                else:
                    break  # We have half a packet; wait for next function call

        # If it's not a header, move forward 1 byte to keep hunting
        i += 1

    # Chop off the data we just successfully parsed, keeping the leftovers for next time
    serial_buffer = serial_buffer[i:]

    # Simply return the two lists!
    return emg_data, mic_data


# ====================================================================
# Example of how to use it in your main script
# ====================================================================
if __name__ == '__main__':
    try:
        with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0) as ser:
            ser.reset_input_buffer()
            time.sleep(1)  # Let connection stabilize

            print("Listening for sensor data... (Press Ctrl+C to stop)")

            # This is your main program loop
            while True:
                # 1. Call the function and get your two variables
                latest_emg, latest_mic = get_latest_data(ser)

                # 2. Do whatever you want with the data!
                if latest_emg:
                    print(f"Received {len(latest_emg)} new EMG samples. Latest: {latest_emg[-1]:.2f} mV")

                if latest_mic:
                    print(f"Received {len(latest_mic)} new Microphone samples.")

                # Small delay so we aren't running the CPU at 100%
                time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nDisconnected.")