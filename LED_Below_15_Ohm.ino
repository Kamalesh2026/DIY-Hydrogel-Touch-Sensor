/*
  Arduino Uno R3, USB powered.
  A valid resistance below 15 ohms triggers a 30-second LED pulse.
  The pulse completes even if the resistance rises or the sensor opens.
  After the pulse, a valid reading >= 15 ohms rearms the next trigger.
  If resistance stays below 15 ohms, the LED stays OFF after the pulse.
  Open/invalid readings cannot trigger or rearm. Reset cancels the pulse.

  BUILD_OPTION 1 (existing no-new-resistor breadboard map):
    D8 -> 100 ohm -> 100 ohm -> LED anode; LED cathode -> GND.
    3.3V -> remaining 100 ohm -> junction -> sample -> GND.
    A0 -> junction. A1 -> 3.3V (NOT AREF).

  BUILD_OPTION 2 (alternative with added reference resistors):
    D8 -> 300 ohm total -> LED anode; LED cathode -> GND.
    5V -> 200 ohm total -> junction -> sample -> GND.
    A0 -> junction. A1 is unused.

  Use fixed resistors rated at least 1/4 W and a common Arduino GND.
  Measurement is approximate: ADC error, resistor tolerance, and
  wire/contact resistance affect the cutoff. No threshold hysteresis or
  baseline calibration is applied. Timer uses millis(), not delay(30000).
*/

const byte BUILD_OPTION = 1;
const byte SENSOR_PIN = A0;
const byte SUPPLY_SENSE_PIN = A1;
const byte LED_PIN = 8;

// Use the measured sensor reference value here for better accuracy.
const float REFERENCE_OHMS = (BUILD_OPTION == 1) ? 100.0 : 200.0;
const float THRESHOLD_OHMS = 15.0;
const unsigned long LED_ON_TIME_MS = 30000UL;

bool ledOn = false;
bool armed = true;
unsigned long ledStartedAt = 0;

float readAverage(byte pin) {
  analogRead(pin);  // Discard first conversion after changing input.
  unsigned long total = 0;
  for (int i = 0; i < 64; i++) {
    total += analogRead(pin);
    delayMicroseconds(100);
  }
  return total / 64.0;
}

void setup() {
  Serial.begin(9600);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  pinMode(SENSOR_PIN, INPUT);
  digitalWrite(SENSOR_PIN, LOW);  // Internal pull-up OFF.
  pinMode(SUPPLY_SENSE_PIN, INPUT);
  digitalWrite(SUPPLY_SENSE_PIN, LOW);
  analogReference(DEFAULT);
  delay(20);

  Serial.println("Below 15 ohms triggers LED ON for 30 seconds.");
  Serial.println("After timeout, a valid R >= 15 ohms rearms the trigger.");
}

void loop() {
  float supplyADC = (BUILD_OPTION == 1)
                      ? readAverage(SUPPLY_SENSE_PIN) : 1023.0;
  float sampleADC = readAverage(SENSOR_PIN);

  bool validReading = false;
  float resistance = 0.0;

  // Show these values even for an open circuit to help check wiring.
  Serial.print("A0: ");
  Serial.print(sampleADC, 1);
  Serial.print(" | Supply ADC: ");
  Serial.print(supplyADC, 1);

  if (supplyADC < 100.0 || sampleADC > supplyADC + 3.0) {
    Serial.print(" | Check input wiring");
  } else if (sampleADC >= supplyADC - 2.0) {
    Serial.print(" | Open / very high resistance");
  } else {
    resistance = REFERENCE_OHMS * sampleADC / (supplyADC - sampleADC);
    validReading = true;

    Serial.print(" | Estimated R: ");
    Serial.print(resistance, 2);
    Serial.print(" ohms");
  }

  unsigned long now = millis();

  if (ledOn) {
    // Unsigned subtraction also works across millis() rollover.
    if (now - ledStartedAt >= LED_ON_TIME_MS) {
      ledOn = false;
    }
  } else if (!armed) {
    // Require a valid release after the pulse before another trigger.
    if (validReading && resistance >= THRESHOLD_OHMS) {
      armed = true;
    }
  } else if (validReading && resistance < THRESHOLD_OHMS) {
    ledOn = true;
    armed = false;
    ledStartedAt = now;
  }

  digitalWrite(LED_PIN, ledOn ? HIGH : LOW);
  Serial.print(" | LED command: ");
  Serial.print(ledOn ? "ON" : "OFF");
  if (ledOn) {
    unsigned long remainingMs = LED_ON_TIME_MS - (now - ledStartedAt);
    Serial.print(" | Seconds remaining: ");
    Serial.println((remainingMs + 999UL) / 1000UL);
  } else {
    Serial.print(" | ");
    Serial.println(armed ? "Ready" : "Waiting for R >= 15 ohms");
  }
  delay(100);
}
