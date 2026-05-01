import serial
import struct
import time

# Configuration
PORT = 'COM3' 
BAUD = 115200

def send_single_packet(v: float, w:float):
    ser = None
    try:
        # 1. Attempt to open the connection
        ser = serial.Serial(PORT, BAUD, timeout=1)
        print(f"Successfully connected to {PORT}")
        
        # 2. Mandatory wait for Arduino Giga bootloader
        time.sleep(2)

        # 3. Pack and Write data
        packet = struct.pack('<BffB', 0x02, v, w, 0x03)
        ser.write(packet)
        print(f"Packet sent: {packet.hex()}")

    except serial.SerialException as e:
        # This triggers if the port is busy or not found
        print(f"Serial Error: Could not open {PORT}. Is it plugged in or used by another app?")
        print(f"Details: {e}")

    except Exception as e:
        # General catch-all for other errors
        print(f"An unexpected error occurred: {e}")

    finally:
        # 4. Always close the port if it was opened
        if ser is not None and ser.is_open:
            ser.close()
            print("Serial connection closed safely.")

if __name__ == "__main__":
    send_single_packet(1000.0, 10000.0)