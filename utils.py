"""
Utility functions and constants for the tensile tester application.
"""

# Constants for sparkline plotting
SPARK_BLOCKS = "▁▂▃▄▅▆▇█"
SPARK_DURATION = 1.5
SPARK_HEIGHT = 10  # Number of lines for the sparkline plot

# Test constants
SAMPLE_INTERVAL = 0.01  # 100 Hz
DROP_DURATION = 10.0  # seconds below threshold to end trial
XY_AXIS_AREA = 20  # mm^2 cross-sectional area for the XY axis test
Z_AXIS_AREA = 30  # mm^2 cross-sectional area for the Z axis test

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