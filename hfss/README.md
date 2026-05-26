# HFSS scripts — WPT coil design

PyAEDT scripts that build the 3-D models for the wireless-power-transfer (WPT)
coil pair in Ansys HFSS. Stage-2 follow-up to the Keysight ADS circuit
simulations.

## Files

| File                          | What it does                                                                 |
| ----------------------------- | ---------------------------------------------------------------------------- |
| `design_400MHz_coils.py`      | Builds primary + secondary square planar spirals, ports, boundary, reports. |

## Quick start

```powershell
# 1. install PyAEDT (uses the bundled CPython that ships with AEDT, or system Python)
py -m pip install -U ansys-aedt-core

# 2. (optional) print analytic L / R / k estimates without launching HFSS
py design_400MHz_coils.py --analytic-only

# 3. build the model (opens AEDT, leaves it open for inspection)
py design_400MHz_coils.py

# 4. build + run the adaptive solve and frequency sweep
py design_400MHz_coils.py --solve
```

The default AEDT version is `2025.2` (Student v252). Pass `--version 2024.2`
or similar if you have a different release installed.

## Design targets (400 MHz)

|              | Primary  | Secondary |
| ------------ | -------- | --------- |
| L            | 120 nH   | 80 nH     |
| R @ 400 MHz  | 2.85 Ω   | 2 Ω       |
| Outer size   | (free)   | ≤ 10 mm   |
| Gap          | 11 mm (fixed) |     |
| k            | ~0.25 (stretch) |    |
| Conductor    | copper, 35 µm (1 oz Cu) |  |

## What the script does

1. Sizes both coils with the modified-Wheeler formula and the skin-depth
   surface-resistance model — prints estimates so you can sanity-check
   before the (slow) HFSS solve.
2. Launches AEDT and creates a parameterised HFSS design. Every coil
   dimension lives as a design variable (`$d_out_pri`, `$n_pri`, `$w_pri`,
   …) so you can sweep them from inside Optimetrics without touching this
   script.
3. Draws each coil as a copper square planar spiral (rectangular
   cross-section polyline). Brings the inner end out through a copper
   *bridge* 0.5 mm above the spiral so both ends sit on the same plane.
4. Drops a lumped circuit port across the 0.2 mm gap between the two pads
   of each coil — one port per coil. Reference impedance is 50 Ω
   (renormalised).
5. Wraps the assembly in an air region with a radiation boundary
   (`hfss.create_open_region`, ~30 mm margin → ≈ λ/25 at 400 MHz, fine
   with a rad boundary).
6. Defines an adaptive solve at 400 MHz (20 passes, ΔS = 0.01) and an
   interpolating sweep 50–800 MHz.
7. Adds **output variables** that compute the quantities you actually
   care about from the open-circuit Z-matrix:

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

   These are because the network's Z-matrix is open-circuit by definition
   (Z[i,j] ≡ V_i / I_j with all other ports' I = 0), so `Z(P,P)` is the
   primary impedance with the secondary open — which is the right thing to
   call `R_internal` and use for `Q_unloaded`.
8. Creates two reports: `Coil parameters vs frequency` (helps spot SRF /
   loss-vs-frequency behaviour) and `Coil parameters @ 400 MHz` (a data
   table with the single design point).

## Tuning guide

| Observed (HFSS) | What to change |
| --------------- | -------------- |
| L too high      | shrink `d_out`, drop a turn, or widen `s` (smaller fill ratio) |
| L too low       | grow `d_out` or add a turn |
| R too high      | widen the trace `w` (R ∝ 1/w at fixed length) |
| R too low       | narrow `w`, or shrink Cu thickness `t` (skin already dominates at 400 MHz so `t` past ~10·δ ≈ 35 µm has little effect) |
| k too low       | enlarge the primary (its diameter sets flux capture at 11 mm gap), or add a back-side ferrite to the primary |
| Im(Z₁₁) < 0 at 400 MHz | you are above self-resonance — increase `s` to drop parasitic C between turns |

The k = 0.25 target is the optimistic stretch goal and, with the L₁=120 nH /
L₂=80 nH constraints, geometrically very hard at an 11 mm gap. The on-axis
elliptic-integral estimate the script prints for the default geometry is
~0.02, and even sweeping the primary outer dimension up to ~40–50 mm (with a
single turn, to stay at L₁=120 nH) tops out around k ≈ 0.08 by the same
analytic. HFSS will produce a higher number than the on-axis estimate because
fringe field captured by the secondary's loop area adds to M, but reaching
0.25 in air-core form is unlikely without one of:

- relaxing L₁ (a smaller L₁ allows a larger primary at higher k for the same
  Mω product),
- a ferrite flux concentrator on the back face of the primary (k can multiply
  ~2–3×), or
- a smaller gap (k goes roughly as 1 / (R² + z²)^{3/2} on-axis).

If 0.25 turns out to be infeasible, the figure-of-merit `k · √(Q₁ · Q₂)`
matters more than k alone for link efficiency — keep Q up by widening traces
(R drops) once L is on target.

## Frequency-domain caveats

- λ_air at 400 MHz ≈ 75 cm; both coils are ≪ λ → lumped model still valid.
- Self-resonance of an 80 nH coil with 1 pF of parasitic C is ≈ 560 MHz, only
  ~30 % above operating frequency. Check `ImZ11` / `ImZ22` stay positive at
  400 MHz in the swept report.
- δ_Cu at 400 MHz ≈ 3.3 µm, so any copper thicker than ~10 µm gives no
  further R reduction. The default 35 µm (1 oz Cu) is chosen for
  manufacturability, not loss.

## Open-region margin

`RAD_MARGIN_MM = 30` (≈ λ/25). HFSS' radiation boundary tolerates λ/8 or
smaller comfortably when the radiator is electrically small. If you start
seeing reflection artefacts in the swept reports, bump this up to 50–80 mm.
