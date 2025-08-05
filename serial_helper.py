import serial
from collections import deque
import os, sys


class SerialMovingAverageReader:
    """
    A helper class to read a stream of floats from a serial port and return a smoothed average of those readings.
    For use with a XH711 load cell amp (running at 80Hz) connected to a Raspberry Pi Pico or similar microcontroller.
    """

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
            port = "/dev/serial1"
        if not os.path.exists(port):
            print(f"Error: Serial port cannot be determined; specify with --port")
            sys.exit(1)

        self.ser = serial.Serial(port, baud, timeout=timeout)
        self.buffer = deque(maxlen=window_size)
        # Open error log file for logging invalid reads
        self.log_file = open("serial_errors.log", "a")

    def reset(self):
        """Reset the serial buffer."""
        self.buffer.clear()
        self.ser.reset_input_buffer()

    def _log_error(self, message):
        """Log error message with timestamp to log file."""
        from datetime import datetime
        timestamp = datetime.now().isoformat()
        self.log_file.write(f"{timestamp} - {message}\n")
        self.log_file.flush()

    def read_raw(self):
        """Read one raw float from the serial port (or log error and return None)."""
        try:
            line = self.ser.readline().decode(errors="ignore").strip()
        except Exception as e:
            self._log_error(f"Error reading line: {e}")
            return None

        if not line:
            self._log_error("Empty line received")
            return None

        try:
            return float(line)
        except ValueError as e:
            self._log_error(f"ValueError parsing float from line: {line} - {e}")
            return None

    def read_smoothed(self):
        """
        Read raw data, push it into the circular buffer,
        and return the average of whatever's in the buffer.
        """
        # Continue reading until buffer is full and one new valid sample is added
        while True:
            raw = self.read_raw()
            if raw is None:
                continue  # skip invalid readings
            self.buffer.append(raw)
            if len(self.buffer) == self.buffer.maxlen:
                break

        return sum(self.buffer) / len(self.buffer)

    def close(self):
        """Cleanly close the serial port."""
        if self.ser and self.ser.is_open:
            self.ser.close()
        if hasattr(self, 'log_file'):
            self.log_file.close()


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
