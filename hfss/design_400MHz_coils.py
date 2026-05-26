#!/usr/bin/env python3
"""
WPT Coil Pair Designer for Ansys HFSS (PyAEDT)
==============================================

Builds parameterized 3D models of a primary and secondary planar-square-spiral
coil pair for an inductive wireless-power-transfer link operating at 400 MHz.
Drops in two lumped circuit ports (one per coil) so the user can read off the
open-circuit Z-matrix at 400 MHz and compute L, R_internal, k, and Q_unloaded
for both coils.

Design targets (handed off from the Keysight ADS stage)
-------------------------------------------------------
                  Primary        Secondary
  Inductance      120 nH         80 nH
  Series R @400M  2.85 Ohm       2 Ohm
  Coupling k                   ~0.25 (stretch goal)
  Vertical gap                 = 11 mm    (fixed)
  Secondary size              <= 10 mm x 10 mm
  Conductor                    copper, 35 um (1 oz Cu) default
  Frequency                    400 MHz

Initial geometry in PRIMARY / SECONDARY below was sized using:
  * Modified-Wheeler L for square planar spirals
    (Mohan, Hershenson, Boyd, Lee 1999, IEEE JSSC)
  * Skin-depth surface-resistance with proximity multiplier
    (delta_Cu @ 400 MHz approx 3.3 um)
  * Coaxial elliptic-integral mutual-inductance for k estimate
    (Grover 1946)
Run ``--analytic-only`` to print these estimates without launching HFSS.

Realistic k expectation
-----------------------
With L1=120 nH, L2=80 nH and an 11 mm gap, k ~ 0.25 in pure air-core form is
geometrically tight; the on-axis analytic baseline for the default geometry
is ~0.02. To boost k the script now bakes in a back-side ferrite slab on
the primary (toggle via FERRITE.enabled, tweak FERRITE.* params at the top).
The image-method estimate gives roughly a ~1.9x M boost for the defaults
(mu_r = 30, ~zero gap), so analytic k climbs to ~0.04. HFSS will give the
real number including fringe coupling and ferrite losses.

Other levers, if still short:
   (1) a larger primary diameter (relax the primary's footprint),
   (2) a more aggressive ferrite (higher mu_r) -- watch the loss tangent,
   (3) a reduced gap.
All coil dimensions plus all ferrite parameters are HFSS design variables so
they can be swept inside Optimetrics without re-running this script.

400 MHz parasitic notes
-----------------------
Lambda_air ~ 75 cm, so a coil <= 25 mm is << lambda -- the lumped model is
still valid. But the self-resonance of an 80 nH coil with even 1 pF of
parasitic shunt C lands at ~560 MHz, only ~30% above operating frequency.
Keep inter-turn spacing reasonable, and verify Im(Z11) > 0 (inductive) at
400 MHz in the reports the script creates.

Usage
-----
    py -m pip install -U ansys-aedt-core
    py design_400MHz_coils.py --analytic-only    # estimates without HFSS
    py design_400MHz_coils.py                    # build only
    py design_400MHz_coils.py --solve            # build + analyze
    py design_400MHz_coils.py --help             # all flags
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# PyAEDT is imported lazily inside main(); --analytic-only doesn't need it.
Hfss = None  # populated by _lazy_import_pyaedt()


def _lazy_import_pyaedt():
    """Import PyAEDT only when an HFSS-touching code path actually runs."""
    global Hfss
    if Hfss is not None:
        return Hfss
    try:
        from ansys.aedt.core import Hfss as _Hfss
    except ImportError:
        try:
            from pyaedt import Hfss as _Hfss
        except ImportError as exc:
            raise SystemExit(
                "PyAEDT is not installed. Run: py -m pip install -U ansys-aedt-core"
            ) from exc
    Hfss = _Hfss
    return Hfss


# ============================================================================
# Top-level design parameters -- edit these to tune the model
# ============================================================================

FREQUENCY_HZ = 400e6
SEPARATION_MM = 11.0          # fixed by the implant geometry

PROJECT_NAME = "WPT_400MHz"
DESIGN_NAME = "CoilPair"
AEDT_VERSION = "2025.2"       # ANSYS Student v252 == Electronics Desktop 2025 R2

COND_MATERIAL = "copper"
RAD_MARGIN_MM = 30.0          # ~lambda/25 at 400 MHz -- fine with rad boundary
ADAPTIVE_PASSES = 20
DELTA_S = 0.01
PORT_GAP_MM = 0.20            # gap across the lumped-port sheet


@dataclass
class CoilParams:
    """Geometry of one square planar spiral coil."""
    name: str
    d_out_mm: float            # outer side length of the square spiral
    n_turns: int
    trace_w_mm: float
    trace_s_mm: float          # inter-turn gap
    trace_t_mm: float = 0.035  # copper thickness (1 oz Cu default)
    z_base_mm: float = 0.0     # bottom-of-trace z coordinate
    bridge_height_mm: float = 0.5  # bridge above-spiral clearance (in air)
    lead_length_mm: float = 1.5    # lead extending outward from outer corner

    # Filled in during build:
    outer_terminal_xy: tuple = field(default_factory=tuple)
    inner_terminal_xy: tuple = field(default_factory=tuple)


PRIMARY = CoilParams(
    name="Primary",
    d_out_mm=13.0,
    n_turns=2,
    trace_w_mm=0.10,
    trace_s_mm=0.40,
    z_base_mm=0.0,
)

SECONDARY = CoilParams(
    name="Secondary",
    d_out_mm=8.5,
    n_turns=2,
    trace_w_mm=0.10,
    trace_s_mm=0.20,
    z_base_mm=SEPARATION_MM,
)


@dataclass
class FerriteSlab:
    """Optional ferrite flux-concentrator placed BEHIND the primary coil.

    The slab acts as a magnetic mirror: flux that would otherwise leak away
    from the secondary is returned through the primary, roughly doubling M
    (and so k) in the ideal limit (mu_r -> inf, zero air gap). For finite
    mu_r the image-current method gives a boost factor of
        1 + (mu_r - 1) / (mu_r + 1)
    Expect ~1.8 - 1.9x with the defaults below.

    Tradeoff: ferrite losses at 400 MHz add to the primary's R_internal
    (NiZn tan(delta_mu) ~ 0.05 - 0.3 at this band). Bigger mu_r pushes k
    up but also widens the loss penalty -- watch R1 after enabling.

    Defaults below are representative of an HF-rated NiZn ferrite
    (Fair-Rite 67/68 family, Ferroxcube 4F1) near 400 MHz. Swap in your
    datasheet values once a part is chosen.
    """
    enabled: bool = True

    # Geometry (square slab, centred on the origin in x and y)
    lateral_size_mm: float = 25.0   # x and y extent; >= ~2 * primary d_out
    thickness_mm: float = 1.0       # z extent (RF skin depth in ferrite is
                                    # metres at 400 MHz, so 1 mm is plenty)
    air_gap_mm: float = 0.10        # gap between slab TOP and primary BOTTOM

    # Material (custom material registered in the HFSS material library)
    material_name: str = "HF_Ferrite_400MHz"
    mu_r: float = 30.0              # relative permeability (real part)
    magnetic_loss_tangent: float = 0.10
    epsilon_r: float = 12.0
    dielectric_loss_tangent: float = 0.001
    bulk_conductivity_S_per_m: float = 0.01    # NiZn ferrite is ~ MOhm cm


# Top-level tweakable: edit fields and re-run.
FERRITE = FerriteSlab()


# ============================================================================
# Analytical pre-sizing (sanity-check vs. HFSS)
# ============================================================================

MU0 = 4e-7 * math.pi
RHO_CU = 1.68e-8
SIGMA_CU = 5.96e7


def wheeler_L_square(d_out_mm: float, n: int, w_mm: float, s_mm: float) -> float:
    """Modified-Wheeler L for a square planar spiral (Henries).

    K1=2.34, K2=2.75 are the Mohan/Boahen coefficients for square geometry.
    """
    d_out = d_out_mm * 1e-3
    w = w_mm * 1e-3
    s = s_mm * 1e-3
    d_in = d_out - 2 * (n * w + (n - 1) * s)
    if d_in <= 0:
        raise ValueError(
            f"Spiral collapses to a point (n={n}, w={w_mm}, s={s_mm}, d_out={d_out_mm})."
        )
    d_avg = 0.5 * (d_out + d_in)
    rho = (d_out - d_in) / (d_out + d_in)
    return 2.34 * MU0 * n * n * d_avg / (1.0 + 2.75 * rho)


def skin_depth(f_hz: float, mu_r: float = 1.0, sigma: float = SIGMA_CU) -> float:
    return math.sqrt(2.0 / (2.0 * math.pi * f_hz * mu_r * MU0 * sigma))


def surface_R_ac(length_m: float, w_mm: float, t_mm: float,
                 f_hz: float, prox_factor: float = 1.8) -> float:
    """Skin-effect R of a rectangular conductor with a proximity multiplier."""
    delta = skin_depth(f_hz)
    w = w_mm * 1e-3
    t = t_mm * 1e-3
    R_dc = RHO_CU * length_m / (w * t)
    perim_skin = 2.0 * (w + t) * delta
    R_skin = RHO_CU * length_m / perim_skin
    return prox_factor * max(R_dc, R_skin)


def square_spiral_centerline_length(d_out_mm: float, n: int,
                                    w_mm: float, s_mm: float) -> float:
    """Approximate centre-line length of the spiral (metres)."""
    p = (w_mm + s_mm) * 1e-3
    a = d_out_mm * 1e-3 / 2.0
    half_w = w_mm * 1e-3 / 2.0
    L = 0.0
    for k in range(n):
        r_k = a - half_w - k * p
        # Right (up), top (left), left (down): each leg is 2*r_k long
        L += 6.0 * r_k
        # Bottom leg: either to next step-in, or to centre on the last turn
        if k < n - 1:
            r_next = a - half_w - (k + 1) * p
            L += (r_k + r_next)
        else:
            L += r_k  # last turn terminates at (0, -r_k)
    return L


def coaxial_mutual_M(R1_m: float, R2_m: float, z_m: float) -> float:
    """Mutual inductance of two coaxial single-turn circular loops (Grover)."""
    # k_modulus squared
    m = 4.0 * R1_m * R2_m / ((R1_m + R2_m) ** 2 + z_m ** 2)
    k = math.sqrt(m)
    # Numerical elliptic K(m), E(m) via the AGM (no scipy dependency)
    K_m, E_m = _elliptic_K_E(m)
    return MU0 * math.sqrt(R1_m * R2_m) * ((2.0 / k - k) * K_m - (2.0 / k) * E_m)


def _elliptic_K_E(m: float, tol: float = 1e-12) -> tuple[float, float]:
    """Complete elliptic integrals of the 1st and 2nd kind via AGM."""
    if m >= 1.0:
        return float("inf"), 1.0
    a, b = 1.0, math.sqrt(1.0 - m)
    c = math.sqrt(m)
    sum_c2 = 0.0
    n = 0
    while abs(c) > tol:
        a_next = 0.5 * (a + b)
        b_next = math.sqrt(a * b)
        c = 0.5 * (a - b)
        a, b = a_next, b_next
        n += 1
        sum_c2 += (2 ** n) * c * c
    K_m = math.pi / (2.0 * a)
    E_m = K_m * (1.0 - 0.5 * (m + sum_c2))
    return K_m, E_m


def estimate_targets(coil: CoilParams) -> dict:
    L_H = wheeler_L_square(coil.d_out_mm, coil.n_turns, coil.trace_w_mm, coil.trace_s_mm)
    L_total = square_spiral_centerline_length(
        coil.d_out_mm, coil.n_turns, coil.trace_w_mm, coil.trace_s_mm
    )
    R = surface_R_ac(L_total, coil.trace_w_mm, coil.trace_t_mm, FREQUENCY_HZ)
    return {
        "L_nH_analytic": L_H * 1e9,
        "R_ohm_analytic": R,
        "wire_length_mm": L_total * 1e3,
    }


def estimate_k(primary: CoilParams, secondary: CoilParams,
               separation_mm: float) -> float:
    """Crude on-axis k estimate using d_avg as the equivalent radius."""
    p = (primary.trace_w_mm + primary.trace_s_mm)
    half_w = primary.trace_w_mm / 2.0
    pri_d_avg = 2 * (primary.d_out_mm / 2 - half_w - 0.5 * (primary.n_turns - 1) * p)
    p2 = (secondary.trace_w_mm + secondary.trace_s_mm)
    half_w2 = secondary.trace_w_mm / 2.0
    sec_d_avg = 2 * (secondary.d_out_mm / 2 - half_w2 - 0.5 * (secondary.n_turns - 1) * p2)
    R1 = pri_d_avg / 2 * 1e-3
    R2 = sec_d_avg / 2 * 1e-3
    M_loop = coaxial_mutual_M(R1, R2, separation_mm * 1e-3)
    M_total = primary.n_turns * secondary.n_turns * M_loop
    L1 = wheeler_L_square(primary.d_out_mm, primary.n_turns,
                          primary.trace_w_mm, primary.trace_s_mm)
    L2 = wheeler_L_square(secondary.d_out_mm, secondary.n_turns,
                          secondary.trace_w_mm, secondary.trace_s_mm)
    return M_total / math.sqrt(L1 * L2)


def ferrite_image_boost(slab: FerriteSlab) -> float:
    """Image-current k-boost factor for a back-side ferrite slab.

    The 'mirror' image of every primary-current element has strength
    (mu_r - 1) / (mu_r + 1) (the magnetic reflection coefficient at a
    half-infinite slab). M gets contributions from both the real coil and
    its image, so total M_with / M_without = 1 + (mu_r-1)/(mu_r+1).

    The estimate ignores: (a) finite slab thickness, (b) finite slab
    lateral size, (c) air-gap distance, (d) ferrite losses. HFSS will
    capture all of these -- this number is only for setting expectations.
    """
    if not slab.enabled or slab.mu_r <= 1.0:
        return 1.0
    image_strength = (slab.mu_r - 1.0) / (slab.mu_r + 1.0)
    return 1.0 + image_strength


def print_analytic_estimates() -> None:
    print("-" * 72)
    print("Analytic pre-build estimates (Wheeler L, surface-R, on-axis M)")
    print("-" * 72)
    delta = skin_depth(FREQUENCY_HZ) * 1e6
    print(f"  skin depth in copper @ {FREQUENCY_HZ/1e6:.0f} MHz = {delta:.2f} um")
    print()
    for coil, target_L, target_R in (
        (PRIMARY,   120.0, 2.85),
        (SECONDARY,  80.0, 2.00),
    ):
        est = estimate_targets(coil)
        print(f"  {coil.name:9s}  d_out={coil.d_out_mm:5.2f}mm  n={coil.n_turns}  "
              f"w={coil.trace_w_mm:.3f}mm  s={coil.trace_s_mm:.3f}mm  "
              f"t={coil.trace_t_mm*1000:.1f}um")
        print(f"             L ~ {est['L_nH_analytic']:6.2f} nH  (target {target_L:>5.1f})    "
              f"R ~ {est['R_ohm_analytic']:5.2f} Ohm  (target {target_R:.2f})")
        print(f"             centre-line wire length ~ {est['wire_length_mm']:5.1f} mm")
    k_est = estimate_k(PRIMARY, SECONDARY, SEPARATION_MM)
    boost = ferrite_image_boost(FERRITE)
    print()
    print(f"  on-axis coupling estimate at z={SEPARATION_MM} mm:  k ~ {k_est:.3f}  (no ferrite)")
    if FERRITE.enabled:
        print(f"  ferrite slab enabled (mu_r={FERRITE.mu_r}, "
              f"tan_delta_mu={FERRITE.magnetic_loss_tangent}, "
              f"t={FERRITE.thickness_mm} mm, gap={FERRITE.air_gap_mm} mm)")
        print(f"     image-method boost ~ {boost:.2f}x  =>  k ~ {k_est*boost:.3f}")
        print(f"     (HFSS will give the real number including loss / finite-slab effects)")
    else:
        print(f"  ferrite slab disabled  (set FERRITE.enabled = True to engage)")
    print("-" * 72)


# ============================================================================
# Geometry generation - square Archimedean spiral
# ============================================================================

def square_spiral_vertices(coil: CoilParams) -> list[list[float]]:
    """Centre-line polyline points of a CCW square Archimedean spiral.

    Path:
        outer lead (+x stub) -> right-side up -> top left -> left down ->
        bottom right (step inward) -> next turn ... -> inner termination ->
        inner lead (+y stub to centre).
    """
    a = coil.d_out_mm / 2.0
    p = coil.trace_w_mm + coil.trace_s_mm
    half_w = coil.trace_w_mm / 2.0
    z = coil.z_base_mm + coil.trace_t_mm / 2.0   # centroid z for polyline

    pts: list[list[float]] = []

    outer_x = a - half_w
    outer_y = -(a - half_w)
    pts.append([outer_x + coil.lead_length_mm, outer_y, z])
    pts.append([outer_x, outer_y, z])

    for k in range(coil.n_turns):
        r_k = a - half_w - k * p
        r_next = a - half_w - (k + 1) * p

        # Right (up), top (left), left (down)
        pts.append([r_k, r_k, z])
        pts.append([-r_k, r_k, z])
        pts.append([-r_k, -r_k, z])
        # Bottom (right) -- step inward to next turn, or terminate at centre
        if k < coil.n_turns - 1:
            pts.append([r_next, -r_k, z])
        else:
            pts.append([0.0, -r_k, z])

    inner_end_x, inner_end_y = pts[-1][0], pts[-1][1]
    pts.append([inner_end_x, inner_end_y + coil.lead_length_mm / 2.0, z])

    coil.outer_terminal_xy = (outer_x + coil.lead_length_mm, outer_y)
    coil.inner_terminal_xy = (pts[-1][0], pts[-1][1])
    return pts


# ============================================================================
# HFSS construction
# ============================================================================

def _set_design_variables(hfss: Hfss, coil: CoilParams, prefix: str) -> None:
    """Register coil geometry as named HFSS design variables (for Optimetrics)."""
    hfss[f"$d_out_{prefix}"] = f"{coil.d_out_mm}mm"
    hfss[f"$n_{prefix}"]     = coil.n_turns
    hfss[f"$w_{prefix}"]     = f"{coil.trace_w_mm}mm"
    hfss[f"$s_{prefix}"]     = f"{coil.trace_s_mm}mm"
    hfss[f"$t_{prefix}"]     = f"{coil.trace_t_mm}mm"
    hfss[f"$z_{prefix}"]     = f"{coil.z_base_mm}mm"
    hfss[f"$br_{prefix}"]    = f"{coil.bridge_height_mm}mm"


def build_one_coil(hfss: Hfss, coil: CoilParams, prefix: str) -> dict:
    """Build a complete coil (spiral + bridge + via stubs) and lay out the port pads."""
    _set_design_variables(hfss, coil, prefix)

    # --- 1. Spiral as rectangular-cross-section polyline ---
    pts = square_spiral_vertices(coil)
    spiral_name = f"{coil.name}_spiral"
    hfss.modeler.create_polyline(
        points=pts,
        name=spiral_name,
        material=COND_MATERIAL,
        xsection_type="Rectangle",
        xsection_width=f"{coil.trace_w_mm}mm",
        xsection_height=f"{coil.trace_t_mm}mm",
        xsection_orient="Z",
    )

    # --- 2. Inner-end bridge (overpass to bring the inner end outside) ---
    inner_x, inner_y = coil.inner_terminal_xy
    bridge_z_centre = coil.z_base_mm + coil.bridge_height_mm + coil.trace_t_mm / 2.0

    # 2a. Via UP from spiral inner-lead tip
    via_in_name = f"{coil.name}_via_in"
    hfss.modeler.create_box(
        origin=[inner_x - coil.trace_w_mm / 2.0,
                inner_y - coil.trace_w_mm / 2.0,
                coil.z_base_mm + coil.trace_t_mm],
        sizes=[coil.trace_w_mm, coil.trace_w_mm,
               coil.bridge_height_mm - coil.trace_t_mm / 2.0],
        name=via_in_name,
        material=COND_MATERIAL,
    )

    # 2b. Bridge wire over the spiral, ending just above the outer lead's pad
    bridge_end_x = coil.outer_terminal_xy[0]
    bridge_end_y = coil.outer_terminal_xy[1] + (PORT_GAP_MM + coil.trace_w_mm)
    bridge_pts = [
        [inner_x, inner_y, bridge_z_centre],
        [bridge_end_x, inner_y, bridge_z_centre],
        [bridge_end_x, bridge_end_y, bridge_z_centre],
    ]
    bridge_name = f"{coil.name}_bridge"
    hfss.modeler.create_polyline(
        points=bridge_pts,
        name=bridge_name,
        material=COND_MATERIAL,
        xsection_type="Rectangle",
        xsection_width=f"{coil.trace_w_mm}mm",
        xsection_height=f"{coil.trace_t_mm}mm",
        xsection_orient="Z",
    )

    # 2c. Via DOWN at bridge end
    via_out_name = f"{coil.name}_via_out"
    hfss.modeler.create_box(
        origin=[bridge_end_x - coil.trace_w_mm / 2.0,
                bridge_end_y - coil.trace_w_mm / 2.0,
                coil.z_base_mm + coil.trace_t_mm],
        sizes=[coil.trace_w_mm, coil.trace_w_mm,
               coil.bridge_height_mm - coil.trace_t_mm / 2.0],
        name=via_out_name,
        material=COND_MATERIAL,
    )

    # 2d. Inner-end pad at z_base (the bridge's landing pad)
    inner_pad_name = f"{coil.name}_pad_inner"
    pad_w = coil.trace_w_mm * 2.0
    hfss.modeler.create_box(
        origin=[bridge_end_x - pad_w / 2.0,
                bridge_end_y - coil.trace_w_mm / 2.0,
                coil.z_base_mm],
        sizes=[pad_w, coil.trace_w_mm, coil.trace_t_mm],
        name=inner_pad_name,
        material=COND_MATERIAL,
    )

    # 2e. Outer-end pad at z_base (sits on the end of the outer lead)
    outer_pad_name = f"{coil.name}_pad_outer"
    hfss.modeler.create_box(
        origin=[bridge_end_x - pad_w / 2.0,
                coil.outer_terminal_xy[1] - coil.trace_w_mm / 2.0,
                coil.z_base_mm],
        sizes=[pad_w, coil.trace_w_mm, coil.trace_t_mm],
        name=outer_pad_name,
        material=COND_MATERIAL,
    )

    # --- 3. Lumped-port sheet bridging the gap between the two pads ---
    sheet_y0 = coil.outer_terminal_xy[1] + coil.trace_w_mm / 2.0
    sheet_y1 = bridge_end_y - coil.trace_w_mm / 2.0
    sheet_x0 = bridge_end_x - pad_w / 2.0
    sheet_x1 = bridge_end_x + pad_w / 2.0
    port_sheet_name = f"{coil.name}_port_sheet"
    hfss.modeler.create_rectangle(
        orientation="Z",
        origin=[sheet_x0, sheet_y0, coil.z_base_mm + coil.trace_t_mm / 2.0],
        sizes=[sheet_x1 - sheet_x0, sheet_y1 - sheet_y0],
        name=port_sheet_name,
    )

    return {
        "spiral": spiral_name,
        "bridge": bridge_name,
        "via_in": via_in_name,
        "via_out": via_out_name,
        "pad_inner": inner_pad_name,
        "pad_outer": outer_pad_name,
        "port_sheet": port_sheet_name,
        "port_int_start": [
            (sheet_x0 + sheet_x1) / 2.0, sheet_y0,
            coil.z_base_mm + coil.trace_t_mm / 2.0,
        ],
        "port_int_end": [
            (sheet_x0 + sheet_x1) / 2.0, sheet_y1,
            coil.z_base_mm + coil.trace_t_mm / 2.0,
        ],
    }


def assign_lumped_port(hfss: Hfss, port_info: dict, port_name: str,
                       impedance: float = 50.0) -> None:
    hfss.lumped_port(
        assignment=port_info["port_sheet"],
        integration_line=[port_info["port_int_start"], port_info["port_int_end"]],
        impedance=impedance,
        name=port_name,
        renormalize=True,
    )


def add_ferrite_material(hfss: Hfss, slab: FerriteSlab) -> None:
    """Register the ferrite material in the project's material library.

    Tries a few attribute names because PyAEDT has shifted these between
    versions (e.g. magnetic_loss_tangent vs loss_tangent_mu).
    """
    existing = getattr(hfss.materials, "material_keys", None) or set(hfss.materials.mat_names_aedt)
    if slab.material_name in existing:
        return

    mat = hfss.materials.add_material(slab.material_name)

    def _try_set(attr_name: str, value):
        try:
            setattr(mat, attr_name, value)
            return True
        except Exception:
            return False

    _try_set("permeability", slab.mu_r)
    _try_set("permittivity", slab.epsilon_r)
    _try_set("conductivity", slab.bulk_conductivity_S_per_m)

    # Magnetic loss tangent: attribute name has moved around. Try them all.
    for cand in ("magnetic_loss_tangent", "loss_tangent_mu",
                 "magnetic_loss_tan", "mu_loss_tangent"):
        if _try_set(cand, slab.magnetic_loss_tangent):
            break
    for cand in ("dielectric_loss_tangent", "loss_tangent",
                 "dielectric_loss_tan"):
        if _try_set(cand, slab.dielectric_loss_tangent):
            break


def build_ferrite_slab(hfss: Hfss, slab: FerriteSlab, primary: CoilParams) -> str:
    """Place a ferrite slab BEHIND the primary coil (in -z half-space).

    Slab is centred on (0, 0) in x-y and sits below the primary's z_base by
    `air_gap_mm`. Returns the new object's name.
    """
    add_ferrite_material(hfss, slab)
    # Register slab geometry as design vars too (for Optimetrics)
    hfss["$ferrite_size"] = f"{slab.lateral_size_mm}mm"
    hfss["$ferrite_thick"] = f"{slab.thickness_mm}mm"
    hfss["$ferrite_gap"] = f"{slab.air_gap_mm}mm"

    z_top = primary.z_base_mm - slab.air_gap_mm
    z_bottom = z_top - slab.thickness_mm
    half = slab.lateral_size_mm / 2.0
    name = "Primary_FerriteSlab"
    hfss.modeler.create_box(
        origin=[-half, -half, z_bottom],
        sizes=[slab.lateral_size_mm, slab.lateral_size_mm, slab.thickness_mm],
        name=name,
        material=slab.material_name,
    )
    return name


def add_open_region(hfss: Hfss) -> None:
    """Wrap the assembly in an air box with a radiation boundary."""
    hfss.create_open_region(
        frequency=f"{FREQUENCY_HZ/1e9}GHz",
        boundary="Radiation",
        apply_infinite_ground=False,
    )


# ============================================================================
# Analysis setup + post-processing
# ============================================================================

def setup_analysis(hfss: Hfss) -> Any:
    """Adaptive solve at 400 MHz plus a wide interpolating sweep."""
    setup = hfss.create_setup(
        name="Setup_400MHz",
        Frequency=f"{FREQUENCY_HZ/1e9}GHz",
        MaximumPasses=ADAPTIVE_PASSES,
        MinimumPasses=2,
        MinimumConvergedPasses=2,
        MaxDeltaS=DELTA_S,
    )
    setup.create_frequency_sweep(
        unit="MHz",
        name="Sweep_50_to_800",
        start_frequency=50,
        stop_frequency=800,
        num_of_freq_points=151,
        sweep_type="Interpolating",
    )
    return setup


def create_output_variables_and_reports(hfss: Hfss) -> None:
    """Add output variables for L, R, M, k, Q derived from the Z-matrix.

    The Z-parameters that HFSS reports are by definition open-circuit
    (Z[i,j] = V_i / I_j with all other ports' I = 0). Hence the diagonal
    entries give the self-impedance with the opposite coil open -- exactly
    what we need for L, R_internal, and unloaded Q.
    """
    omega = "(2*pi*Freq)"
    expressions = {
        "L1_nH":         f"im(Z(Primary,Primary))     / {omega} * 1e9",
        "L2_nH":         f"im(Z(Secondary,Secondary)) / {omega} * 1e9",
        "M_nH":          f"im(Z(Primary,Secondary))   / {omega} * 1e9",
        "R1_ohm":        "re(Z(Primary,Primary))",
        "R2_ohm":        "re(Z(Secondary,Secondary))",
        "k_coupling":    ("im(Z(Primary,Secondary)) / "
                          "sqrt(im(Z(Primary,Primary)) * im(Z(Secondary,Secondary)))"),
        "Q1_unloaded":   "im(Z(Primary,Primary))   / re(Z(Primary,Primary))",
        "Q2_unloaded":   "im(Z(Secondary,Secondary)) / re(Z(Secondary,Secondary))",
        "ImZ11":         "im(Z(Primary,Primary))",     # > 0 means still inductive
        "ImZ22":         "im(Z(Secondary,Secondary))",
    }

    solution_for_outputs = "Setup_400MHz : LastAdaptive"
    for var_name, expr in expressions.items():
        try:
            hfss.create_output_variable(var_name, expr, solution_name=solution_for_outputs)
        except Exception as e:
            print(f"[WARN] could not create output variable {var_name}: {e}")

    try:
        hfss.post.create_report(
            expressions=list(expressions.keys()),
            setup_sweep_name="Setup_400MHz : Sweep_50_to_800",
            domain="Sweep",
            primary_sweep_variable="Freq",
            plot_name="Coil parameters vs frequency",
        )
    except Exception as e:
        print(f"[WARN] could not create swept report: {e}")

    try:
        hfss.post.create_report(
            expressions=list(expressions.keys()),
            setup_sweep_name="Setup_400MHz : LastAdaptive",
            domain="Sweep",
            primary_sweep_variable="Freq",
            plot_name="Coil parameters @ 400 MHz",
            plot_type="Data Table",
        )
    except Exception as e:
        print(f"[WARN] could not create single-point data-table report: {e}")


# ============================================================================
# Orchestration
# ============================================================================

def build_model(hfss: Hfss) -> dict:
    hfss.modeler.model_units = "mm"
    primary_info = build_one_coil(hfss, PRIMARY,   prefix="pri")
    secondary_info = build_one_coil(hfss, SECONDARY, prefix="sec")

    slab_name = None
    if FERRITE.enabled:
        slab_name = build_ferrite_slab(hfss, FERRITE, PRIMARY)

    assign_lumped_port(hfss, primary_info,   "Primary")
    assign_lumped_port(hfss, secondary_info, "Secondary")
    add_open_region(hfss)
    setup_analysis(hfss)
    create_output_variables_and_reports(hfss)
    return {
        "primary": primary_info,
        "secondary": secondary_info,
        "ferrite_slab": slab_name,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--solve", action="store_true",
                        help="Run the HFSS analysis after building the model.")
    parser.add_argument("--no-graphics", action="store_true",
                        help="Launch AEDT headless (still requires the license).")
    parser.add_argument("--project-dir", type=Path,
                        default=Path.cwd() / "hfss_projects",
                        help="Where to write the .aedt project file.")
    parser.add_argument("--version", default=AEDT_VERSION,
                        help="AEDT version, e.g. '2025.2' or '2024.2'.")
    parser.add_argument("--analytic-only", action="store_true",
                        help="Just print Wheeler / skin / M estimates and exit.")
    args = parser.parse_args(argv)

    print_analytic_estimates()
    if args.analytic_only:
        return 0

    args.project_dir.mkdir(parents=True, exist_ok=True)
    project_path = str(args.project_dir / f"{PROJECT_NAME}.aedt")

    _lazy_import_pyaedt()

    print(f"\n[HFSS] Launching AEDT {args.version} ...")
    hfss = Hfss(
        project=project_path,
        design=DESIGN_NAME,
        solution_type="Modal",
        new_desktop=True,
        non_graphical=args.no_graphics,
        version=args.version,
    )
    rc = 0
    try:
        names = build_model(hfss)
        hfss.save_project()
        print(f"[HFSS] Model built and saved to: {project_path}")
        for side in ("primary", "secondary"):
            info = names[side]
            print(f"  {side:10s}  port sheet = {info['port_sheet']}")
        if names.get("ferrite_slab"):
            print(f"  ferrite     slab box   = {names['ferrite_slab']}")

        if args.solve:
            print("[HFSS] Running adaptive solve + sweep ...")
            hfss.analyze_setup("Setup_400MHz")
            print("[HFSS] Solve complete. Open the design to see the reports.")
    except Exception:
        import traceback
        traceback.print_exc()
        rc = 1
    finally:
        hfss.release_desktop(close_projects=False, close_on_exit=False)
    return rc


if __name__ == "__main__":
    sys.exit(main())
