#include <Arduino.h>
#include <Arduino_CAN.h>

void setup() {
  Serial.begin(115200);
  
  // Wait for Serial monitor to open before proceeding
  while (!Serial); 
  
  Serial.println("Booting CAN Sniffer...");

  if (!CAN.begin(CanBitRate::BR_500k)) {
    Serial.println("CRITICAL ERROR: CAN hardware failed to initialize.");
    while (1); 
  }
  
  Serial.println("CAN Bus Initialized at 500kbps.");
  Serial.println("Listening for VESC heartbeats...");
}

void loop() {
  // Check if there is any data sitting in the CAN hardware buffer
  if (CAN.available()) {
    CanMsg const msg = CAN.read();
    
    Serial.print("SUCCESS! Received CAN ID: 0x");
    Serial.print(msg.id, HEX); // Print the ID in Hexadecimal
    
    Serial.print(" | Payload Length: ");
    Serial.print(msg.data_length);
    Serial.println(" bytes");
  }
}