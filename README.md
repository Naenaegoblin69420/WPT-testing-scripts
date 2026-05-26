# WPT-testing-scripts

Automation scripts for the wireless-power-transfer (WPT) research project.
Stage 1 (Keysight ADS circuit modelling) is complete; this repo collects the
Python-driven tooling for stage 2 (Ansys HFSS 3-D coil design) and beyond.

## Contents

| Path                                           | Tool       | Purpose                                                                                  |
| ---------------------------------------------- | ---------- | ---------------------------------------------------------------------------------------- |
| [`hfss/design_400MHz_coils.py`](hfss/design_400MHz_coils.py) | PyAEDT     | Build the primary + secondary square planar spirals (400 MHz target), ports, sweep, reports. |
| [`hfss/README.md`](hfss/README.md)             | —          | Install, target parameters, tuning guide, k-feasibility notes for the script above.       |

See each tool's README for installation and usage.
