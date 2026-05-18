#pragma once

#include <Arduino.h>
#include <math.h>

// Structured reading/refactor copy of main.cpp.
//
// This file is intentionally not included by main.cpp yet. It is here so the
// CAN wheelchair sketch can be read as one controller with clear sections:
// boot, PC commands, safety, motion, CAN transmit, CAN receive, and status.
//
// If you later want to make this active code, replace main.cpp with a tiny
// wrapper that creates VescCanWheelchairController and calls begin()/update().

#ifndef ARDUINO_GIGA
#error This sketch is intended for Arduino GIGA R1 WiFi.
#endif

// ACANFD_GIGA_R1 needs these constants before the library include.
// NEXT shield uses FDCAN2, not FDCAN1.
static const uint32_t FDCAN1_MESSAGE_RAM_WORD_SIZE = 0;
static const uint32_t FDCAN2_MESSAGE_RAM_WORD_SIZE = 2560;

#include <ACANFD_GIGA_R1.h>

class VescCanWheelchairController {
public:
  void begin() {
    Serial.begin(115200);
    while (!Serial) {;}

    setupMotorRelay();
    state.canReady = setupCan();
    state.lastValidMovementCommandMs = millis();

    printBootBanner();

    if (!state.canReady && !Config::DryRun) {
      pcWarn("CAN_NOT_READY_OUTPUT_DISABLED");
    }

    rawStopMotors();
    setMotorRelay(false);
    sendStatusFrame();
  }

  void update() {
    readPcSerial();
    readCan();
    processPendingTransition();
    checkPcTimeout();
    refreshKeepaliveIfNeeded();
    handleCanFaultShutdown();
  }

private:
  struct Config {
    static constexpr bool DryRun = false;

    static constexpr uint32_t CanBitrate = 500000;
    static constexpr uint8_t LeftVescId = 1;
    static constexpr uint8_t RightVescId = 2;

    static constexpr uint8_t CanStandbyPin = 7;
    static constexpr uint8_t CanStandbyNormalLevel = LOW;
    static constexpr uint8_t CanStandbyLevel = HIGH;

    static constexpr uint8_t MotorRelayPin = A1;
    static constexpr uint8_t MotorRelayActiveLevel = LOW;
    static constexpr uint8_t MotorRelayInactiveLevel = HIGH;

    static constexpr unsigned long ExpectedPcCommandPeriodMs = 50;
    static constexpr unsigned long PcTimeoutMs = 500;
    static constexpr unsigned long KeepaliveMs = 20;
    static constexpr unsigned long StopBeforeChangeMs = 150;

    static constexpr float DutyMode1 = 0.30f;
    static constexpr float DutyMode2 = 0.40f;
    static constexpr float DutyMode3 = 0.50f;
    static constexpr float TurnDutyFactor = 0.80f;
    static constexpr float ReverseDutyFactor = 0.70f;
  };

  enum class MotionState : uint8_t {
    Stopped,
    Forward,
    Reverse,
    Left,
    Right
  };

  enum class DrivingMode : uint8_t {
    Mode1,
    Mode2,
    Mode3
  };

  enum class BinaryCommand : uint8_t {
    Stop = 0b000,
    Mode1 = 0b001,
    Mode2 = 0b010,
    Mode3 = 0b011,
    Right = 0b100,
    Left = 0b101,
    Status = 0b110,
    Estop = 0b111
  };

  enum VescCanPacketId : uint32_t {
    CAN_PACKET_SET_DUTY = 0,
    CAN_PACKET_STATUS = 9,
    CAN_PACKET_STATUS_5 = 27
  };

  struct WheelTargets {
    float left = 0.0f;
    float right = 0.0f;
  };

  struct TelemetryCache {
    bool seenStatus = false;
    bool seenStatus5 = false;
    unsigned long lastRxMs = 0;
    int32_t rpm = 0;
    float current = 0.0f;
    float duty = 0.0f;
    float vin = 0.0f;
  };

  struct RuntimeState {
    bool canReady = false;
    bool canFaultLatched = false;
    uint32_t lastCanTxStatus = 0;
    uint32_t canTxFailCount = 0;
    uint32_t canRxCount = 0;

    bool motorRelayActive = false;
    bool driveEnabled = false;
    bool modeSelected = false;
    bool timeoutLatched = false;
    bool emergencyLatched = false;

    MotionState motion = MotionState::Stopped;
    DrivingMode drivingMode = DrivingMode::Mode1;

    float leftTarget = 0.0f;
    float rightTarget = 0.0f;

    unsigned long lastValidMovementCommandMs = 0;
    unsigned long lastKeepaliveMs = 0;

    bool transitionPending = false;
    unsigned long transitionStartMs = 0;

    float pendingLeftTarget = 0.0f;
    float pendingRightTarget = 0.0f;
    MotionState pendingMotion = MotionState::Stopped;
  };

  RuntimeState state;
  TelemetryCache leftTelemetry;
  TelemetryCache rightTelemetry;

  // --------------------------------------------------
  // Names and small conversions
  // --------------------------------------------------

  const char* motionToString(MotionState motion) const {
    switch (motion) {
      case MotionState::Stopped: return "STOP";
      case MotionState::Forward: return "FORWARD";
      case MotionState::Reverse: return "REVERSE";
      case MotionState::Left:    return "LEFT";
      case MotionState::Right:   return "RIGHT";
      default:                   return "UNKNOWN";
    }
  }

  const char* drivingModeToString(DrivingMode mode) const {
    switch (mode) {
      case DrivingMode::Mode1: return "MODE1";
      case DrivingMode::Mode2: return "MODE2";
      case DrivingMode::Mode3: return "MODE3";
      default:                 return "UNKNOWN";
    }
  }

  float getDriveDuty() const {
    switch (state.drivingMode) {
      case DrivingMode::Mode1:
        return Config::DutyMode1;

      case DrivingMode::Mode2:
        return Config::DutyMode2;

      case DrivingMode::Mode3:
        return Config::DutyMode3;

      default:
        return Config::DutyMode1;
    }
  }

  float getTurnDuty() const {
    return getDriveDuty() * Config::TurnDutyFactor;
  }

  float getReverseDuty() const {
    return getDriveDuty() * Config::ReverseDutyFactor;
  }

  void markValidMovementCommand() {
    state.lastValidMovementCommandMs = millis();
  }

  static int16_t readInt16BE(const uint8_t* data) {
    return int16_t((uint16_t(data[0]) << 8) | uint16_t(data[1]));
  }

  static int32_t readInt32BE(const uint8_t* data) {
    return int32_t(
      (uint32_t(data[0]) << 24) |
      (uint32_t(data[1]) << 16) |
      (uint32_t(data[2]) << 8) |
      uint32_t(data[3])
    );
  }

  static void writeInt32BE(uint8_t* data, int32_t value) {
    data[0] = uint8_t((uint32_t(value) >> 24) & 0xFF);
    data[1] = uint8_t((uint32_t(value) >> 16) & 0xFF);
    data[2] = uint8_t((uint32_t(value) >> 8) & 0xFF);
    data[3] = uint8_t(uint32_t(value) & 0xFF);
  }

  static uint32_t makeVescCanId(uint32_t packetId, uint8_t vescId) {
    return ((packetId & 0x1FFFFF) << 8) | uint32_t(vescId);
  }

  static uint32_t getVescPacketIdFromCanId(uint32_t extendedId) {
    return extendedId >> 8;
  }

  static uint8_t getVescSourceIdFromCanId(uint32_t extendedId) {
    return uint8_t(extendedId & 0xFF);
  }

  static float clampDuty(float duty) {
    if (duty > 0.95f) {
      return 0.95f;
    }

    if (duty < -0.95f) {
      return -0.95f;
    }

    return duty;
  }

  // --------------------------------------------------
  // PC protocol output
  // --------------------------------------------------

  void pcAck(const char* message) const {
    Serial.print("<ACK,");
    Serial.print(message);
    Serial.println(">");
  }

  void pcErr(const char* message) const {
    Serial.print("<ERR,");
    Serial.print(message);
    Serial.println(">");
  }

  void pcEvent(const char* message) const {
    Serial.print("<EVT,");
    Serial.print(message);
    Serial.println(">");
  }

  void pcWarn(const char* message) const {
    Serial.print("<WARN,");
    Serial.print(message);
    Serial.println(">");
  }

  // --------------------------------------------------
  // Boot and relay control
  // --------------------------------------------------

  void printBootBanner() const {
    Serial.println();
    Serial.println("<BOOT,CHAIR_CAN_RAW_BYTE_TEST_READY>");
    Serial.println("<BOOT,THIS_USES_SAME_RAW_BYTE_LOGIC_AS_UART>");
    Serial.println("<BOOT,0x00=STOP>");
    Serial.println("<BOOT,0x01=MODE1_FORWARD>");
    Serial.println("<BOOT,0x02=MODE2_FORWARD>");
    Serial.println("<BOOT,0x03=MODE3_FORWARD>");
    Serial.println("<BOOT,0x04=RIGHT>");
    Serial.println("<BOOT,0x05=LEFT>");
    Serial.println("<BOOT,0x06=STATUS>");
    Serial.println("<BOOT,0x07=ESTOP>");

    Serial.print("<BOOT,LEFT_VESC_ID=");
    Serial.print(Config::LeftVescId);
    Serial.println(">");

    Serial.print("<BOOT,RIGHT_VESC_ID=");
    Serial.print(Config::RightVescId);
    Serial.println(">");

    Serial.print("<BOOT,CAN_BITRATE=");
    Serial.print(Config::CanBitrate);
    Serial.println(">");

    Serial.println("<BOOT,CAN_PERIPHERAL=FDCAN2>");

    Serial.print("<BOOT,CAN_STBY_PIN=D");
    Serial.print(Config::CanStandbyPin);
    Serial.println(">");

    Serial.print("<BOOT,EXPECTED_COMMAND_PERIOD_MS=");
    Serial.print(Config::ExpectedPcCommandPeriodMs);
    Serial.println(">");

    Serial.print("<BOOT,TIMEOUT_MS=");
    Serial.print(Config::PcTimeoutMs);
    Serial.println(">");

    Serial.print("<BOOT,TEST_DUTY_MODE1=");
    Serial.print(Config::DutyMode1, 3);
    Serial.println(">");

    Serial.print("<BOOT,TEST_DUTY_MODE2=");
    Serial.print(Config::DutyMode2, 3);
    Serial.println(">");

    Serial.print("<BOOT,TEST_DUTY_MODE3=");
    Serial.print(Config::DutyMode3, 3);
    Serial.println(">");

    Serial.print("<BOOT,DRY_RUN=");
    Serial.print(Config::DryRun ? 1 : 0);
    Serial.println(">");
  }

  void setupMotorRelay() {
    digitalWrite(Config::MotorRelayPin, Config::MotorRelayInactiveLevel);
    pinMode(Config::MotorRelayPin, OUTPUT);
    digitalWrite(Config::MotorRelayPin, Config::MotorRelayInactiveLevel);

    state.motorRelayActive = false;
    Serial.println("<BOOT,MOTOR_RELAY_OFF>");
  }

  void setMotorRelay(bool active) {
    if (Config::DryRun) {
      state.motorRelayActive = false;
      Serial.print("<DRY,MOTOR_RELAY_REQUEST=");
      Serial.print(active ? 1 : 0);
      Serial.println(">");
      return;
    }

    digitalWrite(
      Config::MotorRelayPin,
      active ? Config::MotorRelayActiveLevel : Config::MotorRelayInactiveLevel
    );

    state.motorRelayActive = active;

    Serial.print("<EVT,MOTOR_RELAY=");
    Serial.print(state.motorRelayActive ? 1 : 0);
    Serial.println(">");
  }

  // --------------------------------------------------
  // CAN setup
  // --------------------------------------------------

  void setupCanTransceiver() const {
    pinMode(Config::CanStandbyPin, OUTPUT);
    digitalWrite(Config::CanStandbyPin, Config::CanStandbyNormalLevel);
    delay(10);

    Serial.println("<BOOT,CAN_TRANSCEIVER_STBY_LOW>");
  }

  bool setupCan() const {
    if (Config::DryRun) {
      Serial.println("<BOOT,CAN_DRY_RUN>");
      return true;
    }

    setupCanTransceiver();

    ACANFD_GIGA_R1_Settings settings(Config::CanBitrate, DataBitRateFactor::x1);

    // The STM32 peripheral runs in FD mode, but VESC frames are classic CAN.
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

    const uint32_t errorCode = fdcan2.beginFD(settings);

    Serial.print("<BOOT,FDCAN2_RAM_REQUIRED_WORDS=");
    Serial.print(fdcan2.messageRamRequiredMinimumSize());
    Serial.println(">");

    if (errorCode == 0) {
      Serial.print("<BOOT,CAN_OK,PERIPHERAL=FDCAN2,BITRATE=");
      Serial.print(Config::CanBitrate);
      Serial.println(">");
      return true;
    }

    Serial.print("<ERR,CAN_BEGIN_FAILED,PERIPHERAL=FDCAN2,CODE=0x");
    Serial.print(errorCode, HEX);
    Serial.println(">");

    digitalWrite(Config::CanStandbyPin, Config::CanStandbyLevel);
    return false;
  }

  // --------------------------------------------------
  // VESC CAN transmit
  // --------------------------------------------------

  bool sendVescCanFrame(uint8_t vescId, uint32_t packetId, const uint8_t* payload, uint8_t len) {
    if (len > 8) {
      pcErr("CAN_PAYLOAD_TOO_LONG");
      return false;
    }

    if (Config::DryRun) {
      printDryRunCanFrame(vescId, packetId, payload, len);
      return true;
    }

    if (!state.canReady) {
      state.canTxFailCount++;

      if (state.driveEnabled || state.motorRelayActive) {
        state.canFaultLatched = true;
      }

      pcErr("CAN_NOT_READY");
      return false;
    }

    CANFDMessage frame;
    frame.idx = 0;
    frame.id = makeVescCanId(packetId, vescId);
    frame.ext = true;
    frame.type = CANFDMessage::CAN_DATA;
    frame.len = len;

    for (uint8_t i = 0; i < len; i++) {
      frame.data[i] = payload[i];
    }

    state.lastCanTxStatus = fdcan2.tryToSendReturnStatusFD(frame);

    if (state.lastCanTxStatus != 0) {
      state.canTxFailCount++;

      if (state.driveEnabled || state.motorRelayActive) {
        state.canFaultLatched = true;
      }

      Serial.print("<ERR,CAN_TX_FAIL,STATUS=0x");
      Serial.print(state.lastCanTxStatus, HEX);
      Serial.println(">");

      return false;
    }

    return true;
  }

  void printDryRunCanFrame(uint8_t vescId, uint32_t packetId, const uint8_t* payload, uint8_t len) const {
    Serial.print("<DRY,CAN,ID=");
    Serial.print(vescId);
    Serial.print(",PACKET=");
    Serial.print(packetId);
    Serial.print(",LEN=");
    Serial.print(len);
    Serial.print(",DATA=");

    for (uint8_t i = 0; i < len; i++) {
      if (payload[i] < 16) {
        Serial.print('0');
      }
      Serial.print(payload[i], HEX);
    }

    Serial.println(">");
  }

  bool sendVescDuty(uint8_t vescId, float duty) {
    duty = clampDuty(duty);

    uint8_t payload[4];
    const int32_t scaledDuty = int32_t(lroundf(duty * 100000.0f));
    writeInt32BE(payload, scaledDuty);

    return sendVescCanFrame(vescId, CAN_PACKET_SET_DUTY, payload, sizeof(payload));
  }

  void sendLeftCommand(float duty) {
    if (Config::DryRun) {
      Serial.print("<DRY,L,DUTY=");
      Serial.print(duty, 3);
      Serial.println(">");
      return;
    }

    sendVescDuty(Config::LeftVescId, duty);
  }

  void sendRightCommand(float duty) {
    if (Config::DryRun) {
      Serial.print("<DRY,R,DUTY=");
      Serial.print(duty, 3);
      Serial.println(">");
      return;
    }

    sendVescDuty(Config::RightVescId, duty);
  }

  void refreshVescCommandsBoth() {
    sendVescDuty(Config::LeftVescId, state.leftTarget);
    sendVescDuty(Config::RightVescId, state.rightTarget);
  }

  void refreshKeepaliveIfNeeded() {
    if (!state.driveEnabled) {
      return;
    }

    if (millis() - state.lastKeepaliveMs > Config::KeepaliveMs) {
      state.lastKeepaliveMs = millis();
      refreshVescCommandsBoth();
    }
  }

  // --------------------------------------------------
  // VESC CAN receive and telemetry
  // --------------------------------------------------

  void readCan() {
    if (Config::DryRun || !state.canReady) {
      return;
    }

    CANFDMessage frame;

    while (fdcan2.receiveFD0(frame)) {
      parseVescStatusFrame(frame);
    }
  }

  void parseVescStatusFrame(const CANFDMessage& frame) {
    if (!frame.ext) {
      return;
    }

    const uint32_t packetId = getVescPacketIdFromCanId(frame.id);
    const uint8_t sourceId = getVescSourceIdFromCanId(frame.id);

    TelemetryCache* telemetry = telemetryForVescId(sourceId);

    if (telemetry == nullptr) {
      return;
    }

    state.canRxCount++;
    telemetry->lastRxMs = millis();

    if (packetId == CAN_PACKET_STATUS && frame.len >= 8) {
      telemetry->seenStatus = true;
      telemetry->rpm = readInt32BE(&frame.data[0]);
      telemetry->current = float(readInt16BE(&frame.data[4])) / 10.0f;
      telemetry->duty = float(readInt16BE(&frame.data[6])) / 1000.0f;
      return;
    }

    if (packetId == CAN_PACKET_STATUS_5 && frame.len >= 6) {
      telemetry->seenStatus5 = true;
      telemetry->vin = float(readInt16BE(&frame.data[4])) / 10.0f;
      return;
    }
  }

  TelemetryCache* telemetryForVescId(uint8_t sourceId) {
    if (sourceId == Config::LeftVescId) {
      return &leftTelemetry;
    }

    if (sourceId == Config::RightVescId) {
      return &rightTelemetry;
    }

    return nullptr;
  }

  // --------------------------------------------------
  // Status frame
  // --------------------------------------------------

  void sendStatusFrame() const {
    Serial.print("<STAT,EN=");
    Serial.print(state.driveEnabled ? 1 : 0);

    Serial.print(",MODE_SET=");
    Serial.print(state.modeSelected ? 1 : 0);

    Serial.print(",MODE=");
    Serial.print(state.modeSelected ? drivingModeToString(state.drivingMode) : "NONE");

    Serial.print(",MOTION=");
    Serial.print(motionToString(state.motion));

    Serial.print(",L=");
    Serial.print(state.leftTarget, 3);

    Serial.print(",R=");
    Serial.print(state.rightTarget, 3);

    Serial.print(",L_ID=");
    Serial.print(Config::LeftVescId);

    Serial.print(",R_ID=");
    Serial.print(Config::RightVescId);

    Serial.print(",PENDING=");
    Serial.print(state.transitionPending ? 1 : 0);

    Serial.print(",TIMEOUT=");
    Serial.print(state.timeoutLatched ? 1 : 0);

    Serial.print(",ESTOP=");
    Serial.print(state.emergencyLatched ? 1 : 0);

    Serial.print(",RELAY=");
    Serial.print(state.motorRelayActive ? 1 : 0);

    Serial.print(",CAN_READY=");
    Serial.print(state.canReady ? 1 : 0);

    Serial.print(",CAN_FAULT=");
    Serial.print(state.canFaultLatched ? 1 : 0);

    Serial.print(",CAN_BITRATE=");
    Serial.print(Config::CanBitrate);

    Serial.print(",CAN_TX_FAILS=");
    Serial.print(state.canTxFailCount);

    Serial.print(",CAN_LAST_TX_STATUS=0x");
    Serial.print(state.lastCanTxStatus, HEX);

    Serial.print(",CAN_RX=");
    Serial.print(state.canRxCount);

    Serial.print(",TIMEOUT_MS=");
    Serial.print(Config::PcTimeoutMs);

    Serial.print(",EXPECTED_PERIOD_MS=");
    Serial.print(Config::ExpectedPcCommandPeriodMs);

    Serial.print(",DRY=");
    Serial.print(Config::DryRun ? 1 : 0);

    printTelemetryStatus("L", leftTelemetry);
    printTelemetryStatus("R", rightTelemetry);

    Serial.println(">");
  }

  void printTelemetryStatus(const char* prefix, const TelemetryCache& telemetry) const {
    Serial.print(",");
    Serial.print(prefix);
    Serial.print("_SEEN=");
    Serial.print(telemetry.seenStatus ? 1 : 0);

    Serial.print(",");
    Serial.print(prefix);
    Serial.print("_RPM=");
    Serial.print(telemetry.rpm);

    Serial.print(",");
    Serial.print(prefix);
    Serial.print("_CURR=");
    Serial.print(telemetry.current, 1);

    Serial.print(",");
    Serial.print(prefix);
    Serial.print("_DUTY_FB=");
    Serial.print(telemetry.duty, 3);

    Serial.print(",");
    Serial.print(prefix);
    Serial.print("_VIN=");
    Serial.print(telemetry.vin, 1);

    Serial.print(",");
    Serial.print(prefix);
    Serial.print("_AGE_MS=");
    Serial.print(telemetry.lastRxMs == 0 ? 0 : millis() - telemetry.lastRxMs);
  }

  // --------------------------------------------------
  // Movement mapping and state machine
  // --------------------------------------------------

  bool getTargetsForMotion(MotionState wantedMotion, WheelTargets& targets) const {
    const float driveDuty = getDriveDuty();
    const float reverseDuty = getReverseDuty();
    const float turnDuty = getTurnDuty();

    switch (wantedMotion) {
      case MotionState::Forward:
        targets.left = driveDuty;
        targets.right = driveDuty;
        return true;

      case MotionState::Reverse:
        targets.left = -reverseDuty;
        targets.right = -reverseDuty;
        return true;

      case MotionState::Left:
        targets.left = -turnDuty;
        targets.right = turnDuty;
        return true;

      case MotionState::Right:
        targets.left = turnDuty;
        targets.right = -turnDuty;
        return true;

      case MotionState::Stopped:
        targets.left = 0.0f;
        targets.right = 0.0f;
        return true;

      default:
        targets.left = 0.0f;
        targets.right = 0.0f;
        return false;
    }
  }

  void rawStopMotors() {
    state.leftTarget = 0.0f;
    state.rightTarget = 0.0f;
    state.motion = MotionState::Stopped;

    sendLeftCommand(0.0f);
    sendRightCommand(0.0f);

    pcEvent("MOTORS_STOPPED");
  }

  void stopMotors() {
    state.transitionPending = false;
    rawStopMotors();
  }

  void applyMotors(float left, float right, MotionState newMotion) {
    state.leftTarget = left;
    state.rightTarget = right;
    state.motion = newMotion;

    sendLeftCommand(state.leftTarget);
    sendRightCommand(state.rightTarget);

    Serial.print("<EVT,MOTION=");
    Serial.print(motionToString(state.motion));
    Serial.print(",L=");
    Serial.print(state.leftTarget, 3);
    Serial.print(",R=");
    Serial.print(state.rightTarget, 3);
    Serial.println(">");
  }

  void requestMotion(float left, float right, MotionState newMotion) {
    if (!state.driveEnabled) {
      pcErr("DRIVE_NOT_ENABLED_INTERNAL");
      return;
    }

    if (!state.modeSelected && newMotion != MotionState::Stopped) {
      pcErr("MODE_NOT_SELECTED_INTERNAL");
      return;
    }

    if (!Config::DryRun && !state.canReady) {
      pcErr("CAN_NOT_READY_MOTION_BLOCKED");
      return;
    }

    if (state.canFaultLatched) {
      pcErr("CAN_FAULT_LATCHED_MOTION_BLOCKED");
      return;
    }

    if (state.transitionPending) {
      state.pendingLeftTarget = left;
      state.pendingRightTarget = right;
      state.pendingMotion = newMotion;

      Serial.print("<EVT,PENDING_REPLACED,MOTION=");
      Serial.print(motionToString(state.pendingMotion));
      Serial.println(">");
      return;
    }

    if (state.motion == MotionState::Stopped || state.motion == newMotion) {
      applyMotors(left, right, newMotion);
      return;
    }

    Serial.print("<EVT,MOTION_CHANGE,FROM=");
    Serial.print(motionToString(state.motion));
    Serial.print(",TO=");
    Serial.print(motionToString(newMotion));
    Serial.println(">");

    rawStopMotors();

    state.pendingLeftTarget = left;
    state.pendingRightTarget = right;
    state.pendingMotion = newMotion;
    state.transitionPending = true;
    state.transitionStartMs = millis();
  }

  void requestMotionState(MotionState wantedMotion) {
    WheelTargets targets;

    if (!getTargetsForMotion(wantedMotion, targets)) {
      pcErr("INVALID_MOTION");
      return;
    }

    requestMotion(targets.left, targets.right, wantedMotion);
  }

  void processPendingTransition() {
    if (!state.transitionPending) {
      return;
    }

    if (!state.driveEnabled) {
      state.transitionPending = false;
      return;
    }

    if (millis() - state.transitionStartMs >= Config::StopBeforeChangeMs) {
      state.transitionPending = false;
      applyMotors(state.pendingLeftTarget, state.pendingRightTarget, state.pendingMotion);
    }
  }

  // --------------------------------------------------
  // Drive enable, disable, and fault handling
  // --------------------------------------------------

  bool enableDrive() {
    if (!Config::DryRun && !state.canReady) {
      pcErr("CAN_NOT_READY_ENABLE_BLOCKED");
      return false;
    }

    if (state.canFaultLatched) {
      pcErr("CAN_FAULT_LATCHED_ENABLE_BLOCKED");
      return false;
    }

    state.driveEnabled = true;
    state.modeSelected = true;
    state.timeoutLatched = false;
    state.emergencyLatched = false;

    setMotorRelay(true);
    markValidMovementCommand();

    return true;
  }

  void disableDrive(const char* reason) {
    state.transitionPending = false;
    stopMotors();

    state.driveEnabled = false;
    state.modeSelected = false;

    setMotorRelay(false);

    Serial.print("<EVT,DRIVE_DISABLED,REASON=");
    Serial.print(reason);
    Serial.println(">");
  }

  void forceDisableDriveNoCanStop(const char* reason) {
    state.transitionPending = false;

    state.leftTarget = 0.0f;
    state.rightTarget = 0.0f;
    state.motion = MotionState::Stopped;

    state.driveEnabled = false;
    state.modeSelected = false;

    setMotorRelay(false);

    Serial.print("<WARN,DRIVE_FORCE_DISABLED,REASON=");
    Serial.print(reason);
    Serial.println(">");
  }

  void selectDrivingMode(DrivingMode newMode) {
    state.drivingMode = newMode;
    state.modeSelected = true;

    Serial.print("<EVT,MODE=");
    Serial.print(drivingModeToString(state.drivingMode));
    Serial.print(",BASE_DUTY=");
    Serial.print(getDriveDuty(), 3);
    Serial.println(">");
  }

  void handleCanFaultShutdown() {
    if (!state.canFaultLatched) {
      return;
    }

    if (state.driveEnabled || state.motorRelayActive) {
      forceDisableDriveNoCanStop("CAN_TX_FAULT");
    }
  }

  // --------------------------------------------------
  // PC raw-byte commands
  // --------------------------------------------------

  void readPcSerial() {
    while (Serial.available() > 0) {
      const uint8_t rawByte = uint8_t(Serial.read());
      handleBinaryCommand(rawByte);
    }
  }

  void handleBinaryCommand(uint8_t rawByte) {
    if (rawByte > 0x07) {
      return;
    }

    const BinaryCommand command = static_cast<BinaryCommand>(rawByte & 0x07);

    switch (command) {
      case BinaryCommand::Stop:
        state.timeoutLatched = false;
        state.emergencyLatched = false;
        state.canFaultLatched = false;
        disableDrive("BIN_STOP");
        pcAck("BIN,STOP");
        return;

      case BinaryCommand::Mode1:
        handleForwardModeCommand(DrivingMode::Mode1, "BIN,MODE1_FORWARD");
        return;

      case BinaryCommand::Mode2:
        handleForwardModeCommand(DrivingMode::Mode2, "BIN,MODE2_FORWARD");
        return;

      case BinaryCommand::Mode3:
        handleForwardModeCommand(DrivingMode::Mode3, "BIN,MODE3_FORWARD");
        return;

      case BinaryCommand::Right:
        handleTurnCommand(MotionState::Right, "BIN,RIGHT");
        return;

      case BinaryCommand::Left:
        handleTurnCommand(MotionState::Left, "BIN,LEFT");
        return;

      case BinaryCommand::Status:
        sendStatusFrame();
        return;

      case BinaryCommand::Estop:
        handleEmergencyStopCommand();
        return;

      default:
        pcErr("BIN_UNKNOWN");
        return;
    }
  }

  void handleForwardModeCommand(DrivingMode mode, const char* ackMessage) {
    selectDrivingMode(mode);

    if (!enableDrive()) {
      return;
    }

    requestMotionState(MotionState::Forward);
    pcAck(ackMessage);
  }

  void handleTurnCommand(MotionState turnMotion, const char* ackMessage) {
    if (!state.modeSelected) {
      selectDrivingMode(DrivingMode::Mode1);
    }

    if (!enableDrive()) {
      return;
    }

    requestMotionState(turnMotion);
    pcAck(ackMessage);
  }

  void handleEmergencyStopCommand() {
    state.transitionPending = false;
    stopMotors();

    state.driveEnabled = false;
    state.modeSelected = false;
    state.timeoutLatched = false;
    state.emergencyLatched = true;
    state.canFaultLatched = false;

    setMotorRelay(false);

    pcWarn("BIN_ESTOP");
    pcAck("BIN,ESTOP");
  }

  // --------------------------------------------------
  // Timeout
  // --------------------------------------------------

  void checkPcTimeout() {
    if (!state.driveEnabled) {
      return;
    }

    const unsigned long now = millis();

    if (now - state.lastValidMovementCommandMs > Config::PcTimeoutMs) {
      state.transitionPending = false;

      stopMotors();

      state.driveEnabled = false;
      state.modeSelected = false;
      state.timeoutLatched = true;

      setMotorRelay(false);

      pcWarn("PC_TIMEOUT_500MS");
      pcEvent("DRIVE_DISABLED_AFTER_TIMEOUT");
    }
  }
};

/*
Suggested wrapper if this structured version becomes the active sketch later:

#include "5_can_structured.hpp"

VescCanWheelchairController chair;

void setup() {
  chair.begin();
}

void loop() {
  chair.update();
}
*/

