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
# This script creates the loop body AND a TX circuit port across the
# gap. It does NOT create the air region or the radiation boundary --
# add those yourself in HFSS once before running this script.
#
# Usage:
#   1. Open / create an HFSS DrivenModal design.
#   2. Automation -> Run Script -> select this file.
#
# All knobs are at the top of the file: edit, save, re-run.
#
# Fold mechanics
# --------------
# On each of the FOUR sides (top, left, bottom, and the right side --
# the right side is treated as ONE logical side that just happens to
# have the 1 mm gap somewhere in the middle), FOLDS_PER_SIDE evenly-
# spaced rectangular "bumps" are inserted into the polyline. Each fold
# is:
#   * vertical line UP from z_base to z_base + FOLD_HEIGHT_MM
#   * horizontal run of FOLD_LENGTH_MM along the path at the raised z
#   * vertical line DOWN back to z_base
# Added wire length per fold is 2 * FOLD_HEIGHT_MM. Set FOLDS_PER_SIDE
# to 0 to disable folds (script then matches single_square_loop.py).
#
# Right-side gap handling
# -----------------------
# Fold positions on the right side use the SAME even spacing across its
# full corner-to-corner length as the other three sides, so all four
# sides are visually symmetric in a top-down view. The 1 mm gap (always
# centred on y = 0) just lives wherever it falls:
#   * if it lands between folds, the two ends of the trace sit at z_base
#     on either side of the gap (the usual flat-gap case);
#   * if a fold's elevated run happens to span y = 0, the gap lives
#     inside that elevated run and the two ends of the trace sit at
#     z_base + FOLD_HEIGHT_MM on either side of the gap.
# Either way the right side has the same number of fold-bumps as the
# other three sides.

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
LOOP_SIDE_MM     = 28.0    # outer side length
TRACE_WIDTH_MM   = 0.1     # trace width (perpendicular to path)
TRACE_THICK_MM   = 0.05   # copper thickness (35 um = 1 oz Cu)
CORNER_RADIUS_MM = 3.0     # inside fillet radius (must be > W/2)
GAP_MM           = 1.0     # right-side open gap, centred on y = 0
LOOP_Z_MM        = 11.0    # base z plane the loop sits in

# Fold parameters (set FOLDS_PER_SIDE = 0 to disable folds)
FOLDS_PER_SIDE   = 5       # number of bumps along each straight side
FOLD_HEIGHT_MM   = 1.0     # z displacement of each fold above z_base
FOLD_LENGTH_MM   = 1     # length of the raised "run" portion of each fold

MATERIAL  = "copper"
LOOP_NAME = "FoldedSquareLoop"

# Port parameters (edge-based circuit port across the right-side gap)
PORT_NAME      = "TX"
PORT_IMPEDANCE = 50.0    # ohm


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
# When TRACE_WIDTH approaches or exceeds either of the fold's segment
# lengths (FOLD_HEIGHT for the vertical lifts, FOLD_LENGTH for the
# elevated horizontal run), the 90 deg z-corners of the fold self-
# intersect via the polyline miter (XSectionBendType = "Corner"). Result:
# TAU mesh repair fails and hf3d refuses to start. Empirical safe margin
# is ~2x. Report only the offending dimension(s) so it's clear which knob
# to bump.
if FOLDS_PER_SIDE > 0 and FOLD_HEIGHT_MM > 0:
    offenders = []
    if TRACE_WIDTH_MM > FOLD_HEIGHT_MM:
        offenders.append(
            "FOLD_HEIGHT_MM (%.3f) < TRACE_WIDTH_MM (%.3f) -- vertical lift "
            "miters self-intersect; raise FOLD_HEIGHT_MM to >= %.3f"
            % (FOLD_HEIGHT_MM, TRACE_WIDTH_MM, 2.0 * TRACE_WIDTH_MM))
    if TRACE_WIDTH_MM > FOLD_LENGTH_MM:
        offenders.append(
            "FOLD_LENGTH_MM (%.3f) < TRACE_WIDTH_MM (%.3f) -- elevated-run "
            "miters self-intersect; raise FOLD_LENGTH_MM to >= %.3f"
            % (FOLD_LENGTH_MM, TRACE_WIDTH_MM, 2.0 * TRACE_WIDTH_MM))
    if offenders:
        raise Exception(
            "Fold geometry would self-intersect during the polyline sweep:\n  - "
            + "\n  - ".join(offenders)
            + "\nAlternative: change XSectionBendType from 'Corner' to "
              "'Curved' further down in this script (rounds the bumps, "
              "tolerates wider traces).")


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

def plan_right_side():
    """Plan the right side as ONE logical side with FOLDS_PER_SIDE folds
    evenly spaced across the full corner-to-corner length, with the gap
    sitting wherever it falls.

    Returns:
        top_half:    points to append AFTER the initial gap-top point;
                     traces from (a, +half_gap) UP to (a, a - r).
        bottom_half: points to append AFTER the bottom-right corner arc;
                     traces from (a, -(a - r)) UP to (a, -half_gap).
        z_at_gap:    z level the trace sits at when crossing y = 0
                     (z if no fold straddles, z + FOLD_HEIGHT_MM if one does).
    """
    L = 2 * (a - r)
    if FOLDS_PER_SIDE == 0:
        return [(a, a - r, z)], [(a, -half_gap, z)], z

    occupied = FOLDS_PER_SIDE * FOLD_LENGTH_MM
    if occupied >= L:
        raise Exception(
            "Folds too long for the right side (%.2f mm): %d x %.2f mm = "
            "%.2f mm occupied. Reduce FOLDS_PER_SIDE or FOLD_LENGTH_MM."
            % (L, FOLDS_PER_SIDE, FOLD_LENGTH_MM, occupied))
    pitch_gap = (L - occupied) / (FOLDS_PER_SIDE + 1)
    folds = []
    for i in range(FOLDS_PER_SIDE):
        s_start = (i + 1) * pitch_gap + i * FOLD_LENGTH_MM
        folds.append((s_start, s_start + FOLD_LENGTH_MM))

    s_gap_lo = L / 2.0 - half_gap
    s_gap_hi = L / 2.0 + half_gap
    mid_s    = L / 2.0

    z_at_gap = z
    for (fs, fe) in folds:
        if fs <= mid_s <= fe:
            z_at_gap = z + FOLD_HEIGHT_MM
            break

    def y_at(s):
        return -(a - r) + s

    top_half = []
    bottom_half = []
    for (fs, fe) in folds:
        ys, ye = y_at(fs), y_at(fe)
        if fe <= s_gap_lo:
            # Full fold in the bottom half
            bottom_half.append((a, ys, z))
            bottom_half.append((a, ys, z + FOLD_HEIGHT_MM))
            bottom_half.append((a, ye, z + FOLD_HEIGHT_MM))
            bottom_half.append((a, ye, z))
        elif fs >= s_gap_hi:
            # Full fold in the top half
            top_half.append((a, ys, z))
            top_half.append((a, ys, z + FOLD_HEIGHT_MM))
            top_half.append((a, ye, z + FOLD_HEIGHT_MM))
            top_half.append((a, ye, z))
        elif fs < s_gap_lo and fe > s_gap_hi:
            # Straddling fold: UP in the bottom half, DOWN in the top half
            bottom_half.append((a, ys, z))
            bottom_half.append((a, ys, z + FOLD_HEIGHT_MM))
            top_half.append((a, ye, z + FOLD_HEIGHT_MM))
            top_half.append((a, ye, z))
        # Other partial-overlap cases are silently dropped; they shouldn't
        # happen when GAP_MM <= FOLD_LENGTH_MM (the normal case).

    bottom_half.append((a, -half_gap, z_at_gap))
    top_half.append((a, a - r, z))
    return top_half, bottom_half, z_at_gap


# Plan the right side first -- the initial polyline point's z depends on
# whether a fold straddles the gap.
right_top_pts, right_bottom_pts, z_at_gap = plan_right_side()

points = []
segment_types = []

# Initial point: top of gap on the right side (may sit at elevated z)
points.append((a, half_gap, z_at_gap))


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


def add_point_sequence(pt_list):
    """Append a precomputed sequence of points, one Line segment each."""
    for pt in pt_list:
        points.append(pt)
        segment_types.append(("Line", len(points) - 2, 2))


# Right side TOP half (gap -> top-right corner) -- pre-planned above
add_point_sequence(right_top_pts)
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
# Right side BOTTOM half (BR corner -> bottom of gap) -- pre-planned above
add_point_sequence(right_bottom_pts)


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
# Port "TX" -- circuit port between the two edges at the gap
# ============================================================
# Same edge-based pattern as petal_square_loop.py: pick one edge of the
# trace on each side of the 1 mm gap (top of the trace's cross-section
# on each end face) and AssignCircuitPort between them. The two target
# points use z_at_gap so the port correctly follows the elevated-z case
# when a fold straddles the gap.

def _to_mm(value):
    s = str(value).strip()
    if s.endswith("mm"):
        return float(s[:-2])
    if s.endswith("m"):
        return float(s[:-1]) * 1000.0
    return float(s)


def _edge_midpoint(eid):
    vids = oEditor.GetVertexIDsFromEdge(eid)
    if not vids:
        return None
    n = float(len(vids))
    sx = sy = sz = 0.0
    for vid in vids:
        pos = oEditor.GetVertexPosition(vid)
        sx += _to_mm(pos[0])
        sy += _to_mm(pos[1])
        sz += _to_mm(pos[2])
    return (sx / n, sy / n, sz / n)


def _find_closest_edge(body, tx, ty, tz):
    eids = oEditor.GetEdgeIDsFromObject(body)
    best, best_d2 = None, 1.0e30
    for eid in eids:
        mid = _edge_midpoint(eid)
        if mid is None:
            continue
        dx = mid[0] - tx
        dy = mid[1] - ty
        dz = mid[2] - tz
        d2 = dx * dx + dy * dy + dz * dz
        if d2 < best_d2:
            best_d2 = d2
            best = eid
    return best


# The two trace ends at the gap sit at (a, +/- half_gap, z_at_gap).
# Aim at the top-of-trace edge of each end face (z_at_gap + T/2) -- any
# end-face edge would work; this is just a deterministic pick.
trace_top_z = z_at_gap + TRACE_THICK_MM / 2.0
edge_top = _find_closest_edge(LOOP_NAME, a, +half_gap, trace_top_z)
edge_bot = _find_closest_edge(LOOP_NAME, a, -half_gap, trace_top_z)

if edge_top is None or edge_bot is None:
    raise Exception("Could not locate trace-end edges at the gap.")
if edge_top == edge_bot:
    raise Exception(
        "Same edge picked for both ends of the gap -- the trace's two end "
        "faces may not have produced distinct edges. Check the polyline.")

oBoundary = oDesign.GetModule("BoundarySetup")
oBoundary.AssignCircuitPort([
    "NAME:" + PORT_NAME,
    "Edges:=",                   [int(edge_top), int(edge_bot)],
    "Impedance:=",               "%fohm" % PORT_IMPEDANCE,
    "DoDeembed:=",               False,
    "RenormalizeAllTerminals:=", True,
])


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
    "Circuit port 'TX' assigned across the gap at y=+/-%.2f, z=%.2f "
    "(50 ohm). Flat-loop Greenhouse L ~ %.1f nH (folded L will be a bit "
    "higher; HFSS to confirm)."
    % (LOOP_SIDE_MM, LOOP_Z_MM, total_folds, added_wire_mm,
       half_gap, z_at_gap, L_flat_nH))

oEditor.FitAll()
