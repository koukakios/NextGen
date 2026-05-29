import serial
import time

PORT = "COM9"     
BAUD = 115200

SEND_INTERVAL = 0.20   # Must be less than Arduino timeout: 500 ms

COMMAND_NAMES = {
    0: "STOP",
    1: "FORWARD SLOW",
    2: "FORWARD MEDIUM",
    3: "FORWARD FAST",
    4: "RIGHT",
    5: "LEFT",
}

MOVEMENT_COMMANDS = {1, 2, 3, 4, 5}


def send_command(ser, command):
    ser.write(bytes([command]))
    ser.flush()
    print(f"Sent {command}: {COMMAND_NAMES[command]}")


def hold_command(ser, command, seconds):
    if command not in COMMAND_NAMES:
        print("Invalid command. Use 0 to 5.")
        return

    if command == 0:
        send_command(ser, 0)
        return

    end_time = time.time() + seconds

    print(f"Holding {COMMAND_NAMES[command]} for {seconds} seconds")

    while time.time() < end_time:
        send_command(ser, command)
        time.sleep(SEND_INTERVAL)

    send_command(ser, 0)
    print("Auto stop")


def main():
    print(f"Opening {PORT} at {BAUD} baud...")

    with serial.Serial(PORT, BAUD, timeout=1) as ser:
        time.sleep(2)  

        send_command(ser, 0)

        print()
        print("Commands:")
        print("0 = stop")
        print("1 = forward slow")
        print("2 = forward medium")
        print("3 = forward fast")
        print("4 = right")
        print("5 = left")
        print()
        print("Examples:")
        print("1 1     = forward slow for 1 second")
        print("4 0.5   = turn right for 0.5 seconds")
        print("0       = stop")
        print("q       = quit")
        print()

        while True:
            user_input = input("command> ").strip().lower()

            if user_input in ["q", "quit", "exit"]:
                send_command(ser, 0)
                print("Stopped and closed.")
                break

            if not user_input:
                continue

            parts = user_input.split()

            try:
                command = int(parts[0])
            except ValueError:
                print("Invalid command.")
                continue

            if command not in COMMAND_NAMES:
                print("Use command 0 to 5.")
                continue

            seconds = 1.0

            if len(parts) > 1:
                try:
                    seconds = float(parts[1])
                except ValueError:
                    print("Invalid time value.")
                    continue

            hold_command(ser, command, seconds)


if __name__ == "__main__":
    main()