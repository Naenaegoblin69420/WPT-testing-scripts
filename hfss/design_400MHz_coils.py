# IronPython 2.7 script for HFSS (Automation -> Run Script)
#
# WPT coil pair @ 400 MHz: primary + secondary square planar spirals,
# inner-end bridges, lumped circuit ports on both coils, optional ferrite
# back-concentrator on the primary, air region with radiation boundary,
# adaptive solve at 400 MHz + 50-800 MHz interpolating sweep, and output
# variables that compute L, R, M, k, Q from the open-circuit Z-matrix.
#
# Targets handed off from the Keysight ADS stage:
#                  Primary       Secondary
#   Inductance     120 nH        80 nH
#   Series R @400M 2.85 ohm      2 ohm
#   Coupling k                ~0.25  (stretch goal)
#   Vertical gap              = 11 mm  (fixed)
#   Secondary size           <= 10 mm x 10 mm
#   Conductor                 copper, 35 um (1 oz Cu)
#
# Usage:
#   1. Open / create an HFSS DrivenModal design.
#   2. Automation -> Run Script -> select this file.
#
# All knobs are at the top of the file: edit, save, re-run.

import ScriptEnv
import math

ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
oDesktop.RestoreWindow()

oProject = oDesktop.GetActiveProject()
oDesign  = oProject.GetActiveDesign()
oEditor  = oDesign.SetActiveEditor("3D Modeler")


# ============================================================
# Top-level parameters -- edit these and re-run
# ============================================================

# --- Frequency / global ---
FREQ_MHZ        = 400.0          # design + radiation-boundary frequency
SEPARATION_MM   = 11.0           # fixed primary-to-secondary vertical gap
PORT_IMPEDANCE  = 50.0           # ohm
PORT_GAP_MM     = 0.20           # gap across the lumped-port sheet
PAD_MM          = 30.0           # air-region padding around assembly
COND_MATERIAL   = "copper"

# --- Primary square planar spiral ---
PRI_D_OUT_MM      = 13.0         # outer side length
PRI_N_TURNS       = 2
PRI_TRACE_W_MM    = 0.10         # trace width
PRI_TRACE_S_MM    = 0.40         # inter-turn gap
PRI_TRACE_T_MM    = 0.035        # copper thickness (35 um = 1 oz Cu)
PRI_Z_BASE_MM     = 0.0          # bottom-of-trace z
PRI_BRIDGE_H_MM   = 0.5          # bridge above-spiral clearance
PRI_LEAD_LEN_MM   = 1.5

# --- Secondary square planar spiral ---
SEC_D_OUT_MM      = 8.5
SEC_N_TURNS       = 2
SEC_TRACE_W_MM    = 0.10
SEC_TRACE_S_MM    = 0.20
SEC_TRACE_T_MM    = 0.035
SEC_Z_BASE_MM     = SEPARATION_MM  # 11 mm above primary
SEC_BRIDGE_H_MM   = 0.5
SEC_LEAD_LEN_MM   = 1.5

# --- Ferrite back-concentrator (placed behind the primary) ---
FERRITE_ENABLED          = True
FERRITE_LATERAL_SIZE_MM  = 25.0
FERRITE_THICKNESS_MM     = 1.0
FERRITE_AIR_GAP_MM       = 0.10
FERRITE_MATERIAL_NAME    = "HF_Ferrite_400MHz"
FERRITE_MU_R             = 30.0
FERRITE_MAG_TAN_DELTA    = 0.10
FERRITE_EPS_R            = 12.0
FERRITE_DIEL_TAN_DELTA   = 0.001
FERRITE_CONDUCTIVITY     = 0.01     # NiZn ferrites are ~MOhm-cm

# --- Optional steps ---
ADD_AIR_REGION       = True
ADD_SOLUTION         = True
ADD_OUTPUT_VARIABLES = True


# ============================================================
# Helper: build COM arg lists for primitives + boundaries
# ============================================================

def _mm(v):
    return "%fmm" % v


def make_polyline(name, points, w_mm, t_mm, material="copper",
                  color="(255 128 0)"):
    """Create an open straight-segment polyline with rectangular cross-section."""
    polyline_points = ["NAME:PolylinePoints"]
    for p in points:
        polyline_points.append([
            "NAME:PLPoint",
            "X:=", _mm(p[0]),
            "Y:=", _mm(p[1]),
            "Z:=", _mm(p[2]),
        ])

    segments = ["NAME:PolylineSegments"]
    for i in range(len(points) - 1):
        segments.append([
            "NAME:PLSegment",
            "SegmentType:=", "Line",
            "StartIndex:=",  i,
            "NoOfPoints:=",  2,
        ])

    xsection = [
        "NAME:PolylineXSection",
        "XSectionType:=",        "Rectangle",
        "XSectionOrient:=",      "Auto",
        "XSectionWidth:=",       _mm(w_mm),
        "XSectionTopWidth:=",    _mm(w_mm),
        "XSectionHeight:=",      _mm(t_mm),
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
        "Name:=",                 name,
        "Flags:=",                "",
        "Color:=",                color,
        "Transparency:=",         0,
        "PartCoordinateSystem:=", "Global",
        "MaterialValue:=",        '"' + material + '"',
        "SolveInside:=",          True,
    ]

    oEditor.CreatePolyline(polyline_params, attributes)


def make_box(name, origin_xyz, sizes_xyz, material="copper",
             color="(0 128 255)"):
    """Create a copper box (used for vias, pads, ferrite slab)."""
    oEditor.CreateBox(
        [
            "NAME:BoxParameters",
            "XPosition:=", _mm(origin_xyz[0]),
            "YPosition:=", _mm(origin_xyz[1]),
            "ZPosition:=", _mm(origin_xyz[2]),
            "XSize:=",     _mm(sizes_xyz[0]),
            "YSize:=",     _mm(sizes_xyz[1]),
            "ZSize:=",     _mm(sizes_xyz[2]),
        ],
        [
            "NAME:Attributes",
            "Name:=",                 name,
            "Flags:=",                "",
            "Color:=",                color,
            "Transparency:=",         0,
            "PartCoordinateSystem:=", "Global",
            "MaterialValue:=",        '"' + material + '"',
            "SolveInside:=",          True,
        ],
    )


def make_rectangle_z(name, origin_xyz, width_x, height_y):
    """Create a rectangle in the XY plane (constant Z) for port sheets."""
    oEditor.CreateRectangle(
        [
            "NAME:RectangleParameters",
            "IsCovered:=", True,
            "XStart:=",    _mm(origin_xyz[0]),
            "YStart:=",    _mm(origin_xyz[1]),
            "ZStart:=",    _mm(origin_xyz[2]),
            "Width:=",     _mm(width_x),
            "Height:=",    _mm(height_y),
            "WhichAxis:=", "Z",
        ],
        [
            "NAME:Attributes",
            "Name:=",                 name,
            "Flags:=",                "",
            "Color:=",                "(255 0 0)",
            "Transparency:=",         0.5,
            "PartCoordinateSystem:=", "Global",
            "MaterialValue:=",        '"vacuum"',
            "SolveInside:=",          True,
        ],
    )


def assign_lumped_port(port_name, sheet_name, int_start_xyz, int_end_xyz,
                       impedance=50.0):
    oBoundary = oDesign.GetModule("BoundarySetup")
    oBoundary.AssignLumpedPort([
        "NAME:" + port_name,
        "Objects:=",                 [sheet_name],
        "RenormalizeAllTerminals:=", True,
        "DoDeembed:=",               False,
        [
            "NAME:Modes",
            [
                "NAME:Mode1",
                "ModeNum:=",      1,
                "UseIntLine:=",   True,
                [
                    "NAME:IntLine",
                    "Start:=", [_mm(int_start_xyz[0]),
                                _mm(int_start_xyz[1]),
                                _mm(int_start_xyz[2])],
                    "End:=",   [_mm(int_end_xyz[0]),
                                _mm(int_end_xyz[1]),
                                _mm(int_end_xyz[2])],
                ],
                "CharImp:=",        "Zpi",
                "AlignmentGroup:=", 0,
                "RenormImp:=",      "%fohm" % impedance,
            ],
        ],
        "ShowReporterFilter:=", False,
        "ReporterFilter:=",     [True],
        "Impedance:=",          "%fohm" % impedance,
    ])


def add_ferrite_material():
    """Register a custom isotropic ferrite material in the project library."""
    oDef = oProject.GetDefinitionManager()
    # If the material already exists from a prior run, skip; HFSS will
    # raise if we try to add a duplicate.
    try:
        oDef.AddMaterial([
            "NAME:" + FERRITE_MATERIAL_NAME,
            "CoordinateSystemType:=", "Cartesian",
            "BulkOrSurfaceType:=", 1,
            [
                "NAME:PhysicsTypes",
                "set:=", ["Electromagnetic"],
            ],
            "permittivity:=",            str(FERRITE_EPS_R),
            "dielectric_loss_tangent:=", str(FERRITE_DIEL_TAN_DELTA),
            "permeability:=",            str(FERRITE_MU_R),
            "magnetic_loss_tangent:=",   str(FERRITE_MAG_TAN_DELTA),
            "conductivity:=",            str(FERRITE_CONDUCTIVITY),
        ])
    except Exception:
        pass  # already exists


# ============================================================
# Spiral path generator (CCW, lead in +x, terminates at centre-bottom)
# ============================================================

def square_spiral_path(d_out_mm, n_turns, w_mm, s_mm, z, lead_length_mm):
    """Centre-line points of an N-turn CCW square spiral.

    The path starts with an outer lead stub in the +x direction at the
    bottom-right corner, traverses N turns CCW (stepping inward at the
    bottom-right corner of each turn), and ends with a short inner lead
    stub in the +y direction at the centre-bottom of the innermost turn.
    """
    a = d_out_mm / 2.0
    p = w_mm + s_mm
    half_w = w_mm / 2.0
    pts = []

    outer_x = a - half_w
    outer_y = -(a - half_w)
    pts.append((outer_x + lead_length_mm, outer_y, z))
    pts.append((outer_x,                   outer_y, z))

    for k in range(n_turns):
        r_k    = a - half_w - k * p
        r_next = a - half_w - (k + 1) * p
        pts.append(( r_k,  r_k, z))     # right side up
        pts.append((-r_k,  r_k, z))     # top left
        pts.append((-r_k, -r_k, z))     # left down
        if k < n_turns - 1:
            pts.append((r_next, -r_k, z))
        else:
            pts.append((0.0,    -r_k, z))

    inner_end_x, inner_end_y = pts[-1][0], pts[-1][1]
    pts.append((inner_end_x, inner_end_y + lead_length_mm / 2.0, z))
    return pts


# ============================================================
# Build one coil: spiral + bridge + pads + port sheet
# ============================================================

def build_coil(prefix, d_out_mm, n_turns, w_mm, s_mm, t_mm, z_base_mm,
               bridge_h_mm, lead_len_mm):
    z_centroid = z_base_mm + t_mm / 2.0
    pts = square_spiral_path(d_out_mm, n_turns, w_mm, s_mm,
                             z_centroid, lead_len_mm)

    # 1. Spiral as polyline
    spiral_name = prefix + "_spiral"
    make_polyline(spiral_name, pts, w_mm, t_mm, COND_MATERIAL)

    outer_terminal_xy = (pts[0][0], pts[0][1])
    inner_terminal_xy = (pts[-1][0], pts[-1][1])
    inner_x, inner_y = inner_terminal_xy

    bridge_z = z_base_mm + bridge_h_mm + t_mm / 2.0

    # 2. Via UP from spiral inner-lead tip
    via_in_name = prefix + "_via_in"
    make_box(
        via_in_name,
        origin_xyz=(inner_x - w_mm / 2.0,
                    inner_y - w_mm / 2.0,
                    z_base_mm + t_mm),
        sizes_xyz=(w_mm, w_mm, bridge_h_mm - t_mm / 2.0),
        material=COND_MATERIAL,
    )

    # 3. Bridge wire over the spiral, ending just above the outer pad
    bridge_end_x = outer_terminal_xy[0]
    bridge_end_y = outer_terminal_xy[1] + (PORT_GAP_MM + w_mm)
    bridge_pts = [
        (inner_x,      inner_y,      bridge_z),
        (bridge_end_x, inner_y,      bridge_z),
        (bridge_end_x, bridge_end_y, bridge_z),
    ]
    bridge_name = prefix + "_bridge"
    make_polyline(bridge_name, bridge_pts, w_mm, t_mm, COND_MATERIAL)

    # 4. Via DOWN at bridge end
    via_out_name = prefix + "_via_out"
    make_box(
        via_out_name,
        origin_xyz=(bridge_end_x - w_mm / 2.0,
                    bridge_end_y - w_mm / 2.0,
                    z_base_mm + t_mm),
        sizes_xyz=(w_mm, w_mm, bridge_h_mm - t_mm / 2.0),
        material=COND_MATERIAL,
    )

    # 5. Inner-end pad at z_base (the bridge-down landing pad)
    pad_w = w_mm * 2.0
    inner_pad_name = prefix + "_pad_inner"
    make_box(
        inner_pad_name,
        origin_xyz=(bridge_end_x - pad_w / 2.0,
                    bridge_end_y - w_mm / 2.0,
                    z_base_mm),
        sizes_xyz=(pad_w, w_mm, t_mm),
        material=COND_MATERIAL,
    )

    # 6. Outer-end pad at z_base (sits on the end of the outer lead)
    outer_pad_name = prefix + "_pad_outer"
    make_box(
        outer_pad_name,
        origin_xyz=(bridge_end_x - pad_w / 2.0,
                    outer_terminal_xy[1] - w_mm / 2.0,
                    z_base_mm),
        sizes_xyz=(pad_w, w_mm, t_mm),
        material=COND_MATERIAL,
    )

    # 7. Port sheet across the pad-to-pad gap
    sheet_x0 = bridge_end_x - pad_w / 2.0
    sheet_x1 = bridge_end_x + pad_w / 2.0
    sheet_y0 = outer_terminal_xy[1] + w_mm / 2.0
    sheet_y1 = bridge_end_y         - w_mm / 2.0
    sheet_z  = z_base_mm + t_mm / 2.0
    port_sheet_name = prefix + "_port_sheet"
    make_rectangle_z(
        port_sheet_name,
        origin_xyz=(sheet_x0, sheet_y0, sheet_z),
        width_x=sheet_x1 - sheet_x0,
        height_y=sheet_y1 - sheet_y0,
    )

    return {
        "port_sheet":      port_sheet_name,
        "port_int_start":  ((sheet_x0 + sheet_x1) / 2.0, sheet_y0, sheet_z),
        "port_int_end":    ((sheet_x0 + sheet_x1) / 2.0, sheet_y1, sheet_z),
    }


# ============================================================
# Main build sequence
# ============================================================

# 1. Custom ferrite material (must exist before the slab references it)
if FERRITE_ENABLED:
    add_ferrite_material()

# 2. Coils + bridges + pads + port sheets
primary_info = build_coil(
    "Primary",
    PRI_D_OUT_MM, PRI_N_TURNS, PRI_TRACE_W_MM, PRI_TRACE_S_MM,
    PRI_TRACE_T_MM, PRI_Z_BASE_MM, PRI_BRIDGE_H_MM, PRI_LEAD_LEN_MM,
)
secondary_info = build_coil(
    "Secondary",
    SEC_D_OUT_MM, SEC_N_TURNS, SEC_TRACE_W_MM, SEC_TRACE_S_MM,
    SEC_TRACE_T_MM, SEC_Z_BASE_MM, SEC_BRIDGE_H_MM, SEC_LEAD_LEN_MM,
)

# 3. Ferrite slab BEHIND the primary (in -z half-space)
if FERRITE_ENABLED:
    half = FERRITE_LATERAL_SIZE_MM / 2.0
    z_top    = PRI_Z_BASE_MM - FERRITE_AIR_GAP_MM
    z_bottom = z_top - FERRITE_THICKNESS_MM
    make_box(
        "Primary_FerriteSlab",
        origin_xyz=(-half, -half, z_bottom),
        sizes_xyz=(FERRITE_LATERAL_SIZE_MM,
                   FERRITE_LATERAL_SIZE_MM,
                   FERRITE_THICKNESS_MM),
        material=FERRITE_MATERIAL_NAME,
        color="(96 64 0)",
    )

# 4. Lumped ports
assign_lumped_port("Primary",   primary_info["port_sheet"],
                   primary_info["port_int_start"],
                   primary_info["port_int_end"],
                   PORT_IMPEDANCE)
assign_lumped_port("Secondary", secondary_info["port_sheet"],
                   secondary_info["port_int_start"],
                   secondary_info["port_int_end"],
                   PORT_IMPEDANCE)

# 5. Air region + radiation boundary
if ADD_AIR_REGION:
    pad_str = _mm(PAD_MM)
    oEditor.CreateRegion(
        [
            "NAME:RegionParameters",
            "+XPaddingType:=", "Absolute Offset",
            "+XPadding:=",     pad_str,
            "-XPaddingType:=", "Absolute Offset",
            "-XPadding:=",     pad_str,
            "+YPaddingType:=", "Absolute Offset",
            "+YPadding:=",     pad_str,
            "-YPaddingType:=", "Absolute Offset",
            "-YPadding:=",     pad_str,
            "+ZPaddingType:=", "Absolute Offset",
            "+ZPadding:=",     pad_str,
            "-ZPaddingType:=", "Absolute Offset",
            "-ZPadding:=",     pad_str,
        ],
        [
            "NAME:Attributes",
            "Name:=",                 "Region",
            "Flags:=",                "Wireframe#",
            "Color:=",                "(143 175 143)",
            "Transparency:=",         1,
            "PartCoordinateSystem:=", "Global",
            "MaterialValue:=",        '"vacuum"',
            "SolveInside:=",          True,
        ],
    )
    region_faces = oEditor.GetFaceIDs("Region")
    oBoundary = oDesign.GetModule("BoundarySetup")
    oBoundary.AssignRadiation([
        "NAME:Rad1",
        "Faces:=",          region_faces,
        "IsFssReference:=", False,
        "IsForPML:=",       False,
    ])

# 6. Adaptive setup + interpolating sweep
if ADD_SOLUTION:
    oAnalysis = oDesign.GetModule("AnalysisSetup")
    oAnalysis.InsertSetup("HfssDriven", [
        "NAME:Setup_400MHz",
        "Frequency:=",              "%fMHz" % FREQ_MHZ,
        "MaxDeltaS:=",              0.01,
        "MaximumPasses:=",          20,
        "MinimumPasses:=",          2,
        "MinimumConvergedPasses:=", 2,
        "PercentRefinement:=",      30,
        "IsEnabled:=",              True,
        "BasisOrder:=",             1,
        "DoLambdaRefine:=",         True,
        "DoMaterialLambda:=",       True,
        "SetLambdaTarget:=",        False,
        "Target:=",                 0.3333,
        "UseMaxTetIncrease:=",      False,
    ])
    oAnalysis.InsertFrequencySweep("Setup_400MHz", [
        "NAME:Sweep_50_to_800",
        "IsEnabled:=",          True,
        "RangeType:=",          "LinearCount",
        "RangeStart:=",         "50MHz",
        "RangeEnd:=",           "800MHz",
        "RangeCount:=",         151,
        "Type:=",               "Interpolating",
        "SaveFields:=",         False,
        "SaveRadFields:=",      False,
        "InterpTolerance:=",    0.5,
        "InterpMaxSolns:=",     250,
        "InterpMinSolns:=",     0,
        "InterpMinSubranges:=", 1,
    ])

# 7. Output variables for L, R, M, k, Q derived from the Z-matrix
if ADD_OUTPUT_VARIABLES and ADD_SOLUTION:
    oOutputVariable = oDesign.GetModule("OutputVariable")
    solution = "Setup_400MHz : LastAdaptive"
    omega = "(2*pi*Freq)"
    output_defs = [
        ("L1_nH",       "im(Z(Primary,Primary)) / " + omega + " * 1e9"),
        ("L2_nH",       "im(Z(Secondary,Secondary)) / " + omega + " * 1e9"),
        ("M_nH",        "im(Z(Primary,Secondary)) / " + omega + " * 1e9"),
        ("R1_ohm",      "re(Z(Primary,Primary))"),
        ("R2_ohm",      "re(Z(Secondary,Secondary))"),
        ("k_coupling", ("im(Z(Primary,Secondary)) / "
                        "sqrt(im(Z(Primary,Primary)) * "
                        "im(Z(Secondary,Secondary)))")),
        ("Q1_unloaded", "im(Z(Primary,Primary)) / re(Z(Primary,Primary))"),
        ("Q2_unloaded", ("im(Z(Secondary,Secondary)) / "
                         "re(Z(Secondary,Secondary))")),
        ("ImZ11",       "im(Z(Primary,Primary))"),
        ("ImZ22",       "im(Z(Secondary,Secondary))"),
    ]
    for var_name, expr in output_defs:
        try:
            oOutputVariable.CreateOutputVariable(
                var_name, expr, solution, "Modal Solution Data", [])
        except Exception as ex:
            oDesktop.AddMessage("", "", 1,
                "Could not create output variable " + var_name + ": " + str(ex))


# ============================================================
# Wrap-up
# ============================================================

oEditor.FitAll()

msg = "WPT coil pair built: primary + secondary spirals, bridges, ports"
if FERRITE_ENABLED:
    msg = msg + ", ferrite slab (mu_r=%.0f)" % FERRITE_MU_R
if ADD_AIR_REGION:
    msg = msg + ", radiation boundary"
if ADD_SOLUTION:
    msg = msg + ", 400 MHz setup + 50-800 MHz sweep"
if ADD_OUTPUT_VARIABLES:
    msg = msg + ", L/R/M/k/Q output variables"
oDesktop.AddMessage("", "", 0, msg + ".")
