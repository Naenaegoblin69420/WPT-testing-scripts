# IronPython 2.7 script for HFSS (Automation -> Run Script)
#
# Parametric SWEEP over the petal square loop. For each combination of
# (LOOP_SIDE_MM, TRACE_WIDTH_MM, FOLD_HEIGHT_MM):
#   1. Delete the prior loop body / TX port / setup / output vars / report
#      from the active design (does NOT touch the air region or rad bndy)
#   2. Rebuild the petal loop with the new params (same geometry code as
#      petal_square_loop.py)
#   3. Drop the TX circuit port between the two trace-end edges
#   4. Insert a 400 MHz adaptive setup + 5-point sweep 350-450 MHz
#   5. Create output variables L_nH and R_ohm derived from Z(TX,TX)
#   6. Solve
#   7. Export a CSV with L_nH, R_ohm vs Freq; parse it; pull the 400 MHz row
#   8. Export the L/R-vs-Freq plot as a PNG into OUTPUT_DIR
#   9. Append a row to results.csv with the iteration's params + measured L,R
#      and the squared error vs the (120 nH, 2.8 ohm) target
# After all iterations, print the iteration whose total error was smallest
# into the Message Manager.
#
# IMPORTANT WORKFLOW NOTES
# ------------------------
# * BEFORE running, you must MANUALLY create an air region (any name)
#   and assign a radiation boundary to it. The script will NOT touch
#   either of them -- it only wipes/rebuilds the loop body, port, setup
#   and reports it owns.
# * This is script-driven, NOT HFSS Optimetrics. Each iteration re-meshes
#   from scratch -- slow but works without making the polyline parametric
#   in HFSS variables. Expect 2-5 min per iteration on a student licence.
# * Open / create an HFSS DrivenModal design BEFORE running. Save your
#   work first -- the script wipes anything named PetalSquareLoop, TX,
#   SweepSetup, L_nH/R_ohm/ImZ, LRvsFreq, ZExport every iteration.
# * Results land in OUTPUT_DIR (defaults to %USERPROFILE%\Desktop\PetalSweep).
#   That folder gets: results.csv (full table), one PNG per iteration, and
#   a temp_z.csv used internally during result parsing.
# * Plot export and CSV parsing are wrapped in try/except so a single
#   failed iteration doesn't kill the whole sweep -- you'll see WARN
#   messages in the Message Manager.

import ScriptEnv
import math
import os
import time

ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
oDesktop.RestoreWindow()

oProject = oDesktop.GetActiveProject()
oDesign  = oProject.GetActiveDesign()
oEditor  = oDesign.SetActiveEditor("3D Modeler")


# ============================================================
# SWEEP CONFIGURATION -- edit these
# ============================================================

# Parameters that are SWEPT
SWEEP_LOOP_SIDE_MM   = [30.0]
SWEEP_TRACE_WIDTH_MM = [0.15]
SWEEP_FOLD_HEIGHT_MM = [0.0, 1.0]

# Parameters that are FIXED across all iterations
TRACE_THICK_MM   = 0.035
CORNER_RADIUS_MM = 3.0
GAP_MM           = 1.0
LOOP_Z_MM        = 11.0
FOLDS_PER_SIDE   = 3
FOLD_LENGTH_MM   = 4.5
PETAL_SEGMENTS   = 16

# Solver / sim settings
FREQ_MHZ         = 400.0
ADAPTIVE_PASSES  = 12       # less than the single-shot script to save time
MAX_DELTA_S      = 0.02
SWEEP_F_LO_MHZ   = 350.0    # narrow band around 400 MHz for the plot
SWEEP_F_HI_MHZ   = 450.0
SWEEP_F_NPOINTS  = 5
PORT_IMPEDANCE   = 50.0     # ohm

# Targets for ranking iterations
TARGET_L_NH      = 120.0
TARGET_R_OHM     = 2.8

# Output folder for CSV + PNGs. Defaults to a folder on the Desktop.
USER_HOME        = os.path.expanduser("~")
OUTPUT_DIR       = os.path.join(USER_HOME, "Desktop", "PetalSweep")

MATERIAL         = "copper"
LOOP_NAME        = "PetalSquareLoop"
PORT_NAME        = "TX"
SETUP_NAME       = "SweepSetup"
FSWEEP_NAME      = "Sweep1"


# ============================================================
# Output folder setup
# ============================================================

try:
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
except Exception as ex:
    OUTPUT_DIR = oProject.GetPath() if oProject else "."
    oDesktop.AddMessage("", "", 1,
        "Couldn't create OUTPUT_DIR; falling back to project dir %s (%s)"
        % (OUTPUT_DIR, str(ex)))

results_csv = os.path.join(OUTPUT_DIR, "results.csv")
tempz_csv   = os.path.join(OUTPUT_DIR, "temp_z.csv")


# ============================================================
# Geometry helpers (transcribed from petal_square_loop.py with
# the script-level constants pulled in as function arguments)
# ============================================================

def derive(params):
    """Compute a, half_gap, r, r2, z from the param dict."""
    L = params["LOOP_SIDE_MM"]
    W = params["TRACE_WIDTH_MM"]
    R = params["CORNER_RADIUS_MM"]
    G = params["GAP_MM"]
    a        = L / 2.0 - W / 2.0
    half_gap = G / 2.0
    r        = R
    r2       = r / math.sqrt(2.0)
    z        = params["LOOP_Z_MM"]
    return a, half_gap, r, r2, z


def petal_side_points(params, start_xy, end_xy):
    a, half_gap, r, r2, z = derive(params)
    W   = params["TRACE_WIDTH_MM"]
    NS  = params["FOLDS_PER_SIDE"]
    h   = params["FOLD_HEIGHT_MM"]
    Lc  = params["FOLD_LENGTH_MM"]
    nseg = params["PETAL_SEGMENTS"]

    sx, sy = start_xy
    ex, ey = end_xy
    L_side = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)
    if NS == 0 or h == 0.0:
        return [(ex, ey, z)]

    occupied = NS * Lc
    if occupied >= L_side:
        raise Exception("Petals too long for side (%.2fmm; %d x %.2fmm)."
                        % (L_side, NS, Lc))
    pitch_gap = (L_side - occupied) / (NS + 1)
    tx = (ex - sx) / L_side
    ty = (ey - sy) / L_side
    nx = ty
    ny = -tx

    pts = []
    for i in range(NS):
        ps = (i + 1) * pitch_gap + i * Lc
        pts.append((sx + tx * ps, sy + ty * ps, z))
        for k in range(1, nseg + 1):
            theta = k * math.pi / nseg
            s_along = ps + Lc * (1.0 - math.cos(theta)) / 2.0
            v_perp  = h * math.sin(theta)
            x = sx + tx * s_along + nx * v_perp
            y = sy + ty * s_along + ny * v_perp
            pts.append((x, y, z))
    pts.append((ex, ey, z))
    return pts


def plan_right_side(params):
    a, half_gap, r, r2, z = derive(params)
    W   = params["TRACE_WIDTH_MM"]
    NS  = params["FOLDS_PER_SIDE"]
    h   = params["FOLD_HEIGHT_MM"]
    Lc  = params["FOLD_LENGTH_MM"]
    nseg = params["PETAL_SEGMENTS"]

    L = 2 * (a - r)
    if NS == 0 or h == 0.0:
        return ([(a, a - r, z)],
                [(a, -half_gap, z)],
                (a, +half_gap, z),
                (a, -half_gap, z))

    occupied = NS * Lc
    if occupied >= L:
        raise Exception("Petals too long for right side.")
    pitch_gap = (L - occupied) / (NS + 1)
    petals = []
    for i in range(NS):
        ps = (i + 1) * pitch_gap + i * Lc
        pe = ps + Lc
        petals.append((ps, pe))

    s_gap_lo = L / 2.0 - half_gap
    s_gap_hi = L / 2.0 + half_gap
    mid_s    = L / 2.0

    straddling = None
    for (ps, pe) in petals:
        if ps < mid_s < pe:
            pc = (ps + pe) / 2.0
            cos_theta_top = (2.0 * pc - L - 2.0 * half_gap) / Lc
            cos_theta_bot = (2.0 * pc - L + 2.0 * half_gap) / Lc
            if abs(cos_theta_top) >= 1.0 or abs(cos_theta_bot) >= 1.0:
                raise Exception("Gap doesn't fit inside straddling petal.")
            theta_top = math.acos(cos_theta_top)
            theta_bot = math.acos(cos_theta_bot)
            straddling = (ps, pe, theta_bot, theta_top)
            break

    def y_of(s):
        return -(a - r) + s

    def petal_xy(ps_local, theta):
        s_along = ps_local + Lc * (1.0 - math.cos(theta)) / 2.0
        return (a + h * math.sin(theta), y_of(s_along), z)

    bottom_half = []
    top_half = []

    for (ps, pe) in petals:
        if straddling and ps == straddling[0]:
            _, _, theta_bot, theta_top = straddling
            bottom_half.append((a, y_of(ps), z))
            for k in range(1, nseg + 1):
                theta = k * math.pi / nseg
                if theta >= theta_bot:
                    break
                bottom_half.append(petal_xy(ps, theta))
            for k in range(1, nseg + 1):
                theta = k * math.pi / nseg
                if theta <= theta_top:
                    continue
                top_half.append(petal_xy(ps, theta))
        elif pe <= s_gap_lo:
            bottom_half.append((a, y_of(ps), z))
            for k in range(1, nseg + 1):
                theta = k * math.pi / nseg
                bottom_half.append(petal_xy(ps, theta))
        elif ps >= s_gap_hi:
            top_half.append((a, y_of(ps), z))
            for k in range(1, nseg + 1):
                theta = k * math.pi / nseg
                top_half.append(petal_xy(ps, theta))

    if straddling:
        _, _, theta_bot, theta_top = straddling
        gap_top_x = a + h * math.sin(theta_top)
        gap_bot_x = a + h * math.sin(theta_bot)
    else:
        gap_top_x = a
        gap_bot_x = a

    bottom_half.append((gap_bot_x, -half_gap, z))
    top_half.append((a, a - r, z))

    return (top_half, bottom_half,
            (gap_top_x, +half_gap, z),
            (gap_bot_x, -half_gap, z))


def build_geometry(params):
    """Build the petal loop polyline. Returns (gap_top_xyz, gap_bot_xyz)."""
    a, half_gap, r, r2, z = derive(params)
    W = params["TRACE_WIDTH_MM"]
    T = params["TRACE_THICK_MM"]

    right_top_pts, right_bottom_pts, gap_top_xyz, gap_bot_xyz = plan_right_side(params)

    points = []
    segment_types = []
    points.append(gap_top_xyz)

    def add_pts(pt_list):
        for pt in pt_list:
            points.append(pt)
            segment_types.append(("Line", len(points) - 2, 2))

    def add_arc(mid_xy, end_xy):
        points.append((mid_xy[0], mid_xy[1], z))
        points.append((end_xy[0], end_xy[1], z))
        segment_types.append(("Arc", len(points) - 3, 3))

    def add_side(start_xy, end_xy):
        add_pts(petal_side_points(params, start_xy, end_xy))

    add_pts(right_top_pts)
    add_arc((a - r + r2, a - r + r2), (a - r, a))
    add_side((a - r, a), (-a + r, a))
    add_arc((-a + r - r2, a - r + r2), (-a, a - r))
    add_side((-a, a - r), (-a, -a + r))
    add_arc((-a + r - r2, -a + r - r2), (-a + r, -a))
    add_side((-a + r, -a), (a - r, -a))
    add_arc((a - r + r2, -a + r - r2), (a, -a + r))
    add_pts(right_bottom_pts)

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
            "StartIndex:=", start_idx,
            "NoOfPoints:=", n_pts,
        ])
    xsection = [
        "NAME:PolylineXSection",
        "XSectionType:=",        "Rectangle",
        "XSectionOrient:=",      "Auto",
        "XSectionWidth:=",       "%fmm" % W,
        "XSectionTopWidth:=",    "%fmm" % W,
        "XSectionHeight:=",      "%fmm" % T,
        "XSectionNumSegments:=", "0",
        "XSectionBendType:=",    "Corner",
    ]
    polyline_params = [
        "NAME:PolylineParameters",
        "IsPolylineCovered:=", False,
        "IsPolylineClosed:=",  False,
        polyline_points, segments, xsection,
    ]
    attributes = [
        "NAME:Attributes",
        "Name:=", LOOP_NAME,
        "Flags:=", "",
        "Color:=", "(255 128 0)",
        "Transparency:=", 0,
        "PartCoordinateSystem:=", "Global",
        "MaterialValue:=", '"' + MATERIAL + '"',
        "SolveInside:=", True,
    ]
    oEditor.CreatePolyline(polyline_params, attributes)
    return gap_top_xyz, gap_bot_xyz


# ============================================================
# Port + region + setup helpers
# ============================================================

def _to_mm(s):
    s = str(s).strip()
    if s.endswith("mm"):
        return float(s[:-2])
    if s.endswith("m"):
        return float(s[:-1]) * 1000.0
    return float(s)


def _edge_midpoint(eid):
    vids = oEditor.GetVertexIDsFromEdge(eid)
    if not vids:
        return None
    sx = sy = sz = 0.0
    for vid in vids:
        pos = oEditor.GetVertexPosition(vid)
        sx += _to_mm(pos[0])
        sy += _to_mm(pos[1])
        sz += _to_mm(pos[2])
    n = float(len(vids))
    return (sx / n, sy / n, sz / n)


def _find_closest_edge(body_name, tx, ty, tz):
    eids = oEditor.GetEdgeIDsFromObject(body_name)
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


def create_circuit_port(params, gap_top_xyz, gap_bot_xyz):
    T = params["TRACE_THICK_MM"]
    z = params["LOOP_Z_MM"]
    trace_top_z = z + T / 2.0
    edge_top = _find_closest_edge(LOOP_NAME,
                                  gap_top_xyz[0], gap_top_xyz[1], trace_top_z)
    edge_bot = _find_closest_edge(LOOP_NAME,
                                  gap_bot_xyz[0], gap_bot_xyz[1], trace_top_z)
    if edge_top is None or edge_bot is None or edge_top == edge_bot:
        raise Exception("Couldn't locate two distinct gap edges for the port.")
    oBoundary = oDesign.GetModule("BoundarySetup")
    oBoundary.AssignCircuitPort([
        "NAME:" + PORT_NAME,
        "Edges:=",                   [int(edge_top), int(edge_bot)],
        "Impedance:=",               "%fohm" % PORT_IMPEDANCE,
        "DoDeembed:=",               False,
        "RenormalizeAllTerminals:=", True,
    ])


# Note: the air region + radiation boundary are NOT created by this
# script. You must create them manually in HFSS once before running the
# sweep -- the script only owns the loop body, the TX port, the setup,
# the output variables and the LRvsFreq/ZExport reports.


def create_setup_and_sweep():
    oA = oDesign.GetModule("AnalysisSetup")
    oA.InsertSetup("HfssDriven", [
        "NAME:" + SETUP_NAME,
        "Frequency:=",              "%fMHz" % FREQ_MHZ,
        "MaxDeltaS:=",              MAX_DELTA_S,
        "MaximumPasses:=",          ADAPTIVE_PASSES,
        "MinimumPasses:=",          2,
        "MinimumConvergedPasses:=", 1,
        "PercentRefinement:=",      30,
        "IsEnabled:=",              True,
        "BasisOrder:=",             1,
        "DoLambdaRefine:=",         True,
        "DoMaterialLambda:=",       True,
        "SetLambdaTarget:=",        False,
        "Target:=",                 0.3333,
        "UseMaxTetIncrease:=",      False,
    ])
    oA.InsertFrequencySweep(SETUP_NAME, [
        "NAME:" + FSWEEP_NAME,
        "IsEnabled:=",        True,
        "RangeType:=",        "LinearCount",
        "RangeStart:=",       "%fMHz" % SWEEP_F_LO_MHZ,
        "RangeEnd:=",         "%fMHz" % SWEEP_F_HI_MHZ,
        "RangeCount:=",       SWEEP_F_NPOINTS,
        "Type:=",             "Interpolating",
        "SaveFields:=",       False,
        "SaveRadFields:=",    False,
        "InterpTolerance:=",  0.5,
        "InterpMaxSolns:=",   50,
        "InterpMinSolns:=",   0,
        "InterpMinSubranges:=", 1,
    ])


def create_output_variables():
    oOV = oDesign.GetModule("OutputVariable")
    solution = SETUP_NAME + " : LastAdaptive"
    omega = "(2*pi*Freq)"
    defs = [
        ("L_nH",  "im(Z(%s,%s))/%s*1e9" % (PORT_NAME, PORT_NAME, omega)),
        ("R_ohm", "re(Z(%s,%s))" % (PORT_NAME, PORT_NAME)),
        ("ImZ",   "im(Z(%s,%s))" % (PORT_NAME, PORT_NAME)),
    ]
    for name, expr in defs:
        try:
            oOV.CreateOutputVariable(name, expr, solution, "Modal Solution Data", [])
        except Exception:
            pass  # already exists from a prior run; that's fine


def create_results_report():
    oR = oDesign.GetModule("ReportSetup")
    try:
        oR.DeleteReports(["LRvsFreq"])
    except Exception:
        pass
    try:
        oR.CreateReport(
            "LRvsFreq", "Modal Solution Data", "Rectangular Plot",
            SETUP_NAME + " : " + FSWEEP_NAME,
            ["Domain:=", "Sweep"],
            ["Freq:=", ["All"]],
            ["X Component:=", "Freq",
             "Y Component:=", ["L_nH", "R_ohm"]],
            [],
        )
    except Exception as ex:
        oDesktop.AddMessage("", "", 1, "Couldn't create LRvsFreq report: " + str(ex))


# ============================================================
# Delete / wipe helpers
# ============================================================

def delete_previous_model():
    """Best-effort wipe of geometry, ports, region, setup, reports."""
    # Reports
    try:
        oR = oDesign.GetModule("ReportSetup")
        for rn in ["LRvsFreq"]:
            try:
                oR.DeleteReports([rn])
            except Exception:
                pass
    except Exception:
        pass

    # Setup
    try:
        oA = oDesign.GetModule("AnalysisSetup")
        try:
            oA.DeleteSetups([SETUP_NAME])
        except Exception:
            pass
    except Exception:
        pass

    # Output variables (skip; they'll be re-created above)
    try:
        oOV = oDesign.GetModule("OutputVariable")
        for ov in ["L_nH", "R_ohm", "ImZ"]:
            try:
                oOV.DeleteOutputVariable(ov)
            except Exception:
                pass
    except Exception:
        pass

    # Boundaries (TX port only -- the user's radiation boundary is NOT touched)
    try:
        oB = oDesign.GetModule("BoundarySetup")
        try:
            oB.DeleteBoundaries([PORT_NAME])
        except Exception:
            pass
    except Exception:
        pass

    # Geometry (loop body only -- the user's air region is NOT touched)
    try:
        oEditor.Delete([
            "NAME:Selections",
            "Selections:=", LOOP_NAME,
        ])
    except Exception:
        pass


# ============================================================
# Solve + result extraction
# ============================================================

def solve_setup():
    """Run the adaptive solve + sweep. Blocking."""
    oDesign.Analyze(SETUP_NAME)


def export_z_csv(path):
    """Export im(Z), re(Z) vs Freq from the sweep into a CSV. Returns True
    if the file was written."""
    oR = oDesign.GetModule("ReportSetup")
    try:
        try:
            oR.DeleteReports(["ZExport"])
        except Exception:
            pass
        oR.CreateReport(
            "ZExport", "Modal Solution Data", "Data Table",
            SETUP_NAME + " : " + FSWEEP_NAME,
            ["Domain:=", "Sweep"],
            ["Freq:=", ["All"]],
            ["X Component:=", "Freq",
             "Y Component:=", ["L_nH", "R_ohm"]],
            [],
        )
        oR.ExportToFile("ZExport", path, False)
        return True
    except Exception as ex:
        oDesktop.AddMessage("", "", 1, "ZExport failed: " + str(ex))
        return False


def parse_csv_at_freq(path, target_mhz, tol_mhz=10.0):
    """Read the CSV produced by export_z_csv and return (L_nH, R_ohm) at
    the row whose Freq is closest to target_mhz (within tol_mhz)."""
    if not os.path.exists(path):
        raise Exception("Result CSV missing: " + path)
    f = open(path, "r")
    try:
        lines = f.readlines()
    finally:
        f.close()
    if len(lines) < 2:
        raise Exception("Result CSV empty: " + path)

    # Header line tells us which column is which
    header = [h.strip() for h in lines[0].split(",")]
    # Find the columns. Header names often look like
    # "Freq [GHz]", "L_nH []", "R_ohm []". We normalise.
    def col_index(name_prefix):
        for i, h in enumerate(header):
            if h.lower().startswith(name_prefix.lower()):
                return i
        return -1
    i_freq = col_index("Freq")
    i_L    = col_index("L_nH")
    i_R    = col_index("R_ohm")
    if i_freq < 0 or i_L < 0 or i_R < 0:
        raise Exception("Couldn't find columns in CSV header: " + str(header))

    # The Freq column units are in the header (e.g. "Freq [GHz]" or
    # "Freq [MHz]"). Detect.
    freq_header = header[i_freq].lower()
    if "ghz" in freq_header:
        freq_scale = 1.0e3   # data is in GHz; we want MHz
    elif "khz" in freq_header:
        freq_scale = 1.0e-3
    elif "hz"  in freq_header and "mhz" not in freq_header and "ghz" not in freq_header and "khz" not in freq_header:
        freq_scale = 1.0e-6
    else:
        freq_scale = 1.0     # already MHz

    best_L, best_R, best_df = None, None, 1.0e30
    for line in lines[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) <= max(i_freq, i_L, i_R):
            continue
        try:
            f_mhz = float(parts[i_freq]) * freq_scale
            L_nH  = float(parts[i_L])
            R_ohm = float(parts[i_R])
        except Exception:
            continue
        df = abs(f_mhz - target_mhz)
        if df < best_df and df <= tol_mhz:
            best_df = df
            best_L  = L_nH
            best_R  = R_ohm
    if best_L is None:
        raise Exception("No row within %.1f MHz of %.1f MHz in %s"
                        % (tol_mhz, target_mhz, path))
    return best_L, best_R


def export_plot_png(path):
    """Save the LRvsFreq plot as a PNG. Best-effort -- failures are warned."""
    try:
        oR = oDesign.GetModule("ReportSetup")
        oR.ExportImageToFile("LRvsFreq", path, 1000, 600)
        return True
    except Exception as ex:
        oDesktop.AddMessage("", "", 1, "Plot export failed: " + str(ex))
        return False


# ============================================================
# Sweep loop
# ============================================================

def fmt_filename(loop_side, trace_w, fold_h):
    return ("LS%05.2f_W%04.2f_H%+04.2f"
            % (loop_side, trace_w, fold_h)).replace(".", "p")


total_iters = (len(SWEEP_LOOP_SIDE_MM)
               * len(SWEEP_TRACE_WIDTH_MM)
               * len(SWEEP_FOLD_HEIGHT_MM))

oDesktop.AddMessage("", "", 0,
    "Petal sweep starting: %d iterations. Output -> %s"
    % (total_iters, OUTPUT_DIR))

# Open results.csv for write+flush so progress survives a crash
fres = open(results_csv, "w")
fres.write("iter,loop_side_mm,trace_width_mm,fold_height_mm,"
           "L_nH,R_ohm,L_err_pct,R_err_pct,total_err,wall_sec,status\n")
fres.flush()

best = {"err": 1.0e30, "row": None}
iter_num = 0
sweep_start = time.time()

for loop_side in SWEEP_LOOP_SIDE_MM:
    for trace_w in SWEEP_TRACE_WIDTH_MM:
        for fold_h in SWEEP_FOLD_HEIGHT_MM:
            iter_num += 1
            tag = fmt_filename(loop_side, trace_w, fold_h)
            params = {
                "LOOP_SIDE_MM":     loop_side,
                "TRACE_WIDTH_MM":   trace_w,
                "TRACE_THICK_MM":   TRACE_THICK_MM,
                "CORNER_RADIUS_MM": CORNER_RADIUS_MM,
                "GAP_MM":           GAP_MM,
                "LOOP_Z_MM":        LOOP_Z_MM,
                "FOLDS_PER_SIDE":   FOLDS_PER_SIDE,
                "FOLD_HEIGHT_MM":   fold_h,
                "FOLD_LENGTH_MM":   FOLD_LENGTH_MM,
                "PETAL_SEGMENTS":   PETAL_SEGMENTS,
            }

            oDesktop.AddMessage("", "", 0,
                "[%d/%d] %s  LOOP=%.1f  W=%.2f  H=%+.2f"
                % (iter_num, total_iters, tag, loop_side, trace_w, fold_h))
            t_iter = time.time()
            status = "ok"
            L_nH = float("nan")
            R_ohm = float("nan")

            try:
                delete_previous_model()
                gap_top, gap_bot = build_geometry(params)
                create_circuit_port(params, gap_top, gap_bot)
                create_setup_and_sweep()
                create_output_variables()
                create_results_report()
                solve_setup()
                if export_z_csv(tempz_csv):
                    L_nH, R_ohm = parse_csv_at_freq(tempz_csv, FREQ_MHZ)
                else:
                    raise Exception("Z export failed")
                png_path = os.path.join(OUTPUT_DIR, tag + ".png")
                export_plot_png(png_path)
            except Exception as ex:
                status = "fail: " + str(ex)
                oDesktop.AddMessage("", "", 2,
                    "[%d/%d] FAILED: %s" % (iter_num, total_iters, str(ex)))

            wall = time.time() - t_iter

            if status == "ok":
                L_err = (L_nH  - TARGET_L_NH)  / TARGET_L_NH  * 100.0
                R_err = (R_ohm - TARGET_R_OHM) / TARGET_R_OHM * 100.0
                tot_err = math.sqrt((L_err / 100.0) ** 2 + (R_err / 100.0) ** 2)
                oDesktop.AddMessage("", "", 0,
                    "[%d/%d] L=%.2f nH (err %+.1f%%)  R=%.3f ohm (err %+.1f%%)  "
                    "tot_err=%.4f  wall=%.0fs"
                    % (iter_num, total_iters, L_nH, L_err, R_ohm, R_err,
                       tot_err, wall))
                if tot_err < best["err"]:
                    best["err"] = tot_err
                    best["row"] = (iter_num, loop_side, trace_w, fold_h,
                                   L_nH, R_ohm, tot_err)
                fres.write("%d,%f,%f,%f,%f,%f,%f,%f,%f,%f,%s\n"
                    % (iter_num, loop_side, trace_w, fold_h,
                       L_nH, R_ohm, L_err, R_err, tot_err, wall, status))
            else:
                fres.write("%d,%f,%f,%f,nan,nan,nan,nan,nan,%f,%s\n"
                    % (iter_num, loop_side, trace_w, fold_h, wall, status))
            fres.flush()

fres.close()
sweep_wall = time.time() - sweep_start

if best["row"] is not None:
    (bi, bls, bw, bh, bL, bR, berr) = best["row"]
    oDesktop.AddMessage("", "", 0,
        "Sweep finished in %.1f min. BEST: iter %d  LOOP_SIDE=%.1f  "
        "TRACE_WIDTH=%.2f  FOLD_HEIGHT=%+.2f  -> L=%.2fnH  R=%.3fohm  "
        "(target %.1fnH/%.1fohm, err=%.4f). Full table: %s"
        % (sweep_wall / 60.0, bi, bls, bw, bh, bL, bR,
           TARGET_L_NH, TARGET_R_OHM, berr, results_csv))
else:
    oDesktop.AddMessage("", "", 2,
        "Sweep finished in %.1f min but every iteration failed. See %s."
        % (sweep_wall / 60.0, results_csv))
