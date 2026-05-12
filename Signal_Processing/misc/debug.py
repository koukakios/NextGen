import serial
import time

PORT = '/dev/cu.usbmodem101'
BAUD = 1_000_000

print(f"Connecting to {PORT}...")

try:
    # We added dsrdtr=True to force the Mac to open the data lines
    with serial.Serial(PORT, BAUD, timeout=1, dsrdtr=True) as ser:

        # Force DTR high to wake up the Arduino's serial transmitter
        ser.setDTR(True)
        time.sleep(1)
        ser.reset_input_buffer()

        print("Listening to raw USB data... (Press Ctrl+C to stop)")

        while True:
            bytes_waiting = ser.in_waiting
            if bytes_waiting > 0:
                raw_data = ser.read(bytes_waiting)
                print(raw_data)
            else:
                # Print a dot every 0.5s just so we know the script hasn't frozen
                print(".", end="", flush=True)
                time.sleep(0.5)

except Exception as e:
    print(f"\nCRITICAL ERROR: {e}")
except KeyboardInterrupt:
    print("\nTest Stopped.")