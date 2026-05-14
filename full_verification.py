"""
Full verification of AASHTO calc_engine across all section permutations.
Tests: flexure, P-M interaction, shear (3 methods), torsion, service stress.
Checks internal consistency and hand-calc spot checks.
"""
import math, sys, traceback
sys.path.insert(0, ".")
from calc_engine import (calculate_all, build_pm_curve, get_mr_at_pu,
                         derive_constants, do_flexure, BARS)

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
    """Relative tolerance check."""
    if abs(b) < 1e-9:
        return abs(a) < tol
    return abs(a - b) / max(abs(b), 1e-9) < tol

def N_safe(v):
    return v if isinstance(v, (int, float)) and v == v else 0

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

# ─── TEST CASES ───────────────────────────────────────────────────────────────

SECTIONS = {
    "Rect_BotOnly": dict(
        desc="Rectangular 36×36, 4#8 bot only, no PT",
        h=36, b=36, barN_bot=8, nBars_bot=4,
        barN_top=0, nBars_top=0,
    ),
    "Rect_TopBot": dict(
        desc="Rectangular 36×36, 4#8 bot + 4#8 top, no PT",
        h=36, b=36, barN_bot=8, nBars_bot=4,
        barN_top=8, nBars_top=4,
    ),
    "Rect_BotOnly_PT": dict(
        desc="Rectangular 36×36, 4#8 bot + PT, no top bars",
        h=36, b=36, barN_bot=8, nBars_bot=4,
        barN_top=0, nBars_top=0,
        nStrands=1, strand_area=math.pi/4*2**2, dp=28,
        sectionClass="CIP_PT",
    ),
    "Rect_TopBot_PT": dict(
        desc="Rectangular 36×36, 4#8 bot + 4#8 top + PT",
        h=36, b=36, barN_bot=8, nBars_bot=4,
        barN_top=8, nBars_top=4,
        nStrands=1, strand_area=math.pi/4*2**2, dp=28,
        sectionClass="CIP_PT",
    ),
    "I_BotOnly": dict(
        desc="I-Section 36×36 bw=12 flanges=8, 4#8 bot only",
        h=36, b=36, secType="T-SECTION", bw_input=12, hf_top=8, hf_bot=8,
        barN_bot=8, nBars_bot=4,
        barN_top=0, nBars_top=0,
    ),
    "I_TopBot": dict(
        desc="I-Section 36×36 bw=12 flanges=8, 4#8 bot + 4#8 top",
        h=36, b=36, secType="T-SECTION", bw_input=12, hf_top=8, hf_bot=8,
        barN_bot=8, nBars_bot=4,
        barN_top=8, nBars_top=4,
    ),
    "I_TopBot_PT": dict(
        desc="I-Section 36×36 bw=12 flanges=8, 4#8 bot + 4#8 top + PT",
        h=36, b=36, secType="T-SECTION", bw_input=12, hf_top=8, hf_bot=8,
        barN_bot=8, nBars_bot=4,
        barN_top=8, nBars_top=4,
        nStrands=1, strand_area=math.pi/4*2**2, dp=28,
        sectionClass="CIP_PT",
    ),
    "I_BotOnly_PT": dict(
        desc="I-Section 36×36 bw=12 flanges=8, 4#8 bot + PT, no top",
        h=36, b=36, secType="T-SECTION", bw_input=12, hf_top=8, hf_bot=8,
        barN_bot=8, nBars_bot=4,
        barN_top=0, nBars_top=0,
        nStrands=1, strand_area=math.pi/4*2**2, dp=28,
        sectionClass="CIP_PT",
    ),
}

# Demand combos to test on each section
DEMANDS = {
    "Pure_Sag_M": [
        {"Pu":0, "Mu":3000, "Vu":100, "Tu":50, "Vp":0, "Ms":1500, "Ps":0},
    ],
    "Pure_Hog_M": [
        {"Pu":0, "Mu":-3000, "Vu":100, "Tu":50, "Vp":0, "Ms":1500, "Ps":0},
    ],
    "Axial_Tens_Sag": [
        {"Pu":50, "Mu":2000, "Vu":80, "Tu":30, "Vp":0, "Ms":1000, "Ps":10},
    ],
    "Axial_Comp_Sag": [
        {"Pu":-200, "Mu":2000, "Vu":80, "Tu":30, "Vp":0, "Ms":1000, "Ps":-50},
    ],
    "Axial_Tens_Hog": [
        {"Pu":50, "Mu":-2000, "Vu":80, "Tu":30, "Vp":0, "Ms":1000, "Ps":10},
    ],
    "High_Shear_Torsion": [
        {"Pu":0, "Mu":2000, "Vu":300, "Tu":200, "Vp":0, "Ms":1000, "Ps":0},
    ],
    "MultiRow": [
        {"Pu":0,   "Mu":3000,  "Vu":150, "Tu":100, "Vp":0, "Ms":1500, "Ps":0},
        {"Pu":50,  "Mu":-2000, "Vu":80,  "Tu":30,  "Vp":0, "Ms":1000, "Ps":10},
        {"Pu":-100,"Mu":4000,  "Vu":200, "Tu":50,  "Vp":0, "Ms":2000, "Ps":-20},
    ],
}

# ─── VERIFICATION FUNCTIONS ───────────────────────────────────────────────────

def verify_flexure(res, raw, dem):
    fl = res["flexure"]
    inp = res["inputs"]
    d = dem[0]
    Mu = d["Mu"]
    Pu = d["Pu"]

    # Basic sanity
    # When hogging with no tension steel, Mn/Mr can be 0
    has_tens = fl["As"] > 0 or (inp.get("Aps",0) > 0 and inp.get("hasPT",False))
    if has_tens:
        ok(fl["Mr"] > 0, f"Mr should be > 0, got {fl['Mr']:.1f}")
        ok(fl["Mn"] > 0, f"Mn should be > 0, got {fl['Mn']:.1f}")
    else:
        ok(fl["Mn"] >= 0, f"Mn should be >= 0 (no tension steel), got {fl['Mn']:.1f}")
        ok(fl["Mr"] >= 0, f"Mr should be >= 0 (no tension steel), got {fl['Mr']:.1f}")
    ok(fl["Mr"] <= fl["Mn"] + 0.1, f"Mr ({fl['Mr']:.1f}) should be <= Mn ({fl['Mn']:.1f})")
    ok(0 < fl["phi_f"] <= 1.0, f"phi_f should be 0 < φ ≤ 1.0, got {fl['phi_f']:.4f}")
    ok(near(fl["Mr"], fl["phi_f"] * fl["Mn"]),
       f"Mr ({fl['Mr']:.1f}) should = φ·Mn ({fl['phi_f']:.4f}×{fl['Mn']:.1f}={fl['phi_f']*fl['Mn']:.1f})")
    ok(fl["a"] > 0, f"Stress block a should be > 0, got {fl['a']:.4f}")
    ok(fl["c"] > 0, f"Neutral axis c should be > 0, got {fl['c']:.4f}")
    ok(near(fl["a"], fl["beta1"] * fl["c"]),
       f"a ({fl['a']:.4f}) should = β1·c ({fl['beta1']:.4f}×{fl['c']:.4f})")

    # Comp face correct?
    if Mu >= 0:
        ok(fl["comp_face"] == "top", f"Mu≥0 should give comp_face='top', got '{fl['comp_face']}'")
    else:
        ok(fl["comp_face"] == "bottom", f"Mu<0 should give comp_face='bottom', got '{fl['comp_face']}'")

    # ds should be positive and < h
    h = inp["h"]
    ok(0 < fl["ds"] < h, f"ds ({fl['ds']:.3f}) should be 0 < ds < h ({h})")
    ok(fl["dv"] > 0, f"dv should be > 0, got {fl['dv']:.3f}")

    # P-M curve
    ok(fl.get("pm_curve") is not None, "pm_curve should exist")
    ok(fl.get("pm_data") is not None, "pm_data should exist")
    if fl.get("pm_curve"):
        pm = fl["pm_curve"]
        ok(len(pm) >= 10, f"pm_curve should have ≥10 points, got {len(pm)}")
        # Check that Mr_atPu matches interpolation
        Mr_atPu_check = get_mr_at_pu(pm, Pu)
        ok(near(fl["Mr_atPu"], Mr_atPu_check, tol=0.02),
           f"Mr_atPu ({fl['Mr_atPu']:.1f}) should match get_mr_at_pu ({Mr_atPu_check:.1f})")

    # Minimum flexure check
    ok("Mcr" in fl, "Mcr should be in flexure result")
    ok("min_flex_ok" in fl, "min_flex_ok should be in flexure result")

    # Beta1 check (ACI/AASHTO): beta1 = 0.85 for fc <= 4 ksi, decreases for higher
    fc = raw.get("fc", 4)
    if fc <= 4:
        ok(near(fl["beta1"], 0.85), f"β1 for fc={fc} should be 0.85, got {fl['beta1']:.4f}")
    elif fc >= 8:
        ok(near(fl["beta1"], 0.65), f"β1 for fc={fc} should be 0.65, got {fl['beta1']:.4f}")

    return True


def verify_shear(res, raw, dem):
    sh = res["shear"]
    d = dem[0]
    Vu = d["Vu"]

    ok(sh["dv"] > 0, f"Shear dv > 0, got {sh['dv']:.3f}")
    ok(sh["bv"] > 0, f"Shear bv > 0, got {sh['bv']:.3f}")

    # Three shear methods
    for m in [1, 2, 3]:
        Vr = sh.get(f"Vr{m}")
        Vn = sh.get(f"Vn{m}")
        Vc = sh.get(f"Vc{m}")
        Vs = sh.get(f"Vs{m}")
        ok(Vr is not None, f"Vr{m} should exist")
        ok(Vn is not None, f"Vn{m} should exist")
        if Vr is not None and Vn is not None:
            phi_v = raw.get("phi_v", 0.9)
            ok(near(Vr, phi_v * Vn),
               f"Vr{m} ({Vr:.1f}) should = φ_v·Vn{m} ({phi_v}×{Vn:.1f}={phi_v*Vn:.1f})")
        if Vc is not None:
            ok(Vc >= 0, f"Vc{m} ({Vc:.1f}) should be ≥ 0")
        if Vs is not None:
            ok(Vs >= 0, f"Vs{m} ({Vs:.1f}) should be ≥ 0")

    # Vnmax check
    ok(sh["Vnmax"] > 0, f"Vnmax should be > 0, got {sh['Vnmax']:.1f}")
    for m in [1, 2, 3]:
        Vn = sh.get(f"Vn{m}")
        if Vn is not None:
            ok(Vn <= sh["Vnmax"] + 0.1,
               f"Vn{m} ({Vn:.1f}) should not exceed Vnmax ({sh['Vnmax']:.1f})")

    # Longitudinal reinforcement check
    ok("long_ok" in sh, "long_ok should be in shear result")
    ok("long_dem" in sh and "long_cap" in sh,
       f"long_dem and long_cap should exist")

    # Method 1 (simplified θ=45°)
    ok(sh.get("th1") is not None, "theta1 should exist")
    if sh.get("th1") is not None:
        ok(near(sh["th1"], 45, tol=0.01), f"Method 1 theta should be 45°, got {sh['th1']:.1f}")

    # Method 2 theta should be between 18° and 50° (can exceed 45° for high strain)
    th2 = sh.get("th2")
    if th2 is not None:
        ok(18 <= th2 <= 50.5, f"Method 2 theta ({th2:.1f}) should be 18-50°")

    # Method 3 (B5) should have converged
    if sh.get("b5_valid") is not None:
        ok(sh["b5_valid"], f"Method 3 (B5) should converge, n_iter={sh.get('n_iter','?')}", warn_only=True)

    return True


def verify_torsion(res, raw, dem):
    tor = res["torsion"]
    d = dem[0]
    Tu = d["Tu"]

    ok("Tcr" in tor, "Tcr should be in torsion result")
    ok("thresh" in tor, "thresh should be in torsion result")
    ok("consider" in tor, "consider should be in torsion result")

    if tor["consider"]:
        # Tn/Tr CAN legitimately be 0 for I-sections whose web is too thin
        # to form a closed torsional perimeter -- in that case the engine
        # still flags the section as inadequate via comb_reinf_ok=False.
        Tn = tor.get("Tn", 0)
        Tr = tor.get("Tr", 0)
        ok(Tn >= 0, f"Tn should be >= 0, got {Tn:.1f}")
        ok(Tr >= 0, f"Tr should be >= 0, got {Tr:.1f}")
        if Tn == 0:
            ok(tor.get("comb_reinf_ok") is False,
               f"Tn=0 but comb_reinf_ok=True -- inconsistent")
        else:
            phi_v = raw.get("phi_v", 0.9)
            ok(near(Tr, phi_v * Tn),
               f"Tr ({Tr:.1f}) should = φ_v·Tn ({phi_v}×{Tn:.1f})")
        # Combined shear+torsion check
        ok("comb_ok" in tor, "comb_ok should exist when torsion considered")
    else:
        # Torsion below threshold
        if abs(Tu) > 0:
            ok(abs(Tu) <= tor["thresh"] + 0.1,
               f"|Tu|={abs(Tu)} should be ≤ thresh={tor['thresh']:.1f} since not considered", warn_only=True)
    return True


def verify_service(res, raw, dem):
    fl = res["flexure"]
    d = dem[0]
    Ms = d.get("Ms", 0)

    ok("fss" in fl, "fss should be in flexure result")
    ok("c_cr" in fl, "c_cr should be in flexure result")
    ok("Icr" in fl, "Icr should be in flexure result")
    ok("curv" in fl, "curv should be in flexure result")
    ok("eps_rb" in fl, "eps_rb should be in flexure result")

    if Ms > 0:
        ok(fl["fss"] >= 0, f"fss should be ≥ 0 when Ms>0, got {fl['fss']:.2f}")
        # c_cr can be 0 for hogging with no tension steel
        has_tens_svc = fl["As"] > 0 or (N_safe(fl.get("Aps",0)) > 0)
        if has_tens_svc:
            ok(fl["c_cr"] > 0, f"c_cr should be > 0 when Ms>0, got {fl['c_cr']:.4f}")
            ok(fl["Icr"] > 0, f"Icr should be > 0 when Ms>0, got {fl['Icr']:.1f}")
            ok(fl["curv"] >= 0, f"curv should be \u2265 0 when Ms>0, got {fl['curv']}")

        # Hand-check service stress: fss = M_total*(ds-c_cr)/Icr * n + Ps*n/(nAs+nAps+c_cr*b)
        # Note: M_total includes addlBM from axial load eccentricity
        h = raw["h"]
        M_total = fl.get("M_serv", 0) + fl.get("addlBM", 0)
        if M_total > 0 and fl["c_cr"] > 0 and fl["Icr"] > 0 and has_tens_svc:
            n = fl.get("n_mod", 1)
            Ps_val = d.get("Ps", 0)
            b_sec = raw.get("b", 36)
            nAs_val = fl.get("nAs", 0)
            nAps_val = fl.get("nAps", 0)
            # Bending term
            fss_bend = M_total * (fl["ds"] - fl["c_cr"]) / fl["Icr"] * n
            # Axial term: direct stress from axial on cracked transformed section
            A_tr_cr = nAs_val + nAps_val + fl["c_cr"] * b_sec
            fss_axial = Ps_val / A_tr_cr * n if A_tr_cr > 0 else 0
            fss_check = fss_bend + fss_axial
            ok(near(fl["fss"], fss_check, tol=0.02),
               f"fss ({fl['fss']:.2f}) should match hand-calc ({fss_check:.2f})")

    # Ieff should be between Icr and Ig
    if fl.get("Ieff") and fl.get("Ig") and fl.get("Icr"):
        ok(fl["Icr"] <= fl["Ieff"] + 1,
           f"Ieff ({fl['Ieff']:.0f}) should be ≥ Icr ({fl['Icr']:.0f})", warn_only=True)
        ok(fl["Ieff"] <= fl["Ig"] + 1,
           f"Ieff ({fl['Ieff']:.0f}) should be ≤ Ig ({fl['Ig']:.0f})", warn_only=True)

    return True


def verify_row_results(res, demands):
    rr = res["row_results"]
    inp = res["inputs"]
    ok(len(rr) == len(demands), f"row_results count ({len(rr)}) should match demands count ({len(demands)})")

    for i, (r, d) in enumerate(zip(rr, demands)):
        # Determine if there is tension steel for this moment direction
        Mu_row = d["Mu"]
        if Mu_row >= 0:  # sagging – tension on bottom
            has_tens_row = inp["As_bot"] > 0 or (inp.get("Aps", 0) > 0 and inp.get("hasPT", False))
        else:            # hogging – tension on top
            has_tens_row = inp["As_top"] > 0 or (inp.get("Aps", 0) > 0 and inp.get("hasPT", False))

        # The engine intentionally signs row.Mr by Mu direction:
        #   Mr_signed = -Mr if Mu < 0 else Mr   (calc_engine.py:2842)
        # Compare magnitudes so the sign convention is respected.
        Mr_mag = abs(r["Mr"])
        if has_tens_row:
            ok(Mr_mag > 0, f"Row {i+1}: |Mr| should be > 0, got {r['Mr']:.1f}")
        else:
            ok(Mr_mag >= 0, f"Row {i+1}: |Mr| should be >= 0 (no tension steel for this Mu sign), got {r['Mr']:.1f}")
        ok(r.get("flexStatus") in ("OK", "MIN", "NG"),
           f"Row {i+1}: flexStatus should be OK/MIN/NG, got '{r.get('flexStatus')}'")
        ok(r.get("shearStatus") in ("OK", "NR", "NG"),
           f"Row {i+1}: shearStatus should be OK/NR/NG, got '{r.get('shearStatus')}'")
        ok(r.get("crackStatus") in ("OK", "NG"),
           f"Row {i+1}: crackStatus should be OK/NG, got '{r.get('crackStatus')}'")

        # Vr values should be positive (except B5 which may not converge)
        for vm in [1, 2]:
            ok(r.get(f"Vr{vm}", 0) > 0,
               f"Row {i+1}: Vr{vm} should be > 0, got {r.get(f'Vr{vm}',0):.1f}")
        # Method 3 (B5) may legitimately not converge
        ok(r.get("Vr3", 0) >= 0,
           f"Row {i+1}: Vr3 should be >= 0, got {r.get('Vr3',0):.1f}")
    return True


def verify_report_keys(res):
    """Check all keys used by generateReport() are present."""
    fl = res["flexure"]
    sh = res["shear"]
    tor = res["torsion"]
    inp = res["inputs"]

    # Flexure keys used in report
    for k in ["c", "a", "beta1", "alpha1", "phi_f", "Mn", "Mr", "Mr_atPu",
              "eps_t", "sec_status", "ds", "As", "As_comp", "d_s_comp",
              "comp_face", "dv", "de", "hf",
              "gamma1", "gamma3", "fr", "Sc", "Mcr", "Mcond", "min_flex_ok",
              "dc", "beta_s", "fss_simp", "s_crack", "s_min_ck", "s_max_ck",
              "c_cr", "Icr", "fss", "eps_rb", "curv", "Ieff", "Ig",
              "n_mod", "M_serv", "addlBM",
              "pm_data", "pm_curve",
              "c_ds_ratio", "c_ds_limit", "c_ds_ok",
              "phi_cc", "phi_tc", "phi_k"]:
        ok(k in fl, f"Flexure key '{k}' should exist in result")

    # Shear keys
    for k in ["dv", "bv", "Vnmax", "eps_s", "fpo",
              "th1", "bt1", "Vc1", "Vs1", "Vn1", "Vr1",
              "bt2", "th2", "Vc2", "Vs2", "Vn2", "Vr2",
              "th3", "bt3", "Vc3", "Vs3", "Vn3", "Vr3",
              "sh_reqd", "Av_min", "s_max_sh",
              "long_dem", "long_cap", "long_ok"]:
        ok(k in sh, f"Shear key '{k}' should exist in result")

    # Torsion keys
    for k in ["Tcr", "thresh", "consider", "pc", "Acp", "Ao", "ph"]:
        ok(k in tor, f"Torsion key '{k}' should exist in result")
    if tor.get("consider"):
        # AASHTO Eq. 5.7.3.6.3-1 combined longitudinal check is required.
        # Eq. 5.7.3.6.3-2 (Al_tors/Al_min/Al_gov) is box-only and
        # intentionally NOT computed by this app.
        for k in ["Tn", "Tr", "theta", "comb_ok", "comb_stress", "comb_lim",
                   "long_dem_comb", "long_cap_val", "long_comb_ok"]:
            ok(k in tor, f"Torsion key '{k}' (when considered) should exist")

    # Input keys
    for k in ["h", "b", "Ec", "Es", "cover", "dp", "isRect", "bw",
              "As_top", "As_bot", "d_top", "d_bot", "Aps", "hasPT",
              "hf_top", "hf_bot"]:
        ok(k in inp, f"Input key '{k}' should exist in result")

    return True


def verify_pm_consistency(res, raw):
    """Check P-M curve is self-consistent."""
    fl = res["flexure"]
    pm = fl.get("pm_curve", [])
    if not pm:
        return

    # Should have points from pure compression to pure tension
    Pr_vals = [p["Pr"] for p in pm]
    ok(max(Pr_vals) > 0, f"P-M curve should have compression (Pr>0), max Pr = {max(Pr_vals):.0f}", warn_only=True)
    # Note: min Pr could be tensile (negative) or could be 0
    ok(any(abs(p["Mr"]) > 0 for p in pm), "P-M curve should have non-zero |Mr| somewhere")

    # φ should be between limits
    for i, p in enumerate(pm):
        if p.get("phi"):
            ok(0 < p["phi"] <= 1.0,
               f"PM point {i}: phi ({p['phi']:.4f}) should be 0 < φ ≤ 1.0")

    # Pr and Mr should be φ × Pn and φ × Mn
    for i, p in enumerate(pm):
        if p.get("phi") and p.get("Pn") is not None:
            ok(near(p["Pr"], p["phi"] * p["Pn"], tol=0.01),
               f"PM point {i}: Pr ({p['Pr']:.1f}) should = φ·Pn ({p['phi']:.4f}×{p['Pn']:.1f})")
            ok(near(p["Mr"], p["phi"] * p["Mn"], tol=0.01),
               f"PM point {i}: Mr ({p['Mr']:.1f}) should = φ·Mn ({p['phi']:.4f}×{p['Mn']:.1f})")


def verify_isection_geometry(res, raw):
    """Check I-section geom properties are correct."""
    tor = res["torsion"]
    inp = res["inputs"]
    h = raw["h"]
    b = raw["b"]
    bw = raw["bw_input"]
    hf_top = raw["hf_top"]
    hf_bot = raw["hf_bot"]

    Ag_exp = b * hf_top + bw * (h - hf_top - hf_bot) + b * hf_bot
    pc_exp = 2 * (b + hf_top) + 2 * (bw + (h - hf_top - hf_bot)) + 2 * (b + hf_bot) - 2 * bw

    ok(not inp["isRect"], "I-section should have isRect=False")
    ok(inp["bw"] == bw, f"bw should be {bw}, got {inp['bw']}")

    # Torsion Acp
    if tor.get("Acp"):
        ok(near(tor["Acp"], Ag_exp, tol=0.02),
           f"Acp ({tor['Acp']:.1f}) should ≈ Ag ({Ag_exp:.1f})")


# ─── HAND-CALC SPOT CHECKS ───────────────────────────────────────────────────

def spot_check_rect_simple():
    """Rect 36×36, 4#8 bot, fc=4, fy=60: hand-calc Mn."""
    print("\n  [Spot Check: Rectangular simple Mn]")
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4)
    demands = [{"Pu":0, "Mu":1000, "Vu":0, "Tu":0, "Vp":0, "Ms":0, "Ps":0}]
    res = calculate_all(raw, demands, 0)
    fl = res["flexure"]

    As = 4 * BARS[8]["a"]  # 4 × 0.79 = 3.16 in²
    fc, fy, b, h = 4, 60, 36, 36
    beta1 = 0.85
    alpha1 = 0.85
    d_bot = fl["ds"]
    a = As * fy / (alpha1 * fc * b)
    c = a / beta1
    Mn = As * fy * (d_bot - a / 2)
    eps_t = 0.003 * (d_bot - c) / c
    phi = min(0.9, 0.75 + 0.15 * (eps_t - 0.002) / 0.003) if eps_t >= 0.002 else 0.75
    phi = max(0.75, min(0.9, phi))

    print(f"    Hand: As={As:.3f}, ds={d_bot:.3f}, a={a:.4f}, c={c:.4f}")
    print(f"    Hand: Mn={Mn:.1f}, εt={eps_t:.6f}, φ={phi:.4f}, Mr={phi*Mn:.1f}")
    print(f"    Engine: Mn={fl['Mn']:.1f}, εt={fl['eps_t']:.6f}, φ={fl['phi_f']:.4f}, Mr={fl['Mr']:.1f}")

    ok(near(fl["Mn"], Mn, tol=0.005), f"Mn hand ({Mn:.1f}) vs engine ({fl['Mn']:.1f})")
    ok(near(fl["phi_f"], phi, tol=0.005), f"phi hand ({phi:.4f}) vs engine ({fl['phi_f']:.4f})")


def spot_check_rect_doubly():
    """Rect 36×36, 4#8 bot + 4#8 top, Mu < 0 (hogging): check comp_face=bottom."""
    print("\n  [Spot Check: Hogging — comp face = bottom]")
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4)
    demands = [{"Pu":0, "Mu":-3000, "Vu":0, "Tu":0, "Vp":0, "Ms":0, "Ps":0}]
    res = calculate_all(raw, demands, 0)
    fl = res["flexure"]

    ok(fl["comp_face"] == "bottom", f"Hogging should give comp_face='bottom', got '{fl['comp_face']}'")
    # For symmetric section (same top&bot bars), Mr should be same as sagging
    demands_pos = [{"Pu":0, "Mu":3000, "Vu":0, "Tu":0, "Vp":0, "Ms":0, "Ps":0}]
    res_pos = calculate_all(raw, demands_pos, 0)
    fl_pos = res_pos["flexure"]
    ok(near(fl["Mr"], fl_pos["Mr"], tol=0.01),
       f"Symmetric section: sagging Mr ({fl_pos['Mr']:.1f}) should ≈ hogging Mr ({fl['Mr']:.1f})")


def spot_check_shear_method1():
    """Hand-check simplified shear (θ=45°)."""
    print("\n  [Spot Check: Shear Method 1 — θ=45°]")
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4, shN=4, shear_legs=2, s_shear=12)
    demands = [{"Pu":0, "Mu":2000, "Vu":100, "Tu":0, "Vp":0, "Ms":0, "Ps":0}]
    res = calculate_all(raw, demands, 0)
    sh = res["shear"]
    fl = res["flexure"]

    fc, b_v, dv = 4, sh["bv"], sh["dv"]
    lam = raw["lam"]
    # Method 1: β=2.0, θ=45°
    Vc1 = 0.0316 * 2.0 * lam * math.sqrt(fc) * b_v * dv
    Av = 2 * BARS[4]["a"]  # 2 legs of #4
    s = 12
    Vs1 = Av * 60 * dv / s  # cot(45)=1
    Vn1 = Vc1 + Vs1
    phi_v = 0.9
    Vr1 = phi_v * Vn1

    print(f"    Hand: bv={b_v:.2f}, dv={dv:.3f}, Vc1={Vc1:.1f}, Vs1={Vs1:.1f}, Vn1={Vn1:.1f}, Vr1={Vr1:.1f}")
    print(f"    Engine: Vc1={sh['Vc1']:.1f}, Vs1={sh['Vs1']:.1f}, Vn1={sh['Vn1']:.1f}, Vr1={sh['Vr1']:.1f}")

    ok(near(sh["Vc1"], Vc1, tol=0.02), f"Vc1 hand ({Vc1:.1f}) vs engine ({sh['Vc1']:.1f})")
    ok(near(sh["Vs1"], Vs1, tol=0.02), f"Vs1 hand ({Vs1:.1f}) vs engine ({sh['Vs1']:.1f})")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    global PASS, FAIL, WARN
    print("=" * 80)
    print("  FULL VERIFICATION — AASHTO Calc Engine")
    print("  All Permutations: Rect/I × Bot/TopBot × PT/NoPT × Sag/Hog/Axial")
    print("=" * 80)

    # ─── Phase 1: Spot checks ───
    print("\n" + "─" * 60)
    print("  PHASE 1: Hand-Calculation Spot Checks")
    print("─" * 60)
    spot_check_rect_simple()
    spot_check_rect_doubly()
    spot_check_shear_method1()

    # ─── Phase 2: Full matrix ───
    print("\n" + "─" * 60)
    print("  PHASE 2: Full Permutation Matrix")
    print("─" * 60)

    total_combos = 0
    error_combos = []

    for sec_name, sec_kwargs in SECTIONS.items():
        desc = sec_kwargs.pop("desc", sec_name)
        for dem_name, dem_list in DEMANDS.items():
            combo_name = f"{sec_name} × {dem_name}"
            total_combos += 1
            print(f"\n  ▸ {combo_name}")
            print(f"    {desc}")

            try:
                raw = make_inputs(**sec_kwargs)
                active = 0
                res = calculate_all(raw, dem_list, active)

                verify_flexure(res, raw, dem_list)
                verify_shear(res, raw, dem_list)
                verify_torsion(res, raw, dem_list)
                verify_service(res, raw, dem_list)
                verify_row_results(res, dem_list)
                verify_report_keys(res)
                verify_pm_consistency(res, raw)

                # I-section geometry check
                if sec_kwargs.get("secType") == "T-SECTION":
                    verify_isection_geometry(res, raw)

            except Exception as e:
                FAIL += 1
                error_combos.append(combo_name)
                print(f"    ✗ EXCEPTION: {e}")
                traceback.print_exc()

        # Re-add desc for next iteration
        sec_kwargs["desc"] = desc

    # ─── Phase 3: Symmetric section consistency ───
    print("\n" + "─" * 60)
    print("  PHASE 3: Consistency Checks")
    print("─" * 60)

    # Sagging Mr == Hogging Mr for symmetric section
    print("\n  [Symmetry: Rect_TopBot, sagging vs hogging]")
    raw_sym = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4)
    dem_sag = [{"Pu":0, "Mu":3000, "Vu":100, "Tu":0, "Vp":0, "Ms":1500, "Ps":0}]
    dem_hog = [{"Pu":0, "Mu":-3000, "Vu":100, "Tu":0, "Vp":0, "Ms":1500, "Ps":0}]
    res_sag = calculate_all(raw_sym, dem_sag, 0)
    res_hog = calculate_all(raw_sym, dem_hog, 0)
    ok(near(res_sag["flexure"]["Mr"], res_hog["flexure"]["Mr"], tol=0.01),
       f"Symmetric Mr: sag={res_sag['flexure']['Mr']:.1f} vs hog={res_hog['flexure']['Mr']:.1f}")
    ok(near(res_sag["shear"]["Vr2"], res_hog["shear"]["Vr2"], tol=0.05),
       f"Symmetric Vr2: sag={res_sag['shear']['Vr2']:.1f} vs hog={res_hog['shear']['Vr2']:.1f}")

    # More compression → more Vr (concrete contribution increases)
    print("\n  [Compression increases shear capacity]")
    raw_sh = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4)
    dem_no_P = [{"Pu":0, "Mu":2000, "Vu":100, "Tu":0, "Vp":0, "Ms":0, "Ps":0}]
    dem_comp = [{"Pu":-300, "Mu":2000, "Vu":100, "Tu":0, "Vp":0, "Ms":0, "Ps":0}]
    res_noP = calculate_all(raw_sh, dem_no_P, 0)
    res_comp = calculate_all(raw_sh, dem_comp, 0)
    ok(res_comp["shear"]["Vr2"] >= res_noP["shear"]["Vr2"] - 1,
       f"Compression should help shear: Vr2(P=-300)={res_comp['shear']['Vr2']:.1f} vs Vr2(P=0)={res_noP['shear']['Vr2']:.1f}",
       warn_only=True)

    # I-section: flange overhangs should increase Mn vs web-only
    print("\n  [I-section flange contributes to Mn]")
    raw_rect_small = make_inputs(h=36, b=12, barN_bot=8, nBars_bot=4)
    raw_i = make_inputs(h=36, b=36, secType="T-SECTION", bw_input=12, hf_top=8, hf_bot=8,
                         barN_bot=8, nBars_bot=4)
    dem_mn = [{"Pu":0, "Mu":2000, "Vu":0, "Tu":0, "Vp":0, "Ms":0, "Ps":0}]
    res_rect = calculate_all(raw_rect_small, dem_mn, 0)
    res_i = calculate_all(raw_i, dem_mn, 0)
    # The I-section with wider flanges should have same or greater Mn
    # (since stress block usually fits in flange, Mn may be same;
    #  but for deep stress blocks it's higher)
    print(f"    Rect (b=12): Mn={res_rect['flexure']['Mn']:.1f}")
    print(f"    I-sect (b=36, bw=12): Mn={res_i['flexure']['Mn']:.1f}")
    ok(res_i["flexure"]["Mn"] >= res_rect["flexure"]["Mn"] - 1,
       f"I-section Mn should be ≥ rect(bw) Mn")

    # ─── Summary ───
    print("\n" + "=" * 80)
    print(f"  RESULTS:  {PASS} passed / {FAIL} failed / {WARN} warnings")
    print(f"  Total permutation combos tested: {total_combos}")
    if error_combos:
        print(f"  Exception combos: {error_combos}")
    if FAIL == 0:
        print("  ✓ ALL CHECKS PASSED")
    else:
        print(f"  ✗ {FAIL} CHECK(S) FAILED — review above")
    print("=" * 80)
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
