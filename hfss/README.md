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
| k too low       | enable `FERRITE` (see below), or enlarge the primary's `d_out` |
| k boost adds too much R₁ | drop ferrite `mu_r` or `magnetic_loss_tangent`, or add air gap |
| Im(Z₁₁) < 0 at 400 MHz | you are above self-resonance — increase `s` to drop parasitic C between turns |

## Ferrite back-concentrator

The script places a parameterised square ferrite slab on the back of the primary
(opposite the secondary). It acts as a magnetic mirror — flux that would otherwise
leak away from the secondary is reflected back through the primary plane.
Top-of-file params (`FERRITE = FerriteSlab(...)`):

| Param | Default | What it controls |
| ----- | ------- | ---------------- |
| `enabled` | `True` | turn the slab on/off without deleting anything |
| `lateral_size_mm` | `25.0` | square slab side; ~2 × primary `d_out` is a good starting point |
| `thickness_mm` | `1.0` | z extent; at 400 MHz ferrite skin depth is metres, so 1 mm is plenty |
| `air_gap_mm` | `0.10` | gap between slab top and primary bottom (smaller → tighter coupling) |
| `mu_r` | `30.0` | relative permeability (real part) at 400 MHz |
| `magnetic_loss_tangent` | `0.10` | tan δ_μ — the dominant loss term, contributes to R₁ |
| `epsilon_r` | `12.0` | dielectric constant of the ferrite |
| `dielectric_loss_tangent` | `0.001` | usually small for ferrites |
| `bulk_conductivity_S_per_m` | `0.01` | NiZn ferrites are essentially insulators |

**Boost rule of thumb (image-current method):**
`M_with / M_without ≈ 1 + (μ_r − 1) / (μ_r + 1)`. For μ_r = 30 this is ~1.94×; for
μ_r = 10, ~1.82×. The `--analytic-only` mode prints both numbers so you can compare.

**Loss tradeoff:** the ferrite's tan δ_μ adds to R₁_internal (because the primary's
flux now passes through a lossy medium on its return path). At 400 MHz typical NiZn
ferrites sit at tan δ_μ ≈ 0.05–0.3. If HFSS reports R₁ much higher than the 2.85 Ω
target after you enable the slab, the levers are: (a) widen the primary trace `w`
(takes R₁ back down before the ferrite adds it back), (b) drop `mu_r`, or
(c) open up `air_gap_mm` to reduce coupling to the lossy material.

**Picking a real part:** Fair-Rite 67/68, Ferroxcube 4F1, TDK HF70 — all NiZn
families intended for ~100 MHz – 1 GHz. Once you choose, replace the four material
constants above with that part's 400 MHz datasheet values.

**Realistic k expectation:** with the default geometry the analytic chain is
0.021 (no ferrite) → ~0.041 (with ferrite). HFSS typically lands ~1.5–2× higher
than the on-axis baseline because it captures fringe flux through the secondary's
finite loop area, so a HFSS-reported k of 0.08–0.12 with ferrite is plausible.
Reaching 0.25 still needs additional levers (larger primary, smaller gap, or a
shaped ferrite cup rather than a flat slab). If 0.25 turns out to be infeasible,
the figure-of-merit `k · √(Q₁ · Q₂)` matters more than k alone for link
efficiency — keep Q up by widening traces (R drops) once L is on target.

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
