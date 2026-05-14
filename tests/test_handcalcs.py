"""
Hand-calculation golden references.

These tests independently compute key AASHTO quantities from first
principles and compare against the engine output. They are the strongest
defense against silent formula drift -- a refactor that accidentally
changes a coefficient anywhere will break one of these tests.

If a test in this file fails, treat it as a calculation-engine
regression and review the responsible commit before shipping.
"""
import math
import pytest

from tests.fixtures import make_inputs, demand
from calc_engine import BARS, calculate_all


# ─── 1. Singly-reinforced rectangular Mn ──────────────────────────────

def test_singly_reinforced_rect_Mn():
    """Hand calc: a = As*fy / (alpha1 * fc * b); Mn = As*fy * (d - a/2)."""
    raw = make_inputs(h=36, b=36, fc=4, fy=60, barN_bot=8, nBars_bot=4)
    res = calculate_all(raw, [demand(Mu=1000)], 0)
    fl = res["flexure"]

    As = 4 * BARS[8]["a"]  # 3.16 in^2
    fc, fy, b = 4, 60, 36
    alpha1 = 0.85
    d_bot = fl["ds"]
    a = As * fy / (alpha1 * fc * b)
    Mn = As * fy * (d_bot - a / 2)

    assert math.isclose(fl["Mn"], Mn, rel_tol=0.005), \
        f"Mn hand={Mn:.2f}, engine={fl['Mn']:.2f}"
    assert math.isclose(fl["a"], a, rel_tol=0.005), \
        f"a hand={a:.4f}, engine={fl['a']:.4f}"


# ─── 2. Method 1 shear hand calc ──────────────────────────────────────

def test_method1_shear_hand_calc():
    """Vc = 0.0316 * beta * lam * sqrt(fc) * bv * dv;  Vs = Av*fy*dv/s."""
    raw = make_inputs(h=36, b=36, fc=4, fy=60, lam=1.0,
                      barN_bot=8, nBars_bot=4,
                      shN=4, shear_legs=2, s_shear=12)
    res = calculate_all(raw, [demand(Mu=2000, Vu=100)], 0)
    sh = res["shear"]

    beta = 2.0  # Method 1 fixed
    Vc1 = 0.0316 * beta * 1.0 * math.sqrt(4) * sh["bv"] * sh["dv"]
    Av = 2 * BARS[4]["a"]
    Vs1 = Av * 60 * sh["dv"] / 12  # cot 45 = 1

    assert math.isclose(sh["Vc1"], Vc1, rel_tol=0.02), \
        f"Vc1 hand={Vc1:.2f}, engine={sh['Vc1']:.2f}"
    assert math.isclose(sh["Vs1"], Vs1, rel_tol=0.02), \
        f"Vs1 hand={Vs1:.2f}, engine={sh['Vs1']:.2f}"


# ─── 3. Beta1 transition formula ──────────────────────────────────────

@pytest.mark.parametrize("fc, expected", [
    (3.0, 0.85),
    (4.0, 0.85),
    (4.5, 0.825),    # 0.85 - 0.05*(4.5-4) = 0.825
    (5.5, 0.775),
    (6.5, 0.725),
    (7.5, 0.675),
    (8.0, 0.65),
    (10.0, 0.65),
])
def test_beta1_formula(fc, expected):
    raw = make_inputs(h=36, b=36, fc=fc, barN_bot=8, nBars_bot=4)
    res = calculate_all(raw, [demand(Mu=2000)], 0)
    beta1 = res["flexure"]["beta1"]
    assert math.isclose(beta1, expected, abs_tol=0.005), \
        f"fc={fc}: expected beta1={expected}, got {beta1}"


# ─── 4. phi transition (eps_t basis) ──────────────────────────────────

def test_phi_at_balanced_strain_limit():
    """phi should reach 0.9 at eps_t = etl (default 0.005)."""
    # Use a lightly reinforced section so eps_t exceeds 0.005
    raw = make_inputs(h=36, b=36, fc=4, fy=60, barN_bot=6, nBars_bot=2)
    res = calculate_all(raw, [demand(Mu=500)], 0)
    fl = res["flexure"]
    if fl["eps_t"] >= 0.005:
        assert math.isclose(fl["phi_f"], 0.9, abs_tol=0.005)


def test_phi_at_compression_strain_limit():
    """phi should be at 0.75 floor when eps_t <= ecl (default 0.002)."""
    # Heavy steel -> small eps_t -> phi at compression floor
    raw = make_inputs(h=24, b=12, fc=4, fy=60, barN_bot=11, nBars_bot=6)
    res = calculate_all(raw, [demand(Mu=2000)], 0)
    fl = res["flexure"]
    if fl["eps_t"] <= 0.002:
        assert math.isclose(fl["phi_f"], 0.75, abs_tol=0.005)


# ─── 5. Mr = phi * Mn invariant ───────────────────────────────────────

@pytest.mark.parametrize("fc", [3, 4, 5, 6, 8])
def test_Mr_equals_phi_times_Mn(fc):
    raw = make_inputs(h=36, b=36, fc=fc, barN_bot=8, nBars_bot=4)
    res = calculate_all(raw, [demand(Mu=2000)], 0)
    fl = res["flexure"]
    assert math.isclose(fl["Mr"], fl["phi_f"] * fl["Mn"], rel_tol=0.005), \
        f"fc={fc}: Mr={fl['Mr']:.1f} should = phi*Mn = " \
        f"{fl['phi_f']:.4f}*{fl['Mn']:.1f} = {fl['phi_f']*fl['Mn']:.1f}"


# ─── 6. a = beta1 * c invariant ───────────────────────────────────────

@pytest.mark.parametrize("fc", [3, 4, 5, 6, 8])
def test_a_equals_beta1_times_c(fc):
    raw = make_inputs(h=36, b=36, fc=fc, barN_bot=8, nBars_bot=4)
    res = calculate_all(raw, [demand(Mu=2000)], 0)
    fl = res["flexure"]
    assert math.isclose(fl["a"], fl["beta1"] * fl["c"], rel_tol=0.005), \
        f"fc={fc}: a={fl['a']:.4f} should = beta1*c = " \
        f"{fl['beta1']:.4f}*{fl['c']:.4f}"


# ─── 7. Symmetric section: sagging Mr == hogging Mr ───────────────────

def test_symmetric_section_sag_equals_hog():
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                      barN_top=8, nBars_top=4)
    res_s = calculate_all(raw, [demand(Mu=3000)], 0)
    res_h = calculate_all(raw, [demand(Mu=-3000)], 0)
    assert math.isclose(res_s["flexure"]["Mr"], res_h["flexure"]["Mr"],
                        rel_tol=0.005), \
        f"sag Mr={res_s['flexure']['Mr']:.1f} vs hog Mr={res_h['flexure']['Mr']:.1f}"


# ─── 8. P-M curve self-consistency (Mr = phi*Mn at every point) ───────

def test_pm_curve_Mr_equals_phi_Mn():
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                      barN_top=8, nBars_top=4)
    res = calculate_all(raw, [demand(Mu=2000)], 0)
    pm = res["flexure"]["pm_curve"]
    bad = []
    for i, p in enumerate(pm):
        if p.get("phi") is None or p.get("Mn") is None:
            continue
        if not math.isclose(p["Mr"], p["phi"] * p["Mn"], abs_tol=1.0, rel_tol=0.01):
            bad.append((i, p["Mr"], p["phi"], p["Mn"]))
    assert not bad, f"P-M points where Mr != phi*Mn: {bad[:3]}..."


# ─── 9. P-M endpoint: pure-compression Pn_max formula ─────────────────

def test_pn_max_pure_compression_endpoint():
    """The pure-compression endpoint of the P-M curve should match
    AASHTO 10th Ed Eq. 5.6.4.4-3 for an RC section (no PT).

    Engine sign convention: compression is NEGATIVE.
      Pn_max = -0.80 * [k_c * fc * (Ag - Ast) + fy * Ast]   (no PT)
    with k_c = 0.85 for fc <= 10 ksi.
    """
    raw = make_inputs(h=36, b=36, fc=4, fy=60,
                      barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4)
    res = calculate_all(raw, [demand(Mu=2000)], 0)
    pm = res["flexure"]["pm_curve"]
    # Compression is negative -> most-compressive point is the minimum Pn.
    Pn_max_engine = min(p["Pn"] for p in pm)
    Ast = 8 * BARS[8]["a"]
    Ag = 36 * 36
    k_c = 0.85
    Pn_max_hand = -0.80 * (k_c * 4 * (Ag - Ast) + 60 * Ast)
    assert math.isclose(Pn_max_engine, Pn_max_hand, rel_tol=0.02), \
        f"Pn_max hand={Pn_max_hand:.1f}, engine={Pn_max_engine:.1f}"


# ─── 10. Tcr threshold (AASHTO 5.7.2.1-3 / -4) ────────────────────────

def test_Tcr_threshold_proportional_to_sqrt_fc():
    """Tcr should scale as sqrt(fc) at otherwise-identical geometry."""
    raw_4 = make_inputs(h=36, b=36, fc=4, barN_bot=8, nBars_bot=4)
    raw_9 = make_inputs(h=36, b=36, fc=9, barN_bot=8, nBars_bot=4)
    res_4 = calculate_all(raw_4, [demand(Mu=1000, Vu=50, Tu=10)], 0)
    res_9 = calculate_all(raw_9, [demand(Mu=1000, Vu=50, Tu=10)], 0)
    Tcr_4 = res_4["torsion"]["Tcr"]
    Tcr_9 = res_9["torsion"]["Tcr"]
    # sqrt(9/4) = 1.5
    assert math.isclose(Tcr_9 / Tcr_4, 1.5, rel_tol=0.05), \
        f"Tcr ratio expected 1.5, got {Tcr_9/Tcr_4:.3f} (Tcr_4={Tcr_4:.1f}, Tcr_9={Tcr_9:.1f})"


# ─── 11. Doubly reinforced symmetric: top steel does not hurt Mn ──────

def test_doubly_reinforced_symmetric_Mn_not_less():
    raw_bot = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4)
    raw_dbl = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                          barN_top=8, nBars_top=4)
    res_b = calculate_all(raw_bot, [demand(Mu=2000)], 0)
    res_d = calculate_all(raw_dbl, [demand(Mu=2000)], 0)
    # Adding compression steel to a tension-controlled rectangular section
    # gives slightly higher Mn (small effect). At minimum it cannot be less.
    assert res_d["flexure"]["Mn"] >= res_b["flexure"]["Mn"] - 1.0


# ─── 12. PT contribution to Pn_max ────────────────────────────────────

def test_pt_section_pn_max_smaller_magnitude_than_rc():
    """Adding PT should reduce the MAGNITUDE of Pn_max: the term
    -Aps*(fpe - Ep*eps_cu) in Eq. 5.6.4.4-3 subtracts from the
    available compression capacity.  Since compression is stored as
    a negative number, the PT |Pn_max| should be smaller than RC's."""
    raw_rc = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                         barN_top=8, nBars_top=4)
    raw_pt = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                         barN_top=8, nBars_top=4,
                         nStrands=4, strand_area=0.217, dp=28,
                         fpe=170, sectionClass="CIP_PT")
    res_rc = calculate_all(raw_rc, [demand(Mu=2000)], 0)
    res_pt = calculate_all(raw_pt, [demand(Mu=2000)], 0)
    Pn_max_rc = min(p["Pn"] for p in res_rc["flexure"]["pm_curve"])
    Pn_max_pt = min(p["Pn"] for p in res_pt["flexure"]["pm_curve"])
    assert abs(Pn_max_pt) < abs(Pn_max_rc), \
        f"|PT Pn_max| ({abs(Pn_max_pt):.1f}) should be < " \
        f"|RC Pn_max| ({abs(Pn_max_rc):.1f})"
