#include <Arduino.h>
#include <VescUart.h>
#include <string.h>

// --------------------------------------------------
// Wheelchair skeleton for 2 VESCs over UART
// Arduino GIGA + PlatformIO
//
// PC protocol over Serial:
//
// Required order:
//   1. <EN,1>
//   2. <MODE,2> or <MODE,5> or <MODE,10>
//   3. <MOVE,F/B/L/R/S> every 50 ms
//
// Safety:
//   - After <EN,1>, Arduino expects valid PC commands.
//   - If no valid command is received for 500 ms,
//     the chair stops, drive disables, and mode is cleared.
//   - After timeout, PC must send <EN,1> again.
// --------------------------------------------------

constexpr bool DRY_RUN = false;

// PC communication port
#define PC_SERIAL Serial

// VESC UART ports
#define LEFT_VESC_SERIAL  Serial1
#define RIGHT_VESC_SERIAL Serial2

VescUart leftVesc;
VescUart rightVesc;

// --------------------------------------------------
// Timing
// --------------------------------------------------

constexpr unsigned long EXPECTED_PC_COMMAND_PERIOD_MS = 50;
constexpr unsigned long PC_TIMEOUT_MS = 500;

constexpr unsigned long KEEPALIVE_MS = 100;
constexpr unsigned long STOP_BEFORE_CHANGE_MS = 150;

// --------------------------------------------------
// Motion and mode states
// --------------------------------------------------

enum MotionState {
  STOPPED,
  FORWARD,
  REVERSE,
  LEFT,
  RIGHT
};

enum DrivingMode {
  MODE_2_KMH,
  MODE_5_KMH,
  MODE_10_KMH
};

bool driveEnabled = false;
bool modeSelected = false;
bool timeoutLatched = false;

MotionState motion = STOPPED;
DrivingMode drivingMode = MODE_2_KMH;

float leftTarget = 0.0f;
float rightTarget = 0.0f;

unsigned long lastValidPcCommandMs = 0;
unsigned long lastKeepAliveMs = 0;

bool transitionPending = false;
unsigned long transitionStartMs = 0;

float pendingLeftTarget = 0.0f;
float pendingRightTarget = 0.0f;
MotionState pendingMotion = STOPPED;

// --------------------------------------------------
// Duty presets
//
// These are starting values.
// They do NOT automatically guarantee exact real km/h.
// You must tune them on the real wheelchair.
// --------------------------------------------------

constexpr float DUTY_2_KMH  = 0.05f;
constexpr float DUTY_5_KMH  = 0.10f;
constexpr float DUTY_10_KMH = 0.70f;

constexpr float TURN_DUTY_FACTOR = 0.80f;
constexpr float REVERSE_DUTY_FACTOR = 0.70f;

// --------------------------------------------------
// PC frame buffer
// --------------------------------------------------

constexpr size_t PC_RX_BUFFER_SIZE = 64;
char pcRxBuffer[PC_RX_BUFFER_SIZE];
size_t pcRxIndex = 0;
bool receivingFrame = false;

// --------------------------------------------------
// Helper functions
// --------------------------------------------------

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

const char* drivingModeToString(DrivingMode m) {
  switch (m) {
    case MODE_2_KMH:  return "2KMH";
    case MODE_5_KMH:  return "5KMH";
    case MODE_10_KMH: return "10KMH";
    default:          return "UNKNOWN";
  }
}

float getDriveDuty() {
  switch (drivingMode) {
    case MODE_2_KMH:
      return DUTY_2_KMH;

    case MODE_5_KMH:
      return DUTY_5_KMH;

    case MODE_10_KMH:
      return DUTY_10_KMH;

    default:
      return DUTY_2_KMH;
  }
}

float getTurnDuty() {
  return getDriveDuty() * TURN_DUTY_FACTOR;
}

float getReverseDuty() {
  return getDriveDuty() * REVERSE_DUTY_FACTOR;
}

char toUpperChar(char c) {
  if (c >= 'a' && c <= 'z') {
    return c - 32;
  }

  return c;
}

bool equalsIgnoreCase(const char* a, const char* b) {
  if (a == nullptr || b == nullptr) {
    return false;
  }

  while (*a && *b) {
    char ca = toUpperChar(*a);
    char cb = toUpperChar(*b);

    if (ca != cb) {
      return false;
    }

    a++;
    b++;
  }

  return *a == '\0' && *b == '\0';
}

void markValidPcCommand() {
  lastValidPcCommandMs = millis();
}

// --------------------------------------------------
// Protocol reply helpers
// --------------------------------------------------

void pcAck(const char* message) {
  PC_SERIAL.print("<ACK,");
  PC_SERIAL.print(message);
  PC_SERIAL.println(">");
}

void pcErr(const char* message) {
  PC_SERIAL.print("<ERR,");
  PC_SERIAL.print(message);
  PC_SERIAL.println(">");
}

void pcEvent(const char* message) {
  PC_SERIAL.print("<EVT,");
  PC_SERIAL.print(message);
  PC_SERIAL.println(">");
}

void pcWarn(const char* message) {
  PC_SERIAL.print("<WARN,");
  PC_SERIAL.print(message);
  PC_SERIAL.println(">");
}

// --------------------------------------------------
// Status
// --------------------------------------------------

void sendStatusFrame() {
  PC_SERIAL.print("<STAT,EN=");
  PC_SERIAL.print(driveEnabled ? 1 : 0);

  PC_SERIAL.print(",MODE_SET=");
  PC_SERIAL.print(modeSelected ? 1 : 0);

  PC_SERIAL.print(",MODE=");
  PC_SERIAL.print(modeSelected ? drivingModeToString(drivingMode) : "NONE");

  PC_SERIAL.print(",MOTION=");
  PC_SERIAL.print(motionToString(motion));

  PC_SERIAL.print(",L=");
  PC_SERIAL.print(leftTarget, 3);

  PC_SERIAL.print(",R=");
  PC_SERIAL.print(rightTarget, 3);

  PC_SERIAL.print(",PENDING=");
  PC_SERIAL.print(transitionPending ? 1 : 0);

  PC_SERIAL.print(",TIMEOUT=");
  PC_SERIAL.print(timeoutLatched ? 1 : 0);

  PC_SERIAL.print(",TIMEOUT_MS=");
  PC_SERIAL.print(PC_TIMEOUT_MS);

  PC_SERIAL.print(",EXPECTED_PERIOD_MS=");
  PC_SERIAL.print(EXPECTED_PC_COMMAND_PERIOD_MS);

  PC_SERIAL.print(",DRY=");
  PC_SERIAL.print(DRY_RUN ? 1 : 0);

  PC_SERIAL.println(">");
}

// --------------------------------------------------
// VESC wrapper functions
// --------------------------------------------------

void sendLeftCommand(float duty) {
  if (DRY_RUN) {
    PC_SERIAL.print("<DRY,L,DUTY=");
    PC_SERIAL.print(duty, 3);
    PC_SERIAL.println(">");
    return;
  }

  leftVesc.setDuty(duty);
}

void sendRightCommand(float duty) {
  if (DRY_RUN) {
    PC_SERIAL.print("<DRY,R,DUTY=");
    PC_SERIAL.print(duty, 3);
    PC_SERIAL.println(">");
    return;
  }

  rightVesc.setDuty(duty);
}

void sendKeepaliveBoth() {
  if (DRY_RUN) {
    return;
  }

  leftVesc.sendKeepalive();
  rightVesc.sendKeepalive();
}

// --------------------------------------------------
// Movement mapping
// --------------------------------------------------

bool getTargetsForMotion(MotionState wantedMotion, float &left, float &right) {
  float driveDuty = getDriveDuty();
  float reverseDuty = getReverseDuty();
  float turnDuty = getTurnDuty();

  switch (wantedMotion) {
    case FORWARD:
      left = driveDuty;
      right = driveDuty;
      return true;

    case REVERSE:
      left = -reverseDuty;
      right = -reverseDuty;
      return true;

    case LEFT:
      left = -turnDuty;
      right = turnDuty;
      return true;

    case RIGHT:
      left = turnDuty;
      right = -turnDuty;
      return true;

    case STOPPED:
      left = 0.0f;
      right = 0.0f;
      return true;

    default:
      left = 0.0f;
      right = 0.0f;
      return false;
  }
}

// --------------------------------------------------
// Motor state functions
// --------------------------------------------------

void rawStopMotors() {
  leftTarget = 0.0f;
  rightTarget = 0.0f;
  motion = STOPPED;

  sendLeftCommand(0.0f);
  sendRightCommand(0.0f);

  pcEvent("MOTORS_STOPPED");
}

void stopMotors() {
  transitionPending = false;
  rawStopMotors();
}

void applyMotors(float left, float right, MotionState newMotion) {
  leftTarget = left;
  rightTarget = right;
  motion = newMotion;

  sendLeftCommand(leftTarget);
  sendRightCommand(rightTarget);

  PC_SERIAL.print("<EVT,MOTION=");
  PC_SERIAL.print(motionToString(motion));
  PC_SERIAL.print(",L=");
  PC_SERIAL.print(leftTarget, 3);
  PC_SERIAL.print(",R=");
  PC_SERIAL.print(rightTarget, 3);
  PC_SERIAL.println(">");
}

void requestMotion(float left, float right, MotionState newMotion) {
  if (!driveEnabled) {
    pcErr("ENABLE_FIRST");
    return;
  }

  if (!modeSelected && newMotion != STOPPED) {
    pcErr("MODE_FIRST");
    return;
  }

  if (transitionPending) {
    pendingLeftTarget = left;
    pendingRightTarget = right;
    pendingMotion = newMotion;

    PC_SERIAL.print("<EVT,PENDING_REPLACED,MOTION=");
    PC_SERIAL.print(motionToString(pendingMotion));
    PC_SERIAL.println(">");

    return;
  }

  if (motion == STOPPED) {
    applyMotors(left, right, newMotion);
    return;
  }

  if (motion == newMotion) {
    applyMotors(left, right, newMotion);
    return;
  }

  PC_SERIAL.print("<EVT,MOTION_CHANGE,FROM=");
  PC_SERIAL.print(motionToString(motion));
  PC_SERIAL.print(",TO=");
  PC_SERIAL.print(motionToString(newMotion));
  PC_SERIAL.println(">");

  rawStopMotors();

  pendingLeftTarget = left;
  pendingRightTarget = right;
  pendingMotion = newMotion;

  transitionPending = true;
  transitionStartMs = millis();
}

void requestMotionState(MotionState wantedMotion) {
  float left = 0.0f;
  float right = 0.0f;

  if (!getTargetsForMotion(wantedMotion, left, right)) {
    pcErr("INVALID_MOTION");
    return;
  }

  requestMotion(left, right, wantedMotion);
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
    applyMotors(pendingLeftTarget, pendingRightTarget, pendingMotion);
  }
}

// --------------------------------------------------
// Drive and mode control
// --------------------------------------------------

void enableDrive() {
  driveEnabled = true;
  modeSelected = false;
  timeoutLatched = false;
  transitionPending = false;

  markValidPcCommand();
  rawStopMotors();

  pcAck("EN,1");
  pcEvent("WAITING_FOR_MODE");
}

void disableDrive() {
  stopMotors();

  driveEnabled = false;
  modeSelected = false;
  transitionPending = false;

  markValidPcCommand();

  pcAck("EN,0");
}

void setDrivingMode(DrivingMode newMode) {
  if (!driveEnabled) {
    pcErr("ENABLE_FIRST");
    return;
  }

  drivingMode = newMode;
  modeSelected = true;

  // Safer behavior:
  // if mode changes while moving, stop first.
  if (motion != STOPPED || transitionPending) {
    stopMotors();
  }

  markValidPcCommand();

  PC_SERIAL.print("<ACK,MODE,");
  PC_SERIAL.print(drivingModeToString(drivingMode));
  PC_SERIAL.println(">");

  PC_SERIAL.print("<EVT,BASE_DUTY=");
  PC_SERIAL.print(getDriveDuty(), 3);
  PC_SERIAL.println(">");
}

// --------------------------------------------------
// Telemetry
// --------------------------------------------------

void sendTelemetryFrame() {
  if (DRY_RUN) {
    PC_SERIAL.println("<TEL,DRY=1>");
    return;
  }

  bool leftOk = leftVesc.getVescValues();
  bool rightOk = rightVesc.getVescValues();

  PC_SERIAL.print("<TEL,L_OK=");
  PC_SERIAL.print(leftOk ? 1 : 0);

  if (leftOk) {
    PC_SERIAL.print(",L_RPM=");
    PC_SERIAL.print(leftVesc.data.rpm);

    PC_SERIAL.print(",L_VIN=");
    PC_SERIAL.print(leftVesc.data.inpVoltage, 2);
  }

  PC_SERIAL.print(",R_OK=");
  PC_SERIAL.print(rightOk ? 1 : 0);

  if (rightOk) {
    PC_SERIAL.print(",R_RPM=");
    PC_SERIAL.print(rightVesc.data.rpm);

    PC_SERIAL.print(",R_VIN=");
    PC_SERIAL.print(rightVesc.data.inpVoltage, 2);
  }

  PC_SERIAL.println(">");
}

// --------------------------------------------------
// PC protocol handler
// --------------------------------------------------

void handlePcFrame(char* frame) {
  char* cmd = strtok(frame, ",");

  if (cmd == nullptr) {
    pcErr("EMPTY_FRAME");
    return;
  }

  // <STATUS>
  if (equalsIgnoreCase(cmd, "STATUS")) {
    markValidPcCommand();
    sendStatusFrame();
    return;
  }

  // <TEL>
  if (equalsIgnoreCase(cmd, "TEL")) {
    markValidPcCommand();
    sendTelemetryFrame();
    return;
  }

  // <EN,1> or <EN,0>
  if (equalsIgnoreCase(cmd, "EN")) {
    char* arg = strtok(nullptr, ",");

    if (arg == nullptr) {
      pcErr("EN_MISSING_ARG");
      return;
    }

    if (strcmp(arg, "1") == 0) {
      enableDrive();
      return;
    }

    if (strcmp(arg, "0") == 0) {
      disableDrive();
      return;
    }

    pcErr("EN_BAD_ARG");
    return;
  }

  // After timeout, require enable again.
  if (timeoutLatched) {
    pcErr("TIMEOUT_SEND_EN_FIRST");
    return;
  }

  // <MODE,2>, <MODE,5>, <MODE,10>
  if (equalsIgnoreCase(cmd, "MODE")) {
    char* arg = strtok(nullptr, ",");

    if (arg == nullptr) {
      pcErr("MODE_MISSING_ARG");
      return;
    }

    int modeValue = atoi(arg);

    if (modeValue == 2) {
      setDrivingMode(MODE_2_KMH);
      return;
    }

    if (modeValue == 5) {
      setDrivingMode(MODE_5_KMH);
      return;
    }

    if (modeValue == 10) {
      setDrivingMode(MODE_10_KMH);
      return;
    }

    pcErr("MODE_BAD_ARG");
    return;
  }

  // <MOVE,F>, <MOVE,B>, <MOVE,L>, <MOVE,R>, <MOVE,S>
  if (equalsIgnoreCase(cmd, "MOVE")) {
    char* arg = strtok(nullptr, ",");

    if (arg == nullptr) {
      pcErr("MOVE_MISSING_ARG");
      return;
    }

    char moveCmd = toUpperChar(arg[0]);

    // This is the main command that should arrive every 50 ms.
    markValidPcCommand();

    switch (moveCmd) {
      case 'F':
        requestMotionState(FORWARD);
        pcAck("MOVE,F");
        return;

      case 'B':
        requestMotionState(REVERSE);
        pcAck("MOVE,B");
        return;

      case 'L':
        requestMotionState(LEFT);
        pcAck("MOVE,L");
        return;

      case 'R':
        requestMotionState(RIGHT);
        pcAck("MOVE,R");
        return;

      case 'S':
        requestMotionState(STOPPED);
        pcAck("MOVE,S");
        return;

      default:
        pcErr("MOVE_BAD_ARG");
        return;
    }
  }

  pcErr("UNKNOWN_CMD");
}

// --------------------------------------------------
// Serial receiving
// --------------------------------------------------

void readPcSerial() {
  while (PC_SERIAL.available() > 0) {
    char c = PC_SERIAL.read();

    if (c == '<') {
      receivingFrame = true;
      pcRxIndex = 0;
      memset(pcRxBuffer, 0, sizeof(pcRxBuffer));
      continue;
    }

    if (c == '>') {
      if (receivingFrame) {
        pcRxBuffer[pcRxIndex] = '\0';
        receivingFrame = false;
        handlePcFrame(pcRxBuffer);
      }

      continue;
    }

    if (receivingFrame) {
      if (pcRxIndex < PC_RX_BUFFER_SIZE - 1) {
        pcRxBuffer[pcRxIndex++] = c;
      } else {
        receivingFrame = false;
        pcRxIndex = 0;
        pcErr("FRAME_TOO_LONG");
      }

      continue;
    }
  }
}

// --------------------------------------------------
// PC timeout
// --------------------------------------------------

void checkPcTimeout() {
  if (!driveEnabled) {
    return;
  }

  unsigned long now = millis();

  if (now - lastValidPcCommandMs > PC_TIMEOUT_MS) {
    transitionPending = false;

    rawStopMotors();

    driveEnabled = false;
    modeSelected = false;
    timeoutLatched = true;

    pcWarn("PC_TIMEOUT_500MS");
    pcEvent("DRIVE_DISABLED_AFTER_TIMEOUT");
  }
}

// --------------------------------------------------
// Setup and loop
// --------------------------------------------------

void setup() {
  PC_SERIAL.begin(115200);
  while (!PC_SERIAL) {;}

  LEFT_VESC_SERIAL.begin(115200);
  RIGHT_VESC_SERIAL.begin(115200);

  leftVesc.setSerialPort(&LEFT_VESC_SERIAL);
  rightVesc.setSerialPort(&RIGHT_VESC_SERIAL);

  lastValidPcCommandMs = millis();

  PC_SERIAL.println();
  PC_SERIAL.println("<BOOT,CHAIR_UART_PROTOCOL_READY>");
  PC_SERIAL.print("<BOOT,EXPECTED_COMMAND_PERIOD_MS=");
  PC_SERIAL.print(EXPECTED_PC_COMMAND_PERIOD_MS);
  PC_SERIAL.println(">");
  PC_SERIAL.print("<BOOT,TIMEOUT_MS=");
  PC_SERIAL.print(PC_TIMEOUT_MS);
  PC_SERIAL.println(">");
  PC_SERIAL.print("<BOOT,DRY_RUN=");
  PC_SERIAL.print(DRY_RUN ? 1 : 0);
  PC_SERIAL.println(">");

  rawStopMotors();
  sendStatusFrame();
}

void loop() {
  readPcSerial();

  processPendingTransition();

  checkPcTimeout();

  if (driveEnabled && (millis() - lastKeepAliveMs > KEEPALIVE_MS)) {
    lastKeepAliveMs = millis();
    sendKeepaliveBoth();
  }
}