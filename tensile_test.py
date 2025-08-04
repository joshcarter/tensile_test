#!/usr/bin/env python3
"""
tensile_tester.py

Usage:
  # 1) Calibrate:
  python tensile_tester.py calibrate --port /dev/cu.usbserial101

  # 2) Test:
  python tensile_tester.py test \
    --port /dev/cu.usbserial101 \
    --type PETG \
    --manufacturer "Atomic Filament" \
    --color "black" \
    --axis xy \
    --trials 5 \

The port will be auto-detected if not specified (MacOS only), but you can also pass it explicitly.
"""
import argparse, json, os, sys, time, csv, statistics, io, zipfile
from collections import deque

from serial_helper import SerialMovingAverageReader

from rich.panel import Panel
from rich.text import Text

from textual.app import App, ComposeResult
from textual.widgets import Static
from textual.containers import Container

G = 9.80665  # m/s²
CAL_FILE = "calibration.json"
CAL_WEIGHTS = [0.0, 7.9, 15.9, 31.4]  # kg
SAMPLE_INTERVAL = 0.01  # 100 Hz
DROP_DURATION = 10.0  # seconds below threshold to end trial
SPARK_BLOCKS = "▁▂▃▄▅▆▇█"
SPARK_DURATION = 1.5
XY_AXIS_AREA = 20  # mm^2 cross-sectional area for the XY axis test
Z_AXIS_AREA = 30  # mm^2 cross-sectional area for the Z axis test

TEST_RESULTS = []  # will hold max forces per trial
TEST_RESULT_FORCE = None  # will hold the final average force
TEST_RESULT_STRENGTH = None  # will hold the final average strength

class CalibrateApp(App):
    """TUI for calibration."""
    CSS_PATH = None
    BINDINGS = [("enter", "proceed", "Next")]

    def __init__(self):
        super().__init__()
        self.reader = None

        self.data = deque()  # (t, raw)
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
        self.reader = SerialMovingAverageReader(self.port)
        self.start_stage()

        # periodic updates
        self.set_interval(SAMPLE_INTERVAL, self.update_reading)
        self.set_interval(0.2, SAMPLE_PLOT := self.update_plot)

    def start_stage(self):
        """Prepare for the next weight stage."""
        w = CAL_WEIGHTS[self.stage]
        self.collecting = False
        self.stage_samples.clear()
        self.data.clear()
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
        sample = self.reader.read_raw()  # Use the raw readings as we're going to average anyway.
        t = time.monotonic()
        # store for sparkline
        self.data.append((t, sample))
        # trim older than 5 s
        while self.data and (t - self.data[0][0]) > SPARK_DURATION:
            self.data.popleft()
        # if collecting stage samples
        if self.collecting:
            self.stage_samples.append(sample)

    def update_plot(self):
        """Re-render the 5 s sparkline of raw data."""
        arr = [r for _, r in self.data]
        plot = self.make_sparkline(arr)
        self.query_one("#plot", Static).update(Panel(plot, title="raw counts"))

    @staticmethod
    def make_sparkline(data: list[float]) -> str:
        if not data:
            return ""
        lo, hi = min(data), max(data)
        rng = hi - lo or 1.0
        chars = []
        for v in data:
            lvl = int((v - lo) / rng * (len(SPARK_BLOCKS) - 1))
            chars.append(SPARK_BLOCKS[lvl])
        return "".join(chars)


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

        self.reader = None
        self.offset = None
        self.slope = None

        self.data = deque()  # (t, raw, F)
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
        # load calibration
        cal = json.load(open(CAL_FILE))
        self.offset, self.slope = cal["offset"], cal["slope"]

        # serial
        self.reader = SerialMovingAverageReader(self.port)

        # start polling
        self.set_interval(SAMPLE_INTERVAL, self.update_reading)
        self.set_interval(0.2, self.update_plot)

        # initialize UI
        self.query_one("#header", Static).update(
            f"[b]MODE:[/] test    [b]RAW:[/] –    [b]N:[/] –    "
            f"[b]TYPE:[/] {self.type}    [b]AXIS:[/] {self.axis}    "
        )
        self.query_one("#footer", Static).update("below threshold…")

    def update_reading(self):
        sample = self.reader.read_smoothed()
        now = time.monotonic()
        # convert to N
        F = (sample - self.offset) / self.slope
        # update header
        hdr = self.query_one("#header", Static)
        hdr.update(
            f"[b]MODE:[/] test    [b]RAW:[/] {sample:.0f}    [b]N:[/] {F:.1f}    "
            f"[b]TYPE:[/] {self.type}    [b]AXIS:[/] {self.axis}    "
            f"[b]TRIAL:[/] {self.trial_idx}/{self.trials}    "
        )
        # keep 5 s plot buffer
        self.data.append((now, sample, F))
        while self.data and (now - self.data[0][0]) > SPARK_DURATION:
            self.data.popleft()

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
        dname = f"data/{self.manufacturer} {self.type} {self.color}"
        os.makedirs(dname, exist_ok=True)

        # write ZIP-compressed CSV
        fname = f"{self.axis}-trial-{self.trial_idx}.csv"
        with zipfile.ZipFile(os.path.join(dname, fname + ".zip"), "w", compression=zipfile.ZIP_DEFLATED) as zipf:
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
            # auto-quit when all trials are done
            global TEST_RESULT_FORCE, TEST_RESULT_STRENGTH
            TEST_RESULT_FORCE = statistics.mean(self.results)

            if self.axis == "z":
                TEST_RESULT_STRENGTH = TEST_RESULT_FORCE / Z_AXIS_AREA
            else:
                TEST_RESULT_STRENGTH = TEST_RESULT_FORCE / XY_AXIS_AREA

            self.log_summary(dname)
            self.update_master_summary()
            self.reader.close()
            self.exit()
        else:
            # next trial
            self.state = "waiting"
            self.query_one("#footer", Static).update("below threshold…")
            self.data.clear()
            self.reader.reset()

    def log_summary(self, dname):
        """Write a summary of the test results to a file."""
        fname = os.path.join(dname, f"summary.txt")
        with open(fname, "a") as f:
            f.write("=== Test Summary ===\n")
            f.write(f"Manufacturer: {self.manufacturer}\n")
            f.write(f"Material Type: {self.type}\n")
            f.write(f"Color: {self.color}\n")
            f.write(f"Axis: {self.axis}\n")
            f.write(f"Trials: {self.trials}\n")
            f.write(f"Threshold: {self.threshold} N\n")
            f.write(f"Extrusion width: {self.extrusion_width} mm\n")
            f.write(f"Layer height: {self.layer_height} mm\n")
            f.write(f"Printer: {self.printer}\n")
            f.write("Results:\n")
            for i, res in enumerate(self.results, 1):
                f.write(f"  Trial {i}: {res:.2f} N\n")
            f.write(f"Average max force: {TEST_RESULT_FORCE:.2f} N\n")
            f.write(f"Tensile strength: {TEST_RESULT_STRENGTH:.2f} MPa\n")
            f.write("\n\n")

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
        """Re-render 5 s sparkline of force in N."""
        arr = [F for _, _, F in self.data]
        plot = CalibrateApp.make_sparkline(arr)
        self.query_one("#plot", Static).update(Panel(plot, title="force [N]"))


def main():
    # Load configuration overrides from configuration.json
    config = {}
    config_path = "configuration.json"
    if os.path.exists(config_path):
        with open(config_path) as cf:
            config = json.load(cf)

    p = argparse.ArgumentParser()
    subs = p.add_subparsers(dest="cmd", required=True)

    c = subs.add_parser("calibrate")
    c.add_argument("--port", "-p", required=False, default=config.get("port", None))
    c.set_defaults(mode="calibrate")

    t = subs.add_parser("test")
    t.add_argument("--port", "-p", required=False, default=config.get("port", None))
    t.add_argument("--type", "-t", required=True)
    t.add_argument("--manufacturer", "-m", required=True)
    t.add_argument("--color", "-c", required=True)
    t.add_argument("--axis", "-a", choices=("xy", "z"), required=True)
    t.add_argument("--trials", type=int, default=config.get("trials", 5))
    t.add_argument("--threshold", type=float, default=config.get("threshold", 50.0))
    t.add_argument("--extrusion-width", type=float, help="Extrusion width in mm", default=config.get("extrusion_width", 0.4)),
    t.add_argument("--layer-height", type=float, help="Layer height in mm", default=config.get("layer_height", 0.2)),
    t.add_argument("--printer", help="Printer model or name", default=config.get("printer", ""))
    t.set_defaults(mode="test")

    args = p.parse_args()

    # Open port before starting the TUI so that any error messages will print.
    reader = SerialMovingAverageReader(args.port)

    if args.mode == "calibrate":
        app = CalibrateApp()
        app.reader = reader
        app.run()
    else:
        app = TestApp()
        app.reader = reader
        app.type = args.type
        app.manufacturer = args.manufacturer
        app.color = args.color
        app.axis = args.axis
        app.trials = args.trials
        app.threshold = args.threshold
        app.extrusion_width = args.extrusion_width
        app.layer_height = args.layer_height
        app.printer = args.printer
        app.run()

        # need to print this after the TUI exits
        print("\n=== TEST SUMMARY ===")
        for i, res in enumerate(TEST_RESULTS, 1):
            print(f"  Trial {i}: {res:.2f} N")
        print(f"Average max force: {TEST_RESULT_FORCE:.2f} N")
        print(f"Tensile strength: {TEST_RESULT_STRENGTH:.2f} MPa")


if __name__ == "__main__":
    main()
