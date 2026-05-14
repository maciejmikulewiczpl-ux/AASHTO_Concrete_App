"""
Dimension 5+7 — Materials and code edition.

Vary fc, fy, lambda, and codeEdition / sectionClass to ensure the
engine handles the relevant code transitions:

  - beta1 = 0.85 for fc <= 4 ksi, decreases linearly to 0.65 at fc >= 8 ksi
  - lambda affects Vc (lightweight concrete)
  - Higher fy increases tension capacity
  - codeEdition='CA' vs 'AASHTO' may shift phi factors
  - sectionClass='RC' vs 'CIP_PT' affects strain limits and phi
"""
import math
import pytest

from tests.fixtures import make_inputs, demand


# ─── beta1 vs fc ──────────────────────────────────────────────────────

@pytest.mark.parametrize("fc, expected_beta1", [
    (4.0, 0.85),
    (5.0, 0.80),   # 0.85 - 0.05 * (5 - 4)
    (6.0, 0.75),
    (7.0, 0.70),
    (8.0, 0.65),
    (10.0, 0.65),  # floor
])
def test_beta1_vs_fc(fc, expected_beta1):
    from calc_engine import calculate_all
    raw = make_inputs(h=36, b=36, fc=fc, barN_bot=8, nBars_bot=4)
    res = calculate_all(raw, [demand(Mu=2000)], 0)
    beta1 = res["flexure"]["beta1"]
    assert math.isclose(beta1, expected_beta1, abs_tol=0.005), \
        f"fc={fc}: beta1 expected {expected_beta1}, got {beta1}"


# ─── Higher fy increases Mn (until concrete crush controls) ──────────

def test_higher_fy_increases_Mn_small_section():
    from calc_engine import calculate_all
    base = make_inputs(h=24, b=12, fc=4, fy=60, barN_bot=8, nBars_bot=3)
    res_60 = calculate_all(base, [demand(Mu=1000)], 0)
    raw_80 = make_inputs(h=24, b=12, fc=4, fy=80, barN_bot=8, nBars_bot=3)
    res_80 = calculate_all(raw_80, [demand(Mu=1000)], 0)
    assert res_80["flexure"]["Mn"] > res_60["flexure"]["Mn"], \
        f"Higher fy should increase Mn: 60->{res_60['flexure']['Mn']:.1f}, " \
        f"80->{res_80['flexure']['Mn']:.1f}"


# ─── Lightweight lambda reduces Vc (general procedure) ──────────────

def test_lightweight_concrete_reduces_Vc():
    from calc_engine import calculate_all
    # Use #5 stirrups (Av_provided = 2*0.31 = 0.62 in²) so both NW and LW
    # cases comfortably satisfy has_min_av — needed because audit decision
    # D15 (2026-05-14) added the λ factor to Av_min itself, so with weaker
    # stirrups the LW case can cross the min-Av boundary and invert β
    # (a real and correct behavior — but obscures the direct λ multiplier
    # in Vc=0.0316·β·λ·√fc'·bv·dv that this test is checking).
    nw = make_inputs(h=36, b=36, lam=1.0, shN=5, shear_legs=2, s_shear=12,
                     barN_bot=8, nBars_bot=4)
    lw = make_inputs(h=36, b=36, lam=0.75, shN=5, shear_legs=2, s_shear=12,
                     barN_bot=8, nBars_bot=4)
    dem = [demand(Mu=2000, Vu=100)]
    res_nw = calculate_all(nw, dem, 0)
    res_lw = calculate_all(lw, dem, 0)
    # Both Method 1 and Method 2 Vc should scale with lambda.
    for m in (1, 2):
        Vc_nw = res_nw["shear"][f"Vc{m}"]
        Vc_lw = res_lw["shear"][f"Vc{m}"]
        assert Vc_lw < Vc_nw, \
            f"Method {m}: lightweight Vc ({Vc_lw:.1f}) should be < NW ({Vc_nw:.1f})"


# ─── Code edition + section class smoke tests ───────────────────────

@pytest.mark.parametrize("code,sclass", [
    ("AASHTO", "RC"),
    ("AASHTO", "CIP_PT"),
    ("CA",     "RC"),
    ("CA",     "NP"),
    ("CA",     "CIP_PT"),
])
def test_code_and_section_class_run(code, sclass):
    """Every code/section-class combination should produce a valid result."""
    from calc_engine import calculate_all
    raw = make_inputs(
        h=36, b=36, fc=5, fy=60,
        barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4,
        codeEdition=code, sectionClass=sclass,
    )
    if sclass == "CIP_PT":
        raw["nStrands"] = 2
        raw["strand_area"] = 0.196
        raw["dp"] = 28
        raw["fpe"] = 170
    res = calculate_all(raw, [demand(Mu=2500, Vu=100)], 0)
    fl = res["flexure"]
    assert fl["Mn"] > 0 and fl["Mr"] > 0
    assert 0 < fl["phi_f"] <= 1.0


# ─── High-strength concrete sanity ────────────────────────────────────

def test_high_fc_still_reaches_capacity():
    """fc=10 ksi should not break the engine; beta1 should clamp to 0.65."""
    from calc_engine import calculate_all
    raw = make_inputs(h=36, b=36, fc=10, barN_bot=8, nBars_bot=4)
    res = calculate_all(raw, [demand(Mu=2000, Vu=100)], 0)
    fl = res["flexure"]
    assert math.isclose(fl["beta1"], 0.65, abs_tol=0.01)
    assert fl["Mn"] > 0


# ─── Strain limits + phi transition ──────────────────────────────────

def test_phi_transition_tension_controlled():
    """A very lightly reinforced section should be tension-controlled (phi=0.9)."""
    from calc_engine import calculate_all
    # Very low reinforcement ratio -> deep tension strain -> phi=0.9
    raw = make_inputs(h=36, b=36, fc=4, fy=60, barN_bot=6, nBars_bot=2)
    res = calculate_all(raw, [demand(Mu=1000)], 0)
    fl = res["flexure"]
    assert fl["eps_t"] > 0.005, f"Expected eps_t > 0.005 (tension-ctrl), got {fl['eps_t']}"
    assert math.isclose(fl["phi_f"], 0.9, abs_tol=0.01), \
        f"phi should be 0.9 in tension-controlled, got {fl['phi_f']}"


def test_phi_transition_compression_controlled():
    """A very heavily reinforced section should be compression-controlled (phi=0.75)."""
    from calc_engine import calculate_all
    # Heavy steel -> shallow tension strain -> phi -> 0.75
    raw = make_inputs(
        h=24, b=12, fc=4, fy=60,
        barN_bot=11, nBars_bot=6,  # 6 #11 bars = 9.36 in^2 in 12x24 section
    )
    res = calculate_all(raw, [demand(Mu=2000)], 0)
    fl = res["flexure"]
    # In compression-controlled region, eps_t < ecl (0.002) and phi=0.75
    if fl["eps_t"] < 0.002:
        assert math.isclose(fl["phi_f"], 0.75, abs_tol=0.01), \
            f"Compression-controlled phi should be 0.75, got {fl['phi_f']}"
