import time
import board
import digitalio
import usb_cdc
import json

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

        # Clamp codes that exceed full-scale
        if reading > MAX_CODE:
            return MAX_CODE
        elif reading < MIN_CODE:
            return MIN_CODE
        else:
            return result


# 🧪 Set up pins
hx = HX711(board.GP0, board.GP1)

# USB serial output (usb_cdc is required for REPL-less output)
serial = usb_cdc.data
serial.timeout = 0

# ——— Try Load Calibration ———
use_newtons = False
offset = 0
slope = 1
try:
    with open("calibration.json", "r") as f:
        cal = json.load(f)
        offset = float(cal["offset"])
        slope  = float(cal["slope"])
        use_newtons = True
except Exception:
    # no file or parse error → stick to raw counts
    use_newtons = False


while True:
    try:
        reading = hx.read()

        if use_newtons:
            # convert to Newtons and tag with "N"
            N = (reading - offset) / slope
            serial.write(f"{N:.3f}N\n".encode("utf-8"))
        else:
            # emit raw counts for calibration
            serial.write(f"{reading}\n".encode("utf-8"))
    except Exception as e:
        pass

    time.sleep(0.001)
