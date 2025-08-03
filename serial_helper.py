import serial
from collections import deque
import os, sys

class SerialMovingAverageReader:
    def __init__(self, port, baud=115200, timeout=0.1, window_size=3):
        """
        :param port:      Serial port device (e.g. '/dev/ttyACM1')
        :param baud:      Baud rate (must match Pico)
        :param timeout:   Read timeout in seconds
        :param window_size: Number of samples to average
        """
        if port is None:
            port = "/dev/cu.usbmodem103"
        if not os.path.exists(port):
            port = "/dev/cu.usbmodem1103"
        if not os.path.exists(port):
            print(f"Error: Serial port cannot be determined; specify with --port")
            sys.exit(1)

        self.ser = serial.Serial(port, baud, timeout=timeout)
        self.buffer = deque(maxlen=window_size)

    def reset(self):
        """Reset the serial buffer."""
        self.buffer.clear()
        self.ser.reset_input_buffer()

    def read_raw(self):
        """Read one raw float from the serial port (or return None)."""
        line = self.ser.readline().decode(errors="ignore").strip()
        if not line:
            return None
        try:
            return float(line)
        except ValueError:
            return None

    def read_smoothed(self):
        """
        Read raw data, push it into the circular buffer,
        and return the average of whatever's in the buffer.
        """
        # make sure averager is always full
        while True:
            raw = self.read_raw()
            if raw is None:
                return None

            self.buffer.append(raw)

            if len(self.buffer) == self.buffer.maxlen:
                break

        # raw = self.read_raw()
        # if raw is None:
        #     return None
        # self.buffer.append(raw)

        return sum(self.buffer) / len(self.buffer)

    def close(self):
        """Cleanly close the serial port."""
        if self.ser and self.ser.is_open:
            self.ser.close()


def test_serial():
    s = SerialMovingAverageReader(port=None, window_size=5)
    try:
        while True:
            avg = s.read_smoothed()
            print(f"Average: {avg:.2f}")
    except KeyboardInterrupt:
        print("Exiting...")
    finally:
        s.close()

if __name__ == "__main__":
    test_serial()
