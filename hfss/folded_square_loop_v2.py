# IronPython 2.7 script for HFSS (Automation -> Run Script)
#
# folded_square_loop_v2.py
#
# Same XY footprint, parameters, sanity checks, gap handling, and TX
# circuit port as folded_square_loop.py -- but the folds along each
# side now ALTERNATE between two types:
#
#   even fold index (0, 2, 4, ...) -- "Z-fold":  rectangular bump in z,
#                                                identical to the original
#                                                folded_square_loop.py
#                                                (lift to z+FOLD_HEIGHT_MM,
#                                                 run for FOLD_LENGTH_MM,
#                                                 drop back).
#
#   odd  fold index (1, 3, 5, ...) -- "2D-fold": half-ellipse petal in the
#                                                XY plane (chord =
#                                                FOLD_LENGTH_MM along the
#                                                path, height =
#                                                FOLD_HEIGHT_MM out from
#                                                the path), exactly like
#                                                petal_square_loop.py.
#
# A new parameter INPLANE_FOLD_DIRECTION (+1 = outward / -1 = inward)
# controls which way the 2D folds bulge. It has NO effect on the
# Z-folds.
#
# The right side (the one with the 1 mm gap) is still planned as one
# logical side with FOLDS_PER_SIDE folds at the same even spacing as
# the other three. If the middle fold ends up straddling the gap:
#   * if it's a Z-fold:  the two trace ends meet the gap at
#                         z_base + FOLD_HEIGHT_MM (existing behaviour)
#   * if it's a 2D-fold: the two trace ends meet the gap at the
#                         petal-curve x (displaced from the plain
#                         straight-side x by FOLD_HEIGHT_MM *
#                         INPLANE_FOLD_DIRECTION *
#                         sqrt(1 - (2*half_gap/FOLD_LENGTH_MM)^2))
# The TX circuit port is placed across whatever the gap actually looks
# like (z and x can both be off-base).
#
# This script creates the loop body AND a TX circuit port across the
# gap. It does NOT create the air region or the radiation boundary --
# add those yourself in HFSS once before running this script.

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
LOOP_SIDE_MM     = 25.0
TRACE_WIDTH_MM   = 0.1
TRACE_THICK_MM   = 0.035
CORNER_RADIUS_MM = 3.0
GAP_MM           = 1.0
LOOP_Z_MM        = 11.0

# Fold parameters
FOLDS_PER_SIDE   = 4       # total folds per side; alternates Z, 2D, Z, 2D, ...
FOLD_HEIGHT_MM   = 1.0     # Z-fold lift OR 2D-fold petal-height magnitude
FOLD_LENGTH_MM   = 2.0     # chord (path-direction length) of each fold

# NEW: controls the 2D folds only
INPLANE_FOLD_DIRECTION = 1   # +1 = outward (loop area +), -1 = inward (loop area -)
PETAL_SEGMENTS         = 16  # straight pieces approximating each 2D half-ellipse

MATERIAL  = "copper"
LOOP_NAME = "FoldedSquareLoopV2"

# Port parameters
PORT_NAME      = "TX"
PORT_IMPEDANCE = 50.0


# ============================================================
# Derived constants + sanity checks
# ============================================================

a = LOOP_SIDE_MM / 2.0 - TRACE_WIDTH_MM / 2.0
half_gap = GAP_MM / 2.0
r = CORNER_RADIUS_MM
r2 = r / math.sqrt(2.0)
z = LOOP_Z_MM

if r <= TRACE_WIDTH_MM / 2.0:
    raise Exception("CORNER_RADIUS_MM (%s) must exceed half the trace width."
                    % r)
if r >= a - half_gap:
    raise Exception("CORNER_RADIUS_MM (%s) too big: corner arcs overlap the gap."
                    % r)
if GAP_MM <= 0:
    raise Exception("GAP_MM must be positive.")
if FOLDS_PER_SIDE < 0:
    raise Exception("FOLDS_PER_SIDE must be >= 0.")
if FOLD_HEIGHT_MM < 0 or FOLD_LENGTH_MM <= 0:
    raise Exception("FOLD_HEIGHT_MM must be >= 0, FOLD_LENGTH_MM must be > 0.")
if INPLANE_FOLD_DIRECTION not in (-1, 1):
    raise Exception("INPLANE_FOLD_DIRECTION must be +1 (outward) or -1 (inward).")
if PETAL_SEGMENTS < 4:
    raise Exception("PETAL_SEGMENTS must be >= 4.")

# Z-fold miter sanity (same rule as folded_square_loop.py)
if FOLDS_PER_SIDE > 0 and FOLD_HEIGHT_MM > 0:
    offenders = []
    if TRACE_WIDTH_MM > FOLD_HEIGHT_MM:
        offenders.append(
            "FOLD_HEIGHT_MM (%.3f) < TRACE_WIDTH_MM (%.3f) -- Z-fold vertical "
            "lift miters self-intersect; raise FOLD_HEIGHT_MM to >= %.3f"
            % (FOLD_HEIGHT_MM, TRACE_WIDTH_MM, 2.0 * TRACE_WIDTH_MM))
    if TRACE_WIDTH_MM > FOLD_LENGTH_MM:
        offenders.append(
            "FOLD_LENGTH_MM (%.3f) < TRACE_WIDTH_MM (%.3f) -- fold elevated-run "
            "miters self-intersect; raise FOLD_LENGTH_MM to >= %.3f"
            % (FOLD_LENGTH_MM, TRACE_WIDTH_MM, 2.0 * TRACE_WIDTH_MM))
    if offenders:
        raise Exception(
            "Fold geometry would self-intersect:\n  - " + "\n  - ".join(offenders))

# 2D inward sanity: petal can't reach the loop centre
if (FOLDS_PER_SIDE > 0 and FOLD_HEIGHT_MM > 0
        and INPLANE_FOLD_DIRECTION < 0
        and FOLD_HEIGHT_MM >= (a - r)):
    raise Exception(
        "|FOLD_HEIGHT_MM| (%.3f) too large for inward 2D folds: would cross the "
        "loop centre. Keep FOLD_HEIGHT_MM < %.3f when INPLANE_FOLD_DIRECTION = -1."
        % (FOLD_HEIGHT_MM, a - r))


# ============================================================
# Alternating-fold path generator for a generic straight side
# ============================================================

def alternating_folds_straight(start_xy, end_xy):
    """Polyline points for a straight side with FOLDS_PER_SIDE folds
    alternating Z (even index) and 2D (odd index). Excludes start_xy
    (already in the polyline), includes end_xy.
    """
    sx, sy = start_xy
    ex, ey = end_xy
    total = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)

    if FOLDS_PER_SIDE == 0 or FOLD_HEIGHT_MM == 0.0:
        return [(ex, ey, z)]

    occupied = FOLDS_PER_SIDE * FOLD_LENGTH_MM
    if occupied >= total:
        raise Exception(
            "Folds too long for this side (%.2f mm available)." % total)
    pitch_gap = (total - occupied) / (FOLDS_PER_SIDE + 1)

    ux = (ex - sx) / total
    uy = (ey - sy) / total
    nx = uy            # outward perpendicular (CCW path)
    ny = -ux
    inplane_h = INPLANE_FOLD_DIRECTION * FOLD_HEIGHT_MM

    pts = []
    cursor = 0.0
    for i in range(FOLDS_PER_SIDE):
        cursor += pitch_gap
        fs = cursor
        fsx = sx + ux * fs
        fsy = sy + uy * fs

        if i % 2 == 0:
            # ------- Z-fold (rectangular bump up) -------
            pts.append((fsx, fsy, z))                          # arrive at fold start
            pts.append((fsx, fsy, z + FOLD_HEIGHT_MM))         # lift up
            cursor += FOLD_LENGTH_MM
            fe = cursor
            fex = sx + ux * fe
            fey = sy + uy * fe
            pts.append((fex, fey, z + FOLD_HEIGHT_MM))         # run across at top
            pts.append((fex, fey, z))                          # drop back down
        else:
            # ------- 2D-fold (half-ellipse petal in XY) -------
            pts.append((fsx, fsy, z))                          # pre-petal start
            for k in range(1, PETAL_SEGMENTS + 1):
                theta = k * math.pi / PETAL_SEGMENTS
                s_along = fs + FOLD_LENGTH_MM * (1.0 - math.cos(theta)) / 2.0
                v_perp  = inplane_h * math.sin(theta)
                px = sx + ux * s_along + nx * v_perp
                py = sy + uy * s_along + ny * v_perp
                pts.append((px, py, z))
            cursor += FOLD_LENGTH_MM
    pts.append((ex, ey, z))
    return pts


# ============================================================
# Right-side plan: handles BOTH straddling-Z and straddling-2D fold cases
# ============================================================

def plan_right_side():
    """Plan the right side. Returns:
        top_half_pts:    points to append after the initial gap-top point
        bottom_half_pts: points to append after the BR corner arc
        z_at_gap:        z value of the two trace ends at the gap
        x_at_gap:        x value of the two trace ends at the gap (= a for
                         flat / Z-straddling, displaced for 2D-straddling)
    """
    L = 2 * (a - r)

    if FOLDS_PER_SIDE == 0 or FOLD_HEIGHT_MM == 0.0:
        return ([(a, a - r, z)],
                [(a, -half_gap, z)],
                z, a)

    occupied = FOLDS_PER_SIDE * FOLD_LENGTH_MM
    if occupied >= L:
        raise Exception("Folds too long for the right side.")
    pitch_gap_s = (L - occupied) / (FOLDS_PER_SIDE + 1)

    folds = []
    for i in range(FOLDS_PER_SIDE):
        s_start = (i + 1) * pitch_gap_s + i * FOLD_LENGTH_MM
        s_end   = s_start + FOLD_LENGTH_MM
        is_z    = (i % 2 == 0)
        folds.append((s_start, s_end, is_z))

    s_gap_lo = L / 2.0 - half_gap
    s_gap_hi = L / 2.0 + half_gap
    mid_s    = L / 2.0

    # Find the straddling fold (if any) and figure out (z_at_gap, x_at_gap)
    z_at_gap = z
    x_at_gap = a
    straddling_2d = None
    for (fs, fe, is_z) in folds:
        if fs < mid_s < fe:
            if is_z:
                z_at_gap = z + FOLD_HEIGHT_MM
            else:
                pc = (fs + fe) / 2.0
                cos_theta_top = (2.0 * pc - L - 2.0 * half_gap) / FOLD_LENGTH_MM
                cos_theta_bot = (2.0 * pc - L + 2.0 * half_gap) / FOLD_LENGTH_MM
                if abs(cos_theta_top) >= 1.0 or abs(cos_theta_bot) >= 1.0:
                    raise Exception(
                        "GAP_MM (%.2f) doesn't fit inside the straddling 2D fold "
                        "(chord %.2f mm). Lower GAP_MM or raise FOLD_LENGTH_MM."
                        % (GAP_MM, FOLD_LENGTH_MM))
                theta_top = math.acos(cos_theta_top)
                theta_bot = math.acos(cos_theta_bot)
                inplane_h = INPLANE_FOLD_DIRECTION * FOLD_HEIGHT_MM
                x_at_gap = a + inplane_h * math.sin(theta_top)
                straddling_2d = (fs, fe, theta_bot, theta_top)
            break

    def y_of(s):
        return -(a - r) + s

    inplane_h = INPLANE_FOLD_DIRECTION * FOLD_HEIGHT_MM

    bottom_half = []
    top_half = []

    for (fs, fe, is_z) in folds:
        ys, ye = y_of(fs), y_of(fe)
        if fe <= s_gap_lo:
            # Fold entirely in bottom half
            if is_z:
                bottom_half.append((a, ys, z))
                bottom_half.append((a, ys, z + FOLD_HEIGHT_MM))
                bottom_half.append((a, ye, z + FOLD_HEIGHT_MM))
                bottom_half.append((a, ye, z))
            else:
                bottom_half.append((a, ys, z))
                for k in range(1, PETAL_SEGMENTS + 1):
                    theta = k * math.pi / PETAL_SEGMENTS
                    s_along = fs + FOLD_LENGTH_MM * (1.0 - math.cos(theta)) / 2.0
                    bottom_half.append(
                        (a + inplane_h * math.sin(theta), y_of(s_along), z))
        elif fs >= s_gap_hi:
            # Fold entirely in top half
            if is_z:
                top_half.append((a, ys, z))
                top_half.append((a, ys, z + FOLD_HEIGHT_MM))
                top_half.append((a, ye, z + FOLD_HEIGHT_MM))
                top_half.append((a, ye, z))
            else:
                top_half.append((a, ys, z))
                for k in range(1, PETAL_SEGMENTS + 1):
                    theta = k * math.pi / PETAL_SEGMENTS
                    s_along = fs + FOLD_LENGTH_MM * (1.0 - math.cos(theta)) / 2.0
                    top_half.append(
                        (a + inplane_h * math.sin(theta), y_of(s_along), z))
        else:
            # Straddling the gap
            if is_z:
                # Z-fold straddling: UP in bottom half, DOWN in top half
                bottom_half.append((a, ys, z))
                bottom_half.append((a, ys, z + FOLD_HEIGHT_MM))
                top_half.append((a, ye, z + FOLD_HEIGHT_MM))
                top_half.append((a, ye, z))
            else:
                # 2D fold straddling: petal points with theta < theta_bot in
                # bottom half, theta > theta_top in top half
                _, _, theta_bot, theta_top = straddling_2d
                bottom_half.append((a, ys, z))
                for k in range(1, PETAL_SEGMENTS + 1):
                    theta = k * math.pi / PETAL_SEGMENTS
                    if theta >= theta_bot:
                        break
                    s_along = fs + FOLD_LENGTH_MM * (1.0 - math.cos(theta)) / 2.0
                    bottom_half.append(
                        (a + inplane_h * math.sin(theta), y_of(s_along), z))
                for k in range(1, PETAL_SEGMENTS + 1):
                    theta = k * math.pi / PETAL_SEGMENTS
                    if theta <= theta_top:
                        continue
                    s_along = fs + FOLD_LENGTH_MM * (1.0 - math.cos(theta)) / 2.0
                    top_half.append(
                        (a + inplane_h * math.sin(theta), y_of(s_along), z))

    bottom_half.append((x_at_gap, -half_gap, z_at_gap))
    top_half.append((a, a - r, z))
    return top_half, bottom_half, z_at_gap, x_at_gap


# Plan the right side -- initial polyline point depends on whether (and
# what kind of) fold straddles the gap.
right_top_pts, right_bottom_pts, z_at_gap, x_at_gap = plan_right_side()


# ============================================================
# Build the polyline
# ============================================================

points = []
segment_types = []

# Initial point: top of gap on the right side (x and z may be off-base)
points.append((x_at_gap, half_gap, z_at_gap))


def add_folded_side(start_xy, end_xy):
    fold_pts = alternating_folds_straight(start_xy, end_xy)
    for pt in fold_pts:
        points.append(pt)
        segment_types.append(("Line", len(points) - 2, 2))


def add_corner_arc(mid_xy, end_xy):
    points.append((mid_xy[0], mid_xy[1], z))
    points.append((end_xy[0], end_xy[1], z))
    segment_types.append(("Arc", len(points) - 3, 3))


def add_point_sequence(pt_list):
    for pt in pt_list:
        points.append(pt)
        segment_types.append(("Line", len(points) - 2, 2))


# Right side TOP half (pre-planned)
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
# Right side BOTTOM half (pre-planned)
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
# Port "TX" -- circuit port between the two edges at the gap
# ============================================================

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


trace_top_z = z_at_gap + TRACE_THICK_MM / 2.0
edge_top = _find_closest_edge(LOOP_NAME, x_at_gap, +half_gap, trace_top_z)
edge_bot = _find_closest_edge(LOOP_NAME, x_at_gap, -half_gap, trace_top_z)

if edge_top is None or edge_bot is None:
    raise Exception("Could not locate trace-end edges at the gap.")
if edge_top == edge_bot:
    raise Exception(
        "Same edge picked for both ends of the gap -- check the polyline.")

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

a_m = (LOOP_SIDE_MM - TRACE_WIDTH_MM) * 1e-3
wt_m = (TRACE_WIDTH_MM + TRACE_THICK_MM) * 1e-3
mu0 = 4e-7 * math.pi
L_flat_H = (2.0 * mu0 * a_m / math.pi) * (math.log(2.0 * a_m / wt_m) - 0.274)
L_flat_nH = L_flat_H * 1e9

# Fold breakdown
n_z_folds  = 4 * ((FOLDS_PER_SIDE + 1) // 2)   # ceil(N/2) per side, 4 sides
n_2d_folds = 4 * (FOLDS_PER_SIDE // 2)         # floor(N/2) per side, 4 sides

# Wire added by each fold type
added_z_wire_mm  = n_z_folds  * 2.0 * FOLD_HEIGHT_MM
# Half-ellipse arc minus chord: Ramanujan approx for arc length
if FOLD_HEIGHT_MM > 0:
    arc_each = math.pi * math.sqrt(((FOLD_LENGTH_MM / 2.0) ** 2 + FOLD_HEIGHT_MM ** 2) / 2.0)
    added_2d_wire_mm = n_2d_folds * (arc_each - FOLD_LENGTH_MM)
else:
    added_2d_wire_mm = 0.0

dir_word = "outward" if INPLANE_FOLD_DIRECTION > 0 else "inward"

oDesktop.AddMessage("", "", 0,
    "FoldedSquareLoopV2 built. side=%.1fmm  z=%.1fmm. %d Z-folds (+%.1fmm "
    "wire) + %d 2D-folds (%s, +%.1fmm wire). Circuit port 'TX' at "
    "(x=%.3f, y=+/-%.2f, z=%.2f, 50 ohm). Flat-loop Greenhouse L ~ %.1f nH."
    % (LOOP_SIDE_MM, LOOP_Z_MM,
       n_z_folds, added_z_wire_mm,
       n_2d_folds, dir_word, added_2d_wire_mm,
       x_at_gap, half_gap, z_at_gap, L_flat_nH))

oEditor.FitAll()
