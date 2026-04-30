#include <Arduino.h>
#include <VescUart.h>

int v;
int w;

unsigned long lastPacketTime = 0;
const unsigned long TIMEOUT_MS = 500;

void loop() {
  readSerial(); // Updates v and w if data is present
  
  // Safety Check
  if (millis() - lastPacketTime > TIMEOUT_MS) {
    v = 0;
    w = 0;
    // Optional: Log error to indicate comms loss
  }

  driveMotors(v, w);
}
