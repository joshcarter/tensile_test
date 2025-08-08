import serial
from collections import deque
import os, sys


class SerialMovingAverageReader:
    """
    A helper class to read a stream of values from a serial port and return a smoothed average.
    Can handle both raw counts (integers) and Newton values (floats with 'N' suffix).
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

    def _read_line(self):
        """Read one line from the serial port."""
        try:
            line = self.ser.readline().decode(errors="ignore").strip()
            return line
        except Exception as e:
            self._log_error(f"Error reading line: {e}")
            return None

    def read_raw_counts(self):
        """
        Read one raw count value from the serial port.
        Expects integer values with no suffix.
        Raises ValueError if Newton values are detected.
        """
        line = self._read_line()
        if not line:
            self._log_error("Empty line received")
            return None

        # Check if this is a Newton value (has 'N' suffix)
        if line.endswith('N'):
            raise ValueError(
                "ERROR: Pico is sending calibrated Newton values when raw counts are expected. "
                "The Pico should not have a calibration.json file during calibration mode."
            )

        try:
            # Try to parse as integer first (expected format)
            return float(int(line))
        except ValueError:
            try:
                # Fall back to float if it's a decimal raw value
                return float(line)
            except ValueError as e:
                self._log_error(f"ValueError parsing raw count from line: {line} - {e}")
                return None

    def read_newtons(self):
        """
        Read one Newton value from the serial port.
        Expects float values with 'N' suffix.
        Raises ValueError if raw counts are detected.
        """
        line = self._read_line()
        if not line:
            self._log_error("Empty line received")
            return None

        # Check if this has the Newton suffix
        if not line.endswith('N'):
            raise ValueError(
                "ERROR: Pico is sending raw counts when calibrated Newton values are expected. "
                "Please upload calibration.json to the Pico to enable Newton output."
            )

        # Strip the 'N' suffix and parse the float
        try:
            return float(line[:-1])
        except ValueError as e:
            self._log_error(f"ValueError parsing Newton value from line: {line} - {e}")
            return None

    def read_raw(self):
        """
        Legacy method for backward compatibility.
        Reads raw counts for calibration mode.
        """
        return self.read_raw_counts()

    def read_smoothed_counts(self):
        """
        Read raw counts, push into buffer, and return smoothed average.
        For use during calibration.
        """
        while True:
            raw = self.read_raw_counts()
            if raw is None:
                continue  # skip invalid readings
            self.buffer.append(raw)
            if len(self.buffer) == self.buffer.maxlen:
                break

        return sum(self.buffer) / len(self.buffer)

    def read_smoothed_newtons(self):
        """
        Read Newton values, push into buffer, and return smoothed average.
        For use during testing.
        """
        while True:
            newtons = self.read_newtons()
            if newtons is None:
                continue  # skip invalid readings
            self.buffer.append(newtons)
            if len(self.buffer) == self.buffer.maxlen:
                break

        return sum(self.buffer) / len(self.buffer)

    def read_smoothed(self):
        """
        Legacy method for backward compatibility.
        Defaults to reading Newton values.
        """
        return self.read_smoothed_newtons()

    def close(self):
        """Cleanly close the serial port."""
        if self.ser and self.ser.is_open:
            self.ser.close()
        if hasattr(self, 'log_file'):
            self.log_file.close()


def test_serial():
    s = SerialMovingAverageReader(port=None, window_size=5)
    try:
        print("Testing Newton value reading (expecting values with 'N' suffix)...")
        while True:
            try:
                avg = s.read_smoothed_newtons()
                print(f"Average force: {avg:.2f} N")
            except ValueError as e:
                print(f"Configuration error: {e}")
                sys.exit(1)
    except KeyboardInterrupt:
        print("Exiting...")
    finally:
        s.close()


if __name__ == "__main__":
    test_serial()