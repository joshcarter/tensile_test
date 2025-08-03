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

    def __init__(self, port: str):
        super().__init__()
        self.port = port
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

    def __init__(self, port, mat_type, manufacturer, color, axis, trials, threshold):
        super().__init__()
        self.port = port
        self.type = mat_type
        self.manufacturer = manufacturer
        self.color = color
        self.axis = axis
        self.trials = trials
        self.threshold = threshold

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
            f.write("Results:\n")
            for i, res in enumerate(self.results, 1):
                f.write(f"  Trial {i}: {res:.2f} N\n")
            f.write(f"Average max force: {TEST_RESULT_FORCE:.2f} N\n")
            f.write(f"Tensile strength: {TEST_RESULT_STRENGTH:.2f} MPa\n")
            f.write("\n\n")

    def update_plot(self):
        """Re-render 5 s sparkline of force in N."""
        arr = [F for _, _, F in self.data]
        plot = CalibrateApp.make_sparkline(arr)
        self.query_one("#plot", Static).update(Panel(plot, title="force [N]"))


def main():
    p = argparse.ArgumentParser()
    subs = p.add_subparsers(dest="cmd", required=True)

    c = subs.add_parser("calibrate")
    c.add_argument("--port", "-p", required=False, default=None)
    c.set_defaults(mode="calibrate")

    t = subs.add_parser("test")
    t.add_argument("--port", "-p", required=False, default=None)
    t.add_argument("--type", "-t", required=True)
    t.add_argument("--manufacturer", "-m", required=True)
    t.add_argument("--color", "-c", required=True)
    t.add_argument("--axis", "-a", choices=("xy", "z"), required=True)
    t.add_argument("--trials", type=int, default=5)
    t.add_argument("--threshold", type=float, default=50.0)
    t.set_defaults(mode="test")

    args = p.parse_args()

    if args.mode == "calibrate":
        CalibrateApp(args.port).run()
    else:
        TestApp(
            args.port,
            args.type,
            args.manufacturer,
            args.color,
            args.axis,
            args.trials,
            args.threshold,
        ).run()

        # need to print this after the TUI exits
        print("\n=== TEST SUMMARY ===")
        for i, res in enumerate(TEST_RESULTS, 1):
            print(f"  Trial {i}: {res:.2f} N")
        print(f"Average max force: {TEST_RESULT_FORCE:.2f} N")
        print(f"Tensile strength: {TEST_RESULT_STRENGTH:.2f} MPa")


if __name__ == "__main__":
    main()
