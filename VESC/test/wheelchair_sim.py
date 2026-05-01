
"""
wheelchair_sim.py

Virtual wheelchair simulation for your Arduino/VESC protocol.

Protocol model:
    <EN,1>       enable drive
    <EN,0>       disable drive
    <MODE,2>     select 2 km/h speed mode
    <MODE,5>     select 5 km/h speed mode
    <MODE,10>    select 10 km/h speed mode
    <MOVE,F>     forward
    <MOVE,B>     reverse
    <MOVE,L>     left turn on spot
    <MOVE,R>     right turn on spot
    <MOVE,S>     stop

Safety model:
    After enable, valid commands must arrive at least every timeout_s.
    Your Arduino expects commands every 50 ms and times out after 500 ms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import math
import csv


# ============================================================
# 1) FILL IN YOUR REAL WHEELCHAIR VALUES HERE
# ============================================================

@dataclass
class WheelchairParams:
    # Geometry
    wheel_diameter_m: float = 0.30          # TODO: measure wheel diameter [m]
    wheel_base_m: float = 0.55              # TODO: distance between left/right wheel contact points [m]

    # Mass
    chair_mass_kg: float = 70.0             # TODO: chair mass [kg]
    rider_mass_kg: float = 70.0             # TODO: rider/test load mass [kg]

    # Drivetrain
    gear_ratio: float = 10.0                # TODO: motor revs per wheel rev
    motor_kv_rpm_per_volt: float = 170.0    # TODO: motor Kv [rpm/V]
    battery_voltage_v: float = 24.0         # TODO: battery voltage [V]
    motor_resistance_ohm: float = 0.20      # TODO: phase/equivalent resistance estimate [ohm], rough
    drivetrain_efficiency: float = 0.75     # TODO: 0.6-0.9 typical rough guess

    # VESC/safety limits
    max_motor_current_a: float = 10.0       # TODO: match conservative VESC Tool current limit
    max_battery_current_a: float = 8.0      # TODO: match battery/BMS/VESC limit
    max_duty: float = 0.30                  # TODO: software duty cap for testing, start low

    # Environment
    rolling_resistance_coeff: float = 0.03  # smooth floor ~0.01-0.03, carpet can be higher
    slope_deg: float = 0.0                  # positive = uphill while driving forward

    # Motion comfort/safety
    max_accel_mps2: float = 0.35            # gentle acceleration
    max_decel_mps2: float = 0.60            # braking/slowdown limit
    turn_speed_factor: float = 0.80         # turning speed relative to selected forward speed
    reverse_speed_factor: float = 0.70      # reverse speed relative to selected forward speed

    # Command protocol timing
    expected_command_period_s: float = 0.050
    timeout_s: float = 0.500

    # Simulation timing
    dt_s: float = 0.010                     # physics step, 10 ms

    # Your speed modes. Keep these matching your Arduino modes.
    speed_modes_kmh: Dict[int, float] = field(default_factory=lambda: {
        2: 2.0,
        5: 5.0,
        10: 10.0,
    })

    @property
    def total_mass_kg(self) -> float:
        return self.chair_mass_kg + self.rider_mass_kg

    @property
    def wheel_radius_m(self) -> float:
        return self.wheel_diameter_m / 2.0

    @property
    def motor_kt_nm_per_a(self) -> float:
        """
        Approx motor torque constant from Kv:
            Kt = 60 / (2*pi*Kv)
        Kv is rpm/V, Kt is Nm/A.
        This is approximate but useful for simulation.
        """
        return 60.0 / (2.0 * math.pi * self.motor_kv_rpm_per_volt)


# ============================================================
# 2) SIMULATION STATE
# ============================================================

@dataclass
class WheelchairState:
    # Pose on floor
    x_m: float = 0.0
    y_m: float = 0.0
    heading_rad: float = 0.0

    # Wheel linear speeds at ground contact
    left_speed_mps: float = 0.0
    right_speed_mps: float = 0.0

    # Targets from command layer
    target_left_speed_mps: float = 0.0
    target_right_speed_mps: float = 0.0

    # Protocol state
    drive_enabled: bool = False
    mode_selected: bool = False
    timeout_latched: bool = False
    selected_mode: Optional[int] = None
    motion: str = "S"

    # Timing
    last_valid_command_time_s: float = 0.0

    # Latest estimates
    left_motor_current_a: float = 0.0
    right_motor_current_a: float = 0.0
    battery_current_a: float = 0.0
    left_duty_estimate: float = 0.0
    right_duty_estimate: float = 0.0
    warning: str = ""


# ============================================================
# 3) SIMULATOR
# ============================================================

class WheelchairSim:
    def __init__(self, params: WheelchairParams):
        self.p = params
        self.s = WheelchairState()
        self.log: List[dict] = []

    # -----------------------------
    # Protocol receive function
    # -----------------------------

    def receive_frame(self, frame: str, t_s: float) -> str:
        """
        Feed one protocol frame into the simulator.
        Example:
            sim.receive_frame("<EN,1>", t)
            sim.receive_frame("<MODE,2>", t)
            sim.receive_frame("<MOVE,F>", t)
        """
        frame = frame.strip()

        if not (frame.startswith("<") and frame.endswith(">")):
            return "<ERR,BAD_FRAME>"

        body = frame[1:-1].strip()
        parts = [p.strip().upper() for p in body.split(",") if p.strip()]

        if not parts:
            return "<ERR,EMPTY_FRAME>"

        cmd = parts[0]

        # Status is valid but does not command motion.
        if cmd == "STATUS":
            self._mark_valid(t_s)
            return self.status_frame()

        # Enable/disable
        if cmd == "EN":
            if len(parts) < 2:
                return "<ERR,EN_MISSING_ARG>"

            if parts[1] == "1":
                self.s.drive_enabled = True
                self.s.mode_selected = False
                self.s.timeout_latched = False
                self.s.selected_mode = None
                self.s.motion = "S"
                self._set_targets(0.0, 0.0)
                self._mark_valid(t_s)
                return "<ACK,EN,1>"

            if parts[1] == "0":
                self._disable_and_stop()
                self._mark_valid(t_s)
                return "<ACK,EN,0>"

            return "<ERR,EN_BAD_ARG>"

        # If timed out, require enable again.
        if self.s.timeout_latched:
            return "<ERR,TIMEOUT_SEND_EN_FIRST>"

        # Mode selection must come after enable.
        if cmd == "MODE":
            if not self.s.drive_enabled:
                return "<ERR,ENABLE_FIRST>"

            if len(parts) < 2:
                return "<ERR,MODE_MISSING_ARG>"

            try:
                mode = int(parts[1])
            except ValueError:
                return "<ERR,MODE_BAD_ARG>"

            if mode not in self.p.speed_modes_kmh:
                return "<ERR,MODE_UNKNOWN>"

            self.s.selected_mode = mode
            self.s.mode_selected = True
            self.s.motion = "S"
            self._set_targets(0.0, 0.0)
            self._mark_valid(t_s)
            return f"<ACK,MODE,{mode}>"

        # Movement command: expected every 50 ms in your real system.
        if cmd == "MOVE":
            if not self.s.drive_enabled:
                return "<ERR,ENABLE_FIRST>"

            if not self.s.mode_selected:
                return "<ERR,MODE_FIRST>"

            if len(parts) < 2:
                return "<ERR,MOVE_MISSING_ARG>"

            move = parts[1][0]
            if move not in ("F", "B", "L", "R", "S"):
                return "<ERR,MOVE_BAD_ARG>"

            self.s.motion = move
            left, right = self._motion_to_targets(move)
            self._set_targets(left, right)
            self._mark_valid(t_s)
            return f"<ACK,MOVE,{move}>"

        return "<ERR,UNKNOWN_CMD>"

    # -----------------------------
    # Main physics update
    # -----------------------------

    def step(self, t_s: float, dt_s: Optional[float] = None) -> None:
        """
        Advance physics by dt_s.
        """
        if dt_s is None:
            dt_s = self.p.dt_s

        self._check_timeout(t_s)

        # Smoothly ramp each wheel speed toward target.
        self.s.left_speed_mps = self._ramp_speed(
            self.s.left_speed_mps,
            self.s.target_left_speed_mps,
            dt_s,
        )

        self.s.right_speed_mps = self._ramp_speed(
            self.s.right_speed_mps,
            self.s.target_right_speed_mps,
            dt_s,
        )

        # Differential-drive kinematics.
        v = 0.5 * (self.s.left_speed_mps + self.s.right_speed_mps)
        yaw_rate = (self.s.right_speed_mps - self.s.left_speed_mps) / self.p.wheel_base_m

        self.s.heading_rad += yaw_rate * dt_s
        self.s.x_m += v * math.cos(self.s.heading_rad) * dt_s
        self.s.y_m += v * math.sin(self.s.heading_rad) * dt_s

        self._estimate_electrical_load(dt_s)
        self._append_log(t_s, v, yaw_rate)

    # -----------------------------
    # Calculations
    # -----------------------------

    def estimate_duty_for_speed_kmh(self, speed_kmh: float, motor_current_a: float = 0.0) -> float:
        """
        Rough feed-forward duty estimate for straight driving at a certain speed.

        This is not exact. It estimates:
            duty ≈ (back_emf_voltage + current * motor_resistance) / battery_voltage
        """
        speed_mps = speed_kmh / 3.6
        wheel_rpm = self._linear_speed_to_wheel_rpm(speed_mps)
        motor_rpm = wheel_rpm * self.p.gear_ratio

        back_emf_v = motor_rpm / self.p.motor_kv_rpm_per_volt
        voltage_drop_v = motor_current_a * self.p.motor_resistance_ohm
        duty = (back_emf_v + voltage_drop_v) / self.p.battery_voltage_v

        return self._clamp(duty, -1.0, 1.0)

    def print_speed_table(self) -> None:
        print("\nEstimated speed-mode table:")
        print("Mode | speed km/h | speed m/s | wheel rpm | motor rpm | no-load duty")
        print("-----|------------|-----------|-----------|-----------|-------------")

        for mode, kmh in self.p.speed_modes_kmh.items():
            speed_mps = kmh / 3.6
            wheel_rpm = self._linear_speed_to_wheel_rpm(speed_mps)
            motor_rpm = wheel_rpm * self.p.gear_ratio
            duty = self.estimate_duty_for_speed_kmh(kmh, motor_current_a=0.0)

            print(
                f"{mode:>4} | "
                f"{kmh:>10.2f} | "
                f"{speed_mps:>9.3f} | "
                f"{wheel_rpm:>9.1f} | "
                f"{motor_rpm:>9.1f} | "
                f"{duty:>11.3f}"
            )

        print()

    # -----------------------------
    # Export
    # -----------------------------

    def save_log_csv(self, filename: str) -> None:
        if not self.log:
            return

        with open(filename, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(self.log[0].keys()))
            writer.writeheader()
            writer.writerows(self.log)

    # -----------------------------
    # Internal helpers
    # -----------------------------

    def _mark_valid(self, t_s: float) -> None:
        self.s.last_valid_command_time_s = t_s

    def _disable_and_stop(self) -> None:
        self.s.drive_enabled = False
        self.s.mode_selected = False
        self.s.selected_mode = None
        self.s.motion = "S"
        self._set_targets(0.0, 0.0)

    def _check_timeout(self, t_s: float) -> None:
        if not self.s.drive_enabled:
            return

        if (t_s - self.s.last_valid_command_time_s) > self.p.timeout_s:
            self._disable_and_stop()
            self.s.timeout_latched = True
            self.s.warning = "PC_TIMEOUT_500MS"

    def _set_targets(self, left_mps: float, right_mps: float) -> None:
        self.s.target_left_speed_mps = left_mps
        self.s.target_right_speed_mps = right_mps

    def _motion_to_targets(self, move: str) -> Tuple[float, float]:
        assert self.s.selected_mode is not None

        base_speed_mps = self.p.speed_modes_kmh[self.s.selected_mode] / 3.6

        if move == "F":
            return base_speed_mps, base_speed_mps

        if move == "B":
            v = base_speed_mps * self.p.reverse_speed_factor
            return -v, -v

        if move == "L":
            v = base_speed_mps * self.p.turn_speed_factor
            return -v, v

        if move == "R":
            v = base_speed_mps * self.p.turn_speed_factor
            return v, -v

        return 0.0, 0.0

    def _ramp_speed(self, current: float, target: float, dt_s: float) -> float:
        error = target - current

        if abs(error) < 1e-9:
            return target

        # If target magnitude is lower, use decel limit. Otherwise accel limit.
        if abs(target) < abs(current):
            max_delta = self.p.max_decel_mps2 * dt_s
        else:
            max_delta = self.p.max_accel_mps2 * dt_s

        delta = self._clamp(error, -max_delta, max_delta)
        return current + delta

    def _estimate_electrical_load(self, dt_s: float) -> None:
        """
        Rough current and duty estimate.

        This is a simple engineering estimate, not a full motor/VESC model.
        It is good enough for deciding whether numbers are clearly unrealistic.
        """
        mass = self.p.total_mass_kg
        g = 9.81
        slope_rad = math.radians(self.p.slope_deg)

        # Longitudinal speed and approximate acceleration.
        v = 0.5 * (self.s.left_speed_mps + self.s.right_speed_mps)
        v_target = 0.5 * (self.s.target_left_speed_mps + self.s.target_right_speed_mps)

        accel_est = self._clamp(
            (v_target - v) / max(dt_s, 1e-6),
            -self.p.max_decel_mps2,
            self.p.max_accel_mps2,
        )

        # Resistance forces.
        rolling_force = mass * g * self.p.rolling_resistance_coeff
        slope_force = mass * g * math.sin(slope_rad)

        # Force sign should oppose motion. If almost stopped, assume command direction.
        direction = 0.0
        if abs(v) > 1e-4:
            direction = 1.0 if v > 0 else -1.0
        elif abs(v_target) > 1e-4:
            direction = 1.0 if v_target > 0 else -1.0

        force_total = mass * accel_est + direction * rolling_force + direction * slope_force

        # Split over two drive wheels.
        force_per_wheel = force_total / 2.0
        wheel_torque_nm = force_per_wheel * self.p.wheel_radius_m
        motor_torque_nm = wheel_torque_nm / max(self.p.gear_ratio * self.p.drivetrain_efficiency, 1e-6)

        motor_current_a = motor_torque_nm / max(self.p.motor_kt_nm_per_a, 1e-6)

        # For turning in place, estimate additional current from wheel speeds
        # using rolling resistance on each wheel.
        if abs(v) < 1e-4 and abs(self.s.left_speed_mps - self.s.right_speed_mps) > 1e-4:
            turn_force_per_wheel = mass * g * self.p.rolling_resistance_coeff / 2.0
            turn_wheel_torque = turn_force_per_wheel * self.p.wheel_radius_m
            turn_motor_torque = turn_wheel_torque / max(self.p.gear_ratio * self.p.drivetrain_efficiency, 1e-6)
            motor_current_a = turn_motor_torque / max(self.p.motor_kt_nm_per_a, 1e-6)

        self.s.left_motor_current_a = abs(motor_current_a) if abs(self.s.left_speed_mps) > 1e-4 else 0.0
        self.s.right_motor_current_a = abs(motor_current_a) if abs(self.s.right_speed_mps) > 1e-4 else 0.0

        self.s.left_duty_estimate = self._estimate_duty_for_wheel_speed(
            self.s.left_speed_mps,
            self.s.left_motor_current_a,
        )
        self.s.right_duty_estimate = self._estimate_duty_for_wheel_speed(
            self.s.right_speed_mps,
            self.s.right_motor_current_a,
        )

        mechanical_power_w = abs(force_total * v)
        self.s.battery_current_a = mechanical_power_w / max(self.p.battery_voltage_v * self.p.drivetrain_efficiency, 1e-6)

        warnings = []

        if abs(self.s.left_motor_current_a) > self.p.max_motor_current_a:
            warnings.append("LEFT_MOTOR_CURRENT_LIMIT")

        if abs(self.s.right_motor_current_a) > self.p.max_motor_current_a:
            warnings.append("RIGHT_MOTOR_CURRENT_LIMIT")

        if self.s.battery_current_a > self.p.max_battery_current_a:
            warnings.append("BATTERY_CURRENT_LIMIT")

        if abs(self.s.left_duty_estimate) > self.p.max_duty:
            warnings.append("LEFT_DUTY_LIMIT")

        if abs(self.s.right_duty_estimate) > self.p.max_duty:
            warnings.append("RIGHT_DUTY_LIMIT")

        if warnings:
            self.s.warning = "|".join(warnings)
        elif self.s.warning != "PC_TIMEOUT_500MS":
            self.s.warning = ""

    def _estimate_duty_for_wheel_speed(self, wheel_speed_mps: float, motor_current_a: float) -> float:
        wheel_rpm = self._linear_speed_to_wheel_rpm(wheel_speed_mps)
        motor_rpm = wheel_rpm * self.p.gear_ratio

        back_emf_v = motor_rpm / self.p.motor_kv_rpm_per_volt
        voltage_drop_v = motor_current_a * self.p.motor_resistance_ohm

        # Keep voltage drop sign consistent with wheel direction.
        sign = 1.0 if wheel_speed_mps >= 0 else -1.0
        required_v = back_emf_v + sign * voltage_drop_v

        duty = required_v / self.p.battery_voltage_v
        return self._clamp(duty, -1.0, 1.0)

    def _linear_speed_to_wheel_rpm(self, speed_mps: float) -> float:
        circumference = math.pi * self.p.wheel_diameter_m
        return (speed_mps / circumference) * 60.0

    def _append_log(self, t_s: float, v_mps: float, yaw_rate_rad_s: float) -> None:
        self.log.append({
            "t_s": round(t_s, 4),
            "enabled": int(self.s.drive_enabled),
            "mode_selected": int(self.s.mode_selected),
            "mode": self.s.selected_mode if self.s.selected_mode is not None else "",
            "motion": self.s.motion,
            "x_m": self.s.x_m,
            "y_m": self.s.y_m,
            "heading_deg": math.degrees(self.s.heading_rad),
            "left_speed_mps": self.s.left_speed_mps,
            "right_speed_mps": self.s.right_speed_mps,
            "forward_speed_mps": v_mps,
            "forward_speed_kmh": v_mps * 3.6,
            "yaw_rate_deg_s": math.degrees(yaw_rate_rad_s),
            "left_current_a": self.s.left_motor_current_a,
            "right_current_a": self.s.right_motor_current_a,
            "battery_current_a": self.s.battery_current_a,
            "left_duty_estimate": self.s.left_duty_estimate,
            "right_duty_estimate": self.s.right_duty_estimate,
            "warning": self.s.warning,
        })

    def status_frame(self) -> str:
        mode = self.s.selected_mode if self.s.selected_mode is not None else "NONE"
        return (
            f"<STAT,"
            f"EN={int(self.s.drive_enabled)},"
            f"MODE_SET={int(self.s.mode_selected)},"
            f"MODE={mode},"
            f"MOTION={self.s.motion},"
            f"TIMEOUT={int(self.s.timeout_latched)},"
            f"L_SPEED={self.s.left_speed_mps:.3f},"
            f"R_SPEED={self.s.right_speed_mps:.3f},"
            f"L_DUTY={self.s.left_duty_estimate:.3f},"
            f"R_DUTY={self.s.right_duty_estimate:.3f},"
            f"L_CUR={self.s.left_motor_current_a:.2f},"
            f"R_CUR={self.s.right_motor_current_a:.2f},"
            f"WARN={self.s.warning or 'NONE'}"
            f">"
        )

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))


# ============================================================
# 4) DEMO / TEST RUN
# ============================================================

def run_demo() -> None:
    params = WheelchairParams(
        # Change these values first:
        wheel_diameter_m=0.30,
        wheel_base_m=0.55,
        chair_mass_kg=70.0,
        rider_mass_kg=70.0,
        gear_ratio=10.0,
        motor_kv_rpm_per_volt=170.0,
        battery_voltage_v=24.0,

        # Start conservative:
        max_motor_current_a=10.0,
        max_battery_current_a=8.0,
        max_duty=0.30,
    )

    sim = WheelchairSim(params)
    sim.print_speed_table()

    t = 0.0
    dt = params.dt_s

    print(sim.receive_frame("<EN,1>", t))
    print(sim.receive_frame("<MODE,2>", t))

    # Send MOVE,F every 50 ms for 3 seconds.
    next_command_t = 0.0
    stop_sending_at = 3.0
    total_sim_time = 4.0

    while t <= total_sim_time:
        if t <= stop_sending_at and t >= next_command_t - 1e-9:
            sim.receive_frame("<MOVE,F>", t)
            next_command_t += params.expected_command_period_s

        sim.step(t, dt)
        t += dt

    print(sim.status_frame())
    sim.save_log_csv("wheelchair_sim_log.csv")
    print("Saved log to wheelchair_sim_log.csv")

    # Optional plot. Requires matplotlib:
    # import matplotlib.pyplot as plt
    # xs = [row["x_m"] for row in sim.log]
    # ys = [row["y_m"] for row in sim.log]
    # plt.figure()
    # plt.plot(xs, ys)
    # plt.xlabel("x [m]")
    # plt.ylabel("y [m]")
    # plt.axis("equal")
    # plt.show()


if __name__ == "__main__":
    run_demo()
