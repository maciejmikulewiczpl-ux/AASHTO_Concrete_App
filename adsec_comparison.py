"""
Compare AdSec model sections with our AASHTO calc_engine.
AdSec sign convention mapping:
  - AdSec positive fx = tension = our positive Pu
  - AdSec positive Myy = hogging (tension at top via right-hand rule)
    => our Mu = -AdSec_Myy
  - AdSec negative Myy = sagging (compression at top)
    => our Mu = +|AdSec_Myy|
"""
import math, sys, json
sys.path.insert(0, ".")
from calc_engine import calculate_all, build_pm_curve, get_mr_at_pu, derive_constants, do_flexure, get_phi_flex

# ─── Helper: build raw_inputs dict (same keys as gatherInputs in JS) ──────
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
    if d_bot is None:
        from calc_engine import BARS
        bar = BARS.get(barN_bot, BARS[7])
        d_bot = h - cover - bar["d"] / 2
    if d_top is None:
        from calc_engine import BARS
        bar_t = BARS.get(barN_top, None)
        d_top = cover + (bar_t["d"] / 2 if bar_t else 0)
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


def print_section_header(name, desc):
    print("\n" + "=" * 80)
    print(f"  {name}")
    print(f"  {desc}")
    print("=" * 80)


def print_flexure_detail(res, Pu, Mu, label=""):
    fl = res["flexure"]
    inp = res["inputs"]
    print(f"\n  --- {label} (Pu={Pu:+.1f} kip, Mu={Mu:+.1f} kip-in) ---")
    print(f"  Compression face : {fl['comp_face']}")
    print(f"  Tension steel    : As = {fl['As']:.3f} in²  (ds = {fl['ds']:.3f} in)")
    print(f"  Compression steel: A's = {fl['As_comp']:.3f} in²  (d's = {fl.get('d_s_comp',0):.3f} in)")
    print(f"  Neutral axis c   : {fl['c']:.3f} in")
    print(f"  Stress block a   : {fl['a']:.3f} in")
    if inp["hasPT"]:
        print(f"  fps (calc)       : {fl['fps_calc']:.1f} ksi")
    print(f"  Mn (nominal)     : {fl['Mn']:.1f} kip-in")
    print(f"  φ (flexure)      : {fl['phi_f']:.4f}")
    print(f"  Mr = φ·Mn        : {fl['Mr']:.1f} kip-in")
    print(f"  εt (tension)     : {fl['eps_t']:.6f}")
    print(f"  Section status   : {fl['sec_status']}")
    print(f"  Mr at Pu (P-M)   : {fl['Mr_atPu']:.1f} kip-in")
    demand_ratio = abs(Mu) / fl['Mr'] if fl['Mr'] > 0 else float('inf')
    pm_ratio = abs(Mu) / fl['Mr_atPu'] if fl['Mr_atPu'] > 0 else float('inf')
    print(f"  |Mu|/Mr (pure M) : {demand_ratio:.3f}")
    print(f"  |Mu|/Mr@Pu (P-M) : {pm_ratio:.3f}")
    # dv
    print(f"  dv               : {fl.get('dv',0):.3f} in")
    print(f"  de               : {fl.get('de',0):.3f} in")


def print_row_summary(row_results, demand_rows):
    print(f"\n  {'Row':>3}  {'Pu':>8}  {'Mu':>10}  {'Mr@Pu':>10}  {'|Mu|/Mr':>8}  {'Flex':>5}  {'Shear':>6}")
    print(f"  {'---':>3}  {'---':>8}  {'---':>10}  {'---':>10}  {'---':>8}  {'---':>5}  {'---':>6}")
    for i, (rr, dr) in enumerate(zip(row_results, demand_rows)):
        Pu = dr.get("Pu", 0)
        Mu = dr.get("Mu", 0)
        Mr = rr["Mr"]
        ratio = abs(Mu) / Mr if Mr > 0 else float('inf')
        print(f"  {i+1:>3}  {Pu:>+8.1f}  {Mu:>+10.1f}  {Mr:>10.1f}  {ratio:>8.3f}  {rr['flexStatus']:>5}  {rr['shearStatus']:>6}")


# ==============================================================================
# SECTION 1: Rectangular RC beam — 60" x 24", 5 #5 bot, 1 PT tendon
# ==============================================================================
def run_section_1():
    print_section_header(
        "SECTION 1: Rectangular RC beam (60\" x 24\")",
        "5 #5 Grade 60 bot bars, 1 PT tendon (Aps=1.086 in², dp=48\" from top)"
    )
    # Tendon: diameter 1.1754" → area = π/4 × 1.1754² = 1.0856 in²
    Aps = math.pi / 4 * 1.1754**2
    print(f"  Aps = π/4 × 1.1754² = {Aps:.4f} in²")

    raw = make_inputs(
        h=60, b=24, fc=4, fy=60,
        barN_bot=5, nBars_bot=5,   # 5 #5 bars
        barN_top=0, nBars_top=0,   # no top bars
        nStrands=1, strand_area=Aps, dp=48,  # tendon at 48" from top
        cover=2.0,
        codeEdition="AASHTO", sectionClass="CIP_PT",
    )

    # AdSec Load Case 1: Myy = -1,242,833 N·m ≈ -11,000 kip·in (sagging)
    # Our Mu = +11,000 kip·in
    demands_1 = [
        {"Pu": 0, "Mu": 11000, "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
        {"Pu": 0, "Mu": 0,     "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
    ]
    res = calculate_all(raw, demands_1, 0)
    print_flexure_detail(res, 0, 11000, "Case 1: Sagging Mu = +11,000 kip-in")
    print_row_summary(res["row_results"], demands_1)
    return res


# ==============================================================================
# SECTION 2: Rectangular — 36" x 36", 4 #8 bot, 1 PT tendon
# ==============================================================================
def run_section_2():
    print_section_header(
        "SECTION 2: Rectangular (36\" x 36\")",
        "4 #8 Grade 60 bot bars, 1 PT tendon (Aps=3.142 in², dp=28\" from top)"
    )
    Aps = math.pi / 4 * 2.0**2
    print(f"  Aps = π/4 × 2² = {Aps:.4f} in²")

    raw = make_inputs(
        h=36, b=36, fc=4, fy=60,
        barN_bot=8, nBars_bot=4,   # 4 #8 bars
        barN_top=0, nBars_top=0,   # no top bars
        nStrands=1, strand_area=Aps, dp=28,
        cover=2.0,
        codeEdition="AASHTO", sectionClass="CIP_PT",
    )

    # AdSec loads (converting):
    # Case 1: fx=+10 kip (tension), Myy=0  → Pu=+10, Mu=0
    # Case 2: fx=+5 kip, Myy=0  → Pu=+5, Mu=0
    # Case 3: fx=0, Myy=-2500 kip·in (sagging)  → Pu=0, Mu=+2500
    # Case 4: fx=+100 kip, Myy=-2500  → Pu=+100, Mu=+2500
    # Case 5: fx=-100 kip, Myy=-2500  → Pu=-100, Mu=+2500
    demands_2 = [
        {"Pu": 10,   "Mu": 0,    "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
        {"Pu": 5,    "Mu": 0,    "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
        {"Pu": 0,    "Mu": 2500, "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
        {"Pu": 100,  "Mu": 2500, "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
        {"Pu": -100, "Mu": 2500, "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
    ]
    res = calculate_all(raw, demands_2, 2)  # active row = case 3 for detail
    print_flexure_detail(res, 0, 2500, "Case 3: Pu=0, Mu=+2500 (sagging)")
    print_row_summary(res["row_results"], demands_2)

    # Also print P-M curve key points
    pm = res["flexure"]["pm_curve"]
    print(f"\n  P-M Interaction Curve (40-point):")
    print(f"  {'Pr (kip)':>12}  {'Mr (kip-in)':>12}")
    for pt in pm:
        print(f"  {pt['Pr']:>12.1f}  {pt['Mr']:>12.1f}")
    return res


# ==============================================================================
# SECTION 3: Rectangular — 36" x 36", 4 #8 bot + 4 #8 top, NO PT
# ==============================================================================
def run_section_3():
    print_section_header(
        "SECTION 3: Rectangular (36\" x 36\") — No prestress",
        "4 #8 Grade 60 bot bars + 4 #8 Grade 60 top bars"
    )

    raw = make_inputs(
        h=36, b=36, fc=4, fy=60,
        barN_bot=8, nBars_bot=4,   # 4 #8 bottom
        barN_top=8, nBars_top=4,   # 4 #8 top
        nStrands=0, strand_area=0, dp=0,
        cover=2.0,
        codeEdition="AASHTO", sectionClass="RC",
    )

    # AdSec loads:
    # Case 1: fx=+10 kip, Myy=0       → Pu=+10, Mu=0
    # Case 2: fx=+10, Myy=+1000 (hog) → Pu=+10, Mu=-1000
    # Case 3: fx=+10, Myy=+5000 (hog) → Pu=+10, Mu=-5000
    demands_3 = [
        {"Pu": 10, "Mu": 0,     "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
        {"Pu": 10, "Mu": -1000, "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
        {"Pu": 10, "Mu": -5000, "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
    ]

    # Detail for Case 2 (negative moment — hogging)
    res2 = calculate_all(raw, demands_3, 1)
    print_flexure_detail(res2, 10, -1000, "Case 2: Pu=+10, Mu=-1000 (hogging)")

    # Detail for Case 3 (negative moment — hogging, near capacity)
    res3 = calculate_all(raw, demands_3, 2)
    print_flexure_detail(res3, 10, -5000, "Case 3: Pu=+10, Mu=-5000 (hogging)")

    # Row summary using case 2 as active
    print_row_summary(res2["row_results"], demands_3)

    # Also check positive moment (for symmetric section, should give same Mr)
    demands_pos = [
        {"Pu": 10, "Mu": 1000, "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
        {"Pu": 10, "Mu": 5000, "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
    ]
    res_pos = calculate_all(raw, demands_pos, 0)
    print(f"\n  [Symmetry check: Positive moment]")
    print_flexure_detail(res_pos, 10, 1000, "Pos Case: Pu=+10, Mu=+1000 (sagging)")

    # P-M curve
    pm = res2["flexure"]["pm_curve"]
    print(f"\n  P-M Interaction Curve (40-point):")
    print(f"  {'Pr (kip)':>12}  {'Mr (kip-in)':>12}")
    for pt in pm:
        print(f"  {pt['Pr']:>12.1f}  {pt['Mr']:>12.1f}")
    return res2


# ==============================================================================
# SECTION 4: I-Section — 36" x 36", bw=12", flanges=8",
#             4 #8 bot + 4 #8 top + 1 PT tendon
# ==============================================================================
def run_section_4():
    print_section_header(
        "SECTION 4: I-Section (36\" x 36\", bw=12\", flanges=8\")",
        "4 #8 bot + 4 #8 top, 1 PT tendon (Aps=3.142 in², dp=28\" from top)"
    )
    Aps = math.pi / 4 * 2.0**2
    print(f"  Aps = π/4 × 2² = {Aps:.4f} in²")

    raw = make_inputs(
        h=36, b=36, fc=4, fy=60,
        secType="T-SECTION",
        bw_input=12, hf_top=8, hf_bot=8,
        barN_bot=8, nBars_bot=4,   # 4 #8 bottom
        barN_top=8, nBars_top=4,   # 4 #8 top
        nStrands=1, strand_area=Aps, dp=28,
        cover=2.0,
        codeEdition="AASHTO", sectionClass="CIP_PT",
    )

    # Same loads as Section 2:
    # Case 1: Pu=+10, Mu=0
    # Case 2: Pu=+5, Mu=0
    # Case 3: Pu=0,   Mu=+2500 (sagging)
    # Case 4: Pu=+100, Mu=+2500
    # Case 5: Pu=-100, Mu=+2500
    demands_4 = [
        {"Pu": 10,   "Mu": 0,    "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
        {"Pu": 5,    "Mu": 0,    "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
        {"Pu": 0,    "Mu": 2500, "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
        {"Pu": 100,  "Mu": 2500, "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
        {"Pu": -100, "Mu": 2500, "Vu": 0, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0},
    ]
    # Active row = case 3
    res = calculate_all(raw, demands_4, 2)
    print_flexure_detail(res, 0, 2500, "Case 3: Pu=0, Mu=+2500 (sagging)")
    print_row_summary(res["row_results"], demands_4)

    # P-M curve
    pm = res["flexure"]["pm_curve"]
    print(f"\n  P-M Interaction Curve (40-point):")
    print(f"  {'Pr (kip)':>12}  {'Mr (kip-in)':>12}")
    for pt in pm:
        print(f"  {pt['Pr']:>12.1f}  {pt['Mr']:>12.1f}")

    # Section geometry check
    fl = res["flexure"]
    inp = res["inputs"]
    print(f"\n  I-Section Properties:")
    print(f"  isRect = {inp['isRect']}, bw = {inp['bw']}")
    print(f"  hf_top = {fl.get('hf', 0)}, hf_bot = {raw['hf_bot']}")
    Ag = raw["b"] * raw["hf_top"] + raw["bw_input"] * (raw["h"] - raw["hf_top"] - raw["hf_bot"]) + raw["b"] * raw["hf_bot"]
    print(f"  Ag = {Ag:.1f} in²")
    return res


# ==============================================================================
# MAIN
# ==============================================================================
if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════════════════════════════════╗")
    print("║           AdSec vs AASHTO Calc Engine — Comparison Report                  ║")
    print("╚══════════════════════════════════════════════════════════════════════════════╝")
    print()
    print("Sign convention mapping:")
    print("  AdSec  Myy(pos) = hogging  →  Our Mu = -Myy (negative)")
    print("  AdSec  Myy(neg) = sagging  →  Our Mu = +|Myy| (positive)")
    print("  AdSec  fx(pos)  = tension  →  Our Pu = +fx (positive)")
    print("  AdSec  fx(neg)  = compress →  Our Pu = fx (negative)")
    print()

    run_section_1()
    run_section_2()
    run_section_3()
    run_section_4()

    print("\n" + "=" * 80)
    print("  COMPARISON COMPLETE")
    print("  Note: Our app uses Whitney stress block (AASHTO simplified).")
    print("  AdSec uses fiber-based strain compatibility, which may give")
    print("  slightly different c, Mn, phi values. Material models also differ")
    print("  (our fpy=243 ksi vs AdSec fpy=245 ksi for Grade 270).")
    print("=" * 80)
