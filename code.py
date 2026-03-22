import time
import board
import analogio
import adafruit_dht
import tm1637lib
import chainable_led

# --- PIN CONFIGURATION (fixed for nRF52840) ---

LED_BRIGHTNESS = 0.15


def scale_color(color, brightness):
    return tuple(int(channel * brightness) for channel in color)

# 1. Light sensor (Grove port A0)
light_sensor = analogio.AnalogIn(board.A0)

# 2. Temperature/humidity sensor DHT11 (Grove port A2)
dht = adafruit_dht.DHT11(board.A2)

# 3. 4-Digit Display (Grove port D2)
# For Feather nRF52840: Grove D2 = D5 (CLK) and D6 (DIO)
display = tm1637lib.Grove4DigitDisplay(board.D5, board.D6)

# 4. RGB LED (Grove port D4)
# On the nRF52840 board, Grove port D4 = pins D9 and D10
num_leds = 1
leds = chainable_led.P9813(board.D9, board.D10, num_leds)
leds.reset()

print("=== bed_room_condition system started ===")

# --- MAIN LOOP ---
while True:
    try:
        # Read sensor data
        temperature = dht.temperature
        humidity = dht.humidity
        light_level = light_sensor.value

        # Print data to serial
        print(f"Temp: {temperature} C | Humidity: {humidity} % | Light: {light_level}")

        # Control display and LED
        if temperature is not None:
            # Show temperature on display
            display.show(f"{int(temperature)} C")

            # LED comfort logic
            if temperature < 19:
                leds.fill(scale_color((0, 0, 255), LED_BRIGHTNESS))     # Cold -> Blue
            elif temperature > 24:
                leds.fill(scale_color((255, 0, 0), LED_BRIGHTNESS))     # Hot -> Red
            else:
                leds.fill(scale_color((0, 255, 0), LED_BRIGHTNESS))     # Comfortable -> Green
            leds.write()

    except RuntimeError as e:
        print("Waiting for DHT11 data...")

    time.sleep(2.0)