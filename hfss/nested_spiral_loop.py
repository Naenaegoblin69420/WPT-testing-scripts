# IronPython 2.7 script for HFSS (Automation -> Run Script)
#
# Builds an N-turn nested rounded-square spiral, with each ring spaced
# RING_SPACING_MM apart (centre-line to centre-line) instead of the
# usual W+s tight pitch. All turns are traced counter-clockwise so the
# current direction is the same in every ring -- this minimises the
# anti-parallel inter-turn current pattern that drives up parasitic
# inter-turn capacitance in tightly-packed spirals.
#
# Topology:
#   * Each ring has its own 1 mm gap on the right side at y = 0.
#   * The polyline starts at the TOP of the OUTER ring's gap, traces
#     the outer ring CCW (right-up, top, left-down, bottom), and ends
#     at the BOTTOM of the outer ring's gap.
#   * A short DIAGONAL jumper from the bottom of ring k's gap to the
#     top of ring k+1's gap drops the trace radially inward by
#     RING_SPACING_MM while flipping y from -half_gap to +half_gap.
#   * Each inner ring is then traced CCW the same way, ending at its
#     own bottom-of-gap, and so on for all N rings.
#   * The polyline's two open ends are:
#         TERMINAL A = (a_outer,    +half_gap, z)   -- outermost top-of-gap
#         TERMINAL B = (a_innermost, -half_gap, z)  -- innermost bottom-of-gap
#   * A TX circuit port is assigned between one edge at each terminal.
#     (HFSS lets circuit ports span edges that aren't physically adjacent;
#     the network impedance comes out fine for inductive structures, and
#     it spares us a 3-D over-pass bridge.)
#
# All knobs are at the top of the file. Edit, save, re-run.
# This script ONLY makes the loop body + the port. The air region and
# radiation boundary are still up to you to create once manually.

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

LOOP_SIDE_MM     = 30.0    # outer side length of the outermost ring
N_TURNS          = 2       # number of nested rings (turns)
RING_SPACING_MM  = 4.0     # centre-line spacing between adjacent rings
TRACE_WIDTH_MM   = 0.10
TRACE_THICK_MM   = 0.035   # copper thickness (35 um = 1 oz Cu)
CORNER_RADIUS_MM = 3.0     # inside fillet radius on every ring
GAP_MM           = 1.0     # gap on each ring's right side (also the port gap)
LOOP_Z_MM        = 11.0    # z plane the spiral sits in

PORT_NAME        = "TX"
PORT_IMPEDANCE   = 50.0    # ohm

MATERIAL  = "copper"
LOOP_NAME = "NestedSpiralLoop"


# ============================================================
# Derived constants + sanity checks
# ============================================================

a_outer  = LOOP_SIDE_MM / 2.0 - TRACE_WIDTH_MM / 2.0   # outer ring centre-line half-side
half_gap = GAP_MM / 2.0
r        = CORNER_RADIUS_MM
r2       = r / math.sqrt(2.0)                          # arc midpoint offset
z        = LOOP_Z_MM

if N_TURNS < 1:
    raise Exception("N_TURNS must be >= 1.")
if r <= TRACE_WIDTH_MM / 2.0:
    raise Exception("CORNER_RADIUS_MM (%s) must exceed half the trace width."
                    % r)
if RING_SPACING_MM <= TRACE_WIDTH_MM:
    raise Exception(
        "RING_SPACING_MM (%s) must exceed TRACE_WIDTH_MM (%s) so the rings "
        "don't touch. Aim for at least 2 * TRACE_WIDTH (more is better for "
        "low inter-turn capacitance)." % (RING_SPACING_MM, TRACE_WIDTH_MM))
if GAP_MM <= 0:
    raise Exception("GAP_MM must be positive.")

# Innermost ring must still have positive size and fit its corner arcs + gap
a_innermost = a_outer - (N_TURNS - 1) * RING_SPACING_MM
if a_innermost <= r + half_gap:
    raise Exception(
        "Innermost ring's half-side (%.3f mm) <= corner radius + half gap "
        "(%.3f mm). Reduce N_TURNS, reduce RING_SPACING_MM, reduce "
        "CORNER_RADIUS_MM, or grow LOOP_SIDE_MM."
        % (a_innermost, r + half_gap))


# ============================================================
# Path for ONE ring (CCW from its top-of-gap to its bottom-of-gap)
# ============================================================
# Returns 14 points and the corresponding 9 segments (Line / Arc / ...),
# expressed as a list of (kind, n_points_consumed) tuples that the caller
# will turn into "Line"/"Arc" entries with the right StartIndex.

RING_POINT_COUNT = 14   # one ring contributes this many polyline points
RING_SEGMENT_COUNT = 9


def ring_points(a_k):
    """14 polyline points along ring k, CCW, top-of-gap -> bottom-of-gap."""
    pts = [
        (a_k,              half_gap,         z),   # 0  top of gap (start)
        (a_k,              a_k - r,          z),   # 1  end of right-up straight
        (a_k - r + r2,     a_k - r + r2,     z),   # 2  TR arc midpoint
        (a_k - r,          a_k,              z),   # 3  end of TR arc
        (-a_k + r,         a_k,              z),   # 4  start of TL arc
        (-a_k + r - r2,    a_k - r + r2,     z),   # 5  TL arc midpoint
        (-a_k,             a_k - r,          z),   # 6  end of TL arc
        (-a_k,             -a_k + r,         z),   # 7  start of BL arc
        (-a_k + r - r2,    -a_k + r - r2,    z),   # 8  BL arc midpoint
        (-a_k + r,         -a_k,             z),   # 9  end of BL arc
        (a_k - r,          -a_k,             z),   # 10 start of BR arc
        (a_k - r + r2,     -a_k + r - r2,    z),   # 11 BR arc midpoint
        (a_k,              -a_k + r,         z),   # 12 end of BR arc
        (a_k,              -half_gap,        z),   # 13 bottom of gap (end)
    ]
    return pts


# Segment shape relative to the ring's first point index N0:
#   ("Line", N0 + 0, 2)    # 0 -> 1
#   ("Arc",  N0 + 1, 3)    # 1 -> 2 -> 3
#   ("Line", N0 + 3, 2)    # 3 -> 4
#   ("Arc",  N0 + 4, 3)    # 4 -> 5 -> 6
#   ("Line", N0 + 6, 2)    # 6 -> 7
#   ("Arc",  N0 + 7, 3)    # 7 -> 8 -> 9
#   ("Line", N0 + 9, 2)    # 9 -> 10
#   ("Arc",  N0 + 10, 3)   # 10 -> 11 -> 12
#   ("Line", N0 + 12, 2)   # 12 -> 13
_RING_SEG_TEMPLATE = [
    ("Line",  0, 2),
    ("Arc",   1, 3),
    ("Line",  3, 2),
    ("Arc",   4, 3),
    ("Line",  6, 2),
    ("Arc",   7, 3),
    ("Line",  9, 2),
    ("Arc",  10, 3),
    ("Line", 12, 2),
]


# ============================================================
# Build the polyline
# ============================================================

points = []
segment_types = []

for k in range(N_TURNS):
    a_k = a_outer - k * RING_SPACING_MM
    base_idx = len(points)

    if k == 0:
        # Outer ring: append all 14 points (no jumper before it -- it's
        # the start of the whole polyline)
        for p in ring_points(a_k):
            points.append(p)
    else:
        # Diagonal jumper from previous ring's bottom-of-gap to this
        # ring's top-of-gap. The previous ring's last point is at the
        # current polyline end; we just add the jumper's destination
        # (which is this ring's first point) and emit one Line segment
        # for the jumper.
        ring_pts = ring_points(a_k)
        # First point of this ring (= jumper endpoint = top-of-gap)
        points.append(ring_pts[0])
        # The jumper segment (Line) connects the previous ring's last
        # point (at base_idx - 1) to this new point (at base_idx).
        segment_types.append(("Line", base_idx - 1, 2))
        # Then the rest of the ring's points
        for p in ring_pts[1:]:
            points.append(p)
        # Update base_idx to point at this ring's first point
        # (which we just added)
        # base_idx already equals len(points) before this ring's first
        # point was appended; we used base_idx above for that append.

    # Emit the 9 segments for this ring, offset by base_idx
    for kind, off, npts in _RING_SEG_TEMPLATE:
        segment_types.append((kind, base_idx + off, npts))


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

segments_arg = ["NAME:PolylineSegments"]
for stype, start_idx, n_pts in segment_types:
    segments_arg.append([
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
    segments_arg,
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
# TX circuit port -- one edge on the outermost top-of-gap, one on the
# innermost bottom-of-gap (the polyline's two open ends)
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


trace_top_z = LOOP_Z_MM + TRACE_THICK_MM / 2.0
edge_outer_top = _find_closest_edge(LOOP_NAME,
                                    a_outer,    +half_gap, trace_top_z)
edge_inner_bot = _find_closest_edge(LOOP_NAME,
                                    a_innermost, -half_gap, trace_top_z)

if edge_outer_top is None or edge_inner_bot is None:
    raise Exception("Could not locate the two terminal edges for the port.")
if edge_outer_top == edge_inner_bot:
    raise Exception(
        "Outer-top and innermost-bot resolved to the same edge -- check "
        "that the polyline actually has two distinct open ends.")

oBoundary = oDesign.GetModule("BoundarySetup")
oBoundary.AssignCircuitPort([
    "NAME:" + PORT_NAME,
    "Edges:=",                   [int(edge_outer_top), int(edge_inner_bot)],
    "Impedance:=",               "%fohm" % PORT_IMPEDANCE,
    "DoDeembed:=",               False,
    "RenormalizeAllTerminals:=", True,
])


# ============================================================
# Summary into the Message Manager
# ============================================================

# Rough perimeter (centre-line) for the whole spiral
perim_per_ring = lambda a_k: (3 * (2 * a_k - 2 * r)            # three full sides
                               + (2 * (a_k - r) - GAP_MM)       # right side minus gap
                               + 4 * (math.pi / 2.0) * r)       # four arcs
total_centerline_mm = 0.0
for k in range(N_TURNS):
    total_centerline_mm += perim_per_ring(a_outer - k * RING_SPACING_MM)
# Plus the jumpers between rings (diagonal length each)
jumper_mm_each = math.sqrt(RING_SPACING_MM ** 2 + GAP_MM ** 2)
total_centerline_mm += (N_TURNS - 1) * jumper_mm_each

oDesktop.AddMessage("", "", 0,
    "NestedSpiralLoop built. N_TURNS=%d  outer_side=%.1fmm  "
    "ring_spacing=%.1fmm  innermost_side=%.1fmm. Centre-line wire "
    "length ~ %.1fmm (rings %.1fmm + %d jumpers of %.2fmm). "
    "TX circuit port assigned between outer top-of-gap and innermost "
    "bottom-of-gap (50 ohm)."
    % (N_TURNS,
       LOOP_SIDE_MM,
       RING_SPACING_MM,
       2 * a_innermost + TRACE_WIDTH_MM,
       total_centerline_mm,
       total_centerline_mm - (N_TURNS - 1) * jumper_mm_each,
       N_TURNS - 1, jumper_mm_each))

oEditor.FitAll()
