import time
import board
import digitalio
import usb_cdc

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
    reading = hx.read()
    # print(f"{reading}\n".encode("utf-8"))
    serial.write(f"{reading}\n".encode("utf-8"))
    time.sleep(0.01)
