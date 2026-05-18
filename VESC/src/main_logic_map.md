# VESC src reading map

This file is only a reading and debugging guide. It does not replace or change
`main.cpp`, `5-can`, `5_uart`, or anything in `old _code`.

## Active files

- `main.cpp` is the PlatformIO entry point that gets compiled.
- `5-can` is the same CAN sketch structure as `main.cpp`, but with lower test
  duty presets.
- `5_uart` is the UART version of the same raw-byte hold-button control idea.
- `5_can_structured.hpp` is a C++ reading/refactor copy. It is not included by
  `main.cpp`, so it does not change the active build.
- `old _code/` keeps the earlier steps: first UART/CAN tests, the linear and
  angular UART version, the two-Arduino CAN FSM, and the older 3-mode FSMs.

Only difference found between `main.cpp` and `5-can`:

| File | DUTY_MODE_1 | DUTY_MODE_2 | DUTY_MODE_3 |
| --- | ---: | ---: | ---: |
| `main.cpp` | `0.30f` | `0.40f` | `0.50f` |
| `5-can` | `0.05f` | `0.08f` | `0.10f` |

## main.cpp pieces

Use these sections when reading or debugging the active sketch:

| Lines | Piece | What it owns |
| ---: | --- | --- |
| 1-42 | Sketch header | Hardware notes, raw-byte protocol, safety summary |
| 44-104 | Board, CAN, VESC constants | GIGA guard, FDCAN2 RAM, CAN bitrate, VESC IDs, relay pin, CAN packet IDs |
| 106-207 | Global state | Relay state, motion state, mode state, latches, timers, targets, telemetry cache |
| 209-303 | Small helpers | State names, duty lookup, timeout timestamp, endian reads/writes, CAN ID helpers, duty clamp |
| 305-331 | PC reply helpers | `<ACK,...>`, `<ERR,...>`, `<EVT,...>`, `<WARN,...>` serial output |
| 333-365 | Relay helpers | Relay output pin setup and brake-release relay switching |
| 367-424 | CAN setup | Transceiver standby pin, ACANFD settings, FDCAN2 startup |
| 426-535 | VESC CAN transmit | Build extended VESC CAN IDs, send duty payloads, send left/right commands, keepalive refresh |
| 537-587 | CAN receive and telemetry | Read received CAN frames and cache VESC `STATUS` / `STATUS_5` values |
| 589-693 | Status frame | Print one full `<STAT,...>` line with state, CAN, relay, targets, and telemetry |
| 695-735 | Movement mapping | Convert wanted motion into left/right duty targets |
| 737-859 | Motor state machine | Stop, apply motion, request motion, stop-before-change transition |
| 861-937 | Internal drive safety | Enable/disable drive, select mode, force disable after CAN fault |
| 939-1038 | Raw-byte command handler | Decode `0x00` to `0x07` from the PC and trigger the matching action |
| 1040-1049 | Serial receive | Drain USB serial bytes and pass each raw byte to the command handler |
| 1051-1076 | PC timeout | Stop and disable drive if commands stop arriving while enabled |
| 1078-1170 | Arduino entry points | `setup()` boot sequence and `loop()` recurring work |

## Top-level flow

`setup()` does this:

1. Start USB serial.
2. Put the motor relay in the inactive state.
3. Start CAN on FDCAN2.
4. Print boot/protocol information.
5. Stop motors, keep relay off, and print one status frame.

`loop()` does this forever:

1. Read raw bytes from the PC.
2. Read VESC telemetry frames from CAN.
3. Finish any pending stop-before-change transition.
4. Check the 500 ms PC command timeout.
5. Re-send left/right duty commands every `KEEPALIVE_MS` while enabled.
6. If a CAN transmit fault latched, force-disable drive and relay.

## Raw-byte PC commands

| Byte | Name | Main action |
| ---: | --- | --- |
| `0x00` | STOP | Clear latches, disable drive, stop motors, relay off |
| `0x01` | MODE_1 | Select mode 1, enable drive, request forward |
| `0x02` | MODE_2 | Select mode 2, enable drive, request forward |
| `0x03` | MODE_3 | Select mode 3, enable drive, request forward |
| `0x04` | RIGHT | Default to mode 1 if needed, enable drive, request right turn |
| `0x05` | LEFT | Default to mode 1 if needed, enable drive, request left turn |
| `0x06` | STATUS | Print the full `<STAT,...>` line |
| `0x07` | ESTOP | Stop motors, disable drive, relay off, latch emergency state |

Bytes greater than `0x07` are ignored so normal ASCII text does not become a
motion command by accident.

## Safety behavior

- A motion command automatically enables drive through `internalEnableDrive()`.
- Drive enable is blocked if CAN is not ready, unless `DRY_RUN` is true.
- Drive enable and motion are blocked while `canFaultLatched` is true.
- `CMD_STOP` clears timeout, emergency, and CAN-fault latches.
- `CMD_ESTOP` stops motors, disables drive, disables relay, and latches
  `emergencyLatched`.
- A motion change from one non-stopped motion to another first calls
  `rawStopMotors()`, waits `STOP_BEFORE_CHANGE_MS`, then applies the pending
  target.
- The timeout only runs while `driveEnabled` is true.
- If no valid movement command is seen for `PC_TIMEOUT_MS`, the sketch stops
  motors, disables drive, disables the relay, and latches `timeoutLatched`.
- A CAN send failure while drive or relay is active latches `canFaultLatched`.
  The main loop then calls `forceDisableDriveNoCanStop()` so it does not depend
  on more CAN messages to make the local system safe.

## State variables to watch

| Variable | Meaning |
| --- | --- |
| `driveEnabled` | Main permission for motion and keepalive sends |
| `modeSelected` | Whether a mode has been chosen |
| `drivingMode` | Current mode: `MODE_1`, `MODE_2`, or `MODE_3` |
| `motion` | Current motion state: stop, forward, reverse, left, right |
| `leftTarget`, `rightTarget` | Last commanded duty targets |
| `transitionPending` | A stop-before-change transition is waiting to finish |
| `pendingLeftTarget`, `pendingRightTarget`, `pendingMotion` | Next target after the stop delay |
| `timeoutLatched` | PC command timeout happened |
| `emergencyLatched` | ESTOP command happened |
| `canFaultLatched` | CAN transmit failed while output was active |
| `canReady` | CAN bus setup succeeded |
| `lastCanTxStatus`, `canTxFailCount`, `canRxCount` | CAN debug counters/status |
| `leftTel`, `rightTel` | Last cached telemetry from each VESC |

## Debug paths

Forward mode command:

```text
readPcSerial()
  -> handleBinaryCommand(CMD_MODE_1/CMD_MODE_2/CMD_MODE_3)
  -> setDrivingModeInternal(...)
  -> internalEnableDrive()
  -> requestMotionState(FORWARD)
  -> getTargetsForMotion(FORWARD)
  -> requestMotion(...)
  -> applyMotors(...)
  -> sendLeftCommand(...) / sendRightCommand(...)
  -> sendVescDuty(...)
  -> sendVescCanFrame(...)
```

Stop command:

```text
readPcSerial()
  -> handleBinaryCommand(CMD_STOP)
  -> internalDisableDrive("BIN_STOP")
  -> stopMotors()
  -> rawStopMotors()
  -> setMotorRelay(false)
```

Turn while already moving:

```text
handleBinaryCommand(CMD_LEFT/CMD_RIGHT)
  -> requestMotionState(LEFT/RIGHT)
  -> requestMotion(...)
  -> rawStopMotors()
  -> transitionPending = true
loop()
  -> processPendingTransition()
  -> applyMotors(...)
```

CAN transmit failure:

```text
sendVescCanFrame(...)
  -> lastCanTxStatus != 0
  -> canFaultLatched = true
loop()
  -> handleCanFaultShutdown()
  -> forceDisableDriveNoCanStop("CAN_TX_FAULT")
```

## Where to start when debugging

- Boot or CAN startup problem: `setup()`, `setupCan()`, `setupCanTransceiver()`.
- Relay/brake release problem: `setupMotorRelay()`, `setMotorRelay()`.
- Wrong direction or speed: `getTargetsForMotion()`, `DUTY_MODE_*`,
  `TURN_DUTY_FACTOR`, `REVERSE_DUTY_FACTOR`, `LEFT_VESC_ID`, `RIGHT_VESC_ID`.
- PC button command problem: `readPcSerial()`, `handleBinaryCommand()`.
- Motion transition problem: `requestMotion()`, `processPendingTransition()`.
- Unexpected stop: `checkPcTimeout()`, `handleCanFaultShutdown()`,
  `internalDisableDrive()`, `forceDisableDriveNoCanStop()`.
- Missing telemetry: `readCan()`, `parseVescStatusFrame()`,
  `printTelemetryStatus()`, `sendStatusFrame()`.
