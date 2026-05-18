import argparse
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, messagebox

import serial


BAUD = 115200
SEND_PERIOD_MS = 50
AUTO_STATUS_PERIOD_MS = 1000

CMD_STOP = 0x00
CMD_MODE1_FORWARD = 0x01
CMD_MODE2_FORWARD = 0x02
CMD_MODE3_FORWARD = 0x03
CMD_RIGHT = 0x04
CMD_LEFT = 0x05
CMD_STATUS = 0x06
CMD_ESTOP = 0x07


class CanHoldButtonTester:
    def __init__(self, root, port, baud):
        self.root = root
        self.port = port
        self.baud = baud

        self.ser = serial.Serial(port, baudrate=baud, timeout=0.1)

        self.running = True
        self.active_cmd = None
        self.active_name = None

        self.rx_queue = queue.Queue()

        self.auto_status_var = tk.BooleanVar(value=True)

        self.stat_text_vars = {
            "connection": tk.StringVar(value="Connected"),
            "drive": tk.StringVar(value="Drive: ?"),
            "mode": tk.StringVar(value="Mode: ?"),
            "motion": tk.StringVar(value="Motion: ?"),
            "left": tk.StringVar(value="Left target: ?"),
            "right": tk.StringVar(value="Right target: ?"),
            "relay": tk.StringVar(value="Relay: ?"),
            "timeout": tk.StringVar(value="Timeout: ?"),
            "estop": tk.StringVar(value="E-stop: ?"),
            "can": tk.StringVar(value="CAN: ?"),
            "left_tel": tk.StringVar(value="Left VESC: ?"),
            "right_tel": tk.StringVar(value="Right VESC: ?"),
        }

        self.root.title("CAN Binary Hold-Button VESC Test")

        self.build_ui()

        self.reader_thread = threading.Thread(target=self.reader_loop, daemon=True)
        self.reader_thread.start()

        self.root.after(100, self.process_rx_queue)
        self.root.after(SEND_PERIOD_MS, self.send_active_command_loop)
        self.root.after(AUTO_STATUS_PERIOD_MS, self.auto_status_loop)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.log(f"[INFO] Connected to {self.port} at {self.baud}")
        self.log("[INFO] PC -> Arduino is USB Serial raw bytes.")
        self.log("[INFO] Arduino -> VESC is CAN bus.")
        self.log("[INFO] Hold a movement button to send command every 50 ms.")
        self.log("[INFO] Releasing a movement button sends STOP burst.")
        self.log("[INFO] This sends RAW BYTES, not strings.")
        self.log("")

        self.send_byte(CMD_STATUS, "STATUS")

    def build_ui(self):
        top = tk.Frame(self.root)
        top.pack(padx=10, pady=10, fill="x")

        status_button = tk.Button(
            top,
            text="STATUS\n0x06",
            width=18,
            height=2,
            command=lambda: self.send_byte(CMD_STATUS, "STATUS"),
        )
        status_button.grid(row=0, column=0, padx=5, pady=5)

        stop_button = tk.Button(
            top,
            text="STOP\n0x00",
            width=18,
            height=2,
            bg="orange",
            command=self.stop_now,
        )
        stop_button.grid(row=0, column=1, padx=5, pady=5)

        estop_button = tk.Button(
            top,
            text="ESTOP\n0x07",
            width=18,
            height=2,
            bg="red",
            fg="white",
            command=self.estop_now,
        )
        estop_button.grid(row=0, column=2, padx=5, pady=5)

        auto_status_check = tk.Checkbutton(
            top,
            text="Auto status every 1 s",
            variable=self.auto_status_var,
        )
        auto_status_check.grid(row=0, column=3, padx=10, pady=5)

        movement_frame = tk.LabelFrame(
            self.root,
            text="Hold button to move. Release sends STOP.",
        )
        movement_frame.pack(padx=10, pady=10)

        self.mode1_button = tk.Button(
            movement_frame,
            text="HOLD MODE 1 FORWARD\n0x01",
            width=24,
            height=4,
        )
        self.mode2_button = tk.Button(
            movement_frame,
            text="HOLD MODE 2 FORWARD\n0x02",
            width=24,
            height=4,
        )
        self.mode3_button = tk.Button(
            movement_frame,
            text="HOLD MODE 3 FORWARD\n0x03",
            width=24,
            height=4,
        )
        self.right_button = tk.Button(
            movement_frame,
            text="HOLD RIGHT\n0x04",
            width=24,
            height=4,
        )
        self.left_button = tk.Button(
            movement_frame,
            text="HOLD LEFT\n0x05",
            width=24,
            height=4,
        )

        self.mode1_button.grid(row=0, column=1, padx=6, pady=6)
        self.left_button.grid(row=1, column=0, padx=6, pady=6)
        self.right_button.grid(row=1, column=2, padx=6, pady=6)
        self.mode2_button.grid(row=2, column=1, padx=6, pady=6)
        self.mode3_button.grid(row=3, column=1, padx=6, pady=6)

        self.bind_hold_button(self.mode1_button, CMD_MODE1_FORWARD, "MODE1_FORWARD")
        self.bind_hold_button(self.mode2_button, CMD_MODE2_FORWARD, "MODE2_FORWARD")
        self.bind_hold_button(self.mode3_button, CMD_MODE3_FORWARD, "MODE3_FORWARD")
        self.bind_hold_button(self.right_button, CMD_RIGHT, "RIGHT")
        self.bind_hold_button(self.left_button, CMD_LEFT, "LEFT")

        status_frame = tk.LabelFrame(self.root, text="Decoded Arduino / CAN status")
        status_frame.pack(padx=10, pady=5, fill="x")

        labels = [
            "connection",
            "drive",
            "mode",
            "motion",
            "left",
            "right",
            "relay",
            "timeout",
            "estop",
            "can",
            "left_tel",
            "right_tel",
        ]

        for index, key in enumerate(labels):
            tk.Label(
                status_frame,
                textvariable=self.stat_text_vars[key],
                anchor="w",
                width=42,
            ).grid(row=index // 2, column=index % 2, sticky="w", padx=8, pady=2)

        keyboard_frame = tk.LabelFrame(self.root, text="Keyboard shortcuts")
        keyboard_frame.pack(padx=10, pady=5, fill="x")

        tk.Label(
            keyboard_frame,
            text=(
                "Hold keys: 1 = mode1 forward, 2 = mode2 forward, "
                "3 = mode3 forward, A = left, D = right, Space = stop, E = estop"
            ),
        ).pack(padx=10, pady=5)

        self.root.bind("<KeyPress-1>", lambda event: self.start_command(CMD_MODE1_FORWARD, "MODE1_FORWARD"))
        self.root.bind("<KeyRelease-1>", lambda event: self.release_command(CMD_MODE1_FORWARD, "MODE1_FORWARD"))

        self.root.bind("<KeyPress-2>", lambda event: self.start_command(CMD_MODE2_FORWARD, "MODE2_FORWARD"))
        self.root.bind("<KeyRelease-2>", lambda event: self.release_command(CMD_MODE2_FORWARD, "MODE2_FORWARD"))

        self.root.bind("<KeyPress-3>", lambda event: self.start_command(CMD_MODE3_FORWARD, "MODE3_FORWARD"))
        self.root.bind("<KeyRelease-3>", lambda event: self.release_command(CMD_MODE3_FORWARD, "MODE3_FORWARD"))

        self.root.bind("<KeyPress-a>", lambda event: self.start_command(CMD_LEFT, "LEFT"))
        self.root.bind("<KeyRelease-a>", lambda event: self.release_command(CMD_LEFT, "LEFT"))

        self.root.bind("<KeyPress-A>", lambda event: self.start_command(CMD_LEFT, "LEFT"))
        self.root.bind("<KeyRelease-A>", lambda event: self.release_command(CMD_LEFT, "LEFT"))

        self.root.bind("<KeyPress-d>", lambda event: self.start_command(CMD_RIGHT, "RIGHT"))
        self.root.bind("<KeyRelease-d>", lambda event: self.release_command(CMD_RIGHT, "RIGHT"))

        self.root.bind("<KeyPress-D>", lambda event: self.start_command(CMD_RIGHT, "RIGHT"))
        self.root.bind("<KeyRelease-D>", lambda event: self.release_command(CMD_RIGHT, "RIGHT"))

        self.root.bind("<space>", lambda event: self.stop_now())
        self.root.bind("<KeyPress-e>", lambda event: self.estop_now())
        self.root.bind("<KeyPress-E>", lambda event: self.estop_now())

        self.output = scrolledtext.ScrolledText(self.root, width=125, height=28)
        self.output.pack(padx=10, pady=10, fill="both", expand=True)

    def bind_hold_button(self, button, cmd, name):
        button.bind("<ButtonPress-1>", lambda event: self.start_command(cmd, name))
        button.bind("<ButtonRelease-1>", lambda event: self.release_command(cmd, name))
        button.bind("<Leave>", lambda event: self.release_command(cmd, name))

    def log(self, message):
        self.output.insert(tk.END, message + "\n")
        self.output.see(tk.END)

    def reader_loop(self):
        buffer = ""

        while self.running:
            try:
                data = self.ser.read(self.ser.in_waiting or 1)

                if not data:
                    continue

                text = data.decode(errors="replace")
                buffer += text

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()

                    if line:
                        self.rx_queue.put(line)

            except Exception as e:
                self.rx_queue.put(f"[READER ERROR] {e}")
                break

    def process_rx_queue(self):
        while not self.rx_queue.empty():
            line = self.rx_queue.get()
            self.log(f"RX: {line}")
            self.handle_rx_line(line)

        if self.running:
            self.root.after(100, self.process_rx_queue)

    def handle_rx_line(self, line):
        if "DRY=1" in line:
            self.log("[WARNING] Arduino reports DRY=1. CAN/VESC commands are dry-run only.")

        if "DRY=0" in line:
            self.log("[OK] Arduino reports DRY=0. Real CAN/VESC output is active.")

        if "CAN_BEGIN_FAILED" in line:
            self.log("[ERROR] Arduino CAN initialization failed. Check GIGA CAN library, pins, transceiver, and bitrate.")
            self.stat_text_vars["can"].set("CAN: begin failed")

        if "CAN_TX_FAIL" in line:
            self.log("[ERROR] Arduino could not transmit a CAN frame. Check transceiver, wiring, termination, and bus power.")

        if "PC_TIMEOUT_500MS" in line:
            self.log("[INFO] Arduino timeout triggered and stopped drive.")

        if "BIN_ESTOP" in line or "BIN,ESTOP" in line:
            self.log("[INFO] Emergency stop acknowledged by Arduino.")

        if line.startswith("<STAT,"):
            self.decode_status_line(line)

    def decode_status_line(self, line):
        fields = self.parse_angle_bracket_csv(line)

        en = fields.get("EN", "?")
        mode = fields.get("MODE", "?")
        motion = fields.get("MOTION", "?")
        left = fields.get("L", "?")
        right = fields.get("R", "?")
        relay = fields.get("RELAY", "?")
        timeout = fields.get("TIMEOUT", "?")
        estop = fields.get("ESTOP", "?")

        can_bitrate = fields.get("CAN_BITRATE", "?")
        can_rx = fields.get("CAN_RX", "?")
        can_tx_fails = fields.get("CAN_TX_FAILS", "?")
        can_last = fields.get("CAN_LAST_TX_STATUS", "?")

        l_id = fields.get("L_ID", "?")
        r_id = fields.get("R_ID", "?")

        l_seen = fields.get("L_SEEN", "?")
        l_rpm = fields.get("L_RPM", "?")
        l_curr = fields.get("L_CURR", "?")
        l_duty = fields.get("L_DUTY_FB", "?")
        l_vin = fields.get("L_VIN", "?")
        l_age = fields.get("L_AGE_MS", "?")

        r_seen = fields.get("R_SEEN", "?")
        r_rpm = fields.get("R_RPM", "?")
        r_curr = fields.get("R_CURR", "?")
        r_duty = fields.get("R_DUTY_FB", "?")
        r_vin = fields.get("R_VIN", "?")
        r_age = fields.get("R_AGE_MS", "?")

        self.stat_text_vars["drive"].set(f"Drive: {'enabled' if en == '1' else 'disabled' if en == '0' else en}")
        self.stat_text_vars["mode"].set(f"Mode: {mode}")
        self.stat_text_vars["motion"].set(f"Motion: {motion}")
        self.stat_text_vars["left"].set(f"Left target: {left}  ID={l_id}")
        self.stat_text_vars["right"].set(f"Right target: {right}  ID={r_id}")
        self.stat_text_vars["relay"].set(f"Relay: {'active' if relay == '1' else 'off' if relay == '0' else relay}")
        self.stat_text_vars["timeout"].set(f"Timeout latch: {timeout}")
        self.stat_text_vars["estop"].set(f"E-stop latch: {estop}")
        self.stat_text_vars["can"].set(
            f"CAN: {can_bitrate} bps, RX={can_rx}, TX fails={can_tx_fails}, last={can_last}"
        )
        self.stat_text_vars["left_tel"].set(
            f"Left VESC: seen={l_seen}, rpm={l_rpm}, current={l_curr}A, duty={l_duty}, vin={l_vin}V, age={l_age}ms"
        )
        self.stat_text_vars["right_tel"].set(
            f"Right VESC: seen={r_seen}, rpm={r_rpm}, current={r_curr}A, duty={r_duty}, vin={r_vin}V, age={r_age}ms"
        )

    @staticmethod
    def parse_angle_bracket_csv(line):
        # Converts lines like:
        # <STAT,EN=0,MODE=NONE,CAN_RX=12,L_RPM=123>
        # into {"EN": "0", "MODE": "NONE", ...}
        clean = line.strip()
        clean = re.sub(r"^<|>$", "", clean)
        parts = clean.split(",")

        fields = {}
        for part in parts[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                fields[key.strip()] = value.strip()

        return fields

    def send_byte(self, value, name=None):
        try:
            self.ser.write(bytes([value]))
            self.ser.flush()

            if name:
                self.log(f"TX: {name}  byte=0x{value:02X}  binary={value:08b}")
            else:
                self.log(f"TX: byte=0x{value:02X}  binary={value:08b}")

        except Exception as e:
            self.log(f"[SERIAL ERROR] {e}")
            self.stat_text_vars["connection"].set("Connection: serial error")

    def start_command(self, cmd, name):
        if self.active_cmd == cmd:
            return

        self.active_cmd = cmd
        self.active_name = name

        self.log(f"[HOLD START] {name}")
        self.send_byte(cmd, name)

    def release_command(self, cmd, name):
        if self.active_cmd != cmd:
            return

        self.log(f"[HOLD RELEASE] {name}. Sending STOP.")
        self.active_cmd = None
        self.active_name = None

        self.send_stop_burst()

    def send_active_command_loop(self):
        if self.running and self.active_cmd is not None:
            self.send_byte(self.active_cmd, self.active_name)

        if self.running:
            self.root.after(SEND_PERIOD_MS, self.send_active_command_loop)

    def auto_status_loop(self):
        if self.running and self.auto_status_var.get():
            # Do not spam status while a movement command is being actively held.
            # Movement commands must keep repeating every 50 ms for safety.
            if self.active_cmd is None:
                self.send_byte(CMD_STATUS, "STATUS")

        if self.running:
            self.root.after(AUTO_STATUS_PERIOD_MS, self.auto_status_loop)

    def send_stop_burst(self):
        for _ in range(3):
            self.send_byte(CMD_STOP, "STOP")
            time.sleep(0.03)

    def stop_now(self):
        self.log("[STOP BUTTON] Sending STOP.")
        self.active_cmd = None
        self.active_name = None
        self.send_stop_burst()

    def estop_now(self):
        self.log("[ESTOP BUTTON] Sending STOP burst, then ESTOP.")
        self.active_cmd = None
        self.active_name = None

        self.send_stop_burst()
        self.send_byte(CMD_ESTOP, "ESTOP")

    def on_close(self):
        self.log("[CLOSE] Sending STOP and ESTOP before exit.")
        self.running = False

        try:
            self.active_cmd = None
            self.active_name = None

            self.send_stop_burst()
            time.sleep(0.05)
            self.send_byte(CMD_ESTOP, "ESTOP")
            time.sleep(0.05)

        except Exception:
            pass

        try:
            if self.ser.is_open:
                self.ser.close()
        except Exception:
            pass

        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM13", help="Serial port, default COM9")
    parser.add_argument("--baud", type=int, default=BAUD)
    args = parser.parse_args()

    print("======================================")
    print("CAN Binary Hold-Button VESC Test")
    print("======================================")
    print("PC -> Arduino: USB serial raw bytes")
    print("Arduino -> VESCs: CAN bus")
    print("Default port is COM9.")
    print()
    print("Command map:")
    print("  0x00 = STOP")
    print("  0x01 = MODE 1 FORWARD")
    print("  0x02 = MODE 2 FORWARD")
    print("  0x03 = MODE 3 FORWARD")
    print("  0x04 = RIGHT")
    print("  0x05 = LEFT")
    print("  0x06 = STATUS")
    print("  0x07 = ESTOP")
    print()

    try:
        root = tk.Tk()
        CanHoldButtonTester(root, args.port, args.baud)
        root.mainloop()
    except serial.SerialException as e:
        message = f"Could not open serial port {args.port}:\n\n{e}"
        print(message)
        try:
            messagebox.showerror("Serial port error", message)
        except Exception:
            pass


if __name__ == "__main__":
    main()
