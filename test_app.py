"""
Testing TUI application for the tensile tester.
"""

import os
import time
import csv
import statistics
import io
import zipfile
import sys

from textual.app import App, ComposeResult
from textual.widgets import Static
from rich.panel import Panel

from utils import (
    SAMPLE_INTERVAL, DROP_DURATION,
    XY_AXIS_AREA, Z_AXIS_AREA, SparklineGraph
)


# Global variables for test results (shared with main)
TEST_RESULTS = []  # will hold max forces per trial
TEST_RESULT_FORCE = 0.0  # will hold the final average force
TEST_RESULT_STRENGTH = 0.0  # will hold the final average strength


class TestApp(App):
    """TUI for running tensile trials."""
    CSS_PATH = None

    def __init__(self):
        super().__init__()
        self.type = None
        self.manufacturer = None
        self.color = None
        self.axis = None
        self.trials = None
        self.threshold = None
        self.extrusion_width = None
        self.layer_height = None
        self.printer = None
        self.cross_section = None  # will be set to XY_AXIS_AREA, Z_AXIS_AREA, or CLI arg
        self.dirname = None  # directory for saving results

        self.reader = None

        self.graph = SparklineGraph()
        self.state = "waiting"  # waiting -> measuring -> done
        self.trial_idx = 1
        self.trial_start = None
        self.below_since = None
        self.trial_samples = []  # (ms, F)
        self.results = []

    def compose(self) -> ComposeResult:
        yield Static("", id="header")
        yield Static("", id="plot", expand=True)
        yield Static("", id="footer")

    async def on_mount(self):
        if self.cross_section is None:
            if self.axis == "z":
                self.cross_section = Z_AXIS_AREA
            else:
                self.cross_section = XY_AXIS_AREA

        # Set up directory for results
        self.dirname = f"data/{self.manufacturer} {self.type} {self.color}"
        os.makedirs(self.dirname, exist_ok=True)

        # start polling
        self.set_interval(SAMPLE_INTERVAL, self.update_reading)
        self.set_interval(0.2, self.update_plot)

        # initialize UI
        self.query_one("#header", Static).update(
            f"[b]MODE:[/] test    [b]N:[/] –    "
            f"[b]TYPE:[/] {self.type}    [b]AXIS:[/] {self.axis}    "
        )
        self.query_one("#footer", Static).update("below threshold…")

    def update_reading(self):
        now = time.monotonic()

        # Read Newton values directly from Pico
        try:
            F = self.reader.read_smoothed_newtons()
        except ValueError as e:
            # Pico is not calibrated - show error and exit
            self.query_one("#footer", Static).update(str(e))
            self.reader.close()
            self.exit(return_code=1)
            return

        # update header (no more raw values)
        hdr = self.query_one("#header", Static)
        hdr.update(
            f"[b]MODE:[/] test    [b]N:[/] {F:.1f}    "
            f"[b]TYPE:[/] {self.type}    [b]AXIS:[/] {self.axis}    "
            f"[b]TRIAL:[/] {self.trial_idx}/{self.trials}    "
        )

        # Add to graph for sparkline
        self.graph.add_value(F)

        # state machine
        if self.state == "waiting":
            if F >= self.threshold:
                self.state = "measuring"
                self.trial_start = now
                self.below_since = None
                self.trial_samples.clear()
                self.query_one("#footer", Static).update("measuring…")
        elif self.state == "measuring":
            t_ms = int((now - self.trial_start) * 1000)
            self.trial_samples.append((t_ms, F))
            if F >= self.threshold:
                self.below_since = None
            else:
                if self.below_since is None:
                    self.below_since = now
                elif (now - self.below_since) >= DROP_DURATION:
                    self.finish_trial()
        # else done or exiting — ignore further input

    def finish_trial(self):
        global TEST_RESULTS, TEST_RESULT_FORCE, TEST_RESULT_STRENGTH

        # write ZIP-compressed CSV
        fname = f"{self.axis}-trial-{self.trial_idx}.csv"
        with zipfile.ZipFile(os.path.join(self.dirname, fname + ".zip"), "w", compression=zipfile.ZIP_DEFLATED) as zipf:
            with io.StringIO() as csv_buffer:
                w = csv.writer(csv_buffer)
                w.writerow(["time_ms", "force_N"])
                w.writerows(self.trial_samples)
                zipf.writestr(fname, csv_buffer.getvalue())

        maxF = max(f for _, f in self.trial_samples)
        self.results.append(maxF)
        TEST_RESULTS.append(maxF)
        self.trial_idx += 1

        if self.trial_idx > self.trials:
            # All trials completed - exit
            self.reader.close()
            self.exit()
        else:
            # next trial
            self.state = "waiting"
            self.query_one("#footer", Static).update("below threshold…")
            self.graph.reset()
            self.reader.reset()

    def cleanup_and_save_results(self):
        """
        Cleanup method that calculates results and saves summaries for any completed trials.
        Called after the app exits.
        """
        if not self.results:
            # No completed trials to process
            return

        # Calculate results from completed trials
        global TEST_RESULT_FORCE, TEST_RESULT_STRENGTH
        TEST_RESULT_FORCE = statistics.mean(self.results)
        TEST_RESULT_STRENGTH = TEST_RESULT_FORCE / self.cross_section

        # Save summary and update master CSV
        with open(os.path.join(self.dirname, "summary.txt"), "a") as f:
            self.log_summary(f)
        self.log_summary(sys.stdout)
        self.update_master_summary()

    def log_summary(self, out):
        """Write a summary of the test results to a file-like object."""
        completed_trials = len(self.results)
        is_incomplete = completed_trials < self.trials

        out.write("=== Test Summary ===\n")
        if is_incomplete:
            out.write(f"*** INCOMPLETE TEST - {completed_trials} of {self.trials} trials completed ***\n")
        out.write(f"Manufacturer: {self.manufacturer}\n")
        out.write(f"Material Type: {self.type}\n")
        out.write(f"Color: {self.color}\n")
        out.write(f"Axis: {self.axis}\n")
        out.write(f"Cross-section area: {self.cross_section} mm²\n")
        out.write(f"Trials planned: {self.trials}\n")
        out.write(f"Trials completed: {completed_trials}\n")
        out.write(f"Threshold: {self.threshold} N\n")
        out.write(f"Extrusion width: {self.extrusion_width} mm\n")
        out.write(f"Layer height: {self.layer_height} mm\n")
        out.write(f"Printer: {self.printer}\n")
        out.write("Results:\n")
        for i, res in enumerate(self.results, 1):
            out.write(f"  Trial {i}: {res:.2f} N\n")
        out.write(f"Average max force ({completed_trials} trials): {TEST_RESULT_FORCE:.2f} N\n")
        out.write(f"Tensile strength ({completed_trials} trials): {TEST_RESULT_STRENGTH:.2f} MPa\n")
        out.write("\n\n")
        out.flush()

    def update_master_summary(self):
        # Log results to CSV, updating existing rows by type/manufacturer/color
        csv_path = os.path.join("data", "data.csv")
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)

        # Read existing data
        rows = []
        fieldnames = [
            "brand", "material type", "color",
            "extrusion width", "layer height", "printer",
            "xy strength (Mpa)", "z strength (Mpa)"
        ]
        if os.path.exists(csv_path) and os.stat(csv_path).st_size > 0:
            with open(csv_path, newline="") as csv_file:
                reader = csv.DictReader(csv_file)
                for row in reader:
                    rows.append(row)

        # Prepare updated row
        xy_val = f"{TEST_RESULT_STRENGTH:.2f}" if self.axis == "xy" else ""
        z_val = f"{TEST_RESULT_STRENGTH:.2f}" if self.axis == "z" else ""
        found = False
        for row in rows:
            if (row["brand"] == self.manufacturer and
                    row["material type"] == self.type and
                    row["color"] == self.color):
                # Update the proper column
                if self.axis == "xy":
                    row["xy strength (Mpa)"] = xy_val
                else:
                    row["z strength (Mpa)"] = z_val
                row["extrusion width"] = str(self.extrusion_width)
                row["layer height"] = str(self.layer_height)
                row["printer"] = self.printer
                found = True
                break

        # Append new row if not found
        if not found:
            rows.append({
                "brand": self.manufacturer,
                "material type": self.type,
                "color": self.color,
                "extrusion width": str(self.extrusion_width),
                "layer height": str(self.layer_height),
                "printer": self.printer,
                "xy strength (Mpa)": xy_val,
                "z strength (Mpa)": z_val
            })

        # Write all rows back to CSV
        with open(csv_path, "w", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def update_plot(self):
        """Re-render sparkline of force in N."""
        plot_widget = self.query_one("#plot", Static)
        panel_width = plot_widget.size.width
        plot = self.graph.render(panel_width)
        plot_widget.update(Panel(plot, title="force [N]"))