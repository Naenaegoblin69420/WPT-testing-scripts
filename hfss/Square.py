"""
HFSS / PyAEDT script:
Create a centered rounded-square single-turn loop with a 1 mm gap.

Geometry:
- Centered at origin
- Lies in XY plane
- Thickened in +Z
- Gap is centered on the +X side
- Rounded outer/inner corners
- Copper material

Requires:
    pip install pyaedt

Run from a Python environment that can launch/connect to Ansys Electronics Desktop.
"""

import math
from ansys.aedt.core import Hfss


# ----------------------------
# User parameters
# ----------------------------
project_name = "Rounded_Square_Loop_Project"
design_name = "Rounded_Square_Loop_HFSS"

length_size = 20.0      # mm, outer side length of square loop
trace_width = 1.0       # mm, conductor trace width
thickness = 0.035       # mm, copper thickness, e.g. 35 um = 0.035 mm
gap = 1.0               # mm, physical break in loop
corner_radius = 2.0     # mm, outer corner radius
material = "copper"

# Polygon resolution for rounded corners
arc_points = 18


# ----------------------------
# Safety checks
# ----------------------------
if trace_width <= 0:
    raise ValueError("trace_width must be > 0")

if thickness <= 0:
    raise ValueError("thickness must be > 0")

if length_size <= 2 * trace_width:
    raise ValueError("length_size must be larger than 2*trace_width")

if gap <= 0:
    raise ValueError("gap must be > 0")

if gap >= length_size - 2 * corner_radius:
    raise ValueError("gap is too large for the straight section on the +X side")

if corner_radius <= 0:
    raise ValueError("corner_radius must be > 0")

if corner_radius >= length_size / 2:
    raise ValueError("corner_radius must be less than length_size/2")

inner_radius = corner_radius - trace_width

if inner_radius <= 0:
    raise ValueError(
        "corner_radius must be larger than trace_width so the inner rounded corner is valid"
    )


# ----------------------------
# Helper functions
# ----------------------------
def arc_points_xy(cx, cy, r, start_deg, end_deg, n):
    """
    Return points along an arc in XY plane.
    Angles in degrees.
    """
    pts = []
    for i in range(n + 1):
        a = math.radians(start_deg + (end_deg - start_deg) * i / n)
        pts.append([cx + r * math.cos(a), cy + r * math.sin(a), 0])
    return pts


def rounded_rect_points(side, radius, n=16, clockwise=True):
    """
    Generate closed rounded-rectangle boundary points centered at origin.

    side: outer or inner side length
    radius: corner radius
    clockwise: point orientation
    """
    h = side / 2.0
    r = radius

    # Corner centers
    tr = [h - r, h - r]
    tl = [-(h - r), h - r]
    bl = [-(h - r), -(h - r)]
    br = [h - r, -(h - r)]

    if clockwise:
        # Start on +X side near top, move clockwise
        pts = []
        pts += arc_points_xy(tr[0], tr[1], r, 0, -90, n)
        pts += arc_points_xy(br[0], br[1], r, 0, -90, n)  # will be overwritten below
    else:
        pts = []

    # Easier: create CCW then reverse if needed.
    # CCW path:
    pts_ccw = []
    # Top-right corner: 0 to 90
    pts_ccw += arc_points_xy(tr[0], tr[1], r, 0, 90, n)
    # Top-left: 90 to 180
    pts_ccw += arc_points_xy(tl[0], tl[1], r, 90, 180, n)
    # Bottom-left: 180 to 270
    pts_ccw += arc_points_xy(bl[0], bl[1], r, 180, 270, n)
    # Bottom-right: 270 to 360
    pts_ccw += arc_points_xy(br[0], br[1], r, 270, 360, n)

    if clockwise:
        return list(reversed(pts_ccw))
    return pts_ccw


def remove_gap_on_positive_x(points, gap_mm):
    """
    Remove points/segments near the +X side center to create a gap.
    This assumes the boundary is a rounded rectangle centered at origin.

    For a ring sheet, we will use Boolean subtraction with a rectangular
    gap cutter instead, which is more reliable. This helper is unused but
    kept for clarity.
    """
    return points


# ----------------------------
# Launch/connect to HFSS
# ----------------------------
hfss = Hfss(
    project=project_name,
    design=design_name,
    solution_type="DrivenModal",
    new_desktop=True,
    non_graphical=False,
)

hfss.modeler.model_units = "mm"


# ----------------------------
# Create rounded outer and inner sheets
# ----------------------------
outer_side = length_size
inner_side = length_size - 2 * trace_width

outer_pts = rounded_rect_points(outer_side, corner_radius, arc_points, clockwise=False)
inner_pts = rounded_rect_points(inner_side, inner_radius, arc_points, clockwise=False)

# Create outer filled sheet
outer_poly = hfss.modeler.create_polyline(
    points=outer_pts,
    close_surface=True,
    cover_surface=True,
    name="outer_rounded_square",
    material=material,
)

# Create inner filled sheet
inner_poly = hfss.modeler.create_polyline(
    points=inner_pts,
    close_surface=True,
    cover_surface=True,
    name="inner_cutout",
    material=material,
)

# Subtract inner sheet from outer sheet to make the trace ring
hfss.modeler.subtract(
    blank_list=[outer_poly.name],
    tool_list=[inner_poly.name],
    keep_originals=False,
)

loop_sheet_name = outer_poly.name


# ----------------------------
# Create the 1 mm gap on +X side
# ----------------------------
# Gap centered at x = +length_size/2, y = 0.
# Cutter is slightly larger than trace width to ensure it cuts through the full trace.
gap_cutter_x = length_size / 2 - trace_width * 1.5
gap_cutter_y = -gap / 2
gap_cutter_width_x = trace_width * 3.0
gap_cutter_width_y = gap

gap_cut = hfss.modeler.create_box(
    origin=[gap_cutter_x, gap_cutter_y, -thickness],
    sizes=[gap_cutter_width_x, gap_cutter_width_y, 3 * thickness],
    name="gap_cutter",
    material="vacuum",
)

# Subtract cutter from loop sheet/solid
hfss.modeler.subtract(
    blank_list=[loop_sheet_name],
    tool_list=[gap_cut.name],
    keep_originals=False,
)


# ----------------------------
# Thicken the sheet into a 3D conductor
# ----------------------------
loop_obj = hfss.modeler[loop_sheet_name]
hfss.modeler.thicken_sheet(loop_obj.name, thickness=f"{thickness}mm", both_sides=False)

# Rename final object if needed
try:
    hfss.modeler[loop_sheet_name].name = "rounded_square_loop_gap_1mm"
except Exception:
    pass


# ----------------------------
# Optional: assign material/color
# ----------------------------
try:
    hfss.modeler["rounded_square_loop_gap_1mm"].material_name = material
    hfss.modeler["rounded_square_loop_gap_1mm"].color = (255, 165, 0)
except Exception:
    pass


# ----------------------------
# Fit view and save
# ----------------------------
hfss.modeler.fit_all()
hfss.save_project()

print("Created centered rounded square loop with 1 mm gap.")
print(f"Outer side length: {length_size} mm")
print(f"Trace width:       {trace_width} mm")
print(f"Thickness:         {thickness} mm")
print(f"Gap:               {gap} mm")
print(f"Corner radius:     {corner_radius} mm")