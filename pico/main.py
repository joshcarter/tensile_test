import time
import board
import digitalio
import usb_cdc

last_reading = 0
MAX_CODE = 0x7FFFFF
MIN_CODE = -0x800000

class HX711:
    def __init__(self, dout, pd_sck):
        self.pSCK = digitalio.DigitalInOut(pd_sck)
        self.pOUT = digitalio.DigitalInOut(dout)
        self.pSCK.direction = digitalio.Direction.OUTPUT
        self.pOUT.direction = digitalio.Direction.INPUT
        self.offset = 0

    def is_ready(self):
        return not self.pOUT.value

    def read(self):
        # Wait for ready
        while not self.is_ready():
            pass

        result = 0
        for _ in range(24):
            self.pSCK.value = True
            result = result << 1
            self.pSCK.value = False
            if self.pOUT.value:
                result += 1

        # Set gain = 128 (25th pulse)
        self.pSCK.value = True
        self.pSCK.value = False
        # self.pSCK.value = True
        # self.pSCK.value = False

        # Convert from 2's complement
        if result & 0x800000:
            result -= 0x1000000

        return result

# 🧪 Set up pins
hx = HX711(board.GP0, board.GP1)

# USB serial output (usb_cdc is required for REPL-less output)
serial = usb_cdc.data
serial.timeout = 0

while True:
    try:
        # Raw 24-bit signed code from HX711
        raw = hx.read()
        # Clamp codes that exceed full-scale
        if raw > MAX_CODE:
            raw = MAX_CODE
        elif raw < MIN_CODE:
            raw = MIN_CODE
        reading = int(raw)
        last_reading = reading
    except Exception as e:
        # On any read or clamp error, log and reuse last valid reading
        reading = last_reading

    # Send a guaranteed float value over serial
    serial.write(str(reading) + "\n")
    time.sleep(0.001)
