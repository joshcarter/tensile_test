# 3D Printed Plastic Tensile Strength

## Overview

I use this for measuring the tensile strength of 3D printed plastics.
There is a test fixture, an interface board, and program that runs on
a nearby laptop.

## Test Fixture

- Hi-Lift Jack
- Two clamps (see `printed_parts/Clamp.3mf`)
- 500kg S-type load cell
- HX711 load cell amplifier
- Rasperry Pi Pico interface board
- Laptop with USB connection to interface board

## Test Fixture Assembly

TODO: photo and instructions.

## Test Samples

See `printed_parts/Tensile test samples.3mf`. Note that the Z axis has
additional cross-sectional area since the Z axis is usually
substantially weaker.

## Interface Board

- Sparkfun HX711 load cell amplifier
- Raspberry Pi Pico

TODO: circuit schematic

The MicroPython code for the Pico is in the `pico` subdirectory.

## Python Requirements

    pip install -r requirements.txt

## Test Fixture Calibration

Initially the fixture will not be calibrated. Load code on the Pi Pico
(`pico/*.py) and it will output raw readings from the HX711.

Find some number of known calibration weights. I used kettlebells and
used a hanging scale to measure them as accurately as possible. These
readings (in KG) go into the `CAL_WEIGHTS` list in `utils.py`.

Run the calibration:

    python tensile_test.py calibrate --port /dev/cu.usbserial101

The first "known weight" should be no weight except the printed clamp.
Then add each known weight, pressing enter when the fixture is steady.

Finally, a `calibration.json` file will be written to this directory.
That file should be copied to the Pico. Once the Pico has its
calibration file it will output Newtons of force instead of raw HX711
readings.

## Running Tensile Tests

The main program is run like so:

    python tensile_test.py test \
      --port /dev/cu.usbserial101 \
      --type "PETG-CF" \
      --manufacturer "Atomic Filament" \
      --color "black" \
      --axis xy \

All test data will be output to a directory in the `data`
subdirectory, plus summary stats will be collected in `data/data.csv`.
