#!/usr/bin/env python3
"""
tensile_tester.py

Usage:
  # Calibrate (unchanged):
  python tensile_tester.py calibrate --port /dev/ttyACM1

  # Run test with GUI:
  python tensile_tester.py test \
    --port /dev/ttyACM1 \
    --type LDPE \
    --manufacturer "ACME Plastics" \
    --trials 5 \
    --threshold 50
"""

import argparse, serial, time, json, statistics, sys, os, csv
import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import signal

G = 9.80665  # m/s²
CAL_FILE = "calibration.json"
SAMPLE_INTERVAL = 0.01  # seconds between reads
DROP_DURATION = 10.0  # seconds below threshold to end trial
shutdown_requested = False


def connect_serial(port, baud=115200, timeout=1):
    ser = serial.Serial(port, baud, timeout=timeout)
    ser.reset_input_buffer()
    return ser


def read_raw(ser):
    line = ser.readline().decode("utf-8").strip()
    try:
        return float(line)
    except:
        return None


def average_reading(ser, count=50, delay=0.05):
    ser.reset_input_buffer()
    vals = []
    while len(vals) < count:
        r = read_raw(ser)
        if r is not None:
            vals.append(r)
        time.sleep(delay)
    return statistics.mean(vals)


def measure_trial(ser, threshold, offset, slope):
    """
    Wait for reading > threshold, then capture samples until it
    stays below threshold continuously for DROP_DURATION seconds.
    Returns a list of dicts: {'t': seconds, 'raw':counts, 'N':force}.
    """
    ser.reset_input_buffer()

    # wait for start
    while True:
        r = read_raw(ser)
        if r is None: continue
        F = (r - offset) / slope
        if F >= threshold:
            start_time = time.monotonic()
            break

    samples = []
    below_since = None

    # capture loop
    while True:
        now = time.monotonic()
        r = read_raw(ser)
        if r is None:
            time.sleep(SAMPLE_INTERVAL)
            continue
        t = now - start_time
        F = (r - offset) / slope
        samples.append({'t': t, 'raw': r, 'N': F})

        # check drop-below-threshold timer
        if F < threshold:
            if below_since is None:
                below_since = now
            elif (now - below_since) >= DROP_DURATION:
                break
        else:
            below_since = None

        time.sleep(SAMPLE_INTERVAL)

    return samples


def run_test_with_gui(args):
    print("starting gui")
    update_id = None

    # load calibration
    if not os.path.exists(CAL_FILE):
        print("No calibration found. Run `calibrate` first.");
        sys.exit(1)
    cal = json.load(open(CAL_FILE))
    off, m = cal["offset"], cal["slope"]

    ser = connect_serial(args.port)
    print('connected to', ser.portstr)

    # Set up GUI
    root = tk.Tk()
    root.title("Tensile Tester")

    # Top frame: live readings
    top = ttk.Frame(root, padding=10)
    top.pack(side=tk.TOP, fill=tk.X)
    raw_var = tk.StringVar(value="Raw: –")
    N_var = tk.StringVar(value="Force: – N")
    ttk.Label(top, textvariable=raw_var, font=("TkDefaultFont", 14)).pack(side=tk.LEFT, padx=10)
    ttk.Label(top, textvariable=N_var, font=("TkDefaultFont", 14)).pack(side=tk.LEFT, padx=10)

    # Bottom frame: matplotlib plot
    fig, ax = plt.subplots(figsize=(5, 3))
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Force (N)")
    line, = ax.plot([], [], lw=2)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, max(args.threshold * 2, 200))  # initial scale

    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True)

    def do_trials():
        results = []
        for ti in range(1, args.trials + 1):
            raw_var.set(f"Trial {ti}: waiting…")
            root.update()

            samples = measure_trial(ser, args.threshold, off, m)

            # log to CSV
            fname = f"trial_{ti}.csv"
            with open(fname, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=['t', 'raw', 'N'])
                w.writeheader()
                w.writerows(samples)

            maxN = max(s['N'] for s in samples)
            results.append(maxN)
            print(f"Trial {ti} max = {maxN:.2f} N  →   saved {fname}")

        # summary
        avg = statistics.mean(results)
        print("\n=== Summary ===")
        for i, f in enumerate(results, 1):
            print(f"  Trial {i}: {f:.2f} N")
        print(f"\nAverage: {avg:.2f} N")
        raw_var.set("Done.")
        N_var.set(f"Avg max: {avg:.2f} N")

    # live-update loop for GUI & plotting
    times, forces = [], []

    def live_update():
        if shutdown_requested:
            return

        r = read_raw(ser)
        if r is not None:
            F = (r - off) / m
            t = time.monotonic()
            # update labels
            raw_var.set(f"Raw: {r:.0f}")
            N_var.set(f"Force: {F:.1f} N")
            # update plot buffer (last 10s window)
            if times and (t - times[0]) > 10:
                # shift window
                while times and (t - times[0]) > 10:
                    times.pop(0);
                    forces.pop(0)
                ax.set_xlim(times[0], times[0] + 10)
            times.append(t)
            forces.append(F)
            line.set_data(times, forces)
            ax.relim();
            ax.autoscale_view(False, True, False)
            canvas.draw()
        root.after(int(SAMPLE_INTERVAL * 1000), live_update)
        update_id = root.after(int(SAMPLE_INTERVAL*1000), live_update)

    def clean_shutdown():
        nonlocal update_id
        global shutdown_requested
        shutdown_requested = True
        try:
            if update_id:
                root.after_cancel(update_id)
        except Exception as e:
            print("Error cancelling update:", e)
        try:
            ser.close()
        except:
            pass
        root.destroy()

    # For Ctrl+C
    signal.signal(signal.SIGINT, lambda s, f: clean_shutdown())

    # For window close button
    root.protocol("WM_DELETE_WINDOW", clean_shutdown)

    # start live updates & trials
    update_id = root.after(100, live_update)
    root.after(500, lambda: do_trials())
    print('entering main loop')
    root.mainloop()

    try:
        print('closing serial port')
        ser.close()
    except:
        pass


def calibrate(args):
    # unchanged from before...
    ser = connect_serial(args.port)
    input("1) Remove weight → Enter")
    zero = average_reading(ser)
    print(f"Zero: {zero}")
    weights = [16, 24, 32]
    readings = []
    for w in weights:
        input(f"2) Place {w}kg → Enter")
        r = average_reading(ser)
        readings.append(r)
        print(f"{w}kg → {r}")
    deltas = [r - zero for r in readings]
    forces = [w * G for w in weights]
    m = statistics.mean(delta / F for delta, F in zip(deltas, forces))
    json.dump({"offset": zero, "slope": m}, open(CAL_FILE, "w"), indent=2)
    print("Saved calibration.")


def main():
    p = argparse.ArgumentParser()
    subs = p.add_subparsers(dest="cmd", required=True)

    c1 = subs.add_parser("calibrate");
    c1.add_argument("-p", "--port", required=True);
    c1.set_defaults(func=calibrate)

    c2 = subs.add_parser("test")
    c2.add_argument("-p", "--port", required=True)
    c2.add_argument("-t", "--type", required=True)
    c2.add_argument('-m", '"--manufacturer", required=True)
    c2.add_argument("--trials", type=int, default=5)
    c2.add_argument("--threshold", type=float, default=50.0)
    c2.set_defaults(func=run_test_with_gui)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
