"""
AASHTO LRFD Reinforced Concrete Section Design — Calculation Engine
Pure math, no UI dependencies. All units: kip, in, ksi.
"""
import math

# ─── Equation Instrumentation ───────────────────────────────────────

class EqBreakdown:
    """Capture detailed equation steps for reporting."""
    def __init__(self, title=""):
        self.title = title
        self.steps = []  # list of {equation, desc, result, units}
    
    def add(self, equation, desc, result, units=""):
        """Add a calculation step. equation can be template with {var} placeholders."""
        self.steps.append({
            "equation": equation,
            "desc": desc,
            "result": round(result, 6) if isinstance(result, float) else result,
            "units": units
        })
        return result
    
    def to_dict(self):
        return {"title": self.title, "steps": self.steps}

def fmt_num(val, decimals=2):
    """Format a number for equation display."""
    if isinstance(val, bool):
        return str(val)
    try:
        return f"{float(val):.{decimals}f}"
    except:
        return str(val)

# ─── Bar Database ───────────────────────────────────────────────────
BARS = {
    2:  {"d": 0.250, "a": 0.05},
    3:  {"d": 0.375, "a": 0.11},
    4:  {"d": 0.500, "a": 0.20},
    5:  {"d": 0.625, "a": 0.31},
    6:  {"d": 0.750, "a": 0.44},
    7:  {"d": 0.875, "a": 0.60},
    8:  {"d": 1.000, "a": 0.79},
    9:  {"d": 1.128, "a": 1.00},
    10: {"d": 1.270, "a": 1.27},
    11: {"d": 1.410, "a": 1.56},
    14: {"d": 1.693, "a": 2.25},
    18: {"d": 2.257, "a": 4.00},
}

# ─── AASHTO B5 Tables ──────────────────────────────────────────────
B5_T1_EX_COLS = [-0.20, -0.10, -0.05, 0, 0.125, 0.25, 0.50, 0.75, 1.00]
B5_T1_VU_ROWS = [0.075, 0.100, 0.125, 0.150, 0.175, 0.200, 0.225, 0.250]
B5_T1_THETA = [
    [22.3, 20.4, 21.0, 21.8, 24.3, 26.6, 30.5, 33.7, 36.4],
    [18.1, 20.4, 21.4, 22.5, 24.9, 27.1, 30.8, 34.0, 36.7],
    [19.9, 21.9, 22.8, 23.7, 25.9, 27.9, 31.4, 34.4, 37.0],
    [21.6, 23.3, 24.2, 25.0, 26.9, 28.8, 32.1, 34.9, 37.3],
    [23.2, 24.7, 25.5, 26.2, 28.0, 29.7, 32.7, 35.2, 36.8],
    [24.7, 26.1, 26.7, 27.4, 29.0, 30.6, 32.8, 34.5, 36.1],
    [26.1, 27.3, 27.9, 28.5, 30.0, 30.8, 32.3, 34.0, 35.7],
    [27.5, 28.6, 29.1, 29.7, 30.6, 31.3, 32.8, 34.3, 35.8],
]
B5_T1_BETA = [
    [6.32, 4.75, 4.10, 3.75, 3.24, 2.94, 2.59, 2.38, 2.23],
    [3.79, 3.38, 3.24, 3.14, 2.91, 2.75, 2.50, 2.32, 2.18],
    [3.18, 2.99, 2.94, 2.87, 2.74, 2.62, 2.42, 2.26, 2.13],
    [2.88, 2.79, 2.78, 2.72, 2.60, 2.52, 2.36, 2.21, 2.08],
    [2.73, 2.66, 2.65, 2.60, 2.52, 2.44, 2.28, 2.14, 1.96],
    [2.63, 2.59, 2.52, 2.51, 2.43, 2.37, 2.14, 1.94, 1.79],
    [2.53, 2.45, 2.42, 2.40, 2.34, 2.14, 1.86, 1.73, 1.64],
    [2.39, 2.39, 2.33, 2.33, 2.12, 1.93, 1.70, 1.58, 1.50],
]

B5_T2_EX_COLS = [-0.20, -0.10, -0.05, 0, 0.125, 0.25, 0.50, 0.75, 1.00, 1.50, 2.00]
B5_T2_SXE_ROWS = [5, 10, 15, 20, 30, 40, 60, 80]
B5_T2_THETA = [
    [25.4, 25.5, 25.9, 26.4, 27.7, 28.9, 30.9, 32.4, 33.7, 35.6, 37.2],
    [27.6, 27.6, 28.3, 29.3, 31.6, 33.5, 36.3, 38.4, 40.1, 42.7, 44.7],
    [29.5, 29.5, 29.7, 31.1, 34.1, 36.5, 39.9, 42.4, 44.4, 47.4, 49.7],
    [31.2, 31.2, 31.2, 32.3, 36.0, 38.8, 42.7, 45.5, 47.6, 50.9, 53.4],
    [34.1, 34.1, 34.1, 34.2, 38.9, 42.3, 46.9, 50.1, 52.6, 56.3, 59.0],
    [36.6, 36.6, 36.6, 36.6, 41.2, 45.0, 50.2, 53.7, 56.3, 60.2, 63.0],
    [40.8, 40.8, 40.8, 40.8, 44.5, 49.2, 55.1, 58.9, 61.8, 65.8, 68.6],
    [44.3, 44.3, 44.3, 44.3, 47.1, 52.3, 58.7, 62.8, 65.7, 69.7, 72.4],
]
B5_T2_BETA = [
    [6.36, 6.06, 5.56, 5.15, 4.41, 3.91, 3.26, 2.86, 2.58, 2.21, 1.96],
    [5.78, 5.78, 5.38, 4.89, 4.05, 3.52, 2.88, 2.50, 2.23, 1.88, 1.65],
    [5.34, 5.34, 5.27, 4.73, 3.82, 3.28, 2.64, 2.26, 2.01, 1.68, 1.46],
    [4.99, 4.99, 4.99, 4.61, 3.65, 3.09, 2.46, 2.09, 1.85, 1.52, 1.31],
    [4.46, 4.46, 4.46, 4.43, 3.39, 2.82, 2.19, 1.84, 1.60, 1.30, 1.10],
    [4.06, 4.06, 4.06, 4.06, 3.20, 2.62, 2.00, 1.66, 1.43, 1.14, 0.95],
    [3.50, 3.50, 3.50, 3.50, 2.92, 2.32, 1.72, 1.40, 1.18, 0.92, 0.75],
    [3.10, 3.10, 3.10, 3.10, 2.71, 2.11, 1.52, 1.21, 1.01, 0.76, 0.62],
]


# ─── Helper Functions ───────────────────────────────────────────────

def interp_b5(row_vals, col_vals, theta_grid, beta_grid, row_val, col_val):
    """Bilinear interpolation in AASHTO B5 tables."""
    r = max(row_vals[0], min(row_val, row_vals[-1]))
    c = max(col_vals[0], min(col_val, col_vals[-1]))
    ri = 0
    for i in range(len(row_vals) - 1):
        if r >= row_vals[i] and r <= row_vals[i + 1]:
            ri = i
            break
        if i == len(row_vals) - 2:
            ri = i
    ci = 0
    for i in range(len(col_vals) - 1):
        if c >= col_vals[i] and c <= col_vals[i + 1]:
            ci = i
            break
        if i == len(col_vals) - 2:
            ci = i
    rr = (r - row_vals[ri]) / (row_vals[ri + 1] - row_vals[ri]) if row_vals[ri + 1] != row_vals[ri] else 0
    cr = (c - col_vals[ci]) / (col_vals[ci + 1] - col_vals[ci]) if col_vals[ci + 1] != col_vals[ci] else 0
    def interp_grid(g):
        v00, v01 = g[ri][ci], g[ri][ci + 1]
        v10, v11 = g[ri + 1][ci], g[ri + 1][ci + 1]
        return v00 * (1 - rr) * (1 - cr) + v01 * (1 - rr) * cr + v10 * rr * (1 - cr) + v11 * rr * cr
    return {"theta": interp_grid(theta_grid), "beta": interp_grid(beta_grid)}


def lookup_b5(has_min_av, ex, vufc, sxe):
    """Look up θ and β from AASHTO B5 tables. Returns None if εx exceeds table limits."""
    ex1000 = ex * 1000
    if has_min_av:
        if ex1000 > 1.00:
            return None
        return interp_b5(B5_T1_VU_ROWS, B5_T1_EX_COLS, B5_T1_THETA, B5_T1_BETA, vufc, ex1000)
    else:
        if ex1000 > 2.00:
            return None
        return interp_b5(B5_T2_SXE_ROWS, B5_T2_EX_COLS, B5_T2_THETA, B5_T2_BETA, sxe, ex1000)


def get_phi_flex(code_edition, section_class, eps_t, ecl, etl):
    """Flexural resistance factor per C5.5.4.2."""
    et = abs(eps_t)
    if et <= ecl:
        return 0.75
    if code_edition == "CA":
        if section_class == "PP":
            if et >= etl:
                return 1.0
            return min(max(0.75 + 0.25 * (et - ecl) / (etl - ecl), 0.75), 1.0)
        elif section_class == "CIP_PT":
            if et >= etl:
                return 0.95
            return min(max(0.75 + 0.20 * (et - ecl) / (etl - ecl), 0.75), 0.95)
        else:
            if et >= etl:
                return 0.9
            return min(max(0.75 + 0.15 * (et - ecl) / (etl - ecl), 0.75), 0.9)
    else:
        is_prestressed = section_class in ("PP", "CIP_PT")
        if is_prestressed:
            if et >= etl:
                return 1.0
            return min(max(0.75 + 0.25 * (et - ecl) / (etl - ecl), 0.75), 1.0)
        else:
            if et >= etl:
                return 0.9
            return min(max(0.75 + 0.15 * (et - ecl) / (etl - ecl), 0.75), 0.9)


# ─── Derived Constants ──────────────────────────────────────────────

def derive_constants(I):
    """Compute derived constants from raw inputs and attach to I dict."""
    fc = I["fc"]
    fy = I["fy"]
    Es = I["Es"]
    Ec = I["Ec"]
    fpu = I["fpu"]
    fpy = I["fpy"]

    I["beta1"] = max(min(0.85, 0.85 - 0.05 * (fc - 4)), 0.65)
    # alpha1: 0.85 for fc <= 10, reduced by 0.02 per ksi above 10, min 0.75  (5.6.2.2)
    I["alpha1"] = max(0.75, 0.85 - 0.02 * max(fc - 10, 0))
    I["k_pt"] = 2 * (1.04 - fpy / fpu) if fpu > 0 else 0
    I["n_mod"] = Es / Ec if Ec > 0 else 0
    I["ey"] = fy / Es if Es > 0 else 0
    # ecl / etl: auto-compute from fy per 5.6.2.1 unless user overrides
    # Compression-controlled strain limit:
    #   fy <= 60:  fy/Es but <= 0.002
    #   fy = 100:  0.004
    #   60 < fy < 100: linear interpolation
    #   Prestressed: 0.002
    if I.get("ecl_override"):
        pass  # keep user value
    else:
        if fy <= 60:
            I["ecl"] = min(fy / Es, 0.002) if Es > 0 else 0.002
        elif fy >= 100:
            I["ecl"] = 0.004
        else:
            I["ecl"] = 0.002 + (0.004 - 0.002) * (fy - 60) / (100 - 60)
    # Tension-controlled strain limit:
    #   fy <= 75 and prestressed: 0.005
    #   fy = 100: 0.008
    #   75 < fy < 100: linear interpolation
    if I.get("etl_override"):
        pass  # keep user value
    else:
        if fy <= 75:
            I["etl"] = 0.005
        elif fy >= 100:
            I["etl"] = 0.008
        else:
            I["etl"] = 0.005 + (0.008 - 0.005) * (fy - 75) / (100 - 75)

    bar = BARS.get(I["barN_bot"], BARS[7])
    I["bar_d_bot"] = bar["d"]
    I["bar_a_bot"] = bar["a"]
    I["As_bot"] = I["nBars_bot"] * bar["a"]
    # Multi-row override: use actual total As if provided
    if I.get("As_bot_ovr") is not None:
        I["As_bot"] = I["As_bot_ovr"]

    bar_top = BARS.get(I["barN_top"], None)
    if bar_top and I["nBars_top"] > 0:
        I["bar_d_top"] = bar_top["d"]
        I["bar_a_top"] = bar_top["a"]
        I["As_top"] = I["nBars_top"] * bar_top["a"]
        # Multi-row override
        if I.get("As_top_ovr") is not None:
            I["As_top"] = I["As_top_ovr"]
    else:
        I["bar_d_top"] = 0
        I["bar_a_top"] = 0
        I["As_top"] = 0
        if I.get("As_top_ovr") is not None:
            I["As_top"] = I["As_top_ovr"]

    sh_bar = BARS.get(I["shN"], BARS[4])
    I["shBar_d"] = sh_bar["d"]
    I["shBar_a"] = sh_bar["a"]
    I["Av"] = sh_bar["a"] * I["shear_legs"]

    t_bar = BARS.get(I["tN"], BARS[4])
    I["tBar_d"] = t_bar["d"]
    I["tBar_a"] = t_bar["a"]

    # Torsion uses same stirrup as shear (same bar, same spacing) per C5.7.3.6.2
    I["s_torsion"] = I["s_shear"]

    I["isRect"] = I["secType"] == "RECTANGULAR"
    I["bw"] = I["b"] if I["isRect"] else I["bw_input"]

    # Gross section properties (for PT elastic shortening, etc.)
    if I["isRect"]:
        I["Ag"] = I["b"] * I["h"]
        I["Ig"] = I["b"] * I["h"] ** 3 / 12.0
        I["yb_centroid"] = I["h"] / 2.0  # centroid from top
    else:
        b_fl = I["b"]       # top flange width
        bw = I["bw"]
        h = I["h"]
        hf_t = I["hf_top"]
        hf_b = I.get("hf_bot", 0)
        h_web = h - hf_t - hf_b
        A_top = b_fl * hf_t
        A_web = bw * h_web
        A_bot = b_fl * hf_b
        I["Ag"] = A_top + A_web + A_bot
        # Centroid from top
        y_top = hf_t / 2.0
        y_web = hf_t + h_web / 2.0
        y_bot = hf_t + h_web + hf_b / 2.0
        Ag = I["Ag"]
        yb = (A_top * y_top + A_web * y_web + A_bot * y_bot) / Ag if Ag > 0 else h / 2.0
        I["yb_centroid"] = yb
        # Parallel axis theorem
        I["Ig"] = (b_fl * hf_t ** 3 / 12.0 + A_top * (yb - y_top) ** 2
                    + bw * h_web ** 3 / 12.0 + A_web * (yb - y_web) ** 2
                    + b_fl * hf_b ** 3 / 12.0 + A_bot * (yb - y_bot) ** 2)

    I["Aps"] = I["nStrands"] * I["strand_area"]
    I["hasPT"] = I["Aps"] > 0
    # Effective prestress after losses (0 = conservative, strain compat only)
    if "fpe" not in I:
        I["fpe"] = 0

    # Multi-row reinforcement data (for PM curves):
    # Each is a list of {"d": depth_from_top, "As": area} or None for single-layer
    if "mr_rows_bot" not in I:
        I["mr_rows_bot"] = None
    if "mr_rows_top" not in I:
        I["mr_rows_top"] = None
    return I


# ─── P-M Interaction ───────────────────────────────────────────────

def _get_steel_rows(I, side, comp_face, h):
    """Build [{d_cf, As}] for one reinforcement side.
    d_cf = depth measured from the compression face."""
    mr_rows = I.get(f"mr_rows_{side}")
    if mr_rows and len(mr_rows) > 0:
        rows = []
        for row in mr_rows:
            d_top_val = row["d"]   # depth from top of section
            d_cf = (h - d_top_val) if comp_face == "bottom" else d_top_val
            As_r = row.get("As", 0)
            if As_r > 0:
                rows.append({"d_cf": d_cf, "As": As_r})
        return rows
    # Fallback: single layer from centroid values
    if side == "bot":
        d_top_val, As_val = I["d_bot"], I["As_bot"]
    else:
        d_top_val, As_val = I["d_top"], I["As_top"]
    if As_val <= 0:
        return []
    d_cf = (h - d_top_val) if comp_face == "bottom" else d_top_val
    return [{"d_cf": d_cf, "As": As_val}]


def build_pm_curve(I, comp_face="top"):
    """Build factored P-M interaction diagram data (40-point sweep).
    Supports multiple reinforcement rows per face.
    comp_face: 'top' for sagging, 'bottom' for hogging."""
    fc, fy, Es, Ept = I["fc"], I["fy"], I["Es"], I["Ept"]
    fpu, fpy, ecl = I["fpu"], I["fpy"], I["ecl"]
    alpha1, beta1, k_pt, etl = I["alpha1"], I["beta1"], I["k_pt"], I["etl"]
    fpe = I.get("fpe", 0)
    eps_pe = fpe / Ept if Ept > 0 else 0
    is_rect, b, h, bw = I["isRect"], I["b"], I["h"], I["bw"]
    hf_top = I["hf_top"]
    hf_bot = I.get("hf_bot", 0)
    Aps, dp = I["Aps"], I["dp"]
    code_edition, section_class = I["codeEdition"], I["sectionClass"]

    hf = h if is_rect else (hf_bot if comp_face == "bottom" else hf_top)
    dp_cf = (h - dp) if (comp_face == "bottom" and dp > 0) else dp

    # Build per-row arrays: [{d_cf, As}] measured from compression face
    if comp_face == "bottom":
        tens_rows = _get_steel_rows(I, "top", comp_face, h)
        comp_rows = _get_steel_rows(I, "bot", comp_face, h)
    else:
        tens_rows = _get_steel_rows(I, "bot", comp_face, h)
        comp_rows = _get_steel_rows(I, "top", comp_face, h)

    As_tens_total = sum(r["As"] for r in tens_rows)
    As_comp_total = sum(r["As"] for r in comp_rows)

    pc_y = h / 2
    Ag = b * h if is_rect else b * hf_top + bw * (h - hf_top - hf_bot) + b * hf_bot
    Pn_max = -0.8 * alpha1 * fc * Ag
    N = 40
    d_tens_max = max((r["d_cf"] for r in tens_rows), default=0)
    # Fallback sweep depth: use centroid depth when no tension rows exist
    if d_tens_max <= 0:
        d_fallback = (h - I["d_top"]) if comp_face == "bottom" else I["d_bot"]
        d_tens_max = max(d_fallback, 0.1)
    dt_bc = max(d_tens_max, dp_cf) if Aps > 0 else d_tens_max

    def _row_zero(rows):
        return [{"d_cf": r["d_cf"], "As": r["As"], "es": 0, "fs": 0, "F": 0} for r in rows]

    pts = []
    # Pure compression
    pts.append({
        "c": 9999, "a": 9999, "eps_t": 0, "stat": "CC", "phi": 0.75,
        "Pn": Pn_max, "Mn": 0, "Pr": Pn_max * 0.75, "Mr": 0,
        "es_tens": 0, "fs_tens": 0, "F_tens": 0,
        "es_comp": 0, "fs_comp": 0, "F_comp": 0,
        "rows_tens": _row_zero(tens_rows), "rows_comp": _row_zero(comp_rows),
        "eps_pe": eps_pe, "delta_eps": 0, "eps_pt": eps_pe, "fps_pt": 0, "F_pt": 0,
    })

    for i in range(N, 0, -1):
        ci = dt_bc * i / N
        ai = ci * beta1
        if is_rect or ai <= hf:
            Cc = -alpha1 * fc * b * ai
            ycc = ai / 2
        else:
            Cf = alpha1 * fc * (b - bw) * hf
            Cw = alpha1 * fc * bw * ai
            Cc = -(Cf + Cw)
            ycc = None

        # Tension rows
        F_tens_sum = 0
        Mn_tens_sum = 0
        rows_tens_data = []
        ext_es_tens = 0  # extreme tension strain (for table backward compat)
        ext_fs_tens = 0
        for row in tens_rows:
            d_r = row["d_cf"]
            es_r = 0.003 * (d_r - ci) / ci
            fs_r = min(abs(es_r) * Es, fy) * (1 if es_r >= 0 else -1)
            F_r = row["As"] * fs_r
            F_tens_sum += F_r
            Mn_tens_sum += F_r * (d_r - pc_y)
            rows_tens_data.append({"d_cf": d_r, "As": row["As"], "es": es_r, "fs": fs_r, "F": F_r})
            if d_r >= (ext_es_tens and d_r or 0) or ext_es_tens == 0:
                ext_es_tens = es_r
                ext_fs_tens = fs_r

        # Pick extreme tension strain from the deepest tension row
        if tens_rows:
            deepest = max(tens_rows, key=lambda r: r["d_cf"])
            ext_es_tens = 0.003 * (deepest["d_cf"] - ci) / ci
            ext_fs_tens = min(abs(ext_es_tens) * Es, fy) * (1 if ext_es_tens >= 0 else -1)

        # Compression rows
        F_comp_sum = 0
        Mn_comp_sum = 0
        rows_comp_data = []
        ext_es_comp = 0
        ext_fs_comp = 0
        for row in comp_rows:
            d_r = row["d_cf"]
            es_r = 0.003 * (d_r - ci) / ci if ci > 0 else 0
            fs_r = min(abs(es_r) * Es, fy) * (1 if es_r >= 0 else -1)
            F_r = row["As"] * fs_r
            F_comp_sum += F_r
            Mn_comp_sum += F_r * (d_r - pc_y)
            rows_comp_data.append({"d_cf": d_r, "As": row["As"], "es": es_r, "fs": fs_r, "F": F_r})
        if comp_rows:
            shallowest = min(comp_rows, key=lambda r: r["d_cf"])
            ext_es_comp = 0.003 * (shallowest["d_cf"] - ci) / ci if ci > 0 else 0
            ext_fs_comp = min(abs(ext_es_comp) * Es, fy) * (1 if ext_es_comp >= 0 else -1)

        # PT tendon
        Tpt = 0
        eps_p_i = 0
        fps_u_i = 0
        delta_eps_i = 0
        if Aps > 0 and dp_cf > 0:
            delta_eps_i = 0.003 * (dp_cf - ci) / ci
            eps_p_i = eps_pe + delta_eps_i
            fps_u_i = min(abs(eps_p_i) * Ept, fpy) * (1 if eps_p_i >= 0 else -1)
            Tpt = Aps * fps_u_i

        Pn = max(Cc + F_tens_sum + F_comp_sum + Tpt, Pn_max)

        # Moment about section mid-height
        arm_pt = dp_cf - pc_y if Aps > 0 else 0
        if is_rect or ai <= hf:
            Mn_cc = -Cc * (pc_y - ycc)
        else:
            Mn_cc = Cf * (pc_y - hf / 2) + Cw * (pc_y - ai / 2)

        Mn_i = Mn_cc + Mn_tens_sum + Mn_comp_sum + (Tpt * arm_pt if Aps > 0 else 0)

        et_i = 0.003 * (dt_bc - ci) / ci
        phi_i = get_phi_flex(code_edition, section_class, et_i, ecl, etl)
        st = "TC" if abs(et_i) >= etl else ("CC" if abs(et_i) <= ecl else "TR")

        pts.append({
            "c": ci, "a": ai, "eps_t": abs(et_i), "stat": st, "phi": phi_i,
            "Pn": Pn, "Mn": Mn_i, "Pr": Pn * phi_i, "Mr": Mn_i * phi_i,
            "es_tens": ext_es_tens, "fs_tens": ext_fs_tens, "F_tens": F_tens_sum,
            "es_comp": ext_es_comp, "fs_comp": ext_fs_comp, "F_comp": F_comp_sum,
            "rows_tens": rows_tens_data, "rows_comp": rows_comp_data,
            "eps_pe": eps_pe, "delta_eps": delta_eps_i, "eps_pt": eps_p_i, "fps_pt": fps_u_i, "F_pt": Tpt,
        })

    # Pure tension
    As_all = As_tens_total + As_comp_total
    Pn_tens = As_all * fy + (Aps * fpy if Aps > 0 else 0)
    phi_tens = get_phi_flex(code_edition, section_class, 0.01, ecl, etl)
    rows_tens_pt = [{"d_cf": r["d_cf"], "As": r["As"], "es": 99, "fs": fy, "F": r["As"] * fy} for r in tens_rows]
    rows_comp_pt = [{"d_cf": r["d_cf"], "As": r["As"], "es": 99, "fs": fy, "F": r["As"] * fy} for r in comp_rows]
    pts.append({
        "c": 0, "a": 0, "eps_t": 99, "stat": "TC", "phi": phi_tens,
        "Pn": Pn_tens, "Mn": 0, "Pr": Pn_tens * phi_tens, "Mr": 0,
        "es_tens": 99, "fs_tens": fy, "F_tens": As_tens_total * fy,
        "es_comp": 99, "fs_comp": fy, "F_comp": As_comp_total * fy,
        "rows_tens": rows_tens_pt, "rows_comp": rows_comp_pt,
        "eps_pe": eps_pe, "delta_eps": 99, "eps_pt": 99, "fps_pt": fpy if Aps > 0 else 0, "F_pt": Aps * fpy if Aps > 0 else 0,
    })
    return pts


def build_pm_curve_display(I, comp_face="top"):
    """Build the 20-point P-M curve used for the display table (with Pn_max row)."""
    fc, fy, Es, Ept = I["fc"], I["fy"], I["Es"], I["Ept"]
    fpu, fpy, ecl = I["fpu"], I["fpy"], I["ecl"]
    alpha1, beta1, k_pt, etl = I["alpha1"], I["beta1"], I["k_pt"], I["etl"]
    has_pt = I["hasPT"]
    fpe = I.get("fpe", 0)
    eps_pe = fpe / Ept if Ept > 0 else 0
    is_rect, b, h, bw = I["isRect"], I["b"], I["h"], I["bw"]
    hf_top = I["hf_top"]
    hf_bot = I.get("hf_bot", 0)
    As_bot, As_top = I["As_bot"], I["As_top"]
    d_bot, d_top = I["d_bot"], I["d_top"]
    Aps, dp = I["Aps"], I["dp"]
    code_edition, section_class = I["codeEdition"], I["sectionClass"]

    if comp_face == "bottom":
        hf = h if is_rect else hf_bot
        d_tens = h - d_top
        d_comp_s = h - d_bot
        dp_cf = (h - dp) if dp > 0 else 0
        As_tens = As_top
        As_comp_s = As_bot
    else:
        hf = h if is_rect else hf_top
        d_tens = d_bot
        d_comp_s = d_top
        dp_cf = dp
        As_tens = As_bot
        As_comp_s = As_top

    pc_y = h / 2
    Ag = b * h if is_rect else b * hf_top + bw * (h - hf_top - hf_bot) + b * hf_bot
    Pn_max = -0.8 * alpha1 * fc * Ag
    N = 20
    dt = max(d_tens, dp_cf) if Aps > 0 else d_tens

    pts = []
    pts.append({
        "c": 9999, "a": 9999, "eps_t": 0, "stat": "CC", "phi": 0.75,
        "Pn": Pn_max, "Mn": 0, "Pr": Pn_max * 0.75, "Mr": 0,
        "es_tens": 0, "fs_tens": 0, "F_tens": 0,
        "es_comp": 0, "fs_comp": 0, "F_comp": 0,
        "eps_pe": eps_pe, "delta_eps": 0, "eps_pt": eps_pe, "fps_pt": 0, "F_pt": 0,
    })

    for i in range(N, 0, -1):
        ci = dt * i / N
        ai = ci * beta1
        if is_rect or ai <= hf:
            Cc = -alpha1 * fc * b * ai
            ycc = ai / 2
        else:
            Cf = alpha1 * fc * (b - bw) * hf
            Cw = alpha1 * fc * bw * ai
            Cc = -(Cf + Cw)
            ycc = None

        es_tens = 0.003 * (d_tens - ci) / ci
        fs_tens = min(abs(es_tens) * Es, fy) * (1 if es_tens >= 0 else -1)
        F_tens = As_tens * fs_tens

        es_comp_s = 0.003 * (d_comp_s - ci) / ci if ci > 0 else 0
        fs_comp_s = min(abs(es_comp_s) * Es, fy) * (1 if es_comp_s >= 0 else -1)
        F_comp_s = As_comp_s * fs_comp_s

        Tpt = 0
        eps_p_i = 0
        fps_u_i = 0
        delta_eps_i = 0
        if Aps > 0 and dp_cf > 0:
            delta_eps_i = 0.003 * (dp_cf - ci) / ci
            eps_p_i = eps_pe + delta_eps_i
            fps_u_i = min(abs(eps_p_i) * Ept, fpy) * (1 if eps_p_i >= 0 else -1)
            Tpt = Aps * fps_u_i

        Pn = max(Cc + F_tens + F_comp_s + Tpt, Pn_max)

        # Moment about section mid-height (same formula for both comp faces)
        arm_tens = d_tens - pc_y
        arm_comp_s = d_comp_s - pc_y
        arm_pt = dp_cf - pc_y if Aps > 0 else 0
        if is_rect or ai <= hf:
            Mn_cc = -Cc * (pc_y - ycc)
        else:
            Mn_cc = Cf * (pc_y - hf / 2) + Cw * (pc_y - ai / 2)

        Mn_i = (Mn_cc + F_tens * arm_tens + F_comp_s * arm_comp_s
                + (Tpt * arm_pt if Aps > 0 else 0))

        et_i = 0.003 * (dt - ci) / ci
        phi_i = get_phi_flex(code_edition, section_class, et_i, ecl, etl)
        st = "TC" if abs(et_i) >= etl else ("CC" if abs(et_i) <= ecl else "TR")

        pts.append({
            "c": ci, "a": ai, "eps_t": abs(et_i), "stat": st, "phi": phi_i,
            "Pn": Pn, "Mn": Mn_i, "Pr": Pn * phi_i, "Mr": Mn_i * phi_i,
            "es_tens": es_tens, "fs_tens": fs_tens, "F_tens": F_tens,
            "es_comp": es_comp_s, "fs_comp": fs_comp_s, "F_comp": F_comp_s,
            "eps_pe": eps_pe, "delta_eps": delta_eps_i, "eps_pt": eps_p_i, "fps_pt": fps_u_i, "F_pt": Tpt,
        })

    Pn_tens = As_tens * fy + As_comp_s * fy + (Aps * fpy if Aps > 0 else 0)
    phi_tens = get_phi_flex(code_edition, section_class, 0.01, ecl, etl)
    pts.append({
        "c": 0, "a": 0, "eps_t": 99, "stat": "TC", "phi": phi_tens,
        "Pn": Pn_tens, "Mn": 0, "Pr": Pn_tens * phi_tens, "Mr": 0,
        "es_tens": 99, "fs_tens": fy, "F_tens": As_tens * fy,
        "es_comp": 99, "fs_comp": fy, "F_comp": As_comp_s * fy,
        "eps_pe": eps_pe, "delta_eps": 99, "eps_pt": 99, "fps_pt": fpy if Aps > 0 else 0, "F_pt": Aps * fpy if Aps > 0 else 0,
    })
    return pts


def get_mr_at_pu(pm_curve, Pu):
    """Interpolate Mr from factored P-M curve at given Pu."""
    max_mr = 0
    for i in range(len(pm_curve) - 1):
        p1, p2 = pm_curve[i], pm_curve[i + 1]
        lo = min(p1["Pr"], p2["Pr"])
        hi = max(p1["Pr"], p2["Pr"])
        if Pu >= lo and Pu <= hi:
            if abs(p2["Pr"] - p1["Pr"]) < 1e-10:
                max_mr = max(max_mr, p1["Mr"], p2["Mr"])
            else:
                t = (Pu - p1["Pr"]) / (p2["Pr"] - p1["Pr"])
                max_mr = max(max_mr, p1["Mr"] + t * (p2["Mr"] - p1["Mr"]))
    return max_mr


def get_pm_equilibrium_at_pu(pm_data, Pu):
    """Find the P-M display point closest to Pr = Pu and interpolate c, strains, stresses."""
    # Find the segment where Pr crosses Pu with maximum Mr (tension side)
    best = None
    best_mr = 0
    for i in range(len(pm_data) - 1):
        p1, p2 = pm_data[i], pm_data[i + 1]
        lo = min(p1.get("Pr", 0), p2.get("Pr", 0))
        hi = max(p1.get("Pr", 0), p2.get("Pr", 0))
        if Pu >= lo and Pu <= hi:
            dPr = p2["Pr"] - p1["Pr"]
            if abs(dPr) < 1e-10:
                t = 0.5
            else:
                t = (Pu - p1["Pr"]) / dPr
            t = max(0, min(1, t))
            mr_interp = p1["Mr"] + t * (p2["Mr"] - p1["Mr"])
            if mr_interp >= best_mr:
                best_mr = mr_interp
                result = {}
                for key in ["c", "a", "eps_t", "phi", "Pn", "Mn", "Pr", "Mr",
                            "es_tens", "fs_tens", "F_tens", "es_comp", "fs_comp", "F_comp",
                            "eps_pe", "delta_eps", "eps_pt", "fps_pt", "F_pt"]:
                    v1 = p1.get(key)
                    v2 = p2.get(key)
                    if v1 is not None and v2 is not None and isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                        # Only skip interpolation for sentinel values on c/a/strain keys (pure compression c=9999)
                        if key in ("c", "a", "eps_t", "es_tens", "es_comp", "eps_pt", "delta_eps") and (abs(v1) > 9000 or abs(v2) > 9000):
                            result[key] = v1
                        else:
                            result[key] = v1 + t * (v2 - v1)
                    else:
                        result[key] = v1
                # Interpolate per-row arrays (rows_tens, rows_comp)
                for arr_key in ("rows_tens", "rows_comp"):
                    arr1 = p1.get(arr_key, [])
                    arr2 = p2.get(arr_key, [])
                    if arr1 and arr2 and len(arr1) == len(arr2):
                        interp_arr = []
                        for j in range(len(arr1)):
                            rd = {"d_cf": arr1[j]["d_cf"], "As": arr1[j]["As"]}
                            for k in ("es", "fs", "F"):
                                v1r = arr1[j].get(k, 0)
                                v2r = arr2[j].get(k, 0)
                                if isinstance(v1r, (int, float)) and isinstance(v2r, (int, float)):
                                    if k == "es" and (abs(v1r) > 9000 or abs(v2r) > 9000):
                                        rd[k] = v1r
                                    else:
                                        rd[k] = v1r + t * (v2r - v1r)
                                else:
                                    rd[k] = v1r
                            interp_arr.append(rd)
                        result[arr_key] = interp_arr
                    else:
                        result[arr_key] = arr1 if arr1 else arr2
                best = result
    return best


# ─── Flexure ────────────────────────────────────────────────────────

def do_flexure(I, Pu, Mu, Ms, Ps):
    """
    Compute flexural capacity, P-M interaction, cracked section analysis.
    Sign convention:
      Positive Mu -> top in compression, bottom in tension (sagging)
      Negative Mu -> bottom in compression, top in tension (hogging)
    """
    fc, fy, Es, Ept = I["fc"], I["fy"], I["Es"], I["Ept"]
    fpu, fpy, ecl = I["fpu"], I["fpy"], I["ecl"]
    alpha1, beta1, k_pt, etl = I["alpha1"], I["beta1"], I["k_pt"], I["etl"]
    is_rect, b, h, bw = I["isRect"], I["b"], I["h"], I["bw"]
    hf_top, hf_bot = I["hf_top"], I["hf_bot"]
    As_top, As_bot = I["As_top"], I["As_bot"]
    d_top, d_bot = I["d_top"], I["d_bot"]
    bar_d_top, bar_d_bot = I["bar_d_top"], I["bar_d_bot"]
    Aps, dp, cover = I["Aps"], I["dp"], I["cover"]
    n_mod, Ec = I["n_mod"], I["Ec"]
    gamma_e = I["gamma_e"]
    code_edition, section_class = I["codeEdition"], I["sectionClass"]

    # Assign tension/compression based on moment sign
    # All depths measured from the compression face
    if Mu >= 0:
        # Positive moment: top in compression
        As = As_bot          # tension steel (bottom bars)
        ds = d_bot           # depth of tension steel from top (comp face)
        As_comp = As_top     # compression steel (top bars)
        d_s_comp = d_top     # depth of comp steel from top (comp face)
        hf = hf_top if not is_rect else ds  # compression flange depth
        bar_d_tens = bar_d_bot
        bar_d_comp = bar_d_top
        nBars_tens = I["nBars_bot"]
        nBars_comp = I["nBars_top"]
        barN_tens = I["barN_bot"]
        barN_comp = I["barN_top"]
        comp_face = "top"
    else:
        # Negative moment: bottom in compression
        As = As_top          # tension steel (top bars)
        ds = h - d_top       # depth of top bars from bottom (comp face)
        As_comp = As_bot     # compression steel (bottom bars)
        d_s_comp = h - d_bot # depth of bottom bars from bottom (comp face)
        hf = hf_bot if not is_rect else ds  # compression flange depth (bottom flange)
        bar_d_tens = bar_d_top
        bar_d_comp = bar_d_bot
        nBars_tens = I["nBars_top"]
        nBars_comp = I["nBars_bot"]
        barN_tens = I["barN_top"]
        barN_comp = I["barN_bot"]
        # PT depth from bottom face
        dp = h - dp if dp > 0 else 0
        comp_face = "bottom"

    bv = b if is_rect else bw

    # ── Neutral axis (Whitney, pure bending Pu=0) ──
    na_breakdown = EqBreakdown("Neutral Axis (Pure Bending, c from strain compatibility)")

    denom_R_input = alpha1 * fc * beta1 * b + (k_pt * Aps * fpu / dp if Aps > 0 and dp > 0 else 0)
    denom_R = denom_R_input

    # AASHTO simplified approach:
    # 1) Trial c assuming f's = fy (include A's)
    # 2) Check c_trial >= 3·d's AND fy <= 60 ksi
    # 3) If fails → redo c without A's, exclude A's from Mn
    # P-M strain compatibility check always handles compression steel correctly.
    comp_steel_yields = False
    c_trial = 0
    if As_comp > 0 and d_s_comp > 0:
        numer_with = As * fy + (Aps * fpu if Aps > 0 else 0) - As_comp * fy
        c_trial = numer_with / denom_R if denom_R > 0 else 0.01
        if c_trial <= 0:
            c_trial = 0.01
        comp_steel_yields = (c_trial >= 3 * d_s_comp) and (fy <= 60)

        if comp_steel_yields:
            c = c_trial
            na_breakdown.add(f"Trial c with A's·fy: c = {fmt_num(c_trial, 4)} in",
                            f"c ≥ 3·d's = {fmt_num(3*d_s_comp, 3)}? YES, fy ≤ 60? YES → compression steel yields, include A's",
                            c_trial, "in")
        else:
            numer_without = As * fy + (Aps * fpu if Aps > 0 else 0)
            c = numer_without / denom_R if denom_R > 0 else 0.01
            if c <= 0:
                c = 0.01
            na_breakdown.add(f"Trial c with A's·fy: c = {fmt_num(c_trial, 4)} in",
                            f"c ≥ 3·d's = {fmt_num(3*d_s_comp, 3)}? {'YES' if c_trial >= 3*d_s_comp else 'NO'}, fy ≤ 60? {'YES' if fy <= 60 else 'NO'} → A's excluded",
                            c_trial, "in")
            na_breakdown.add(f"Re-solve c without A's",
                            f"c = ({fmt_num(As, 2)}·{fmt_num(fy, 0)} + {fmt_num(Aps, 2)}·{fmt_num(fpu, 0)}) / {fmt_num(denom_R, 2)}",
                            c, "in")
    else:
        c = (As * fy + (Aps * fpu if Aps > 0 else 0)) / denom_R if denom_R > 0 else 0.01
        if c <= 0:
            c = 0.01
        comp_steel_yields = True  # no compression steel to worry about

    # Denominator breakdown
    if Aps > 0 and dp > 0:
        na_breakdown.add(f"denom = α₁·fc·β₁·b + k·Aps·fpu/dp",
                        f"= {fmt_num(alpha1, 3)}·{fmt_num(fc, 1)}·{fmt_num(beta1, 3)}·{fmt_num(b, 1)} + {fmt_num(k_pt, 4)}·{fmt_num(Aps, 2)}·{fmt_num(fpu, 0)}/{fmt_num(dp, 1)}",
                        denom_R_input, "")
    else:
        na_breakdown.add(f"denom = α₁·fc·β₁·b",
                        f"= {fmt_num(alpha1, 3)}·{fmt_num(fc, 1)}·{fmt_num(beta1, 3)}·{fmt_num(b, 1)}",
                        denom_R_input, "")
    if comp_steel_yields and As_comp > 0:
        na_breakdown.add(f"c = (As·fy + Aps·fpu − A's·fy) / denom",
                        f"= ({fmt_num(As, 2)}·{fmt_num(fy, 0)} + {fmt_num(Aps, 2)}·{fmt_num(fpu, 0)} − {fmt_num(As_comp, 2)}·{fmt_num(fy, 0)}) / {fmt_num(denom_R, 2)}",
                        c, "in")
    else:
        na_breakdown.add(f"c = (As·fy + Aps·fpu) / denom",
                        f"= ({fmt_num(As, 2)}·{fmt_num(fy, 0)} + {fmt_num(Aps, 2)}·{fmt_num(fpu, 0)}) / {fmt_num(denom_R, 2)}",
                        c, "in")

    a = c * beta1
    na_breakdown.add(f"a = β₁·c",
                    f"= {fmt_num(beta1, 3)}·{fmt_num(c, 3)}", a, "in")

    # T-section check: if a > hf, re-solve with T-section formula
    if not is_rect and a > hf and hf > 0:
        denom_T_input = alpha1 * fc * beta1 * bw + (k_pt * Aps * fpu / dp if Aps > 0 and dp > 0 else 0)
        flange_comp = alpha1 * fc * (b - bw) * hf
        if comp_steel_yields and As_comp > 0:
            numer_T = As * fy + (Aps * fpu if Aps > 0 else 0) - As_comp * fy
        else:
            numer_T = As * fy + (Aps * fpu if Aps > 0 else 0)
        c_T = (numer_T - flange_comp) / denom_T_input if denom_T_input > 0 else c
        if c_T > 0:
            na_breakdown.add(f"T-section re-solve: c = (numer − α₁·fc·(b−bw)·hf) / denom_T",
                            f"NA extends into web: c_T = {fmt_num(c_T, 3)} in",
                            c_T, "in")
            c = c_T
    if c <= 0:
        c = 0.01
    a = c * beta1

    # ── PT in compression zone check ──
    # AASHTO defines Aps as area on the flexural TENSION side.
    # If dp (from comp face) < c, the tendon is inside the compression zone
    # and should not be included in the simplified equilibrium.
    pt_in_compression = (Aps > 0 and dp > 0 and dp < c)
    if pt_in_compression:
        na_breakdown.add(f"dp = {fmt_num(dp, 2)} < c = {fmt_num(c, 3)} → PT in compression zone, re-solve without Aps",
                        f"Tendon excluded from simplified equilibrium (Aps on tension side = 0)",
                        0, "")
        # Re-solve c without any Aps contribution
        denom_R_noAps = alpha1 * fc * beta1 * b
        if comp_steel_yields and As_comp > 0:
            c = (As * fy - As_comp * fy) / denom_R_noAps if denom_R_noAps > 0 else 0.01
        else:
            c = (As * fy) / denom_R_noAps if denom_R_noAps > 0 else 0.01
        if c <= 0:
            c = 0.01
        a = c * beta1
        # T-section re-check without Aps
        if not is_rect and a > hf and hf > 0:
            denom_T_noAps = alpha1 * fc * beta1 * bw
            if comp_steel_yields and As_comp > 0:
                numer_T = As * fy - As_comp * fy
            else:
                numer_T = As * fy
            flange_comp = alpha1 * fc * (b - bw) * hf
            c_T = (numer_T - flange_comp) / denom_T_noAps if denom_T_noAps > 0 else c
            if c_T > 0:
                c = c_T
        if c <= 0:
            c = 0.01
        a = c * beta1
        na_breakdown.add(f"Re-solved c (no Aps): c = {fmt_num(c, 4)} in, a = {fmt_num(a, 4)} in",
                        f"", c, "in")

    # Aps_tens: area of prestressing steel on the tension side (for de, dv, shear)
    Aps_tens = 0 if pt_in_compression else Aps
    fps_calc = fpu * (1 - k_pt * c / dp) if Aps_tens > 0 and dp > 0 else 0

    # ── c/ds check (5.6.2.1-1): verify fs = fy assumption ──
    c_ds_ratio = c / ds if ds > 0 else 0
    c_ds_limit = 0.003 / (0.003 + ecl) if ecl > 0 else 1.0
    c_ds_ok = c_ds_ratio <= c_ds_limit
    use_strain_compat = not c_ds_ok

    # Compression steel strain/stress at final c (for reporting)
    if As_comp > 0 and d_s_comp > 0:
        eps_comp = 0.003 * (c - d_s_comp) / c if c > 0 else 0
        fs_comp = fy if comp_steel_yields else min(abs(eps_comp) * Es, fy) if c > d_s_comp else 0
    else:
        eps_comp = 0
        fs_comp = 0

    # ── Mn (pure bending) ──
    mn_breakdown = EqBreakdown("Moment Capacity (Mn at Pu = 0)")

    # Compression steel contribution to Mn (AASHTO Eq. 5.6.3.2.2-1):
    # Mn = As·fy·(ds−a/2) + Aps·fps·(dp−a/2) + A's·f's·(a/2 − d's)
    # The last term adds capacity when d's < a/2, reduces when d's > a/2.
    comp_Mn = As_comp * fs_comp * (a / 2 - d_s_comp) if comp_steel_yields and As_comp > 0 else 0

    if is_rect or a <= hf:
        # Rectangular behavior: entire compression block within flange
        Ts = As * fy
        mom_arm_s = ds - a / 2
        Mn_s = Ts * mom_arm_s if Ts > 0 else 0
        
        Aps_contrib = 0
        if Aps_tens > 0:
            Aps_contrib = Aps_tens * fps_calc * (dp - a / 2)
            mn_breakdown.add(f"Ts = As·fy = {fmt_num(As, 2)}·{fmt_num(fy, 0)}",
                            f"", Ts, "kip")
            mn_breakdown.add(f"Tps = Aps·fps = {fmt_num(Aps_tens, 2)}·{fmt_num(fps_calc, 1)}",
                            f"", Aps_tens * fps_calc, "kip")
            mn_breakdown.add(f"Mn = As·fy·(ds − a/2) + Aps·fps·(dp − a/2)" + (f" + A's·f's·(a/2 − d's)" if comp_steel_yields and As_comp > 0 else ""),
                            f"= {fmt_num(As, 2)}·{fmt_num(fy, 0)}·({fmt_num(ds, 2)} − {fmt_num(a/2, 2)}) + {fmt_num(Aps_tens, 2)}·{fmt_num(fps_calc, 1)}·({fmt_num(dp, 2)} − {fmt_num(a/2, 2)})"
                            + (f" + {fmt_num(As_comp, 2)}·{fmt_num(fs_comp, 1)}·({fmt_num(a/2, 2)} − {fmt_num(d_s_comp, 2)})" if comp_steel_yields and As_comp > 0 else ""),
                            Mn_s + Aps_contrib + comp_Mn, "kip-in")
        else:
            mn_breakdown.add(f"Ts = As·fy = {fmt_num(As, 2)}·{fmt_num(fy, 0)}",
                            f"", Ts, "kip")
            if pt_in_compression:
                mn_breakdown.add(f"PT tendon in compression zone (dp < c) → Aps excluded",
                                f"", 0, "")
            mn_breakdown.add(f"Mn = As·fy·(ds − a/2)" + (f" + A's·f's·(a/2 − d's)" if comp_steel_yields and As_comp > 0 else ""),
                            f"= {fmt_num(As, 2)}·{fmt_num(fy, 0)}·({fmt_num(ds, 2)} − {fmt_num(a/2, 2)})"
                            + (f" + {fmt_num(As_comp, 2)}·{fmt_num(fs_comp, 1)}·({fmt_num(a/2, 2)} − {fmt_num(d_s_comp, 2)})" if comp_steel_yields and As_comp > 0 else ""),
                            Mn_s + comp_Mn, "kip-in")
        
        Mn = Mn_s + Aps_contrib + comp_Mn
    else:
        # T-section: compression block extends into web
        Cf = alpha1 * fc * (b - bw) * hf   # force from overhanging flanges
        Cw = alpha1 * fc * bw * a           # force from web rectangle
        mn_breakdown.add(f"T-section: Cf = α₁·fc·(b−bw)·hf",
                        f"= {fmt_num(alpha1, 3)}·{fmt_num(fc, 1)}·({fmt_num(b, 1)}−{fmt_num(bw, 1)})·{fmt_num(hf, 2)}", Cf, "kip")
        mn_breakdown.add(f"Cw = α₁·fc·bw·a",
                        f"= {fmt_num(alpha1, 3)}·{fmt_num(fc, 1)}·{fmt_num(bw, 1)}·{fmt_num(a, 3)}", Cw, "kip")
        
        Mn = (Cf * (ds - hf / 2) + Cw * (ds - a / 2)
              + (Aps_tens * fps_calc * (dp - a / 2) if Aps_tens > 0 else 0)
              + (As_comp * fs_comp * (a / 2 - d_s_comp) if comp_steel_yields and As_comp > 0 else 0))
        mn_breakdown.add(f"Mn = Cf·(ds−hf/2) + Cw·(ds−a/2)" + (f" + Aps·fps·(dp−a/2)" if Aps_tens > 0 else "") + (f" + A's·f's·(a/2−d's)" if comp_steel_yields and As_comp > 0 else ""),
                        f"= {fmt_num(Cf, 1)}·({fmt_num(ds, 2)}−{fmt_num(hf/2, 2)}) + {fmt_num(Cw, 1)}·({fmt_num(ds, 2)}−{fmt_num(a/2, 2)})"
                        + (f" + {fmt_num(Aps_tens*fps_calc, 1)}·({fmt_num(dp, 2)}−{fmt_num(a/2, 2)})" if Aps_tens > 0 else "")
                        + (f" + {fmt_num(As_comp*fs_comp, 1)}·({fmt_num(a/2, 2)}−{fmt_num(d_s_comp, 2)})" if comp_steel_yields and As_comp > 0 else ""),
                        Mn, "kip-in")

    # Clamp Mn to 0 when no tension reinforcement exists
    if As <= 0 and Aps <= 0:
        Mn = 0

    # ── Strain & phi ──
    phi_breakdown = EqBreakdown("Reduction Factor (φ) Calculation")
    
    dt = max(ds, dp) if Aps_tens > 0 else ds
    if Aps_tens > 0:
        phi_breakdown.add(f"dt = max(ds, dp) = max({fmt_num(ds, 3)}, {fmt_num(dp, 3)})",
                         f"", dt, "in")
    elif pt_in_compression:
        phi_breakdown.add(f"dt = ds (PT in compression zone, dp excluded)",
                         f"= {fmt_num(ds, 3)}", dt, "in")
    else:
        phi_breakdown.add(f"dt = ds = {fmt_num(ds, 3)}",
                         f"", dt, "in")
    
    eps_t = 0.003 * (dt - c) / c if c > 0 else 99
    phi_breakdown.add(f"εt = 0.003·(dt − c)/c = 0.003·({fmt_num(dt, 3)} − {fmt_num(c, 3)})/{fmt_num(c, 3)}",
                     f"", eps_t, "")
    
    phi_breakdown.add(f"εcl = {fmt_num(ecl, 4)}, εtl = {fmt_num(etl, 4)}",
                     f"", 0, "")
    
    phi_f = get_phi_flex(code_edition, section_class, eps_t, ecl, etl)
    if abs(eps_t) >= etl:
        sec_status = "TENSION CONTROLLED"
        phi_breakdown.add(f"εt = {fmt_num(eps_t, 4)} ≥ εtl = {fmt_num(etl, 4)} → TENSION CONTROLLED → φ = {fmt_num(phi_f, 2)}",
                         f"", phi_f, "")
    elif abs(eps_t) <= ecl:
        sec_status = "COMPRESSION CONTROLLED"
        phi_breakdown.add(f"εt = {fmt_num(eps_t, 4)} ≤ εcl = {fmt_num(ecl, 4)} → COMPRESSION CONTROLLED → φ = {fmt_num(phi_f, 2)}",
                         f"", phi_f, "")
    else:
        sec_status = "TRANSITION"
        phi_breakdown.add(f"φ = 0.75 + k·(εt − εcl)/(εtl − εcl) [TRANSITION]",
                         f"= 0.75 + {fmt_num(phi_f - 0.75, 3)}", phi_f, "")
    
    Mr = phi_f * Mn
    phi_breakdown.add(f"Mr = φ·Mn = {fmt_num(phi_f, 2)}·{fmt_num(Mn, 1)}",
                     f"reduced moment capacity (design strength)", Mr, "kip-in")

    # ── dv (5.7.2.8) ──
    tot_tens = As * fy + (Aps_tens * fps_calc if Aps_tens > 0 else 0)
    dv1 = Mn / tot_tens if tot_tens > 0 else 0
    dv2 = 0.72 * h
    if Aps_tens > 0 and As > 0:
        de = (Aps_tens * fps_calc * dp + As * fy * ds) / tot_tens
    elif Aps_tens > 0:
        de = dp
    else:
        de = ds
    dv3 = 0.9 * de
    dv = max(dv1, dv2, dv3)

    # ── P-M Interaction Diagram ──
    pm_curve = build_pm_curve(I, comp_face)
    pm_data = pm_curve  # single curve for display and interpolation
    Mr_atPu = get_mr_at_pu(pm_curve, Pu)
    pm_eq = get_pm_equilibrium_at_pu(pm_curve, Pu)

    # ── Minimum flexure reinforcement (5.6.3.3) ──
    gamma1 = 1.6
    # γ3 per Table 5.6.3.3-1: 0.67 for Grade 60, 0.75 for Grade 75/80/100
    gamma3 = 0.67 if fy <= 60 else 0.75
    fr = 0.24 * math.sqrt(fc) if fc > 0 else 0
    if is_rect:
        Sc = b * h * h / 6
    else:
        A1, y1 = b * hf_top, hf_top / 2
        hw = h - hf_top - hf_bot
        A2, y2 = bw * hw, hf_top + hw / 2
        A3, y3 = b * hf_bot, hf_top + hw + hf_bot / 2
        At = A1 + A2 + A3
        yb = (A1 * y1 + A2 * y2 + A3 * y3) / At if At > 0 else h / 2
        It = (b * hf_top ** 3 / 12 + A1 * (yb - y1) ** 2
              + bw * hw ** 3 / 12 + A2 * (yb - y2) ** 2
              + b * hf_bot ** 3 / 12 + A3 * (yb - y3) ** 2)
        Sc = It / max(yb, h - yb) if max(yb, h - yb) > 0 else 0
    Mcr = gamma1 * gamma3 * fr * Sc
    Mcond = min(1.33 * abs(Mu), Mcr)
    min_flex_ok = Mr >= Mcond

    # ── Crack control (5.6.7) ──
    dc = cover + bar_d_tens / 2
    beta_s = 1 + dc / (0.7 * (h - dc)) if (h - dc) > 0 else 1
    fss_simp = 0.6 * fy
    s_crack = (700 * gamma_e) / (beta_s * fss_simp) - 2 * dc if (beta_s * fss_simp) > 0 else 0

    # ── Spacing (5.10.3) ──
    s_min_ck = max(1.5 * bar_d_tens, 1.5 * I["ag"], 1.5)
    s_max_ck = min(1.5 * h, 18)

    # ── Cracked section (service) — uses Ms sign independently of Mu ──
    # Determine service tension/compression assignment based on Ms sign
    if Ms >= 0:
        # Positive service moment: top in compression
        s_As = As_bot;  s_ds = d_bot
        s_As_comp = As_top;  s_d_s_comp = d_top
        s_hf = hf_top if not is_rect else s_ds
        s_dp = I["dp"]
        s_comp_face = "top"
    else:
        # Negative service moment: bottom in compression
        s_As = As_top;  s_ds = h - d_top
        s_As_comp = As_bot;  s_d_s_comp = h - d_bot
        s_hf = hf_bot if not is_rect else s_ds
        s_dp = (h - I["dp"]) if I["dp"] > 0 else 0
        s_comp_face = "bottom"

    nAs = s_As * n_mod
    n_pt = Ept / Ec if Aps > 0 and Ec > 0 else 0
    nAps = Aps * n_pt
    if is_rect or s_hf >= h:
        # Rectangular section
        qa = b / 2
        qb_val = nAs + nAps
        qc_val = -(nAs * s_ds + nAps * s_dp)
        disc = qb_val * qb_val - 4 * qa * qc_val
        c_cr = (-qb_val + math.sqrt(disc)) / (2 * qa) if disc > 0 and qa > 0 else 0
        Icr = b * c_cr ** 3 / 3 + nAs * (s_ds - c_cr) ** 2 + (nAps * (s_dp - c_cr) ** 2 if Aps > 0 else 0)
    else:
        # T-section: try cracked NA within flange first
        qa = b / 2
        qb_val = nAs + nAps
        qc_val = -(nAs * s_ds + nAps * s_dp)
        disc = qb_val * qb_val - 4 * qa * qc_val
        c_cr = (-qb_val + math.sqrt(disc)) / (2 * qa) if disc > 0 and qa > 0 else 0
        if c_cr > s_hf:
            # NA extends into web — re-solve with T-section quadratic
            qa_t = bw / 2
            qb_t = nAs + nAps + (b - bw) * s_hf
            qc_t = -(nAs * s_ds + nAps * s_dp + (b - bw) * s_hf * s_hf / 2)
            disc_t = qb_t * qb_t - 4 * qa_t * qc_t
            c_cr = (-qb_t + math.sqrt(disc_t)) / (2 * qa_t) if disc_t > 0 and qa_t > 0 else 0
        if c_cr <= s_hf:
            Icr = b * c_cr ** 3 / 3 + nAs * (s_ds - c_cr) ** 2 + (nAps * (s_dp - c_cr) ** 2 if Aps > 0 else 0)
        else:
            # Icr for T with NA in web
            Icr = (b * s_hf ** 3 / 12 + b * s_hf * (c_cr - s_hf / 2) ** 2
                   + bw * (c_cr - s_hf) ** 3 / 3
                   + nAs * (s_ds - c_cr) ** 2
                   + (nAps * (s_dp - c_cr) ** 2 if Aps > 0 else 0))

    # Service stress breakdown
    serv_breakdown = EqBreakdown("Service Flexure Stress (Cracked Section Analysis)")
    
    M_serv = abs(Ms)
    addlBM = Ps * (h / 2 - c_cr)
    M_total_serv = M_serv + addlBM
    
    serv_breakdown.add(f"Ms (service moment demand)", f"", M_serv, "kip-in")
    if Ps != 0:
        serv_breakdown.add(f"Additional BM = Ps·(h/2 - c_cr) = {fmt_num(Ps, 1)}·({fmt_num(h/2, 2)} - {fmt_num(c_cr, 2)})",
                          f"secondary moment from axial offset", addlBM, "kip-in")
        serv_breakdown.add(f"Ms_total = Ms + addl_BM", f"", M_total_serv, "kip-in")
    
    fss = (M_total_serv * (s_ds - c_cr) / Icr * n_mod + Ps / (nAs + nAps + c_cr * b) * n_mod) if Icr > 0 else 0
    serv_breakdown.add(f"fss = M·(ds-c_cr)/Icr·n + Ps·n/(transformed area)",
                      f"service rebar stress = {fmt_num(M_total_serv, 1)}·{fmt_num(s_ds - c_cr, 2)}/{fmt_num(Icr, 1)}·{fmt_num(n_mod, 2)}",
                      fss, "ksi")
    
    fps_serv = (M_total_serv * (s_dp - c_cr) / Icr * n_pt) if Aps > 0 and Icr > 0 else 0
    if Aps > 0 and fps_serv > 0:
        serv_breakdown.add(f"fps_serv = M·(dp-c_cr)/Icr·npt",
                          f"service strand stress", fps_serv, "ksi")
    
    eps_rb = fss / Es if Es > 0 else 0
    curv = abs(eps_rb / (s_ds - c_cr)) if (s_ds - c_cr) != 0 else 0

    # Ig — gross moment of inertia (compute before Ieff)
    if is_rect:
        Ig = b * h ** 3 / 12
        yt_serv = h / 2
    else:
        A1, y1 = b * hf_top, hf_top / 2
        hw = h - hf_top - hf_bot
        A2, y2 = bw * hw, hf_top + hw / 2
        A3, y3 = b * hf_bot, hf_top + hw + hf_bot / 2
        At_g = A1 + A2 + A3
        yb_g = (A1 * y1 + A2 * y2 + A3 * y3) / At_g if At_g > 0 else h / 2
        Ig = (b * hf_top ** 3 / 12 + A1 * (yb_g - y1) ** 2
              + bw * hw ** 3 / 12 + A2 * (yb_g - y2) ** 2
              + b * hf_bot ** 3 / 12 + A3 * (yb_g - y3) ** 2)
        yt_serv = max(yb_g, h - yb_g)

    # Ieff — Branson's equation: Ie = (Mcr/Ma)^3 * Ig + [1-(Mcr/Ma)^3] * Icr
    Mcr_serv = fr * Ig / yt_serv if yt_serv > 0 else 0
    Ma = abs(M_total_serv) if abs(M_total_serv) > 0 else 1e-10
    ratio = min(Mcr_serv / Ma, 1.0) if Ma > 0 else 1.0
    Ieff = ratio ** 3 * Ig + (1 - ratio ** 3) * Icr
    Ieff = min(Ieff, Ig)  # cannot exceed Ig

    # ── Phi factor details ──
    if code_edition == "CA":
        phi_cc = 0.75
        if section_class == "PP":
            phi_tc, phi_k = 1.0, 0.25
        elif section_class == "CIP_PT":
            phi_tc, phi_k = 0.95, 0.20
        else:
            phi_tc, phi_k = 0.9, 0.15
    else:
        phi_cc = 0.75
        if section_class in ("PP", "CIP_PT"):
            phi_tc, phi_k = 1.0, 0.25
        else:
            phi_tc, phi_k = 0.9, 0.15

    return {
        # Core results
        "c": c, "a": a, "beta1": beta1, "alpha1": alpha1, "dt": dt, "eps_t": eps_t,
        "sec_status": sec_status, "phi_f": phi_f, "fps_calc": fps_calc,
        "Mn": Mn, "Mr": Mr, "Mr_atPu": Mr_atPu,
        # Detailed breakdowns for reporting
        "breakdown_na": na_breakdown.to_dict(),
        "breakdown_mn": mn_breakdown.to_dict(),
        "breakdown_phi": phi_breakdown.to_dict(),
        "breakdown_serv": serv_breakdown.to_dict(),
        "dv": dv, "dv1": dv1, "dv2": dv2, "dv3": dv3, "de": de,
        "bv": bv, "tot_tens": tot_tens,
        # c/ds check (5.6.2.1-1)
        "c_ds_ratio": c_ds_ratio, "c_ds_limit": c_ds_limit, "c_ds_ok": c_ds_ok,
        "use_strain_compat": use_strain_compat,
        # Compression steel
        "comp_steel_yields": comp_steel_yields, "c_trial": c_trial, "d_s_comp": d_s_comp,
        "eps_comp": eps_comp, "fs_comp": fs_comp,
        # Strain limits
        "ecl": ecl, "etl": etl,
        # Sign convention
        "comp_face": comp_face, "ds": ds, "dp_cf": dp, "As": As, "As_comp": As_comp,
        "As_top": As_top, "As_bot": As_bot, "d_top": d_top, "d_bot": d_bot,
        "nBars_tens": nBars_tens, "nBars_comp": nBars_comp,
        "barN_tens": barN_tens, "barN_comp": barN_comp,
        "bar_d_tens": bar_d_tens, "bar_d_comp": bar_d_comp, "hf": hf,
        # P-M data
        "pm_data": pm_data, "pm_curve": pm_curve, "pm_eq": pm_eq,
        # Min flexure
        "gamma1": gamma1, "gamma3": gamma3, "fr": fr, "Sc": Sc, "Mcr": Mcr, "Mcond": Mcond, "min_flex_ok": min_flex_ok,
        # Crack control
        "dc": dc, "beta_s": beta_s, "fss_simp": fss_simp, "s_crack": s_crack,
        # Spacing
        "s_min_ck": s_min_ck, "s_max_ck": s_max_ck,
        # Cracked section
        "n_mod": n_mod, "nAs": nAs, "n_pt": n_pt, "nAps": nAps,
        "c_cr": c_cr, "Icr": Icr,
        "M_serv": M_serv, "addlBM": addlBM, "fss": fss, "fps_serv": fps_serv,
        "eps_rb": eps_rb, "curv": curv, "Ieff": Ieff, "Ig": Ig,
        # Service sign (based on Ms, independent of Mu)
        "serv_comp_face": s_comp_face, "serv_ds": s_ds,
        "serv_d_s_comp": s_d_s_comp, "serv_As_comp": s_As_comp,
        "serv_dp": s_dp, "serv_As": s_As,
        # Phi details
        "phi_cc": phi_cc, "phi_tc": phi_tc, "phi_k": phi_k,
        # Section props
        "Aps": Aps, "Aps_tens": Aps_tens, "pt_in_compression": pt_in_compression,
    }


# ─── Torsion Threshold (evaluated before shear) ────────────────────

def compute_torsion_threshold(I, Tu):
    """Check if torsion must be considered per AASHTO 5.7.2.1-3.
    Also computes torsion geometry (Ao, ph, be) needed for Veff in shear."""
    fc, fy, lam, phi_v = I["fc"], I["fy"], I["lam"], I["phi_v"]
    is_rect, b, h, bw, cover = I["isRect"], I["b"], I["h"], I["bw"], I["cover"]
    hf_top, hf_bot = I["hf_top"], I["hf_bot"]
    shBar_d = I["shBar_d"]

    if is_rect:
        pc = 2 * b + 2 * h
        Acp = b * h
    else:
        hw = h - hf_top - hf_bot
        Acp = b * hf_top + bw * hw + b * hf_bot
        pc = (b + hf_top + (b - bw) / 2 + hw + (b - bw) / 2 + hf_bot
              + b + hf_bot + (b - bw) / 2 + hw + (b - bw) / 2 + hf_top)

    be = Acp / pc if pc > 0 else 0
    if is_rect:
        Ao = (b - be) * (h - be)
    else:
        Ao = max((bw - be) * (h - be), (b - be) * (h - be) * 0.5)
    if is_rect:
        ph = (b - 2 * cover - shBar_d) * 2 + (h - 2 * cover - shBar_d) * 2
    else:
        ph = (bw - 2 * cover - shBar_d) * 2 + (h - 2 * cover - shBar_d) * 2

    K = 1
    Tcr = 0.126 * K * lam * math.sqrt(fc) * Acp * Acp / pc if pc > 0 and fc > 0 else 0
    thresh = 0.25 * phi_v * Tcr
    consider = abs(Tu) > thresh

    return {"Tcr": Tcr, "thresh": thresh, "consider": consider,
            "Acp": Acp, "pc": pc, "Ao": Ao, "ph": ph, "be": be}


# ─── Shear ──────────────────────────────────────────────────────────

def do_shear(I, flex, Pu, Mu, Vu, Tu, Vp, tors_info=None):
    """Compute shear capacity (3 methods). Returns dict of all results.
    tors_info: dict from compute_torsion_threshold with consider, Ao, ph."""
    fc, fy, Es, Ept = I["fc"], I["fy"], I["Es"], I["Ept"]
    fpu, ecl, ag, lam = I["fpu"], I["ecl"], I["ag"], I["lam"]
    phi_v = I["phi_v"]
    is_rect, b, h, bw = I["isRect"], I["b"], I["h"], I["bw"]
    hf_top, hf_bot = I["hf_top"], I["hf_bot"]
    # Get tension/compression steel from flexure result (sign-adjusted)
    As = flex["As"]
    ds = flex["ds"]
    Aps = I["Aps"]
    Aps_tens = flex.get("Aps_tens", Aps)  # tension-side PT only
    dp = I["dp"]
    # For negative moment, dp is from comp face — already adjusted in do_flexure
    # But do_shear is called after do_flexure, and dp in I is still the original
    # We need dp as used in flexure (from the compression face)
    if Mu < 0 and dp > 0:
        dp = h - dp
    duct_dia = I["ductDia"]
    Av, s_shear = I["Av"], I["s_shear"]
    beta1, alpha1, k_pt = I["beta1"], I["alpha1"], I["k_pt"]
    fps_calc, phi_f = flex["fps_calc"], flex["phi_f"]
    dv, bv = flex["dv"], flex["bv"]
    Ec = I["Ec"]

    fpo = 0.7 * fpu
    lambda_duct = 1.0
    if duct_dia > 0 and bv > 0:
        lambda_duct = max(1 - 2 * (duct_dia / bv) ** 2, 0.5)

    # Torsion info for Veff (5.7.3.4.2-5)
    torsion_consider = tors_info["consider"] if tors_info else False
    tors_Ao = tors_info["Ao"] if tors_info else 0
    tors_ph = tors_info["ph"] if tors_info else 0

    # Veff per 5.7.3.4.2-5 (solid sections)
    # When torsion must be considered, replace Vu with Veff in strain calcs
    if torsion_consider and tors_Ao > 0:
        tors_shear_comp = 0.9 * tors_ph * abs(Tu) / (2 * tors_Ao)
        Veff = math.sqrt(Vu ** 2 + tors_shear_comp ** 2)
    else:
        tors_shear_comp = 0
        Veff = abs(Vu)

    # V_strain: the shear used in strain equations (Veff when torsion considered, else Vu)
    V_strain = Veff

    Mu_c = max(abs(Mu), abs(V_strain - Vp) * dv)

    # Gross stress check
    hw = h - hf_top - hf_bot if not is_rect else 0
    Ag = b * h if is_rect else b * hf_top + bw * hw + b * hf_bot
    if is_rect:
        Ig = b * h ** 3 / 12
        ybar = h / 2
    else:
        A1, y1 = b * hf_top, hf_top / 2
        A2, y2 = bw * hw, hf_top + hw / 2
        A3, y3 = b * hf_bot, hf_top + hw + hf_bot / 2
        ybar = (A1 * y1 + A2 * y2 + A3 * y3) / Ag if Ag > 0 else h / 2
        Ig = (b * hf_top ** 3 / 12 + A1 * (ybar - y1) ** 2
              + bw * hw ** 3 / 12 + A2 * (ybar - y2) ** 2
              + b * hf_bot ** 3 / 12 + A3 * (ybar - y3) ** 2)
    # Positive Mu: top in compression, bottom in tension
    # stress = P/A ± M*y/I  (sign convention: +Mu causes compression at top)
    yt = ybar         # distance from centroid to top fiber
    yb = h - ybar     # distance from centroid to bottom fiber
    stress_top = Pu / Ag - Mu * yt / Ig if Ag > 0 and Ig > 0 else 0
    stress_bot = Pu / Ag + Mu * yb / Ig if Ag > 0 and Ig > 0 else 0
    flex_compr = min(stress_top, stress_bot)
    fr = 0.24 * math.sqrt(fc) if fc > 0 else 0
    dbl_eps = flex_compr > fr

    # Strain eps_s (5.7.3.4.2-4) — uses Veff when torsion considered
    denom = Es * As + Ept * Aps_tens
    # Act = area of concrete on tension side (half-depth from flexural tension face)
    if is_rect:
        Act_gp = b * h / 2
    elif Mu >= 0:
        Act_gp = b * hf_bot + bw * max(h / 2 - hf_bot, 0)
    else:
        Act_gp = b * hf_top + bw * max(h / 2 - hf_top, 0)
    Ec_gp = Ec if Ec > 0 else 2500 * fc ** 0.33

    # Min Av (needed before eps_s for denominator factor)
    # When no stirrups are provided (Av=0 or s_shear=0), has_min_av is always False
    if Av <= 0 or s_shear <= 0:
        Av_min = 0
        has_min_av = False
    else:
        Av_min = 0.0316 * math.sqrt(fc) * bv * s_shear / fy if fy > 0 and fc > 0 else 0
        has_min_av = Av >= Av_min

    # Strain eps_s — Eq. 5.7.3.4.2-4 (with min Av) or -5 (without)
    # Denominator: 2*(Es*As + Ep*Aps) when min Av present, else Es*As + Ep*Aps
    eps_denom = 2 * denom if has_min_av else denom
    eps_s = ((Mu_c / dv + 0.5 * Pu + abs(V_strain - Vp) - Aps_tens * fpo) / eps_denom) if eps_denom > 0 else 0.006
    if dbl_eps:
        eps_s *= 2
    eps_s_neg_recalc = False
    if eps_s < 0:
        denom_neg = (2 * (Es * As + Ept * Aps_tens) + Ec_gp * Act_gp) if has_min_av else (Es * As + Ept * Aps_tens + Ec_gp * Act_gp)
        eps_s = ((Mu_c / dv + 0.5 * Pu + abs(V_strain - Vp) - Aps_tens * fpo) / denom_neg) if denom_neg > 0 else 0
        eps_s = max(eps_s, -0.0004)
        eps_s_neg_recalc = True
    eps_s = min(eps_s, 0.006)

    sx = dv
    sxe = min(max(sx * 1.38 / (ag + 0.63), 12), 80) if (ag + 0.63) > 0 else 12

    # METHOD 1: Simplified
    th1, bt1 = 45, 2
    Vc1 = 0.0316 * bt1 * lam * math.sqrt(fc) * bv * dv if fc > 0 else 0
    Vs1 = Av * fy * dv * lambda_duct / math.tan(math.radians(th1)) / s_shear if s_shear > 0 else 0
    Vnmax = 0.25 * fc * bv * dv + Vp
    Vn1 = min(Vc1 + Vs1 + Vp, Vnmax)
    Vr1 = phi_v * Vn1

    # METHOD 2: General Procedure
    bt2a = 4.8 / (1 + 750 * eps_s) if (1 + 750 * eps_s) != 0 else 4.8
    bt2b = bt2a * 51 / (39 + sxe) if (39 + sxe) != 0 else bt2a
    bt2 = bt2a if has_min_av else bt2b
    th2 = 29 + 3500 * eps_s
    Vc2 = 0.0316 * bt2 * lam * math.sqrt(fc) * bv * dv if fc > 0 else 0
    Vs2 = Av * fy * dv * lambda_duct / math.tan(math.radians(th2)) / s_shear if s_shear > 0 and th2 > 0 else 0
    Vn2 = min(Vc2 + Vs2 + Vp, Vnmax)
    Vr2 = phi_v * Vn2

    # METHOD 3: Appendix B5 Iterative
    vu_b5 = abs(Vu - phi_v * Vp) / (phi_v * bv * dv) if (phi_v * bv * dv) != 0 else 0
    vufc = vu_b5 / fc if fc > 0 else 0
    # Act for B5: area on tension side (same logic as Act_gp)
    if is_rect:
        Act = b * h / 2
    elif Mu >= 0:
        Act = b * hf_bot + bw * max(h / 2 - hf_bot, 0)
    else:
        Act = b * hf_top + bw * max(h / 2 - hf_top, 0)
    b5_max_ex = 0.001 if has_min_av else 0.002
    th3, bt3, ex_b5, n_iter, b5_valid = 30, 2, 0, 0, True
    # B5 intermediate values (saved from final iteration for reporting)
    b5_ex_num = 0
    b5_denom_used = 0
    b5_ex_neg_recalc = False
    b5_Vterm = 0
    b5_cot_th = 1

    for it in range(100):
        n_iter = it + 1
        thr = math.radians(th3)
        tan_val = math.tan(thr) if thr > 0 else 1
        cot_val = 1 / tan_val if tan_val != 0 else 1
        ex_num = Mu_c / dv + 0.5 * Pu + 0.5 * abs(V_strain - Vp) * cot_val - Aps_tens * fpo
        b5denom = 2 * denom if has_min_av else denom
        ex = ex_num / b5denom if b5denom > 0 else 0
        b5_ex_neg_recalc_iter = False
        denom_used = b5denom
        if ex < 0:
            Ec_val = Ec if Ec > 0 else 2500 * fc ** 0.33
            b5denom_neg = 2 * (Ec_val * Act + denom)
            ex = ex_num / b5denom_neg if b5denom_neg > 0 else 0
            b5_ex_neg_recalc_iter = True
            denom_used = b5denom_neg
        ex_b5 = ex
        b5_ex_num = ex_num
        b5_denom_used = denom_used
        b5_ex_neg_recalc = b5_ex_neg_recalc_iter
        b5_Vterm = 0.5 * abs(V_strain - Vp) * cot_val
        b5_cot_th = cot_val
        if ex > b5_max_ex:
            b5_valid = False
            break
        tbl = lookup_b5(has_min_av, ex, vufc, sxe)
        if tbl is None:
            b5_valid = False
            break
        th_new, bt_new = tbl["theta"], tbl["beta"]
        if abs(th_new - th3) < 0.01 and abs(bt_new - bt3) < 0.001:
            th3, bt3 = th_new, bt_new
            break
        th3, bt3 = th_new, bt_new

    Vc3, Vs3, Vn3, Vr3 = 0, 0, 0, 0
    if b5_valid:
        Vc3 = 0.0316 * bt3 * lam * math.sqrt(fc) * bv * dv if fc > 0 else 0
        Vs3 = Av * fy * dv * lambda_duct / math.tan(math.radians(th3)) / s_shear if s_shear > 0 and th3 > 0 else 0
        Vn3 = min(Vc3 + Vs3 + Vp, Vnmax)
        Vr3 = phi_v * Vn3

    # ─── Shear Breakdown Instrumentation ────

    # Method 1 Breakdown
    shear_breakdown_m1 = EqBreakdown("Shear Method 1 — AASHTO Simplified (θ=45°, β=2)")
    shear_breakdown_m1.add(
        f"Vc₁ = 0.0316·β₁·λ·√(fc')·bᵥ·dᵥ",
        f"Vc₁ = 0.0316·{fmt_num(bt1, 1)}·{fmt_num(lam, 2)}·√{fmt_num(fc, 0)}·{fmt_num(bv, 1)}·{fmt_num(dv, 1)}",
        Vc1, "kip"
    )
    shear_breakdown_m1.add(
        f"Vs₁ = Av·fy·dᵥ·λ_duct·cot(45°) / s_shear",
        f"Vs₁ = {fmt_num(Av, 2)}·{fmt_num(fy, 0)}·{fmt_num(dv, 1)}·{fmt_num(lambda_duct, 2)}·cot(45°) / {fmt_num(s_shear, 2)}",
        Vs1, "kip"
    )
    shear_breakdown_m1.add(
        f"Vn₁ = min(Vc₁ + Vs₁ + Vp, Vn_max)",
        f"Vn₁ = min({fmt_num(Vc1, 1)}+{fmt_num(Vs1, 1)}+{fmt_num(Vp, 1)}, {fmt_num(Vnmax, 1)})",
        Vn1, "kip"
    )
    shear_breakdown_m1.add(
        f"Vr₁ = φᵥ·Vn₁",
        f"Vr₁ = {fmt_num(phi_v, 2)}·{fmt_num(Vn1, 1)}",
        Vr1, "kip"
    )

    # Method 2 Breakdown
    shear_breakdown_m2 = EqBreakdown("Shear Method 2 — General Procedure with Variable θ & β")
    shear_breakdown_m2.add(
        f"β₂ = 4.8 / (1 + 750·εs)" + (f" (min Av applied)" if has_min_av else f" / [51/(39+sxe)]"),
        f"β₂ = 4.8 / (1 + 750·{fmt_num(eps_s, 5)}) = {fmt_num(bt2a, 3)}" + (f" → {fmt_num(bt2, 3)} (min Av)" if not has_min_av else ""),
        bt2, ""
    )
    shear_breakdown_m2.add(
        f"θ₂ = 29° + 3500·εs",
        f"θ₂ = 29 + 3500·{fmt_num(eps_s, 5)}",
        th2, "°"
    )
    shear_breakdown_m2.add(
        f"Vc₂ = 0.0316·β₂·λ·√(fc')·bᵥ·dᵥ",
        f"Vc₂ = 0.0316·{fmt_num(bt2, 2)}·{fmt_num(lam, 2)}·√{fmt_num(fc, 0)}·{fmt_num(bv, 1)}·{fmt_num(dv, 1)}",
        Vc2, "kip"
    )
    shear_breakdown_m2.add(
        f"Vs₂ = Av·fy·dᵥ·λ_duct·cot(θ₂) / s_shear",
        f"Vs₂ = {fmt_num(Av, 2)}·{fmt_num(fy, 0)}·{fmt_num(dv, 1)}·{fmt_num(lambda_duct, 2)}·cot({fmt_num(th2, 1)}°) / {fmt_num(s_shear, 2)}",
        Vs2, "kip"
    )
    shear_breakdown_m2.add(
        f"Vn₂ = min(Vc₂ + Vs₂ + Vp, Vn_max)",
        f"Vn₂ = min({fmt_num(Vc2, 1)}+{fmt_num(Vs2, 1)}+{fmt_num(Vp, 1)}, {fmt_num(Vnmax, 1)})",
        Vn2, "kip"
    )
    shear_breakdown_m2.add(
        f"Vr₂ = φᵥ·Vn₂",
        f"Vr₂ = {fmt_num(phi_v, 2)}·{fmt_num(Vn2, 1)}",
        Vr2, "kip"
    )

    # Method 3 (B5) Breakdown
    shear_breakdown_m3 = EqBreakdown("Shear Method 3 — Appendix B5 (Iterative Strain Limit)")
    if b5_valid:
        shear_breakdown_m3.add(
            f"εx (strain limit check): ex = (Mu·cot(θ) + 0.5·Pu + ...) / (2·denom)",
            f"εx_max = {fmt_num(b5_max_ex, 4)} vs εx_computed = {fmt_num(ex_b5, 4)}",
            ex_b5, ""
        )
        shear_breakdown_m3.add(
            f"B5 Table Convergence: θ, β from bilinear interpolation (νu/fc', εx)",
            f"Converged after n_iter={n_iter}: θ₃={fmt_num(th3, 1)}°, β₃={fmt_num(bt3, 2)}",
            n_iter, "iterations"
        )
        shear_breakdown_m3.add(
            f"Vc₃ = 0.0316·β₃·λ·√(fc')·bᵥ·dᵥ",
            f"Vc₃ = 0.0316·{fmt_num(bt3, 2)}·{fmt_num(lam, 2)}·√{fmt_num(fc, 0)}·{fmt_num(bv, 1)}·{fmt_num(dv, 1)}",
            Vc3, "kip"
        )
        shear_breakdown_m3.add(
            f"Vs₃ = Av·fy·dᵥ·λ_duct·cot(θ₃) / s_shear",
            f"Vs₃ = {fmt_num(Av, 2)}·{fmt_num(fy, 0)}·{fmt_num(dv, 1)}·{fmt_num(lambda_duct, 2)}·cot({fmt_num(th3, 1)}°) / {fmt_num(s_shear, 2)}",
            Vs3, "kip"
        )
        shear_breakdown_m3.add(
            f"Vn₃ = min(Vc₃ + Vs₃ + Vp, Vn_max)",
            f"Vn₃ = min({fmt_num(Vc3, 1)}+{fmt_num(Vs3, 1)}+{fmt_num(Vp, 1)}, {fmt_num(Vnmax, 1)})",
            Vn3, "kip"
        )
        shear_breakdown_m3.add(
            f"Vr₃ = φᵥ·Vn₃",
            f"Vr₃ = {fmt_num(phi_v, 2)}·{fmt_num(Vn3, 1)}",
            Vr3, "kip"
        )
    else:
        shear_breakdown_m3.add(
            f"B5 Convergence Check",
            f"B5 convergence failed (ex exceeded limit or table lookup invalid)",
            0, "kip"
        )

    # Shear reinf required? (5.7.2.3)
    sh_reqd = abs(Vu) > 0.5 * phi_v * (Vc2 + Vp)

    # Max spacing (5.7.2.6)
    vu = abs(Vu - phi_v * Vp) / (phi_v * bv * dv) if (phi_v * bv * dv) > 0 else 0
    s_max_sh = min(0.8 * dv, 24) if vu < 0.125 * fc else min(0.4 * dv, 12)

    # Longitudinal reinforcement (5.7.3.5-1 without torsion, 5.7.3.6.3-1 with torsion)
    phi_c = 0.75
    Vs_des = min(Vs2, abs(Vu) / phi_v) if phi_v > 0 else Vs2
    cott = 1 / math.tan(math.radians(th2)) if th2 > 0 else 0
    ld_M = abs(Mu) / (dv * phi_f) if (dv * phi_f) > 0 else 0
    ld_N = 0.5 * Pu / phi_c
    ld_V_shear = max(abs(Vu) / phi_v - Vp, 0) - 0.5 * Vs_des if phi_v > 0 else 0
    # Per 5.7.3.6.3-1: when torsion considered, use SRSS of shear and torsion terms
    if torsion_consider and tors_Ao > 0:
        ld_T_tors = 0.45 * tors_ph * abs(Tu) / (2 * tors_Ao * phi_v) if phi_v > 0 else 0
        ld_VT = math.sqrt(max(ld_V_shear, 0) ** 2 + ld_T_tors ** 2)
    else:
        ld_T_tors = 0
        ld_VT = max(ld_V_shear, 0)
    ld_V = ld_V_shear  # keep for display
    long_dem = ld_M + ld_N + ld_VT * cott
    long_cap = As * fy + (Aps_tens * fps_calc if Aps_tens > 0 else 0)
    long_ok = long_cap >= long_dem

    # Per AASHTO 5.7.2.3: transverse reinf required if Vu > 0.5φ(Vc+Vp)
    # OR where torsion must be considered (Tu > 0.25φTcr per 5.7.2.1-3)
    sh_reqd_shear = abs(Vu) > 0.5 * phi_v * (Vc2 + Vp)
    sh_reqd = sh_reqd_shear or torsion_consider

    return {
        # Common
        "Mu_c": Mu_c, "dv": dv, "bv": bv, "Vnmax": Vnmax,
        "lambda_duct": lambda_duct, "fpo": fpo,
        "Veff": Veff, "tors_shear_comp": tors_shear_comp,
        # Strain
        "eps_s": eps_s, "eps_s_neg_recalc": eps_s_neg_recalc,
        "flex_compr": flex_compr, "fr": fr, "dbl_eps": dbl_eps,
        "sx": sx, "sxe": sxe, "denom": denom, "Aps_tens": Aps_tens,
        "Act_gp": Act_gp, "Ec_gp": Ec_gp,
        # Min Av
        "Av_min": Av_min, "has_min_av": has_min_av,
        # Method 1
        "th1": th1, "bt1": bt1, "Vc1": Vc1, "Vs1": Vs1, "Vn1": Vn1, "Vr1": Vr1,
        # Method 2
        "bt2a": bt2a, "bt2b": bt2b, "bt2": bt2, "th2": th2,
        "Vc2": Vc2, "Vs2": Vs2, "Vn2": Vn2, "Vr2": Vr2,
        # Method 3
        "th3": th3, "bt3": bt3, "ex_b5": ex_b5, "n_iter": n_iter, "b5_valid": b5_valid,
        "vu_b5": vu_b5, "vufc": vufc, "Act": Act, "b5_max_ex": b5_max_ex,
        "b5_ex_num": b5_ex_num, "b5_denom_used": b5_denom_used,
        "b5_ex_neg_recalc": b5_ex_neg_recalc, "b5_Vterm": b5_Vterm, "b5_cot_th": b5_cot_th,
        "Vc3": Vc3, "Vs3": Vs3, "Vn3": Vn3, "Vr3": Vr3,
        # Shear reinf checks
        "sh_reqd": sh_reqd,
        "sh_reqd1": abs(Vu) > 0.5 * phi_v * (Vc1 + Vp) or torsion_consider,
        "sh_reqd2": abs(Vu) > 0.5 * phi_v * (Vc2 + Vp) or torsion_consider,
        "sh_reqd3": (abs(Vu) > 0.5 * phi_v * (Vc3 + Vp) or torsion_consider) if b5_valid else False,
        "torsion_consider": torsion_consider,
        "vu": vu, "s_max_sh": s_max_sh,
        # Longitudinal (5.7.3.5-1 / 5.7.3.6.3-1)
        "phi_c": phi_c, "Vs_des": Vs_des, "th_des": th2, "cott": cott,
        "ld_M": ld_M, "ld_N": ld_N, "ld_V": ld_V, "ld_T_tors": ld_T_tors, "ld_VT": ld_VT,
        "long_dem": long_dem, "long_cap": long_cap, "long_ok": long_ok,
        # Shear Method Breakdowns
        "breakdown_shear_m1": shear_breakdown_m1.to_dict(),
        "breakdown_shear_m2": shear_breakdown_m2.to_dict(),
        "breakdown_shear_m3": shear_breakdown_m3.to_dict(),
    }


# ─── Torsion ────────────────────────────────────────────────────────

def do_torsion(I, flex, shear, Pu, Mu, Vu, Tu, Vp):
    """Compute torsion capacity and combined checks. Returns dict."""
    fc, fy, lam, phi_v = I["fc"], I["fy"], I["lam"], I["phi_v"]
    is_rect, b, h, bw, cover = I["isRect"], I["b"], I["h"], I["bw"], I["cover"]
    hf_top, hf_bot = I["hf_top"], I["hf_bot"]
    ds = flex["ds"]
    As = flex["As"]
    Aps, Av, s_shear = I["Aps"], I["Av"], I["s_shear"]
    s_torsion = I["s_torsion"]
    tBar_a = I["tBar_a"]
    shBar_d = I["shBar_d"]
    dv, bv = flex["dv"], flex["bv"]
    theta_gp = shear["th2"]
    Vc_gp = shear["Vc2"]
    long_demand = shear["long_dem"]
    long_capacity = shear["long_cap"]
    fps_calc, phi_f = flex["fps_calc"], flex["phi_f"]

    if is_rect:
        pc = 2 * b + 2 * h
        Acp = b * h
    else:
        # T-section: actual perimeter and area of the cross-section
        hw = h - hf_top - hf_bot
        Acp = b * hf_top + bw * hw + b * hf_bot
        # Outer perimeter: top flange top -> right -> step in -> web right -> step out -> bot flange -> left -> etc.
        pc = (b + hf_top + (b - bw) / 2 + hw + (b - bw) / 2 + hf_bot
              + b + hf_bot + (b - bw) / 2 + hw + (b - bw) / 2 + hf_top)
    be = Acp / pc if pc > 0 else 0
    # Ao: area enclosed by shear flow path (reduced by be)
    if is_rect:
        Ao = (b - be) * (h - be)
    else:
        # Use web-based Ao: conservative approach for T/I shapes
        Ao = max((bw - be) * (h - be), (b - be) * (h - be) * 0.5)
    # ph: perimeter of stirrup centerline
    if is_rect:
        ph = (b - 2 * cover - shBar_d) * 2 + (h - 2 * cover - shBar_d) * 2
    else:
        ph = (bw - 2 * cover - shBar_d) * 2 + (h - 2 * cover - shBar_d) * 2

    # Tcr (5.7.2.1-4) — consistent with compute_torsion_threshold
    K = 1
    Tcr = 0.126 * K * lam * math.sqrt(fc) * Acp * Acp / pc if pc > 0 and fc > 0 else 0
    thresh = 0.25 * phi_v * Tcr
    consider = abs(Tu) > thresh

    theta = theta_gp if theta_gp else 35
    thr = math.radians(theta)
    cott = 1 / math.tan(thr) if thr > 0 else 0

    At = tBar_a
    lambda_duct = shear["lambda_duct"]

    # Available stirrup capacity for torsion (C5.7.3.6.2)
    # Same stirrups resist both shear and torsion — each leg carries Av/2s for shear + At/s for torsion
    V_steel = max(abs(Vu) / phi_v - Vc_gp - Vp, 0) if phi_v > 0 else 0
    Av_s_shear = V_steel / (fy * dv * cott) if (fy * dv * cott) > 0 else 0
    Av_s_prov = Av / s_shear if s_shear > 0 else 0
    At_s_avail = max(Av_s_prov - Av_s_shear, 0) / 2  # available per leg after shear demand
    At_s_from_bar = At / s_torsion if s_torsion > 0 else 0  # from torsion bar input

    # Tn based on torsion stirrup capacity (5.7.3.6.2-1)
    # Use the greater of: leftover from shear stirrups, or user-specified torsion bar
    At_s_design = max(At_s_avail, At_s_from_bar)
    Tn = 2 * Ao * At_s_design * fy * cott * lambda_duct if At_s_design > 0 else 0
    Tr = phi_v * Tn

    # ─── Torsion Breakdown Instrumentation ────

    torsion_breakdown_tcr = EqBreakdown("Torsion Threshold Check (AASHTO 5.7.2.1-4)")
    torsion_breakdown_tcr.add(
        f"Tcr = 0.126·K·λ·√(fc')·Acp² / pc",
        f"Tcr = 0.126·{fmt_num(K, 1)}·{fmt_num(lam, 2)}·√{fmt_num(fc, 0)}·({fmt_num(Acp, 1)})² / {fmt_num(pc, 1)}",
        Tcr, "kip·in"
    )
    torsion_breakdown_tcr.add(
        f"Threshold = 0.25·φᵥ·Tcr",
        f"Threshold = 0.25·{fmt_num(phi_v, 2)}·{fmt_num(Tcr, 1)}",
        thresh, "kip·in"
    )
    torsion_breakdown_tcr.add(
        f"Consider Torsion? |Tu| > Threshold",
        f"|{fmt_num(abs(Tu), 1)}| > {fmt_num(thresh, 1)} → {'YES' if consider else 'NO'}",
        abs(Tu), "kip·in"
    )

    torsion_breakdown_tn = EqBreakdown("Torsion Capacity (AASHTO 5.7.3.6.2-1)")
    torsion_breakdown_tn.add(
        f"Available stirrup area after shear: At_s_avail = max(Av_s_prov - Av_s_shear, 0) / 2",
        f"At_s_avail = max({fmt_num(Av_s_prov, 3)}-{fmt_num(Av_s_shear, 3)}, 0) / 2 = {fmt_num(At_s_avail, 4)}",
        At_s_avail, "in²/in"
    )
    torsion_breakdown_tn.add(
        f"Design stirrup area: At_s_design = max(At_s_avail, At_s_from_bar)",
        f"At_s_design = max({fmt_num(At_s_avail, 4)}, {fmt_num(At_s_from_bar, 4)}) = {fmt_num(At_s_design, 4)}",
        At_s_design, "in²/in"
    )
    torsion_breakdown_tn.add(
        f"Tn = 2·Ao·At_s_design·fy·cot(θ)·λ_duct",
        f"Tn = 2·{fmt_num(Ao, 1)}·{fmt_num(At_s_design, 4)}·{fmt_num(fy, 0)}·cot({fmt_num(theta, 1)}°)·{fmt_num(lambda_duct, 2)}",
        Tn, "kip·in"
    )
    torsion_breakdown_tn.add(
        f"Tr = φᵥ·Tn",
        f"Tr = {fmt_num(phi_v, 2)}·{fmt_num(Tn, 1)}",
        Tr, "kip·in"
    )

    tors_shear = 0.9 * ph * abs(Tu) / (2 * Ao) if Ao > 0 else 0
    Veff = math.sqrt(Vu ** 2 + tors_shear ** 2)

    Aoh = Ao
    comb_stress = abs(Vu) / (bv * dv) + (abs(Tu) * ph / (1.7 * Aoh ** 2) if Aoh > 0 else 0) if (bv * dv) > 0 else 0
    comb_lim = 0.25 * fc
    comb_ok = comb_stress <= comb_lim

    V_steel_dup = V_steel  # already computed above
    At_s_tors = abs(Tu) / (phi_v * 2 * Ao * fy * cott) if consider and (phi_v * 2 * Ao * fy * cott) > 0 else 0
    Av_s_comb = Av_s_shear + 2 * At_s_tors
    comb_reinf_ok = Av_s_prov >= Av_s_comb

    min_trans = 0.0316 * math.sqrt(fc) * bv * s_shear / fy if fy > 0 and fc > 0 else 0

    Al_tors = At_s_tors * ph * cott ** 2 if consider else 0
    At_s_min = 0.0316 * math.sqrt(fc) * bv / fy if fy > 0 and fc > 0 else 0
    Al_min = max(5 * math.sqrt(fc) * Acp / fy - At_s_min * ph, 0) if fy > 0 and fc > 0 else 0
    Al_gov = max(Al_tors, Al_min if consider else 0)

    long_dem_comb = (long_demand or 0) + Al_gov * fy
    long_cap_val = long_capacity or As * fy
    long_comb_ok = long_cap_val >= long_dem_comb

    s_max_tors = min(ph / 8, 12) if ph > 0 else 12

    return {
        "pc": pc, "Acp": Acp, "be": be, "Ao": Ao, "ph": ph,
        "Tcr": Tcr, "thresh": thresh, "consider": consider,
        "theta": theta, "At": At, "Tn": Tn, "Tr": Tr,
        "At_s_avail": At_s_avail, "At_s_from_bar": At_s_from_bar,
        "tors_shear": tors_shear, "Veff": Veff,
        "comb_stress": comb_stress, "comb_lim": comb_lim, "comb_ok": comb_ok,
        "Av_s_shear": Av_s_shear, "At_s_tors": At_s_tors,
        "Av_s_comb": Av_s_comb, "Av_s_prov": Av_s_prov, "comb_reinf_ok": comb_reinf_ok,
        "min_trans": min_trans,
        "Al_tors": Al_tors, "Al_min": Al_min, "Al_gov": Al_gov,
        "long_dem_comb": long_dem_comb, "long_cap_val": long_cap_val, "long_comb_ok": long_comb_ok,
        "s_max_tors": s_max_tors,
        # Torsion Breakdowns
        "breakdown_torsion_tcr": torsion_breakdown_tcr.to_dict(),
        "breakdown_torsion_tn": torsion_breakdown_tn.to_dict(),
    }


# ─── Compute Row Capacities ────────────────────────────────────────

def compute_row_capacities(I, pm_curve_sag, pm_curve_hog, Pu, Mu, Vu, Tu, Vp, Ms, Ps):
    """Compute capacities and status for a single demand row."""
    fc, fy, Es, Ept = I["fc"], I["fy"], I["Es"], I["Ept"]
    fpu, fpy, ecl = I["fpu"], I["fpy"], I["ecl"]
    alpha1, beta1, k_pt, etl = I["alpha1"], I["beta1"], I["k_pt"], I["etl"]
    is_rect, b, h, bw = I["isRect"], I["b"], I["h"], I["bw"]
    hf_top, hf_bot = I["hf_top"], I["hf_bot"]
    As_top, As_bot = I["As_top"], I["As_bot"]
    d_top, d_bot = I["d_top"], I["d_bot"]
    Aps, dp_orig, cover = I["Aps"], I["dp"], I["cover"]
    duct_dia = I["ductDia"]
    Av, s_shear = I["Av"], I["s_shear"]
    ag, lam, phi_v = I["ag"], I["lam"], I["phi_v"]
    gamma_e, Ec = I["gamma_e"], I["Ec"]
    bar_d_bot, bar_d_top = I["bar_d_bot"], I["bar_d_top"]
    nBars_bot, nBars_top = I["nBars_bot"], I["nBars_top"]
    n_mod = I["n_mod"]
    tBar_a = I["tBar_a"]
    shBar_d = I["shBar_d"]
    s_torsion = I["s_torsion"]
    code_edition, section_class = I["codeEdition"], I["sectionClass"]

    # Sign convention: assign tension/compression based on Mu sign
    if Mu >= 0:
        As = As_bot; ds = d_bot; As_comp = As_top; d_s_comp = d_top
        hf = hf_top if not is_rect else ds
        bar_d_tens = bar_d_bot; nBars = nBars_bot
        dp = dp_orig
    else:
        As = As_top; ds = h - d_top; As_comp = As_bot; d_s_comp = h - d_bot
        hf = hf_bot if not is_rect else ds
        bar_d_tens = bar_d_top; nBars = nBars_top
        dp = h - dp_orig if dp_orig > 0 else 0

    bv = b if is_rect else bw

    # Mr from P-M (use correct curve based on Mu sign)
    pm_curve = pm_curve_sag if Mu >= 0 else pm_curve_hog
    Mr = get_mr_at_pu(pm_curve, Pu)

    # c, Mn, dv for shear calcs
    # Step 1: Solve as rectangular
    c_denom = alpha1 * fc * beta1 * b + (k_pt * Aps * fpu / dp if Aps > 0 and dp > 0 else 0)
    c = (As * fy + Aps * fpu - As_comp * fy - Pu) / c_denom if c_denom > 0 else 0.01
    if c <= 0:
        c = 0.01
    a = c * beta1
    # Step 2: If T-section and a > hf, re-solve with T-formula
    if not is_rect and a > hf and hf > 0:
        c_T_denom = alpha1 * fc * beta1 * bw + (k_pt * Aps * fpu / dp if Aps > 0 and dp > 0 else 0)
        c_T = (As * fy + Aps * fpu - As_comp * fy - alpha1 * fc * (b - bw) * hf - Pu) / c_T_denom if c_T_denom > 0 else c
        if c_T > 0:
            c = c_T
    if c <= 0:
        c = 0.01
    a = c * beta1

    # PT-in-compression-zone check (AASHTO: Aps = tension-side PT only)
    pt_in_compression = (Aps > 0 and dp > 0 and dp < c)
    if pt_in_compression:
        # Re-solve c without Aps
        c_denom2 = alpha1 * fc * beta1 * b
        c = (As * fy - As_comp * fy - Pu) / c_denom2 if c_denom2 > 0 else 0.01
        if c <= 0:
            c = 0.01
        a = c * beta1
        if not is_rect and a > hf and hf > 0:
            c_T_d2 = alpha1 * fc * beta1 * bw
            c_T2 = (As * fy - As_comp * fy - alpha1 * fc * (b - bw) * hf - Pu) / c_T_d2 if c_T_d2 > 0 else c
            if c_T2 > 0:
                c = c_T2
        if c <= 0:
            c = 0.01
        a = c * beta1

    Aps_tens = 0 if pt_in_compression else Aps
    fps_calc = fpu * (1 - k_pt * c / dp) if Aps_tens > 0 and dp > 0 else 0

    if is_rect or a <= hf:
        Mn = As * fy * (ds - a / 2) + (Aps_tens * fps_calc * (dp - a / 2) if Aps_tens > 0 else 0)
    else:
        Cf = alpha1 * fc * (b - bw) * hf
        Cw = alpha1 * fc * bw * a
        Mn = (Cf * (ds - hf / 2) + Cw * (ds - a / 2)
              + (Aps_tens * fps_calc * (dp - a / 2) if Aps_tens > 0 else 0)
              - (As_comp * fy * (ds - cover) if As_comp > 0 else 0))

    tot_tens = As * fy + (Aps_tens * fps_calc if Aps_tens > 0 else 0)
    if Aps_tens > 0 and As > 0:
        de_row = (Aps_tens * fps_calc * dp + As * fy * ds) / tot_tens if tot_tens > 0 else ds
    elif Aps_tens > 0:
        de_row = dp
    else:
        de_row = ds
    dv = max(Mn / tot_tens if tot_tens > 0 else 0, 0.72 * h, 0.9 * de_row)

    # Shear common
    fpo = 0.7 * fpu
    lambda_duct = max(1 - 2 * (duct_dia / bv) ** 2, 0.5) if duct_dia > 0 and bv > 0 else 1

    # Torsion threshold for this row (5.7.2.1-3 and 5.7.2.3)
    tors_row = compute_torsion_threshold(I, Tu)
    torsion_consider_row = tors_row["consider"]
    tors_Ao = tors_row.get("Ao", 0)
    tors_ph = tors_row.get("ph", 0)

    # Veff per 5.7.3.4.2-5 (solid sections)
    if torsion_consider_row and tors_Ao > 0:
        tors_shear_comp = 0.9 * tors_ph * abs(Tu) / (2 * tors_Ao)
        Veff = math.sqrt(Vu ** 2 + tors_shear_comp ** 2)
    else:
        tors_shear_comp = 0
        Veff = abs(Vu)
    V_strain = Veff

    Mu_c = max(abs(Mu), abs(V_strain - Vp) * dv)
    denom = Es * As + Ept * Aps_tens

    # Min Av (needed for eps_s denominator factor)
    # When no stirrups are provided (Av=0 or s_shear=0), has_min_av is always False
    if Av <= 0 or s_shear <= 0:
        Av_min = 0
        has_min_av = False
    else:
        Av_min = 0.0316 * math.sqrt(fc) * bv * s_shear / fy if fy > 0 and fc > 0 else 0
        has_min_av = Av >= Av_min

    # Strain eps_s — Eq. 5.7.3.4.2-4 (with min Av) or -5 (without)
    eps_denom = 2 * denom if has_min_av else denom
    eps_s = (Mu_c / dv + 0.5 * Pu + abs(V_strain - Vp) - Aps_tens * fpo) / eps_denom if eps_denom > 0 else 0.006
    if eps_s < 0:
        if is_rect:
            Act_row = b * h / 2
        elif Mu >= 0:
            Act_row = b * hf_bot + bw * max(h / 2 - hf_bot, 0)
        else:
            Act_row = b * hf_top + bw * max(h / 2 - hf_top, 0)
        Ec_row = Ec if Ec > 0 else 2500 * fc ** 0.33
        denom_neg = (2 * (Es * As + Ept * Aps_tens) + Ec_row * Act_row) if has_min_av else (Es * As + Ept * Aps_tens + Ec_row * Act_row)
        eps_s = (Mu_c / dv + 0.5 * Pu + abs(V_strain - Vp) - Aps_tens * fpo) / denom_neg if denom_neg > 0 else 0
        eps_s = max(eps_s, -0.0004)
    eps_s = min(eps_s, 0.006)

    sx = dv
    sxe = min(max(sx * 1.38 / (ag + 0.63), 12), 80) if (ag + 0.63) > 0 else 12
    Vnmax = 0.25 * fc * bv * dv + Vp

    # Method 1
    Vc1 = 0.0316 * 2 * lam * math.sqrt(fc) * bv * dv if fc > 0 else 0
    Vs1 = Av * fy * dv * lambda_duct / math.tan(math.radians(45)) / s_shear if s_shear > 0 else 0
    Vr1 = phi_v * min(Vc1 + Vs1 + Vp, Vnmax)

    # Method 2
    bt2 = 4.8 / (1 + 750 * eps_s) if has_min_av else 4.8 / (1 + 750 * eps_s) * 51 / (39 + sxe)
    th2 = 29 + 3500 * eps_s
    Vc2 = 0.0316 * bt2 * lam * math.sqrt(fc) * bv * dv if fc > 0 else 0
    Vs2 = Av * fy * dv * lambda_duct / math.tan(math.radians(th2)) / s_shear if s_shear > 0 and th2 > 0 else 0
    Vr2 = phi_v * min(Vc2 + Vs2 + Vp, Vnmax)

    # Method 3
    vu_b5 = abs(Vu - phi_v * Vp) / (phi_v * bv * dv) if (phi_v * bv * dv) > 0 else 0
    vufc = vu_b5 / fc if fc > 0 else 0
    if is_rect:
        Act = b * h / 2
    elif Mu >= 0:
        Act = b * hf_bot + bw * max(h / 2 - hf_bot, 0)
    else:
        Act = b * hf_top + bw * max(h / 2 - hf_top, 0)
    b5_max_ex = 0.001 if has_min_av else 0.002
    th3, bt3, b5_valid = 30, 2, True
    for it in range(100):
        thr = math.radians(th3)
        tan_val = math.tan(thr) if thr > 0 else 1
        ex_num = Mu_c / dv + 0.5 * Pu + 0.5 * abs(V_strain - Vp) / tan_val - Aps_tens * fpo
        b5denom = 2 * denom if has_min_av else denom
        ex = ex_num / b5denom if b5denom > 0 else 0
        if ex < 0:
            Ec_val = Ec if Ec > 0 else 2500 * fc ** 0.33
            b5denom_neg = 2 * (Ec_val * Act + denom)
            ex = ex_num / b5denom_neg if b5denom_neg > 0 else 0
        if ex > b5_max_ex:
            b5_valid = False
            break
        tbl = lookup_b5(has_min_av, ex, vufc, sxe)
        if tbl is None:
            b5_valid = False
            break
        th_new, bt_new = tbl["theta"], tbl["beta"]
        if abs(th_new - th3) < 0.01 and abs(bt_new - bt3) < 0.001:
            th3, bt3 = th_new, bt_new
            break
        th3, bt3 = th_new, bt_new
    Vr3 = 0
    if b5_valid:
        Vc3 = 0.0316 * bt3 * lam * math.sqrt(fc) * bv * dv if fc > 0 else 0
        Vs3 = Av * fy * dv * lambda_duct / math.tan(math.radians(th3)) / s_shear if s_shear > 0 and th3 > 0 else 0
        Vr3 = phi_v * min(Vc3 + Vs3 + Vp, Vnmax)

    # Torsion geometry (matches compute_torsion_threshold / do_torsion)
    if is_rect:
        pc = 2 * b + 2 * h
        Acp = b * h
    else:
        hw = h - hf_top - hf_bot
        Acp = b * hf_top + bw * hw + b * hf_bot
        pc = (b + hf_top + (b - bw) / 2 + hw + (b - bw) / 2 + hf_bot
              + b + hf_bot + (b - bw) / 2 + hw + (b - bw) / 2 + hf_top)
    be_t = Acp / pc if pc > 0 else 0
    if is_rect:
        Ao = (b - be_t) * (h - be_t)
    else:
        Ao = max((bw - be_t) * (h - be_t), (b - be_t) * (h - be_t) * 0.5)
    if is_rect:
        ph = (b - 2 * cover - shBar_d) * 2 + (h - 2 * cover - shBar_d) * 2
    else:
        ph = (bw - 2 * cover - shBar_d) * 2 + (h - 2 * cover - shBar_d) * 2
    theta = th2 if th2 else 35
    cott = 1 / math.tan(math.radians(theta)) if theta > 0 else 0

    # Available stirrup capacity for torsion (C5.7.3.6.2)
    V_steel_row = max(abs(Vu) / phi_v - Vc2 - Vp, 0) if phi_v > 0 else 0
    Av_s_shear_row = V_steel_row / (fy * dv * cott) if (fy * dv * cott) > 0 else 0
    Av_s_prov_row = Av / s_shear if s_shear > 0 else 0
    At_s_avail_row = max(Av_s_prov_row - Av_s_shear_row, 0) / 2
    Tn = 2 * Ao * At_s_avail_row * fy * cott * lambda_duct if At_s_avail_row > 0 else 0
    Tr = phi_v * Tn

    # Crack status — use Ms sign for service steel assignment
    if Ms >= 0:
        s_As_r = As_bot; s_ds_r = d_bot
        s_dp_r = dp_orig
    else:
        s_As_r = As_top; s_ds_r = h - d_top
        s_dp_r = h - dp_orig if dp_orig > 0 else 0
    dc = cover + bar_d_tens / 2
    beta_s_val = 1 + dc / (0.7 * (h - dc)) if (h - dc) > 0 else 1
    fss_simp = 0.6 * fy
    s_crack_val = (700 * gamma_e) / (beta_s_val * fss_simp) - 2 * dc if (beta_s_val * fss_simp) > 0 else 0
    crack_status = "OK"
    if s_As_r > 0 and nBars > 1:
        nAs_c = s_As_r * n_mod
        n_pt_c = Ept / Ec if Aps > 0 and Ec > 0 else 0
        nAps_c = Aps * n_pt_c
        qa_c = b / 2
        qb_c = nAs_c + nAps_c
        qc_c = -(nAs_c * s_ds_r + nAps_c * s_dp_r)
        disc_c = qb_c ** 2 - 4 * qa_c * qc_c
        c_cr_c = (-qb_c + math.sqrt(disc_c)) / (2 * qa_c) if disc_c > 0 and qa_c > 0 else 0
        Icr_c = b * c_cr_c ** 3 / 3 + nAs_c * (s_ds_r - c_cr_c) ** 2 + (nAps_c * (s_dp_r - c_cr_c) ** 2 if Aps > 0 else 0)
        M_serv_c = abs(Ms)
        addlBM_c = Ps * (h / 2 - c_cr_c)
        fss_act = 0
        if Icr_c > 0:
            fss_act = ((M_serv_c + addlBM_c) * (s_ds_r - c_cr_c) / Icr_c * n_mod
                       + Ps / (nAs_c + nAps_c + c_cr_c * b) * n_mod)
        if fss_act > 0.6 * fy:
            crack_status = "NG"
        if s_crack_val <= 0:
            crack_status = "NG"

    # Flex status
    gamma1 = 1.6
    gamma3 = 0.67 if fy <= 60 else 0.75
    fr_c = 0.24 * math.sqrt(fc) if fc > 0 else 0
    if is_rect:
        Sc_c = b * h ** 2 / 6
    else:
        A1, y1 = b * hf_top, hf_top / 2
        hw = h - hf_top - hf_bot
        A2, y2 = bw * hw, hf_top + hw / 2
        A3, y3 = b * hf_bot, hf_top + hw + hf_bot / 2
        At_c = A1 + A2 + A3
        yb = (A1 * y1 + A2 * y2 + A3 * y3) / At_c if At_c > 0 else h / 2
        It_c = (b * hf_top ** 3 / 12 + A1 * (yb - y1) ** 2
                + bw * hw ** 3 / 12 + A2 * (yb - y2) ** 2
                + b * hf_bot ** 3 / 12 + A3 * (yb - y3) ** 2)
        Sc_c = It_c / max(yb, h - yb) if max(yb, h - yb) > 0 else 0
    Mcr_c = gamma1 * gamma3 * fr_c * Sc_c
    Mcond_c = min(1.33 * abs(Mu), Mcr_c)
    min_flex_ok_c = Mr >= Mcond_c
    flex_cap_ok = Mr >= abs(Mu)
    pu_in_range = (pm_curve and Pu >= pm_curve[0]["Pr"] and Pu <= pm_curve[-1]["Pr"]) if pm_curve else True
    if not pu_in_range or not flex_cap_ok:
        flex_status = "NG"
    elif not min_flex_ok_c:
        flex_status = "MIN"
    else:
        flex_status = "OK"

    # Shear status
    sh_reqd = abs(Vu) > 0.5 * phi_v * (Vc2 + Vp) or torsion_consider_row
    vu_stress = abs(Vu) / (phi_v * bv * dv) if (phi_v * bv * dv) > 0 else 0
    s_max_sh = min(0.8 * dv, 24) if vu_stress < 0.125 * fc else min(0.4 * dv, 12)
    if Vr2 < abs(Vu):
        shear_status = "NG"
    elif sh_reqd and not has_min_av:
        shear_status = "NG"
    elif sh_reqd and s_shear > s_max_sh:
        shear_status = "NG"
    elif not sh_reqd:
        shear_status = "NR"
    else:
        shear_status = "OK"

    # Sign convention: Mr follows Mu sign (positive sagging, negative hogging)
    Mr_signed = -Mr if Mu < 0 else Mr

    return {
        "Mr": Mr_signed, "Vr1": Vr1, "Vr2": Vr2, "Vr3": Vr3, "Tr": Tr,
        "crackStatus": crack_status, "flexStatus": flex_status, "shearStatus": shear_status,
        "torsionConsider": torsion_consider_row,
        "shReqd": sh_reqd, "hasMinAv": has_min_av,
    }


# ─── Main Entry Point ──────────────────────────────────────────────

def calculate_all(raw_inputs, demand_rows, active_row_idx):
    """
    Main calculation entry. Takes raw inputs dict, list of demand dicts,
    and active row index. Returns complete results for rendering.
    """
    I = dict(raw_inputs)
    derive_constants(I)

    # Auto-calculated values to return to UI
    Ec = I["Ec"]
    fpy = I["fpy"]

    # Get active demand row
    dr = demand_rows[active_row_idx] if active_row_idx < len(demand_rows) else demand_rows[0]
    Pu = dr.get("Pu", 0)
    Mu = dr.get("Mu", 0)
    Vu = dr.get("Vu", 0)
    Tu = dr.get("Tu", 0)
    Vp = dr.get("Vp", 0)
    Ms = dr.get("Ms", 0)
    Ps = dr.get("Ps", 0)

    # Save original dp and fpe (from global inputs) for restoration
    dp_global = I["dp"]
    fpe_global = I.get("fpe", 0)

    # Per-row dp/fpe override for active row (from PT profile auto-populate)
    if "dp" in dr and dr["dp"] is not None:
        I["dp"] = dr["dp"]
    if "fpe" in dr and dr["fpe"] is not None:
        I["fpe"] = dr["fpe"]

    # Flexure
    flex = do_flexure(I, Pu, Mu, Ms, Ps)

    # Torsion threshold check (before shear, per 5.7.2.1-3 and 5.7.2.3)
    tors_thresh = compute_torsion_threshold(I, Tu)
    torsion_consider = tors_thresh["consider"]

    # Shear (torsion_consider affects sh_reqd per 5.7.2.3)
    shear = do_shear(I, flex, Pu, Mu, Vu, Tu, Vp, tors_thresh)

    # Torsion (full analysis)
    torsion = do_torsion(I, flex, shear, Pu, Mu, Vu, Tu, Vp)

    # P-M curves for demand rows (40-point): sagging and hogging
    pm_curve_sag = build_pm_curve(I, "top")
    pm_curve_hog = build_pm_curve(I, "bottom")
    # Track the actual dp/fpe used to build baseline curves
    pm_dp = I["dp"]
    pm_fpe = I.get("fpe", 0)

    # Restore global dp/fpe before row loop
    I["dp"] = dp_global
    I["fpe"] = fpe_global

    # Compute capacities for all demand rows
    row_results = []
    for dr_row in demand_rows:
        # Per-row dp/fpe override
        row_dp = dr_row.get("dp")
        row_fpe = dr_row.get("fpe")
        if row_dp is not None:
            I["dp"] = row_dp
        else:
            I["dp"] = dp_global
        if row_fpe is not None:
            I["fpe"] = row_fpe
        else:
            I["fpe"] = fpe_global

        # Rebuild P-M curves when dp or fpe changed from what was used for the baseline curves
        dp_changed = (I["dp"] != pm_dp)
        fpe_changed = (I.get("fpe", 0) != pm_fpe)
        if dp_changed or fpe_changed:
            row_pm_sag = build_pm_curve(I, "top")
            row_pm_hog = build_pm_curve(I, "bottom")
        else:
            row_pm_sag = pm_curve_sag
            row_pm_hog = pm_curve_hog

        cap = compute_row_capacities(
            I, row_pm_sag, row_pm_hog,
            dr_row.get("Pu", 0), dr_row.get("Mu", 0), dr_row.get("Vu", 0),
            dr_row.get("Tu", 0), dr_row.get("Vp", 0),
            dr_row.get("Ms", 0), dr_row.get("Ps", 0),
        )
        row_results.append(cap)

    # Restore global dp/fpe
    I["dp"] = dp_global
    I["fpe"] = fpe_global

    return {
        "inputs": {
            "Ec": Ec, "Es": I["Es"], "fpy": fpy,
            "h": I["h"], "b": I["b"], "cover": I["cover"],
            "dp": I["dp"],
            "hf_top": I.get("hf_top", 0), "hf_bot": I.get("hf_bot", 0),
            "As_top": I["As_top"], "As_bot": I["As_bot"],
            "d_top": I["d_top"], "d_bot": I["d_bot"],
            "bar_d_top": I["bar_d_top"], "bar_d_bot": I["bar_d_bot"],
            "Aps": I["Aps"],
            "isRect": I["isRect"], "bw": I["bw"],
            "hasPT": I["hasPT"],
            "ecl": I["ecl"], "etl": I["etl"], "alpha1": I["alpha1"],
            "Ag": I["Ag"], "Ig": I["Ig"], "yb_centroid": I["yb_centroid"],
        },
        "demands": {"Pu": Pu, "Mu": Mu, "Vu": Vu, "Tu": Tu, "Vp": Vp, "Ms": Ms, "Ps": Ps},
        "flexure": flex,
        "shear": shear,
        "torsion": torsion,
        "row_results": row_results,
    }
