"""
Calibration TUI application for the tensile tester.
"""

import os
import sys
import json
import statistics

from textual.app import App, ComposeResult
from textual.widgets import Static
from rich.panel import Panel

from utils import (
    CAL_FILE, CAL_WEIGHTS, G, SAMPLE_INTERVAL, SparklineGraph
)


class CalibrateApp(App):
    """TUI for calibration."""
    CSS_PATH = None
    BINDINGS = [("enter", "proceed", "Next")]

    def __init__(self):
        super().__init__()
        self.reader = None

        self.graph = SparklineGraph()
        self.stage = 0  # index into CAL_WEIGHTS
        self.stage_samples = []  # raw readings for current stage
        self.collecting = False

        self.offset = None
        self.slope = None

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        yield Static("", id="plot", expand=True)
        yield Static("", id="footer")

    async def on_mount(self):
        # connect & start polling
        self.start_stage()

        # periodic updates
        self.set_interval(SAMPLE_INTERVAL, self.update_reading)
        self.set_interval(0.2, self.update_plot)

    def start_stage(self):
        """Prepare for the next weight stage."""
        w = CAL_WEIGHTS[self.stage]
        self.collecting = False
        self.stage_samples.clear()
        self.graph.reset()
        self.reader.reset()
        self.query_one("#header", Static).update(
            f"[b]MODE:[/] calibrate    [b]PLACE[/] {w} kg, then ⏎"
        )
        self.query_one("#footer", Static).update("waiting for ⏎…")

    def action_proceed(self):
        """User pressed Enter → begin 2 s collection."""
        if self.collecting:
            return
        self.collecting = True
        self.query_one("#footer", Static).update("collecting 2 s…")
        # after 2 s, finish this stage
        self.set_timer(2.0, self.finish_stage)

    def finish_stage(self):
        """Called after 2 s of data collection for the current weight."""
        # 1) Log raw samples for record
        fname = f"calibration-{CAL_WEIGHTS[self.stage]}.csv"
        os.makedirs("calibration_data", exist_ok=True)
        with open(os.path.join("calibration_data", fname), "w", newline="") as f:
            for i, sample in enumerate(self.stage_samples, start=1):
                f.write(f"{i},{sample}\n")

        # 2) Compute this stage's average raw reading
        avg = statistics.mean(self.stage_samples) if self.stage_samples else 0.0

        # 3) Initialize readings list on first call
        if not hasattr(self, "stage_readings"):
            self.stage_readings = []

        # 4) On the 0 kg stage, capture your zero‐offset
        if self.offset is None:
            self.offset = avg

        # 5) Record this stage's average
        self.stage_readings.append(avg)

        # 6) Advance to next weight
        self.stage += 1

        # 7) Either loop for more stages or finalize calibration
        if self.stage < len(CAL_WEIGHTS):
            self.start_stage()
        else:
            # 8) Perform linear regression on raw readings vs known forces
            forces = [w * G for w in CAL_WEIGHTS]
            readings = self.stage_readings
            slope, intercept = statistics.linear_regression(forces, readings)

            # 9) Check for outliers: ensure each reading is within 5% of the regression prediction
            tol = 0.05
            for w, r in zip(CAL_WEIGHTS, readings):
                predicted = intercept + slope * (w * G)
                if abs(r - predicted) > tol * r:
                    sys.exit(f"Calibration error: {w} kg reading {r:.2f} deviates by more than {tol*100:.1f}%")

            # 10) Persist calibration with regression intercept as offset
            self.offset = intercept
            self.slope = slope
            with open(CAL_FILE, "w") as cal_f:
                json.dump({"offset": self.offset, "slope": self.slope}, cal_f, indent=2)

            # 11) Clean up and exit
            self.reader.close()
            self.exit()

    def update_reading(self):
        """Read one raw sample + timestamp; append to buffers."""
        try:
            # Use the explicit raw counts method for calibration
            sample = self.reader.read_raw_counts()
        except ValueError as e:
            # Pico has calibration when it shouldn't - show error and exit
            self.query_one("#footer", Static).update(str(e))
            self.reader.close()
            self.exit(return_code=1)
            return

        if sample is None:
            return

        # Add to graph for sparkline
        self.graph.add_value(sample)
        
        # if collecting stage samples
        if self.collecting:
            self.stage_samples.append(sample)
            self.query_one("#header", Static).update(
                f"[b]MODE:[/] calibrate    [b]RAW:[/] {sample:.0f}"
            )

    def update_plot(self):
        """Re-render the sparkline of raw data."""
        plot_widget = self.query_one("#plot", Static)
        panel_width = plot_widget.size.width
        plot = self.graph.render(panel_width)
        plot_widget.update(Panel(plot, title="raw counts"))