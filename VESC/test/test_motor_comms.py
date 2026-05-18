import argparse
import sys
import time


BAUD = 115200
SEND_PERIOD_S = 0.05

CMD_STOP = 0x00
CMD_MODE1_FORWARD = 0x01
CMD_MODE2_FORWARD = 0x02
CMD_MODE3_FORWARD = 0x03
CMD_RIGHT = 0x04
CMD_LEFT = 0x05
CMD_STATUS = 0x06
CMD_ESTOP = 0x07

MOVE_COMMANDS = {
    "mode1": (CMD_MODE1_FORWARD, "MODE1_FORWARD"),
    "mode2": (CMD_MODE2_FORWARD, "MODE2_FORWARD"),
    "mode3": (CMD_MODE3_FORWARD, "MODE3_FORWARD"),
    "right": (CMD_RIGHT, "RIGHT"),
    "left": (CMD_LEFT, "LEFT"),
}


def send_byte(ser, value, name):
    ser.write(bytes([value]))
    ser.flush()
    print(f"TX {name:14s} byte=0x{value:02X}")


def read_lines_for(ser, seconds):
    deadline = time.monotonic() + seconds
    lines = []

    while time.monotonic() < deadline:
        raw = ser.readline()
        if not raw:
            continue

        text = raw.decode("utf-8", errors="replace").strip()
        if text:
            lines.append(text)
            print(f"RX {text}")

    return lines


def send_stop_burst(ser):
    for _ in range(5):
        send_byte(ser, CMD_STOP, "STOP")
        time.sleep(0.03)


def parse_stat_fields(line):
    if not line.startswith("<STAT,") or not line.endswith(">"):
        return None

    fields = {}
    body = line[len("<STAT,"):-1]

    for part in body.split(","):
        if "=" not in part:
            continue

        key, value = part.split("=", 1)
        fields[key] = value

    return fields


def summarize_latest_status(lines):
    stats = [parse_stat_fields(line) for line in lines]
    stats = [stat for stat in stats if stat is not None]

    if not stats:
        print("No <STAT,...> line received.")
        return

    stat = stats[-1]
    print("")
    print("Latest Arduino status:")
    print(f"  EN={stat.get('EN', '?')} MODE={stat.get('MODE', '?')} MOTION={stat.get('MOTION', '?')}")
    print(f"  L={stat.get('L', '?')} R={stat.get('R', '?')} RELAY={stat.get('RELAY', '?')}")
    print(f"  CAN_READY={stat.get('CAN_READY', '?')} CAN_FAULT={stat.get('CAN_FAULT', '?')}")
    print(f"  CAN_RX={stat.get('CAN_RX', '?')} CAN_TX_FAILS={stat.get('CAN_TX_FAILS', '?')}")
    print(f"  L_SEEN={stat.get('L_SEEN', '?')} R_SEEN={stat.get('R_SEEN', '?')}")
    print(f"  L_RPM={stat.get('L_RPM', '?')} R_RPM={stat.get('R_RPM', '?')}")
    print(f"  L_VIN={stat.get('L_VIN', '?')} R_VIN={stat.get('R_VIN', '?')}")


def run_status_only(ser):
    print("Status-only check. Motors should not move.")
    send_stop_burst(ser)
    send_byte(ser, CMD_STATUS, "STATUS")
    lines = read_lines_for(ser, 1.0)
    summarize_latest_status(lines)


def run_move_check(ser, move_name, duration_s):
    command, label = MOVE_COMMANDS[move_name]

    print("")
    print(f"Movement comms check: {label} for {duration_s:.2f} s.")
    print("The script will send STOP burst afterwards even if the command loop exits.")
    print("")

    all_lines = []

    try:
        send_stop_burst(ser)
        all_lines += read_lines_for(ser, 0.2)

        start = time.monotonic()
        next_send = start

        while time.monotonic() - start < duration_s:
            now = time.monotonic()

            if now >= next_send:
                send_byte(ser, command, label)
                next_send += SEND_PERIOD_S

            all_lines += read_lines_for(ser, 0.01)

    finally:
        print("")
        print("Sending STOP burst.")
        send_stop_burst(ser)
        time.sleep(0.1)
        send_byte(ser, CMD_STATUS, "STATUS")
        all_lines += read_lines_for(ser, 1.0)

    summarize_latest_status(all_lines)


def main():
    parser = argparse.ArgumentParser(
        description="Raw-byte Arduino/VESC CAN comms check. Default is status-only."
    )
    parser.add_argument("--port", required=True, help="Serial port, for example COM11")
    parser.add_argument("--baud", type=int, default=BAUD)
    parser.add_argument(
        "--move",
        choices=sorted(MOVE_COMMANDS.keys()),
        help="Optional short motor command to send repeatedly.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.25,
        help="Movement duration in seconds. Default 0.25. Max 2.0.",
    )
    parser.add_argument(
        "--i-understand-wheels-lifted",
        action="store_true",
        help="Required for --move. Confirms wheels are lifted and area is clear.",
    )

    args = parser.parse_args()

    if args.duration <= 0 or args.duration > 2.0:
        print("Refusing duration outside 0 < duration <= 2.0 seconds.", file=sys.stderr)
        return 2

    if args.move and not args.i_understand_wheels_lifted:
        print(
            "Movement test refused. Re-run with --i-understand-wheels-lifted after lifting wheels.",
            file=sys.stderr,
        )
        return 2

    try:
        import serial
    except ImportError:
        print("Missing Python package: pyserial", file=sys.stderr)
        print("Install it with: python -m pip install pyserial", file=sys.stderr)
        return 2

    print(f"Opening {args.port} at {args.baud}.")

    with serial.Serial(args.port, baudrate=args.baud, timeout=0.05) as ser:
        print("Waiting for Arduino boot/serial output...")
        boot_lines = read_lines_for(ser, 2.0)

        if args.move:
            run_move_check(ser, args.move, args.duration)
        else:
            run_status_only(ser)

        if boot_lines:
            print("")
            print(f"Saw {len(boot_lines)} boot/early serial line(s).")

    print("Serial closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
