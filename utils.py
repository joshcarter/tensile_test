"""
Utility functions and constants for the tensile tester application.
"""

import time
from collections import deque

# Constants for sparkline plotting
SPARK_BLOCKS = "▁▂▃▄▅▆▇█"
SPARK_DURATION = 5.0
SPARK_HEIGHT = 7  # Number of lines for the sparkline plot

# Test constants
SAMPLE_INTERVAL = 0.01  # 100 Hz
DROP_DURATION = 10.0  # seconds below threshold to end trial
CROSS_SECTION = None  # will get overriden to the appropriate cross-sectional area
XY_AXIS_AREA = 25  # mm^2 cross-sectional area for the XY axis test
Z_AXIS_AREA = 50  # mm^2 cross-sectional area for the Z axis test

# Physics constants
G = 9.80665  # m/s²

# Calibration constants
CAL_FILE = "calibration.json"
CAL_WEIGHTS = [0.0, 7.9, 15.9, 31.4]  # kg


def make_sparkline(data: list[float], height: int = SPARK_HEIGHT) -> str:
    """
    Create a multi-line sparkline plot from data.
    
    Args:
        data: List of float values to plot
        height: Number of lines for the plot (default: SPARK_HEIGHT)
    
    Returns:
        Multi-line string representing the sparkline plot
    """
    if not data:
        return "\n".join([" " * 50] * height)
    
    lo, hi = min(data), max(data)
    rng = hi - lo or 1.0
    
    # Create a 2D grid for the plot
    width = len(data)
    grid = [[" " for _ in range(width)] for _ in range(height)]
    
    # Fill the grid
    for x, value in enumerate(data):
        # Normalize value to 0-1 range
        normalized = (value - lo) / rng
        # Convert to pixel height (inverted because we draw top-down)
        pixel_height = normalized * (height * len(SPARK_BLOCKS) - 1)
        
        # Determine which row and which character
        row = height - 1 - int(pixel_height // len(SPARK_BLOCKS))
        char_index = int(pixel_height % len(SPARK_BLOCKS))
        
        # Handle edge case where value equals maximum
        if row < 0:
            row = 0
            char_index = len(SPARK_BLOCKS) - 1
        
        # Fill from bottom up to this point
        for y in range(height):
            if y > row:
                grid[y][x] = SPARK_BLOCKS[-1]  # Full block
            elif y == row:
                grid[y][x] = SPARK_BLOCKS[char_index]
    
    # Convert grid to string
    return "\n".join("".join(row) for row in grid)


class SparklineGraph:
    """
    A sparkline graph that manages its own data and automatically sizes to panel width.
    """
    
    def __init__(self, duration: float = SPARK_DURATION, height: int = SPARK_HEIGHT):
        """
        Initialize the sparkline graph.
        
        Args:
            duration: Time window in seconds to keep data for
            height: Height of the graph in lines
        """
        self.duration = duration
        self.height = height
        self.data = deque()  # (timestamp, value)
        
    def add_value(self, value: float) -> None:
        """Add a new value to the graph with current timestamp."""
        now = time.monotonic()
        self.data.append((now, value))
        self._trim_old_data(now)
        
    def reset(self) -> None:
        """Clear all data from the graph."""
        self.data.clear()
        
    def _trim_old_data(self, current_time: float) -> None:
        """Remove data older than the duration window."""
        cutoff_time = current_time - self.duration
        while self.data and self.data[0][0] < cutoff_time:
            self.data.popleft()
            
    def _resample_data(self, target_width: int) -> list[float]:
        """
        Resample data to fit the target width by averaging values in buckets.
        
        Args:
            target_width: Desired number of data points
            
        Returns:
            List of resampled values
        """
        if not self.data or target_width <= 0:
            return []
            
        values = [value for _, value in self.data]
        data_len = len(values)
        
        if data_len <= target_width:
            # If we have fewer data points than target width, return as-is
            return values
            
        # Create buckets and average values within each bucket
        bucket_size = data_len / target_width
        resampled = []
        
        for i in range(target_width):
            start_idx = int(i * bucket_size)
            end_idx = int((i + 1) * bucket_size)
            if end_idx > data_len:
                end_idx = data_len
                
            if start_idx < end_idx:
                bucket_values = values[start_idx:end_idx]
                avg_value = sum(bucket_values) / len(bucket_values)
                resampled.append(avg_value)
                
        return resampled
        
    def render(self, panel_width: int) -> str:
        """
        Render the sparkline to fit the given panel width.
        
        Args:
            panel_width: Width of the panel in characters
            
        Returns:
            Multi-line string representing the sparkline
        """
        # Account for panel borders and padding (rough estimate)
        graph_width = max(1, panel_width - 4)
        
        # Trim old data first
        if self.data:
            self._trim_old_data(time.monotonic())
            
        # Resample data to fit the width
        values = self._resample_data(graph_width)
        
        # Use the existing make_sparkline function
        return make_sparkline(values, self.height)
