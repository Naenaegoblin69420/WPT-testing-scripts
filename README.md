# WPT-testing-scripts

Automation scripts for the wireless-power-transfer (WPT) research project.
Stage 1 (Keysight ADS circuit modelling) is complete; this repo collects the
Python-driven tooling for stage 2 (Ansys HFSS 3-D coil design) and beyond.

## Contents

| Path                                           | Runtime               | Purpose                                                                                  |
| ---------------------------------------------- | --------------------- | ---------------------------------------------------------------------------------------- |
| [`hfss/design_400MHz_coils.py`](hfss/design_400MHz_coils.py) | IronPython in HFSS | Build the primary + secondary square planar spirals (400 MHz target), bridges, ports, ferrite slab, sweep, output variables. |
| [`hfss/single_square_loop.py`](hfss/single_square_loop.py)   | IronPython in HFSS | Build ONE square loop with rounded corners and a 1 mm gap, centred on the origin.        |
| [`hfss/README.md`](hfss/README.md)             | —                     | Run instructions, parameter blocks, tuning guide, k-feasibility notes for the scripts above. |

Both HFSS scripts run via **Automation → Run Script** inside HFSS (bundled
IronPython 2.7 + COM API — no pip install needed).

See each tool's README for installation and usage.
