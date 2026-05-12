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

def _ec_aashto(fc, K1=1.0, wc=0.145):
    """AASHTO LRFD 5.4.2.4-1: Ec = 120000 * K1 * wc^2 * f'c^0.33  (ksi; wc in kcf)."""
    return 120000.0 * K1 * (wc ** 2) * (fc ** 0.33)


def derive_constants(I):
    """Compute derived constants from raw inputs and attach to I dict."""
    # Backward compatibility: if caller passes fy (old format), split into fy_long / fy_trans
    if "fy_long" not in I:
        I["fy_long"] = I.get("fy", 60)
    if "fy_trans" not in I:
        I["fy_trans"] = I.get("fy_long", 60)

    fc = I["fc"]
    fy_long = I["fy_long"]
    fy_trans = I["fy_trans"]
    Es = I["Es"]
    # Concrete unit weight wc (kcf) and AASHTO 5.4.2.4 K1 — defaults match
    # normal-weight concrete at the AASHTO simplification (≈ 2523·f'c^0.33).
    I["K1"] = I.get("K1", 1.0)
    I["wc"] = I.get("wc", 0.145)
    Ec = I["Ec"]
    fpu = I["fpu"]
    fpy = I["fpy"]

    # Apply factor overrides if provided
    fo = I.get("factor_overrides", {})
    if "alpha1_f" in fo:
        I["alpha1"] = fo["alpha1_f"]
    else:
        I["alpha1"] = max(0.75, 0.85 - 0.02 * max(fc - 10, 0))
    if "beta1_f" in fo:
        I["beta1"] = fo["beta1_f"]
    else:
        I["beta1"] = max(min(0.85, 0.85 - 0.05 * (fc - 4)), 0.65)
    if "phi_v_f" in fo:
        I["phi_v"] = fo["phi_v_f"]
    if "lambda_f" in fo:
        I["lam"] = fo["lambda_f"]
    if "gamma_e_f" in fo:
        I["gamma_e"] = fo["gamma_e_f"]

    I["k_pt"] = 2 * (1.04 - fpy / fpu) if fpu > 0 else 0
    I["n_mod"] = Es / Ec if Ec > 0 else 0
    I["ey"] = fy_long / Es if Es > 0 else 0
    # ecl / etl: auto-compute from fy_long per 5.6.2.1 unless user overrides
    # Compression-controlled strain limit:
    #   fy_long <= 60:  fy_long/Es but <= 0.002
    #   fy_long = 100:  0.004
    #   60 < fy_long < 100: linear interpolation
    #   Prestressed: 0.002
    if I.get("ecl_override"):
        pass  # keep user value
    else:
        if fy_long <= 60:
            I["ecl"] = min(fy_long / Es, 0.002) if Es > 0 else 0.002
        elif fy_long >= 100:
            I["ecl"] = 0.004
        else:
            I["ecl"] = 0.002 + (0.004 - 0.002) * (fy_long - 60) / (100 - 60)
    # Tension-controlled strain limit:
    #   fy_long <= 75 and prestressed: 0.005
    #   fy_long = 100: 0.008
    #   75 < fy_long < 100: linear interpolation
    if I.get("etl_override"):
        pass  # keep user value
    else:
        if fy_long <= 75:
            I["etl"] = 0.005
        elif fy_long >= 100:
            I["etl"] = 0.008
        else:
            I["etl"] = 0.005 + (0.008 - 0.005) * (fy_long - 75) / (100 - 75)

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

    # Additional dedicated torsion bars (optional, closed loops on outer perimeter)
    at_add_n = I.get("at_add_bar_N", 0)
    if at_add_n and at_add_n > 0:
        at_add_bar = BARS.get(at_add_n, BARS[4])
        I["at_add_bar_a"] = at_add_bar["a"]
        I["at_add_bar_d"] = at_add_bar["d"]
    else:
        I["at_add_bar_a"] = 0
        I["at_add_bar_d"] = 0

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
    fc, fy_long, Es, Ept = I["fc"], I["fy_long"], I["Es"], I["Ept"]
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
    # AASHTO LRFD 10th Ed Eq. 5.6.4.4-3: Pn_max = 0.80[kc·f'c·(Ag-Ast-Aps) + fy_long·Ast - Aps·(fpe - Ep·εcu)]
    Ast = As_tens_total + As_comp_total
    kc = alpha1  # kc per 5.6.4.4: same formula as α₁ (0.85 for f'c≤10, reduced above)
    pt_reduction = Aps * (fpe - Ept * 0.003) if Aps > 0 else 0
    Pn_max = -0.8 * (kc * fc * (Ag - Ast - Aps) + fy_long * Ast - pt_reduction)
    N = 40
    d_tens_max = max((r["d_cf"] for r in tens_rows), default=0)
    # Fallback sweep depth: use centroid depth when no tension rows exist
    if d_tens_max <= 0:
        d_fallback = (h - I["d_top"]) if comp_face == "bottom" else I["d_bot"]
        d_tens_max = max(d_fallback, 0.1)
    dt_bc = max(d_tens_max, dp_cf) if Aps > 0 else d_tens_max

    # Moment direction: when comp_face="bottom", d_cf is from bottom but
    # moment about h/2 must reference positions from top. Since all moment
    # terms use (d_cf - h/2) which has wrong sign when d_cf is from bottom,
    # we multiply the total Mn by m_sign to correct.
    m_sign = 1 if comp_face == "top" else -1

    def _row_zero(rows):
        return [{"d_cf": r["d_cf"], "As": r["As"], "es": 0, "fs": 0, "F": 0} for r in rows]

    # Centroid of gross concrete area (from top of section)
    if is_rect:
        yc_conc = h / 2
    else:
        A_tf = b * hf_top
        A_web = bw * (h - hf_top - hf_bot)
        A_bf = b * hf_bot
        yc_conc = (A_tf * (hf_top / 2) + A_web * (hf_top + (h - hf_top - hf_bot) / 2) + A_bf * (h - hf_bot / 2)) / Ag

    pts = []

    # Upper sweep: transition from pure compression to main sweep (c > dt_bc)
    # Only sweep from dt_bc up to c_sat where all steel reaches -fy_long (beyond that, Mn is constant)
    # c_sat: strain at deepest tension row = fy_long/Es → 0.003*(d_max-c)/c = -fy_long/Es → c = d_max/(1 - fy_long/(0.003*Es))
    # For fy_long=60, Es=29000: fy_long/(0.003*Es) = 0.69, so c_sat ≈ 3.2*d_max
    fy_ratio = fy_long / (0.003 * Es)
    c_sat = dt_bc / (1 - fy_ratio) if fy_ratio < 1 else 3 * h
    c_upper_max = min(c_sat * 1.05, 5 * h)  # slight overshoot then stop
    # Build upper sweep with denser spacing near dt_bc where Mn changes rapidly
    c_full_block = h / beta1  # c at which a exactly equals h
    upper_c_values = set()
    # 5 points from c_full_block to c_upper_max (flat Mn region — sparse)
    N_above = 5
    for i in range(N_above, 0, -1):
        upper_c_values.add(round(c_full_block + (c_upper_max - c_full_block) * i / N_above, 6))
    upper_c_values.add(round(c_full_block, 6))
    # 8 points from dt_bc to c_full_block (rapid Mn change — dense)
    N_below = 8
    if c_full_block > dt_bc:
        for i in range(N_below, 0, -1):
            upper_c_values.add(round(dt_bc + (c_full_block - dt_bc) * i / N_below, 6))
    upper_c_values = sorted(upper_c_values, reverse=True)

    for ci in upper_c_values:
        ai = min(ci * beta1, h)  # cap stress block at section depth
        if is_rect or ai <= hf:
            if ai >= h and is_rect:
                Cc = -alpha1 * fc * b * h
                ycc = h / 2
            else:
                Cc = -alpha1 * fc * b * ai
                ycc = ai / 2
        else:
            if ai >= h:
                Cc = -alpha1 * fc * Ag
                ycc = None
            else:
                Cf = alpha1 * fc * (b - bw) * hf
                Cw = alpha1 * fc * bw * ai
                Cc = -(Cf + Cw)
                ycc = None

        F_tens_sum = 0
        Mn_tens_sum = 0
        rows_tens_data = []
        for row in tens_rows:
            d_r = row["d_cf"]
            es_r = 0.003 * (d_r - ci) / ci
            fs_r = min(abs(es_r) * Es, fy_long) * (1 if es_r >= 0 else -1)
            F_r = row["As"] * fs_r
            F_tens_sum += F_r
            Mn_tens_sum += F_r * (d_r - pc_y)
            rows_tens_data.append({"d_cf": d_r, "As": row["As"], "es": es_r, "fs": fs_r, "F": F_r})

        ext_es_tens = 0
        ext_fs_tens = 0
        if tens_rows:
            deepest = max(tens_rows, key=lambda r: r["d_cf"])
            ext_es_tens = 0.003 * (deepest["d_cf"] - ci) / ci
            ext_fs_tens = min(abs(ext_es_tens) * Es, fy_long) * (1 if ext_es_tens >= 0 else -1)

        F_comp_sum = 0
        Mn_comp_sum = 0
        rows_comp_data = []
        for row in comp_rows:
            d_r = row["d_cf"]
            es_r = 0.003 * (d_r - ci) / ci if ci > 0 else 0
            fs_r = min(abs(es_r) * Es, fy_long) * (1 if es_r >= 0 else -1)
            F_r = row["As"] * fs_r
            F_comp_sum += F_r
            Mn_comp_sum += F_r * (d_r - pc_y)
            rows_comp_data.append({"d_cf": d_r, "As": row["As"], "es": es_r, "fs": fs_r, "F": F_r})

        ext_es_comp = 0
        ext_fs_comp = 0
        if comp_rows:
            shallowest = min(comp_rows, key=lambda r: r["d_cf"])
            ext_es_comp = 0.003 * (shallowest["d_cf"] - ci) / ci if ci > 0 else 0
            ext_fs_comp = min(abs(ext_es_comp) * Es, fy_long) * (1 if ext_es_comp >= 0 else -1)

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
        arm_pt = dp_cf - pc_y if Aps > 0 else 0
        if ai >= h:
            # Full section compressed: concrete centroid at h/2 from comp face
            Mn_cc = -Cc * (pc_y - h / 2)  # = 0 for rectangular
            if not is_rect:
                # Use actual centroid of gross section from comp face
                yc_cf = yc_conc if comp_face == "top" else (h - yc_conc)
                Mn_cc = -Cc * (pc_y - yc_cf)
        elif is_rect or ai <= hf:
            Mn_cc = -Cc * (pc_y - ycc)
        else:
            Mn_cc = Cf * (pc_y - hf / 2) + Cw * (pc_y - ai / 2)

        Mn_i = (Mn_cc + Mn_tens_sum + Mn_comp_sum + (Tpt * arm_pt if Aps > 0 else 0)) * m_sign

        # c > dt_bc: tension face is in net compression → always compression-controlled
        et_i = 0.003 * (dt_bc - ci) / ci  # negative when c > dt_bc
        phi_i = 0.75  # compression-controlled
        st = "CC"

        pts.append({
            "c": ci, "a": ai, "eps_t": abs(et_i), "stat": st, "phi": phi_i,
            "Pn": Pn, "Mn": Mn_i, "Pr": Pn * phi_i, "Mr": Mn_i * phi_i,
            "es_tens": ext_es_tens, "fs_tens": ext_fs_tens, "F_tens": F_tens_sum,
            "es_comp": ext_es_comp, "fs_comp": ext_fs_comp, "F_comp": F_comp_sum,
            "rows_tens": rows_tens_data, "rows_comp": rows_comp_data,
            "eps_pe": eps_pe, "delta_eps": delta_eps_i, "eps_pt": eps_p_i, "fps_pt": fps_u_i, "F_pt": Tpt,
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
            fs_r = min(abs(es_r) * Es, fy_long) * (1 if es_r >= 0 else -1)
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
            ext_fs_tens = min(abs(ext_es_tens) * Es, fy_long) * (1 if ext_es_tens >= 0 else -1)

        # Compression rows
        F_comp_sum = 0
        Mn_comp_sum = 0
        rows_comp_data = []
        ext_es_comp = 0
        ext_fs_comp = 0
        for row in comp_rows:
            d_r = row["d_cf"]
            es_r = 0.003 * (d_r - ci) / ci if ci > 0 else 0
            fs_r = min(abs(es_r) * Es, fy_long) * (1 if es_r >= 0 else -1)
            F_r = row["As"] * fs_r
            F_comp_sum += F_r
            Mn_comp_sum += F_r * (d_r - pc_y)
            rows_comp_data.append({"d_cf": d_r, "As": row["As"], "es": es_r, "fs": fs_r, "F": F_r})
        if comp_rows:
            shallowest = min(comp_rows, key=lambda r: r["d_cf"])
            ext_es_comp = 0.003 * (shallowest["d_cf"] - ci) / ci if ci > 0 else 0
            ext_fs_comp = min(abs(ext_es_comp) * Es, fy_long) * (1 if ext_es_comp >= 0 else -1)

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

        Mn_i = (Mn_cc + Mn_tens_sum + Mn_comp_sum + (Tpt * arm_pt if Aps > 0 else 0)) * m_sign

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

    # Extended sweep for smooth tension transition (c from dt_bc/40 down to dt_bc/400)
    for i in range(9, 0, -1):
        ci = dt_bc * i / 400
        ai = ci * beta1
        if is_rect or ai <= hf:
            Cc = -alpha1 * fc * b * ai
            ycc = ai / 2
        else:
            Cf = alpha1 * fc * (b - bw) * hf
            Cw = alpha1 * fc * bw * ai
            Cc = -(Cf + Cw)
            ycc = None

        F_tens_sum = 0
        Mn_tens_sum = 0
        rows_tens_data = []
        for row in tens_rows:
            d_r = row["d_cf"]
            es_r = 0.003 * (d_r - ci) / ci
            fs_r = min(abs(es_r) * Es, fy_long) * (1 if es_r >= 0 else -1)
            F_r = row["As"] * fs_r
            F_tens_sum += F_r
            Mn_tens_sum += F_r * (d_r - pc_y)
            rows_tens_data.append({"d_cf": d_r, "As": row["As"], "es": es_r, "fs": fs_r, "F": F_r})

        ext_es_tens = 0.003 * (d_tens_max - ci) / ci if tens_rows else 0
        ext_fs_tens = min(abs(ext_es_tens) * Es, fy_long) * (1 if ext_es_tens >= 0 else -1) if tens_rows else 0

        F_comp_sum = 0
        Mn_comp_sum = 0
        rows_comp_data = []
        for row in comp_rows:
            d_r = row["d_cf"]
            es_r = 0.003 * (d_r - ci) / ci if ci > 0 else 0
            fs_r = min(abs(es_r) * Es, fy_long) * (1 if es_r >= 0 else -1)
            F_r = row["As"] * fs_r
            F_comp_sum += F_r
            Mn_comp_sum += F_r * (d_r - pc_y)
            rows_comp_data.append({"d_cf": d_r, "As": row["As"], "es": es_r, "fs": fs_r, "F": F_r})

        ext_es_comp = 0
        ext_fs_comp = 0
        if comp_rows:
            shallowest = min(comp_rows, key=lambda r: r["d_cf"])
            ext_es_comp = 0.003 * (shallowest["d_cf"] - ci) / ci if ci > 0 else 0
            ext_fs_comp = min(abs(ext_es_comp) * Es, fy_long) * (1 if ext_es_comp >= 0 else -1)

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
        arm_pt = dp_cf - pc_y if Aps > 0 else 0
        if is_rect or ai <= hf:
            Mn_cc = -Cc * (pc_y - ycc)
        else:
            Mn_cc = Cf * (pc_y - hf / 2) + Cw * (pc_y - ai / 2)
        Mn_i = (Mn_cc + Mn_tens_sum + Mn_comp_sum + (Tpt * arm_pt if Aps > 0 else 0)) * m_sign

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

    # Pure tension - moment from bar positions about h/2 (no concrete contribution)
    As_all = As_tens_total + As_comp_total
    Pn_tens = As_all * fy_long + (Aps * fpy if Aps > 0 else 0)
    phi_tens = get_phi_flex(code_edition, section_class, 0.01, ecl, etl)

    # All bars yield in tension at their actual depths from top
    Mn_tens_pure = 0
    for row in tens_rows:
        d_from_top = row["d_cf"] if comp_face == "top" else (h - row["d_cf"])
        Mn_tens_pure += (row["As"] * fy_long) * (d_from_top - pc_y)
    for row in comp_rows:
        d_from_top = row["d_cf"] if comp_face == "top" else (h - row["d_cf"])
        Mn_tens_pure += (row["As"] * fy_long) * (d_from_top - pc_y)
    if Aps > 0 and dp > 0:
        Mn_tens_pure += (Aps * fpy) * (dp - pc_y)

    rows_tens_pt = [{"d_cf": r["d_cf"], "As": r["As"], "es": 99, "fs": fy_long, "F": r["As"] * fy_long} for r in tens_rows]
    rows_comp_pt = [{"d_cf": r["d_cf"], "As": r["As"], "es": 99, "fs": fy_long, "F": r["As"] * fy_long} for r in comp_rows]
    pts.append({
        "c": 0, "a": 0, "eps_t": 99, "stat": "TC", "phi": phi_tens,
        "Pn": Pn_tens, "Mn": Mn_tens_pure, "Pr": Pn_tens * phi_tens, "Mr": Mn_tens_pure * phi_tens,
        "es_tens": 99, "fs_tens": fy_long, "F_tens": As_tens_total * fy_long,
        "es_comp": 99, "fs_comp": fy_long, "F_comp": As_comp_total * fy_long,
        "rows_tens": rows_tens_pt, "rows_comp": rows_comp_pt,
        "eps_pe": eps_pe, "delta_eps": 99, "eps_pt": 99, "fps_pt": fpy if Aps > 0 else 0, "F_pt": Aps * fpy if Aps > 0 else 0,
    })
    return pts


def compute_pm_key_points(I, pm_curve, comp_face="top", Pu=0):
    """Compute key named points on the PM curve with detailed calculation steps."""
    fc, fy_long, Es = I["fc"], I["fy_long"], I["Es"]
    alpha1, beta1 = I["alpha1"], I["beta1"]
    ecl, etl = I["ecl"], I["etl"]
    b, h, bw = I["b"], I["h"], I["bw"]
    is_rect = I["isRect"]
    hf_top, hf_bot = I["hf_top"], I.get("hf_bot", 0)
    Aps, dp, fpy, Ept = I["Aps"], I["dp"], I["fpy"], I["Ept"]
    fpe = I.get("fpe", 0)
    code_edition, section_class = I["codeEdition"], I["sectionClass"]

    hf = h if is_rect else (hf_bot if comp_face == "bottom" else hf_top)
    dp_cf = (h - dp) if (comp_face == "bottom" and dp > 0) else dp

    if comp_face == "bottom":
        tens_rows = _get_steel_rows(I, "top", comp_face, h)
        comp_rows = _get_steel_rows(I, "bot", comp_face, h)
    else:
        tens_rows = _get_steel_rows(I, "bot", comp_face, h)
        comp_rows = _get_steel_rows(I, "top", comp_face, h)

    As_tens = sum(r["As"] for r in tens_rows)
    As_comp = sum(r["As"] for r in comp_rows)
    Ast = As_tens + As_comp
    Ag = b * h if is_rect else b * hf_top + bw * (h - hf_top - hf_bot) + b * hf_bot
    pc_y = h / 2
    d_tens_max = max((r["d_cf"] for r in tens_rows), default=h / 2)
    dt_bc = max(d_tens_max, dp_cf) if Aps > 0 else d_tens_max
    m_sign = 1 if comp_face == "top" else -1

    def _calc_point_at_c(ci):
        """Compute Pn, Mn, and step-by-step calc at a given c.
        For ci = inf (pure compression), uniform ε = 0.003 is assumed."""
        # Detect pure compression (c → ∞): uniform strain 0.003 everywhere
        pure_comp = (ci == float('inf') or ci > 1e6)
        if pure_comp:
            ci = float('inf')
            ai = h  # full section in compression
        else:
            ai = min(ci * beta1, h)
        steps = []
        if pure_comp:
            steps.append(f"c → ∞ (pure uniform compression)")
            steps.append(f"a = h = {h} in (entire section in compression)")
            steps.append(f"")
            steps.append(f"NOTE: For pure compression, c → ∞ means uniform strain")
            steps.append(f"  ε = 0.003 (compression) at ALL fibers, bars, and strands.")
            steps.append(f"")
        else:
            steps.append(f"c = {ci:.4f} in")
            steps.append(f"a = min(c·β₁, h) = min({ci:.4f}×{beta1:.4f}, {h}) = {ai:.4f} in")
            if ci > h:
                steps.append(f"")
                steps.append(f"NOTE: c = {ci:.2f} in > h = {h} in. This is physically valid.")
                steps.append(f"  The neutral axis lies outside the section depth, meaning the")
                steps.append(f"  entire section is in compression. The strain diagram still has")
                steps.append(f"  εcu = 0.003 at the compression face, but since c > h, the")
                steps.append(f"  'tension' face actually has a compressive strain too:")
                eps_far = 0.003 * (ci - h) / ci if ci > 0 else 0
                steps.append(f"  ε at far face = 0.003×(c-h)/c = 0.003×({ci:.2f}-{h})/{ci:.2f} = {eps_far:.6f} (compression)")
                steps.append(f"  All steel bars are in compression because they are all above the NA.")
                steps.append(f"")

        # Concrete compression (net of steel area)
        if is_rect or ai <= hf:
            if ai >= h:
                Cc = -alpha1 * fc * (b * h - Ast - (Aps if Aps > 0 else 0))
                ycc = h / 2
                steps.append(f"a ≥ h → full section in compression (net of steel):")
                steps.append(f"  Ac_net = b·h - Ast - Aps = {b}×{h} - {Ast:.3f} - {Aps:.3f} = {b*h - Ast - (Aps if Aps > 0 else 0):.3f} in²")
                steps.append(f"  Cc = -α₁·f'c·Ac_net = -{alpha1:.3f}×{fc}×{b*h - Ast - (Aps if Aps > 0 else 0):.3f} = {Cc:.1f} kip")
            else:
                Cc = -alpha1 * fc * b * ai
                ycc = ai / 2
                steps.append(f"Cc = -α₁·f'c·b·a = -{alpha1:.3f}×{fc}×{b}×{ai:.4f} = {Cc:.1f} kip")
        else:
            Cf = alpha1 * fc * (b - bw) * hf
            Cw = alpha1 * fc * bw * ai
            Cc = -(Cf + Cw)
            ycc = None
            steps.append(f"I-section: Cf = {Cf:.1f}, Cw = {Cw:.1f}, Cc = {Cc:.1f} kip")

        # Steel
        F_tens = 0
        M_tens = 0
        steps.append("")
        steps.append("--- Tension-side steel (bars on tension face) ---")
        for row in tens_rows:
            d_r = row["d_cf"]
            if pure_comp:
                es_r = -0.003
            else:
                es_r = 0.003 * (d_r - ci) / ci if ci > 0 else 99
            fs_r = min(abs(es_r) * Es, fy_long) * (1 if es_r >= 0 else -1)
            F_r = row["As"] * fs_r
            F_tens += F_r
            arm_r = d_r - pc_y
            M_tens += F_r * arm_r
            if pure_comp:
                steps.append(f"  d={d_r:.3f}: εs = -0.003 (uniform compression)")
            else:
                steps.append(f"  d={d_r:.3f}: εs=0.003×({d_r:.3f}-{ci:.3f})/{ci:.3f} = {es_r:.6f}")
            steps.append(f"          fs=min(|εs|·Es, fy_long)·sign = min({abs(es_r):.6f}×{Es}, {fy_long})×{'(+1)' if es_r>=0 else '(-1)'} = {fs_r:.1f} ksi")
            steps.append(f"          F = As·fs = {row['As']:.3f}×{fs_r:.1f} = {F_r:.1f} kip")
            steps.append(f"          arm = d - h/2 = {d_r:.3f} - {pc_y:.3f} = {arm_r:.3f} in")
            steps.append(f"          M = F×arm = {F_r:.1f}×{arm_r:.3f} = {F_r*arm_r:.1f} kip-in")

        F_comp = 0
        M_comp = 0
        steps.append("")
        steps.append("--- Compression-side steel (bars on compression face) ---")
        for row in comp_rows:
            d_r = row["d_cf"]
            if pure_comp:
                es_r = -0.003
            else:
                es_r = 0.003 * (d_r - ci) / ci if ci > 0 else 0
            fs_r = min(abs(es_r) * Es, fy_long) * (1 if es_r >= 0 else -1)
            F_r = row["As"] * fs_r
            F_comp += F_r
            arm_r = d_r - pc_y
            M_comp += F_r * arm_r
            if pure_comp:
                steps.append(f"  d={d_r:.3f}: εs = -0.003 (uniform compression)")
            else:
                steps.append(f"  d={d_r:.3f}: εs=0.003×({d_r:.3f}-{ci:.3f})/{ci:.3f} = {es_r:.6f}")
            steps.append(f"          fs=min(|εs|·Es, fy_long)·sign = min({abs(es_r):.6f}×{Es}, {fy_long})×{'(+1)' if es_r>=0 else '(-1)'} = {fs_r:.1f} ksi")
            steps.append(f"          F = As·fs = {row['As']:.3f}×{fs_r:.1f} = {F_r:.1f} kip")
            steps.append(f"          arm = d - h/2 = {d_r:.3f} - {pc_y:.3f} = {arm_r:.3f} in")
            steps.append(f"          M = F×arm = {F_r:.1f}×{arm_r:.3f} = {F_r*arm_r:.1f} kip-in")

        # PT
        Tpt = 0
        M_pt = 0
        if Aps > 0 and dp_cf > 0:
            eps_pe = fpe / Ept if Ept > 0 else 0
            if pure_comp:
                delta_eps = -0.003
            else:
                delta_eps = 0.003 * (dp_cf - ci) / ci if ci > 0 else 99
            eps_p = eps_pe + delta_eps
            fps = min(abs(eps_p) * Ept, fpy) * (1 if eps_p >= 0 else -1)
            Tpt = Aps * fps
            arm_pt = dp_cf - pc_y
            M_pt = Tpt * arm_pt
            steps.append(f"")
            steps.append(f"--- Prestressing steel ---")
            steps.append(f"  εpe = fpe/Ept = {fpe:.1f}/{Ept} = {eps_pe:.6f}")
            if pure_comp:
                steps.append(f"  Δε = -0.003 (uniform compression)")
            else:
                steps.append(f"  Δε = 0.003×(dp-c)/c = 0.003×({dp_cf:.3f}-{ci:.3f})/{ci:.3f} = {delta_eps:.6f}")
            steps.append(f"  εps = εpe + Δε = {eps_pe:.6f} + {delta_eps:.6f} = {eps_p:.6f}")
            steps.append(f"  fps = min(|εps|·Ept, fpy)·sign = {fps:.1f} ksi")
            steps.append(f"  Fpt = Aps·fps = {Aps:.3f}×{fps:.1f} = {Tpt:.1f} kip")
            steps.append(f"  arm = dp - h/2 = {dp_cf:.3f} - {pc_y:.3f} = {arm_pt:.3f} in")
            steps.append(f"  Mpt = {Tpt:.1f}×{arm_pt:.3f} = {M_pt:.1f} kip-in")

        # Pn_max per AASHTO 10th Ed Eq. 5.6.4.4-3
        kc = alpha1  # kc per 5.6.4.4: same formula as α₁
        pt_reduction = Aps * (fpe - Ept * 0.003) if Aps > 0 else 0
        Pn_max = -0.8 * (kc * fc * (Ag - Ast - Aps) + fy_long * Ast - pt_reduction)
        Pn_raw = Cc + F_tens + F_comp + Tpt
        Pn = max(Pn_raw, Pn_max)

        # Moment about h/2 — detailed
        steps.append(f"")
        steps.append(f"--- Moment about geometric centroid (h/2 = {pc_y:.3f} in) ---")
        if ai >= h:
            Mn_cc = 0
            steps.append(f"  Mn_cc = 0 (full rect compression block centroid at h/2 → zero arm)")
        elif is_rect or ai <= hf:
            Mn_cc = -Cc * (pc_y - ycc)
            arm_cc = pc_y - ycc
            steps.append(f"  Concrete block centroid at a/2 = {ycc:.4f} in from comp. face")
            steps.append(f"  arm_cc = h/2 - a/2 = {pc_y:.3f} - {ycc:.4f} = {arm_cc:.4f} in")
            steps.append(f"  Mn_cc = -Cc × arm_cc = -({Cc:.1f})×{arm_cc:.4f} = {Mn_cc:.1f} kip-in")
        else:
            Cf = alpha1 * fc * (b - bw) * hf
            Cw = alpha1 * fc * bw * ai
            Mn_cc = Cf * (pc_y - hf / 2) + Cw * (pc_y - ai / 2)
            steps.append(f"  I-section: Mn_cc = Cf×(h/2-hf/2) + Cw×(h/2-a/2)")
            steps.append(f"           = {Cf:.1f}×{pc_y-hf/2:.3f} + {Cw:.1f}×{pc_y-ai/2:.3f} = {Mn_cc:.1f} kip-in")

        steps.append(f"  Mn_steel(tens) = ΣF·arm = {M_tens:.1f} kip-in")
        steps.append(f"  Mn_steel(comp) = ΣF·arm = {M_comp:.1f} kip-in")
        if Aps > 0 and dp_cf > 0:
            steps.append(f"  Mn_pt = {M_pt:.1f} kip-in")
        steps.append(f"  Mn = (Mn_cc + Mn_s_tens + Mn_s_comp + Mn_pt) × m_sign")
        steps.append(f"     = ({Mn_cc:.1f} + {M_tens:.1f} + {M_comp:.1f} + {M_pt:.1f}) × {m_sign}")

        Mn = (Mn_cc + M_tens + M_comp + M_pt) * m_sign
        steps.append(f"     = {Mn:.1f} kip-in")

        # Equilibrium & Pn_max
        steps.append(f"")
        steps.append(f"--- Axial force equilibrium ---")
        steps.append(f"  Pn_raw = Cc + Fs_tens + Fs_comp + Fpt")
        steps.append(f"         = {Cc:.1f} + {F_tens:.1f} + {F_comp:.1f} + {Tpt:.1f} = {Pn_raw:.1f} kip")
        steps.append(f"")
        steps.append(f"  Pn_max per AASHTO LRFD 10th Ed Eq. 5.6.4.4-3:")
        steps.append(f"    Pn_max = -0.80·[kc·f'c·(Ag - Ast - Aps) + fy_long·Ast - Aps·(fpe - Ep·εcu)]")
        steps.append(f"    kc = {kc:.3f} (= α₁ per 5.6.4.4)")
        steps.append(f"    Ag = {Ag:.2f} in²")
        steps.append(f"    Ast = {Ast:.3f} in² (total mild steel)")
        if Aps > 0:
            steps.append(f"    Aps = {Aps:.3f} in², fpe = {fpe:.1f} ksi, Ep = {Ept:.0f} ksi")
        steps.append(f"    Concrete (net): kc·f'c·(Ag-Ast-Aps) = {kc:.3f}×{fc}×({Ag:.2f}-{Ast:.3f}-{Aps:.3f}) = {kc*fc*(Ag-Ast-Aps):.1f} kip")
        steps.append(f"    Steel: fy_long·Ast = {fy_long}×{Ast:.3f} = {fy_long*Ast:.1f} kip")
        if Aps > 0:
            steps.append(f"    PT reduction: Aps·(fpe - Ep·εcu) = {Aps:.3f}×({fpe:.1f} - {Ept:.0f}×0.003) = {pt_reduction:.1f} kip")
        bracket = kc * fc * (Ag - Ast - Aps) + fy_long * Ast - pt_reduction
        steps.append(f"    [bracket] = {bracket:.1f} kip")
        steps.append(f"    Pn_max = -0.80 × {bracket:.1f} = {Pn_max:.1f} kip")
        steps.append(f"")
        if Pn > Pn_raw:
            steps.append(f"  Pn_raw ({Pn_raw:.1f}) < Pn_max ({Pn_max:.1f}) → Pn governed by Pn_max")
        else:
            steps.append(f"  Pn_raw ({Pn_raw:.1f}) ≥ Pn_max ({Pn_max:.1f}) → Pn = Pn_raw (not capped)")
        steps.append(f"  Pn = {Pn:.1f} kip")

        # Phi and factored
        steps.append(f"")
        if pure_comp:
            et = -0.003  # all fibers at 0.003 compression
            phi = 0.75
            steps.append(f"--- Resistance factor ---")
            steps.append(f"  εt = -0.003 (uniform compression, c → ∞)")
            steps.append(f"  Compression-controlled → φ = 0.75")
        else:
            et = 0.003 * (dt_bc - ci) / ci if ci > 0 else 99
            phi = get_phi_flex(code_edition, section_class, et, ecl, etl) if ci <= dt_bc else 0.75
            steps.append(f"--- Resistance factor ---")
            steps.append(f"  εt = 0.003×(dt-c)/c = 0.003×({dt_bc:.3f}-{ci:.3f})/{ci:.3f} = {et:.6f}")
            if ci > dt_bc:
                steps.append(f"  c > dt → compression-controlled → φ = 0.75")
            else:
                steps.append(f"  φ = {phi:.4f} (per AASHTO 5.5.4.2)")
        steps.append(f"")
        steps.append(f"  Pr = φ·Pn = {phi:.4f} × {Pn:.1f} = {Pn*phi:.1f} kip")
        steps.append(f"  Mr = φ·Mn = {phi:.4f} × {Mn:.1f} = {Mn*phi:.1f} kip-in")

        return {"c": (None if pure_comp else ci), "a": ai, "Pn": Pn, "Mn": Mn, "Pr": Pn * phi, "Mr": Mn * phi,
                "eps_t": abs(et), "phi": phi, "steps": steps}

    key_points = []

    # 1. Pure Compression (c → ∞, uniform ε = 0.003 at all fibers)
    pt = _calc_point_at_c(float('inf'))
    pt["name"] = "Pure Compression"
    pt["description"] = ("Uniform compression: c → ∞, ε = 0.003 at all fibers. "
                         "All mild steel yields at fy_long. PT strand: εps = εpe − 0.003. "
                         "Pn capped by Pn_max per AASHTO LRFD 10th Ed Eq. 5.6.4.4-3.")
    key_points.append(pt)

    # 2. Zero Tension (εt = 0, c = dt)
    c_zt = dt_bc
    pt = _calc_point_at_c(c_zt)
    pt["name"] = "Zero Tension"
    pt["description"] = "Extreme tension fiber at zero strain (εt = 0, c = dt)"
    key_points.append(pt)

    # 3. Balanced / Compression-Controlled Limit (εt = εcl)
    c_bal = 0.003 * dt_bc / (0.003 + ecl)
    pt = _calc_point_at_c(c_bal)
    pt["name"] = "Balanced (εt = εcl)"
    pt["description"] = f"Compression-controlled limit: εt = εcl = {ecl:.4f}"
    key_points.append(pt)

    # 4. Tension-Controlled Limit (εt = εtl)
    c_tc = 0.003 * dt_bc / (0.003 + etl)
    pt = _calc_point_at_c(c_tc)
    pt["name"] = "Tension Controlled (εt = εtl)"
    pt["description"] = f"Tension-controlled limit: εt = εtl = {etl:.4f}, φ reaches maximum"
    key_points.append(pt)

    # 5. Pure Flexure (Pn = 0) — interpolate from curve
    c_pf = None
    for i in range(len(pm_curve) - 1):
        p1, p2 = pm_curve[i], pm_curve[i + 1]
        if (p1["Pn"] <= 0 and p2["Pn"] >= 0) or (p1["Pn"] >= 0 and p2["Pn"] <= 0):
            if abs(p2["Pn"] - p1["Pn"]) > 1e-10:
                t = (0 - p1["Pn"]) / (p2["Pn"] - p1["Pn"])
                c_pf = p1["c"] + t * (p2["c"] - p1["c"])
                break
    if c_pf is not None and c_pf > 0:
        pt = _calc_point_at_c(c_pf)
        pt["name"] = "Pure Flexure (Pn = 0)"
        pt["description"] = "Zero axial force — pure bending capacity"
        key_points.append(pt)

    # 6. Demand Level (Pr = Pu) — interpolate c from curve at applied axial force
    c_dem = None
    best_mr_dem = 0
    for i in range(len(pm_curve) - 1):
        p1, p2 = pm_curve[i], pm_curve[i + 1]
        pr1, pr2 = p1.get("Pr", 0), p2.get("Pr", 0)
        lo, hi = min(pr1, pr2), max(pr1, pr2)
        if Pu >= lo and Pu <= hi:
            dPr = pr2 - pr1
            if abs(dPr) < 1e-10:
                t = 0.5
            else:
                t = (Pu - pr1) / dPr
            t = max(0, min(1, t))
            mr_interp = abs(p1["Mr"] + t * (p2["Mr"] - p1["Mr"]))
            c_interp = p1["c"] + t * (p2["c"] - p1["c"])
            if mr_interp >= best_mr_dem and c_interp > 0:
                best_mr_dem = mr_interp
                c_dem = c_interp
    if c_dem is not None and c_dem > 0:
        pt = _calc_point_at_c(c_dem)
        pt["name"] = f"At Demand (Pu = {Pu:.1f} kip)"
        pt["description"] = f"Capacity at the applied axial force Pu = {Pu:.1f} kip — Mr at this level is the moment capacity"
        key_points.append(pt)

    # 7. Pure Tension (c = 0)
    phi_t = get_phi_flex(code_edition, section_class, 0.01, ecl, etl)
    steps_pt = []
    steps_pt.append(f"c = 0 in (no compression zone)")
    steps_pt.append(f"a = 0 in")
    steps_pt.append(f"")
    steps_pt.append(f"NOTE: With c = 0 (neutral axis at the compression face), there is no")
    steps_pt.append(f"  concrete compression block. All steel strains → ∞ (well beyond yield).")
    steps_pt.append(f"  Every bar yields at fy_long = {fy_long} ksi in tension.")
    if Aps > 0:
        steps_pt.append(f"  Prestressing steel yields at fpy = {fpy} ksi.")
    steps_pt.append(f"")
    steps_pt.append(f"--- Concrete ---")
    steps_pt.append(f"  Cc = 0 (no compression block)")
    steps_pt.append(f"")
    steps_pt.append(f"--- Tension-side steel (bars on tension face) ---")
    F_tens_total = 0
    M_tens_total = 0
    for row in tens_rows:
        d_top_pos = row["d_cf"] if comp_face == "top" else (h - row["d_cf"])
        arm = d_top_pos - pc_y
        F_r = row["As"] * fy_long
        M_r = F_r * arm
        F_tens_total += F_r
        M_tens_total += M_r
        steps_pt.append(f"  As = {row['As']:.3f} in² at d_top = {d_top_pos:.3f} in")
        steps_pt.append(f"          εs → ∞ (c = 0), fs = fy_long = {fy_long} ksi (tension)")
        steps_pt.append(f"          F = As·fy_long = {row['As']:.3f}×{fy_long} = {F_r:.1f} kip")
        steps_pt.append(f"          arm = d_top - h/2 = {d_top_pos:.3f} - {pc_y:.3f} = {arm:.3f} in")
        steps_pt.append(f"          M = F×arm = {F_r:.1f}×{arm:.3f} = {M_r:.1f} kip-in")
    steps_pt.append(f"")
    steps_pt.append(f"--- Compression-side steel (bars on compression face) ---")
    F_comp_total = 0
    M_comp_total = 0
    for row in comp_rows:
        d_top_pos = row["d_cf"] if comp_face == "top" else (h - row["d_cf"])
        arm = d_top_pos - pc_y
        F_r = row["As"] * fy_long
        M_r = F_r * arm
        F_comp_total += F_r
        M_comp_total += M_r
        steps_pt.append(f"  As = {row['As']:.3f} in² at d_top = {d_top_pos:.3f} in")
        steps_pt.append(f"          εs → ∞ (c = 0), fs = fy_long = {fy_long} ksi (tension)")
        steps_pt.append(f"          F = As·fy_long = {row['As']:.3f}×{fy_long} = {F_r:.1f} kip")
        steps_pt.append(f"          arm = d_top - h/2 = {d_top_pos:.3f} - {pc_y:.3f} = {arm:.3f} in")
        steps_pt.append(f"          M = F×arm = {F_r:.1f}×{arm:.3f} = {M_r:.1f} kip-in")
    if not comp_rows:
        steps_pt.append(f"  (no compression-side bars)")

    # PT
    F_pt_total = 0
    M_pt_total = 0
    if Aps > 0:
        arm_ps = dp - pc_y
        F_ps = Aps * fpy
        M_ps = F_ps * arm_ps
        F_pt_total = F_ps
        M_pt_total = M_ps
        steps_pt.append(f"")
        steps_pt.append(f"--- Prestressing steel ---")
        steps_pt.append(f"  Aps = {Aps:.3f} in², fpy = {fpy:.1f} ksi")
        steps_pt.append(f"  F = Aps·fpy = {Aps:.3f}×{fpy:.1f} = {F_ps:.1f} kip")
        steps_pt.append(f"  arm = dp - h/2 = {dp:.3f} - {pc_y:.3f} = {arm_ps:.3f} in")
        steps_pt.append(f"  M = F×arm = {F_ps:.1f}×{arm_ps:.3f} = {M_ps:.1f} kip-in")

    Pn_t = F_tens_total + F_comp_total + F_pt_total
    Mn_pt = (M_tens_total + M_comp_total + M_pt_total) * m_sign

    steps_pt.append(f"")
    steps_pt.append(f"--- Moment about geometric centroid (h/2 = {pc_y:.3f} in) ---")
    steps_pt.append(f"  Mn_cc = 0 (no concrete compression)")
    steps_pt.append(f"  Mn_steel(tens) = ΣF·arm = {M_tens_total:.1f} kip-in")
    steps_pt.append(f"  Mn_steel(comp) = ΣF·arm = {M_comp_total:.1f} kip-in")
    if Aps > 0:
        steps_pt.append(f"  Mn_pt = {M_pt_total:.1f} kip-in")
    steps_pt.append(f"  Mn = (0 + {M_tens_total:.1f} + {M_comp_total:.1f} + {M_pt_total:.1f}) × {m_sign}")
    steps_pt.append(f"     = {Mn_pt:.1f} kip-in")

    steps_pt.append(f"")
    steps_pt.append(f"--- Axial force ---")
    steps_pt.append(f"  Pn = ΣFs = {F_tens_total:.1f} + {F_comp_total:.1f} + {F_pt_total:.1f} = {Pn_t:.1f} kip (tension positive)")

    steps_pt.append(f"")
    steps_pt.append(f"--- Resistance factor ---")
    steps_pt.append(f"  εt → ∞ (c = 0) → deeply tension-controlled")
    steps_pt.append(f"  φ = {phi_t:.4f} (maximum per AASHTO 5.5.4.2)")
    steps_pt.append(f"")
    steps_pt.append(f"  Pr = φ·Pn = {phi_t:.4f} × {Pn_t:.1f} = {Pn_t*phi_t:.1f} kip")
    steps_pt.append(f"  Mr = φ·Mn = {phi_t:.4f} × {Mn_pt:.1f} = {Mn_pt*phi_t:.1f} kip-in")

    pt_tens = {
        "c": 0, "a": 0, "Pn": Pn_t, "Mn": Mn_pt,
        "Pr": Pn_t * phi_t, "Mr": Mn_pt * phi_t,
        "eps_t": 99, "phi": phi_t,
        "name": "Pure Tension",
        "description": "All steel yields in tension, no concrete contribution (c = 0)",
        "steps": steps_pt
    }
    key_points.append(pt_tens)

    return key_points


def build_pm_curve_display(I, comp_face="top"):
    """Build the 20-point P-M curve used for the display table (with Pn_max row)."""
    fc, fy_long, Es, Ept = I["fc"], I["fy_long"], I["Es"], I["Ept"]
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
    Ast_total = As_tens + As_comp_s
    kc = alpha1
    pt_reduction = Aps * (fpe - Ept * 0.003) if Aps > 0 else 0
    Pn_max = -0.8 * (kc * fc * (Ag - Ast_total - Aps) + fy_long * Ast_total - pt_reduction)
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
        fs_tens = min(abs(es_tens) * Es, fy_long) * (1 if es_tens >= 0 else -1)
        F_tens = As_tens * fs_tens

        es_comp_s = 0.003 * (d_comp_s - ci) / ci if ci > 0 else 0
        fs_comp_s = min(abs(es_comp_s) * Es, fy_long) * (1 if es_comp_s >= 0 else -1)
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

    Pn_tens = As_tens * fy_long + As_comp_s * fy_long + (Aps * fpy if Aps > 0 else 0)
    phi_tens = get_phi_flex(code_edition, section_class, 0.01, ecl, etl)
    pts.append({
        "c": 0, "a": 0, "eps_t": 99, "stat": "TC", "phi": phi_tens,
        "Pn": Pn_tens, "Mn": 0, "Pr": Pn_tens * phi_tens, "Mr": 0,
        "es_tens": 99, "fs_tens": fy_long, "F_tens": As_tens * fy_long,
        "es_comp": 99, "fs_comp": fy_long, "F_comp": As_comp_s * fy_long,
        "eps_pe": eps_pe, "delta_eps": 99, "eps_pt": 99, "fps_pt": fpy if Aps > 0 else 0, "F_pt": Aps * fpy if Aps > 0 else 0,
    })
    return pts


def get_mr_at_pu(pm_curve, Pu):
    """Interpolate Mr from factored P-M curve at given Pu.
    Returns the maximum |Mr| at the given Pu level (always positive)."""
    max_mr = 0
    for i in range(len(pm_curve) - 1):
        p1, p2 = pm_curve[i], pm_curve[i + 1]
        lo = min(p1["Pr"], p2["Pr"])
        hi = max(p1["Pr"], p2["Pr"])
        if Pu >= lo and Pu <= hi:
            if abs(p2["Pr"] - p1["Pr"]) < 1e-10:
                max_mr = max(max_mr, abs(p1["Mr"]), abs(p2["Mr"]))
            else:
                t = (Pu - p1["Pr"]) / (p2["Pr"] - p1["Pr"])
                mr_interp = p1["Mr"] + t * (p2["Mr"] - p1["Mr"])
                max_mr = max(max_mr, abs(mr_interp))
    return max_mr


def get_pm_equilibrium_at_pu(pm_data, Pu):
    """Find the P-M display point closest to Pr = Pu and interpolate c, strains, stresses."""
    # Find the segment where Pr crosses Pu with maximum |Mr| (capacity side)
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
            if abs(mr_interp) >= best_mr:
                best_mr = abs(mr_interp)
                result = {}
                for key in ["c", "a", "eps_t", "phi", "Pn", "Mn", "Pr", "Mr",
                            "es_tens", "fs_tens", "F_tens", "es_comp", "fs_comp", "F_comp",
                            "eps_pe", "delta_eps", "eps_pt", "fps_pt", "F_pt"]:
                    v1 = p1.get(key)
                    v2 = p2.get(key)
                    if v1 is not None and v2 is not None and isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
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
    fc, fy_long, Es, Ept = I["fc"], I["fy_long"], I["Es"], I["Ept"]
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
    # 1) Trial c assuming f's = fy_long (include A's)
    # 2) Check c_trial >= 3·d's AND fy_long <= 60 ksi
    # 3) If fails → redo c without A's, exclude A's from Mn
    # P-M strain compatibility check always handles compression steel correctly.
    comp_steel_yields = False
    c_trial = 0
    if As_comp > 0 and d_s_comp > 0:
        numer_with = As * fy_long + (Aps * fpu if Aps > 0 else 0) - As_comp * fy_long
        c_trial = numer_with / denom_R if denom_R > 0 else 0.01
        if c_trial <= 0:
            c_trial = 0.01
        comp_steel_yields = (c_trial >= 3 * d_s_comp) and (fy_long <= 60)

        if comp_steel_yields:
            c = c_trial
            na_breakdown.add(f"Trial c with A's·fy_long: c = {fmt_num(c_trial, 4)} in",
                            f"c ≥ 3·d's = {fmt_num(3*d_s_comp, 3)}? YES, fy_long ≤ 60? YES → compression steel yields, include A's",
                            c_trial, "in")
        else:
            numer_without = As * fy_long + (Aps * fpu if Aps > 0 else 0)
            c = numer_without / denom_R if denom_R > 0 else 0.01
            if c <= 0:
                c = 0.01
            na_breakdown.add(f"Trial c with A's·fy_long: c = {fmt_num(c_trial, 4)} in",
                            f"c ≥ 3·d's = {fmt_num(3*d_s_comp, 3)}? {'YES' if c_trial >= 3*d_s_comp else 'NO'}, fy_long ≤ 60? {'YES' if fy_long <= 60 else 'NO'} → A's excluded",
                            c_trial, "in")
            na_breakdown.add(f"Re-solve c without A's",
                            f"c = ({fmt_num(As, 2)}·{fmt_num(fy_long, 0)} + {fmt_num(Aps, 2)}·{fmt_num(fpu, 0)}) / {fmt_num(denom_R, 2)}",
                            c, "in")
    else:
        c = (As * fy_long + (Aps * fpu if Aps > 0 else 0)) / denom_R if denom_R > 0 else 0.01
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
        na_breakdown.add(f"c = (As·fy_long + Aps·fpu − A's·fy_long) / denom",
                        f"= ({fmt_num(As, 2)}·{fmt_num(fy_long, 0)} + {fmt_num(Aps, 2)}·{fmt_num(fpu, 0)} − {fmt_num(As_comp, 2)}·{fmt_num(fy_long, 0)}) / {fmt_num(denom_R, 2)}",
                        c, "in")
    else:
        na_breakdown.add(f"c = (As·fy_long + Aps·fpu) / denom",
                        f"= ({fmt_num(As, 2)}·{fmt_num(fy_long, 0)} + {fmt_num(Aps, 2)}·{fmt_num(fpu, 0)}) / {fmt_num(denom_R, 2)}",
                        c, "in")

    a = c * beta1
    na_breakdown.add(f"a = β₁·c",
                    f"= {fmt_num(beta1, 3)}·{fmt_num(c, 3)}", a, "in")

    # T-section check: if a > hf, re-solve with T-section formula
    if not is_rect and a > hf and hf > 0:
        denom_T_input = alpha1 * fc * beta1 * bw + (k_pt * Aps * fpu / dp if Aps > 0 and dp > 0 else 0)
        flange_comp = alpha1 * fc * (b - bw) * hf
        if comp_steel_yields and As_comp > 0:
            numer_T = As * fy_long + (Aps * fpu if Aps > 0 else 0) - As_comp * fy_long
        else:
            numer_T = As * fy_long + (Aps * fpu if Aps > 0 else 0)
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
            c = (As * fy_long - As_comp * fy_long) / denom_R_noAps if denom_R_noAps > 0 else 0.01
        else:
            c = (As * fy_long) / denom_R_noAps if denom_R_noAps > 0 else 0.01
        if c <= 0:
            c = 0.01
        a = c * beta1
        # T-section re-check without Aps
        if not is_rect and a > hf and hf > 0:
            denom_T_noAps = alpha1 * fc * beta1 * bw
            if comp_steel_yields and As_comp > 0:
                numer_T = As * fy_long - As_comp * fy_long
            else:
                numer_T = As * fy_long
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

    # ── c/ds check (5.6.2.1-1): verify fs = fy_long assumption ──
    c_ds_ratio = c / ds if ds > 0 else 0
    c_ds_limit = 0.003 / (0.003 + ecl) if ecl > 0 else 1.0
    c_ds_ok = c_ds_ratio <= c_ds_limit
    use_strain_compat = not c_ds_ok

    # Compression steel strain/stress at final c (for reporting)
    if As_comp > 0 and d_s_comp > 0:
        eps_comp = 0.003 * (c - d_s_comp) / c if c > 0 else 0
        fs_comp = fy_long if comp_steel_yields else min(abs(eps_comp) * Es, fy_long) if c > d_s_comp else 0
    else:
        eps_comp = 0
        fs_comp = 0

    # ── Mn (pure bending) ──
    mn_breakdown = EqBreakdown("Moment Capacity (Mn at Pu = 0)")

    # Compression steel contribution to Mn (AASHTO Eq. 5.6.3.2.2-1):
    # Mn = As·fy_long·(ds−a/2) + Aps·fps·(dp−a/2) + A's·f's·(a/2 − d's)
    # The last term adds capacity when d's < a/2, reduces when d's > a/2.
    comp_Mn = As_comp * fs_comp * (a / 2 - d_s_comp) if comp_steel_yields and As_comp > 0 else 0

    if is_rect or a <= hf:
        # Rectangular behavior: entire compression block within flange
        Ts = As * fy_long
        mom_arm_s = ds - a / 2
        Mn_s = Ts * mom_arm_s if Ts > 0 else 0
        
        Aps_contrib = 0
        if Aps_tens > 0:
            Aps_contrib = Aps_tens * fps_calc * (dp - a / 2)
            mn_breakdown.add(f"Ts = As·fy_long = {fmt_num(As, 2)}·{fmt_num(fy_long, 0)}",
                            f"", Ts, "kip")
            mn_breakdown.add(f"Tps = Aps·fps = {fmt_num(Aps_tens, 2)}·{fmt_num(fps_calc, 1)}",
                            f"", Aps_tens * fps_calc, "kip")
            mn_breakdown.add(f"Mn = As·fy_long·(ds − a/2) + Aps·fps·(dp − a/2)" + (f" + A's·f's·(a/2 − d's)" if comp_steel_yields and As_comp > 0 else ""),
                            f"= {fmt_num(As, 2)}·{fmt_num(fy_long, 0)}·({fmt_num(ds, 2)} − {fmt_num(a/2, 2)}) + {fmt_num(Aps_tens, 2)}·{fmt_num(fps_calc, 1)}·({fmt_num(dp, 2)} − {fmt_num(a/2, 2)})"
                            + (f" + {fmt_num(As_comp, 2)}·{fmt_num(fs_comp, 1)}·({fmt_num(a/2, 2)} − {fmt_num(d_s_comp, 2)})" if comp_steel_yields and As_comp > 0 else ""),
                            Mn_s + Aps_contrib + comp_Mn, "kip-in")
        else:
            mn_breakdown.add(f"Ts = As·fy_long = {fmt_num(As, 2)}·{fmt_num(fy_long, 0)}",
                            f"", Ts, "kip")
            if pt_in_compression:
                mn_breakdown.add(f"PT tendon in compression zone (dp < c) → Aps excluded",
                                f"", 0, "")
            mn_breakdown.add(f"Mn = As·fy_long·(ds − a/2)" + (f" + A's·f's·(a/2 − d's)" if comp_steel_yields and As_comp > 0 else ""),
                            f"= {fmt_num(As, 2)}·{fmt_num(fy_long, 0)}·({fmt_num(ds, 2)} − {fmt_num(a/2, 2)})"
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
    fo = I.get("factor_overrides", {})
    if "phi_f_f" in fo:
        phi_f = fo["phi_f_f"]
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
    tot_tens = As * fy_long + (Aps_tens * fps_calc if Aps_tens > 0 else 0)
    dv1 = Mn / tot_tens if tot_tens > 0 else 0
    dv2 = 0.72 * h
    if Aps_tens > 0 and As > 0:
        de = (Aps_tens * fps_calc * dp + As * fy_long * ds) / tot_tens
    elif Aps_tens > 0:
        de = dp
    else:
        de = ds
    dv3 = 0.9 * de
    dv = max(dv1, dv2, dv3)

    # ── P-M Interaction Diagram ──
    pm_curve = build_pm_curve(I, comp_face)
    pm_data = pm_curve  # table shows all points directly — same as graph
    pm_curve_sag = build_pm_curve(I, "top")
    pm_curve_hog = build_pm_curve(I, "bottom")
    pm_key_points = compute_pm_key_points(I, pm_curve, comp_face, Pu)
    Mr_atPu = get_mr_at_pu(pm_curve, Pu)
    pm_eq = get_pm_equilibrium_at_pu(pm_curve, Pu)

    # ── Minimum flexure reinforcement (5.6.3.3) ──
    fo = I.get("factor_overrides", {})
    gamma1 = fo.get("gamma1_f", 1.6)  # Table 5.6.3.3-1: flexural cracking variability factor (all sections other than precast segmental)
    gamma2 = fo.get("gamma2_f", 1.1)  # Table 5.6.3.3-1: prestress factor (bonded tendons)
    # γ3 per Table 5.6.3.3-1: depends on ASTM spec of reinforcement
    astm_spec = I.get("astm_spec", "A615_60")
    astm_gamma3_map = {
        "A615_60": 0.67, "A615_75": 0.75, "A615_80": 0.76,
        "A706_60": 0.75, "A706_80": 0.8,
        "A1035_100": 0.67,
        "A615": 0.67, "A706": 0.75  # Legacy values
    }
    gamma3_default = astm_gamma3_map.get(astm_spec, 0.67)
    gamma3 = fo.get("gamma3_f", gamma3_default)
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
    # fcpe: compressive stress at extreme tension fiber due to effective prestress (5.6.3.3)
    # fcpe = P/A + P*e*yt/I  where P = Aps*fpe, e = eccentricity from centroid to PT
    Aps_mcr = I.get("Aps", 0)
    fpe_mcr = I.get("fpe", 0)
    Ag_mcr = I.get("Ag", b * h)
    Ig_mcr = I.get("Ig", b * h ** 3 / 12.0)
    yb_c = I.get("yb_centroid", h / 2.0)  # centroid from top
    dp_mcr = I.get("dp", h / 2.0)
    P_eff = Aps_mcr * fpe_mcr  # effective prestress force (kip)
    # Eccentricity: distance from section centroid to PT centroid (positive if PT below centroid)
    e_pt = dp_mcr - yb_c
    # Distance from centroid to extreme tension fiber
    # For positive moment (top compression): tension fiber is at bottom, yt = h - yb_c
    # For negative moment (bottom compression): tension fiber is at top, yt = yb_c
    if Mu >= 0:
        yt_mcr = h - yb_c
    else:
        yt_mcr = yb_c
    if Ag_mcr > 0 and Ig_mcr > 0 and P_eff > 0:
        fcpe = P_eff / Ag_mcr + P_eff * e_pt * yt_mcr / Ig_mcr
        fcpe = max(fcpe, 0)  # fcpe is compressive stress, must be >= 0
    else:
        fcpe = 0
    # Full AASHTO 5.6.3.3-1: Mcr = γ₃·(γ₁·fr + γ₂·fcpe)·Sc - Mdnc·(Sc/Snc - 1)
    # Non-composite assumption: Sc = Snc, so Mdnc term = 0
    Mcr = gamma3 * (gamma1 * fr + gamma2 * fcpe) * Sc
    Mcond = min(1.33 * abs(Mu), Mcr)
    min_flex_ok = Mr >= Mcond

    # ── Crack control (5.6.7) ──
    dc = cover + bar_d_tens / 2
    beta_s = 1 + dc / (0.7 * (h - dc)) if (h - dc) > 0 else 1
    fss_simp = 0.6 * fy_long
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
        "pm_curve_sag": pm_curve_sag, "pm_curve_hog": pm_curve_hog,
        "pm_key_points": pm_key_points,
        # Min flexure
        "gamma1": gamma1, "gamma2": gamma2, "gamma3": gamma3, "fcpe": fcpe,
        "fr": fr, "Sc": Sc, "Mcr": Mcr, "Mcond": Mcond, "min_flex_ok": min_flex_ok,
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
    fc, fy_trans, lam, phi_v = I["fc"], I["fy_trans"], I["lam"], I["phi_v"]
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
    fc, fy_long, Es, Ept = I["fc"], I["fy_long"], I["Es"], I["Ept"]
    fy_trans = I["fy_trans"]
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
    fo = I.get("factor_overrides", {})
    if "lambda_duct_f" in fo:
        lambda_duct = fo["lambda_duct_f"]
    else:
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
    Ec_gp = Ec if Ec > 0 else _ec_aashto(fc, I.get("K1", 1.0), I.get("wc", 0.145))

    # Min Av (needed before eps_s for denominator factor)
    # When no stirrups are provided (Av=0 or s_shear=0), has_min_av is always False
    if Av <= 0 or s_shear <= 0:
        Av_min = 0
        has_min_av = False
    else:
        Av_min = 0.0316 * math.sqrt(fc) * bv * s_shear / fy_trans if fy_trans > 0 and fc > 0 else 0
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
    Vs1 = Av * fy_trans * dv * lambda_duct / math.tan(math.radians(th1)) / s_shear if s_shear > 0 else 0
    Vnmax = 0.25 * fc * bv * dv + Vp
    Vn1_uncapped = Vc1 + Vs1 + Vp
    Vn1_capped = Vn1_uncapped > Vnmax
    Vn1 = min(Vn1_uncapped, Vnmax)
    Vr1 = phi_v * Vn1

    # METHOD 2: General Procedure
    bt2a = 4.8 / (1 + 750 * eps_s) if (1 + 750 * eps_s) != 0 else 4.8
    bt2b = bt2a * 51 / (39 + sxe) if (39 + sxe) != 0 else bt2a
    bt2 = bt2a if has_min_av else bt2b
    th2 = 29 + 3500 * eps_s
    Vc2 = 0.0316 * bt2 * lam * math.sqrt(fc) * bv * dv if fc > 0 else 0
    Vs2 = Av * fy_trans * dv * lambda_duct / math.tan(math.radians(th2)) / s_shear if s_shear > 0 and th2 > 0 else 0
    Vn2_uncapped = Vc2 + Vs2 + Vp
    Vn2_capped = Vn2_uncapped > Vnmax
    Vn2 = min(Vn2_uncapped, Vnmax)
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
            Ec_val = Ec if Ec > 0 else _ec_aashto(fc, I.get("K1", 1.0), I.get("wc", 0.145))
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
    Vn3_uncapped = 0
    Vn3_capped = False
    if b5_valid:
        Vc3 = 0.0316 * bt3 * lam * math.sqrt(fc) * bv * dv if fc > 0 else 0
        Vs3 = Av * fy_trans * dv * lambda_duct / math.tan(math.radians(th3)) / s_shear if s_shear > 0 and th3 > 0 else 0
        Vn3_uncapped = Vc3 + Vs3 + Vp
        Vn3_capped = Vn3_uncapped > Vnmax
        Vn3 = min(Vn3_uncapped, Vnmax)
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
        f"Vs₁ = Av·fy_trans·dᵥ·λ_duct·cot(45°) / s_shear",
        f"Vs₁ = {fmt_num(Av, 2)}·{fmt_num(fy_trans, 0)}·{fmt_num(dv, 1)}·{fmt_num(lambda_duct, 2)}·cot(45°) / {fmt_num(s_shear, 2)}",
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
        f"Vs₂ = Av·fy_trans·dᵥ·λ_duct·cot(θ₂) / s_shear",
        f"Vs₂ = {fmt_num(Av, 2)}·{fmt_num(fy_trans, 0)}·{fmt_num(dv, 1)}·{fmt_num(lambda_duct, 2)}·cot({fmt_num(th2, 1)}°) / {fmt_num(s_shear, 2)}",
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
            f"Vs₃ = Av·fy_trans·dᵥ·λ_duct·cot(θ₃) / s_shear",
            f"Vs₃ = {fmt_num(Av, 2)}·{fmt_num(fy_trans, 0)}·{fmt_num(dv, 1)}·{fmt_num(lambda_duct, 2)}·cot({fmt_num(th3, 1)}°) / {fmt_num(s_shear, 2)}",
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
    fo = I.get("factor_overrides", {})
    phi_c = fo.get("phi_c_f", 0.75)
    ld_M = abs(Mu) / (dv * phi_f) if (dv * phi_f) > 0 else 0
    ld_N = 0.5 * Pu / phi_c
    long_cap = As * fy_long + (Aps_tens * fps_calc if Aps_tens > 0 else 0)

    # --- Method 2 (General Procedure) - existing logic, kept as primary ---
    Vs_des = min(Vs2, abs(Vu) / phi_v) if phi_v > 0 else Vs2
    cott = 1 / math.tan(math.radians(th2)) if th2 > 0 else 0
    ld_V_shear = max(abs(Vu) / phi_v - Vp, 0) - 0.5 * Vs_des if phi_v > 0 else 0
    if torsion_consider and tors_Ao > 0:
        ld_T_tors = 0.45 * tors_ph * abs(Tu) / (2 * tors_Ao * phi_v) if phi_v > 0 else 0
        ld_VT = math.sqrt(max(ld_V_shear, 0) ** 2 + ld_T_tors ** 2)
    else:
        ld_T_tors = 0
        ld_VT = max(ld_V_shear, 0)
    ld_V = ld_V_shear  # keep for display
    long_dem = ld_M + ld_N + ld_VT * cott
    long_ok = long_cap >= long_dem

    # --- Method 1 (Simplified, θ=45°) ---
    Vs_des_1 = min(Vs1, abs(Vu) / phi_v) if phi_v > 0 else Vs1
    cott_1 = 1.0  # cot(45°) = 1.0
    ld_V_shear_1 = max(abs(Vu) / phi_v - Vp, 0) - 0.5 * Vs_des_1 if phi_v > 0 else 0
    if torsion_consider and tors_Ao > 0:
        ld_VT_1 = math.sqrt(max(ld_V_shear_1, 0) ** 2 + ld_T_tors ** 2)
    else:
        ld_VT_1 = max(ld_V_shear_1, 0)
    long_dem_1 = ld_M + ld_N + ld_VT_1 * cott_1
    long_ok_1 = long_cap >= long_dem_1

    # --- Method 3 (Appendix B5) ---
    if b5_valid and th3 > 0:
        Vs_des_3 = min(Vs3, abs(Vu) / phi_v) if phi_v > 0 else Vs3
        cott_3 = 1 / math.tan(math.radians(th3))
        ld_V_shear_3 = max(abs(Vu) / phi_v - Vp, 0) - 0.5 * Vs_des_3 if phi_v > 0 else 0
        if torsion_consider and tors_Ao > 0:
            ld_VT_3 = math.sqrt(max(ld_V_shear_3, 0) ** 2 + ld_T_tors ** 2)
        else:
            ld_VT_3 = max(ld_V_shear_3, 0)
        long_dem_3 = ld_M + ld_N + ld_VT_3 * cott_3
        long_ok_3 = long_cap >= long_dem_3
    else:
        Vs_des_3 = None
        cott_3 = None
        ld_VT_3 = None
        long_dem_3 = None
        long_ok_3 = None

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
        "Vn1_uncapped": Vn1_uncapped, "Vn1_capped": Vn1_capped,
        # Method 2
        "bt2a": bt2a, "bt2b": bt2b, "bt2": bt2, "th2": th2,
        "Vc2": Vc2, "Vs2": Vs2, "Vn2": Vn2, "Vr2": Vr2,
        "Vn2_uncapped": Vn2_uncapped, "Vn2_capped": Vn2_capped,
        # Method 3
        "th3": th3, "bt3": bt3, "ex_b5": ex_b5, "n_iter": n_iter, "b5_valid": b5_valid,
        "vu_b5": vu_b5, "vufc": vufc, "Act": Act, "b5_max_ex": b5_max_ex,
        "b5_ex_num": b5_ex_num, "b5_denom_used": b5_denom_used,
        "b5_ex_neg_recalc": b5_ex_neg_recalc, "b5_Vterm": b5_Vterm, "b5_cot_th": b5_cot_th,
        "Vc3": Vc3, "Vs3": Vs3, "Vn3": Vn3, "Vr3": Vr3,
        "Vn3_uncapped": Vn3_uncapped, "Vn3_capped": Vn3_capped,
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
        # Longitudinal - Method 1 (Simplified, θ=45°)
        "cott_1": cott_1, "Vs_des_1": Vs_des_1, "ld_VT_1": ld_VT_1,
        "long_dem_1": long_dem_1, "long_ok_1": long_ok_1,
        # Longitudinal - Method 3 (Appendix B5)
        "cott_3": cott_3, "Vs_des_3": Vs_des_3, "ld_VT_3": ld_VT_3,
        "long_dem_3": long_dem_3, "long_ok_3": long_ok_3,
        # Shear Method Breakdowns
        "breakdown_shear_m1": shear_breakdown_m1.to_dict(),
        "breakdown_shear_m2": shear_breakdown_m2.to_dict(),
        "breakdown_shear_m3": shear_breakdown_m3.to_dict(),
    }


# ─── Torsion ────────────────────────────────────────────────────────

def do_torsion(I, flex, shear, Pu, Mu, Vu, Tu, Vp):
    """Compute torsion capacity and combined checks. Returns dict."""
    fc, fy_long, lam, phi_v = I["fc"], I["fy_long"], I["lam"], I["phi_v"]
    fy_trans = I["fy_trans"]
    is_rect, b, h, bw, cover = I["isRect"], I["b"], I["h"], I["bw"], I["cover"]
    hf_top, hf_bot = I["hf_top"], I["hf_bot"]
    ds = flex["ds"]
    As = flex["As"]
    Aps, Av, s_shear = I["Aps"], I["Av"], I["s_shear"]
    s_torsion = I["s_torsion"]
    tBar_a = I["tBar_a"]
    At = tBar_a  # Area of single stirrup bar leg (same as shear bar)
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

    lambda_duct = shear["lambda_duct"]

    # Available stirrup capacity for torsion (C5.7.3.6.2)
    # Only 2 external legs of stirrups form closed loop for torsion; interior legs resist shear only
    V_steel = max(abs(Vu) / phi_v - Vc_gp - Vp, 0) if phi_v > 0 else 0
    Av_s_shear = V_steel / (fy_trans * dv * cott) if (fy_trans * dv * cott) > 0 else 0

    # Only 2 external legs available for torsion (St. Venant shear flows on outer perimeter)
    shBar_a = I["shBar_a"]
    shear_legs_val = max(I.get("shear_legs", 1), 1)
    Av_ext_s = 2 * shBar_a / s_shear if s_shear > 0 else 0  # 2 external legs capacity
    Av_s_shear_ext = Av_s_shear * (2 / shear_legs_val)  # shear demand from external legs
    At_s_avail = max(Av_ext_s - Av_s_shear_ext, 0) / 2  # available per leg after shear demand

    # Additional torsional stirrups (closed loops, 2 external legs, outer perimeter only)
    At_s_additional = I.get("at_add_bar_a", 0) / I.get("s_at_add", 1) if I.get("s_at_add", 0) > 0 else 0

    # Tn based on torsion stirrup capacity (5.7.3.6.2-1): total of external stirrups + additional torsional stirrups
    At_s_design = At_s_avail + At_s_additional
    Tn = 2 * Ao * At_s_design * fy_trans * cott * lambda_duct if At_s_design > 0 else 0
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
        f"Available stirrup area after shear: At_s_avail = max(Av_ext_s - Av_s_shear_ext, 0) / 2",
        f"At_s_avail = max({fmt_num(Av_ext_s, 3)}-{fmt_num(Av_s_shear_ext, 3)}, 0) / 2 = {fmt_num(At_s_avail, 4)}",
        At_s_avail, "in²/in"
    )
    torsion_breakdown_tn.add(
        f"Design stirrup area: At_s_design = At_s_avail + At_s_additional",
        f"At_s_design = {fmt_num(At_s_avail, 4)} + {fmt_num(At_s_additional, 4)} = {fmt_num(At_s_design, 4)}",
        At_s_design, "in²/in"
    )
    torsion_breakdown_tn.add(
        f"Tn = 2·Ao·At_s_design·fy_trans·cot(θ)·λ_duct",
        f"Tn = 2·{fmt_num(Ao, 1)}·{fmt_num(At_s_design, 4)}·{fmt_num(fy_trans, 0)}·cot({fmt_num(theta, 1)}°)·{fmt_num(lambda_duct, 2)}",
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
    At_s_tors = abs(Tu) / (phi_v * 2 * Ao * fy_trans * cott) if consider and (phi_v * 2 * Ao * fy_trans * cott) > 0 else 0
    Av_s_comb = Av_s_shear + 2 * At_s_tors
    comb_reinf_ok = Av_ext_s >= Av_s_comb

    min_trans = 0.0316 * math.sqrt(fc) * bv * s_shear / fy_trans if fy_trans > 0 and fc > 0 else 0

    s_max_tors = min(ph / 8, 12) if ph > 0 else 12

    return {
        "pc": pc, "Acp": Acp, "be": be, "Ao": Ao, "ph": ph,
        "Tcr": Tcr, "thresh": thresh, "consider": consider,
        "theta": theta, "At": At, "Tn": Tn, "Tr": Tr,
        "At_s_avail": At_s_avail, "At_s_additional": At_s_additional, "At_s_design": At_s_design,
        "tors_shear": tors_shear, "Veff": Veff,
        "comb_stress": comb_stress, "comb_lim": comb_lim, "comb_ok": comb_ok,
        "Av_s_shear": Av_s_shear, "At_s_tors": At_s_tors,
        "Av_s_comb": Av_s_comb, "Av_ext_s": Av_ext_s, "comb_reinf_ok": comb_reinf_ok,
        "min_trans": min_trans,
        "s_max_tors": s_max_tors,
        # Torsion Breakdowns
        "breakdown_torsion_tcr": torsion_breakdown_tcr.to_dict(),
        "breakdown_torsion_tn": torsion_breakdown_tn.to_dict(),
    }


# ─── Compute Row Capacities ────────────────────────────────────────

def compute_row_capacities(I, pm_curve_sag, pm_curve_hog, Pu, Mu, Vu, Tu, Vp, Ms, Ps):
    """Compute capacities and status for a single demand row."""
    fc, fy_long, Es, Ept = I["fc"], I["fy_long"], I["Es"], I["Ept"]
    fy_trans = I["fy_trans"]
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
    c = (As * fy_long + Aps * fpu - As_comp * fy_long - Pu) / c_denom if c_denom > 0 else 0.01
    if c <= 0:
        c = 0.01
    a = c * beta1
    # Step 2: If T-section and a > hf, re-solve with T-formula
    if not is_rect and a > hf and hf > 0:
        c_T_denom = alpha1 * fc * beta1 * bw + (k_pt * Aps * fpu / dp if Aps > 0 and dp > 0 else 0)
        c_T = (As * fy_long + Aps * fpu - As_comp * fy_long - alpha1 * fc * (b - bw) * hf - Pu) / c_T_denom if c_T_denom > 0 else c
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
        c = (As * fy_long - As_comp * fy_long - Pu) / c_denom2 if c_denom2 > 0 else 0.01
        if c <= 0:
            c = 0.01
        a = c * beta1
        if not is_rect and a > hf and hf > 0:
            c_T_d2 = alpha1 * fc * beta1 * bw
            c_T2 = (As * fy_long - As_comp * fy_long - alpha1 * fc * (b - bw) * hf - Pu) / c_T_d2 if c_T_d2 > 0 else c
            if c_T2 > 0:
                c = c_T2
        if c <= 0:
            c = 0.01
        a = c * beta1

    Aps_tens = 0 if pt_in_compression else Aps
    fps_calc = fpu * (1 - k_pt * c / dp) if Aps_tens > 0 and dp > 0 else 0

    if is_rect or a <= hf:
        Mn = As * fy_long * (ds - a / 2) + (Aps_tens * fps_calc * (dp - a / 2) if Aps_tens > 0 else 0)
    else:
        Cf = alpha1 * fc * (b - bw) * hf
        Cw = alpha1 * fc * bw * a
        Mn = (Cf * (ds - hf / 2) + Cw * (ds - a / 2)
              + (Aps_tens * fps_calc * (dp - a / 2) if Aps_tens > 0 else 0)
              - (As_comp * fy_long * (ds - cover) if As_comp > 0 else 0))

    tot_tens = As * fy_long + (Aps_tens * fps_calc if Aps_tens > 0 else 0)
    if Aps_tens > 0 and As > 0:
        de_row = (Aps_tens * fps_calc * dp + As * fy_long * ds) / tot_tens if tot_tens > 0 else ds
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
        Av_min = 0.0316 * math.sqrt(fc) * bv * s_shear / fy_trans if fy_trans > 0 and fc > 0 else 0
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
        Ec_row = Ec if Ec > 0 else _ec_aashto(fc, I.get("K1", 1.0), I.get("wc", 0.145))
        denom_neg = (2 * (Es * As + Ept * Aps_tens) + Ec_row * Act_row) if has_min_av else (Es * As + Ept * Aps_tens + Ec_row * Act_row)
        eps_s = (Mu_c / dv + 0.5 * Pu + abs(V_strain - Vp) - Aps_tens * fpo) / denom_neg if denom_neg > 0 else 0
        eps_s = max(eps_s, -0.0004)
    eps_s = min(eps_s, 0.006)

    sx = dv
    sxe = min(max(sx * 1.38 / (ag + 0.63), 12), 80) if (ag + 0.63) > 0 else 12
    Vnmax = 0.25 * fc * bv * dv + Vp

    # Method 1
    Vc1 = 0.0316 * 2 * lam * math.sqrt(fc) * bv * dv if fc > 0 else 0
    Vs1 = Av * fy_trans * dv * lambda_duct / math.tan(math.radians(45)) / s_shear if s_shear > 0 else 0
    Vn1_uncapped = Vc1 + Vs1 + Vp
    Vn1_capped = Vn1_uncapped > Vnmax
    Vr1 = phi_v * min(Vn1_uncapped, Vnmax)

    # Method 2
    bt2 = 4.8 / (1 + 750 * eps_s) if has_min_av else 4.8 / (1 + 750 * eps_s) * 51 / (39 + sxe)
    th2 = 29 + 3500 * eps_s
    Vc2 = 0.0316 * bt2 * lam * math.sqrt(fc) * bv * dv if fc > 0 else 0
    Vs2 = Av * fy_trans * dv * lambda_duct / math.tan(math.radians(th2)) / s_shear if s_shear > 0 and th2 > 0 else 0
    Vn2_uncapped = Vc2 + Vs2 + Vp
    Vn2_capped = Vn2_uncapped > Vnmax
    Vr2 = phi_v * min(Vn2_uncapped, Vnmax)

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
            Ec_val = Ec if Ec > 0 else _ec_aashto(fc, I.get("K1", 1.0), I.get("wc", 0.145))
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
    Vn3_uncapped = 0
    Vn3_capped = False
    if b5_valid:
        Vc3 = 0.0316 * bt3 * lam * math.sqrt(fc) * bv * dv if fc > 0 else 0
        Vs3 = Av * fy_trans * dv * lambda_duct / math.tan(math.radians(th3)) / s_shear if s_shear > 0 and th3 > 0 else 0
        Vn3_uncapped = Vc3 + Vs3 + Vp
        Vn3_capped = Vn3_uncapped > Vnmax
        Vr3 = phi_v * min(Vn3_uncapped, Vnmax)

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
    # Only 2 external legs of stirrups form closed loop for torsion
    V_steel_row = max(abs(Vu) / phi_v - Vc2 - Vp, 0) if phi_v > 0 else 0
    Av_s_shear_row = V_steel_row / (fy_trans * dv * cott) if (fy_trans * dv * cott) > 0 else 0

    # Only 2 external legs available for torsion
    shBar_a = I["shBar_a"]
    shear_legs_val = max(I.get("shear_legs", 1), 1)
    Av_ext_s_row = 2 * shBar_a / s_shear if s_shear > 0 else 0
    Av_s_shear_ext_row = Av_s_shear_row * (2 / shear_legs_val)
    At_s_avail_row = max(Av_ext_s_row - Av_s_shear_ext_row, 0) / 2

    # Additional torsional stirrups (2 external legs, outer perimeter only)
    At_s_additional = I.get("at_add_bar_a", 0) / I.get("s_at_add", 1) if I.get("s_at_add", 0) > 0 else 0

    Tn = 2 * Ao * (At_s_avail_row + At_s_additional) * fy_trans * cott * lambda_duct if (At_s_avail_row + At_s_additional) > 0 else 0
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
    fss_simp = 0.6 * fy_long
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
        if fss_act > 0.6 * fy_long:
            crack_status = "NG"
        if s_crack_val <= 0:
            crack_status = "NG"

    # Flex status
    gamma1 = 1.6
    astm_spec = I.get("astm_spec", "A615_60")
    astm_gamma3_map = {
        "A615_60": 0.67, "A615_75": 0.75, "A615_80": 0.76,
        "A706_60": 0.75, "A706_80": 0.8,
        "A1035_100": 0.67,
        "A615": 0.67, "A706": 0.75  # Legacy values
    }
    gamma3 = astm_gamma3_map.get(astm_spec, 0.67)
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

    # Longitudinal reinforcement check (5.7.3.5-1 / 5.7.3.6.3-1) per row
    fo = I.get("factor_overrides", {})
    phi_c_row = fo.get("phi_c_f", 0.75)
    eps_t_row = 0.003 * (ds - c) / c if c > 0 else 0.005
    phi_f_row = get_phi_flex(code_edition, section_class, eps_t_row, ecl, etl)
    if "phi_f_f" in fo:
        phi_f_row = fo["phi_f_f"]
    ld_M_row = abs(Mu) / (dv * phi_f_row) if (dv * phi_f_row) > 0 else 0
    ld_N_row = 0.5 * Pu / phi_c_row
    long_cap_row = As * fy_long + (Aps_tens * fps_calc if Aps_tens > 0 else 0)

    # Torsion longitudinal component (SRSS per 5.7.3.6.3)
    if torsion_consider_row and tors_Ao > 0:
        ld_T_tors_row = 0.45 * tors_ph * abs(Tu) / (2 * tors_Ao * phi_v) if phi_v > 0 else 0
    else:
        ld_T_tors_row = 0

    # Method 1 (theta=45)
    Vs_des_1_r = min(Vs1, abs(Vu) / phi_v) if phi_v > 0 else Vs1
    ld_V_1_r = max(abs(Vu) / phi_v - Vp, 0) - 0.5 * Vs_des_1_r if phi_v > 0 else 0
    ld_VT_1_r = math.sqrt(max(ld_V_1_r, 0) ** 2 + ld_T_tors_row ** 2) if ld_T_tors_row > 0 else max(ld_V_1_r, 0)
    long_dem_1_r = ld_M_row + ld_N_row + ld_VT_1_r * 1.0
    long_ok_1_r = long_cap_row >= long_dem_1_r

    # Method 2 (General Procedure)
    Vs_des_2_r = min(Vs2, abs(Vu) / phi_v) if phi_v > 0 else Vs2
    cott_2_r = 1 / math.tan(math.radians(th2)) if th2 > 0 else 0
    ld_V_2_r = max(abs(Vu) / phi_v - Vp, 0) - 0.5 * Vs_des_2_r if phi_v > 0 else 0
    ld_VT_2_r = math.sqrt(max(ld_V_2_r, 0) ** 2 + ld_T_tors_row ** 2) if ld_T_tors_row > 0 else max(ld_V_2_r, 0)
    long_dem_2_r = ld_M_row + ld_N_row + ld_VT_2_r * cott_2_r
    long_ok_2_r = long_cap_row >= long_dem_2_r

    # Method 3 (Appendix B5)
    if b5_valid and th3 > 0:
        Vs_des_3_r = min(Vs3, abs(Vu) / phi_v) if phi_v > 0 else Vs3
        cott_3_r = 1 / math.tan(math.radians(th3))
        ld_V_3_r = max(abs(Vu) / phi_v - Vp, 0) - 0.5 * Vs_des_3_r if phi_v > 0 else 0
        ld_VT_3_r = math.sqrt(max(ld_V_3_r, 0) ** 2 + ld_T_tors_row ** 2) if ld_T_tors_row > 0 else max(ld_V_3_r, 0)
        long_dem_3_r = ld_M_row + ld_N_row + ld_VT_3_r * cott_3_r
        long_ok_3_r = long_cap_row >= long_dem_3_r
    else:
        long_ok_3_r = None

    long_dc_1_r = long_dem_1_r / long_cap_row if long_cap_row > 0 else None
    long_dc_2_r = long_dem_2_r / long_cap_row if long_cap_row > 0 else None
    long_dc_3_r = (long_dem_3_r / long_cap_row if long_cap_row > 0 else None) if long_ok_3_r is not None else None

    return {
        "Mr": Mr_signed, "Vr1": Vr1, "Vr2": Vr2, "Vr3": Vr3, "Tr": Tr,
        "Vnmax": Vnmax,
        "Vn1_uncapped": Vn1_uncapped, "Vn1_capped": Vn1_capped,
        "Vn2_uncapped": Vn2_uncapped, "Vn2_capped": Vn2_capped,
        "Vn3_uncapped": Vn3_uncapped, "Vn3_capped": Vn3_capped,
        "crackStatus": crack_status, "flexStatus": flex_status, "shearStatus": shear_status,
        "torsionConsider": torsion_consider_row,
        "shReqd": sh_reqd, "hasMinAv": has_min_av,
        "long_ok_1": long_ok_1_r, "long_ok_2": long_ok_2_r, "long_ok_3": long_ok_3_r,
        "long_dc_1": long_dc_1_r, "long_dc_2": long_dc_2_r, "long_dc_3": long_dc_3_r,
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
            "wc": I.get("wc", 0.145), "K1": I.get("K1", 1.0),
            "h": I["h"], "b": I["b"], "cover": I["cover"],
            "dp": I["dp"],
            "hf_top": I.get("hf_top", 0), "hf_bot": I.get("hf_bot", 0),
            "As_top": I["As_top"], "As_bot": I["As_bot"],
            "d_top": I["d_top"], "d_bot": I["d_bot"],
            "bar_d_top": I["bar_d_top"], "bar_d_bot": I["bar_d_bot"],
            "Aps": I["Aps"],
            "isRect": I["isRect"], "bw": I["bw"],
            "hasPT": I["hasPT"],
            "ecl": I["ecl"], "etl": I["etl"], "alpha1": I["alpha1"], "beta1": I["beta1"],
            "kc": I["alpha1"],  # kc per Eq. 5.6.4.4-3 (same formula as α₁)
            "phi_v": I["phi_v"], "gamma_e": I["gamma_e"], "lam": I["lam"],
            "Ag": I["Ag"], "Ig": I["Ig"], "yb_centroid": I["yb_centroid"],
        },
        "demands": {"Pu": Pu, "Mu": Mu, "Vu": Vu, "Tu": Tu, "Vp": Vp, "Ms": Ms, "Ps": Ps},
        "flexure": flex,
        "shear": shear,
        "torsion": torsion,
        "row_results": row_results,
    }
