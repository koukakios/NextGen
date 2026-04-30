#include <Arduino.h>

// --------------------------------------------------
// Dummy wheelchair skeleton for 2 VESCs over CAN bus
// Arduino GIGA + MCP2562 CAN transceiver shield
//
// IMPORTANT:
// - MCP2562 is a CAN transceiver only.
// - This uses the Arduino GIGA internal FDCAN controller.
// - Your shield routes CAN to FDCAN2:
//      CANTX = PB13
//      CANRX = PB5
// - MCP2562 STBY is connected to D7.
//      LOW  = normal mode
//      HIGH = standby mode
//
// Behavior:
// - DRY_RUN = true  -> safe test, only prints what it would send
// - DRY_RUN = false -> sends real CAN commands to the VESCs
//
// FSM behavior:
// - No automatic stop after 500 ms.
// - Chair keeps doing last motion command.
// - CAN command is refreshed every CAN_REFRESH_MS.
// - If a different motion command arrives:
//      current motion -> STOPPED -> new motion
// --------------------------------------------------

#ifndef ARDUINO_GIGA
  #error This code is for Arduino GIGA R1
#endif

// ACANFD_GIGA_R1 requires these definitions BEFORE the include.
// We use FDCAN2 only.
static const uint32_t FDCAN1_MESSAGE_RAM_WORD_SIZE = 0;
static const uint32_t FDCAN2_MESSAGE_RAM_WORD_SIZE = 2560;

#include <ACANFD_GIGA_R1.h>

// ====================== SAFETY SWITCH ======================

constexpr bool DRY_RUN = true;   // true = safe print only, false = real CAN driving

// ====================== CAN SETUP ======================

// Your shield connects MCP2562 STBY to D7.
// MCP2562 STBY:
// LOW  = normal CAN operation
// HIGH = standby
constexpr uint8_t CAN_STBY_PIN = 7;

// VESC CAN is normally 500 kbit/s.
constexpr uint32_t CAN_BITRATE = 500UL * 1000UL;

bool canReady = false;

// ====================== VESC IDs ======================

// Set these to the CAN IDs in VESC Tool:
// App Settings -> General -> VESC ID
constexpr uint8_t LEFT_VESC_ID  = 1;
constexpr uint8_t RIGHT_VESC_ID = 2;

// ====================== VESC CAN PACKET IDs ======================

enum VescCanPacket {
  CAN_PACKET_SET_DUTY          = 0,
  CAN_PACKET_SET_CURRENT       = 1,
  CAN_PACKET_SET_CURRENT_BRAKE = 2,
  CAN_PACKET_SET_RPM           = 3
};

// ====================== FSM STATES ======================

enum MotionState {
  STOPPED,
  FORWARD,
  REVERSE,
  LEFT,
  RIGHT
};

bool driveEnabled = false;
MotionState motion = STOPPED;

float leftTarget = 0.0f;
float rightTarget = 0.0f;

// CAN command refresh.
// The Arduino keeps resending the current command so the VESC does not timeout.
unsigned long lastCanRefreshMs = 0;
constexpr unsigned long CAN_REFRESH_MS = 50;

// Time to stay in STOPPED before changing to a different movement.
constexpr unsigned long STOP_BEFORE_CHANGE_MS = 150;

bool transitionPending = false;
unsigned long transitionStartMs = 0;

float pendingLeftTarget = 0.0f;
float pendingRightTarget = 0.0f;
MotionState pendingMotion = STOPPED;

// ====================== CONTROL MODE ======================

enum ControlMode {
  MODE_DUTY,
  MODE_RPM,
  MODE_CURRENT
};

ControlMode controlMode = MODE_DUTY;

// ====================== HELPER TEXT ======================

const char* motionToString(MotionState s) {
  switch (s) {
    case STOPPED: return "STOP";
    case FORWARD: return "FORWARD";
    case REVERSE: return "REVERSE";
    case LEFT:    return "LEFT";
    case RIGHT:   return "RIGHT";
    default:      return "UNKNOWN";
  }
}

const char* modeToString(ControlMode m) {
  switch (m) {
    case MODE_DUTY:    return "DUTY";
    case MODE_RPM:     return "RPM";
    case MODE_CURRENT: return "CURRENT";
    default:           return "UNKNOWN";
  }
}

const char* packetToString(VescCanPacket p) {
  switch (p) {
    case CAN_PACKET_SET_DUTY:          return "SET_DUTY";
    case CAN_PACKET_SET_CURRENT:       return "SET_CURRENT";
    case CAN_PACKET_SET_CURRENT_BRAKE: return "SET_CURRENT_BRAKE";
    case CAN_PACKET_SET_RPM:           return "SET_RPM";
    default:                           return "UNKNOWN_PACKET";
  }
}

// ====================== PRINT FUNCTIONS ======================

void printHelp() {
  Serial.println();
  Serial.println("=== Dummy Chair + VESC CAN Skeleton ===");
  Serial.println("h = help");
  Serial.println("e = enable drive");
  Serial.println("d = disable drive");
  Serial.println("f = forward");
  Serial.println("b = reverse");
  Serial.println("l = left");
  Serial.println("r = right");
  Serial.println("s = stop");
  Serial.println("p = print status");
  Serial.println("1 = control mode DUTY");
  Serial.println("2 = control mode RPM");
  Serial.println("3 = control mode CURRENT");
  Serial.println("=======================================");
  Serial.println();
}

void printStatus() {
  Serial.println();
  Serial.println("========== STATUS ==========");

  Serial.print("DRY_RUN: ");
  Serial.println(DRY_RUN ? "true" : "false");

  Serial.print("CAN ready: ");
  Serial.println(canReady ? "YES" : "NO");

  Serial.print("Using CAN peripheral: ");
  Serial.println("FDCAN2");

  Serial.print("FDCAN2 TX pin: ");
  Serial.println("PB13 / GIGA CANTX");

  Serial.print("FDCAN2 RX pin: ");
  Serial.println("PB5 / GIGA CANRX");

  Serial.print("MCP2562 STBY pin: D");
  Serial.println(CAN_STBY_PIN);

  Serial.print("Drive enabled: ");
  Serial.println(driveEnabled ? "YES" : "NO");

  Serial.print("Motion: ");
  Serial.println(motionToString(motion));

  Serial.print("Control mode: ");
  Serial.println(modeToString(controlMode));

  Serial.print("Left VESC ID: ");
  Serial.println(LEFT_VESC_ID);

  Serial.print("Right VESC ID: ");
  Serial.println(RIGHT_VESC_ID);

  Serial.print("Left target: ");
  Serial.println(leftTarget, 3);

  Serial.print("Right target: ");
  Serial.println(rightTarget, 3);

  Serial.print("Transition pending: ");
  Serial.println(transitionPending ? "YES" : "NO");

  if (transitionPending) {
    Serial.print("Pending motion: ");
    Serial.println(motionToString(pendingMotion));
  }

  Serial.println("============================");
  Serial.println();
}

// ====================== CAN SETUP FUNCTION ======================

void setupCan() {
  // Bring MCP2562 out of standby.
  pinMode(CAN_STBY_PIN, OUTPUT);
  digitalWrite(CAN_STBY_PIN, LOW);

  Serial.println("MCP2562 STBY -> LOW, normal mode.");

  if (DRY_RUN) {
    Serial.println("DRY_RUN is true.");
    Serial.println("FDCAN2 initialization skipped.");
    Serial.println("No real CAN messages will be sent.");
    canReady = false;
    return;
  }

  Serial.println("Starting GIGA FDCAN2...");

  // x1 means the data phase is the same as arbitration phase.
  // We are using short VESC command frames.
  ACANFD_GIGA_R1_Settings settings(CAN_BITRATE, DataBitRateFactor::x1);

  // Normal mode, not loopback.
  settings.mModuleMode = ACANFD_GIGA_R1_Settings::NORMAL_FD;

  // Explicitly select the pins your shield uses:
  // FDCAN2 TX = PB13
  // FDCAN2 RX = PB5
  settings.mTxPin = PB_13;
  settings.mRxPin = PB_5;

  const uint32_t errorCode = fdcan2.beginFD(settings);

  Serial.print("FDCAN2 message RAM required minimum size: ");
  Serial.print(fdcan2.messageRamRequiredMinimumSize());
  Serial.println(" words");

  if (errorCode == 0) {
    canReady = true;
    Serial.println("FDCAN2 init OK.");
  } else {
    canReady = false;
    Serial.print("FDCAN2 init failed. Error: 0x");
    Serial.println(errorCode, HEX);
  }
}

// ====================== CAN HELPERS ======================

void bufferAppendInt32(uint8_t* buffer, int32_t value) {
  buffer[0] = (value >> 24) & 0xFF;
  buffer[1] = (value >> 16) & 0xFF;
  buffer[2] = (value >> 8)  & 0xFF;
  buffer[3] = value & 0xFF;
}

void printCanFrame(uint8_t vescId, VescCanPacket packetId, const uint8_t* data, uint8_t len) {
  const uint32_t canId = ((uint32_t)packetId << 8) | vescId;

  Serial.print("[DRY CAN] Extended ID: 0x");
  Serial.print(canId, HEX);

  Serial.print(" | VESC ID: ");
  Serial.print(vescId);

  Serial.print(" | Packet: ");
  Serial.print(packetToString(packetId));

  Serial.print(" | Data: ");

  for (uint8_t i = 0; i < len; i++) {
    if (data[i] < 0x10) {
      Serial.print("0");
    }
    Serial.print(data[i], HEX);
    Serial.print(" ");
  }

  Serial.println();
}

bool sendVescCan(uint8_t vescId, VescCanPacket packetId, const uint8_t* data, uint8_t len, bool dryPrint = true) {
  const uint32_t canId = ((uint32_t)packetId << 8) | vescId;

  if (DRY_RUN) {
    if (dryPrint) {
      printCanFrame(vescId, packetId, data, len);
    }
    return true;
  }

  if (!canReady) {
    Serial.println("CAN is not ready. Cannot send command.");
    return false;
  }

  CANFDMessage message;
  message.id = canId;
  message.ext = true;   // VESC uses extended 29-bit CAN identifiers.
  message.len = len;

  for (uint8_t i = 0; i < len; i++) {
    message.data[i] = data[i];
  }

  const uint32_t sendStatus = fdcan2.tryToSendReturnStatusFD(message);

  if (sendStatus != 0) {
    Serial.print("CAN send failed. Status: 0x");
    Serial.println(sendStatus, HEX);
    return false;
  }

  return true;
}

// ====================== VESC COMMAND WRAPPERS ======================

void vescSetDuty(uint8_t vescId, float duty, bool dryPrint = true) {
  uint8_t data[4];

  // VESC duty scaling: duty * 100000
  // Example: 0.10 -> 10000
  const int32_t value = (int32_t)(duty * 100000.0f);
  bufferAppendInt32(data, value);

  sendVescCan(vescId, CAN_PACKET_SET_DUTY, data, 4, dryPrint);
}

void vescSetRPM(uint8_t vescId, float rpm, bool dryPrint = true) {
  uint8_t data[4];

  const int32_t value = (int32_t)rpm;
  bufferAppendInt32(data, value);

  sendVescCan(vescId, CAN_PACKET_SET_RPM, data, 4, dryPrint);
}

void vescSetCurrent(uint8_t vescId, float current, bool dryPrint = true) {
  uint8_t data[4];

  // VESC current scaling: current * 1000
  // Example: 2.0 A -> 2000
  const int32_t value = (int32_t)(current * 1000.0f);
  bufferAppendInt32(data, value);

  sendVescCan(vescId, CAN_PACKET_SET_CURRENT, data, 4, dryPrint);
}

void vescSetBrakeCurrent(uint8_t vescId, float brakeCurrent, bool dryPrint = true) {
  uint8_t data[4];

  const int32_t value = (int32_t)(brakeCurrent * 1000.0f);
  bufferAppendInt32(data, value);

  sendVescCan(vescId, CAN_PACKET_SET_CURRENT_BRAKE, data, 4, dryPrint);
}

void sendVescCommand(uint8_t vescId, float value, bool dryPrint = true) {
  switch (controlMode) {
    case MODE_DUTY:
      vescSetDuty(vescId, value, dryPrint);
      break;

    case MODE_RPM:
      vescSetRPM(vescId, value, dryPrint);
      break;

    case MODE_CURRENT:
      // Negative current is used here for reverse movement.
      vescSetCurrent(vescId, value, dryPrint);
      break;
  }
}

void sendBothCommands(float left, float right, bool dryPrint = true) {
  sendVescCommand(LEFT_VESC_ID, left, dryPrint);
  sendVescCommand(RIGHT_VESC_ID, right, dryPrint);
}

// ====================== MOTOR STATE FUNCTIONS ======================

void rawStopMotors() {
  leftTarget = 0.0f;
  rightTarget = 0.0f;
  motion = STOPPED;

  sendBothCommands(0.0f, 0.0f, true);

  Serial.println("Motors -> STOP");
}

void stopMotors() {
  transitionPending = false;
  rawStopMotors();
}

void applyMotors(float left, float right, MotionState newMotion) {
  leftTarget = left;
  rightTarget = right;
  motion = newMotion;

  sendBothCommands(leftTarget, rightTarget, true);

  Serial.print("Motion -> ");
  Serial.println(motionToString(motion));
}

void requestMotion(float left, float right, MotionState newMotion) {
  if (!driveEnabled) {
    Serial.println("Drive disabled. Press 'e' first.");
    return;
  }

  // If already waiting in STOP before changing motion,
  // replace the pending command with the newest command.
  if (transitionPending) {
    pendingLeftTarget = left;
    pendingRightTarget = right;
    pendingMotion = newMotion;

    Serial.print("Pending command replaced -> ");
    Serial.println(motionToString(pendingMotion));
    return;
  }

  // If currently stopped, apply immediately.
  if (motion == STOPPED) {
    applyMotors(left, right, newMotion);
    return;
  }

  // If same command again, keep going.
  if (motion == newMotion) {
    Serial.print("Already moving ");
    Serial.println(motionToString(motion));
    return;
  }

  // Different movement command:
  // First STOP, wait STOP_BEFORE_CHANGE_MS, then apply new motion.
  Serial.print("Motion change requested: ");
  Serial.print(motionToString(motion));
  Serial.print(" -> STOP -> ");
  Serial.println(motionToString(newMotion));

  rawStopMotors();

  pendingLeftTarget = left;
  pendingRightTarget = right;
  pendingMotion = newMotion;

  transitionPending = true;
  transitionStartMs = millis();
}

void processPendingTransition() {
  if (!transitionPending) {
    return;
  }

  if (!driveEnabled) {
    transitionPending = false;
    return;
  }

  if (millis() - transitionStartMs >= STOP_BEFORE_CHANGE_MS) {
    transitionPending = false;

    Serial.print("Applying pending motion -> ");
    Serial.println(motionToString(pendingMotion));

    applyMotors(pendingLeftTarget, pendingRightTarget, pendingMotion);
  }
}

void refreshCanCommand() {
  if (!driveEnabled) {
    return;
  }

  if (millis() - lastCanRefreshMs >= CAN_REFRESH_MS) {
    lastCanRefreshMs = millis();

    // Keep resending the current command.
    // In DRY_RUN, this does not print every 50 ms to avoid spam.
    sendBothCommands(leftTarget, rightTarget, false);
  }
}

// ====================== MOVEMENT MAPPING ======================

void commandForward() {
  switch (controlMode) {
    case MODE_DUTY:
      requestMotion(0.10f, 0.10f, FORWARD);
      break;

    case MODE_RPM:
      requestMotion(1000.0f, 1000.0f, FORWARD);
      break;

    case MODE_CURRENT:
      requestMotion(2.0f, 2.0f, FORWARD);
      break;
  }
}

void commandReverse() {
  switch (controlMode) {
    case MODE_DUTY:
      requestMotion(-0.10f, -0.10f, REVERSE);
      break;

    case MODE_RPM:
      requestMotion(-1000.0f, -1000.0f, REVERSE);
      break;

    case MODE_CURRENT:
      requestMotion(-2.0f, -2.0f, REVERSE);
      break;
  }
}

void commandLeft() {
  switch (controlMode) {
    case MODE_DUTY:
      requestMotion(-0.08f, 0.08f, LEFT);
      break;

    case MODE_RPM:
      requestMotion(-700.0f, 700.0f, LEFT);
      break;

    case MODE_CURRENT:
      requestMotion(-1.5f, 1.5f, LEFT);
      break;
  }
}

void commandRight() {
  switch (controlMode) {
    case MODE_DUTY:
      requestMotion(0.08f, -0.08f, RIGHT);
      break;

    case MODE_RPM:
      requestMotion(700.0f, -700.0f, RIGHT);
      break;

    case MODE_CURRENT:
      requestMotion(1.5f, -1.5f, RIGHT);
      break;
  }
}

// ====================== CONTROL MODE CHANGE ======================

void setControlMode(ControlMode newMode) {
  // Safer: stop first before changing how target numbers are interpreted.
  stopMotors();
  controlMode = newMode;

  Serial.print("Control mode -> ");
  Serial.println(modeToString(controlMode));
}

// ====================== DRIVE STATE ======================

void enableDrive() {
  driveEnabled = true;
  transitionPending = false;

  Serial.println("Drive ENABLED");
  stopMotors();
}

void disableDrive() {
  stopMotors();
  driveEnabled = false;

  Serial.println("Drive DISABLED");
}

// ====================== SERIAL COMMAND HANDLER ======================

void handleCommand(char c) {
  switch (c) {
    case 'h':
    case 'H':
      printHelp();
      break;

    case 'e':
    case 'E':
      enableDrive();
      break;

    case 'd':
    case 'D':
      disableDrive();
      break;

    case 'f':
    case 'F':
      commandForward();
      break;

    case 'b':
    case 'B':
      commandReverse();
      break;

    case 'l':
    case 'L':
      commandLeft();
      break;

    case 'r':
    case 'R':
      commandRight();
      break;

    case 's':
    case 'S':
      stopMotors();
      break;

    case 'p':
    case 'P':
      printStatus();
      break;

    case '1':
      setControlMode(MODE_DUTY);
      break;

    case '2':
      setControlMode(MODE_RPM);
      break;

    case '3':
      setControlMode(MODE_CURRENT);
      break;

    case '\n':
    case '\r':
      break;

    default:
      Serial.print("Unknown command: ");
      Serial.println(c);
      break;
  }
}

// ====================== SETUP AND LOOP ======================

void setup() {
  Serial.begin(115200);

  while (!Serial) {
    delay(10);
  }

  Serial.println();
  Serial.println("Dummy Chair + VESC CAN Skeleton started.");
  Serial.println("Using Arduino GIGA internal FDCAN2 + MCP2562 transceiver.");
  Serial.println("Shield pins: CANTX=PB13, CANRX=PB5, STBY=D7.");
  Serial.println();

  setupCan();

  printHelp();
  printStatus();

  stopMotors();
}

void loop() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    handleCommand(c);
  }

  // Handles STOP -> new motion transition without delay()
  processPendingTransition();

  // Keeps refreshing current CAN command while enabled
  refreshCanCommand();
} 