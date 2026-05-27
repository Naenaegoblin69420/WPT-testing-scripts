# IronPython 2.7 script for HFSS (Automation -> Run Script)
#
# Builds ONE square copper loop, centred on (0, 0), with rounded inside
# corners and a configurable open gap on the right side. Same XY base
# footprint as single_square_loop.py, but each straight side has a
# configurable number of "petal" bulges -- half-ellipses in the XY
# plane that push the trace outward (or inward) by FOLD_HEIGHT_MM.
#
# This is the planar-fold cousin of folded_square_loop.py:
#   folded_square_loop.py  -> bumps in Z, trace length grows, area same
#   petal_square_loop.py   -> bumps in XY, area changes (with sign),
#                             trace length also grows
#
# Knobs (same names as folded_square_loop.py so the two are swap-compatible):
#   FOLDS_PER_SIDE   : how many petals per side  (set 0 to disable folds)
#   FOLD_HEIGHT_MM   : petal height. Positive = outward (area UP),
#                      negative = inward (area DOWN),
#                      ZERO = plain rounded square (single_square_loop.py).
#   FOLD_LENGTH_MM   : chord length of each half-ellipse along the path.
#   PETAL_SEGMENTS   : how many straight pieces approximate each
#                      half-ellipse curve (16 is smooth-looking).
#
# Geometry ONLY -- this script does not create a port, an air region,
# a radiation boundary, or any analysis setup. Add all of those yourself
# in HFSS after the script finishes.
#
# Usage:
#   1. Open / create an HFSS DrivenModal design.
#   2. Automation -> Run Script -> select this file.
#
# Right-side gap handling
# -----------------------
# Petal positions on the right side use the SAME even spacing as the
# other three sides, so all four sides are visually symmetric in a
# top-down view. The 1 mm gap (always centred on y = 0) just lives
# wherever it falls in that pre-planned petal pattern:
#   * if it lands between petals, the two trace ends meet the gap at
#     x = (LOOP_SIDE_MM - TRACE_WIDTH_MM) / 2 (the plain straight-side x);
#   * if a petal's bulge happens to span y = 0, the gap lives inside
#     that petal and the two trace ends meet the gap at the petal-curve
#     x, displaced from the straight-side x by
#         FOLD_HEIGHT_MM * sqrt( 1 - (2 * half_gap / FOLD_LENGTH_MM)^2 ).
# The post-build message in the Message Manager prints the gap (x, y)
# you should drop the port sheet at.

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

LOOP_SIDE_MM     = 30.0    # outer side length
TRACE_WIDTH_MM   = 0.15    # trace width (perpendicular to path)
TRACE_THICK_MM   = 0.035   # copper thickness (35 um = 1 oz Cu)
CORNER_RADIUS_MM = 3.0     # inside fillet radius (must be > W/2)
GAP_MM           = 1.0     # right-side open gap, centred on y = 0
LOOP_Z_MM        = 11.0    # z plane the loop sits in

FOLDS_PER_SIDE   = 3       # number of petals per side (0 disables)
FOLD_HEIGHT_MM   = 1.0     # + outward, - inward, 0 = plain loop
FOLD_LENGTH_MM   = 4.5     # chord (path-direction length) of each petal
PETAL_SEGMENTS   = 16      # straight pieces per half-ellipse approximation

MATERIAL  = "copper"
LOOP_NAME = "PetalSquareLoop"


# ============================================================
# Derived constants + sanity checks
# ============================================================

a = LOOP_SIDE_MM / 2.0 - TRACE_WIDTH_MM / 2.0   # centre-line half-side
half_gap = GAP_MM / 2.0
r = CORNER_RADIUS_MM
r2 = r / math.sqrt(2.0)
z = LOOP_Z_MM

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
if FOLD_LENGTH_MM <= 0:
    raise Exception("FOLD_LENGTH_MM must be > 0.")
if PETAL_SEGMENTS < 4:
    raise Exception("PETAL_SEGMENTS must be >= 4 (for a reasonable half-ellipse).")
if (FOLDS_PER_SIDE > 0 and FOLD_HEIGHT_MM != 0.0
        and abs(FOLD_HEIGHT_MM) >= (a - r)):
    raise Exception(
        "|FOLD_HEIGHT_MM| (%.3f) too large: an inward petal would cross the "
        "loop centre, an outward petal would stick out past the side. Keep "
        "|FOLD_HEIGHT_MM| < %.3f."
        % (abs(FOLD_HEIGHT_MM), a - r))


# ============================================================
# Petal helpers
# ============================================================

def petal_side_points(start_xy, end_xy):
    """Return polyline points (each (x, y, z)) for a straight side with
    FOLDS_PER_SIDE half-ellipse petals evenly distributed along it.
    Excludes start_xy (assumed already in the polyline), includes end_xy
    and every intermediate petal-curve point.
    """
    sx, sy = start_xy
    ex, ey = end_xy
    L_side = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)

    if FOLDS_PER_SIDE == 0 or FOLD_HEIGHT_MM == 0.0:
        return [(ex, ey, z)]

    occupied = FOLDS_PER_SIDE * FOLD_LENGTH_MM
    if occupied >= L_side:
        raise Exception(
            "Petals too long for this side (%.2f mm): %d x %.2f mm = %.2f mm "
            "occupied. Reduce FOLDS_PER_SIDE or FOLD_LENGTH_MM."
            % (L_side, FOLDS_PER_SIDE, FOLD_LENGTH_MM, occupied))

    pitch_gap = (L_side - occupied) / (FOLDS_PER_SIDE + 1)
    tx = (ex - sx) / L_side
    ty = (ey - sy) / L_side
    # Outward perpendicular for a CCW path = rotate tangent by -90 deg
    nx = ty
    ny = -tx

    pts = []
    for i in range(FOLDS_PER_SIDE):
        ps = (i + 1) * pitch_gap + i * FOLD_LENGTH_MM
        # Pre-petal: trace on the straight path until the petal starts
        pts.append((sx + tx * ps, sy + ty * ps, z))
        # Half-ellipse: theta from pi/PETAL_SEGMENTS up to pi
        for k in range(1, PETAL_SEGMENTS + 1):
            theta = k * math.pi / PETAL_SEGMENTS
            s_along = ps + FOLD_LENGTH_MM * (1.0 - math.cos(theta)) / 2.0
            v_perp = FOLD_HEIGHT_MM * math.sin(theta)
            x = sx + tx * s_along + nx * v_perp
            y = sy + ty * s_along + ny * v_perp
            pts.append((x, y, z))
    # Final straight stretch to the end corner
    pts.append((ex, ey, z))
    return pts


def plan_right_side():
    """Plan the right side (with the gap) as ONE logical side.

    Returns:
        top_half_pts:    points to append AFTER the initial gap-top point
        bottom_half_pts: points to append AFTER the BR corner arc
        gap_top_xyz:     (x, y, z) of the trace end at the TOP of the gap
        gap_bot_xyz:     (x, y, z) of the trace end at the BOTTOM of the gap
    """
    L = 2 * (a - r)

    if FOLDS_PER_SIDE == 0 or FOLD_HEIGHT_MM == 0.0:
        return ([(a, a - r, z)],
                [(a, -half_gap, z)],
                (a, +half_gap, z),
                (a, -half_gap, z))

    occupied = FOLDS_PER_SIDE * FOLD_LENGTH_MM
    if occupied >= L:
        raise Exception(
            "Petals too long for the right side (%.2f mm available, %.2f "
            "mm occupied)." % (L, occupied))
    pitch_gap = (L - occupied) / (FOLDS_PER_SIDE + 1)
    petals = []
    for i in range(FOLDS_PER_SIDE):
        ps = (i + 1) * pitch_gap + i * FOLD_LENGTH_MM
        pe = ps + FOLD_LENGTH_MM
        petals.append((ps, pe))

    s_gap_lo = L / 2.0 - half_gap
    s_gap_hi = L / 2.0 + half_gap
    mid_s = L / 2.0

    # Identify the straddling petal (if any) and the theta values at which
    # the petal curve crosses y = +half_gap and y = -half_gap.
    #   y_petal(theta) = -(a - r) + pc - (L_chord / 2) * cos(theta)
    # so   cos(theta) at y_gap = (2*pc - L - 2*y_gap) / L_chord
    straddling = None
    for (ps, pe) in petals:
        if ps < mid_s < pe:
            pc = (ps + pe) / 2.0
            cos_theta_top = (2.0 * pc - L - 2.0 * half_gap) / FOLD_LENGTH_MM
            cos_theta_bot = (2.0 * pc - L + 2.0 * half_gap) / FOLD_LENGTH_MM
            if abs(cos_theta_top) >= 1.0 or abs(cos_theta_bot) >= 1.0:
                raise Exception(
                    "GAP_MM (%.2f) doesn't fit inside the straddling petal "
                    "(chord %.2f mm). Reduce GAP_MM or raise FOLD_LENGTH_MM."
                    % (GAP_MM, FOLD_LENGTH_MM))
            theta_top = math.acos(cos_theta_top)
            theta_bot = math.acos(cos_theta_bot)
            straddling = (ps, pe, theta_bot, theta_top)
            break

    def y_of(s):
        return -(a - r) + s

    def petal_xy(ps_local, theta):
        s_along = ps_local + FOLD_LENGTH_MM * (1.0 - math.cos(theta)) / 2.0
        return (a + FOLD_HEIGHT_MM * math.sin(theta), y_of(s_along), z)

    bottom_half = []
    top_half = []

    for (ps, pe) in petals:
        if straddling and ps == straddling[0]:
            _, _, theta_bot, theta_top = straddling
            # Bottom half: pre-petal point + petal samples with theta < theta_bot
            bottom_half.append((a, y_of(ps), z))
            for k in range(1, PETAL_SEGMENTS + 1):
                theta = k * math.pi / PETAL_SEGMENTS
                if theta >= theta_bot:
                    break
                bottom_half.append(petal_xy(ps, theta))
            # Top half resumes after the gap with petal samples theta > theta_top
            for k in range(1, PETAL_SEGMENTS + 1):
                theta = k * math.pi / PETAL_SEGMENTS
                if theta <= theta_top:
                    continue
                top_half.append(petal_xy(ps, theta))
        elif pe <= s_gap_lo:
            # Full petal in the bottom half
            bottom_half.append((a, y_of(ps), z))
            for k in range(1, PETAL_SEGMENTS + 1):
                theta = k * math.pi / PETAL_SEGMENTS
                bottom_half.append(petal_xy(ps, theta))
        elif ps >= s_gap_hi:
            # Full petal in the top half
            top_half.append((a, y_of(ps), z))
            for k in range(1, PETAL_SEGMENTS + 1):
                theta = k * math.pi / PETAL_SEGMENTS
                top_half.append(petal_xy(ps, theta))
        # Edge cases (petal entirely inside the gap, or with only one
        # endpoint inside) are silently dropped -- they shouldn't happen
        # with GAP_MM <= FOLD_LENGTH_MM, the normal case.

    if straddling:
        _, _, theta_bot, theta_top = straddling
        gap_top_x = a + FOLD_HEIGHT_MM * math.sin(theta_top)
        gap_bot_x = a + FOLD_HEIGHT_MM * math.sin(theta_bot)
    else:
        gap_top_x = a
        gap_bot_x = a

    bottom_half.append((gap_bot_x, -half_gap, z))
    top_half.append((a, a - r, z))

    return (top_half, bottom_half,
            (gap_top_x, +half_gap, z),
            (gap_bot_x, -half_gap, z))


# ============================================================
# Build the polyline
# ============================================================

right_top_pts, right_bottom_pts, gap_top_xyz, gap_bot_xyz = plan_right_side()

points = []
segment_types = []

# Initial polyline point: top of gap (x may be displaced if a petal straddles)
points.append(gap_top_xyz)


def add_point_sequence(pt_list):
    """Append a precomputed sequence of points, one Line segment each."""
    for pt in pt_list:
        points.append(pt)
        segment_types.append(("Line", len(points) - 2, 2))


def add_corner_arc(mid_xy, end_xy):
    """Append a 3-point Arc corner."""
    points.append((mid_xy[0], mid_xy[1], z))
    points.append((end_xy[0], end_xy[1], z))
    segment_types.append(("Arc", len(points) - 3, 3))


def add_petal_side(start_xy, end_xy):
    add_point_sequence(petal_side_points(start_xy, end_xy))


# Right side TOP half (gap -> top-right corner) -- pre-planned above
add_point_sequence(right_top_pts)
# Top-right corner arc
add_corner_arc((a - r + r2, a - r + r2), (a - r, a))
# Top side with petals
add_petal_side((a - r, a), (-a + r, a))
# Top-left corner arc
add_corner_arc((-a + r - r2, a - r + r2), (-a, a - r))
# Left side with petals (downward)
add_petal_side((-a, a - r), (-a, -a + r))
# Bottom-left corner arc
add_corner_arc((-a + r - r2, -a + r - r2), (-a + r, -a))
# Bottom side with petals
add_petal_side((-a + r, -a), (a - r, -a))
# Bottom-right corner arc
add_corner_arc((a - r + r2, -a + r - r2), (a, -a + r))
# Right side BOTTOM half (BR corner -> bottom of gap)
add_point_sequence(right_bottom_pts)


# ============================================================
# Convert to HFSS COM args and create the polyline
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
# Summary to the Message Manager
# ============================================================

# Plain rounded-square area (no petals): a square of side (LOOP_SIDE - W)
# minus the four corner-quarter-square pieces replaced by quarter-circles.
side_eff = LOOP_SIDE_MM - TRACE_WIDTH_MM
baseline_area_mm2 = side_eff ** 2 - (4.0 - math.pi) * r ** 2

# Each petal's signed contribution to enclosed area = (pi/2) * (L/2) * h
petal_area_each = (math.pi / 2.0) * (FOLD_LENGTH_MM / 2.0) * FOLD_HEIGHT_MM
total_petals = 4 * FOLDS_PER_SIDE
petal_area_total_mm2 = total_petals * petal_area_each
loop_area_mm2 = baseline_area_mm2 + petal_area_total_mm2

# Plain Greenhouse single-loop L estimate (no petals), as a baseline
a_m = side_eff * 1e-3
wt_m = (TRACE_WIDTH_MM + TRACE_THICK_MM) * 1e-3
mu0 = 4e-7 * math.pi
L_flat_H = (2.0 * mu0 * a_m / math.pi) * (math.log(2.0 * a_m / wt_m) - 0.274)
L_flat_nH = L_flat_H * 1e9

# Where to place the port sheet (where the trace ends at the gap)
gap_x_offset = gap_top_xyz[0] - a   # signed: + outward, - inward

oDesktop.AddMessage("", "", 0,
    "PetalSquareLoop built. side=%.1fmm  z=%.1fmm  %d petals  "
    "height=%+.2fmm  chord=%.2fmm. "
    "Baseline area %.1f mm^2 %+.1f mm^2 from petals = %.1f mm^2 (%+.1f%%). "
    "Port sheet goes at x=%.3f, y=+/-%.2f, z=%.2f. "
    "Greenhouse flat-loop L estimate ~ %.1f nH (HFSS to confirm; petals "
    "will shift it)."
    % (LOOP_SIDE_MM, LOOP_Z_MM, total_petals, FOLD_HEIGHT_MM, FOLD_LENGTH_MM,
       baseline_area_mm2, petal_area_total_mm2, loop_area_mm2,
       100.0 * petal_area_total_mm2 / baseline_area_mm2 if baseline_area_mm2 > 0 else 0.0,
       a + gap_x_offset, half_gap, LOOP_Z_MM,
       L_flat_nH))

oEditor.FitAll()
