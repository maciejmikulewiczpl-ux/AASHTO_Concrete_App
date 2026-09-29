"""
AASHTO LRFD circular section engine (solid circular columns / piles / shafts).

Called from calc_engine.calculate_all() when secType == "CIRCULAR". Produces the
same result structure as the rectangular / I-section path so the UI and report
can render it; circular-only data is added under flexure["circ"].

Shear (all 3 methods) and torsion reuse calc_engine.do_shear / do_torsion with
circular-only geometry overrides (guarded by I["isCirc"]).

Units: kip, inch, ksi.

Citation policy (CODE_PROTECTION.md): provisions listed in CIRC_UNVERIFIED are
implemented from general AASHTO LRFD understanding or read from notation/commentary
whose equation image was not legible in the supplied Chapter 5 text. Everything
else was checked against AASHTO LRFD BDS 10th Ed. (2024) Chapter 5 on 2026-09-29.
"""
import math

import calc_engine as ce

# AASHTO 10th Ed §5.6.4.4 (C5.6.4.4: "values of 0.85 and 0.80 in Eqs. 5.6.4.4-2 and -3"):
#   0.85 — spirals, or hoops closed by full-welded splice / full-mechanical coupler /
#          overlapping hooks around longitudinal bars (Eq. 5.6.4.4-2)
#   0.80 — ties, or hoops closed with a lap splice (Eq. 5.6.4.4-3)
TIE_PN_FACTOR = 0.80
SPIRAL_PN_FACTOR = 0.85

CIRC_UNVERIFIED = [
    "Av = 2·A_hoop + n_ties·A_tie (hoop/spiral crosses the shear plane twice) — 5.7.3.3 defines Av only as "
    "'area of transverse reinforcement within s'; no circular-specific rule found",
    "Crack-control s = centre-to-centre arc spacing of the outer ring — §5.6.7 defines s for the layer "
    "closest to the tension face; no circular-specific rule (interpretation)",
    "fps = fpu·(1 − k·c/dp) (§5.6.3.1.1, stated for rectangular/flanged sections) used with circular-segment c; "
    "§5.6.3.2.4 asks for a 5.6.2-based analysis for other shapes (P-M curve already uses strain compatibility)",
]


# ─── Geometry ───────────────────────────────────────────────────────

def circle_segment(R, a):
    """Circular segment of depth a measured from the compression face.

    Returns (area, y_cf, I_c): y_cf = centroid depth from the compression face,
    I_c = second moment about the circle's own horizontal centroidal axis.
    """
    a = max(0.0, min(a, 2.0 * R))
    if a <= 0 or R <= 0:
        return 0.0, 0.0, 0.0
    th = math.acos(max(-1.0, min(1.0, (R - a) / R)))
    s, c = math.sin(th), math.cos(th)
    k = th - s * c
    area = R * R * k
    zbar = 2.0 * R * s ** 3 / (3.0 * k) if k > 0 else R
    I_c = R ** 4 / 4.0 * (k + 2.0 * s ** 3 * c)
    return area, R - zbar, I_c


def _bundle_centroid_offset(db, nb):
    # 3-bar bundle: two bars tangential on the outside, one inside (triangle)
    return db * math.sqrt(3.0) / 6.0 if nb == 3 else 0.0


def _bundle_width(db, nb):
    return db if nb <= 1 else 2.0 * db


def circ_layout(I):
    """List of bar positions (bundles treated as one bar at the bundle centroid)."""
    D = I["D"]
    R = D / 2.0
    cover = I["cover"]
    d_tr = I["circ_trans_d"]
    bars = []
    rings = []
    ring_specs = [(1, I["circ_bar1"], I["circ_n1"], I["circ_bundle1"], None)]
    if I.get("circ_ring2") and I.get("circ_n2", 0) > 0:
        ring_specs.append((2, I["circ_bar2"], I["circ_n2"], I["circ_bundle2"], I.get("circ_Dr2", 0)))
    for ring, barN, n, nb, Dr_in in ring_specs:
        bar = ce.BARS.get(int(barN), ce.BARS[8])
        n = int(n)
        nb = max(1, min(int(nb), 3))
        if n <= 0:
            continue
        if ring == 1:
            r = R - cover - d_tr - bar["d"] / 2.0 - _bundle_centroid_offset(bar["d"], nb)
        else:
            r = float(Dr_in) / 2.0
        if r <= 0:
            raise ValueError(f"Circular ring {ring}: bar circle diameter must be > 0 (check D, cover, bar sizes)")
        As_pos = nb * bar["a"]
        for i in range(n):
            ang = 2.0 * math.pi * i / n
            bars.append({
                "ring": ring, "idx": i, "angle_deg": math.degrees(ang),
                "x": r * math.sin(ang), "d_top": R - r * math.cos(ang),
                "As": As_pos, "barN": int(barN), "bar_d": bar["d"], "bundle": nb,
            })
        chord = 2.0 * r * math.sin(math.pi / n) if n > 1 else 0.0
        rings.append({
            "ring": ring, "barN": int(barN), "n": n, "bundle": nb, "bar_d": bar["d"],
            "bar_a": bar["a"], "As": n * As_pos, "Dr": 2.0 * r, "r": r,
            "s_arc": (2.0 * math.pi * r / n) if n > 0 else 0.0,
            "s_clear": chord - _bundle_width(bar["d"], nb) if n > 1 else 0.0,
            "d_eq": bar["d"] * math.sqrt(nb),
        })
    return bars, rings


def _rows_cf(bars, comp_face, D):
    """Group bars by depth from the compression face → [{d_cf, As, n}] sorted by depth."""
    rows = {}
    for b in bars:
        d_cf = b["d_top"] if comp_face == "top" else D - b["d_top"]
        key = round(d_cf, 6)
        r = rows.setdefault(key, {"d_cf": d_cf, "As": 0.0, "n": 0})
        r["As"] += b["As"]
        r["n"] += 1
    return [rows[k] for k in sorted(rows)]


def _tension_half_As(rows, R):
    """Steel area on the flexural-tension half (bars exactly on the centreline count half)."""
    As = 0.0
    for r in rows:
        if r["d_cf"] > R + 1e-9:
            As += r["As"]
        elif abs(r["d_cf"] - R) <= 1e-9:
            As += 0.5 * r["As"]
    return As


def derive_circular(I):
    """Prepare a circular input dict: run the shared derive_constants, then override geometry."""
    D = float(I.get("D") or I.get("h") or 0)
    if D <= 0:
        raise ValueError("Circular section: diameter D must be > 0")
    I["D"] = D
    I["b"] = I["h"] = I["bw_input"] = D
    I["hf_top"] = I["hf_bot"] = 0
    I.setdefault("circ_bar1", 8)
    I.setdefault("circ_n1", 8)
    I.setdefault("circ_bundle1", 1)
    I.setdefault("circ_ring2", False)
    I.setdefault("circ_bar2", 8)
    I.setdefault("circ_n2", 0)
    I.setdefault("circ_bundle2", 1)
    I.setdefault("circ_Dr2", 0)
    I.setdefault("circ_trans_type", "hoop")
    I.setdefault("circ_hoop_closure", "lap")
    I.setdefault("circ_tie_legs", 0)
    I.setdefault("circ_tie_bar", I.get("shN", 4))
    I.setdefault("shN", 4)
    I.setdefault("tN", I["shN"])
    I.setdefault("shear_legs", 2)
    for k, v in (("barN_bot", I["circ_bar1"]), ("nBars_bot", 0), ("barN_top", 0), ("nBars_top", 0),
                 ("As_top_ovr", None), ("As_bot_ovr", None), ("d_bot", D / 2), ("d_top", D / 2)):
        I.setdefault(k, v)
    I["mr_rows_bot"] = None
    I["mr_rows_top"] = None
    I["at_add_bar_N"] = 0
    I["s_at_add"] = 0

    ce.derive_constants(I)

    R = D / 2.0
    s_tr = I["s_shear"]
    has_trans = s_tr > 0 and I.get("shear_legs", 0) > 0
    tr_bar = ce.BARS.get(int(I["shN"]), ce.BARS[4])
    I["circ_trans_d"] = tr_bar["d"] if has_trans else 0.0
    I["circ_spiral"] = I["circ_trans_type"] == "spiral"
    # Spiral, or AASHTO "hoop" (5.2: closure by full-welded splice, full-mechanical coupler or
    # hooks around longitudinal bars) → Eq. 5.6.4.4-2 and §5.6.4.6 ρs. Lap-closed hoop → tie.
    I["circ_confined"] = I["circ_spiral"] or (I["circ_trans_type"] == "hoop" and I["circ_hoop_closure"] != "lap")

    bars, rings = circ_layout(I)
    I["circ_bars"] = bars
    I["circ_rings"] = rings
    Ast = sum(b["As"] for b in bars)
    I["circ_Ast"] = Ast

    I["isRect"] = False
    I["isCirc"] = True
    I["bw"] = D
    I["Ag"] = math.pi * R * R
    I["Ig"] = math.pi * D ** 4 / 64.0
    I["yb_centroid"] = R

    # Echo keys used by the UI (tension half for sagging = "bot", hogging = "top")
    rows_top = _rows_cf(bars, "top", D)
    As_half = _tension_half_As(rows_top, R)
    I["As_bot"] = As_half
    I["As_top"] = Ast - As_half
    I["d_bot"] = max((b["d_top"] for b in bars), default=R)
    I["d_top"] = min((b["d_top"] for b in bars), default=R)
    outer = rings[0] if rings else {"bar_d": 0, "bar_a": 0, "n": 0, "barN": 0}
    I["bar_d_bot"] = I["bar_d_top"] = outer["bar_d"]
    I["bar_a_bot"] = I["bar_a_top"] = outer["bar_a"]
    I["barN_bot"] = I["barN_top"] = outer["barN"]
    I["nBars_bot"] = I["nBars_top"] = outer["n"]

    # Transverse reinforcement
    if has_trans:
        tie_n = max(int(I.get("circ_tie_legs") or 0), 0)
        tie_bar = ce.BARS.get(int(I.get("circ_tie_bar") or I["shN"]), tr_bar)
        Av = 2.0 * tr_bar["a"] + tie_n * tie_bar["a"]
        I["circ_tie_a"] = tie_bar["a"] if tie_n > 0 else 0.0
        I["circ_tie_legs"] = tie_n
    else:
        Av = 0.0
        I["circ_tie_a"] = 0.0
        I["circ_tie_legs"] = 0
    I["Av"] = Av
    I["shBar_a"] = tr_bar["a"]
    I["shBar_d"] = tr_bar["d"]
    # Effective leg count: do_torsion apportions shear demand to the 2 "external" legs (the hoop)
    I["shear_legs"] = Av / tr_bar["a"] if (has_trans and tr_bar["a"] > 0) else 0
    I["tN"] = int(I["shN"])
    I["tBar_a"] = tr_bar["a"]
    I["tBar_d"] = tr_bar["d"]
    I["at_add_bar_a"] = 0
    I["at_add_bar_d"] = 0

    # Torsion geometry (consumed by calc_engine.compute_torsion_threshold / do_torsion)
    Acp = I["Ag"]
    pc = math.pi * D
    be = Acp / pc
    Dh = D - 2.0 * I["cover"] - I["circ_trans_d"]
    I["circ_tors"] = {
        "Acp": Acp, "pc": pc, "be": be,
        "Ao": math.pi * (D - be) ** 2 / 4.0,
        "ph": math.pi * Dh if Dh > 0 else 0.0,
        "Dh": Dh,
    }
    return I


# ─── Strain compatibility point (P-M) ───────────────────────────────

def _steel_stress(es, Es, fy):
    return min(abs(es) * Es, fy) * (1 if es >= 0 else -1)


def _pn_max(I):
    fc, fy, Ept = I["fc"], I["fy_long"], I["Ept"]
    Aps, fpe = I["Aps"], I.get("fpe", 0)
    Ast = I["circ_Ast"]
    kc = I["alpha1"]
    factor = SPIRAL_PN_FACTOR if I["circ_confined"] else TIE_PN_FACTOR
    pt_red = Aps * (fpe - Ept * 0.003) if Aps > 0 else 0
    bracket = kc * fc * (I["Ag"] - Ast - Aps) + fy * Ast - pt_red
    return -factor * bracket, factor, bracket, kc, pt_red


def _pm_geometry(I, comp_face):
    D = I["D"]
    R = D / 2.0
    rows = _rows_cf(I["circ_bars"], comp_face, D)
    dp = I["dp"]
    dp_cf = (D - dp) if (comp_face == "bottom" and dp > 0) else dp
    d_max = max((r["d_cf"] for r in rows), default=R)
    dt = max(d_max, dp_cf) if I["Aps"] > 0 else d_max
    return {
        "D": D, "R": R, "rows": rows, "dp_cf": dp_cf, "dt": dt,
        "tens_rows": [r for r in rows if r["d_cf"] > R],
        "comp_rows": [r for r in rows if r["d_cf"] <= R],
        "m_sign": 1 if comp_face == "top" else -1,
    }


def _pm_point(I, g, c, Pn_max):
    fc, fy, Es, Ept = I["fc"], I["fy_long"], I["Es"], I["Ept"]
    fpy, alpha1, beta1 = I["fpy"], I["alpha1"], I["beta1"]
    Aps = I["Aps"]
    eps_pe = I.get("fpe", 0) / Ept if Ept > 0 else 0
    D, R, dp_cf, dt = g["D"], g["R"], g["dp_cf"], g["dt"]

    a = min(c * beta1, D)
    A_seg, y_cf, _ = circle_segment(R, a)
    Cc = -alpha1 * fc * A_seg
    Mn_cc = -Cc * (R - y_cf)

    def _rows(rows):
        out, F_sum, M_sum = [], 0.0, 0.0
        for r in rows:
            es = 0.003 * (r["d_cf"] - c) / c
            fs = _steel_stress(es, Es, fy)
            F = r["As"] * fs
            F_sum += F
            M_sum += F * (r["d_cf"] - R)
            out.append({"d_cf": r["d_cf"], "As": r["As"], "es": es, "fs": fs, "F": F})
        return out, F_sum, M_sum

    rt, Ft, Mt = _rows(g["tens_rows"])
    rc, Fc, Mc = _rows(g["comp_rows"])
    ext_t = max(rt, key=lambda r: r["d_cf"]) if rt else None
    ext_c = min(rc, key=lambda r: r["d_cf"]) if rc else None

    Tpt = eps_p = fps = d_eps = 0.0
    if Aps > 0 and dp_cf > 0:
        d_eps = 0.003 * (dp_cf - c) / c
        eps_p = eps_pe + d_eps
        fps = min(abs(eps_p) * Ept, fpy) * (1 if eps_p >= 0 else -1)
        Tpt = Aps * fps
    M_pt = Tpt * (dp_cf - R) if Aps > 0 else 0.0

    Pn = max(Cc + Ft + Fc + Tpt, Pn_max)
    Mn = (Mn_cc + Mt + Mc + M_pt) * g["m_sign"]
    et = 0.003 * (dt - c) / c
    if c >= dt:
        phi, st = 0.75, "CC"
    else:
        phi = ce.get_phi_flex(I["codeEdition"], I["sectionClass"], et, I["ecl"], I["etl"])
        st = "TC" if abs(et) >= I["etl"] else ("CC" if abs(et) <= I["ecl"] else "TR")
    return {
        "c": c, "a": a, "eps_t": abs(et), "stat": st, "phi": phi,
        "Pn": Pn, "Mn": Mn, "Pr": Pn * phi, "Mr": Mn * phi,
        "es_tens": ext_t["es"] if ext_t else 0, "fs_tens": ext_t["fs"] if ext_t else 0, "F_tens": Ft,
        "es_comp": ext_c["es"] if ext_c else 0, "fs_comp": ext_c["fs"] if ext_c else 0, "F_comp": Fc,
        "rows_tens": rt, "rows_comp": rc,
        "eps_pe": eps_pe, "delta_eps": d_eps, "eps_pt": eps_p, "fps_pt": fps, "F_pt": Tpt,
        "A_comp": A_seg, "y_cc": y_cf, "Cc": Cc,
    }


def build_pm_curve_circ(I, comp_face="top"):
    """40-point factored P-M curve for a circular section (same point schema as rect/I)."""
    g = _pm_geometry(I, comp_face)
    D, dt = g["D"], g["dt"]
    beta1, fy, Es = I["beta1"], I["fy_long"], I["Es"]
    Pn_max = _pn_max(I)[0]
    dt = max(dt, 0.1)
    g["dt"] = dt

    fy_ratio = fy / (0.003 * Es)
    c_sat = dt / (1 - fy_ratio) if fy_ratio < 1 else 3 * D
    c_upper_max = min(c_sat * 1.05, 5 * D)
    c_full = D / beta1
    upper = {round(c_full, 6)}
    for i in range(5, 0, -1):
        upper.add(round(c_full + (c_upper_max - c_full) * i / 5, 6))
    if c_full > dt:
        for i in range(8, 0, -1):
            upper.add(round(dt + (c_full - dt) * i / 8, 6))
    c_values = sorted((c for c in upper if c > dt), reverse=True)
    c_values += [dt * i / 40 for i in range(40, 0, -1)]
    c_values += [dt * i / 400 for i in range(9, 0, -1)]

    pts = [_pm_point(I, g, c, Pn_max) for c in c_values]

    # Pure tension: all steel yields, no concrete; moment about the centre
    Aps, fpy, dp = I["Aps"], I["fpy"], I["dp"]
    R = g["R"]
    Ast = I["circ_Ast"]
    Pn_t = Ast * fy + (Aps * fpy if Aps > 0 else 0)
    Mn_t = sum(b["As"] * fy * (b["d_top"] - R) for b in I["circ_bars"])
    if Aps > 0 and dp > 0:
        Mn_t += Aps * fpy * (dp - R)
    phi_t = ce.get_phi_flex(I["codeEdition"], I["sectionClass"], 0.01, I["ecl"], I["etl"])
    As_t = sum(r["As"] for r in g["tens_rows"])
    As_c = sum(r["As"] for r in g["comp_rows"])
    pts.append({
        "c": 0, "a": 0, "eps_t": 99, "stat": "TC", "phi": phi_t,
        "Pn": Pn_t, "Mn": Mn_t, "Pr": Pn_t * phi_t, "Mr": Mn_t * phi_t,
        "es_tens": 99, "fs_tens": fy, "F_tens": As_t * fy,
        "es_comp": 99, "fs_comp": fy, "F_comp": As_c * fy,
        "rows_tens": [{"d_cf": r["d_cf"], "As": r["As"], "es": 99, "fs": fy, "F": r["As"] * fy} for r in g["tens_rows"]],
        "rows_comp": [{"d_cf": r["d_cf"], "As": r["As"], "es": 99, "fs": fy, "F": r["As"] * fy} for r in g["comp_rows"]],
        "eps_pe": I.get("fpe", 0) / I["Ept"] if I["Ept"] > 0 else 0, "delta_eps": 99, "eps_pt": 99,
        "fps_pt": fpy if Aps > 0 else 0, "F_pt": Aps * fpy if Aps > 0 else 0,
        "A_comp": 0.0, "y_cc": 0.0, "Cc": 0.0,
    })
    return pts


def compute_pm_key_points_circ(I, pm_curve, comp_face="top", Pu=0):
    """Named P-M points with step-by-step strain-compatibility text (circular)."""
    g = _pm_geometry(I, comp_face)
    g["dt"] = max(g["dt"], 0.1)
    D, R, dt = g["D"], g["R"], g["dt"]
    fc, fy, Es = I["fc"], I["fy_long"], I["Es"]
    alpha1, beta1 = I["alpha1"], I["beta1"]
    ecl, etl = I["ecl"], I["etl"]
    Aps, Ept, fpy = I["Aps"], I["Ept"], I["fpy"]
    Pn_max, factor, bracket, kc, pt_red = _pn_max(I)
    Ast = I["circ_Ast"]

    def _steps_for(p):
        s = [f"c = {p['c']:.4f} in",
             f"a = min(β₁·c, D) = min({beta1:.4f}×{p['c']:.4f}, {D:.3f}) = {p['a']:.4f} in",
             f"Circular segment of depth a: A_comp = {p['A_comp']:.3f} in², centroid at {p['y_cc']:.4f} in from compression face",
             f"Cc = −α₁·f'c·A_comp = −{alpha1:.3f}×{fc}×{p['A_comp']:.3f} = {p['Cc']:.1f} kip",
             "", "--- Bars (grouped by depth from compression face) ---"]
        for r in p["rows_comp"] + p["rows_tens"]:
            s.append(f"  d={r['d_cf']:.3f}: As={r['As']:.3f}, εs=0.003×(d−c)/c = {r['es']:.6f}, "
                     f"fs = {r['fs']:.1f} ksi, F = {r['F']:.1f} kip, arm = d − D/2 = {r['d_cf'] - R:.3f} in")
        if Aps > 0 and g["dp_cf"] > 0:
            s.append(f"  PT: εps = εpe + Δε = {p['eps_pe']:.6f} + {p['delta_eps']:.6f} = {p['eps_pt']:.6f}, "
                     f"fps = {p['fps_pt']:.1f} ksi, Fpt = {p['F_pt']:.1f} kip")
        s += ["", f"Pn = max(Cc + ΣFs + Fpt, Pn,max) = {p['Pn']:.1f} kip  (Pn,max = {Pn_max:.1f} kip)",
              f"Mn about centre (moments of Cc, bars, PT about D/2) = {p['Mn']:.1f} kip-in",
              f"εt = 0.003×(dt−c)/c with dt = {dt:.3f} in → φ = {p['phi']:.4f}",
              f"Pr = φ·Pn = {p['Pr']:.1f} kip, Mr = φ·Mn = {p['Mr']:.1f} kip-in"]
        return s

    def _pt(c, name, desc):
        p = _pm_point(I, g, c, Pn_max)
        return {"c": c, "a": p["a"], "Pn": p["Pn"], "Mn": p["Mn"], "Pr": p["Pr"], "Mr": p["Mr"],
                "eps_t": p["eps_t"], "phi": p["phi"], "name": name, "description": desc,
                "steps": _steps_for(p)}

    kps = []
    ftxt = "0.85 (spiral)" if I["circ_spiral"] else "0.80 (hoops/ties)"
    steps_pc = [
        "c → ∞ (uniform compression, ε = 0.003 at all fibres)",
        f"Pn,max = −{factor:.2f}·[kc·f'c·(Ag − Ast − Aps) + fy·Ast − Aps·(fpe − Ep·εcu)]   factor = {ftxt}",
        f"  kc = α₁ = {kc:.3f}, Ag = πD²/4 = {I['Ag']:.2f} in², Ast = {Ast:.3f} in², Aps = {Aps:.3f} in²",
        f"  [bracket] = {kc:.3f}×{fc}×({I['Ag']:.2f} − {Ast:.3f} − {Aps:.3f}) + {fy}×{Ast:.3f} − {pt_red:.1f} = {bracket:.1f} kip",
        f"  Pn,max = {Pn_max:.1f} kip",
        f"φ = 0.75 → Pr = {0.75 * Pn_max:.1f} kip",
    ]
    if I["circ_spiral"]:
        steps_pc.append("NOTE: spiral factor 0.85 — AASHTO 5.6.4.4 region, equation number unverified.")
    kps.append({"c": None, "a": D, "Pn": Pn_max, "Mn": 0.0, "Pr": 0.75 * Pn_max, "Mr": 0.0,
                "eps_t": 0.003, "phi": 0.75, "name": "Pure Compression",
                "description": f"Uniform compression, Pn capped by Pn,max (factor {ftxt}).",
                "steps": steps_pc})
    kps.append(_pt(dt, "Zero Tension", "Extreme tension bar at zero strain (εt = 0, c = dt)"))
    kps.append(_pt(0.003 * dt / (0.003 + ecl), "Balanced (εt = εcl)",
                   f"Compression-controlled limit: εt = εcl = {ecl:.4f}"))
    kps.append(_pt(0.003 * dt / (0.003 + etl), "Tension Controlled (εt = εtl)",
                   f"Tension-controlled limit: εt = εtl = {etl:.4f}"))

    c_pf = None
    for p1, p2 in zip(pm_curve, pm_curve[1:]):
        if (p1["Pn"] <= 0 <= p2["Pn"]) or (p1["Pn"] >= 0 >= p2["Pn"]):
            if abs(p2["Pn"] - p1["Pn"]) > 1e-10:
                t = -p1["Pn"] / (p2["Pn"] - p1["Pn"])
                c_pf = p1["c"] + t * (p2["c"] - p1["c"])
                break
    if c_pf and c_pf > 0:
        kps.append(_pt(c_pf, "Pure Flexure (Pn = 0)", "Zero axial force — pure bending capacity"))

    c_dem, best = None, 0.0
    for p1, p2 in zip(pm_curve, pm_curve[1:]):
        lo, hi = sorted((p1["Pr"], p2["Pr"]))
        if lo <= Pu <= hi:
            dPr = p2["Pr"] - p1["Pr"]
            t = 0.5 if abs(dPr) < 1e-10 else max(0.0, min(1.0, (Pu - p1["Pr"]) / dPr))
            mr = abs(p1["Mr"] + t * (p2["Mr"] - p1["Mr"]))
            ci = p1["c"] + t * (p2["c"] - p1["c"])
            if mr >= best and ci > 0:
                best, c_dem = mr, ci
    if c_dem:
        kps.append(_pt(c_dem, f"At Demand (Pu = {Pu:.1f} kip)",
                       f"Capacity at the applied axial force Pu = {Pu:.1f} kip"))

    tp = pm_curve[-1]
    kps.append({"c": 0, "a": 0, "Pn": tp["Pn"], "Mn": tp["Mn"], "Pr": tp["Pr"], "Mr": tp["Mr"],
                "eps_t": 99, "phi": tp["phi"], "name": "Pure Tension",
                "description": "All steel yields in tension, no concrete contribution (c = 0)",
                "steps": [f"Pn = Ast·fy + Aps·fpy = {Ast:.3f}×{fy} + {Aps:.3f}×{fpy} = {tp['Pn']:.1f} kip",
                          f"Mn = Σ As·fy·(d − D/2) (+ PT) = {tp['Mn']:.1f} kip-in",
                          f"φ = {tp['phi']:.4f} → Pr = {tp['Pr']:.1f} kip"]})
    return kps


# ─── Flexure (pure bending, Pu = 0) ─────────────────────────────────

def _flex_state(I, rows, c, dp_cf, with_pt):
    fc, fy, Es = I["fc"], I["fy_long"], I["Es"]
    alpha1, beta1 = I["alpha1"], I["beta1"]
    R = I["D"] / 2.0
    a = min(beta1 * c, I["D"])
    A, y_cf, _ = circle_segment(R, a)
    Cc = alpha1 * fc * A
    bars = []
    F_sum = 0.0
    M = Cc * (R - y_cf)
    for r in rows:
        es = 0.003 * (r["d_cf"] - c) / c
        fs = _steel_stress(es, Es, fy)
        F = r["As"] * fs
        F_sum += F
        M += F * (r["d_cf"] - R)
        bars.append({"d_cf": r["d_cf"], "As": r["As"], "n": r["n"], "es": es, "fs": fs, "F": F})
    Tp = fps = 0.0
    if with_pt:
        fps = I["fpu"] * (1 - I["k_pt"] * c / dp_cf)
        Tp = I["Aps"] * fps
        M += Tp * (dp_cf - R)
    return {"c": c, "a": a, "A_comp": A, "y_cc": y_cf, "Cc": Cc, "bars": bars,
            "F_steel": F_sum, "Tp": Tp, "fps": fps, "net": F_sum + Tp - Cc, "Mn": M}


def _solve_c(I, rows, dp_cf, with_pt):
    lo, hi = 1e-6 * I["D"], 10.0 * I["D"]
    if _flex_state(I, rows, lo, dp_cf, with_pt)["net"] <= 0:
        return lo
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _flex_state(I, rows, mid, dp_cf, with_pt)["net"] > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-10 * I["D"]:
            break
    return 0.5 * (lo + hi)


def cracked_section_circ(I, rows, dp_cf):
    """Elastic cracked transformed section: concrete segment in compression, all bars
    transformed (n·As below NA, (n−1)·As above NA), bonded PT as n_pt·Aps."""
    R = I["D"] / 2.0
    n = I["n_mod"]
    Aps = I["Aps"]
    n_pt = I["Ept"] / I["Ec"] if Aps > 0 and I["Ec"] > 0 else 0.0

    def coef(d, c):
        return (n - 1.0) if d < c else n

    def Q(c):
        A, y_cf, _ = circle_segment(R, c)
        q = A * (c - y_cf)
        q += sum(coef(r["d_cf"], c) * r["As"] * (c - r["d_cf"]) for r in rows)
        if Aps > 0 and dp_cf > 0:
            q += n_pt * Aps * (c - dp_cf)
        return q

    lo, hi = 0.0, I["D"]
    if Q(hi) <= 0:
        c_cr = hi
    else:
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if Q(mid) > 0:
                hi = mid
            else:
                lo = mid
            if hi - lo < 1e-10 * I["D"]:
                break
        c_cr = 0.5 * (lo + hi)
    A, y_cf, I_c = circle_segment(R, c_cr)
    z_na = R - c_cr
    zbar = R - y_cf
    I_seg = I_c - 2.0 * z_na * A * zbar + A * z_na ** 2
    Icr = I_seg + sum(coef(r["d_cf"], c_cr) * r["As"] * (r["d_cf"] - c_cr) ** 2 for r in rows)
    A_tr = A + sum(coef(r["d_cf"], c_cr) * r["As"] for r in rows)
    if Aps > 0 and dp_cf > 0:
        Icr += n_pt * Aps * (dp_cf - c_cr) ** 2
        A_tr += n_pt * Aps
    return {"c_cr": c_cr, "Icr": Icr, "A_tr": A_tr, "A_seg": A, "I_seg": I_seg, "n_pt": n_pt}


def do_flexure_circ(I, Pu, Mu, Ms, Ps, pm=None):
    """Circular flexure: strain-compatibility Mn at Pu = 0, φ, dv/de/bv, Mcr, crack control,
    cracked-section service stress. `pm` = (sag, hog) curves to reuse; built when None."""
    fc, fy, Es, Ept = I["fc"], I["fy_long"], I["Es"], I["Ept"]
    fpu = I["fpu"]
    alpha1, beta1, k_pt = I["alpha1"], I["beta1"], I["k_pt"]
    ecl, etl = I["ecl"], I["etl"]
    D = I["D"]
    R = D / 2.0
    Aps = I["Aps"]
    lam, gamma_e = I["lam"], I["gamma_e"]
    code_edition, section_class = I["codeEdition"], I["sectionClass"]
    rings = I["circ_rings"]

    comp_face = "top" if Mu >= 0 else "bottom"
    rows = _rows_cf(I["circ_bars"], comp_face, D)
    dp = (D - I["dp"]) if (comp_face == "bottom" and I["dp"] > 0) else I["dp"]
    As_total = I["circ_Ast"]

    # ── Neutral axis by strain compatibility (Σ forces = 0) ──
    na_bd = ce.EqBreakdown("Neutral Axis — circular section, strain compatibility (Pu = 0)")
    with_pt = Aps > 0 and dp > 0
    if As_total <= 0 and not with_pt:
        c = 0.01
        st = _flex_state(I, rows, c, dp, False)
        pt_in_compression = False
    else:
        c = _solve_c(I, rows, dp, with_pt)
        pt_in_compression = with_pt and dp <= c
        if pt_in_compression:
            c = _solve_c(I, rows, dp, False)
        st = _flex_state(I, rows, c, dp, with_pt and not pt_in_compression)
    Aps_tens = Aps if (with_pt and not pt_in_compression) else 0.0
    fps_calc = st["fps"] if Aps_tens > 0 else 0.0
    a = st["a"]
    na_bd.add("Each bar group: εs = 0.003·(d − c)/c, fs = min(|εs|·Es, fy)·sign",
              "strain compatibility at every bar depth (no single 'd' for a circle)", 0, "")
    na_bd.add("Compression block: circular segment of depth a = β₁·c, Cc = α₁·f'c·A_seg(a)",
              f"a = {ce.fmt_num(beta1, 3)}·{ce.fmt_num(c, 3)} = {ce.fmt_num(a, 3)} in, "
              f"A_seg = {ce.fmt_num(st['A_comp'], 2)} in²", st["Cc"], "kip")
    if Aps_tens > 0:
        na_bd.add("fps = fpu·(1 − k·c/dp)",
                  f"= {ce.fmt_num(fpu, 0)}·(1 − {ce.fmt_num(k_pt, 3)}·{ce.fmt_num(c, 3)}/{ce.fmt_num(dp, 2)})",
                  fps_calc, "ksi")
    if pt_in_compression:
        na_bd.add(f"dp = {ce.fmt_num(dp, 2)} ≤ c → PT in compression zone, excluded", "", 0, "")
    na_bd.add("Equilibrium: Cc = ΣAs·fs + Aps·fps  (solved for c by bisection)",
              f"Cc = {ce.fmt_num(st['Cc'], 1)}, ΣF_steel = {ce.fmt_num(st['F_steel'], 1)}, "
              f"Tps = {ce.fmt_num(st['Tp'], 1)} kip", c, "in")

    mn_bd = ce.EqBreakdown("Moment Capacity (Mn at Pu = 0) — circular")
    Mn = st["Mn"] if (As_total > 0 or Aps > 0) else 0.0
    mn_bd.add("Mn = Cc·(D/2 − ȳc) + ΣF·(d − D/2) + Tps·(dp − D/2)",
              f"= {ce.fmt_num(st['Cc'], 1)}·({ce.fmt_num(R, 2)} − {ce.fmt_num(st['y_cc'], 3)}) + "
              f"{ce.fmt_num(sum(b['F'] * (b['d_cf'] - R) for b in st['bars']), 1)}"
              + (f" + {ce.fmt_num(st['Tp'], 1)}·({ce.fmt_num(dp, 2)} − {ce.fmt_num(R, 2)})" if Aps_tens > 0 else ""),
              Mn, "kip-in")

    # ── φ ──
    d_ext = max((r["d_cf"] for r in rows), default=R)
    dt = max(d_ext, dp) if Aps_tens > 0 else d_ext
    eps_t = 0.003 * (dt - c) / c if c > 0 else 99
    phi_f = ce.get_phi_flex(code_edition, section_class, eps_t, ecl, etl)
    fo = I.get("factor_overrides", {})
    if "phi_f_f" in fo:
        phi_f = fo["phi_f_f"]
    if abs(eps_t) >= etl:
        sec_status = "TENSION CONTROLLED"
    elif abs(eps_t) <= ecl:
        sec_status = "COMPRESSION CONTROLLED"
    else:
        sec_status = "TRANSITION"
    phi_bd = ce.EqBreakdown("Reduction Factor (φ) Calculation")
    phi_bd.add(f"dt = depth of extreme tension bar{' / tendon' if Aps_tens > 0 else ''}", "", dt, "in")
    phi_bd.add(f"εt = 0.003·(dt − c)/c = 0.003·({ce.fmt_num(dt, 3)} − {ce.fmt_num(c, 3)})/{ce.fmt_num(c, 3)}",
               "", eps_t, "")
    phi_bd.add(f"εcl = {ce.fmt_num(ecl, 4)}, εtl = {ce.fmt_num(etl, 4)} → {sec_status}", "", phi_f, "")
    Mr = phi_f * Mn
    phi_bd.add(f"Mr = φ·Mn = {ce.fmt_num(phi_f, 2)}·{ce.fmt_num(Mn, 1)}", "", Mr, "kip-in")

    # ── Shear depth (dv, de, bv) ──
    As_t = _tension_half_As(rows, R)
    As_c = As_total - As_t
    ring_As = sum(rg["As"] for rg in rings)
    Dr_eff = sum(rg["As"] * rg["Dr"] for rg in rings) / ring_As if ring_As > 0 else 0.0
    de_s = R + Dr_eff / math.pi
    tot_tens = As_t * fy + (Aps_tens * fps_calc if Aps_tens > 0 else 0)
    if Aps_tens > 0 and As_t > 0:
        de = (Aps_tens * fps_calc * dp + As_t * fy * de_s) / tot_tens
    elif Aps_tens > 0:
        de = dp
    else:
        de = de_s
    dv1 = 0.0
    dv2 = 0.72 * D
    dv3 = 0.9 * de
    dv = max(dv2, dv3)
    bv = D

    # ── P-M ──
    if pm is None:
        pm_sag = build_pm_curve_circ(I, "top")
        pm_hog = build_pm_curve_circ(I, "bottom")
        pm_curve = pm_sag if comp_face == "top" else pm_hog
        pm_key_points = compute_pm_key_points_circ(I, pm_curve, comp_face, Pu)
    else:
        pm_sag, pm_hog = pm
        pm_curve = pm_sag if comp_face == "top" else pm_hog
        pm_key_points = []
    Mr_atPu = ce.get_mr_at_pu(pm_curve, Pu)
    pm_eq = ce.get_pm_equilibrium_at_pu(pm_curve, Pu)

    # ── Minimum flexural reinforcement (same γ factors as rect/I) ──
    gamma1 = fo.get("gamma1_f", 1.6)
    gamma2 = fo.get("gamma2_f", 1.1)
    astm_gamma3_map = {"A615_60": 0.67, "A615_75": 0.75, "A615_80": 0.76,
                       "A706_60": 0.75, "A706_80": 0.8, "A1035_100": 0.67,
                       "A615": 0.67, "A706": 0.75}
    gamma3 = fo.get("gamma3_f", 1.0 if Aps_tens > 0 else astm_gamma3_map.get(I.get("astm_spec", "A615_60"), 0.67))
    fr = 0.24 * lam * math.sqrt(fc) if fc > 0 else 0
    Sc = math.pi * D ** 3 / 32.0
    P_eff = Aps * I.get("fpe", 0)
    e_pt = I["dp"] - R
    if P_eff > 0:
        # Tendon below the centre compresses the bottom fibre and decompresses the top
        fcpe = max(P_eff / I["Ag"] + (1 if Mu >= 0 else -1) * P_eff * e_pt * R / I["Ig"], 0)
    else:
        fcpe = 0
    Mcr = gamma3 * (gamma1 * fr + gamma2 * fcpe) * Sc
    Mcond = min(1.33 * abs(Mu), Mcr)
    min_flex_ok = Mr >= Mcond

    # ── Crack control (5.6.7) ──
    outer = rings[0] if rings else {"bar_d": 0, "d_eq": 0, "s_arc": 0, "s_clear": 0, "n": 0, "barN": 0, "bar_a": 0}
    dc = D - d_ext
    beta_s = 1 + dc / (0.7 * (D - dc)) if (D - dc) > 0 else 1
    fss_simp = 0.6 * fy
    s_crack_capped = (700 * gamma_e) / (beta_s * fss_simp) - 2 * dc if beta_s * fss_simp > 0 else 0
    crack_mode = I.get("crack_mode", "capped")

    s_min_ck = max(1.5 * outer["d_eq"], 1.5 * I["ag"], 1.5)
    s_max_ck = min(1.5 * D, 18)

    # ── Cracked section (service; sign from Ms) ──
    s_face = "top" if Ms >= 0 else "bottom"
    s_rows = _rows_cf(I["circ_bars"], s_face, D)
    s_dp = (D - I["dp"]) if (s_face == "bottom" and I["dp"] > 0) else I["dp"]
    cr = cracked_section_circ(I, s_rows, s_dp)
    c_cr, Icr, n_pt = cr["c_cr"], cr["Icr"], cr["n_pt"]
    n_mod = I["n_mod"]
    s_ds = max((r["d_cf"] for r in s_rows), default=R)
    s_As = _tension_half_As(s_rows, R)
    s_d_comp = min((r["d_cf"] for r in s_rows), default=R)
    nAs = s_As * n_mod
    nAps = Aps * n_pt
    M_serv = abs(Ms)
    addlBM = Ps * (R - c_cr)
    M_total_serv = M_serv + addlBM
    fss = (M_total_serv * (s_ds - c_cr) / Icr * n_mod + Ps / cr["A_tr"] * n_mod) if Icr > 0 and cr["A_tr"] > 0 else 0
    fps_serv = M_total_serv * (s_dp - c_cr) / Icr * n_pt if Aps > 0 and Icr > 0 else 0
    eps_rb = fss / Es if Es > 0 else 0
    curv = abs(eps_rb / (s_ds - c_cr)) if (s_ds - c_cr) != 0 else 0
    serv_bd = ce.EqBreakdown("Service Flexure Stress (Cracked Circular Section)")
    serv_bd.add("Ms (service moment demand)", "", M_serv, "kip-in")
    serv_bd.add("c_cr: Σ first moments of transformed section about NA = 0 (segment + n·As / (n−1)·As)",
                "solved numerically", c_cr, "in")
    serv_bd.add("Icr = I_segment,NA + Σ n_i·As·(d − c_cr)²", "", Icr, "in⁴")
    if Ps != 0:
        serv_bd.add(f"Additional BM = Ps·(D/2 − c_cr) = {ce.fmt_num(Ps, 1)}·({ce.fmt_num(R, 2)} − {ce.fmt_num(c_cr, 2)})",
                    "secondary moment from axial offset", addlBM, "kip-in")
    serv_bd.add("fss = M·(d_ext − c_cr)/Icr·n + Ps·n/A_tr",
                f"= {ce.fmt_num(M_total_serv, 1)}·{ce.fmt_num(s_ds - c_cr, 2)}/{ce.fmt_num(Icr, 1)}·{ce.fmt_num(n_mod, 2)}"
                + (f" + {ce.fmt_num(Ps, 1)}·{ce.fmt_num(n_mod, 2)}/{ce.fmt_num(cr['A_tr'], 1)}" if Ps != 0 else ""),
                fss, "ksi")

    fss_actual = max(fss, 0.0)
    s_crack_actual = (700 * gamma_e) / (beta_s * fss_actual) - 2 * dc if fss_actual * beta_s > 0 else 0
    if crack_mode == "actual":
        fss_used, s_crack = fss_actual, s_crack_actual
    else:
        fss_used, s_crack = fss_simp, s_crack_capped
    s_bar = outer["s_arc"]
    crack_spacing_ok = s_bar <= s_crack if (s_crack > 0 and outer["n"] > 1) else s_crack > 0
    bd_crack = ce.EqBreakdown("Crack Control per AASHTO 5.6.7 (circular)")
    bd_crack.add(f"dc = D − d_ext = {ce.fmt_num(D, 2)} − {ce.fmt_num(d_ext, 3)}",
                 "extreme tension fibre to centre of closest bar", dc, "in")
    bd_crack.add(f"βs = 1 + dc/(0.7·(D − dc)) = 1 + {ce.fmt_num(dc, 2)}/(0.7·({ce.fmt_num(D, 2)} − {ce.fmt_num(dc, 2)}))",
                 "crack distribution factor (Eq. 5.6.7-2)", beta_s, "")
    bd_crack.add(f"fss,capped = 0.6·fy = 0.6·{ce.fmt_num(fy, 1)}", "simplified rebar stress shortcut", fss_simp, "ksi")
    bd_crack.add("fss,actual (cracked circular section)", "", fss_actual, "ksi")
    if fss_simp * beta_s > 0:
        bd_crack.add(f"s_capped = 700·γe/(βs·fss,capped) − 2·dc = 700·{ce.fmt_num(gamma_e, 2)}/({ce.fmt_num(beta_s, 3)}·{ce.fmt_num(fss_simp, 1)}) − 2·{ce.fmt_num(dc, 2)}",
                     "max bar spacing using capped fss (Eq. 5.6.7-1)", s_crack_capped, "in")
    if fss_actual * beta_s > 0:
        bd_crack.add(f"s_actual = 700·γe/(βs·fss,actual) − 2·dc = 700·{ce.fmt_num(gamma_e, 2)}/({ce.fmt_num(beta_s, 3)}·{ce.fmt_num(fss_actual, 2)}) − 2·{ce.fmt_num(dc, 2)}",
                     "max bar spacing using actual fss (Eq. 5.6.7-1)", s_crack_actual, "in")
    bd_crack.add(f"crack_mode = '{crack_mode}'", f"governing s_crack = {ce.fmt_num(s_crack, 2)} in", s_crack, "in")
    bd_crack.add(f"s (outer ring, centre-to-centre arc) = π·Dr/n = π·{ce.fmt_num(outer.get('Dr', 0), 2)}/{outer['n']}",
                 f"information: s {'≤' if crack_spacing_ok else '>'} s_crack", s_bar, "in")

    # ── Gross / effective inertia ──
    Ig = I["Ig"]
    Mcr_serv = fr * Ig / R if R > 0 else 0
    Ma = abs(M_total_serv) if abs(M_total_serv) > 0 else 1e-10
    ratio = min(Mcr_serv / Ma, 1.0)
    Ieff = min(ratio ** 3 * Ig + (1 - ratio ** 3) * Icr, Ig)

    if code_edition == "CA":
        phi_cc = 0.75
        phi_tc, phi_k = {"PP": (1.0, 0.25), "CIP_PT": (0.95, 0.20)}.get(section_class, (0.9, 0.15))
    else:
        phi_cc = 0.75
        phi_tc, phi_k = (1.0, 0.25) if section_class in ("PP", "CIP_PT") else (0.9, 0.15)

    # ── Spiral / transverse detailing ──
    trans = circ_transverse_summary(I)

    eps_comp = fs_comp = 0.0
    if st["bars"]:
        shallow = min(st["bars"], key=lambda b: b["d_cf"])
        eps_comp, fs_comp = shallow["es"], shallow["fs"]

    circ = {
        "D": D, "R": R, "Ag": I["Ag"], "Ig": Ig, "Ast": As_total,
        "rings": rings, "bars": I["circ_bars"], "Dr_eff": Dr_eff, "de_s": de_s,
        "flex_bars": st["bars"], "A_comp": st["A_comp"], "y_cc": st["y_cc"], "Cc": st["Cc"],
        "F_steel": st["F_steel"], "Tps": st["Tp"],
        "As_tens_half": As_t, "As_comp_half": As_c,
        "d_ext": d_ext, "s_bar": s_bar, "s_clear": outer["s_clear"],
        "crack_spacing_ok": crack_spacing_ok,
        "rho_g": As_total / I["Ag"] if I["Ag"] > 0 else 0,
        "cracked": {"A_seg": cr["A_seg"], "I_seg": cr["I_seg"], "A_tr": cr["A_tr"], "rows": s_rows},
        "trans": trans, "tors": I["circ_tors"],
        "pn_factor": SPIRAL_PN_FACTOR if I["circ_confined"] else TIE_PN_FACTOR,
        "unverified": CIRC_UNVERIFIED,
    }

    return {
        "c": c, "a": a, "beta1": beta1, "alpha1": alpha1, "dt": dt, "eps_t": eps_t,
        "sec_status": sec_status, "phi_f": phi_f, "fps_calc": fps_calc,
        "Mn": Mn, "Mr": Mr, "Mr_atPu": Mr_atPu,
        "breakdown_na": na_bd.to_dict(), "breakdown_mn": mn_bd.to_dict(),
        "breakdown_phi": phi_bd.to_dict(), "breakdown_serv": serv_bd.to_dict(),
        "dv": dv, "dv1": dv1, "dv2": dv2, "dv3": dv3, "de": de,
        "bv": bv, "tot_tens": tot_tens,
        "c_ds_ratio": c / dt if dt > 0 else 0,
        "c_ds_limit": 0.003 / (0.003 + ecl) if ecl > 0 else 1.0,
        "c_ds_ok": True, "use_strain_compat": True,
        "comp_steel_yields": False, "c_trial": c, "d_s_comp": min((r["d_cf"] for r in rows), default=R),
        "eps_comp": eps_comp, "fs_comp": fs_comp,
        "ecl": ecl, "etl": etl,
        "comp_face": comp_face, "ds": d_ext, "dp_cf": dp, "As": As_t, "As_comp": As_c,
        "As_top": I["As_top"], "As_bot": I["As_bot"], "d_top": I["d_top"], "d_bot": I["d_bot"],
        "nBars_tens": outer["n"], "nBars_comp": outer["n"],
        "barN_tens": outer["barN"], "barN_comp": outer["barN"],
        "bar_d_tens": outer["bar_d"], "bar_d_comp": outer["bar_d"], "hf": D,
        "pm_data": pm_curve, "pm_curve": pm_curve, "pm_eq": pm_eq,
        "pm_curve_sag": pm_sag, "pm_curve_hog": pm_hog,
        "pm_key_points": pm_key_points,
        "gamma1": gamma1, "gamma2": gamma2, "gamma3": gamma3, "fcpe": fcpe,
        "fr": fr, "Sc": Sc, "Mcr": Mcr, "Mcond": Mcond, "min_flex_ok": min_flex_ok,
        "dc": dc, "beta_s": beta_s, "fss_simp": fss_simp, "s_crack": s_crack,
        "crack_mode": crack_mode, "fss_used": fss_used,
        "s_crack_capped": s_crack_capped, "s_crack_actual": s_crack_actual,
        "breakdown_crack": bd_crack.to_dict(),
        "s_min_ck": s_min_ck, "s_max_ck": s_max_ck,
        "n_mod": n_mod, "nAs": nAs, "n_pt": n_pt, "nAps": nAps,
        "c_cr": c_cr, "Icr": Icr,
        "M_serv": M_serv, "addlBM": addlBM, "fss": fss, "fps_serv": fps_serv,
        "eps_rb": eps_rb, "curv": curv, "Ieff": Ieff, "Ig": Ig,
        "serv_comp_face": s_face, "serv_ds": s_ds,
        "serv_d_s_comp": s_d_comp, "serv_As_comp": I["circ_Ast"] - s_As,
        "serv_dp": s_dp, "serv_As": s_As,
        "phi_cc": phi_cc, "phi_tc": phi_tc, "phi_k": phi_k,
        "Aps": Aps, "Aps_tens": Aps_tens, "pt_in_compression": pt_in_compression,
        "circ": circ,
    }


def circ_transverse_summary(I):
    """Hoop / spiral data, ρs check (Eq. 5.6.4.6-1) and compression-member detailing checks."""
    D, cover = I["D"], I["cover"]
    ttype = I["circ_trans_type"]
    s = I["s_shear"]
    A_sp = I["shBar_a"] if I["Av"] > 0 else 0.0
    d_sp = I["circ_trans_d"]
    out = {
        "type": ttype, "barN": int(I["shN"]) if I["Av"] > 0 else 0, "A_bar": A_sp, "d_bar": d_sp,
        "s": s, "tie_legs": I["circ_tie_legs"], "A_tie": I["circ_tie_a"], "Av": I["Av"],
        "Dh": I["circ_tors"]["Dh"], "closure": I["circ_hoop_closure"], "confined": I["circ_confined"],
    }
    if I["circ_confined"] and A_sp > 0 and s > 0:
        Dc = D - 2.0 * cover
        Ac = math.pi * Dc ** 2 / 4.0
        rho_s = 4.0 * A_sp / (Dc * s) if Dc > 0 else 0.0
        # §5.6.4.6: fyh ≤ 75.0 ksi (≤ 100 ksi only for Art. 5.4.3.3 elements — not modelled)
        fyh = min(I["fy_trans"], 75.0)
        rho_min = 0.45 * (I["Ag"] / Ac - 1.0) * I["fc"] / fyh if (Ac > 0 and fyh > 0) else 0.0
        out.update({"Dc": Dc, "Ac": Ac, "rho_s": rho_s, "rho_s_min": rho_min, "fyh": fyh,
                    "rho_s_ok": rho_s >= rho_min, "clear_pitch": s - d_sp})
    out["detailing"] = _circ_detailing(I, s, d_sp)
    return out


def _circ_detailing(I, s, d_sp):
    """Compression-member detailing (information): §5.6.4.2, 5.10.3.1.5, 5.10.4.2–5.10.4.4."""
    rings = I["circ_rings"]
    ag, D = I["ag"], I["D"]
    chk = []

    def add(item, value, limit, ok, ref):
        chk.append({"item": item, "value": value, "limit": limit, "ok": bool(ok), "ref": ref})

    if rings:
        add("Longitudinal bars in outer ring", f"{rings[0]['n']}", "≥ 6", rings[0]["n"] >= 6, "5.6.4.2")
        smallest = min(rg["barN"] for rg in rings)
        add("Smallest longitudinal bar", f"#{smallest}", "≥ #5", smallest >= 5, "5.6.4.2")
        for rg in rings:
            if rg["bundle"] > 1:
                ok = not (rg["barN"] > 11 and rg["bundle"] > 2)
                add(f"Ring {rg['ring']} bundle", f"{rg['bundle']} × #{rg['barN']}",
                    "≤ 4 bars; ≤ 2 if larger than #11 (flexural members)", ok, "5.10.3.1.5")
    if s <= 0 or d_sp <= 0:
        return chk
    db_long = min((rg["bar_d"] for rg in rings), default=0.0)
    clear_min = max(1.0, 1.33 * ag)
    add("Clear spacing of transverse bars", f"{s - d_sp:.2f} in", f"≥ {clear_min:.2f} in",
        s - d_sp >= clear_min - 1e-9, "5.10.4.2 / 5.10.4.3 / 5.10.4.4")
    if I["circ_confined"]:
        ref = "5.10.4.2" if I["circ_spiral"] else "5.10.4.4"
        s_max = min(6.0 * db_long, 6.0)
        add("Centre-to-centre pitch / spacing", f"{s:.2f} in", f"≤ min(6·db, 6.0) = {s_max:.2f} in",
            s <= s_max + 1e-9, ref)
        if I["circ_spiral"]:
            add("Spiral bar diameter", f"{d_sp:.3f} in", "≥ 0.375 in", d_sp >= 0.375 - 1e-9, "5.10.4.2")
    else:
        big = any(rg["barN"] >= 11 for rg in rings)
        bundled = any(rg["bundle"] > 1 for rg in rings)
        need = 4 if (big or bundled) else 3
        add("Tie bar size", f"#{int(I['shN'])}", f"≥ #{need}", int(I["shN"]) >= need, "5.10.4.3")
        if any(rg["bundle"] > 1 and rg["barN"] > 10 for rg in rings):
            s_max, lim = min(D / 2.0, 6.0), "min(D/2, 6.0)"
        else:
            s_max, lim = min(D, 12.0), "min(D, 12.0)"
        add("Tie spacing", f"{s:.2f} in", f"≤ {lim} = {s_max:.2f} in", s <= s_max + 1e-9, "5.10.4.3")
    return chk


# ─── Per-row capacities ─────────────────────────────────────────────

def compute_row_capacities_circ(I, pm_sag, pm_hog, Pu, Mu, Vu, Tu, Vp, Ms, Ps, dr_row=None):
    """Same output keys as calc_engine.compute_row_capacities. Uses the active-row
    circular flexure + shared do_shear/do_torsion so row and active results agree."""
    fy, phi_v, fc = I["fy_long"], I["phi_v"], I["fc"]
    Aps = I["Aps"]
    pm_curve = pm_sag if Mu >= 0 else pm_hog
    Mr = ce.get_mr_at_pu(pm_curve, Pu)

    fl = do_flexure_circ(I, Pu, Mu, Ms, Ps, pm=(pm_sag, pm_hog))
    tors = ce.compute_torsion_threshold(I, Tu)
    sh = ce.do_shear(I, fl, Pu, Mu, Vu, Tu, Vp, tors)
    tor = ce.do_torsion(I, fl, sh, Pu, Mu, Vu, Tu, Vp)

    # Crack status mirrors rect/I rows: service stress vs 0.6·fy and positive s_crack
    crack_status = "OK"
    if fl["serv_As"] > 0:
        if fl["fss"] > 0.6 * fy or fl["s_crack_capped"] <= 0:
            crack_status = "NG"

    pt_stress_status, pt_stress_result, ftop, fbot = "NA", None, 0.0, 0.0
    if Aps > 0 and I.get("hasPT"):
        lc = (dr_row or {}).get("load_case", "service_I_full") or "service_I_full"
        fpi = float((I.get("pt_loss_summary") or {}).get("fpi", 0.0))
        fpe = I.get("fpe", 0) or 0
        pt_stress_result = ce._pt_row_service_check(
            I, lc, P_xfr_kip=fpi * Aps, P_serv_kip=fpe * Aps, M_kipin=Ms,
            dp_row=I.get("dp", 0) or 0, Ps_kip=Ps, fpi_used=fpi, fpe_used=fpe, Aps_used=Aps)
        pt_stress_status = pt_stress_result["status"]
        ftop, fbot = pt_stress_result["f_top"], pt_stress_result["f_bot"]

    flex_cap_ok = Mr >= abs(Mu)
    pu_in_range = (Pu >= pm_curve[0]["Pr"] and Pu <= pm_curve[-1]["Pr"]) if pm_curve else True
    min_ok = Mr >= min(1.33 * abs(Mu), fl["Mcr"])
    flex_status = "NG" if (not pu_in_range or not flex_cap_ok) else ("MIN" if not min_ok else "OK")

    sh_reqd = sh["sh_reqd"]
    if sh["Vr2"] < abs(Vu):
        shear_status = "NG"
    elif sh_reqd and not sh["has_min_av"]:
        shear_status = "NG"
    elif sh_reqd and I["s_shear"] > sh["s_max_sh"]:
        shear_status = "NG"
    elif not sh_reqd:
        shear_status = "NR"
    else:
        shear_status = "OK"

    cap = sh["long_cap"]
    long_ok_3 = sh["long_ok_3"]
    return {
        "Mr": -Mr if Mu < 0 else Mr, "Vr1": sh["Vr1"], "Vr2": sh["Vr2"], "Vr3": sh["Vr3"], "Tr": tor["Tr"],
        "Vnmax": sh["Vnmax"],
        "Vn1_uncapped": sh["Vn1_uncapped"], "Vn1_capped": sh["Vn1_capped"],
        "Vn2_uncapped": sh["Vn2_uncapped"], "Vn2_capped": sh["Vn2_capped"],
        "Vn3_uncapped": sh["Vn3_uncapped"], "Vn3_capped": sh["Vn3_capped"],
        "crackStatus": crack_status, "flexStatus": flex_status, "shearStatus": shear_status,
        "ptStressStatus": pt_stress_status, "ptStressFtop": ftop, "ptStressFbot": fbot,
        "pt_stress": pt_stress_result,
        "torsionConsider": tors["consider"],
        "shReqd": sh_reqd, "hasMinAv": sh["has_min_av"],
        "epsS": sh["eps_s"], "dblEps": sh["dbl_eps"],
        "long_ok_1": sh["long_ok_1"], "long_ok_2": sh["long_ok"], "long_ok_3": long_ok_3,
        "long_dc_1": sh["long_dem_1"] / cap if cap > 0 else None,
        "long_dc_2": sh["long_dem"] / cap if cap > 0 else None,
        "long_dc_3": (sh["long_dem_3"] / cap if cap > 0 else None) if long_ok_3 is not None else None,
    }


# ─── Entry point ────────────────────────────────────────────────────

def calculate_all_circ(raw_inputs, demand_rows, active_row_idx):
    """Circular counterpart of calc_engine.calculate_all (same return structure)."""
    I = dict(raw_inputs)
    derive_circular(I)

    dr = demand_rows[active_row_idx] if active_row_idx < len(demand_rows) else demand_rows[0]
    Pu, Mu, Vu = dr.get("Pu", 0), dr.get("Mu", 0), dr.get("Vu", 0)
    Tu, Vp, Ms, Ps = dr.get("Tu", 0), dr.get("Vp", 0), dr.get("Ms", 0), dr.get("Ps", 0)

    dp_global, fpe_global = I["dp"], I.get("fpe", 0)
    if dr.get("dp") is not None:
        I["dp"] = dr["dp"]
    if dr.get("fpe") is not None:
        I["fpe"] = dr["fpe"]

    flex = do_flexure_circ(I, Pu, Mu, Ms, Ps)
    tors_thresh = ce.compute_torsion_threshold(I, Tu)
    shear = ce.do_shear(I, flex, Pu, Mu, Vu, Tu, Vp, tors_thresh)
    torsion = ce.do_torsion(I, flex, shear, Pu, Mu, Vu, Tu, Vp)
    torsion["circ_spiral_excluded"] = bool(I["circ_spiral"])
    torsion["circ_Dh"] = I["circ_tors"]["Dh"]
    pm_sag, pm_hog = flex["pm_curve_sag"], flex["pm_curve_hog"]
    pm_dp, pm_fpe = I["dp"], I.get("fpe", 0)

    row_results = []
    for dr_row in demand_rows:
        I["dp"] = dr_row["dp"] if dr_row.get("dp") is not None else dp_global
        I["fpe"] = dr_row["fpe"] if dr_row.get("fpe") is not None else fpe_global
        if I["dp"] != pm_dp or I.get("fpe", 0) != pm_fpe:
            r_sag, r_hog = build_pm_curve_circ(I, "top"), build_pm_curve_circ(I, "bottom")
        else:
            r_sag, r_hog = pm_sag, pm_hog
        row_results.append(compute_row_capacities_circ(
            I, r_sag, r_hog,
            dr_row.get("Pu", 0), dr_row.get("Mu", 0), dr_row.get("Vu", 0),
            dr_row.get("Tu", 0), dr_row.get("Vp", 0), dr_row.get("Ms", 0), dr_row.get("Ps", 0),
            dr_row=dr_row))
    I["dp"], I["fpe"] = dp_global, fpe_global

    return {
        "inputs": {
            "Ec": I["Ec"], "Es": I["Es"], "fpy": I["fpy"],
            "wc": I.get("wc", 0.145), "K1": I.get("K1", 1.0),
            "h": I["h"], "b": I["b"], "cover": I["cover"], "dp": I["dp"],
            "hf_top": 0, "hf_bot": 0,
            "As_top": I["As_top"], "As_bot": I["As_bot"],
            "d_top": I["d_top"], "d_bot": I["d_bot"],
            "bar_d_top": I["bar_d_top"], "bar_d_bot": I["bar_d_bot"],
            "Aps": I["Aps"], "isRect": False, "bw": I["bw"], "hasPT": I["hasPT"],
            "ecl": I["ecl"], "etl": I["etl"], "alpha1": I["alpha1"], "beta1": I["beta1"],
            "kc": I["alpha1"], "phi_v": I["phi_v"], "gamma_e": I["gamma_e"], "lam": I["lam"],
            "Ag": I["Ag"], "Ig": I["Ig"], "yb_centroid": I["yb_centroid"],
            "isCirc": True, "D": I["D"], "secType": "CIRCULAR",
            "circ_trans_type": I["circ_trans_type"], "circ_spiral": I["circ_spiral"],
            "circ_hoop_closure": I["circ_hoop_closure"], "circ_confined": I["circ_confined"],
            "Av": I["Av"], "circ_Ast": I["circ_Ast"],
        },
        "demands": {"Pu": Pu, "Mu": Mu, "Vu": Vu, "Tu": Tu, "Vp": Vp, "Ms": Ms, "Ps": Ps},
        "flexure": flex,
        "shear": shear,
        "torsion": torsion,
        "row_results": row_results,
    }
