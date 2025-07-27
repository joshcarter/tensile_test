#!/usr/bin/env python3
"""
tensile_tester.py

Usage:
  # Calibrate (stores offset & slope in calibration.json):
  python tensile_tester.py calibrate --port /dev/ttyACM1

  # Run 5 trials on “LDPE” from “ACME Plastics” with 50 N threshold:
  python tensile_tester.py test \
    --port /dev/ttyACM1 \
    --type LDPE \
    --manufacturer "ACME Plastics" \
    --trials 5 \
    --threshold 50
"""
import argparse, serial, time, json, statistics, sys, os

G = 9.80665  # m/s²
CAL_FILE = "calibration.json"

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
            print(f"  Read {len(vals)}: {r:.2f}", end="\r")
        time.sleep(delay)
    return statistics.mean(vals)

def calibrate(args):
    ser = connect_serial(args.port)
    input("1) Remove all weight and press Enter → ")
    zero = average_reading(ser)
    print(f"Zero baseline: {zero:.2f}")

    weights = [8.0, 16.0, 31.6]  # kg
    readings = []
    for w in weights:
        input(f"2) Place {w} kg weight and press Enter → ")
        r = average_reading(ser)
        readings.append(r)
        print(f"  Reading @ {w} kg: {r:.2f}")

    deltas = [r - zero for r in readings]
    forces = [w * G for w in weights]  # N
    slopes = [delta / F for delta, F in zip(deltas, forces)]
    m = statistics.mean(slopes)
    print(f"Scale factor (counts per N): {m:.6f}")

    cal = {"offset": zero, "slope": m}
    with open(CAL_FILE, "w") as f:
        json.dump(cal, f, indent=2)
    print(f"Saved calibration → {CAL_FILE}")

def test_mode(args):
    if not os.path.exists(CAL_FILE):
        print("No calibration found. Run `calibrate` first."); sys.exit(1)
    cal = json.load(open(CAL_FILE))
    off, m = cal["offset"], cal["slope"]

    ser = connect_serial(args.port)
    results = []
    print(f"Material: {args.type} (by {args.manufacturer})")
    print(f"Threshold: {args.threshold} N, Trials: {args.trials}")

    for ti in range(1, args.trials + 1):
        print(f"\n--- Trial {ti} ---")
        ser.reset_input_buffer()

        # wait for force to exceed threshold
        F = 0
        while F < args.threshold:
            r = read_raw(ser)
            if r is None: continue
            F = (r - off) / m
        print("  Capture phase…")
        maxF = F
        # record until it drops below threshold again
        while True:
            r = read_raw(ser)
            if r is None: continue
            F = (r - off) / m
            if F > maxF: maxF = F
            if F < args.threshold: break
        print(f"  Trial {ti} max = {maxF:.2f} N")
        results.append(maxF)

    avg = statistics.mean(results)
    print("\n=== Summary ===")
    print(f"{'Trial':>6} | {'Max Force (N)':>12}")
    for i, f in enumerate(results, 1):
        print(f"{i:6} | {f:12.2f}")
    print(f"\nAverage max force: {avg:.2f} N")

def main():
    p = argparse.ArgumentParser()
    subs = p.add_subparsers(dest="cmd", required=True)

    c1 = subs.add_parser("calibrate")
    c1.add_argument("--port", "-p", required=True, help="Serial port (e.g. /dev/ttyACM1)")
    c1.set_defaults(func=calibrate)

    c2 = subs.add_parser("test")
    c2.add_argument("--port", "-p",      required=True)
    c2.add_argument("--type",           required=True, help="Plastic type")
    c2.add_argument("--manufacturer",   required=True)
    c2.add_argument("--axis",          choices=["xy", "z"], default="xy", help="Axis to measure (default: xy)")
    c2.add_argument("--trials",   type=int,   default=5)
    c2.add_argument("--threshold",type=float, default=100.0, help="N")
    c2.set_defaults(func=test_mode)

    args = p.parse_args()
    args.func(args)

if __name__=="__main__":
    main()
