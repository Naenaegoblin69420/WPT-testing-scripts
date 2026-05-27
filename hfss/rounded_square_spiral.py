import ScriptEnv
import math

# ============================================================
# Connect to AEDT / HFSS
# ============================================================

ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
oDesktop.RestoreWindow()

oProject = oDesktop.GetActiveProject()
oDesign = oProject.GetActiveDesign()
oEditor = oDesign.SetActiveEditor("3D Modeler")

# ============================================================
# Tunable coil parameters
# All dimensions are in mm
# ============================================================

coil_name = "Rounded_Square_Spiral"

N = 4                    # number of turns
outer_side = 20.0        # outer side length of coil
trace_width = 0.1        # metal trace width (JLCPCB 4-mil premium minimum)
spacing = 1.0            # spacing between adjacent turns
thickness = 0.035        # metal thickness (1 oz Cu = 35 um, JLCPCB default)
corner_radius = 1.5      # centerline corner radius
z_pos = 11.0             # z-position of coil (matches the rest of the WPT setup)

material = "copper"

# Number of points used to approximate each rounded corner
# Higher = smoother but slower simulation/modeling
arc_points = 10

# ============================================================
# Port + bridge parameters (3-D bridge brings the inner-spiral end
# out to a small pad next to the outer-spiral end so the TX circuit
# port can sit across a clean 1 mm gap, just like in petal_square_loop.py)
# ============================================================

port_name      = "TX"
port_impedance = 50.0      # ohm
gap_mm         = 1.0       # gap between the outer spiral end and the bridge pad
bridge_height  = 0.5       # mm above z_pos for the bridge over-pass

# ============================================================
# Derived parameters
# ============================================================

pitch = trace_width + spacing

# Centerline outer half-side
half_side = outer_side / 2.0 - trace_width / 2.0

# Total number of straight spiral segments
# Four segments per turn
num_segments = 4 * N

# Safety check
last_length = 2.0 * half_side - ((num_segments - 1) / 2) * pitch

if last_length <= trace_width:
    raise Exception("Invalid geometry: too many turns, too much spacing, or outer_side too small.")

if corner_radius <= 0:
    raise Exception("corner_radius must be positive.")

# ============================================================
# Helper functions
# ============================================================

def dist(p1, p2):
    return math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)

def normalize(v):
    mag = math.sqrt(v[0]**2 + v[1]**2)
    if mag == 0:
        return (0.0, 0.0)
    return (v[0] / mag, v[1] / mag)

def remove_duplicate_points(points, tol):
    clean = []
    for p in points:
        if len(clean) == 0:
            clean.append(p)
        else:
            if dist(clean[-1], p) > tol:
                clean.append(p)
    return clean

# ============================================================
# Generate sharp square spiral centerline first
# This creates a normal square spiral path.
# Then we round the corners afterward.
# ============================================================

raw_points = []

# Start at outer top-left corner of centerline
x = -half_side
y = half_side
raw_points.append((x, y, z_pos))

# Directions: right, down, left, up
directions = [
    (1.0, 0.0),
    (0.0, -1.0),
    (-1.0, 0.0),
    (0.0, 1.0)
]

for i in range(num_segments):
    direction = directions[i % 4]

    # Length decreases every two segments
    length = 2.0 * half_side - (i // 2) * pitch

    if length <= 0:
        break

    x = x + direction[0] * length
    y = y + direction[1] * length

    raw_points.append((x, y, z_pos))

# ============================================================
# Round / fillet the corners
# ============================================================

rounded_points = []

# Add first point
rounded_points.append(raw_points[0])

for i in range(1, len(raw_points) - 1):
    p0 = raw_points[i - 1]
    p1 = raw_points[i]
    p2 = raw_points[i + 1]

    len_in = dist(p0, p1)
    len_out = dist(p1, p2)

    # Limit radius so it does not exceed nearby segment lengths
    r = min(corner_radius, 0.45 * len_in, 0.45 * len_out)

    if r <= 0:
        rounded_points.append(p1)
        continue

    d_in = normalize((p1[0] - p0[0], p1[1] - p0[1]))
    d_out = normalize((p2[0] - p1[0], p2[1] - p1[1]))

    # Point before corner
    pA = (
        p1[0] - d_in[0] * r,
        p1[1] - d_in[1] * r,
        z_pos
    )

    # Point after corner
    pB = (
        p1[0] + d_out[0] * r,
        p1[1] + d_out[1] * r,
        z_pos
    )

    # Arc center for 90-degree fillet
    center = (
        p1[0] - d_in[0] * r + d_out[0] * r,
        p1[1] - d_in[1] * r + d_out[1] * r
    )

    rounded_points.append(pA)

    angle_A = math.atan2(pA[1] - center[1], pA[0] - center[0])
    angle_B = math.atan2(pB[1] - center[1], pB[0] - center[0])

    # Determine turn direction
    cross = d_in[0] * d_out[1] - d_in[1] * d_out[0]

    if cross < 0:
        # Clockwise turn
        if angle_B > angle_A:
            angle_B = angle_B - 2.0 * math.pi
    else:
        # Counterclockwise turn
        if angle_B < angle_A:
            angle_B = angle_B + 2.0 * math.pi

    # Add points along arc
    for j in range(1, arc_points + 1):
        t = float(j) / float(arc_points)
        angle = angle_A + t * (angle_B - angle_A)

        px = center[0] + r * math.cos(angle)
        py = center[1] + r * math.sin(angle)

        rounded_points.append((px, py, z_pos))

# Add final point
rounded_points.append(raw_points[-1])

# Clean duplicate points
rounded_points = remove_duplicate_points(rounded_points, 1e-6)

# ============================================================
# Convert points into HFSS polyline format
# ============================================================

polyline_points = ["NAME:PolylinePoints"]

for p in rounded_points:
    polyline_points.append([
        "NAME:PLPoint",
        "X:=", str(p[0]) + "mm",
        "Y:=", str(p[1]) + "mm",
        "Z:=", str(p[2]) + "mm"
    ])

segments = ["NAME:PolylineSegments"]

for i in range(len(rounded_points) - 1):
    segments.append([
        "NAME:PLSegment",
        "SegmentType:=", "Line",
        "StartIndex:=", i,
        "NoOfPoints:=", 2
    ])

xsection = [
    "NAME:PolylineXSection",
    "XSectionType:=", "Rectangle",
    "XSectionOrient:=", "Auto",
    "XSectionWidth:=", str(trace_width) + "mm",
    "XSectionTopWidth:=", str(trace_width) + "mm",
    "XSectionHeight:=", str(thickness) + "mm",
    "XSectionNumSegments:=", "0",
    "XSectionBendType:=", "Corner"
]

polyline_params = [
    "NAME:PolylineParameters",
    "IsPolylineCovered:=", False,
    "IsPolylineClosed:=", False,
    polyline_points,
    segments,
    xsection
]

attributes = [
    "NAME:Attributes",
    "Name:=", coil_name,
    "Flags:=", "",
    "Color:=", "(255 128 0)",
    "Transparency:=", 0,
    "PartCoordinateSystem:=", "Global",
    "MaterialValue:=", "\"" + material + "\"",
    "SolveInside:=", True
]

# ============================================================
# Create the rounded square spiral coil
# ============================================================

oEditor.CreatePolyline(polyline_params, attributes)


# ============================================================
# 3-D bridge from the inner spiral end out to a pad next to the
# outer spiral end, so the TX circuit port can sit across a
# clean ~1 mm gap (rather than spanning the whole coil diameter).
# ============================================================

# Polyline endpoints
outer_end = rounded_points[0]   # (-half_side, +half_side, z_pos), going +x at the start
inner_end = rounded_points[-1]  # whatever (x, y) the spiral terminates at

ox, oy, _ = outer_end
ix, iy, _ = inner_end

# Bridge pad sits one gap to the LEFT of the outer end, same y, same z
pad_x = ox - gap_mm
pad_y = oy
bridge_z = z_pos + bridge_height + thickness / 2.0

# ----- Via UP at the inner end (small Cu box from z_pos to z_pos+bridge_height+thickness) -----
via_in_name = coil_name + "_via_in"
oEditor.CreateBox(
    [
        "NAME:BoxParameters",
        "XPosition:=", str(ix - trace_width / 2.0) + "mm",
        "YPosition:=", str(iy - trace_width / 2.0) + "mm",
        "ZPosition:=", str(z_pos) + "mm",
        "XSize:=",     str(trace_width) + "mm",
        "YSize:=",     str(trace_width) + "mm",
        "ZSize:=",     str(bridge_height + thickness) + "mm",
    ],
    [
        "NAME:Attributes",
        "Name:=",                 via_in_name,
        "Flags:=",                "",
        "Color:=",                "(0 128 255)",
        "Transparency:=",         0,
        "PartCoordinateSystem:=", "Global",
        "MaterialValue:=",        "\"" + material + "\"",
        "SolveInside:=",          True,
    ],
)

# ----- Horizontal bridge wire at z = bridge_z, from inner end to the pad position -----
bridge_name = coil_name + "_bridge"
bridge_pl_pts = ["NAME:PolylinePoints"]
for p in [(ix, iy, bridge_z), (pad_x, pad_y, bridge_z)]:
    bridge_pl_pts.append([
        "NAME:PLPoint",
        "X:=", str(p[0]) + "mm",
        "Y:=", str(p[1]) + "mm",
        "Z:=", str(p[2]) + "mm",
    ])
bridge_pl_segs = ["NAME:PolylineSegments"]
bridge_pl_segs.append([
    "NAME:PLSegment",
    "SegmentType:=", "Line",
    "StartIndex:=",  0,
    "NoOfPoints:=",  2,
])
bridge_xsec = [
    "NAME:PolylineXSection",
    "XSectionType:=",        "Rectangle",
    "XSectionOrient:=",      "Auto",
    "XSectionWidth:=",       str(trace_width) + "mm",
    "XSectionTopWidth:=",    str(trace_width) + "mm",
    "XSectionHeight:=",      str(thickness) + "mm",
    "XSectionNumSegments:=", "0",
    "XSectionBendType:=",    "Corner",
]
oEditor.CreatePolyline(
    [
        "NAME:PolylineParameters",
        "IsPolylineCovered:=", False,
        "IsPolylineClosed:=",  False,
        bridge_pl_pts,
        bridge_pl_segs,
        bridge_xsec,
    ],
    [
        "NAME:Attributes",
        "Name:=",                 bridge_name,
        "Flags:=",                "",
        "Color:=",                "(0 128 255)",
        "Transparency:=",         0,
        "PartCoordinateSystem:=", "Global",
        "MaterialValue:=",        "\"" + material + "\"",
        "SolveInside:=",          True,
    ],
)

# ----- Via DOWN at the pad position -----
via_out_name = coil_name + "_via_out"
oEditor.CreateBox(
    [
        "NAME:BoxParameters",
        "XPosition:=", str(pad_x - trace_width / 2.0) + "mm",
        "YPosition:=", str(pad_y - trace_width / 2.0) + "mm",
        "ZPosition:=", str(z_pos) + "mm",
        "XSize:=",     str(trace_width) + "mm",
        "YSize:=",     str(trace_width) + "mm",
        "ZSize:=",     str(bridge_height + thickness) + "mm",
    ],
    [
        "NAME:Attributes",
        "Name:=",                 via_out_name,
        "Flags:=",                "",
        "Color:=",                "(0 128 255)",
        "Transparency:=",         0,
        "PartCoordinateSystem:=", "Global",
        "MaterialValue:=",        "\"" + material + "\"",
        "SolveInside:=",          True,
    ],
)


# ============================================================
# TX circuit port between the outer-end edge and the pad edge
# (closest-distance edge search, same pattern as petal_square_loop.py)
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


trace_top_z = z_pos + thickness / 2.0
# Edge on the spiral right at its outer terminal face (x = -half_side, y = +half_side)
edge_spiral = _find_closest_edge(coil_name, ox, oy, trace_top_z)
# Edge on the pad's +x face (the side closest to the spiral terminal)
edge_pad    = _find_closest_edge(via_out_name,
                                 pad_x + trace_width / 2.0, pad_y, trace_top_z)

if edge_spiral is None or edge_pad is None or edge_spiral == edge_pad:
    raise Exception(
        "Couldn't locate two distinct edges for the TX port "
        "(spiral edge = %s, pad edge = %s)." % (edge_spiral, edge_pad))

oBoundary = oDesign.GetModule("BoundarySetup")
oBoundary.AssignCircuitPort([
    "NAME:" + port_name,
    "Edges:=",                   [int(edge_spiral), int(edge_pad)],
    "Impedance:=",               str(port_impedance) + "ohm",
    "DoDeembed:=",               False,
    "RenormalizeAllTerminals:=", True,
])

oDesktop.AddMessage("", "", 0,
    "Rounded_Square_Spiral built. N=%d turns, outer=%.1fmm, W=%.3fmm, "
    "T=%.3fmm, z=%.1fmm. TX circuit port assigned across %0.1fmm gap "
    "at the outer-top-left corner."
    % (N, outer_side, trace_width, thickness, z_pos, gap_mm))

oEditor.FitAll()