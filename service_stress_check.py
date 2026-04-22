"""
Service Stress (fss) Verification
Compare calc_engine fss against hand-calculated elastic cracked section analysis.

Section 3 from AdSec comparison: 36x36 RC, 4 #8 bot + 4 #8 top, f'c=4 ksi, fy=60 ksi
"""
import math, sys
sys.path.insert(0, ".")
from calc_engine import calculate_all, BARS

def make_inputs(h, b, fc, fy, barN_bot, nBars_bot, barN_top, nBars_top,
                cover=2.0, shN=4, Es=29000, nStrands=0, strand_area=0, dp=0):
    Ec = 2500 * fc ** 0.33
    bar_bot = BARS.get(barN_bot, BARS[7])
    bar_top = BARS.get(barN_top, None)
    # Include stirrup diameter in d calculation
    stir = BARS.get(shN, BARS[4])
    db_stir = stir["d"]
    d_bot = h - cover - db_stir - bar_bot["d"] / 2
    d_top = cover + db_stir + (bar_top["d"] / 2 if bar_top else 0) if nBars_top > 0 else cover
    return dict(
        fc=fc, fy=fy, Ec=Ec, Es=Es, fpu=270, fpy=243, Ept=28500,
        ecl=0, etl=0, ecl_override=False, etl_override=False,
        ag=0.75, lam=1.0, phi_v=0.9, gamma_e=0.75,
        codeEdition="AASHTO", sectionClass="RC",
        secType="RECTANGULAR", b=b, h=h, bw_input=b,
        hf_top=0, hf_bot=0, cover=cover,
        barN_bot=barN_bot, nBars_bot=nBars_bot, d_bot=d_bot,
        barN_top=barN_top, nBars_top=nBars_top, d_top=d_top,
        nStrands=nStrands, strand_area=strand_area, dp=dp, ductDia=0,
        shN=shN, shear_legs=2, s_shear=12, tN=shN, s_torsion=12,
    )

def hand_calc_fss(b, h, ds, d_top, As, As_comp, Es, Ec, Ms, Ps=0):
    """
    Hand-compute fss for doubly-reinforced rectangular section.
    Cracked elastic analysis (transformed section).
    """
    n = Es / Ec
    print(f"\n  ── Hand Calculation ──")
    print(f"  b = {b}, h = {h}, ds = {ds:.4f}, d' = {d_top:.4f}")
    print(f"  As = {As:.3f} in², A's = {As_comp:.3f} in²")
    print(f"  Es = {Es}, Ec = {Ec:.1f}")
    print(f"  n = Es/Ec = {n:.4f}")

    nAs = n * As
    nAs_comp = (2*n - 1) * As_comp  # transformed compression steel (2n-1 for doubly reinforced)
    # Note: Our engine uses nAs only (no compression steel in cracked section).
    # Let's compute both ways.

    # --- Method A: Tension steel only (matches engine for RC without compression steel) ---
    print(f"\n  Method A: Tension steel only (n*As)")
    qa = b / 2
    qb = nAs
    qc = -nAs * ds
    disc = qb**2 - 4*qa*qc
    c_cr_A = (-qb + math.sqrt(disc)) / (2*qa)
    Icr_A = b * c_cr_A**3 / 3 + nAs * (ds - c_cr_A)**2
    M = abs(Ms)
    fss_A = M * (ds - c_cr_A) / Icr_A * n
    print(f"  c_cr = {c_cr_A:.4f} in")
    print(f"  Icr  = {Icr_A:.1f} in⁴")
    print(f"  fss  = M*(ds-c)/Icr*n = {M:.1f}*({ds:.4f}-{c_cr_A:.4f})/{Icr_A:.1f}*{n:.4f}")
    print(f"  fss  = {fss_A:.4f} ksi")

    # --- Method B: Doubly-reinforced (tension + compression steel) ---
    print(f"\n  Method B: Doubly-reinforced (tension + compression steel)")
    qa2 = b / 2
    qb2 = nAs + nAs_comp
    qc2 = -(nAs * ds + nAs_comp * d_top)
    disc2 = qb2**2 - 4*qa2*qc2
    c_cr_B = (-qb2 + math.sqrt(disc2)) / (2*qa2)
    Icr_B = (b * c_cr_B**3 / 3
             + nAs * (ds - c_cr_B)**2
             + nAs_comp * (c_cr_B - d_top)**2)
    fss_B = M * (ds - c_cr_B) / Icr_B * n
    print(f"  (2n-1)*A's = {nAs_comp:.4f}")
    print(f"  c_cr = {c_cr_B:.4f} in")
    print(f"  Icr  = {Icr_B:.1f} in⁴")
    print(f"  fss  = {fss_B:.4f} ksi")

    return fss_A, fss_B, c_cr_A, Icr_A


def run_test(label, b, h, fc, fy, barN_bot, nBars_bot, barN_top, nBars_top,
             Ms_vals, cover=2.0, shN=4):
    print("\n" + "="*80)
    print(f"  {label}")
    print("="*80)

    raw = make_inputs(h=h, b=b, fc=fc, fy=fy,
                      barN_bot=barN_bot, nBars_bot=nBars_bot,
                      barN_top=barN_top, nBars_top=nBars_top,
                      cover=cover, shN=shN)
    Es = raw["Es"]
    Ec = raw["Ec"]
    bar_bot = BARS[barN_bot]
    bar_top = BARS.get(barN_top, None)
    As = nBars_bot * bar_bot["a"]
    As_comp = nBars_top * bar_top["a"] if bar_top and nBars_top > 0 else 0

    print(f"  Section: {b}\" x {h}\", f'c={fc} ksi, fy={fy} ksi")
    print(f"  Bottom: {nBars_bot}-#{barN_bot}  (As = {As:.3f} in²)")
    print(f"  Top:    {nBars_top}-#{barN_top}  (A's = {As_comp:.3f} in²)")
    print(f"  cover = {cover}\", d_bot = {raw['d_bot']:.4f}\", d_top = {raw['d_top']:.4f}\"")
    print(f"  Ec = 2500*f'c^0.33 = {Ec:.1f} ksi")

    for Ms in Ms_vals:
        print(f"\n  {'─'*60}")
        print(f"  Service Moment Ms = {Ms:.1f} kip-in")
        print(f"  {'─'*60}")

        demands = [{"Pu": 0, "Mu": Ms, "Vu": 0, "Tu": 0, "Vp": 0, "Ms": Ms, "Ps": 0}]
        res = calculate_all(raw, demands, 0)
        fl = res["flexure"]

        # Engine results
        eng_fss = fl.get("fss", 0)
        eng_ccr = fl.get("c_cr", 0)
        eng_Icr = fl.get("Icr", 0)

        print(f"\n  ── Calc Engine Results ──")
        print(f"  c_cr = {eng_ccr:.4f} in")
        print(f"  Icr  = {eng_Icr:.1f} in⁴")
        print(f"  fss  = {eng_fss:.4f} ksi")

        # Hand calc
        fss_A, fss_B, c_hand, Icr_hand = hand_calc_fss(
            b, h, raw["d_bot"], raw["d_top"], As, As_comp, Es, Ec, Ms)

        # Compare
        print(f"\n  ── Comparison ──")
        diff_A = abs(eng_fss - fss_A)
        diff_B = abs(eng_fss - fss_B)
        print(f"  Engine fss       = {eng_fss:.4f} ksi")
        print(f"  Hand (tens only) = {fss_A:.4f} ksi   diff = {diff_A:.4f}")
        print(f"  Hand (doubly)    = {fss_B:.4f} ksi   diff = {diff_B:.4f}")
        pct_A = diff_A / fss_A * 100 if fss_A > 0 else 0
        pct_B = diff_B / fss_B * 100 if fss_B > 0 else 0
        print(f"  % diff (tens)    = {pct_A:.2f}%")
        print(f"  % diff (doubly)  = {pct_B:.2f}%")
        if diff_A < 0.01:
            print(f"  ✓ MATCH (tension-only model)")
        elif diff_B < 0.01:
            print(f"  ✓ MATCH (doubly-reinforced model)")
        else:
            print(f"  ✗ MISMATCH — investigate")


if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════════════════════════════════╗")
    print("║         Service Stress (fss) Verification — Hand Calc vs Engine            ║")
    print("╚══════════════════════════════════════════════════════════════════════════════╝")

    # Test 1: Simple RC, singly reinforced (bottom bars only)
    run_test("TEST 1: Singly Reinforced — 36x36, 4 #8 bot, f'c=4, fy=60",
             b=36, h=36, fc=4, fy=60,
             barN_bot=8, nBars_bot=4, barN_top=0, nBars_top=0,
             Ms_vals=[500, 1000, 2000, 3000])

    # Test 2: Doubly reinforced (top + bottom bars)
    run_test("TEST 2: Doubly Reinforced — 36x36, 4 #8 bot + 4 #8 top, f'c=4, fy=60",
             b=36, h=36, fc=4, fy=60,
             barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4,
             Ms_vals=[500, 1000, 2000, 3000])

    # Test 3: Different geometry — 16x28, 6 #7
    run_test("TEST 3: Singly Reinforced — 16x28, 6 #7 bot, f'c=5, fy=60",
             b=16, h=28, fc=5, fy=60,
             barN_bot=7, nBars_bot=6, barN_top=0, nBars_top=0,
             Ms_vals=[200, 500, 1000])

    # Test 4: Light reinforcement
    run_test("TEST 4: Light Reinforcement — 12x24, 3 #5 bot, f'c=4, fy=60",
             b=12, h=24, fc=4, fy=60,
             barN_bot=5, nBars_bot=3, barN_top=0, nBars_top=0,
             Ms_vals=[100, 200, 400])
