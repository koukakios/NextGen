#include <Arduino.h>
#include <math.h>

// --------------------------------------------------
// SIMPLE wheelchair VESC CAN test code
// Arduino GIGA + CAN transceiver/shield + VESC
//
// PC/Python sends one command byte:
//   0 = stop
//   1 = forward slow
//   2 = forward medium
//   3 = forward fast
//   4 = right
//   5 = left
//   6 = status
//   7 = emergency stop
//
// IMPORTANT:
// - Put this file as src/main.cpp
// - Do NOT keep another .cpp file with setup() and loop() inside src/
// - Wheels off the ground for testing
// --------------------------------------------------

#ifndef ARDUINO_GIGA
#error This code is for Arduino GIGA R1 WiFi.
#endif

// Required by ACANFD_GIGA_R1. Must be before the include.
// We use FDCAN2, so FDCAN2 gets RAM and FDCAN1 gets 0.
static const uint32_t FDCAN1_MESSAGE_RAM_WORD_SIZE = 0;
static const uint32_t FDCAN2_MESSAGE_RAM_WORD_SIZE = 2560;

#include <ACANFD_GIGA_R1.h>
#define VESC_CAN fdcan2

// -------------------- User settings --------------------

constexpr uint32_t CAN_BITRATE = 500000;

// These must match VESC Tool.
constexpr uint8_t LEFT_VESC_ID  = 1;
constexpr uint8_t RIGHT_VESC_ID = 2;

// CAN transceiver standby pin on your shield.
// MCP2562: LOW = normal mode, HIGH = standby.
constexpr uint8_t CAN_STBY_PIN = 7;

// Relay / brake release pin.
// If your relay works backwards, swap RELAY_ON and RELAY_OFF.
constexpr uint8_t MOTOR_RELAY_PIN = A1;
constexpr uint8_t RELAY_ON  = LOW;
constexpr uint8_t RELAY_OFF = HIGH;

// Safe low test duties. Increase only after it works.
constexpr float DUTY_SLOW = 0.45f;
constexpr float DUTY_MED  = 0.50f;
constexpr float DUTY_FAST = 0.55f;
constexpr float DUTY_TURN = 0.40f;

// Safety timeout. Python repeats movement commands below this time.
constexpr unsigned long COMMAND_TIMEOUT_MS = 500;
constexpr unsigned long SEND_EVERY_MS = 20;

// Set this true only if you want CAN RX spam every 500 ms.
constexpr bool DEBUG_CAN_RX_PRINT = false;

// VESC CAN command IDs.
constexpr uint32_t CAN_PACKET_SET_DUTY = 0;

// -------------------- State --------------------

bool canReady = false;
bool driveEnabled = false;

float leftDuty = 0.0f;
float rightDuty = 0.0f;

unsigned long lastCommandMs = 0;
unsigned long lastSendMs = 0;

uint32_t canErrorCode = 0;
uint32_t canRamNeeded = 0;

uint32_t canRxCount = 0;
bool haveLastCanRxFrame = false;
CANFDMessage lastCanRxFrame;
unsigned long lastCanRxPrintMs = 0;

uint32_t canTxOk = 0;
uint32_t canTxFail = 0;
uint32_t lastCanTxStatus = 0;

// -------------------- Helpers --------------------

void writeInt32BE(uint8_t *data, int32_t value) {
  data[0] = uint8_t((uint32_t(value) >> 24) & 0xFF);
  data[1] = uint8_t((uint32_t(value) >> 16) & 0xFF);
  data[2] = uint8_t((uint32_t(value) >> 8) & 0xFF);
  data[3] = uint8_t(uint32_t(value) & 0xFF);
}

float clampDuty(float duty) {
  if (duty > 0.95f) return 0.95f;
  if (duty < -0.95f) return -0.95f;
  return duty;
}

uint32_t makeVescCanId(uint32_t packetId, uint8_t vescId) {
  // VESC extended CAN ID = command in bits 15..8, VESC ID in bits 7..0.
  return (packetId << 8) | uint32_t(vescId);
}

void setRelay(bool on) {
  digitalWrite(MOTOR_RELAY_PIN, on ? RELAY_ON : RELAY_OFF);
}

void printHexByte(uint8_t value) {
  if (value < 16) Serial.print('0');
  Serial.print(value, HEX);
}

void printCanFrame(const CANFDMessage &frame) {
  Serial.print("CAN RX id=0x");
  Serial.print(frame.id, HEX);
  Serial.print(" ext=");
  Serial.print(frame.ext ? 1 : 0);
  Serial.print(" len=");
  Serial.print(frame.len);

  if (frame.ext) {
    uint8_t vescCommand = uint8_t((frame.id >> 8) & 0xFF);
    uint8_t vescId = uint8_t(frame.id & 0xFF);
    Serial.print(" vescCmd=");
    Serial.print(vescCommand);
    Serial.print(" vescId=");
    Serial.print(vescId);
  }

  Serial.print(" data=");
  uint8_t dataLength = frame.len;
  if (dataLength > 8) dataLength = 8;

  for (uint8_t i = 0; i < dataLength; i++) {
    if (i > 0) Serial.print(' ');
    printHexByte(frame.data[i]);
  }

  Serial.println();
}

// -------------------- CAN setup/read/send --------------------

bool setupCan() {
  pinMode(CAN_STBY_PIN, OUTPUT);
  digitalWrite(CAN_STBY_PIN, LOW);  // LOW = normal mode for MCP2562
  delay(10);

  ACANFD_GIGA_R1_Settings settings(CAN_BITRATE, DataBitRateFactor::x1);

  // Disable retransmission during debugging so old failed frames do not clog TX.
  settings.mEnableRetransmission = false;

  // Controller runs FDCAN peripheral, but we send classic CAN data frames.
  settings.mModuleMode = ACANFD_GIGA_R1_Settings::NORMAL_FD;

  settings.mHardwareRxFIFO0Size = 20;
  settings.mHardwareRxFIFO0Payload = ACANFD_GIGA_R1_Settings::PAYLOAD_8_BYTES;
  settings.mHardwareRxFIFO1Size = 0;

  settings.mHardwareTransmitTxFIFOSize = 10;
  settings.mHardwareDedicacedTxBufferCount = 0;
  settings.mHardwareTransmitBufferPayload = ACANFD_GIGA_R1_Settings::PAYLOAD_8_BYTES;

  settings.mDriverTransmitFIFOSize = 10;
  settings.mDriverReceiveFIFO0Size = 20;
  settings.mDriverReceiveFIFO1Size = 0;

  // Your RX is proven working on PB_5 because you receive VESC frames.
  settings.mRxPin = PB_5;

  // Try PB_6 for TX because RX works but VESC does not react to Arduino commands.
  // If this still does not move the motor, try PB_13 here instead.
  settings.mTxPin = PB_13;
  // settings.mTxPin = PB_13;

  canErrorCode = VESC_CAN.beginFD(settings);
  canRamNeeded = VESC_CAN.messageRamRequiredMinimumSize();

  Serial.print("CAN RAM needed=");
  Serial.println(canRamNeeded);

  if (canErrorCode == 0) {
    Serial.println("CAN OK");
    return true;
  }

  Serial.print("CAN FAILED error=0x");
  Serial.println(canErrorCode, HEX);
  return false;
}

void readCanFrames() {
  if (!canReady) return;

  CANFDMessage rxFrame;

  while (VESC_CAN.receiveFD0(rxFrame)) {
    canRxCount++;
    lastCanRxFrame = rxFrame;
    haveLastCanRxFrame = true;
  }

  if (!DEBUG_CAN_RX_PRINT) return;

  if (millis() - lastCanRxPrintMs >= 500) {
    lastCanRxPrintMs = millis();
    Serial.print("CAN RX count=");
    Serial.print(canRxCount);

    if (haveLastCanRxFrame) {
      Serial.print(" last: ");
      printCanFrame(lastCanRxFrame);
    } else {
      Serial.println(" no frames yet");
    }
  }
}

bool sendVescDuty(uint8_t vescId, float duty) {
  if (!canReady) {
    canTxFail++;
    lastCanTxStatus = 0xFFFFFFFF;
    return false;
  }

  duty = clampDuty(duty);

  uint8_t payload[4];
  int32_t scaledDuty = int32_t(lroundf(duty * 100000.0f));
  writeInt32BE(payload, scaledDuty);

  CANFDMessage frame;
  frame.idx = 0;
  frame.id = makeVescCanId(CAN_PACKET_SET_DUTY, vescId);
  frame.ext = true;
  frame.type = CANFDMessage::CAN_DATA;
  frame.len = 4;

  for (uint8_t i = 0; i < 8; i++) frame.data[i] = 0;
  for (uint8_t i = 0; i < 4; i++) frame.data[i] = payload[i];

  uint32_t status = VESC_CAN.tryToSendReturnStatusFD(frame);
  lastCanTxStatus = status;

  if (status == 0) {
    canTxOk++;
    return true;
  }

  canTxFail++;

  Serial.print("CAN TX FAIL to VESC ");
  Serial.print(vescId);
  Serial.print(" status=0x");
  Serial.println(status, HEX);

  return false;
}

void sendBothMotors() {
  sendVescDuty(LEFT_VESC_ID, leftDuty);
  sendVescDuty(RIGHT_VESC_ID, rightDuty);
}

// -------------------- Movement --------------------

void stopMotors() {
  driveEnabled = false;
  leftDuty = 0.0f;
  rightDuty = 0.0f;

  // Send zero first, then disable relay.
  sendBothMotors();
  delay(5);
  setRelay(false);

  Serial.println("STOP");
}

void moveMotors(float left, float right) {
  driveEnabled = true;
  leftDuty = left;
  rightDuty = right;
  lastCommandMs = millis();

  setRelay(true);
  sendBothMotors();

  Serial.print("MOVE L=");
  Serial.print(leftDuty, 3);
  Serial.print(" R=");
  Serial.println(rightDuty, 3);
}

void printStatus() {
  Serial.print("enabled=");
  Serial.print(driveEnabled ? 1 : 0);

  Serial.print(" leftDuty=");
  Serial.print(leftDuty, 3);

  Serial.print(" rightDuty=");
  Serial.print(rightDuty, 3);

  Serial.print(" canReady=");
  Serial.print(canReady ? 1 : 0);

  Serial.print(" canError=0x");
  Serial.print(canErrorCode, HEX);

  Serial.print(" ramNeeded=");
  Serial.print(canRamNeeded);

  Serial.print(" canRxCount=");
  Serial.print(canRxCount);

  Serial.print(" txOk=");
  Serial.print(canTxOk);

  Serial.print(" txFail=");
  Serial.print(canTxFail);

  Serial.print(" lastTxStatus=0x");
  Serial.println(lastCanTxStatus, HEX);

  if (haveLastCanRxFrame) {
    Serial.print("last ");
    printCanFrame(lastCanRxFrame);
  }
}

// -------------------- PC command handling --------------------

uint8_t normalizeCommand(uint8_t b) {
  // Raw byte commands 0x00..0x07.
  if (b <= 7) return b;

  // ASCII commands from Serial Monitor/Python input: '0'..'7'.
  if (b >= '0' && b <= '7') return b - '0';

  return 255;
}

void handleCommand(uint8_t rawByte) {
  uint8_t cmd = normalizeCommand(rawByte);
  if (cmd == 255) return;

  switch (cmd) {
    case 0:
      stopMotors();
      break;

    case 1:
      moveMotors(DUTY_SLOW, DUTY_SLOW);
      break;

    case 2:
      moveMotors(DUTY_MED, DUTY_MED);
      break;

    case 3:
      moveMotors(DUTY_FAST, DUTY_FAST);
      break;

    case 4:
      // Right turn. If direction is wrong, swap signs.
      moveMotors(DUTY_TURN, -DUTY_TURN);
      break;

    case 5:
      // Left turn. If direction is wrong, swap signs.
      moveMotors(-DUTY_TURN, DUTY_TURN);
      break;

    case 6:
      printStatus();
      break;

    case 7:
      stopMotors();
      Serial.println("EMERGENCY STOP");
      break;
  }
}

// -------------------- Arduino setup/loop --------------------

void setup() {
  Serial.begin(115200);
  while (!Serial) {}

  pinMode(MOTOR_RELAY_PIN, OUTPUT);
  setRelay(false);

  canReady = setupCan();

  stopMotors();

  Serial.println("Ready");
  Serial.println("Commands: 1 slow | 2 medium | 3 fast | 4 right | 5 left | 0 stop | 6 status | 7 estop");
}

void loop() {
  while (Serial.available() > 0) {
    handleCommand(uint8_t(Serial.read()));
  }

  readCanFrames();

  if (driveEnabled && millis() - lastCommandMs > COMMAND_TIMEOUT_MS) {
    Serial.println("TIMEOUT");
    stopMotors();
  }

  if (driveEnabled && millis() - lastSendMs > SEND_EVERY_MS) {
    lastSendMs = millis();
    sendBothMotors();
  }
}
