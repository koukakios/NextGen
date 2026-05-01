
 // Incoming Packet: [0x02] [4-byte Float v] [4-byte Float w] [0x03]
 
#include <Arduino.h>
#include <VescUart.h>

unsigned long lastKeepAliveMs = 0;
constexpr unsigned long KEEPALIVE_MS = 100;

struct DriveCommand {
  float v;
  float w; 
};

union ControlPacket {
  DriveCommand cmd;
  byte buffer[sizeof(DriveCommand)];
};

ControlPacket incomingData;
unsigned long lastPacketTime = 0;
const unsigned long WATCHDOG_TIMEOUT = 500; // ms

VescUart VescContr;

void updateMotors(float v, float w) {
  VescContr.setRPM((int)v);
  delay(1000);
  VescContr.setRPM(0);
  return;
}

void stopMotors(){
  return;
}

void sendKeepaliveBoth() {
  VescContr.sendKeepalive();
}

void setup() {
  // Giga Native USB Serial
  Serial.begin(115200);
  Serial1.begin(115200);
  VescContr.setSerialPort(&Serial1);
  pinMode(LED_BUILTIN, OUTPUT);
}

void loop() {
  // incoming data (10 bytes = 1 start + 8 data + 1 end)
  if (Serial.available() >= 10) {
    if (Serial.read() == 0x02) {
      
      Serial.readBytes(incomingData.buffer, 8);
      
      if (Serial.read() == 0x03) { // End Marker
        lastPacketTime = millis(); // Reset Watchdog
        digitalWrite(LED_BUILTIN, HIGH); 
        
        updateMotors(incomingData.cmd.v, incomingData.cmd.w);
      }
    }
  }

  // 2. Safety Watchdog
  if (millis() - lastPacketTime > WATCHDOG_TIMEOUT) {
    stopMotors();
    digitalWrite(LED_BUILTIN, LOW); // Visual indicator of signal loss
  }
  
  if ( (millis() - lastKeepAliveMs > KEEPALIVE_MS)) {
    lastKeepAliveMs = millis();
    sendKeepaliveBoth();
  }
}

