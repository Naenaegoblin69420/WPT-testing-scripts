# IronPython 2.7 script for HFSS (Automation -> Run Script)
#
# Builds ONE square copper loop, centred on (0, 0), with rounded inside
# corners (3-point arcs at each turn) and a configurable open gap on the
# right side so the loop is not electrically closed.
#
# This script builds GEOMETRY ONLY -- it does NOT create a port or a port
# sheet. Add your lumped port manually across the 1 mm gap after the
# script finishes (or set ADD_SOLUTION = True only AFTER you have added a
# port; otherwise the adaptive solve has nothing to drive and will error).
#
# Usage:
#   1. Open / create an HFSS DrivenModal design.
#   2. Automation -> Run Script -> select this file.
#
# All knobs are at the top of the file: edit, save, re-run.
#
# Sizing for 120 nH @ 400 MHz
# ---------------------------
# A single-turn square loop's inductance follows roughly (Greenhouse 1974,
# rectangular cross-section w x t, mean side length a = LOOP_SIDE - w):
#     L ~ (2 * mu0 * a / pi) * [ ln( 2 * a / (w + t) ) - 0.274 ]
# With w = 0.5 mm, t = 0.035 mm, this gives ~120 nH at a ~= 33.5 mm
# (LOOP_SIDE ~= 34 mm). Wheeler's modified-spiral formula (tuned for n >=
# ~2 turns, less accurate for n = 1) would instead suggest LOOP_SIDE ~=
# 43 mm. Real HFSS lands somewhere between these, usually closer to
# Greenhouse for single rectangular loops.
#
# The default below is LOOP_SIDE_MM = 35.0, expected to land in the
# 115 - 130 nH window in HFSS. After you build, add a port, solve, and
# read L = Im(Z11) / (2*pi*Freq) at 400 MHz, scale LOOP_SIDE_MM by
# roughly +/- 1 mm per +/- 4 nH and re-run until you hit 120 nH.

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

LOOP_SIDE_MM     = 35.0    # outer side length; ~120 nH target at 400 MHz
TRACE_WIDTH_MM   = 0.5     # trace width (perpendicular to path)
TRACE_THICK_MM   = 0.035   # copper thickness (35 um = 1 oz Cu)
CORNER_RADIUS_MM = 3.0     # inside fillet radius (must be > W/2)
GAP_MM           = 1.0     # right-side open gap, centred on y = 0
LOOP_Z_MM        = 0.0     # z plane the loop sits in

ADD_AIR_REGION = True      # air region + radiation boundary
ADD_SOLUTION   = False     # 400 MHz adaptive + 50-800 MHz sweep
                           # leave False until you have manually added a
                           # port; otherwise the solve has no excitation
FREQ_MHZ       = 400.0     # design + radiation-boundary frequency
PAD_MM         = 30        # air-region padding around the loop, each face

MATERIAL  = "copper"
LOOP_NAME = "SquareLoop"


# ============================================================
# Geometry: rounded-corner square loop with right-side gap
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

# 14 points along the centre-line, CCW from the top of the gap.
points = [
    (a,             half_gap,        z),   # 0  start  (top of gap on right)
    (a,             a - r,           z),   # 1  end of right-up straight
    (a - r + r2,    a - r + r2,      z),   # 2  top-right arc midpoint (45 deg)
    (a - r,         a,               z),   # 3  end of TR arc
    (-a + r,        a,               z),   # 4  start of TL arc
    (-a + r - r2,   a - r + r2,      z),   # 5  TL arc midpoint (135 deg)
    (-a,            a - r,           z),   # 6  end of TL arc
    (-a,            -a + r,          z),   # 7  start of BL arc
    (-a + r - r2,   -a + r - r2,     z),   # 8  BL arc midpoint (225 deg)
    (-a + r,        -a,              z),   # 9  end of BL arc
    (a - r,         -a,              z),   # 10 start of BR arc
    (a - r + r2,    -a + r - r2,     z),   # 11 BR arc midpoint (315 deg)
    (a,             -a + r,          z),   # 12 end of BR arc
    (a,             -half_gap,       z),   # 13 end (bottom of gap on right)
]

polyline_points = ["NAME:PolylinePoints"]
for p in points:
    polyline_points.append([
        "NAME:PLPoint",
        "X:=", "%fmm" % p[0],
        "Y:=", "%fmm" % p[1],
        "Z:=", "%fmm" % p[2],
    ])

# Segments alternate Line / Arc. A 3-point Arc consumes the start point
# (shared with the previous segment's end) plus a midpoint and end point.
segment_defs = [
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
segments = ["NAME:PolylineSegments"]
for stype, start_idx, n_pts in segment_defs:
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
# Optional: air region with radiation boundary
# ============================================================

if ADD_AIR_REGION:
    pad_str = "%fmm" % PAD_MM
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

    oBoundary = oDesign.GetModule("BoundarySetup")
    region_faces = oEditor.GetFaceIDs("Region")
    oBoundary.AssignRadiation([
        "NAME:Rad1",
        "Faces:=",          region_faces,
        "IsFssReference:=", False,
        "IsForPML:=",       False,
    ])


# ============================================================
# Optional: adaptive setup + sweep
# (only useful AFTER you have manually added a port across the gap)
# ============================================================

if ADD_SOLUTION:
    oAnalysis = oDesign.GetModule("AnalysisSetup")
    oAnalysis.InsertSetup("HfssDriven", [
        "NAME:Setup",
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
    oAnalysis.InsertFrequencySweep("Setup", [
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


# ============================================================
# Summary into the Message Manager
# ============================================================

perim_mm = (3 * (2 * a - 2 * r)) + (2 * (a - r) - GAP_MM) + 4 * (math.pi / 2.0) * r
c_mps   = 299792458.0
freq_hz = FREQ_MHZ * 1e6
lambdas = (perim_mm * 1e-3) / (c_mps / freq_hz)

# Analytic L estimate (Greenhouse single-turn square loop)
a_m = (LOOP_SIDE_MM - TRACE_WIDTH_MM) * 1e-3
wt_m = (TRACE_WIDTH_MM + TRACE_THICK_MM) * 1e-3
mu0 = 4e-7 * math.pi
L_est_H = (2.0 * mu0 * a_m / math.pi) * (math.log(2.0 * a_m / wt_m) - 0.274)
L_est_nH = L_est_H * 1e9

oDesktop.AddMessage("", "", 0,
    "SquareLoop built. side=%.1fmm  perim~%.1fmm (%.3f lambda @ %.0fMHz). "
    "Analytic L ~ %.1f nH (Greenhouse). Add a port across the gap, solve, "
    "then trim LOOP_SIDE_MM by ~1mm per ~4nH to dial in 120 nH."
    % (LOOP_SIDE_MM, perim_mm, lambdas, FREQ_MHZ, L_est_nH))

oEditor.FitAll()
