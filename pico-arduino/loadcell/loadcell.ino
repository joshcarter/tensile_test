#include "HX711.h"

// DOUT → GP0
// SCK  → GP1
constexpr int DOUT_PIN = 0;
constexpr int SCK_PIN  = 1;

HX711 scale;

void setup() {
  Serial.begin(115200);
  // gain=32 selects channel B @ 80 SPS; use 128 for 10 SPS
  scale.begin(DOUT_PIN, SCK_PIN, 32);
}

void loop() {
  if (scale.wait_ready_timeout(100)) {
    long raw = scale.read();
    Serial.println(raw);
  }
}
