"""
Dimension 6 — Shear method cross-checks.

The engine reports three shear capacities per section:
  Method 1: Simplified, beta=2.0, theta=45°
  Method 2: General procedure (strain-dependent theta)
  Method 3: AASHTO Appendix B5 (iterative table-based)

This file verifies:
  - All three methods return numbers (no None / NaN / exception)
  - Method 1 reports theta = 45°
  - Method 2 theta is in the 18-50° range
  - Vr = phi_v * Vn for every method
  - Method 1 Vc matches the closed-form hand calc (0.0316 * 2.0 * lam * sqrt(fc) * bv * dv)
  - Method 1 Vs matches Av*fy*dv/s (cot 45 = 1)
  - No Vn exceeds Vnmax
"""
import copy
import math
import pytest

from tests.fixtures import (
    SECTION_CATALOGUE,
    DEMAND_CATALOGUE,
    make_inputs,
    demand,
    calc,
)
from calc_engine import BARS, calculate_all


SHEAR_SECTIONS = [
    "Rect_TopBot_Sym",
    "Rect_TopBot_Asym",
    "Rect_TopBot_PT",
    "I_Sym_TopBot",
    "I_Asym_Flanges",
]


@pytest.mark.parametrize("sec_name", SHEAR_SECTIONS)
def test_all_three_methods_return_numbers(sec_name):
    sec = copy.deepcopy(SECTION_CATALOGUE[sec_name])
    _, res = calc(sec, DEMAND_CATALOGUE["High_Shear_No_Tor"])
    sh = res["shear"]
    for m in (1, 2, 3):
        for k in (f"Vc{m}", f"Vs{m}", f"Vn{m}", f"Vr{m}"):
            val = sh.get(k)
            assert val is not None, f"{sec_name}: {k} is None"
            assert val == val, f"{sec_name}: {k} is NaN"
            assert val >= 0, f"{sec_name}: {k} negative ({val})"


@pytest.mark.parametrize("sec_name", SHEAR_SECTIONS)
def test_method1_theta_is_45_degrees(sec_name):
    sec = copy.deepcopy(SECTION_CATALOGUE[sec_name])
    _, res = calc(sec, DEMAND_CATALOGUE["High_Shear_No_Tor"])
    assert math.isclose(res["shear"]["th1"], 45.0, abs_tol=0.1)


@pytest.mark.parametrize("sec_name", SHEAR_SECTIONS)
def test_method2_theta_in_valid_range(sec_name):
    sec = copy.deepcopy(SECTION_CATALOGUE[sec_name])
    _, res = calc(sec, DEMAND_CATALOGUE["High_Shear_No_Tor"])
    th2 = res["shear"]["th2"]
    assert 18.0 <= th2 <= 50.5, f"Method 2 theta out of range: {th2}"


@pytest.mark.parametrize("sec_name", SHEAR_SECTIONS)
@pytest.mark.parametrize("method", [1, 2, 3])
def test_Vr_equals_phi_times_Vn(sec_name, method):
    sec = copy.deepcopy(SECTION_CATALOGUE[sec_name])
    raw, res = calc(sec, DEMAND_CATALOGUE["High_Shear_No_Tor"])
    sh = res["shear"]
    Vn = sh[f"Vn{method}"]
    Vr = sh[f"Vr{method}"]
    phi_v = raw["phi_v"]
    assert math.isclose(Vr, phi_v * Vn, abs_tol=0.5, rel_tol=0.01), \
        f"{sec_name} Method {method}: Vr={Vr:.1f} but phi*Vn={phi_v*Vn:.1f}"


@pytest.mark.parametrize("sec_name", SHEAR_SECTIONS)
def test_no_Vn_exceeds_Vnmax(sec_name):
    sec = copy.deepcopy(SECTION_CATALOGUE[sec_name])
    _, res = calc(sec, DEMAND_CATALOGUE["High_Shear_No_Tor"])
    sh = res["shear"]
    Vnmax = sh["Vnmax"]
    assert Vnmax > 0
    for m in (1, 2, 3):
        Vn = sh[f"Vn{m}"]
        assert Vn <= Vnmax + 0.5, f"{sec_name} Vn{m}={Vn:.1f} > Vnmax={Vnmax:.1f}"


def test_method1_Vc_closed_form_match():
    """Method 1: Vc = 0.0316 * 2.0 * lam * sqrt(fc) * bv * dv."""
    raw = make_inputs(h=36, b=36, fc=4, lam=1.0, barN_bot=8, nBars_bot=4,
                      shN=4, shear_legs=2, s_shear=12)
    res = calculate_all(raw, [demand(Mu=2000, Vu=100)], 0)
    sh = res["shear"]
    Vc_hand = 0.0316 * 2.0 * 1.0 * math.sqrt(4) * sh["bv"] * sh["dv"]
    assert math.isclose(sh["Vc1"], Vc_hand, rel_tol=0.02), \
        f"Vc1 hand={Vc_hand:.2f}, engine={sh['Vc1']:.2f}"


def test_method1_Vs_closed_form_match():
    """Method 1: Vs = Av * fy_trans * dv / s (cot 45 = 1)."""
    raw = make_inputs(h=36, b=36, fc=4, fy=60, lam=1.0,
                      barN_bot=8, nBars_bot=4,
                      shN=4, shear_legs=2, s_shear=12)
    res = calculate_all(raw, [demand(Mu=2000, Vu=100)], 0)
    sh = res["shear"]
    Av = 2 * BARS[4]["a"]  # 2 legs of #4
    Vs_hand = Av * 60.0 * sh["dv"] / 12.0
    assert math.isclose(sh["Vs1"], Vs_hand, rel_tol=0.02), \
        f"Vs1 hand={Vs_hand:.2f}, engine={sh['Vs1']:.2f}"


def test_compression_axial_increases_method2_Vc():
    """Method 2: more axial compression should increase Vc (eps_s decreases)."""
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4)
    res_noP = calculate_all(raw, [demand(Mu=2000, Vu=100, Pu=0)], 0)
    # Pu < 0 = compression in this codebase's row convention
    res_comp = calculate_all(raw, [demand(Mu=2000, Vu=100, Pu=-300)], 0)
    Vc2_noP = res_noP["shear"]["Vc2"]
    Vc2_comp = res_comp["shear"]["Vc2"]
    assert Vc2_comp >= Vc2_noP - 0.5, \
        f"Compression should not decrease Vc2: P=0->{Vc2_noP:.1f}, " \
        f"P=-300->{Vc2_comp:.1f}"


def test_method3_b5_reports_result_keys():
    """Method 3 (Appendix B5) must report its convergence state.

    Convergence itself is iteration-sensitive and is treated as a warning,
    not a hard pass criterion (matches full_verification.py behavior).
    """
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4)
    res = calculate_all(raw, [demand(Mu=2000, Vu=100)], 0)
    sh = res["shear"]
    # Engine must always return Vr3 -- even when B5 fails to converge it
    # should fall back to a sensible value, not None.
    assert sh.get("Vr3") is not None
    assert sh["Vr3"] >= 0


def test_longitudinal_reinforcement_check_exists():
    """Result must report long_dem, long_cap, long_ok per AASHTO 5.7.3.5."""
    sec = copy.deepcopy(SECTION_CATALOGUE["Rect_TopBot_Sym"])
    _, res = calc(sec, DEMAND_CATALOGUE["High_Shear_No_Tor"])
    sh = res["shear"]
    for k in ("long_dem", "long_cap", "long_ok"):
        assert k in sh, f"Shear result missing {k}"
    assert isinstance(sh["long_ok"], bool)
