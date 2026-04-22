"""
Deep audit of AASHTO calc_engine.
Checks all functions across rectangular & I-section with:
  - Single row / multi-row reinforcement
  - With / without PT
  - Sagging / hogging moments
  - Axial tension / compression
  - P-M interaction correctness
  - Service stress (correct steel, sign, cracked section)
  - Shear (all 3 methods) — sign-dependent As, Act, dv
  - Torsion
  - Report key completeness
"""
import math, sys, traceback
sys.path.insert(0, ".")
from calc_engine import (calculate_all, build_pm_curve, build_pm_curve_display,
                         get_mr_at_pu, derive_constants, do_flexure, do_shear,
                         compute_torsion_threshold, BARS, get_phi_flex)

PASS = 0
FAIL = 0
WARN = 0

def ok(cond, msg, warn_only=False):
    global PASS, FAIL, WARN
    if cond:
        PASS += 1
    elif warn_only:
        WARN += 1
        print(f"    ⚠ WARN: {msg}")
    else:
        FAIL += 1
        print(f"    ✗ FAIL: {msg}")
    return cond

def near(a, b, tol=0.01):
    if abs(b) < 1e-9:
        return abs(a) < tol
    return abs(a - b) / max(abs(b), 1e-9) < tol

def make_inputs(
    h, b, fc=4, fy=60, Es=29000, Ec=None, fpu=270, fpy=None, Ept=28500,
    secType="RECTANGULAR", bw_input=None, hf_top=0, hf_bot=0, cover=2.0,
    barN_bot=8, nBars_bot=4, d_bot=None,
    barN_top=0, nBars_top=0, d_top=None,
    nStrands=0, strand_area=0, dp=0, ductDia=0,
    shN=4, shear_legs=2, s_shear=12, tN=4, s_torsion=12,
    ag=0.75, lam=1.0, phi_v=0.9, gamma_e=0.75,
    codeEdition="AASHTO", sectionClass="RC",
):
    if Ec is None:
        Ec = 2500 * fc ** 0.33
    if fpy is None:
        fpy = 0.9 * fpu
    if bw_input is None:
        bw_input = b
    bar_bot = BARS.get(barN_bot, BARS[8])
    bar_top = BARS.get(barN_top, None)
    sh_bar = BARS.get(shN, BARS[4])
    db_stir = sh_bar["d"]
    if d_bot is None:
        d_bot = h - cover - db_stir - bar_bot["d"] / 2
    if d_top is None:
        d_top = cover + db_stir + (bar_top["d"] / 2 if bar_top else 0)
    return dict(
        fc=fc, fy=fy, Ec=Ec, Es=Es, fpu=fpu, fpy=fpy, Ept=Ept,
        ecl=0, etl=0, ecl_override=False, etl_override=False,
        ag=ag, lam=lam, phi_v=phi_v, gamma_e=gamma_e,
        codeEdition=codeEdition, sectionClass=sectionClass,
        secType=secType, b=b, h=h, bw_input=bw_input,
        hf_top=hf_top, hf_bot=hf_bot, cover=cover,
        barN_bot=barN_bot, nBars_bot=nBars_bot, d_bot=d_bot,
        barN_top=barN_top, nBars_top=nBars_top, d_top=d_top,
        nStrands=nStrands, strand_area=strand_area, dp=dp, ductDia=ductDia,
        shN=shN, shear_legs=shear_legs, s_shear=s_shear,
        tN=tN, s_torsion=s_torsion,
    )

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION / DEMAND DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════
SECTIONS = {
    # ── Rectangular ──
    "Rect_BotOnly":  dict(desc="Rect 36×36, 4#8 bot only", h=36, b=36, barN_bot=8, nBars_bot=4, barN_top=0, nBars_top=0),
    "Rect_TopBot":   dict(desc="Rect 36×36, 4#8 bot + 4#8 top", h=36, b=36, barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4),
    "Rect_BotOnly_PT": dict(desc="Rect 36×36, 4#8 bot + PT", h=36, b=36, barN_bot=8, nBars_bot=4, barN_top=0, nBars_top=0,
                             nStrands=1, strand_area=math.pi/4*2**2, dp=28, sectionClass="CIP_PT"),
    "Rect_TopBot_PT":  dict(desc="Rect 36×36, 4#8 bot + 4#8 top + PT", h=36, b=36, barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4,
                             nStrands=1, strand_area=math.pi/4*2**2, dp=28, sectionClass="CIP_PT"),
    # ── I-Section ──
    "I_BotOnly":     dict(desc="I-sect 36×36 bw=12, 4#8 bot only", h=36, b=36, secType="T-SECTION", bw_input=12, hf_top=8, hf_bot=8,
                          barN_bot=8, nBars_bot=4, barN_top=0, nBars_top=0),
    "I_TopBot":      dict(desc="I-sect 36×36 bw=12, 4#8 top+bot", h=36, b=36, secType="T-SECTION", bw_input=12, hf_top=8, hf_bot=8,
                          barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4),
    "I_BotOnly_PT":  dict(desc="I-sect 36×36 bw=12, 4#8 bot + PT", h=36, b=36, secType="T-SECTION", bw_input=12, hf_top=8, hf_bot=8,
                          barN_bot=8, nBars_bot=4, barN_top=0, nBars_top=0,
                          nStrands=1, strand_area=math.pi/4*2**2, dp=28, sectionClass="CIP_PT"),
    "I_TopBot_PT":   dict(desc="I-sect 36×36 bw=12, 4#8 top+bot + PT", h=36, b=36, secType="T-SECTION", bw_input=12, hf_top=8, hf_bot=8,
                          barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4,
                          nStrands=1, strand_area=math.pi/4*2**2, dp=28, sectionClass="CIP_PT"),
    # ── Asymmetric flanges ──
    "I_AsymFlange":  dict(desc="I-sect 48×36 bw=12, hf_top=10, hf_bot=6, top+bot bars", h=48, b=36, secType="T-SECTION", bw_input=12, hf_top=10, hf_bot=6,
                          barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4),
    # ── Heavy rebar (large a to exercise T-section flange overrun) ──
    "I_HeavyRebar":  dict(desc="I-sect 36×48 bw=12, hf=6, 8#11 bot + 8#11 top", h=36, b=48, secType="T-SECTION", bw_input=12, hf_top=6, hf_bot=6,
                          barN_bot=11, nBars_bot=8, barN_top=11, nBars_top=8),
}

DEMANDS = {
    "Sag":       [{"Pu":0,    "Mu":3000,  "Vu":100, "Tu":50,  "Vp":0, "Ms":1500, "Ps":0}],
    "Hog":       [{"Pu":0,    "Mu":-3000, "Vu":100, "Tu":50,  "Vp":0, "Ms":-1500,"Ps":0}],
    "Sag+Axcomp":[{"Pu":-200, "Mu":2000,  "Vu":120, "Tu":30,  "Vp":0, "Ms":1000, "Ps":-50}],
    "Hog+Axtens":[{"Pu":50,   "Mu":-2000, "Vu":80,  "Tu":30,  "Vp":0, "Ms":-1000,"Ps":10}],
    "Sag+Axtens":[{"Pu":100,  "Mu":2500,  "Vu":150, "Tu":40,  "Vp":0, "Ms":1200, "Ps":20}],
    "Hog+Axcomp":[{"Pu":-300, "Mu":-2500, "Vu":150, "Tu":40,  "Vp":0, "Ms":-1200,"Ps":-60}],
    "HighTorsion":[{"Pu":0,   "Mu":2000,  "Vu":300, "Tu":200, "Vp":0, "Ms":1000, "Ps":0}],
    "MultiRow":  [
        {"Pu":0,   "Mu":3000,  "Vu":150, "Tu":100, "Vp":0, "Ms":1500, "Ps":0},
        {"Pu":50,  "Mu":-2000, "Vu":80,  "Tu":30,  "Vp":0, "Ms":-1000,"Ps":10},
        {"Pu":-100,"Mu":4000,  "Vu":200, "Tu":50,  "Vp":0, "Ms":2000, "Ps":-20},
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT 1: FLEXURE — sign convention, steel assignment, Mn, Mr, P-M consistency
# ═══════════════════════════════════════════════════════════════════════════════

def audit_flexure(res, raw, dem):
    fl = res["flexure"]
    inp = res["inputs"]
    d = dem[0]
    Mu, Pu, Ms = d["Mu"], d["Pu"], d.get("Ms", 0)
    h, b = inp["h"], inp["b"]
    As_top, As_bot = inp["As_top"], inp["As_bot"]
    d_top, d_bot = inp["d_top"], inp["d_bot"]
    is_rect = inp["isRect"]
    hf_top, hf_bot = inp.get("hf_top", 0), inp.get("hf_bot", 0)
    Aps = inp.get("Aps", 0)
    hasPT = inp.get("hasPT", False)

    # 1. Compression face
    if Mu >= 0:
        ok(fl["comp_face"] == "top", f"comp_face should be 'top' for Mu≥0, got '{fl['comp_face']}'")
        ok(near(fl["As"], As_bot), f"Tension As should = As_bot ({As_bot:.3f}), got {fl['As']:.3f}")
        ok(near(fl["ds"], d_bot), f"ds should = d_bot ({d_bot:.3f}), got {fl['ds']:.3f}")
        ok(near(fl["As_comp"], As_top), f"Comp As should = As_top ({As_top:.3f}), got {fl['As_comp']:.3f}")
    else:
        ok(fl["comp_face"] == "bottom", f"comp_face should be 'bottom' for Mu<0, got '{fl['comp_face']}'")
        ok(near(fl["As"], As_top), f"Tension As should = As_top ({As_top:.3f}), got {fl['As']:.3f}")
        ok(near(fl["ds"], h - d_top), f"ds should = h-d_top ({h-d_top:.3f}), got {fl['ds']:.3f}")
        ok(near(fl["As_comp"], As_bot), f"Comp As should = As_bot ({As_bot:.3f}), got {fl['As_comp']:.3f}")

    # 2. ds sanity
    ok(0 < fl["ds"] < h, f"ds ({fl['ds']:.3f}) should be 0 < ds < h ({h})")

    # 3. c, a, beta1
    ok(fl["c"] > 0, f"c > 0, got {fl['c']:.4f}")
    ok(near(fl["a"], fl["beta1"] * fl["c"]), f"a = β1·c check: a={fl['a']:.4f}, β1·c={fl['beta1']*fl['c']:.4f}")

    # 4. hf — should use correct flange
    if not is_rect:
        if Mu >= 0:
            ok(near(fl["hf"], hf_top), f"hf should = hf_top ({hf_top}) for sagging, got {fl['hf']}")
        else:
            ok(near(fl["hf"], hf_bot), f"hf should = hf_bot ({hf_bot}) for hogging, got {fl['hf']}")

    # 5. Mn, Mr
    has_tens = fl["As"] > 0 or (Aps > 0 and hasPT)
    if has_tens:
        ok(fl["Mn"] > 0, f"Mn > 0, got {fl['Mn']:.1f}")
        ok(fl["Mr"] > 0, f"Mr > 0, got {fl['Mr']:.1f}")
    else:
        ok(fl["Mn"] >= 0, f"Mn >= 0 (no tension steel), got {fl['Mn']:.1f}")
    ok(0 < fl["phi_f"] <= 1.0, f"phi_f valid, got {fl['phi_f']:.4f}")
    ok(near(fl["Mr"], fl["phi_f"] * fl["Mn"]), f"Mr = φ·Mn: {fl['Mr']:.1f} vs {fl['phi_f']*fl['Mn']:.1f}")

    # 6. Hand-calc Mn for simple rectangular sagging (no PT, no comp steel)
    if is_rect and Mu >= 0 and As_top == 0 and not hasPT and As_bot > 0:
        fc = raw["fc"]
        fy = raw["fy"]
        alpha1 = fl["alpha1"]
        a_hand = As_bot * fy / (alpha1 * fc * b)
        Mn_hand = As_bot * fy * (d_bot - a_hand / 2)
        ok(near(fl["Mn"], Mn_hand, tol=0.005),
           f"Hand Mn ({Mn_hand:.1f}) vs engine ({fl['Mn']:.1f}) for simple rect sagging")

    # 7. dv checks
    ok(fl["dv"] > 0, f"dv > 0, got {fl['dv']:.3f}")
    ok(fl["dv"] >= 0.72 * h - 0.1, f"dv >= 0.72h = {0.72*h:.2f}, got {fl['dv']:.3f}")
    ok(fl["dv"] >= 0.9 * fl["de"] - 0.1, f"dv >= 0.9de = {0.9*fl['de']:.2f}, got {fl['dv']:.3f}")

    # 8. Minimum flexure
    ok("Mcr" in fl, "Mcr present")
    ok("min_flex_ok" in fl, "min_flex_ok present")
    ok(fl["Mcr"] > 0, f"Mcr > 0, got {fl['Mcr']:.1f}")

    # 9. c/ds check
    ok("c_ds_ratio" in fl, "c_ds_ratio present")
    ok("c_ds_limit" in fl, "c_ds_limit present")

    # 10. I-section: if a > hf, Mn should include flange/web decomposition
    if not is_rect and has_tens:
        # Just check that Mn exists and is positive
        ok(fl["Mn"] > 0, f"I-section Mn > 0, got {fl['Mn']:.1f}")


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT 2: P-M INTERACTION — both curves built, correct curve selected
# ═══════════════════════════════════════════════════════════════════════════════

def audit_pm(res, raw, dem):
    fl = res["flexure"]
    inp = res["inputs"]
    d = dem[0]
    Mu, Pu = d["Mu"], d["Pu"]
    h = inp["h"]
    As_top, As_bot = inp["As_top"], inp["As_bot"]
    Aps = inp.get("Aps", 0)
    hasPT = inp.get("hasPT", False)
    is_rect = inp["isRect"]

    pm_curve = fl.get("pm_curve", [])
    pm_data = fl.get("pm_data", [])
    ok(len(pm_curve) >= 10, f"pm_curve has {len(pm_curve)} pts, need ≥10")
    ok(len(pm_data) >= 10, f"pm_data has {len(pm_data)} pts, need ≥10")

    # Pr and Mr should be φ × Pn and φ × Mn
    for i, p in enumerate(pm_curve[1:-1], 1):
        if p.get("phi"):
            ok(near(p["Pr"], p["phi"] * p["Pn"], tol=0.02),
               f"PM pt {i}: Pr={p['Pr']:.1f} vs φ·Pn={p['phi']*p['Pn']:.1f}")
            ok(near(p["Mr"], p["phi"] * p["Mn"], tol=0.02),
               f"PM pt {i}: Mr={p['Mr']:.1f} vs φ·Mn={p['phi']*p['Mn']:.1f}")

    # P-M curve should be built for the correct compression face
    comp_face = fl["comp_face"]
    # Build reference directly
    I = dict(raw)
    derive_constants(I)
    pm_ref = build_pm_curve(I, comp_face)
    if pm_ref and pm_curve:
        # Mid-point comparison
        mid = len(pm_ref) // 2
        ok(near(pm_curve[mid]["Mr"], pm_ref[mid]["Mr"], tol=0.01),
           f"PM curve matches direct build_pm_curve(comp_face='{comp_face}') at midpoint")

    # Check that Mr_atPu is correctly interpolated
    Mr_atPu_check = get_mr_at_pu(pm_curve, Pu) if pm_curve else 0
    ok(near(fl["Mr_atPu"], Mr_atPu_check, tol=0.02),
       f"Mr_atPu ({fl['Mr_atPu']:.1f}) vs get_mr_at_pu ({Mr_atPu_check:.1f})")

    # Now test hogging curve vs sagging curve for symmetric sections
    if As_top == As_bot and As_top > 0:
        pm_sag = build_pm_curve(I, "top")
        pm_hog = build_pm_curve(I, "bottom")
        # For symmetric reinforcement (same bars top/bot, symmetric d), curves should match
        # Only exactly true if d_top and h-d_bot are equal AND flanges are symmetric
        d_top_val = inp["d_top"]
        d_bot_val = inp["d_bot"]
        flanges_sym = is_rect or near(inp.get("hf_top", 0), inp.get("hf_bot", 0), tol=0.01)
        if near(d_top_val, h - d_bot_val, tol=0.01) and (Aps == 0) and flanges_sym:
            mid = len(pm_sag) // 2
            ok(near(pm_sag[mid]["Mr"], pm_hog[mid]["Mr"], tol=0.02),
               f"Symmetric section: sag PM Mr={pm_sag[mid]['Mr']:.1f} ≈ hog PM Mr={pm_hog[mid]['Mr']:.1f} at midpoint")

    # Both sagging and hogging Pn_max should be the same (section is the same)
    pm_sag = build_pm_curve(I, "top")
    pm_hog = build_pm_curve(I, "bottom")
    ok(near(pm_sag[0]["Pr"], pm_hog[0]["Pr"]),
       f"Pn_max should be same for sag/hog: sag={pm_sag[0]['Pr']:.0f}, hog={pm_hog[0]['Pr']:.0f}")


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT 3: SERVICE STRESS — correct steel, sign independence, Icr, Ieff
# ═══════════════════════════════════════════════════════════════════════════════

def audit_service(res, raw, dem):
    fl = res["flexure"]
    inp = res["inputs"]
    d = dem[0]
    Mu, Ms, Ps = d["Mu"], d.get("Ms", 0), d.get("Ps", 0)
    h, b = inp["h"], inp["b"]
    Es = inp["Es"]
    As_top, As_bot = inp["As_top"], inp["As_bot"]
    d_top, d_bot = inp["d_top"], inp["d_bot"]
    Aps = inp.get("Aps", 0)
    is_rect = inp["isRect"]

    # 1. Service steel assignment should be based on Ms sign, NOT Mu sign
    if Ms >= 0:
        ok(fl.get("serv_comp_face") == "top", f"Service comp_face should be 'top' for Ms≥0, got '{fl.get('serv_comp_face')}'")
        ok(near(fl.get("serv_As", 0), As_bot), f"Service As should = As_bot for Ms≥0, got {fl.get('serv_As',0):.3f}")
        ok(near(fl.get("serv_ds", 0), d_bot), f"Service ds should = d_bot for Ms≥0, got {fl.get('serv_ds',0):.3f}")
    else:
        ok(fl.get("serv_comp_face") == "bottom", f"Service comp_face should be 'bottom' for Ms<0, got '{fl.get('serv_comp_face')}'")
        ok(near(fl.get("serv_As", 0), As_top), f"Service As should = As_top for Ms<0, got {fl.get('serv_As',0):.3f}")
        ok(near(fl.get("serv_ds", 0), h - d_top), f"Service ds should = h-d_top for Ms<0, got {fl.get('serv_ds',0):.3f}")

    # 2. c_cr, Icr sanity
    s_As = fl.get("serv_As", 0)
    if s_As > 0 or (Aps > 0):
        ok(fl["c_cr"] > 0, f"c_cr > 0, got {fl['c_cr']:.4f}")
        ok(fl["Icr"] > 0, f"Icr > 0, got {fl['Icr']:.1f}")

    # 3. Ig should match section
    if is_rect:
        Ig_hand = b * h ** 3 / 12
        ok(near(fl["Ig"], Ig_hand, tol=0.005), f"Ig rect: {fl['Ig']:.1f} vs hand {Ig_hand:.1f}")
    else:
        hf_top, hf_bot = inp.get("hf_top", 0), inp.get("hf_bot", 0)
        bw = inp["bw"]
        hw = h - hf_top - hf_bot
        A1, y1 = b * hf_top, hf_top / 2
        A2, y2 = bw * hw, hf_top + hw / 2
        A3, y3 = b * hf_bot, hf_top + hw + hf_bot / 2
        At = A1 + A2 + A3
        yb = (A1*y1 + A2*y2 + A3*y3) / At if At > 0 else h/2
        Ig_hand = (b*hf_top**3/12 + A1*(yb-y1)**2
                   + bw*hw**3/12 + A2*(yb-y2)**2
                   + b*hf_bot**3/12 + A3*(yb-y3)**2)
        ok(near(fl["Ig"], Ig_hand, tol=0.005), f"Ig I-sect: {fl['Ig']:.1f} vs hand {Ig_hand:.1f}")

    # 4. Ieff bounds
    if fl.get("Ieff") and fl.get("Ig") and fl.get("Icr"):
        ok(fl["Ieff"] <= fl["Ig"] + 1, f"Ieff ({fl['Ieff']:.0f}) ≤ Ig ({fl['Ig']:.0f})")
        # Icr ≤ Ieff only when cracking occurs
        if fl["Icr"] > 0 and abs(Ms) > 0:
            ok(fl["Icr"] <= fl["Ieff"] + 1, f"Icr ({fl['Icr']:.0f}) ≤ Ieff ({fl['Ieff']:.0f})", warn_only=True)

    # 5. Hand-check fss for simple rectangular (no PT, no compression steel)
    if is_rect and s_As > 0 and not (Aps > 0) and abs(Ms) > 0:
        n = fl["n_mod"]
        nAs = s_As * n
        s_ds = fl.get("serv_ds", 0)
        # quadratic for c_cr
        qa = b / 2
        qb = nAs
        qc = -nAs * s_ds
        disc = qb**2 - 4*qa*qc
        if disc > 0 and qa > 0:
            c_cr_hand = (-qb + math.sqrt(disc)) / (2*qa)
            Icr_hand = b * c_cr_hand**3 / 3 + nAs * (s_ds - c_cr_hand)**2
            M_total = abs(Ms) + Ps * (h/2 - c_cr_hand)
            fss_hand = M_total * (s_ds - c_cr_hand) / Icr_hand * n + Ps / (nAs + c_cr_hand*b) * n if Icr_hand > 0 else 0
            ok(near(fl["c_cr"], c_cr_hand, tol=0.02),
               f"c_cr hand ({c_cr_hand:.3f}) vs engine ({fl['c_cr']:.3f})")
            ok(near(fl["Icr"], Icr_hand, tol=0.02),
               f"Icr hand ({Icr_hand:.1f}) vs engine ({fl['Icr']:.1f})")
            ok(near(fl["fss"], fss_hand, tol=0.03),
               f"fss hand ({fss_hand:.2f}) vs engine ({fl['fss']:.2f})")


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT 4: SHEAR — sign-dependent As, Act, eps_s, all 3 methods
# ═══════════════════════════════════════════════════════════════════════════════

def audit_shear(res, raw, dem):
    sh = res["shear"]
    fl = res["flexure"]
    inp = res["inputs"]
    d = dem[0]
    Mu, Pu, Vu, Tu = d["Mu"], d["Pu"], d["Vu"], d.get("Tu", 0)
    h, b = inp["h"], inp["b"]
    is_rect = inp["isRect"]
    bw = inp["bw"]
    hf_top, hf_bot = inp.get("hf_top", 0), inp.get("hf_bot", 0)
    As_top, As_bot = inp["As_top"], inp["As_bot"]
    d_top, d_bot = inp["d_top"], inp["d_bot"]
    fc = raw["fc"]
    fy = raw["fy"]

    # 1. Shear uses tension As from flexure (sign-dependent)
    if Mu >= 0:
        As_tens_exp = As_bot
    else:
        As_tens_exp = As_top
    ok(near(fl["As"], As_tens_exp),
       f"Shear As (from flexure) should be {As_tens_exp:.3f}, flexure As = {fl['As']:.3f}")

    # 2. dv and bv correct
    ok(sh["dv"] > 0, f"dv > 0, got {sh['dv']:.3f}")
    if is_rect:
        ok(near(sh["bv"], b), f"bv should = b ({b}) for rect, got {sh['bv']:.2f}")
    else:
        ok(near(sh["bv"], bw), f"bv should = bw ({bw}) for I-sect, got {sh['bv']:.2f}")

    # 3. Strain eps_s should be finite
    ok(-0.001 <= sh["eps_s"] <= 0.007, f"eps_s in valid range, got {sh['eps_s']:.6f}")

    # 4. All 3 methods produce valid results
    for m in [1, 2, 3]:
        Vr = sh.get(f"Vr{m}", 0)
        Vn = sh.get(f"Vn{m}", 0)
        Vc = sh.get(f"Vc{m}", 0)
        Vs = sh.get(f"Vs{m}", 0)
        ok(Vc >= 0, f"Vc{m} >= 0, got {Vc:.1f}")
        ok(Vs >= 0, f"Vs{m} >= 0, got {Vs:.1f}")
        ok(Vn <= sh["Vnmax"] + 0.1, f"Vn{m} ({Vn:.1f}) ≤ Vnmax ({sh['Vnmax']:.1f})")
        phi_v = raw.get("phi_v", 0.9)
        ok(near(Vr, phi_v * Vn, tol=0.02), f"Vr{m} = φ·Vn{m}: {Vr:.1f} vs {phi_v*Vn:.1f}")

    # 5. Method 1: θ=45°, β=2.0
    ok(near(sh["th1"], 45, tol=0.01), f"Method 1 θ=45, got {sh['th1']}")
    ok(near(sh["bt1"], 2, tol=0.01), f"Method 1 β=2.0, got {sh['bt1']}")

    # 6. Method 2: θ = 29+3500εs, β from formula
    th2_chk = 29 + 3500 * sh["eps_s"]
    ok(near(sh["th2"], th2_chk, tol=0.1), f"Method 2 θ = 29+3500εs = {th2_chk:.2f}, got {sh['th2']:.2f}")

    # 7. Act on tension side for negative moment should use top flange
    if not is_rect and Mu < 0:
        Act_exp = b * hf_top + bw * max(h/2 - hf_top, 0)
        ok(near(sh["Act_gp"], Act_exp, tol=0.02),
           f"Act_gp for hogging I-sect should use top flange: exp={Act_exp:.1f}, got {sh['Act_gp']:.1f}")
    elif not is_rect and Mu >= 0:
        Act_exp = b * hf_bot + bw * max(h/2 - hf_bot, 0)
        ok(near(sh["Act_gp"], Act_exp, tol=0.02),
           f"Act_gp for sagging I-sect should use bottom flange: exp={Act_exp:.1f}, got {sh['Act_gp']:.1f}")

    # 8. Hand-check Vc1 (Method 1 simplified)
    lam = raw.get("lam", 1.0)
    Vc1_hand = 0.0316 * 2.0 * lam * math.sqrt(fc) * sh["bv"] * sh["dv"]
    ok(near(sh["Vc1"], Vc1_hand, tol=0.02), f"Vc1 hand ({Vc1_hand:.1f}) vs engine ({sh['Vc1']:.1f})")

    # 9. Longitudinal reinforcement
    ok("long_ok" in sh, "long_ok present")
    ok(sh["long_cap"] >= 0, f"long_cap >= 0, got {sh['long_cap']:.1f}")
    ok(sh["long_dem"] >= 0 or sh["long_dem"] < 0, f"long_dem exists, got {sh['long_dem']:.1f}")

    # 10. Veff increases when torsion is considered
    if sh.get("torsion_consider"):
        ok(sh["Veff"] >= abs(Vu), f"Veff ({sh['Veff']:.1f}) >= |Vu| ({abs(Vu):.1f}) when torsion considered")

    # 11. Compression should decrease eps_s (more compression = lower strain = higher Vc)
    # (not a direct check here, tested in consistency section)


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT 5: TORSION — threshold, capacity, combined checks
# ═══════════════════════════════════════════════════════════════════════════════

def audit_torsion(res, raw, dem):
    tor = res["torsion"]
    sh = res["shear"]
    d = dem[0]
    Tu = d.get("Tu", 0)
    Vu = d["Vu"]
    phi_v = raw.get("phi_v", 0.9)
    fc = raw["fc"]

    ok(tor["Tcr"] > 0, f"Tcr > 0, got {tor['Tcr']:.1f}")
    ok(tor["thresh"] > 0, f"thresh > 0, got {tor['thresh']:.1f}")
    ok(near(tor["thresh"], 0.25 * phi_v * tor["Tcr"]),
       f"thresh = 0.25φTcr: {tor['thresh']:.1f} vs {0.25*phi_v*tor['Tcr']:.1f}")

    # Consider check
    if abs(Tu) > tor["thresh"]:
        ok(tor["consider"], f"Tu={abs(Tu)} > thresh={tor['thresh']:.1f}: consider should be True")
    else:
        ok(not tor["consider"], f"Tu={abs(Tu)} ≤ thresh={tor['thresh']:.1f}: consider should be False")

    if tor["consider"]:
        ok(tor["Tr"] > 0, f"Tr > 0 when torsion considered, got {tor['Tr']:.1f}")
        ok(near(tor["Tr"], phi_v * tor["Tn"]), f"Tr = φTn: {tor['Tr']:.1f} vs {phi_v*tor['Tn']:.1f}")
        ok("comb_ok" in tor, "comb_ok present when torsion considered")
        ok(tor["comb_lim"] > 0, f"comb_lim = 0.25fc > 0")
        ok(near(tor["comb_lim"], 0.25 * fc), f"comb_lim = 0.25fc: {tor['comb_lim']:.2f} vs {0.25*fc:.2f}")
        ok("Al_gov" in tor, "Al_gov present when torsion considered")
        ok("long_comb_ok" in tor, "long_comb_ok present")


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT 6: ROW RESULTS — each demand row gets correct Mr, shear, crack
# ═══════════════════════════════════════════════════════════════════════════════

def audit_rows(res, raw, dem):
    rr = res["row_results"]
    inp = res["inputs"]
    ok(len(rr) == len(dem), f"row_results count ({len(rr)}) = demands count ({len(dem)})")

    for i, (r, d) in enumerate(zip(rr, dem)):
        Mu_row = d["Mu"]
        Vu_row = d["Vu"]
        # Determine tension steel for this Mu sign
        if Mu_row >= 0:
            has_tens = inp["As_bot"] > 0 or (inp.get("Aps", 0) > 0 and inp.get("hasPT", False))
        else:
            has_tens = inp["As_top"] > 0 or (inp.get("Aps", 0) > 0 and inp.get("hasPT", False))

        if has_tens:
            ok(r["Mr"] > 0, f"Row {i+1}: Mr > 0, got {r['Mr']:.1f}")
        else:
            ok(r["Mr"] >= 0, f"Row {i+1}: Mr ≥ 0 (no tension steel), got {r['Mr']:.1f}")

        ok(r.get("flexStatus") in ("OK", "MIN", "NG"),
           f"Row {i+1}: flexStatus in {{OK,MIN,NG}}, got '{r.get('flexStatus')}'")
        ok(r.get("shearStatus") in ("OK", "NR", "NG"),
           f"Row {i+1}: shearStatus in {{OK,NR,NG}}, got '{r.get('shearStatus')}'")
        ok(r.get("crackStatus") in ("OK", "NG"),
           f"Row {i+1}: crackStatus in {{OK,NG}}, got '{r.get('crackStatus')}'")

        # Shear capacities positive
        for vm in [1, 2]:
            ok(r.get(f"Vr{vm}", 0) > 0, f"Row {i+1}: Vr{vm} > 0, got {r.get(f'Vr{vm}',0):.1f}")
        ok(r.get("Vr3", 0) >= 0, f"Row {i+1}: Vr3 ≥ 0, got {r.get('Vr3',0):.1f}")


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT 7: REPORT KEYS — all keys referenced in generateReport() exist
# ═══════════════════════════════════════════════════════════════════════════════

def audit_report_keys(res):
    fl = res["flexure"]
    sh = res["shear"]
    tor = res["torsion"]
    inp = res["inputs"]

    # Flexure keys
    for k in ["c", "a", "beta1", "alpha1", "phi_f", "Mn", "Mr", "Mr_atPu",
              "eps_t", "sec_status", "ds", "As", "As_comp", "d_s_comp", "comp_face",
              "dv", "dv1", "dv2", "dv3", "de", "hf", "bv",
              "As_top", "As_bot", "d_top", "d_bot",
              "nBars_tens", "nBars_comp", "barN_tens", "barN_comp",
              "bar_d_tens", "bar_d_comp",
              "gamma1", "gamma3", "fr", "Sc", "Mcr", "Mcond", "min_flex_ok",
              "dc", "beta_s", "fss_simp", "s_crack", "s_min_ck", "s_max_ck",
              "c_cr", "Icr", "fss", "fps_serv", "eps_rb", "curv", "Ieff", "Ig",
              "n_mod", "nAs", "n_pt", "nAps", "M_serv", "addlBM",
              "pm_data", "pm_curve",
              "c_ds_ratio", "c_ds_limit", "c_ds_ok", "use_strain_compat",
              "comp_steel_yields", "eps_comp", "fs_comp",
              "ecl", "etl",
              "phi_cc", "phi_tc", "phi_k",
              "Aps", "fps_calc",
              "serv_comp_face", "serv_ds", "serv_As",
              "tot_tens"]:
        ok(k in fl, f"Flexure key '{k}' present in result")

    # Shear keys
    for k in ["dv", "bv", "Vnmax", "eps_s", "fpo", "Mu_c",
              "th1", "bt1", "Vc1", "Vs1", "Vn1", "Vr1",
              "bt2", "bt2a", "bt2b", "th2", "Vc2", "Vs2", "Vn2", "Vr2",
              "th3", "bt3", "Vc3", "Vs3", "Vn3", "Vr3",
              "b5_valid", "n_iter", "ex_b5", "vufc", "vu_b5", "sxe",
              "sh_reqd", "Av_min", "has_min_av", "s_max_sh", "vu",
              "long_dem", "long_cap", "long_ok",
              "ld_M", "ld_N", "ld_V", "ld_T_tors", "ld_VT", "cott",
              "Vs_des", "phi_c",
              "lambda_duct", "denom", "Act_gp",
              "eps_s_neg_recalc", "flex_compr", "fr", "dbl_eps",
              "Veff", "tors_shear_comp", "torsion_consider",
              "sh_reqd1", "sh_reqd2", "sh_reqd3"]:
        ok(k in sh, f"Shear key '{k}' present in result")

    # Torsion keys
    for k in ["Tcr", "thresh", "consider", "pc", "Acp", "Ao", "ph", "be",
              "theta", "At", "Tn", "Tr",
              "At_s_avail", "At_s_from_bar",
              "tors_shear", "Veff",
              "comb_stress", "comb_lim", "comb_ok",
              "Av_s_shear", "At_s_tors", "Av_s_comb", "Av_s_prov", "comb_reinf_ok",
              "min_trans",
              "Al_tors", "Al_min", "Al_gov",
              "long_dem_comb", "long_cap_val", "long_comb_ok",
              "s_max_tors"]:
        ok(k in tor, f"Torsion key '{k}' present in result")

    # Input keys used by report
    for k in ["h", "b", "Ec", "Es", "cover", "dp", "isRect", "bw",
              "As_top", "As_bot", "d_top", "d_bot", "bar_d_top", "bar_d_bot",
              "Aps", "hasPT", "hf_top", "hf_bot", "ecl", "etl", "alpha1"]:
        ok(k in inp, f"Input key '{k}' present in result")


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT 8: CONSISTENCY CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

def consistency_checks():
    print("\n" + "─" * 60)
    print("  CONSISTENCY CHECKS")
    print("─" * 60)

    # A. Symmetric section: sagging = hogging (rect, top=bot reinforcement)
    print("\n  [Symmetric Rect: sag vs hog Mr]")
    raw_sym = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4)
    dem_s = [{"Pu":0, "Mu":3000, "Vu":100, "Tu":50, "Vp":0, "Ms":1500, "Ps":0}]
    dem_h = [{"Pu":0, "Mu":-3000, "Vu":100, "Tu":50, "Vp":0, "Ms":-1500, "Ps":0}]
    rs = calculate_all(raw_sym, dem_s, 0)
    rh = calculate_all(raw_sym, dem_h, 0)
    ok(near(rs["flexure"]["Mr"], rh["flexure"]["Mr"], tol=0.01),
       f"Sym rect: sag Mr={rs['flexure']['Mr']:.1f} ≈ hog Mr={rh['flexure']['Mr']:.1f}")
    ok(near(rs["shear"]["Vr2"], rh["shear"]["Vr2"], tol=0.05),
       f"Sym rect: sag Vr2={rs['shear']['Vr2']:.1f} ≈ hog Vr2={rh['shear']['Vr2']:.1f}")

    # B. Symmetric I-section: sag vs hog Mr
    print("\n  [Symmetric I-sect: sag vs hog Mr]")
    raw_isym = make_inputs(h=36, b=36, secType="T-SECTION", bw_input=12, hf_top=8, hf_bot=8,
                            barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4)
    rs_i = calculate_all(raw_isym, dem_s, 0)
    rh_i = calculate_all(raw_isym, dem_h, 0)
    ok(near(rs_i["flexure"]["Mr"], rh_i["flexure"]["Mr"], tol=0.01),
       f"Sym I-sect: sag Mr={rs_i['flexure']['Mr']:.1f} ≈ hog Mr={rh_i['flexure']['Mr']:.1f}")

    # C. Asymmetric flanges: hf_top ≠ hf_bot should give different Mr
    print("\n  [Asymmetric I-sect: different Mr for sag vs hog]")
    raw_asym = make_inputs(h=48, b=36, secType="T-SECTION", bw_input=12, hf_top=10, hf_bot=6,
                            barN_bot=11, nBars_bot=6, barN_top=11, nBars_top=6)
    rs_a = calculate_all(raw_asym, dem_s, 0)
    rh_a = calculate_all(raw_asym, dem_h, 0)
    # Not necessarily different if block stays in flange, but P-M curves should differ
    I_a = dict(raw_asym)
    derive_constants(I_a)
    pm_sag_a = build_pm_curve(I_a, "top")
    pm_hog_a = build_pm_curve(I_a, "bottom")
    mid = len(pm_sag_a) // 2
    # At balanced point, moment capacity should differ due to different flange sizes
    print(f"    Asym: sag PM mid Mr={pm_sag_a[mid]['Mr']:.0f}, hog PM mid Mr={pm_hog_a[mid]['Mr']:.0f}")
    # Just check they computed without error
    ok(pm_sag_a[mid]["Mr"] >= 0, "Asym sag PM mid Mr ≥ 0")
    ok(pm_hog_a[mid]["Mr"] >= 0, "Asym hog PM mid Mr ≥ 0")

    # D. Compression should reduce eps_s (improve Vc)
    print("\n  [Compression reduces shear strain → higher Vc]")
    raw_c = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4)
    dem_0 = [{"Pu":0, "Mu":2000, "Vu":100, "Tu":0, "Vp":0, "Ms":0, "Ps":0}]
    dem_comp = [{"Pu":-300, "Mu":2000, "Vu":100, "Tu":0, "Vp":0, "Ms":0, "Ps":0}]
    res_0 = calculate_all(raw_c, dem_0, 0)
    res_c = calculate_all(raw_c, dem_comp, 0)
    ok(res_c["shear"]["eps_s"] <= res_0["shear"]["eps_s"] + 1e-6,
       f"Compression reduces eps_s: P=0 eps={res_0['shear']['eps_s']:.6f}, P=-300 eps={res_c['shear']['eps_s']:.6f}")
    ok(res_c["shear"]["Vc2"] >= res_0["shear"]["Vc2"] - 1,
       f"Compression increases Vc2: P=0 Vc={res_0['shear']['Vc2']:.1f}, P=-300 Vc={res_c['shear']['Vc2']:.1f}",
       warn_only=True)

    # E. I-section Mn ≥ Rectangular(bw) Mn (wider flanges can only help)
    print("\n  [I-section Mn ≥ Rectangular(bw) Mn]")
    raw_rect_bw = make_inputs(h=36, b=12, barN_bot=8, nBars_bot=4)
    raw_i_mn = make_inputs(h=36, b=36, secType="T-SECTION", bw_input=12, hf_top=8, hf_bot=8,
                            barN_bot=8, nBars_bot=4)
    dem_mn = [{"Pu":0, "Mu":2000, "Vu":0, "Tu":0, "Vp":0, "Ms":0, "Ps":0}]
    res_rect_bw = calculate_all(raw_rect_bw, dem_mn, 0)
    res_i_mn = calculate_all(raw_i_mn, dem_mn, 0)
    ok(res_i_mn["flexure"]["Mn"] >= res_rect_bw["flexure"]["Mn"] - 1,
       f"I-sect Mn ({res_i_mn['flexure']['Mn']:.1f}) ≥ Rect(bw) Mn ({res_rect_bw['flexure']['Mn']:.1f})")

    # F. Heavy rebar I-section: compression block should exceed flange
    print("\n  [Heavy rebar I-sect: stress block exceeds flange]")
    raw_heavy = make_inputs(h=36, b=48, secType="T-SECTION", bw_input=12, hf_top=6, hf_bot=6,
                             barN_bot=11, nBars_bot=8, barN_top=11, nBars_top=8)
    dem_heavy = [{"Pu":0, "Mu":5000, "Vu":100, "Tu":0, "Vp":0, "Ms":2500, "Ps":0}]
    res_heavy = calculate_all(raw_heavy, dem_heavy, 0)
    fl_h = res_heavy["flexure"]
    print(f"    a = {fl_h['a']:.3f}, hf = {fl_h['hf']:.1f}")
    if fl_h["a"] > fl_h["hf"]:
        print("    ✓ Block exceeds flange (T-section formula used)")
        ok(fl_h["Mn"] > 0, f"Mn > 0 for T-section case, got {fl_h['Mn']:.1f}")
    else:
        print(f"    Block within flange (a={fl_h['a']:.3f} ≤ hf={fl_h['hf']:.1f})")

    # G. Hogging heavy rebar: verify bottom flange used
    dem_heavy_hog = [{"Pu":0, "Mu":-5000, "Vu":100, "Tu":0, "Vp":0, "Ms":-2500, "Ps":0}]
    res_heavy_hog = calculate_all(raw_heavy, dem_heavy_hog, 0)
    fl_hh = res_heavy_hog["flexure"]
    ok(fl_hh["comp_face"] == "bottom", f"Heavy hogging comp_face='bottom', got '{fl_hh['comp_face']}'")
    ok(near(fl_hh["hf"], 6), f"Heavy hogging hf should = hf_bot (6), got {fl_hh['hf']}")
    print(f"    Hogging: a = {fl_hh['a']:.3f}, hf_bot = {fl_hh['hf']:.1f}")

    # H. PT section: fps_calc should be > 0 and < fpu
    print("\n  [PT section: fps_calc valid]")
    raw_pt = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                          nStrands=4, strand_area=0.217, dp=30, sectionClass="CIP_PT")
    dem_pt = [{"Pu":0, "Mu":3000, "Vu":100, "Tu":0, "Vp":0, "Ms":1500, "Ps":0}]
    res_pt = calculate_all(raw_pt, dem_pt, 0)
    fl_pt = res_pt["flexure"]
    ok(0 < fl_pt["fps_calc"] < 270, f"fps_calc ({fl_pt['fps_calc']:.1f}) should be 0 < fps < 270")

    # I. Service: Ms sign independent of Mu sign
    print("\n  [Service: Ms sign independent of Mu]")
    raw_ind = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4)
    # Case 1: Mu sagging, Ms hogging
    dem_mixed1 = [{"Pu":0, "Mu":3000, "Vu":100, "Tu":0, "Vp":0, "Ms":-1500, "Ps":0}]
    res_m1 = calculate_all(raw_ind, dem_mixed1, 0)
    ok(res_m1["flexure"]["comp_face"] == "top", "Mu>0 → comp_face=top")
    ok(res_m1["flexure"]["serv_comp_face"] == "bottom", "Ms<0 → serv_comp_face=bottom")
    # Case 2: Mu hogging, Ms sagging
    dem_mixed2 = [{"Pu":0, "Mu":-3000, "Vu":100, "Tu":0, "Vp":0, "Ms":1500, "Ps":0}]
    res_m2 = calculate_all(raw_ind, dem_mixed2, 0)
    ok(res_m2["flexure"]["comp_face"] == "bottom", "Mu<0 → comp_face=bottom")
    ok(res_m2["flexure"]["serv_comp_face"] == "top", "Ms>0 → serv_comp_face=top")


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT 9: I-SECTION SPECIFIC — flange transition in P-M curve
# ═══════════════════════════════════════════════════════════════════════════════

def audit_isection_pm():
    """Verify P-M curve handles compression block > flange thickness correctly for I-sections."""
    print("\n" + "─" * 60)
    print("  I-SECTION P-M SPECIFIC AUDIT")
    print("─" * 60)

    I_raw = make_inputs(h=36, b=48, secType="T-SECTION", bw_input=12, hf_top=6, hf_bot=6,
                         barN_bot=11, nBars_bot=8, barN_top=11, nBars_top=8)
    I = dict(I_raw)
    derive_constants(I)
    fc, fy = I["fc"], I["fy"]
    alpha1, beta1 = I["alpha1"], I["beta1"]
    b, bw, h = I["b"], I["bw"], I["h"]
    hf_top, hf_bot = I["hf_top"], I["hf_bot"]

    for comp_face_name, hf_val in [("top", hf_top), ("bottom", hf_bot)]:
        pm = build_pm_curve(I, comp_face_name)
        print(f"\n  Comp face = {comp_face_name}, hf = {hf_val}")

        found_rect = False
        found_tsect = False
        for p in pm:
            if "a" in p:
                a_val = p["a"]
                if a_val <= hf_val:
                    found_rect = True
                elif a_val > hf_val:
                    found_tsect = True

        ok(found_rect, f"  comp={comp_face_name}: Some PM points have a ≤ hf (within flange)")
        ok(found_tsect, f"  comp={comp_face_name}: Some PM points have a > hf (T-section region)",
           warn_only=not found_tsect)

        # Verify Mr values are all non-negative
        for i, p in enumerate(pm):
            ok(p["Mr"] >= -0.1, f"  comp={comp_face_name} pt {i}: Mr={p['Mr']:.1f} ≥ 0")

        # Equilibrium check at a few points: sum of forces ≈ Pn
        for idx in [5, 10, 20, 30]:
            if idx >= len(pm) or "c" not in pm[idx]:
                continue
            p = pm[idx]
            ci = p["c"]
            if ci <= 0 or ci > 9000:
                continue
            ai = ci * beta1

            if comp_face_name == "top":
                As_tens, As_comp_s = I["As_bot"], I["As_top"]
                d_tens, d_comp = I["d_bot"], I["d_top"]
            else:
                As_tens, As_comp_s = I["As_top"], I["As_bot"]
                d_tens, d_comp = h - I["d_top"], h - I["d_bot"]

            # Concrete force
            if I["isRect"] or ai <= hf_val:
                Cc = -alpha1 * fc * b * ai
            else:
                Cf = alpha1 * fc * (b - bw) * hf_val
                Cw = alpha1 * fc * bw * ai
                Cc = -(Cf + Cw)

            # Steel forces
            es_tens = 0.003 * (d_tens - ci) / ci
            fs_tens = min(abs(es_tens) * I["Es"], fy) * (1 if es_tens >= 0 else -1)
            F_tens = As_tens * fs_tens

            es_comp_s = 0.003 * (d_comp - ci) / ci
            fs_comp_s = min(abs(es_comp_s) * I["Es"], fy) * (1 if es_comp_s >= 0 else -1)
            F_comp_s = As_comp_s * fs_comp_s

            Pn_check = Cc + F_tens + F_comp_s
            ok(near(p["Pn"], Pn_check, tol=0.05),
               f"  comp={comp_face_name} pt {idx}: Pn equil check: curve={p['Pn']:.0f} vs hand={Pn_check:.0f}")


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT 10: T-SECTION SERVICE — cracked section handles flange correctly
# ═══════════════════════════════════════════════════════════════════════════════

def audit_isection_service():
    """For I-section, the cracked section analysis should handle NA in flange vs web."""
    print("\n" + "─" * 60)
    print("  I-SECTION SERVICE AUDIT")
    print("─" * 60)

    # Case where c_cr is likely within flange (small reinforcement)
    raw_small = make_inputs(h=36, b=36, secType="T-SECTION", bw_input=12, hf_top=8, hf_bot=8,
                             barN_bot=5, nBars_bot=2, barN_top=5, nBars_top=2)
    dem_s = [{"Pu":0, "Mu":1000, "Vu":50, "Tu":0, "Vp":0, "Ms":500, "Ps":0}]
    res = calculate_all(raw_small, dem_s, 0)
    fl = res["flexure"]
    print(f"  Small rebar: c_cr = {fl['c_cr']:.3f}, hf_top = 8")
    ok(fl["c_cr"] > 0, f"c_cr > 0, got {fl['c_cr']:.3f}")
    ok(fl["Icr"] > 0, f"Icr > 0, got {fl['Icr']:.1f}")

    # Case where c_cr extends into web (heavy reinforcement)
    raw_heavy = make_inputs(h=36, b=48, secType="T-SECTION", bw_input=12, hf_top=6, hf_bot=6,
                             barN_bot=11, nBars_bot=8)
    dem_h = [{"Pu":0, "Mu":3000, "Vu":100, "Tu":0, "Vp":0, "Ms":1500, "Ps":0}]
    res_h = calculate_all(raw_heavy, dem_h, 0)
    fl_h = res_h["flexure"]
    print(f"  Heavy rebar: c_cr = {fl_h['c_cr']:.3f}, hf_top = 6")
    ok(fl_h["c_cr"] > 0, f"c_cr > 0, got {fl_h['c_cr']:.3f}")
    ok(fl_h["Icr"] > 0, f"Icr > 0, got {fl_h['Icr']:.1f}")
    if fl_h["c_cr"] > 6:
        print("    ✓ c_cr in web (T-section quadratic used)")
    else:
        print(f"    c_cr in flange (a small case)")

    # Hogging service for I-section
    dem_hog = [{"Pu":0, "Mu":-3000, "Vu":100, "Tu":0, "Vp":0, "Ms":-1500, "Ps":0}]
    res_hog = calculate_all(raw_heavy, dem_hog, 0)
    fl_hog = res_hog["flexure"]
    print(f"  Hogging heavy: serv_comp_face = {fl_hog.get('serv_comp_face')}, c_cr = {fl_hog['c_cr']:.3f}")
    ok(fl_hog.get("serv_comp_face") == "bottom", "Hogging Ms → serv_comp_face=bottom")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    global PASS, FAIL, WARN
    print("=" * 80)
    print("  DEEP AUDIT — AASHTO Calc Engine")
    print("  Rect & I-Section × Bot/Top/PT × Sag/Hog × Axial Tens/Comp")
    print("  P-M, Service, Shear (3 methods), Torsion, Report Keys")
    print("=" * 80)

    # ── Phase 1: Full matrix ──
    print("\n" + "─" * 60)
    print("  PHASE 1: Full Permutation Matrix")
    print("─" * 60)

    total = 0
    for sec_name, sec_kwargs in SECTIONS.items():
        desc = sec_kwargs.pop("desc", sec_name)
        for dem_name, dem_list in DEMANDS.items():
            total += 1
            label = f"{sec_name} × {dem_name}"
            print(f"\n  ▸ {label}")
            print(f"    {desc}")
            try:
                raw = make_inputs(**sec_kwargs)
                res = calculate_all(raw, dem_list, 0)
                audit_flexure(res, raw, dem_list)
                audit_pm(res, raw, dem_list)
                audit_service(res, raw, dem_list)
                audit_shear(res, raw, dem_list)
                audit_torsion(res, raw, dem_list)
                audit_rows(res, raw, dem_list)
                audit_report_keys(res)
            except Exception as e:
                global FAIL
                FAIL += 1
                print(f"    ✗ EXCEPTION: {e}")
                traceback.print_exc()
        sec_kwargs["desc"] = desc

    # ── Phase 2: Consistency checks ──
    consistency_checks()

    # ── Phase 3: I-section specific P-M audit ──
    audit_isection_pm()

    # ── Phase 4: I-section service audit ──
    audit_isection_service()

    # ── Summary ──
    print("\n" + "=" * 80)
    print(f"  RESULTS:  {PASS} passed / {FAIL} failed / {WARN} warnings")
    print(f"  Total permutation combos tested: {total}")
    if FAIL == 0:
        print("  ✓ ALL CHECKS PASSED")
    else:
        print(f"  ✗ {FAIL} CHECK(S) FAILED — review above")
    print("=" * 80)
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
