import serial
import time

# Change this to your Arduino port
# Windows example: "COM5"
# Linux example: "/dev/ttyACM0"
# macOS example: "/dev/cu.usbmodemXXXX"
PORT = "COM9"

BAUDRATE = 115200
COMMAND_PERIOD = 0.05  # 50 ms

ser = serial.Serial(PORT, BAUDRATE, timeout=0.05)

# Arduino often resets when serial opens, so wait a bit
time.sleep(2)


def send_frame(frame: str):
    """
    Send one command frame to Arduino.
    Example: send_frame("<MOVE,F>")
    """
    ser.write(frame.encode("ascii"))
    ser.write(b"\n")


def read_replies():
    """
    Print all replies currently waiting from Arduino.
    """
    while ser.in_waiting > 0:
        line = ser.readline().decode(errors="ignore").strip()
        if line:
            print("Arduino:", line)


# 1. Enable drive
send_frame("<EN,1>")
time.sleep(0.05)
read_replies()

# 2. Select mode
# Choose one:
# <MODE,2>
# <MODE,5>
# <MODE,10>
send_frame("<MODE,10>")
time.sleep(0.05)
read_replies()

# 3. Keep sending movement command every 50 ms
try:
    while True:
        send_frame("<MOVE,F>")
        read_replies()
        time.sleep(COMMAND_PERIOD)

except KeyboardInterrupt:
    print("Stopping...")

    # Send stop a few times to make sure Arduino receives it
    for _ in range(5):
        send_frame("<MOVE,S>")
        time.sleep(0.05)

    send_frame("<EN,0>")
    time.sleep(0.1)
    read_replies()

    ser.close()
    print("Serial closed.")