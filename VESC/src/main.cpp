#include "5_can_structured.hpp"

VescCanWheelchairController chair;

void setup() {
  chair.begin();
}

void loop() {
  chair.update();
}

