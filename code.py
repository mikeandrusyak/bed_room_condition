import time
import board
import busio
import analogio
import digitalio
import adafruit_dht
import adafruit_scd30
import tm1637lib
import chainable_led

# --- PIN CONFIGURATION (fixed for nRF52840) ---

LED_BRIGHTNESS = 0.02
DISPLAY_CLK_PIN = board.D2
DISPLAY_DIO_PIN = board.D3
DHT11_PIN = board.A4
RED_LED_PIN = board.D5
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
TEMP_CROSSCHECK_MAX_DIFF = 3.0
HUMIDITY_CROSSCHECK_MAX_DIFF = 12.0

# Set to True, place sensor in fresh outdoor air, deploy -> FRC runs once then set back to False
CALIBRATE_CO2_ON_BOOT = False
CO2_FRC_REFERENCE_PPM = 422  # current outdoor atmospheric CO2 (~422 ppm)

# Extra manual offset added ON TOP of auto-calibration (positive = subtract more from SCD30 reading)
# 0.0 = rely fully on auto-calibration; adjust in 0.5 steps only if needed
SCD30_TEMP_EXTRA_OFFSET = 0.0


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

# 3b. DHT11 — Temperature and Humidity (Grove port A4)
dht11 = adafruit_dht.DHT11(DHT11_PIN)

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

# 5. 4-Digit Display (Grove port D2 -> D2 CLK, D3 DIO)
display = tm1637lib.Grove4DigitDisplay(DISPLAY_CLK_PIN, DISPLAY_DIO_PIN)
display.set_brightness(tm1637lib.BRIGHT_HIGHEST)
display.show(8888)
time.sleep(0.6)
display.clear()

# 6. RGB LED (Grove port D4)
# On the nRF52840 board, Grove port D4 = pins D9 and D10
num_leds = 1
leds = chainable_led.P9813(board.D9, board.D10, num_leds)
leds.reset()

# 7. Grove Red LED (connected to nRF52840 pin D5)
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

# --- SCD30 TEMPERATURE OFFSET AUTO-CALIBRATION via DHT11 ---
# Collect 10 paired readings for a stable mean; apply precise offset to achieve DeltaT <= 0.5 C.
# SCD30 tends to read higher due to self-heating; DHT11 is used as a reference.
_cal_samples = 10
_delta_sum = 0.0
_cal_count = 0
print("SCD30 calibration: collecting " + str(_cal_samples) + " paired readings...")
for _ in range(_cal_samples):
    time.sleep(2)
    _dht_t = None
    try:
        _dht_t = dht11.temperature
    except Exception:
        pass
    if _dht_t is not None and scd30.data_available:
        _delta_sum += scd30.temperature - _dht_t
        _cal_count += 1

if _cal_count >= 5:
    _auto = _delta_sum / _cal_count
    _offset = round(_auto + SCD30_TEMP_EXTRA_OFFSET, 2)
    scd30.temperature_offset = _offset
    print("SCD30 offset set to " + str(_offset) + " C (auto " + str(round(_auto, 2)) + " + extra " + str(SCD30_TEMP_EXTRA_OFFSET) + ", " + str(_cal_count) + " samples)")
else:
    print("SCD30 calibration skipped: not enough paired readings (" + str(_cal_count) + "/" + str(_cal_samples) + ")")

# --- SCD30 CO2 FORCED RECALIBRATION (FRC) ---
# Run only when CALIBRATE_CO2_ON_BOOT = True AND sensor is in fresh outdoor air.
# SCD30 must stabilise for ~2 min before FRC is applied.
if CALIBRATE_CO2_ON_BOOT:
    print("CO2 FRC: warming up 2 min — keep sensor in fresh outdoor air...")
    display.show("CAL ")
    for _t in range(24):              # 24 x 5 s = 120 s
        leds.fill(scale_color((0, 0, 255), LED_BRIGHTNESS))
        leds.write()
        time.sleep(2.5)
        leds.fill(scale_color((0, 0, 0), LED_BRIGHTNESS))
        leds.write()
        time.sleep(2.5)
    scd30.forced_recalibration_reference = CO2_FRC_REFERENCE_PPM
    print("CO2 FRC applied: reference = " + str(CO2_FRC_REFERENCE_PPM) + " ppm")
    print("Set CALIBRATE_CO2_ON_BOOT = False and redeploy to resume normal mode.")
    display.show("donE")
    while True:                       # halt so user sees the message
        time.sleep(1)

# --- MAIN LOOP ---
while True:
    # Read sensors
    light_level = light_sensor.value
    sound_level = 1 if sound_sensor.value else 0
    sound_alarm = (sound_sensor.value == SOUND_ACTIVE_STATE)

    # DHT11 may occasionally fail one read; keep loop alive and retry next cycle
    dht_temperature = None
    dht_humidity = None
    try:
        dht_temperature = dht11.temperature
        dht_humidity = dht11.humidity
    except RuntimeError:
        pass
    except Exception as err:
        print("DHT11 error: " + str(err))

    # Read SCD30 (CO2 + Temperature + Humidity)
    if scd30.data_available:
        co2         = scd30.CO2
        temperature = scd30.temperature
        humidity    = scd30.relative_humidity

        print("CO2: " + str(int(co2)) + " ppm | Temp: " + str(round(temperature, 1)) + " C | Humidity: " + str(round(humidity, 1)) + " % | Light: " + str(light_level) + " | Sound: " + str(sound_level))

        sensor_disagree = False
        if dht_temperature is not None and dht_humidity is not None:
            temp_diff = abs(temperature - dht_temperature)
            humidity_diff = abs(humidity - dht_humidity)
            sensor_disagree = (
                temp_diff > TEMP_CROSSCHECK_MAX_DIFF or
                humidity_diff > HUMIDITY_CROSSCHECK_MAX_DIFF
            )
            print(
                "DHT11 -> Temp: " + str(round(dht_temperature, 1)) + " C | Humidity: " +
                str(round(dht_humidity, 1)) + " % | DeltaT: " + str(round(temp_diff, 1)) +
                " C | DeltaH: " + str(round(humidity_diff, 1)) + " %"
            )
            if sensor_disagree:
                print("WARNING: SCD30 and DHT11 values differ too much")
        else:
            print("DHT11: no valid reading this cycle")

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
            sensor_disagree or
            sound_alarm
        )
        red_led.value = non_co2_not_ok

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