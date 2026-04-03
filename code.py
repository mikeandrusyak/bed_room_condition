import time
import board
import busio
import analogio
import digitalio
import adafruit_scd30
import tm1637lib
import chainable_led

# --- PIN CONFIGURATION (fixed for nRF52840) ---

LED_BRIGHTNESS = 0.02
DISPLAY_CLK_PIN = board.D2
DISPLAY_DIO_PIN = board.D3
RED_LED_PIN = board.A4
SOUND_DIGITAL_PIN = board.A2
SOUND_ACTIVE_STATE = True

# CO2 thresholds (ppm)
CO2_FRESH_MAX = 600
CO2_GOOD_MAX = 800
CO2_WARN_MAX = 1500

# Non-CO2 normal ranges
TEMP_MIN = 19
TEMP_MAX = 24
HUMIDITY_MIN = 40
HUMIDITY_MAX = 60


def scale_color(color, brightness):
    return tuple(int(channel * brightness) for channel in color)

# 1. Light sensor (Grove port A0)
light_sensor = analogio.AnalogIn(board.A0)

# 2. Sound sensor (digital)
sound_sensor = digitalio.DigitalInOut(SOUND_DIGITAL_PIN)
sound_sensor.direction = digitalio.Direction.INPUT

# 3. SCD30 — CO2, Temperature, Humidity (Grove I2C port)
i2c = busio.I2C(board.SCL, board.SDA)
scd30 = adafruit_scd30.SCD30(i2c)

# 4. Multichannel Gas Sensor v2 (Grove I2C port, address 0x08)
GAS_ADDR = 0x08

def read_gas_channel(i2c_bus, channel):
    """Read a gas channel from Multichannel Gas Sensor v2 via raw I2C.
    Channels: 1=GM102B(NO2), 2=GM302B(C2H5OH), 3=GM502B(VOC), 4=GM702B(CO)
    Returns raw ADC value (0..1023) or None on error.
    """
    try:
        while not i2c_bus.try_lock():
            pass
        buf = bytearray(2)
        i2c_bus.writeto(GAS_ADDR, bytes([channel]))
        time.sleep(0.01)
        i2c_bus.readfrom_into(GAS_ADDR, buf)
        return (buf[0] << 8) | buf[1]
    except Exception:
        return None
    finally:
        i2c_bus.unlock()

# 5. 4-Digit Display (Grove port A4)
display = tm1637lib.Grove4DigitDisplay(DISPLAY_CLK_PIN, DISPLAY_DIO_PIN)

# 6. RGB LED (Grove port D4)
# On the nRF52840 board, Grove port D4 = pins D9 and D10
num_leds = 1
leds = chainable_led.P9813(board.D9, board.D10, num_leds)
leds.reset()

# 7. Grove Red LED (connected to Grove port D2)
red_led = digitalio.DigitalInOut(RED_LED_PIN)
red_led.direction = digitalio.Direction.OUTPUT
red_led.value = False

print("=== bed_room_condition system started ===")
print("Testing red LED...")
red_led.value = True
time.sleep(2.0)
red_led.value = False

# --- GAS SENSOR BASELINE CALIBRATION ---
# Wait for sensor warm-up, then record baseline in (assumed) fresh air
_baseline_samples = 5
_no2_sum = _eth_sum = _voc_sum = _co_sum = 0
for _ in range(_baseline_samples):
    v = read_gas_channel(i2c, 1)
    _no2_sum += v if v is not None else 0
    v = read_gas_channel(i2c, 2)
    _eth_sum += v if v is not None else 0
    v = read_gas_channel(i2c, 3)
    _voc_sum += v if v is not None else 0
    v = read_gas_channel(i2c, 4)
    _co_sum  += v if v is not None else 0
    time.sleep(1)
GAS_BASELINE_NO2 = _no2_sum // _baseline_samples
GAS_BASELINE_ETH = _eth_sum // _baseline_samples
GAS_BASELINE_VOC = _voc_sum // _baseline_samples
GAS_BASELINE_CO  = _co_sum  // _baseline_samples
print("Gas baseline — NO2: " + str(GAS_BASELINE_NO2) + " | ETH: " + str(GAS_BASELINE_ETH) + " | VOC: " + str(GAS_BASELINE_VOC) + " | CO: " + str(GAS_BASELINE_CO))

# --- MAIN LOOP ---
while True:
    # Read sensors
    light_level = light_sensor.value
    sound_level = 1 if sound_sensor.value else 0
    sound_alarm = (sound_sensor.value == SOUND_ACTIVE_STATE)

    # Read SCD30 (CO2 + Temperature + Humidity)
    if scd30.data_available:
        co2         = scd30.CO2
        temperature = scd30.temperature
        humidity    = scd30.relative_humidity

        print("CO2: " + str(int(co2)) + " ppm | Temp: " + str(round(temperature, 1)) + " C | Humidity: " + str(round(humidity, 1)) + " % | Light: " + str(light_level) + " | Sound: " + str(sound_level))

        # Show temperature on display
        display.show(int(temperature))

        # RGB LED: indicate CO2 level (4 colors)
        if co2 <= CO2_FRESH_MAX:
            leds.fill(scale_color((0, 0, 255), LED_BRIGHTNESS))     # Fresh air -> Blue
        elif co2 <= CO2_GOOD_MAX:
            leds.fill(scale_color((0, 255, 0), LED_BRIGHTNESS))     # Good indoor level -> Green
        elif co2 <= CO2_WARN_MAX:
            leds.fill(scale_color((255, 80, 0), LED_BRIGHTNESS))    # Comfort limit / warning -> Orange
        else:
            leds.fill(scale_color((255, 0, 0), LED_BRIGHTNESS))     # Poor air quality -> Red
        leds.write()

        # Red LED alarm for non-CO2 parameters
        non_co2_not_ok = (
            temperature < TEMP_MIN or
            temperature > TEMP_MAX or
            humidity < HUMIDITY_MIN or
            humidity > HUMIDITY_MAX or
            sound_alarm
        )
        red_led.value = non_co2_not_ok
        print("Alarm LED: " + ("ON" if non_co2_not_ok else "OFF"))

    # Read Multichannel Gas Sensor v2
    no2 = read_gas_channel(i2c, 1)   # NO2
    eth = read_gas_channel(i2c, 2)   # Ethanol (C2H5OH)
    voc = read_gas_channel(i2c, 3)   # VOC
    co  = read_gas_channel(i2c, 4)   # CO
    if no2 is not None:
        def pct(val, base):
            if base == 0:
                return 0
            return int((val - base) * 100 / base)
        print("Gas - NO2: " + str(no2) + " (" + str(pct(no2, GAS_BASELINE_NO2)) + "%) | ETH: " + str(eth) + " (" + str(pct(eth, GAS_BASELINE_ETH)) + "%) | VOC: " + str(voc) + " (" + str(pct(voc, GAS_BASELINE_VOC)) + "%) | CO: " + str(co) + " (" + str(pct(co, GAS_BASELINE_CO)) + "%)")

    time.sleep(2.0)