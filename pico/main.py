import time
import board
import digitalio
import usb_cdc
import json

last_reading = 0
MAX_CODE = 0x7FFFFF
MIN_CODE = -0x800000

class HX711:
    def __init__(self, dout, pd_sck, gain=128):
        self.pSCK = digitalio.DigitalInOut(pd_sck)
        self.pOUT = digitalio.DigitalInOut(dout)
        self.pSCK.direction = digitalio.Direction.OUTPUT
        self.pOUT.direction = digitalio.Direction.INPUT
        self.gain = gain
        self.offset = 0
        self.reset()

    def reset(self):
        # Reset HX711 by toggling clock
        self.pSCK.value = False
        time.sleep(0.001)

    def is_ready(self):
        return not self.pOUT.value

    def read(self, timeout_ms=100):
        # Wait for ready with timeout
        start_ms = time.monotonic() * 1000
        while not self.is_ready():
            if (time.monotonic() * 1000) - start_ms > timeout_ms:
                self.reset()
                return None  # Return None on timeout
            time.sleep(0.0001)

        # Read 24 bits
        result = 0
        for _ in range(24):
            self.pSCK.value = True
            time.sleep(0.000001)  # Small delay for signal stability
            result = result << 1
            self.pSCK.value = False
            if self.pOUT.value:
                result += 1
            time.sleep(0.000001)

        # Set gain for next reading
        for _ in range(1 if self.gain == 128 else 2 if self.gain == 32 else 3):
            self.pSCK.value = True
            time.sleep(0.000001)
            self.pSCK.value = False
            time.sleep(0.000001)

        # Convert from 2's complement
        if result & 0x800000:
            result -= 0x1000000

        # Clamp values
        return max(MIN_CODE, min(MAX_CODE, result))

# Initialize
hx = HX711(board.GP0, board.GP1)
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


# Main loop with error handling
error_count = 0
last_send_time = time.monotonic()

while True:
    try:
        # Rate limiting
        now = time.monotonic()
        if now - last_send_time < 0.01:  # Max 100Hz instead of 1000Hz
            continue

        reading = hx.read(timeout_ms=50)

        if reading is not None:
            if use_newtons:
                N = (reading - offset) / slope
                serial.write(f"{N:.3f}N\n".encode("utf-8"))
            else:
                serial.write(f"{reading}\n".encode("utf-8"))
            last_send_time = now
            error_count = 0
        else:
            error_count += 1
            if error_count > 10:
                print("reseting hx711")
                # Too many errors, reset HX711
                hx.reset()
                error_count = 0

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(0.1)  # Back off on errors
