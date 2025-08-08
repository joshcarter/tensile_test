#!/usr/bin/env python3
"""
tensile_test.py - Main entry point for the tensile tester application

Usage:
  # 1) Calibrate:
  python tensile_test.py calibrate --port /dev/cu.usbserial101

  # 2) Test:
  python tensile_test.py test \
    --port /dev/cu.usbserial101 \
    --type PETG \
    --manufacturer "Atomic Filament" \
    --color "black" \
    --axis xy \
    --trials 5 \

The port will be auto-detected if not specified (MacOS only), but you can also pass it explicitly.
"""
import argparse
import json
import os

from serial_helper import SerialMovingAverageReader
from calibrate_app import CalibrateApp
from test_app import TestApp, TEST_RESULTS, TEST_RESULT_FORCE, TEST_RESULT_STRENGTH


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