#include <Arduino.h>
#include <VescUart.h>

VescUart leftVesc;
VescUart rightVesc;

unsigned long lastKeepAliveMs = 0;
const unsigned long KEEPALIVE_MS = 100; // ms
unsigned long lastPacketTime = 0;
const unsigned long WATCHDOG_TIMEOUT = 500; // ms

// --- Physical Constants ---
const float TRACK_WIDTH = 1.0;   
const float WHEEL_DIAMETER = 0.3; 
const float MOTOR_CONST = 500.0;       

bool isWatchdogActive = true; 

struct DriveCommand {
  float v;
  float w; 
};

union ControlPacket {
  DriveCommand cmd;
  byte buffer[sizeof(DriveCommand)];
};

ControlPacket incomingData;

void updateMotors(float v, float w) {
  // 1. Differential Drive Kinematics (m/s)
  float v_l = v - (w * TRACK_WIDTH) / 2.0f;
  float v_r = v + (w * TRACK_WIDTH) / 2.0f;

  float wheel_rpm_l = (v_l * 60.0f) / (PI * WHEEL_DIAMETER);
  float wheel_rpm_r = (v_r * 60.0f) / (PI * WHEEL_DIAMETER);

  long erpm_l = round(wheel_rpm_l * MOTOR_CONST );
  long erpm_r = round(wheel_rpm_r * MOTOR_CONST);

  leftVesc.setRPM(erpm_l);
  rightVesc.setRPM(erpm_r);
}

void stopMotors() {
  leftVesc.setRPM(0);
  rightVesc.setRPM(0);
}

void setup() {
  Serial.begin(115200);
  Serial1.begin(115200);
  Serial2.begin(115200);
  
  rightVesc.setSerialPort(&Serial1);
  leftVesc.setSerialPort(&Serial2);

  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
  
  stopMotors(); 
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
    leftVesc.sendKeepalive();
    rightVesc.sendKeepalive();
  }
}