#!/usr/bin/env python3
"""
tensile_tester.py

Usage:
  # 1) Calibrate:
  python tensile_tester.py calibrate --port /dev/ttyACM1

  # 2) Test:
  python tensile_tester.py test \
    --port /dev/ttyACM1 \
    --type LDPE \
    --manufacturer "ACME Plastics" \
    --axis z \
    --trials 5 \
    --threshold 50
"""
import argparse, json, os, sys, time, csv, statistics
from collections import deque

from serial_helper import SerialMovingAverageReader

from rich.panel import Panel
from rich.text import Text

from textual.app import App, ComposeResult
from textual.widgets import Static
from textual.containers import Container

G = 9.80665  # m/s²
CAL_FILE = "calibration.json"
CAL_WEIGHTS = [0.0, 8.0, 16.0, 31.6]  # kg
SAMPLE_INTERVAL = 0.01    # 100 Hz
DROP_DURATION   = 10.0    # seconds below threshold to end trial
SPARK_BLOCKS    = "▁▂▃▄▅▆▇█"
SPARK_DURATION = 1.5

TEST_RESULTS = []  # will hold max forces per trial



class CalibrateApp(App):
    """TUI for calibration."""
    CSS_PATH = None
    BINDINGS = [("enter", "proceed", "Next")]

    def __init__(self, port:str):
        super().__init__()
        self.port = port
        self.reader = None

        self.data = deque()       # (t, raw)
        self.stage = 0            # index into CAL_WEIGHTS
        self.stage_samples = []   # raw readings for current stage
        self.collecting = False

        self.offset = None
        self.slope  = None

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
        """Called after 2 s of data collection."""
        # log to file
        fname = f"calibration-{CAL_WEIGHTS[self.stage]}.csv"
        with open(fname, "w", newline="") as f:
            for i in range(len(self.stage_samples)):
                f.write(f"{i+1},{self.stage_samples[i]}\n")

        avg = statistics.mean(self.stage_samples) if self.stage_samples else 0.0
        self.stage += 1
        # record reading
        if self.offset is None:
            self.offset = avg
            self.stage_readings = [avg]
        else:
            self.stage_readings.append(avg)

        self.stage_readings = getattr(self, "stage_readings", []) + [avg]

        if self.stage < len(CAL_WEIGHTS):
            self.start_stage()
        else:
            # compute slope & save
            zero = self.stage_readings[0]
            slopes = [
                (r - zero) / (w * G)
                for r, w in zip(self.stage_readings[1:], CAL_WEIGHTS[1:])
            ]
            self.slope = statistics.mean(slopes)
            json.dump({"offset": zero, "slope": self.slope}, open(CAL_FILE, "w"), indent=2)
            self.reader.close()
            self.exit()

    def update_reading(self):
        """Read one raw sample + timestamp; append to buffers."""
        sample = self.reader.read_raw()
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
            lvl = int((v - lo) / rng * (len(SPARK_BLOCKS)-1))
            chars.append(SPARK_BLOCKS[lvl])
        return "".join(chars)

class TestApp(App):
    """TUI for running tensile trials."""
    CSS_PATH = None

    def __init__(self, port, mat_type, manufacturer, axis, trials, threshold):
        super().__init__()
        self.port = port
        self.type = mat_type
        self.manufacturer = manufacturer
        self.axis = axis
        self.trials = trials
        self.threshold = threshold

        self.reader = None
        self.offset = None
        self.slope  = None

        self.data = deque()      # (t, raw, F)
        self.state = "waiting"   # waiting -> measuring -> done
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
        # write CSV
        fname = f"{self.manufacturer}-{self.type}-{self.axis}-{self.trial_idx}.csv"
        with open(fname, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time_ms","force_N"])
            w.writerows(self.trial_samples)
        maxF = max(f for _,f in self.trial_samples)
        self.results.append(maxF)
        TEST_RESULTS.append(maxF)
        self.trial_idx += 1

        if self.trial_idx > self.trials:
            self.reader.close()
            self.exit()
        else:
            # next trial
            self.state = "waiting"
            self.query_one("#footer", Static).update("below threshold…")
            self.data.clear()
            self.reader.reset()

    def update_plot(self):
        """Re-render 5 s sparkline of force in N."""
        arr = [F for _,_,F in self.data]
        plot = CalibrateApp.make_sparkline(arr)
        self.query_one("#plot", Static).update(Panel(plot, title="force [N]"))

def main():
    p = argparse.ArgumentParser()
    subs = p.add_subparsers(dest="cmd", required=True)

    c = subs.add_parser("calibrate")
    c.add_argument("--port", "-p", required=False, default=None)
    c.set_defaults(mode="calibrate")

    t = subs.add_parser("test")
    t.add_argument("--port",         "-p", required=False, default=None)
    t.add_argument("--type",         "-t", required=True)
    t.add_argument("--manufacturer", "-m", required=True)
    t.add_argument("--axis",    choices=("xy","z"), required=True)
    t.add_argument("--trials",   type=int,     default=5)
    t.add_argument("--threshold",type=float,   default=50.0)
    t.set_defaults(mode="test")

    args = p.parse_args()

    if args.mode == "calibrate":
        CalibrateApp(args.port).run()
    else:
        TestApp(
            args.port,
            args.type,
            args.manufacturer,
            args.axis,
            args.trials,
            args.threshold,
        ).run()
        # after auto-quit, print summary
        print("\n=== TEST SUMMARY ===")
        for i, f in enumerate(TEST_RESULTS, 1):
            print(f"  Trial {i}: {f:.2f} N")
        print(f"Average max force: {statistics.mean(TEST_RESULTS):.2f} N")

if __name__ == "__main__":
    main()
