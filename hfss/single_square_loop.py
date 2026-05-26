#!/usr/bin/env python3
"""
Single Square Loop with Rounded Corners and a Gap -- HFSS / PyAEDT
===================================================================

Builds ONE square copper loop, centred on the origin in x-y, with rounded
inside corners (90 deg arcs at each turn) and a configurable open gap on
the right side so the loop is not electrically closed.

Geometry summary
----------------
  - Outer square side length .............. LOOP_SIDE_MM
  - Trace width (perpendicular to path) ... TRACE_WIDTH_MM
  - Copper thickness ...................... TRACE_THICK_MM
  - Inside corner fillet radius ........... CORNER_RADIUS_MM
  - Gap on the right side ................. GAP_MM   (default 1.0 mm)
  - Loop sits in the plane z = LOOP_Z_MM

The trace is centred along a polyline that goes counter-clockwise from
the top edge of the gap, all the way around the square with arc-rounded
corners, and ends at the bottom edge of the gap. The polyline is swept
with a rectangular cross-section to give the 3-D copper solid.

Optional features (toggle at the top of the file):
  ADD_PORT          place a lumped circuit port across the gap so input
                    impedance is solvable
  ADD_AIR_REGION    wrap the loop in an air box with a radiation boundary
  ADD_SOLUTION      add a 400 MHz adaptive setup + interpolating sweep
                    (matches the WPT coil-pair script's defaults)

Usage
-----
    py -m pip install -U ansys-aedt-core
    py single_square_loop.py --analytic-only   # geometry summary, no HFSS
    py single_square_loop.py                   # build in HFSS
    py single_square_loop.py --solve           # build + run analysis
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path


# ============================================================================
# Top-level parameters -- edit these and re-run
# ============================================================================

LOOP_SIDE_MM = 20.0        # outer side length of the square
TRACE_WIDTH_MM = 0.5       # trace width (perpendicular to the path)
TRACE_THICK_MM = 0.035     # copper thickness (35 um = 1 oz Cu)
CORNER_RADIUS_MM = 2.0     # centre-line corner fillet radius (must be > W/2)
GAP_MM = 1.0               # open gap, centred on y=0 on the right side
LOOP_Z_MM = 0.0            # z position of the trace (centre of thickness)

ADD_PORT = True            # place a lumped port across the gap
ADD_AIR_REGION = True      # wrap in an air box with a radiation boundary
ADD_SOLUTION = True        # add an adaptive setup + sweep
PORT_IMPEDANCE = 50.0
FREQUENCY_HZ = 400e6       # solver design frequency (also the rad-boundary freq)

COND_MATERIAL = "copper"
LOOP_NAME = "SquareLoop"
PORT_NAME = "LoopPort"
PORT_SHEET_NAME = "LoopPort_Sheet"

PROJECT_NAME = "SingleSquareLoop"
DESIGN_NAME = "Loop"
AEDT_VERSION = "2025.2"


# ============================================================================
# Lazy PyAEDT import (so --analytic-only works without an install)
# ============================================================================

Hfss = None


def _lazy_import_pyaedt():
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
# Geometry
# ============================================================================

def validate_params() -> None:
    if CORNER_RADIUS_MM <= TRACE_WIDTH_MM / 2.0:
        raise SystemExit(
            f"CORNER_RADIUS_MM ({CORNER_RADIUS_MM}) must exceed half the trace width "
            f"({TRACE_WIDTH_MM/2.0}) so the inside edge of the fillet stays > 0."
        )
    max_r = (LOOP_SIDE_MM - TRACE_WIDTH_MM) / 2.0 - GAP_MM / 2.0
    if CORNER_RADIUS_MM >= max_r:
        raise SystemExit(
            f"CORNER_RADIUS_MM ({CORNER_RADIUS_MM}) must be < {max_r:.3f} so the "
            f"arcs don't overlap the gap or each other."
        )
    if GAP_MM <= 0:
        raise SystemExit("GAP_MM must be positive (the loop must NOT close).")


def loop_path(L: float, W: float, r: float, gap: float, z: float
              ) -> tuple[list[list[float]], list[str]]:
    """Centre-line polyline of a rounded-corner square loop with a right-side gap.

    Path goes counter-clockwise (viewed from +z) starting at the TOP of the
    gap and ending at the BOTTOM of the gap. Each 90 deg corner is a 3-point
    arc; the four straight sides are line segments.

    Returns (points, segment_types) ready for ``create_polyline``.
    """
    a = L / 2.0 - W / 2.0     # centreline half-side (inset by W/2 from outer edge)
    half_gap = gap / 2.0
    r2 = r / math.sqrt(2.0)   # arc midpoint offset

    pts: list[list[float]] = [
        # Right side, going UP from the top of the gap
        [a,                    half_gap,           z],   # 0: start
        [a,                    a - r,              z],   # 1: end of right-up straight
        # Top-right corner arc (centre at (a-r, a-r))
        [a - r + r2,           a - r + r2,         z],   # 2: arc midpoint (45 deg)
        [a - r,                a,                  z],   # 3: end of TR arc
        # Top, going LEFT
        [-a + r,               a,                  z],   # 4: start of TL arc
        # Top-left corner arc (centre at (-a+r, a-r))
        [-a + r - r2,          a - r + r2,         z],   # 5: arc midpoint (135 deg)
        [-a,                   a - r,              z],   # 6: end of TL arc
        # Left side, going DOWN
        [-a,                   -a + r,             z],   # 7: start of BL arc
        # Bottom-left corner arc (centre at (-a+r, -a+r))
        [-a + r - r2,          -a + r - r2,        z],   # 8: arc midpoint (225 deg)
        [-a + r,               -a,                 z],   # 9: end of BL arc
        # Bottom, going RIGHT
        [a - r,                -a,                 z],   # 10: start of BR arc
        # Bottom-right corner arc (centre at (a-r, -a+r))
        [a - r + r2,           -a + r - r2,        z],   # 11: arc midpoint (315 deg)
        [a,                    -a + r,             z],   # 12: end of BR arc
        # Right side, going UP to the bottom of the gap
        [a,                    -half_gap,          z],   # 13: end (bottom of gap)
    ]
    segments = ["Line", "Arc", "Line", "Arc",
                "Line", "Arc", "Line", "Arc", "Line"]
    return pts, segments


def centerline_perimeter(L: float, W: float, r: float, gap: float) -> float:
    """Perimeter of the centre-line path in mm (handy for SRF guessing)."""
    a = L / 2.0 - W / 2.0
    # 4 straight sides minus the gap, with each side shortened by 2 r at its
    # corners (one arc-radius at each end). The right side is doubly trimmed
    # by the gap and the corner arcs.
    side_full = 2 * a - 2 * r           # one untrimmed side, minus 2*r for arcs
    sides_total = 3 * side_full         # top, left, bottom -- full
    right_split = 2 * (a - r) - gap     # right side: minus arcs minus gap
    arcs_total = 4 * (math.pi / 2.0) * r
    return sides_total + right_split + arcs_total


# ============================================================================
# HFSS construction
# ============================================================================

def _set_design_variables(hfss) -> None:
    """Register parameters as HFSS design vars (for Optimetrics sweeps)."""
    hfss["$L"] = f"{LOOP_SIDE_MM}mm"
    hfss["$W"] = f"{TRACE_WIDTH_MM}mm"
    hfss["$T"] = f"{TRACE_THICK_MM}mm"
    hfss["$r"] = f"{CORNER_RADIUS_MM}mm"
    hfss["$gap"] = f"{GAP_MM}mm"
    hfss["$z0"] = f"{LOOP_Z_MM}mm"


def build_loop(hfss) -> None:
    """Create the copper loop solid in HFSS."""
    pts, segs = loop_path(LOOP_SIDE_MM, TRACE_WIDTH_MM,
                          CORNER_RADIUS_MM, GAP_MM, LOOP_Z_MM)
    hfss.modeler.create_polyline(
        points=pts,
        segment_type=segs,
        name=LOOP_NAME,
        material=COND_MATERIAL,
        xsection_type="Rectangle",
        xsection_width=f"{TRACE_WIDTH_MM}mm",
        xsection_height=f"{TRACE_THICK_MM}mm",
        xsection_orient="Z",
    )


def add_port_across_gap(hfss) -> None:
    """Drop a lumped port sheet spanning the 1 mm gap."""
    a = LOOP_SIDE_MM / 2.0 - TRACE_WIDTH_MM / 2.0
    half_gap = GAP_MM / 2.0
    x0 = a - TRACE_WIDTH_MM / 2.0
    x1 = a + TRACE_WIDTH_MM / 2.0
    y0 = -half_gap
    y1 = +half_gap

    hfss.modeler.create_rectangle(
        orientation="Z",
        origin=[x0, y0, LOOP_Z_MM],
        sizes=[x1 - x0, y1 - y0],
        name=PORT_SHEET_NAME,
    )
    hfss.lumped_port(
        assignment=PORT_SHEET_NAME,
        integration_line=[[a, y0, LOOP_Z_MM], [a, y1, LOOP_Z_MM]],
        impedance=PORT_IMPEDANCE,
        name=PORT_NAME,
        renormalize=True,
    )


def add_air_region(hfss) -> None:
    """Open region with a radiation boundary at the operating frequency."""
    hfss.create_open_region(
        frequency=f"{FREQUENCY_HZ/1e9}GHz",
        boundary="Radiation",
        apply_infinite_ground=False,
    )


def add_solution(hfss) -> None:
    """Adaptive solve at FREQUENCY_HZ plus a 50-800 MHz interpolating sweep."""
    setup = hfss.create_setup(
        name="Setup",
        Frequency=f"{FREQUENCY_HZ/1e9}GHz",
        MaximumPasses=20,
        MinimumPasses=2,
        MinimumConvergedPasses=2,
        MaxDeltaS=0.01,
    )
    setup.create_frequency_sweep(
        unit="MHz",
        name="Sweep_50_to_800",
        start_frequency=50,
        stop_frequency=800,
        num_of_freq_points=151,
        sweep_type="Interpolating",
    )

    if not ADD_PORT:
        return

    # Convenience output variables, mirroring the coil-pair script's style.
    omega = "(2*pi*Freq)"
    expressions = {
        "L_nH":     f"im(Z({PORT_NAME},{PORT_NAME}))/{omega}*1e9",
        "R_ohm":    f"re(Z({PORT_NAME},{PORT_NAME}))",
        "Q":        f"im(Z({PORT_NAME},{PORT_NAME}))/re(Z({PORT_NAME},{PORT_NAME}))",
        "ImZ":      f"im(Z({PORT_NAME},{PORT_NAME}))",
    }
    for var, expr in expressions.items():
        try:
            hfss.create_output_variable(var, expr,
                                        solution_name="Setup : LastAdaptive")
        except Exception as e:
            print(f"[WARN] could not add output variable {var}: {e}")

    try:
        hfss.post.create_report(
            expressions=list(expressions.keys()),
            setup_sweep_name="Setup : Sweep_50_to_800",
            domain="Sweep",
            primary_sweep_variable="Freq",
            plot_name="Loop parameters vs frequency",
        )
    except Exception as e:
        print(f"[WARN] could not create swept report: {e}")


# ============================================================================
# Orchestration
# ============================================================================

def print_summary() -> None:
    perim = centerline_perimeter(LOOP_SIDE_MM, TRACE_WIDTH_MM,
                                 CORNER_RADIUS_MM, GAP_MM)
    c = 299_792_458.0
    f_res_full = c / (perim * 1e-3)            # full-wave loop resonance
    f_res_half = f_res_full / 2.0              # half-wave dipole-like behaviour

    print("-" * 70)
    print("Single rounded-corner square loop, centred at the origin")
    print("-" * 70)
    print(f"  Outer side length  L  = {LOOP_SIDE_MM:.3f} mm")
    print(f"  Trace width        W  = {TRACE_WIDTH_MM:.3f} mm")
    print(f"  Copper thickness   T  = {TRACE_THICK_MM*1000:.1f} um")
    print(f"  Corner fillet      r  = {CORNER_RADIUS_MM:.3f} mm")
    print(f"  Gap                g  = {GAP_MM:.3f} mm  (right side, centred on y=0)")
    print(f"  Centre-line plane  z  = {LOOP_Z_MM:.3f} mm")
    print()
    print(f"  centre-line perimeter ~ {perim:.2f} mm")
    print(f"  full-wave loop resonance  ~ {f_res_full/1e9:.3f} GHz")
    print(f"  half-wave (dipole) resonance ~ {f_res_half/1e9:.3f} GHz")
    print(f"  At {FREQUENCY_HZ/1e6:.0f} MHz the loop is electrically "
          f"{perim*1e-3 / (c/FREQUENCY_HZ) :.4f} lambda "
          f"({(perim*1e-3) * (FREQUENCY_HZ / c) * 360:.2f} deg) of "
          "a wavelength.")
    print("-" * 70)


def build(hfss) -> None:
    hfss.modeler.model_units = "mm"
    _set_design_variables(hfss)
    build_loop(hfss)
    if ADD_PORT:
        add_port_across_gap(hfss)
    if ADD_AIR_REGION:
        add_air_region(hfss)
    if ADD_SOLUTION:
        add_solution(hfss)


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
                        help="Print the geometry summary and exit (no HFSS).")
    args = parser.parse_args(argv)

    validate_params()
    print_summary()
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
        build(hfss)
        hfss.save_project()
        print(f"[HFSS] Model saved to: {project_path}")
        if args.solve and ADD_SOLUTION:
            print("[HFSS] Running adaptive solve + sweep ...")
            hfss.analyze_setup("Setup")
            print("[HFSS] Solve complete.")
    except Exception:
        import traceback
        traceback.print_exc()
        rc = 1
    finally:
        hfss.release_desktop(close_projects=False, close_on_exit=False)
    return rc


if __name__ == "__main__":
    sys.exit(main())
