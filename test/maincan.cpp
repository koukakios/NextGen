#include <Arduino.h>
#include <Arduino_CAN.h> 

// --- VESC CAN Command Protocol ---
const uint8_t CAN_PACKET_SET_DUTY = 0;
const uint8_t CAN_PACKET_SET_CURRENT = 1;

// --- Node IDs (Configure these via VESC Tool) ---
const uint8_t LEFT_VESC_ID = 1;
const uint8_t RIGHT_VESC_ID = 11;

const int RELAY_PIN = A1;

unsigned long lastKeepAliveMs = 0;
const unsigned long KEEPALIVE_MS = 100; // ms
unsigned long lastPacketTime = 0;
const unsigned long WATCHDOG_TIMEOUT = 500; // ms
bool isWatchdogActive = true; 

// --- Power Management Constants ---
unsigned long lastMovementTime = 0;
const unsigned long IDLE_BRAKE_TIMEOUT = 2000; // ms, Engage brakes after 2 seconds of standing still
bool isRelayActive = false;

void setup() {
    Serial.begin(115200);
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
    pinMode(RELAY_PIN, OUTPUT);
    digitalWrite(RELAY_PIN, LOW);
  
    // Initialize the CAN bus at 500 kbps (VESC Default)
    // Ensure your CAN transceiver is connected to the correct Giga pins
    if (!CAN.begin(CanBitRate::BR_500k)) {
        Serial.println("CAN bus initialization failed!");
        while (1); // Halt if CAN fails
    }
    Serial.println("CAN initialized.");
}

/**
 * Commands a specific VESC to run at a given duty cycle.
 * @param target_id The CAN ID of the VESC (e.g., 10 or 11)
 * @param duty The duty cycle [-1.0 to +1.0]
 */
void setVescDuty(uint8_t target_id, float duty) {
    if (duty > 1.0f) duty = 1.0f;
    if (duty < -1.0f) duty = -1.0f;

  // 2. Mathematical Scaling (VESC expects float * 100000)
  int32_t duty_scaled = (int32_t)(duty * 100000.0f);

  // 3. Construct the 29-bit Extended ID using SocketCAN EFF flag (0x80000000)
  uint32_t can_id = (CAN_PACKET_SET_DUTY << 8) | target_id | 0x80000000U;

  // 4. Pack Payload (Enforce Big-Endian transmission)
  uint8_t payload[4];
  payload[0] = (duty_scaled >> 24) & 0xFF; // MSB
  payload[1] = (duty_scaled >> 16) & 0xFF;
  payload[2] = (duty_scaled >> 8)  & 0xFF;
  payload[3] = (duty_scaled & 0xFF);       // LSB

  // 5. Transmit the frame (3 arguments for Arduino_CAN)
  CanMsg msg(can_id, sizeof(payload), payload);
  CAN.write(msg);
}

struct DriveCommand {
  float v;
  float w; 
};

union ControlPacket {
  DriveCommand cmd;
  byte buffer[sizeof(DriveCommand)];
};

ControlPacket incomingData;

void activateRelay() {
  if (!isRelayActive) {
    digitalWrite(RELAY_PIN, LOW); // Pull DOWN to activate relay/release brakes
    isRelayActive = true;
    delay(50); // Wait 50ms for mechanical relay contacts to physically close
  }
}

void deactivateRelay() {
  if (isRelayActive) {
    digitalWrite(RELAY_PIN, HIGH); // Pull HIGH to deactivate relay/engage brakes
    isRelayActive = false;
  }
}

void updateMotors(float v, float w) {

    if (fabs(v) > 0.001f || fabs(w) > 0.001f) {
    activateRelay();
    lastMovementTime = millis(); // Reset the idle timer because we are moving
    }
    // 1. Differential Drive Kinematics (m/s)
    float duty_l = v + w;
    float duty_r = v - w;

  // 2. Find the absolute maximum of the two raw values
    float max_duty = max(fabs(duty_l), fabs(duty_r));

  // 3. Proportional Scaling (Normalize to [-1.0, 1.0])
    if (max_duty > 1.0f) {
        duty_l /= max_duty;
        duty_r /= max_duty;
    }
    setVescDuty(LEFT_VESC_ID, duty_l);
    setVescDuty(RIGHT_VESC_ID, duty_r);
}

void stopMotors() {
    setVescDuty(LEFT_VESC_ID, 0);
    setVescDuty(RIGHT_VESC_ID, 0);
}


void loop() {
  while (Serial.available() >= 10) {
    if (Serial.peek() != 0x02) {
      Serial.read();
      continue;
    }

    // Start marker found, consume it
    Serial.read(); 
    
    // Read the 8-byte payload
    Serial.readBytes(incomingData.buffer, 8);
    
    // Validate end marker
    if (Serial.read() == 0x03) { 
      lastPacketTime = millis(); 
      isWatchdogActive = false; // We have valid data, clear watchdog
      digitalWrite(LED_BUILTIN, HIGH); 
      
      updateMotors(incomingData.cmd.v, incomingData.cmd.w);
    }
  }

  if (millis() - lastPacketTime >= WATCHDOG_TIMEOUT) {
    if (!isWatchdogActive) {
      stopMotors();
      isWatchdogActive = true; 
      digitalWrite(LED_BUILTIN, LOW); 
    }
  }

  if (!isWatchdogActive && (millis() - lastKeepAliveMs > KEEPALIVE_MS)) {
    lastKeepAliveMs = millis();
    // Resend last command to ensure VESCs remain active
    updateMotors(incomingData.cmd.v, incomingData.cmd.w);}

  if (!isWatchdogActive && isRelayActive) {
    if (millis() - lastMovementTime > IDLE_BRAKE_TIMEOUT) {
      deactivateRelay(); // Save 1A of current
    }
  }
}