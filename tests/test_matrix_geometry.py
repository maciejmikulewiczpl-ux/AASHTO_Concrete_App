"""
Dimension 1+2 — Section geometry x reinforcement layout.

Runs every section in SECTION_CATALOGUE through a representative
sagging-moment demand and checks that the engine returns a usable
result with internally consistent values. Catches regressions where
a particular section variant starts crashing or returning nonsense.
"""
import copy
import math
import pytest

from tests.fixtures import (
    SECTION_CATALOGUE,
    DEMAND_CATALOGUE,
    make_inputs,
    calc,
)


@pytest.mark.parametrize("sec_name", list(SECTION_CATALOGUE.keys()))
def test_section_runs_and_has_positive_capacity(sec_name):
    """Every section should produce a valid Mr, Vr, and P-M curve."""
    sec = copy.deepcopy(SECTION_CATALOGUE[sec_name])
    raw, res = calc(sec, DEMAND_CATALOGUE["Pure_Sag"])

    fl = res["flexure"]
    sh = res["shear"]

    assert fl["Mn"] > 0, f"{sec_name}: Mn must be > 0"
    assert fl["Mr"] > 0, f"{sec_name}: Mr must be > 0"
    assert fl["Mr"] <= fl["Mn"] + 0.1, f"{sec_name}: Mr should be <= Mn"
    assert 0 < fl["phi_f"] <= 1.0, f"{sec_name}: phi_f out of [0,1]"
    assert fl["a"] > 0 and fl["c"] > 0, f"{sec_name}: a, c must be > 0"
    assert math.isclose(fl["a"], fl["beta1"] * fl["c"], rel_tol=1e-3), \
        f"{sec_name}: a should equal beta1*c"
    assert 0 < fl["ds"] < raw["h"], f"{sec_name}: ds must be 0 < ds < h"
    assert fl.get("dv", 0) > 0, f"{sec_name}: dv must be > 0"

    # All three shear methods must produce a non-negative Vr.
    for m in (1, 2, 3):
        Vr = sh.get(f"Vr{m}")
        assert Vr is not None and Vr >= 0, f"{sec_name}: Vr{m} missing/negative"

    # P-M curve must exist and span both signs of P.
    pm = fl.get("pm_curve")
    assert pm and len(pm) >= 10, f"{sec_name}: P-M curve too short"
    Pr_vals = [p["Pr"] for p in pm]
    assert max(Pr_vals) > 0, f"{sec_name}: P-M curve has no compression branch"


@pytest.mark.parametrize("sec_name", list(SECTION_CATALOGUE.keys()))
def test_pm_curve_internal_consistency(sec_name):
    """At every P-M curve point, Pr == phi*Pn and Mr == phi*Mn."""
    sec = copy.deepcopy(SECTION_CATALOGUE[sec_name])
    _, res = calc(sec, DEMAND_CATALOGUE["Pure_Sag"])
    pm = res["flexure"]["pm_curve"]

    for i, p in enumerate(pm):
        phi = p.get("phi")
        if phi is None:
            continue
        if p.get("Pn") is not None:
            assert math.isclose(p["Pr"], phi * p["Pn"], abs_tol=1.0, rel_tol=0.01), \
                f"{sec_name} point {i}: Pr != phi*Pn"
        if p.get("Mn") is not None:
            assert math.isclose(p["Mr"], phi * p["Mn"], abs_tol=1.0, rel_tol=0.01), \
                f"{sec_name} point {i}: Mr != phi*Mn"


def test_isection_flange_contributes_to_capacity():
    """An I-section with wide flanges must give Mn >= rect(bw) Mn."""
    rect = make_inputs(h=36, b=12, barN_bot=8, nBars_bot=4)
    isec = make_inputs(
        h=36, b=36, secType="T-SECTION", bw_input=12,
        hf_top=8, hf_bot=8, barN_bot=8, nBars_bot=4,
    )
    dem = [DEMAND_CATALOGUE["Pure_Sag"]]
    from calc_engine import calculate_all
    res_rect = calculate_all(rect, dem, 0)
    res_i = calculate_all(isec, dem, 0)
    assert res_i["flexure"]["Mn"] >= res_rect["flexure"]["Mn"] - 1.0, \
        f"I-section Mn ({res_i['flexure']['Mn']:.1f}) must be >= rect(bw) " \
        f"Mn ({res_rect['flexure']['Mn']:.1f})"


def test_isection_geometry_keys_present():
    """I-section results must expose web-width and flange info."""
    sec = copy.deepcopy(SECTION_CATALOGUE["I_Sym_TopBot"])
    _, res = calc(sec, DEMAND_CATALOGUE["Pure_Sag"])
    inp = res["inputs"]
    assert inp["isRect"] is False
    assert inp["bw"] == 12
    assert inp["hf_top"] == 8
    assert inp["hf_bot"] == 8


def test_multi_row_bottom_steel_runs():
    """Two-row bottom steel should run without error and split forces."""
    from calc_engine import calculate_all
    raw = make_inputs(h=26, b=16, barN_bot=7, nBars_bot=5)
    raw["mr_rows_bot"] = [{"d": 24.5625, "As": 3.0}, {"d": 20.0, "As": 3.0}]
    raw["As_bot_ovr"] = 6.0
    res = calculate_all(raw, [DEMAND_CATALOGUE["Pure_Sag"]], 0)
    pm = res["flexure"]["pm_curve_sag"]
    # Pick a mid-curve point and check that rows_tens reports two rows.
    p_mid = pm[len(pm) // 2]
    rows = p_mid.get("rows_tens", [])
    assert len(rows) == 2, "Expected two tension rows from multi-row input"
    # Strains must differ between rows at different depths
    assert abs(rows[0]["es"] - rows[1]["es"]) > 1e-6
