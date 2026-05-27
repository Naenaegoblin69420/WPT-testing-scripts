# IronPython 2.7 script for HFSS (Automation -> Run Script)
#
# Builds ONE square copper loop, centred on (0, 0), with rounded inside
# corners (3-point arcs at each turn) and a configurable open gap on the
# right side -- same XY footprint as single_square_loop.py.
#
# NEW feature: each STRAIGHT side has a configurable number of "folds"
# where the trace lifts up to a higher z, runs along the path for a
# short distance at that elevated z, then drops back down to the base
# z. Top-down (looking along -z), the inductor outline is IDENTICAL to
# the flat single-loop version -- the folds only add length in the z
# direction, increasing total wire length (and L) without enlarging the
# loop area. Corners (the rounded arcs) stay flat at the base z.
#
# Geometry ONLY -- this script does not create a port, an air region, a
# radiation boundary, or any analysis setup. Add all of those yourself
# in HFSS after the script finishes.
#
# Usage:
#   1. Open / create an HFSS DrivenModal design.
#   2. Automation -> Run Script -> select this file.
#
# All knobs are at the top of the file: edit, save, re-run.
#
# Fold mechanics
# --------------
# On each of the four straight sides, FOLDS_PER_SIDE evenly-spaced
# rectangular "bumps" are inserted into the polyline. Each fold is:
#   * vertical line UP from z_base to z_base + FOLD_HEIGHT_MM
#   * horizontal run of FOLD_LENGTH_MM along the path at the raised z
#   * vertical line DOWN back to z_base
# Added wire length per fold is 2 * FOLD_HEIGHT_MM. Set FOLDS_PER_SIDE
# to 0 to disable folds (script then matches single_square_loop.py).

import ScriptEnv
import math

ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
oDesktop.RestoreWindow()

oProject = oDesktop.GetActiveProject()
oDesign  = oProject.GetActiveDesign()
oEditor  = oDesign.SetActiveEditor("3D Modeler")


# ============================================================
# Tunable parameters (mm everywhere)
# ============================================================

# Loop geometry (XY footprint -- identical to single_square_loop.py)
LOOP_SIDE_MM     = 30.0    # outer side length
TRACE_WIDTH_MM   = 0.1     # trace width (perpendicular to path)
TRACE_THICK_MM   = 0.035   # copper thickness (35 um = 1 oz Cu)
CORNER_RADIUS_MM = 3.0     # inside fillet radius (must be > W/2)
GAP_MM           = 1.0     # right-side open gap, centred on y = 0
LOOP_Z_MM        = 11.0    # base z plane the loop sits in

# Fold parameters (set FOLDS_PER_SIDE = 0 to disable folds)
FOLDS_PER_SIDE   = 3       # number of bumps along each straight side
FOLD_HEIGHT_MM   = 1.0     # z displacement of each fold above z_base
FOLD_LENGTH_MM   = 1.5     # length of the raised "run" portion of each fold

MATERIAL  = "copper"
LOOP_NAME = "FoldedSquareLoop"


# ============================================================
# Geometry: rounded-corner square loop with right-side gap + folds
# ============================================================

a = LOOP_SIDE_MM / 2.0 - TRACE_WIDTH_MM / 2.0   # centre-line half-side
half_gap = GAP_MM / 2.0
r = CORNER_RADIUS_MM
r2 = r / math.sqrt(2.0)                          # arc midpoint offset
z = LOOP_Z_MM

# Sanity checks
if r <= TRACE_WIDTH_MM / 2.0:
    raise Exception("CORNER_RADIUS_MM (%s) must exceed half the trace width "
                    "(%s)." % (r, TRACE_WIDTH_MM / 2.0))
if r >= a - half_gap:
    raise Exception("CORNER_RADIUS_MM (%s) too big: corner arcs overlap the "
                    "gap (must be < %s)." % (r, a - half_gap))
if GAP_MM <= 0:
    raise Exception("GAP_MM must be positive (loop must NOT close).")
if FOLDS_PER_SIDE < 0:
    raise Exception("FOLDS_PER_SIDE must be >= 0.")
if FOLD_HEIGHT_MM < 0 or FOLD_LENGTH_MM <= 0:
    raise Exception("FOLD_HEIGHT_MM must be >= 0, FOLD_LENGTH_MM must be > 0.")


def folded_straight(start_xy, end_xy, n_folds, fold_length, fold_height, z_base):
    """Generate intermediate polyline points for a folded straight side.

    Returns a list of (x, y, z) tuples to APPEND to the polyline after
    start_xy has already been added. Includes the end point. Each fold
    is a 3-D rectangular bump: up, across, down.
    """
    sx, sy = start_xy
    ex, ey = end_xy
    total = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)
    if n_folds == 0:
        return [(ex, ey, z_base)]

    occupied = n_folds * fold_length
    if occupied >= total:
        raise Exception(
            "Folds too long for this side (%.2f mm): %d x %.2f mm = %.2f mm "
            "occupied of %.2f mm available. Reduce FOLDS_PER_SIDE or "
            "FOLD_LENGTH_MM."
            % (total, n_folds, fold_length, occupied, total))

    n_gaps = n_folds + 1
    gap = (total - occupied) / n_gaps
    ux = (ex - sx) / total
    uy = (ey - sy) / total

    pts = []
    cursor = 0.0
    for i in range(n_folds):
        cursor += gap
        fsx = sx + ux * cursor
        fsy = sy + uy * cursor
        pts.append((fsx, fsy, z_base))                 # arrive at fold start
        pts.append((fsx, fsy, z_base + fold_height))   # lift up
        cursor += fold_length
        fex = sx + ux * cursor
        fey = sy + uy * cursor
        pts.append((fex, fey, z_base + fold_height))   # run across at top
        pts.append((fex, fey, z_base))                 # drop back down
    pts.append((ex, ey, z_base))                       # final stretch to corner
    return pts


# Build the full polyline points + segment list.
# Each "side" is a folded straight (Line segments only).
# Each corner is a 3-point Arc (start shared with previous segment's end,
# plus midpoint + end appended to the points list).

points = []
segment_types = []

# Initial point: top of gap, right side
points.append((a, half_gap, z))

def add_folded_side(start_xy, end_xy):
    """Append a folded straight side and its Line segments."""
    fold_pts = folded_straight(start_xy, end_xy, FOLDS_PER_SIDE,
                               FOLD_LENGTH_MM, FOLD_HEIGHT_MM, z)
    for pt in fold_pts:
        points.append(pt)
        segment_types.append(("Line", len(points) - 2, 2))


def add_corner_arc(mid_xy, end_xy):
    """Append a 3-point Arc corner: mid + end (start is the prior point)."""
    points.append((mid_xy[0], mid_xy[1], z))
    points.append((end_xy[0], end_xy[1], z))
    segment_types.append(("Arc", len(points) - 3, 3))


# Right side going UP (top half), folded
add_folded_side((a, half_gap), (a, a - r))
# Top-right arc
add_corner_arc((a - r + r2, a - r + r2), (a - r, a))
# Top going LEFT, folded
add_folded_side((a - r, a), (-a + r, a))
# Top-left arc
add_corner_arc((-a + r - r2, a - r + r2), (-a, a - r))
# Left side going DOWN, folded
add_folded_side((-a, a - r), (-a, -a + r))
# Bottom-left arc
add_corner_arc((-a + r - r2, -a + r - r2), (-a + r, -a))
# Bottom going RIGHT, folded
add_folded_side((-a + r, -a), (a - r, -a))
# Bottom-right arc
add_corner_arc((a - r + r2, -a + r - r2), (a, -a + r))
# Right side going UP (bottom half, to bottom of gap), folded
add_folded_side((a, -a + r), (a, -half_gap))


# ============================================================
# Convert to HFSS COM arg structures and create the polyline
# ============================================================

polyline_points = ["NAME:PolylinePoints"]
for p in points:
    polyline_points.append([
        "NAME:PLPoint",
        "X:=", "%fmm" % p[0],
        "Y:=", "%fmm" % p[1],
        "Z:=", "%fmm" % p[2],
    ])

segments = ["NAME:PolylineSegments"]
for stype, start_idx, n_pts in segment_types:
    segments.append([
        "NAME:PLSegment",
        "SegmentType:=", stype,
        "StartIndex:=",  start_idx,
        "NoOfPoints:=",  n_pts,
    ])

xsection = [
    "NAME:PolylineXSection",
    "XSectionType:=",        "Rectangle",
    "XSectionOrient:=",      "Auto",
    "XSectionWidth:=",       "%fmm" % TRACE_WIDTH_MM,
    "XSectionTopWidth:=",    "%fmm" % TRACE_WIDTH_MM,
    "XSectionHeight:=",      "%fmm" % TRACE_THICK_MM,
    "XSectionNumSegments:=", "0",
    "XSectionBendType:=",    "Corner",
]

polyline_params = [
    "NAME:PolylineParameters",
    "IsPolylineCovered:=", False,
    "IsPolylineClosed:=",  False,
    polyline_points,
    segments,
    xsection,
]

attributes = [
    "NAME:Attributes",
    "Name:=",                 LOOP_NAME,
    "Flags:=",                "",
    "Color:=",                "(255 128 0)",
    "Transparency:=",         0,
    "PartCoordinateSystem:=", "Global",
    "MaterialValue:=",        '"' + MATERIAL + '"',
    "SolveInside:=",          True,
]

oEditor.CreatePolyline(polyline_params, attributes)


# ============================================================
# Summary into the Message Manager
# ============================================================

# Flat-loop (no-folds) Greenhouse analytic L estimate, as a baseline
a_m = (LOOP_SIDE_MM - TRACE_WIDTH_MM) * 1e-3
wt_m = (TRACE_WIDTH_MM + TRACE_THICK_MM) * 1e-3
mu0 = 4e-7 * math.pi
L_flat_H = (2.0 * mu0 * a_m / math.pi) * (math.log(2.0 * a_m / wt_m) - 0.274)
L_flat_nH = L_flat_H * 1e9

total_folds = 4 * FOLDS_PER_SIDE
added_wire_mm = total_folds * 2.0 * FOLD_HEIGHT_MM

oDesktop.AddMessage("", "", 0,
    "FoldedSquareLoop built. side=%.1fmm  z=%.1fmm. "
    "%d folds total, +%.1fmm of wire vs. flat loop. "
    "Flat-loop Greenhouse L ~ %.1f nH (folded L will be a bit higher; "
    "HFSS to confirm)."
    % (LOOP_SIDE_MM, LOOP_Z_MM, total_folds, added_wire_mm, L_flat_nH))

oEditor.FitAll()
