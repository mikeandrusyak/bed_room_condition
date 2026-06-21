# Bed Room Condition Monitor

A project for monitoring room conditions (temperature, humidity, light level) using an **Adafruit Feather nRF52840 Express** and Grove modules.

---

## Hardware

| Component | Module | Grove Port | Pins |
|---|---|---|---|
| Light sensor | Grove Light Sensor | A0 | A0 |
| Temp./humidity sensor | DHT11 | A2 | A2 |
| 4-digit display | Grove 4-Digit Display (TM1637) | A4 | A4 (CLK), A5 (DIO) |
| RGB LED | Grove Chainable RGB LED (P9813) | D4 | D9 (CLK), D10 (DATA) |
| Green LED | Grove Green LED | D2 | D5 |

---

## Repository Structure

```
bed_room_condition/
├── code.py          # Main code — copied to the board
└── lib/             # CircuitPython libraries
```

---

## Setup & Deployment

### 1. Connect the board
Plug the Feather nRF52840 in via USB. It should appear as a **CIRCUITPY** drive.

### 2. Copy code to the board

**Via VS Code (recommended):**
- Press `Cmd+Shift+B` — runs the **Deploy to Feather** build task
- Or: `Terminal → Run Build Task`

**Manually via terminal:**
```bash
cp code.py /Volumes/CIRCUITPY/code.py
```

> The board automatically restarts the code after the file is saved.

---

## Monitoring Output (Serial Monitor)

### Option 1 — VS Code Serial Monitor
1. Open `View → Serial Monitor`
2. Select port `/dev/tty.usbmodem*`
3. Click ▶ **Start Monitoring**

### Option 2 — Terminal (`screen`)
```bash
screen /dev/tty.usbmodem11301 115200
```
Exit: `Ctrl+A`, then `K`

### Option 3 — `mpremote`
```bash
pip install mpremote
mpremote connect /dev/tty.usbmodem11301
```

**Expected output:**
```
=== bed_room_condition system started ===
Temp: 22 C | Humidity: 55 % | Light: 32768
Temp: 22 C | Humidity: 56 % | Light: 31200
```

---

## How It Works

For a detailed flow of the program logic, see the [Logic Diagram](file:///Users/workflow/FHNW%20git/FS2026%20git/idb/bed_room_condition/logic_diagram.md).

- **Display** — shows the current temperature (°C)
- **RGB LED** — comfort indicator:
  - 🔵 Blue — too cold (< 19 °C)
  - 🟢 Green — comfortable (19–24 °C)
  - 🔴 Red — too warm (> 24 °C)
- Data refreshes every **2 seconds**

---

## Dependencies (CircuitPython Libraries)

All libraries are already included in the `lib/` folder. To update them, download the latest [CircuitPython Bundle](https://circuitpython.org/libraries) and copy the relevant `.mpy` files.
