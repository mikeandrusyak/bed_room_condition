# Bedroom Condition Monitor

A project for monitoring bedroom conditions (CO2, temperature, humidity, noise levels, ambient light, and gases) using an **Adafruit Feather nRF52840 Express** (with ESP32 AirLift co-processor) and Grove modules. Data is displayed locally and published to **ThingSpeak** via MQTT.

---

## Hardware Configuration

| Component | Module | Grove Port / Pins | Pin Connections |
|---|---|---|---|
| **Microcontroller** | Adafruit Feather nRF52840 Express | — | — |
| **Wi-Fi Co-processor** | FeatherWing ESP32 AirLift | SPI | CS (D13), RDY (D11), RST (D12) |
| **CO2 / Temp / Humidity** | Grove SCD30 | I2C | SCL, SDA |
| **Gas Sensor (NO2, CO, VOC, Ethanol)** | Grove Multichannel Gas Sensor v2 | I2C (Address `0x08`) | SCL, SDA |
| **Light Sensor** | Grove Light Sensor | A0 | A0 |
| **Sound Sensor** | Grove Sound Sensor | A2 | A2 |
| **4-Digit Display** | Grove 4-Digit Display (TM1637) | A4 | A4 (CLK), A5 (DIO) |
| **RGB LED** | Grove Chainable RGB LED (P9813) | D4 | D9 (CLK), D10 (DATA) |
| **Green LED** | Grove Green LED | D2 | D5 |

---

## Repository Structure

```
bed_room_condition/
├── code.py          # Main application logic
├── secrets.py       # Wi-Fi credentials & ThingSpeak MQTT configuration (Git ignored)
├── logic_diagram.md # Detailed flow diagram and block descriptions
├── lib/             # CircuitPython libraries (e.g. adafruit_scd30, chainable_led)
└── library/         # Additional helper libraries
```

---

## Installation & Setup

### 1. Configure Credentials
Create a `secrets.py` file in the root directory (if it doesn't exist) with your Wi-Fi credentials and ThingSpeak MQTT device configurations:

```python
# WiFi credentials
WIFI_SSID = "Your_WiFi_SSID"
WIFI_PASSWORD = "Your_WiFi_Password"

# ThingSpeak channel
TS_CHANNEL_ID = "Your_ThingSpeak_Channel_ID"

# ThingSpeak MQTT Device credentials
# Create at: thingspeak.com → Devices → MQTT → Add a new device → select channel
# WARNING: password shown only once after device creation!
TS_MQTT_CLIENT_ID = "Your_MQTT_Client_ID"
TS_MQTT_USERNAME  = "Your_MQTT_Username"
TS_MQTT_PASSWORD  = "Your_MQTT_Password"
```

### 2. Connect the Board
Plug the Feather nRF52840 Express board into your computer via a USB micro-B data cable. The board will appear as a USB drive named **CIRCUITPY**.

### 3. Copy Files to the Board

**Via VS Code (Recommended):**
- Run the **Deploy to Feather** build task (`Cmd+Shift+B` on macOS or `Ctrl+Shift+B` on Windows/Linux).
- Or go to `Terminal → Run Build Task`.

**Manually via Terminal:**
```bash
cp -r code.py secrets.py lib/ library/ /Volumes/CIRCUITPY/
```

---

## System Behavior & Indicators

For a complete logic flow, refer to the [Logic Diagram](logic_diagram.md).

- **4-Digit Display** — Displays the current temperature in °C (updated every 2 seconds).
- **RGB LED** — Indicates **CO2 concentration**:
  - 🔵 **Blue** — Fresh air (`<= 650 ppm`)
  - 🟢 **Green** — Acceptable indoor levels (`651 - 1000 ppm`)
  - 🔴 **Red** — High CO2 level (Ventilation required, `> 1000 ppm`)
- **Green LED** — Humidity alarm:
  - Turns **ON** if the humidity is outside the comfort range (`< 40%` or `> 60%`).
  - Turns **OFF** when humidity is within range.
- **Sound Level Monitoring** — Uses peak-to-peak amplitude measurement over a short window (32 samples) to capture dynamic sounds (e.g., speech or music).
- **Data Publishing** — Publishes all 8 sensor parameters to ThingSpeak every 15 seconds.

---

## Monitoring Output (Serial Monitor)

### VS Code Serial Monitor
1. Open `View → Serial Monitor`
2. Select port `/dev/tty.usbmodem*`
3. Click ▶ **Start Monitoring**

### Terminal `screen` Connection
```bash
screen /dev/tty.usbmodem11301 115200
```
*(Exit: press `Ctrl+A`, then `K`)*

### Expected Serial Log Output:
```
Connecting to WiFi: Your_WiFi_SSID
WiFi connected, IP: 192.168.1.150
MQTT connected to mqtt3.thingspeak.com
Gas baseline — NO2: 512 | ETH: 420 | VOC: 610 | CO: 480
CO2: 540 ppm | Temp: 21.4 C | Humidity: 45.2 % | Light: 15430 | Sound: 420
Gas - NO2: 512 (0%) | ETH: 425 (1%) | VOC: 610 (0%) | CO: 480 (0%)
Published to ThingSpeak
```
