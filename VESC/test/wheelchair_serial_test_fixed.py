import argparse
import sys
import threading
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("Missing library: pyserial")
    print("Install it with: pip install pyserial")
    sys.exit(1)

# CHANGE ONLY THIS LINE IF YOUR ARDUINO IS ON ANOTHER PORT
DEFAULT_PORT = "COM9"

COMMAND_NAMES = {
    0: "STOP",
    1: "FORWARD SLOW",
    2: "FORWARD MEDIUM",
    3: "FORWARD FAST",
    4: "RIGHT",
    5: "LEFT",
    6: "STATUS",
    7: "EMERGENCY STOP",
}

MOVEMENT_COMMANDS = {1, 2, 3, 4, 5}


def list_available_ports() -> None:
    ports = list(list_ports.comports())

    if not ports:
        print("No serial ports found.")
        return

    print("Available serial ports:")
    for port in ports:
        print(f"  {port.device:15} {port.description}")


def read_from_arduino(ser: serial.Serial, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            line = ser.readline()
            if line:
                text = line.decode(errors="replace").strip()
                if text:
                    print(f"[arduino] {text}")
        except serial.SerialException:
            break


def send_command(ser: serial.Serial, command: int, use_raw_bytes: bool = True) -> None:
    if command not in COMMAND_NAMES:
        raise ValueError("Command must be from 0 to 7.")

    if use_raw_bytes:
        ser.write(bytes([command]))
    else:
        ser.write(str(command).encode("ascii"))

    ser.flush()
    print(f"[pc] sent {command}: {COMMAND_NAMES[command]}")


def hold_command(
    ser: serial.Serial,
    command: int,
    seconds: float,
    interval: float,
    use_raw_bytes: bool,
) -> None:
    """Repeat movement commands because Arduino stops after 500 ms without input."""
    if command not in COMMAND_NAMES:
        print("Invalid command. Use 0 to 7.")
        return

    if command not in MOVEMENT_COMMANDS:
        send_command(ser, command, use_raw_bytes)
        return

    print(f"[pc] holding {COMMAND_NAMES[command]} for {seconds:.2f} seconds")

    end_time = time.time() + seconds
    while time.time() < end_time:
        send_command(ser, command, use_raw_bytes)
        time.sleep(interval)

    send_command(ser, 0, use_raw_bytes)
    print("[pc] auto-stop after movement")


def run_demo(ser: serial.Serial, interval: float, use_raw_bytes: bool) -> None:
    sequence = [
        (6, 0.0),   # status
        (1, 2.0),   # forward slow
        (0, 0.0),   # stop
        (4, 1.0),   # right
        (0, 0.0),   # stop
        (5, 1.0),   # left
        (0, 0.0),   # stop
        (7, 0.0),   # emergency stop
    ]

    print("[pc] starting demo sequence")
    for command, seconds in sequence:
        hold_command(ser, command, seconds, interval, use_raw_bytes)
        time.sleep(1.0)

    print("[pc] demo finished")


def interactive_mode(ser: serial.Serial, interval: float, use_raw_bytes: bool) -> None:
    print()
    print("Interactive mode")
    print("Commands:")
    print("  0 = stop")
    print("  1 = forward slow")
    print("  2 = forward medium")
    print("  3 = forward fast")
    print("  4 = right")
    print("  5 = left")
    print("  6 = status")
    print("  7 = emergency stop")
    print()
    print("Type for example:")
    print("  1       -> forward slow for 1 second, then stop")
    print("  1 2.5   -> forward slow for 2.5 seconds, then stop")
    print("  4 0.5   -> right for 0.5 seconds, then stop")
    print("  q       -> quit")
    print()

    while True:
        user_input = input("command> ").strip().lower()

        if user_input in {"q", "quit", "exit"}:
            send_command(ser, 0, use_raw_bytes)
            print("[pc] stopped and closed")
            return

        if not user_input:
            continue

        parts = user_input.split()

        try:
            command = int(parts[0])
        except ValueError:
            print("Invalid input. Use command 0 to 7, or q to quit.")
            continue

        if command not in COMMAND_NAMES:
            print("Invalid command. Use 0 to 7.")
            continue

        seconds = 1.0
        if len(parts) >= 2:
            try:
                seconds = float(parts[1])
            except ValueError:
                print("Invalid duration.")
                continue

        if seconds < 0:
            print("Duration must be positive.")
            continue

        hold_command(ser, command, seconds, interval, use_raw_bytes)


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Arduino wheelchair serial commands.")
    parser.add_argument(
        "--port",
        default=DEFAULT_PORT,
        help=f"Serial port. Default: {DEFAULT_PORT}",
    )
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate. Default: 115200")
    parser.add_argument("--list", action="store_true", help="List available serial ports and exit")
    parser.add_argument("--demo", action="store_true", help="Run automatic test sequence")
    parser.add_argument(
        "--ascii",
        action="store_true",
        help="Send ASCII characters '0'..'7' instead of raw bytes 0x00..0x07",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.20,
        help="Repeat interval for movement commands. Must be below Arduino timeout. Default: 0.20 s",
    )

    args = parser.parse_args()

    if args.list:
        list_available_ports()
        return 0

    if args.interval >= 0.50:
        print("Warning: interval should be below 0.50 s because Arduino timeout is 500 ms.")

    use_raw_bytes = not args.ascii

    print(f"[pc] opening {args.port} at {args.baud} baud")
    print(f"[pc] mode: {'raw bytes' if use_raw_bytes else 'ASCII characters'}")

    stop_event = threading.Event()
    ser = None

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.1)
        with ser:
            # Many Arduino boards reset when the serial port opens.
            time.sleep(2.0)

            reader = threading.Thread(
                target=read_from_arduino,
                args=(ser, stop_event),
                daemon=True,
            )
            reader.start()

            send_command(ser, 0, use_raw_bytes)

            if args.demo:
                run_demo(ser, args.interval, use_raw_bytes)
            else:
                interactive_mode(ser, args.interval, use_raw_bytes)

            send_command(ser, 0, use_raw_bytes)

    except serial.SerialException as error:
        print(f"Serial error: {error}")
        return 1
    except KeyboardInterrupt:
        print("\n[pc] keyboard interrupt")
        try:
            if ser is not None and ser.is_open:
                send_command(ser, 0, use_raw_bytes)
        except Exception:
            pass
        return 1
    finally:
        stop_event.set()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
