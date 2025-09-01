import serial
from collections import deque
import os, sys
import time


def _find_available_port(preferred_port=None):
    """
    Find an available serial port, trying preferred_port first if specified.
    Returns the port path or None if no port found.
    """
    ports_to_try = []
    
    # If a preferred port is specified, try it first
    if preferred_port:
        ports_to_try.append(preferred_port)
    
    # Add default ports to try
    default_ports = ["/dev/cu.usbmodem103", "/dev/cu.usbmodem1103", "/dev/cu.usbmodem13103", "/dev/serial1", "/dev/cu.usbmodem11203"]
    for port in default_ports:
        if port not in ports_to_try:
            ports_to_try.append(port)
    
    for port in ports_to_try:
        if os.path.exists(port):
            return port
    
    return None


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
        # Use utility function to find available port
        found_port = _find_available_port(port)
        if found_port is None:
            print(f"Error: Serial port cannot be determined; specify with --port")
            sys.exit(1)
        port = found_port

        # Store connection parameters for recovery
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.recovery_attempts = 0
        self.max_recovery_attempts = 3
        self.consecutive_errors = 0
        self.max_consecutive_errors = 10  # Trigger clean exit after this many errors
        
        self.ser = serial.Serial(port, baud, timeout=timeout)
        self.buffer = deque(maxlen=window_size)
        # Open error log file for logging invalid reads
        self.log_file = open("serial_errors.log", "a")

    def reset(self):
        """Reset the serial buffer."""
        self.buffer.clear()
        if self.ser and self.ser.is_open:
            self.ser.reset_input_buffer()
            
    def _recover_connection(self):
        """
        Attempt to recover the serial connection by closing and reopening the port.
        If the current port is no longer available, scan for available ports.
        Returns True if recovery successful, False otherwise.
        """
        if self.recovery_attempts >= self.max_recovery_attempts:
            self._log_error(f"Max recovery attempts ({self.max_recovery_attempts}) reached")
            return False
            
        self.recovery_attempts += 1
        self._log_error(f"Attempting connection recovery #{self.recovery_attempts}")
        
        try:
            # Close existing connection
            if self.ser and self.ser.is_open:
                self.ser.close()
                
            # Wait a moment before reopening
            time.sleep(0.1)
            
            # Find available port (may be different if device was unplugged/replugged)
            recovery_port = _find_available_port(self.port)
            if recovery_port is None:
                self._log_error(f"No available serial ports found during recovery")
                return False
                
            # Update stored port if it changed
            if recovery_port != self.port:
                self._log_error(f"Port changed from {self.port} to {recovery_port}")
                self.port = recovery_port
            
            # Reopen connection
            self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
            self._log_error(f"Connection recovery #{self.recovery_attempts} successful on {self.port}")
            
            # Reset error counter on successful recovery
            self.consecutive_errors = 0
            return True
            
        except Exception as e:
            self._log_error(f"Connection recovery #{self.recovery_attempts} failed: {e}")
            return False

    def _log_error(self, message):
        """Log error message with timestamp to log file."""
        from datetime import datetime
        timestamp = datetime.now().isoformat()
        self.log_file.write(f"{timestamp} - {message}\n")
        self.log_file.flush()

    def _read_line(self):
        """Read one line from the serial port with automatic recovery on errors."""
        for attempt in range(2):  # Try twice: initial attempt + one retry after recovery
            try:
                line = self.ser.readline().decode(errors="ignore").strip()
                # Reset counters on successful read
                self.consecutive_errors = 0
                self.recovery_attempts = 0
                return line
            except Exception as e:
                self.consecutive_errors += 1
                self._log_error(f"Error reading line (error #{self.consecutive_errors}): {e}")
                
                # Only attempt recovery on first failure (attempt 0)
                if attempt == 0 and not self._recover_connection():
                    break  # Recovery failed, don't retry
                    
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


    def read_smoothed_newtons(self):
        """
        Read Newton values, push into buffer, and return smoothed average.
        For use during testing.
        Raises SystemExit if too many consecutive errors occur.
        """
        while True:
            # Check if we've exceeded max consecutive errors
            if self.consecutive_errors >= self.max_consecutive_errors:
                self._log_error(f"Too many consecutive errors ({self.consecutive_errors}). Triggering clean exit.")
                raise SystemExit("Serial communication failed - too many consecutive read errors")
                
            newtons = self.read_newtons()
            if newtons is None:
                continue  # skip invalid readings
            self.buffer.append(newtons)
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
