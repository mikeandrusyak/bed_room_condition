import time
import board
import busio
import analogio
import digitalio
import adafruit_scd30
import tm1637lib
import chainable_led
import adafruit_connection_manager
from adafruit_esp32spi import adafruit_esp32spi
import adafruit_minimqtt.adafruit_minimqtt as MQTT
import secrets

# --- PIN CONFIGURATION (fixed for nRF52840) ---

LED_BRIGHTNESS = 0.004          # dimmed further to make colors easier to distinguish
TEMPERATURE_OFFSET = -2.0       # SCD30 reads ~2°C high due to board heat
DISPLAY_CLK_PIN = board.A4
DISPLAY_DIO_PIN = board.A5
RED_LED_PIN = board.D5
SOUND_ANALOG_PIN = board.A2
SOUND_WINDOW_SAMPLES = 32
SOUND_ACTIVITY_THRESHOLD = 2500

# CO2 thresholds (ppm) for a simpler 3-color indicator
CO2_FRESH_MAX = 650
CO2_GOOD_MAX = 1000

# Non-CO2 normal ranges
HUMIDITY_MIN = 40
HUMIDITY_MAX = 60

# ThingSpeak MQTT
TS_MQTT_BROKER = "mqtt3.thingspeak.com"
TS_MQTT_TOPIC = "channels/" + secrets.TS_CHANNEL_ID + "/publish"
PUBLISH_INTERVAL = 15.0  # seconds (ThingSpeak free tier minimum)


def scale_color(color, brightness):
    return tuple(int(channel * brightness) for channel in color)

# 1. Light sensor (Grove port A0)
light_sensor = analogio.AnalogIn(board.A0)

# 2. Sound sensor (analog)
sound_sensor = analogio.AnalogIn(SOUND_ANALOG_PIN)

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

# 5. 4-Digit Display (Grove port A4 -> A4 CLK, A5 DIO)
display = tm1637lib.Grove4DigitDisplay(DISPLAY_CLK_PIN, DISPLAY_DIO_PIN)
display.set_brightness(tm1637lib.BRIGHT_DARKEST)
display.show(8888)
time.sleep(0.6)
display.clear()

# 6. RGB LED (Grove port D4)
# On the nRF52840 board, Grove port D4 = pins D9 and D10
num_leds = 1
leds = chainable_led.P9813(board.D9, board.D10, num_leds)
leds.reset()

# 7. Grove Red LED (connected to Grove port D2 -> nRF52840 D5)
red_led = digitalio.DigitalInOut(RED_LED_PIN)
red_led.direction = digitalio.Direction.OUTPUT
red_led.value = True
time.sleep(0.6)
red_led.value = False

# --- ESP32 AIRLIFT WIFI + MQTT SETUP ---

time.sleep(3)  # wait for ESP32 AirLift to boot after cold power-on

# FeatherWing ESP32 AirLift pins (nRF52840)
esp32_cs  = digitalio.DigitalInOut(board.D13)
esp32_rdy = digitalio.DigitalInOut(board.D11)
esp32_rst = digitalio.DigitalInOut(board.D12)
spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_rdy, esp32_rst)

print("Connecting to WiFi:", secrets.WIFI_SSID)
leds.fill(scale_color((255, 255, 255), LED_BRIGHTNESS))  # white = connecting
leds.write()
while not esp.is_connected:
    try:
        esp.connect_AP(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)
    except RuntimeError as e:
        print("WiFi error, retrying:", e)
print("WiFi connected, IP:", esp.pretty_ip(esp.ip_address))
time.sleep(2)  # let DHCP/DNS settle before first socket use

pool = adafruit_connection_manager.get_radio_socketpool(esp)
mqtt_client = MQTT.MQTT(
    broker=TS_MQTT_BROKER,
    client_id=secrets.TS_MQTT_CLIENT_ID,
    username=secrets.TS_MQTT_USERNAME,
    password=secrets.TS_MQTT_PASSWORD,
    socket_pool=pool,
)

while True:
    try:
        mqtt_client.connect()
        break
    except Exception as e:
        print("MQTT connect error, retrying in 5s:", e)
        time.sleep(5)
print("MQTT connected to", TS_MQTT_BROKER)
leds.fill(scale_color((0, 255, 0), LED_BRIGHTNESS))  # green = connected
leds.write()
time.sleep(1)
leds.fill((0, 0, 0))  # off until first CO2 reading
leds.write()

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
last_publish = time.monotonic() - PUBLISH_INTERVAL  # publish immediately on first reading
co2 = temperature = humidity = None  # last known SCD30 values
while True:
    # Read sensors
    light_level = light_sensor.value
    # Use peak-to-peak amplitude over a short window so the value reacts to speech/music.
    sound_min = 65535
    sound_max = 0
    for _ in range(SOUND_WINDOW_SAMPLES):
        sample = sound_sensor.value
        if sample < sound_min:
            sound_min = sample
        if sample > sound_max:
            sound_max = sample
    sound_level = sound_max - sound_min

    # Read SCD30 (CO2 + Temperature + Humidity)
    if scd30.data_available:
        co2         = scd30.CO2
        temperature = scd30.temperature + TEMPERATURE_OFFSET
        humidity    = scd30.relative_humidity

        print("CO2: " + str(int(co2)) + " ppm | Temp: " + str(round(temperature, 1)) + " C | Humidity: " + str(round(humidity, 1)) + " % | Light: " + str(light_level) + " | Sound: " + str(sound_level))

        # Show temperature on display
        display.show(int(temperature))

        # RGB LED: indicate CO2 level (3 colors)
        if co2 <= CO2_FRESH_MAX:
            leds.fill(scale_color((0, 0, 255), LED_BRIGHTNESS))     # Fresh air -> Blue
        elif co2 <= CO2_GOOD_MAX:
            leds.fill(scale_color((0, 255, 0), LED_BRIGHTNESS))     # Acceptable indoor level -> Green
        else:
            leds.fill(scale_color((255, 0, 0), LED_BRIGHTNESS))     # Ventilate room -> Red
        leds.write()

        # Red LED alarm for non-CO2 parameters
        non_co2_not_ok = (
            humidity < HUMIDITY_MIN or
            humidity > HUMIDITY_MAX 
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

    # Publish to ThingSpeak every PUBLISH_INTERVAL seconds
    now = time.monotonic()
    if now - last_publish >= PUBLISH_INTERVAL and co2 is not None and no2 is not None:
        payload = (
            "field1=" + str(int(co2)) +
            "&field2=" + str(round(temperature, 1)) +
            "&field3=" + str(round(humidity, 1)) +
            "&field4=" + str(light_level) +
            "&field5=" + str(sound_level) +
            "&field6=" + str(no2) +
            "&field7=" + str(voc) +
            "&field8=" + str(co)
        )
        try:
            mqtt_client.publish(TS_MQTT_TOPIC, payload)
            print("Published to ThingSpeak")
        except Exception as e:
            print("Publish error:", e)
        last_publish = now

    time.sleep(2.0)
