# 3D Printed Plastic Tensile Strength

## Overview

I use this for measuring the tensile strength of 3D printed plastics. There is a test fixture, an interface board, and program that runs on a nearby laptop.

## Test Fixture

- Hi-Lift Jack
- S-type load cell (I use 200kg)
- Two clamps (see `printed_parts/Clamp.stl`)
- Interface board
- Laptop with USB connection to interface board

## Test Parts

See `printed_parts/Tensile test samples.3mf`. These are sized to fit within the limits of my 200kg load cell. Note that the Z axis has additional cross-sectional area since the Z axis is usually substantially weaker.

The parts probably need to be redesigned to add additional area to the Z axis part. An 30mm^2 I think it's still too small to get an accurate gauge of the true Z axis tensile strength. And it could be fairly argued that a 500kg load cell and much larger sample cross-sections would be better, however I also need to consider just how much plastic I want flying at me at very high velocity when the sample breaks.

## Interface Board

- Sparkfun HX711 load cell amplifier
- Raspberry Pi Pico

The MicroPython code for the Pico is in the `pico` subdirectory.

## Local Program

- Run `python main.py` with the commands `calibrate` (initially) and `test` once the calibration has been done. There's a lot more here to document; TBD at the moment, sorry. Bug me if you really want to use this for yourself.

# Data

All of my collected data is in the `data` subdirectory. Note than any measurements in Newtons needs to be converted to megapascals (divide by cross-sectional area) to get the actual strength. The XY cross-sectional area is 20mm^2 and Z cross-sectional area is 30mm^2.

TBD: just put the data in this README.
