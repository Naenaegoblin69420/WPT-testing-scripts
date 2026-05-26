# HFSS scripts — WPT coil design

IronPython 2.7 scripts that build the 3-D models for the wireless-power-transfer
(WPT) coil pair in Ansys HFSS. Stage-2 follow-up to the Keysight ADS circuit
simulations. Run via **Automation → Run Script** inside HFSS.

## Files

| File                          | What it does                                                                 |
| ----------------------------- | ---------------------------------------------------------------------------- |
| `design_400MHz_coils.py`      | Builds primary + secondary square planar spirals + bridges + ports + ferrite slab + region + 400 MHz adaptive solve + 50–800 MHz sweep + L/R/M/k/Q output variables. |
| `single_square_loop.py`       | Builds ONE square loop with rounded corners and a 1 mm gap (parameterised), with optional port + region + setup. |

## How to run

1. Open / create an HFSS **DrivenModal** design.
2. **Automation → Run Script**, pick the file.
3. Edit the parameter block at the top of the file and re-run from the
   same menu.

No `pip install` needed — these scripts use HFSS's bundled IronPython 2.7
and the COM API (`oEditor.CreatePolyline`, `oBoundary.AssignLumpedPort`, …).
For an external-Python (PyAEDT) version of either script, see the git
history before commit `807e64d` — those used CPython 3.x and won't parse
in IronPython.

## Design targets (`design_400MHz_coils.py`, 400 MHz)

|              | Primary  | Secondary |
| ------------ | -------- | --------- |
| L            | 120 nH   | 80 nH     |
| R @ 400 MHz  | 2.85 Ω   | 2 Ω       |
| Outer size   | (free)   | ≤ 10 mm   |
| Gap          | 11 mm (fixed) |     |
| k            | ~0.25 (stretch) |    |
| Conductor    | copper, 35 µm (1 oz Cu) |  |

## What `design_400MHz_coils.py` does

1. Builds each coil as a copper square-planar-spiral polyline with
   rectangular cross-section (trace width × thickness). The bottom-right
   corner of each turn steps inward by `w + s` to thread to the next turn.
2. Brings the inner end out over a copper **bridge** 0.5 mm above the
   spiral, then back down to the same z plane as the outer lead, so both
   ends sit on the same plane and a port sheet can bridge them.
3. Optionally places a parameterised **ferrite slab** behind the primary
   (registers a custom NiZn-like material first via
   `oProject.GetDefinitionManager().AddMaterial`). See the section below.
4. Drops a **lumped circuit port** across the 0.2 mm gap between the two
   pads of each coil — one port per coil, 50 Ω, renormalised, with the
   integration line spanning the gap.
5. Creates an **air region** padded by 30 mm (~λ/25 at 400 MHz, fine with
   a rad boundary) and assigns **AssignRadiation** to all six faces.
6. Inserts an **adaptive solve at 400 MHz** (20 passes, ΔS = 0.01) plus a
   **50–800 MHz interpolating sweep**.
7. Creates **output variables** computed from the open-circuit Z-matrix:

   ```
   L1_nH        = im(Z(Primary,Primary))      / (2 π f) * 1e9
   L2_nH        = im(Z(Secondary,Secondary))  / (2 π f) * 1e9
   M_nH         = im(Z(Primary,Secondary))    / (2 π f) * 1e9
   R1_ohm       = re(Z(Primary,Primary))
   R2_ohm       = re(Z(Secondary,Secondary))
   k_coupling   = im(Z₁₂) / sqrt(im(Z₁₁) · im(Z₂₂))
   Q1_unloaded  = im(Z₁₁) / re(Z₁₁)
   Q2_unloaded  = im(Z₂₂) / re(Z₂₂)
   ```

   These are open-circuit by definition: the network's Z-matrix is
   defined with all "other" ports' I = 0, so `Z(Primary,Primary)` is the
   primary's impedance with the secondary open — which is what you want
   for `R_internal` and `Q_unloaded`.

The script does not create reports automatically (IronPython COM
`CreateReport` is fiddly). Right-click **Results → Create Modal Solution
Data Report → Rectangular Plot**, then pick `L1_nH`, `R1_ohm`, etc. from
the output-variable list.

## Tuning guide

| Observed (HFSS) | What to change |
| --------------- | -------------- |
| L too high      | shrink `D_OUT_MM`, drop a turn, or widen `TRACE_S_MM` (smaller fill ratio) |
| L too low       | grow `D_OUT_MM` or add a turn |
| R too high      | widen the trace `TRACE_W_MM` (R ∝ 1/w at fixed length) |
| R too low       | narrow `TRACE_W_MM`, or thin the Cu (skin already dominates at 400 MHz so `TRACE_T_MM` past ~10·δ ≈ 35 µm has little effect) |
| k too low       | enable `FERRITE_ENABLED` (see below), or enlarge the primary's `D_OUT_MM` |
| k boost adds too much R₁ | drop `FERRITE_MU_R` or `FERRITE_MAG_TAN_DELTA`, or grow `FERRITE_AIR_GAP_MM` |
| Im(Z₁₁) < 0 at 400 MHz | you are above self-resonance — grow `TRACE_S_MM` to drop parasitic C between turns |

## Ferrite back-concentrator

The script places a parameterised square ferrite slab behind the primary
(opposite the secondary). It acts as a magnetic mirror — flux that would
otherwise leak away from the secondary is reflected back through the
primary plane. Top-of-file knobs:

| Param | Default | What it controls |
| ----- | ------- | ---------------- |
| `FERRITE_ENABLED` | `True` | turn the slab on/off without deleting anything |
| `FERRITE_LATERAL_SIZE_MM` | `25.0` | square slab side; ~2 × primary `D_OUT_MM` is a good starting point |
| `FERRITE_THICKNESS_MM` | `1.0` | z extent; at 400 MHz ferrite skin depth is metres, so 1 mm is plenty |
| `FERRITE_AIR_GAP_MM` | `0.10` | gap between slab top and primary bottom (smaller → tighter coupling) |
| `FERRITE_MU_R` | `30.0` | relative permeability (real part) at 400 MHz |
| `FERRITE_MAG_TAN_DELTA` | `0.10` | tan δ_μ — the dominant loss term, contributes to R₁ |
| `FERRITE_EPS_R` | `12.0` | dielectric constant of the ferrite |
| `FERRITE_DIEL_TAN_DELTA` | `0.001` | usually small for ferrites |
| `FERRITE_CONDUCTIVITY` | `0.01` | NiZn ferrites are essentially insulators (S/m) |

**Boost rule of thumb (image-current method):**
`M_with / M_without ≈ 1 + (μ_r − 1) / (μ_r + 1)`. For μ_r = 30 this is
~1.94×; for μ_r = 10, ~1.82×.

**Loss tradeoff:** the ferrite's tan δ_μ adds to R₁_internal (the primary's
flux now passes through a lossy medium on its return path). At 400 MHz
typical NiZn ferrites sit at tan δ_μ ≈ 0.05–0.3. If HFSS reports R₁ much
higher than the 2.85 Ω target after enabling the slab, the levers are:
(a) widen `PRI_TRACE_W_MM` (takes R₁ back down before the ferrite adds it
back), (b) drop `FERRITE_MU_R`, or (c) open up `FERRITE_AIR_GAP_MM`.

**Picking a real part:** Fair-Rite 67/68, Ferroxcube 4F1, TDK HF70 — all
NiZn families intended for ~100 MHz – 1 GHz. Once you choose, replace the
four material constants above with that part's 400 MHz datasheet values.

**Realistic k expectation:** with the default geometry, the analytic
chain is 0.021 (no ferrite) → ~0.041 (with ferrite, image method). HFSS
typically lands ~1.5–2× higher than the on-axis baseline because it
captures fringe flux through the secondary's finite loop area, so a
HFSS-reported k of 0.08–0.12 with ferrite is plausible. Reaching 0.25
still needs additional levers (larger primary, smaller gap, or a shaped
ferrite cup rather than a flat slab). If 0.25 turns out to be infeasible,
the figure-of-merit `k · √(Q₁ · Q₂)` matters more than k alone for link
efficiency — keep Q up by widening traces (R drops) once L is on target.

## Frequency-domain caveats

- λ_air at 400 MHz ≈ 75 cm; both coils are ≪ λ → lumped model still valid.
- Self-resonance of an 80 nH coil with 1 pF of parasitic C is ≈ 560 MHz,
  only ~30 % above operating frequency. Check `ImZ11` / `ImZ22` stay
  positive at 400 MHz in the swept report.
- δ_Cu at 400 MHz ≈ 3.3 µm, so any copper thicker than ~10 µm gives no
  further R reduction. The default 35 µm (1 oz Cu) is chosen for
  manufacturability, not loss.

## Open-region margin

`PAD_MM = 30` (≈ λ/25). HFSS' radiation boundary tolerates λ/8 or smaller
comfortably when the radiator is electrically small. If you start seeing
reflection artefacts in the swept reports, bump this up to 50–80 mm.
