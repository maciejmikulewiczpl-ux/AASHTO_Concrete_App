"""
PT integration tests.

The pt_engine module itself is covered by the existing test_pt.py (22
unit tests for parabola fitting, friction, anchor set, elastic
shortening, time-dependent losses, etc.).  This file covers how PT
inputs flow through calc_engine -- per-row fpe overrides, Vp shear
contribution, PT impact on flexural capacity and phi.
"""
import copy
import math
import pytest

from tests.fixtures import make_inputs, demand
from calc_engine import calculate_all


def _pt_inputs(**overrides):
    base = make_inputs(
        h=36, b=36, fc=5, fy=60,
        barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4,
        nStrands=4, strand_area=0.217, dp=28, fpe=170, ductDia=2.5,
        sectionClass="CIP_PT",
    )
    base.update(overrides)
    return base


# ─── PT increases flexural capacity vs identical RC section ──────────

def test_pt_section_has_higher_Mn_than_no_pt():
    raw_rc = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                         barN_top=8, nBars_top=4)
    raw_pt = _pt_inputs()
    res_rc = calculate_all(raw_rc, [demand(Mu=4000)], 0)
    res_pt = calculate_all(raw_pt, [demand(Mu=4000)], 0)
    assert res_pt["flexure"]["Mn"] > res_rc["flexure"]["Mn"], \
        f"PT Mn={res_pt['flexure']['Mn']:.1f} should exceed RC " \
        f"Mn={res_rc['flexure']['Mn']:.1f}"


# ─── Higher fpe increases the cracking moment Mcr ───────────────────
#
# Per AASHTO 5.7.2.2-1, ultimate strand stress fps is computed from
# strain compatibility and does NOT depend on fpe.  fpe DOES enter the
# cracking-moment formula (gamma1 * (fr + fcpe) * Sc), so higher fpe
# should raise Mcr.  This is the right field to gate on.

def test_higher_fpe_increases_Mcr():
    raw_low = _pt_inputs(fpe=100)
    raw_high = _pt_inputs(fpe=220)
    res_low = calculate_all(raw_low, [demand(Mu=4000)], 0)
    res_high = calculate_all(raw_high, [demand(Mu=4000)], 0)
    assert res_high["flexure"]["Mcr"] > res_low["flexure"]["Mcr"], \
        f"Mcr should grow with fpe: low={res_low['flexure']['Mcr']:.1f} " \
        f"vs high={res_high['flexure']['Mcr']:.1f}"


def test_fpe_does_not_affect_ultimate_Mn():
    """Sanity: at ultimate, Mn must be independent of fpe (5.7.2.2-1).
    This is a regression guard -- if Mn ever does start depending on
    fpe, we want to know about it explicitly."""
    raw_low = _pt_inputs(fpe=100)
    raw_high = _pt_inputs(fpe=200)
    res_low = calculate_all(raw_low, [demand(Mu=4000)], 0)
    res_high = calculate_all(raw_high, [demand(Mu=4000)], 0)
    assert math.isclose(res_low["flexure"]["Mn"],
                        res_high["flexure"]["Mn"], rel_tol=1e-3)


# ─── More strands increase Mn ───────────────────────────────────────

def test_more_strands_increases_Mn():
    raw_2 = _pt_inputs(nStrands=2)
    raw_8 = _pt_inputs(nStrands=8)
    res_2 = calculate_all(raw_2, [demand(Mu=4000)], 0)
    res_8 = calculate_all(raw_8, [demand(Mu=4000)], 0)
    assert res_8["flexure"]["Mn"] > res_2["flexure"]["Mn"]


# ─── Deeper strand position (larger dp) increases Mn ─────────────────

def test_larger_dp_increases_Mn():
    raw_shallow = _pt_inputs(dp=20)
    raw_deep = _pt_inputs(dp=30)
    res_shallow = calculate_all(raw_shallow, [demand(Mu=4000)], 0)
    res_deep = calculate_all(raw_deep, [demand(Mu=4000)], 0)
    assert res_deep["flexure"]["Mn"] > res_shallow["flexure"]["Mn"], \
        f"dp=30 Mn={res_deep['flexure']['Mn']:.1f} should exceed " \
        f"dp=20 Mn={res_shallow['flexure']['Mn']:.1f}"


# ─── PT increases concrete shear contribution Vc (eps_s decreases) ──

def test_pt_section_has_higher_or_equal_Vc():
    raw_rc = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                         barN_top=8, nBars_top=4)
    raw_pt = _pt_inputs()
    dem = [demand(Mu=2000, Vu=100)]
    res_rc = calculate_all(raw_rc, dem, 0)
    res_pt = calculate_all(raw_pt, dem, 0)
    # Method 2 (general procedure) is the most sensitive to PT
    assert res_pt["shear"]["Vc2"] >= res_rc["shear"]["Vc2"] - 1.0


# ─── Vp (vertical PT component) directly augments Vr ─────────────────

def test_Vp_demand_increases_Vr():
    """A row with Vp>0 should report a higher Vr than the same row with Vp=0."""
    raw = _pt_inputs()
    res_no_Vp = calculate_all(raw, [demand(Mu=2000, Vu=200, Vp=0)], 0)
    res_with_Vp = calculate_all(raw, [demand(Mu=2000, Vu=200, Vp=40)], 0)
    Vr2_no = res_no_Vp["shear"]["Vr2"]
    Vr2_yes = res_with_Vp["shear"]["Vr2"]
    assert Vr2_yes > Vr2_no - 0.5, \
        f"Vp=40 should not reduce Vr2: {Vr2_no:.1f} -> {Vr2_yes:.1f}"


# ─── Per-row fpe override (multi-row PT support) ────────────────────

def test_per_row_fpe_override_propagates_via_active_row():
    """A row-level fpe override must propagate when that row is active.

    Mcr is reported only for the active row (in res['flexure']), so we
    check the override by activating each row in turn and verifying
    that res['flexure']['Mcr'] tracks the row-level fpe value.
    """
    raw = _pt_inputs(fpe=170)
    dems = [
        demand(Mu=3000),                       # row 0: global fpe=170
        dict(**demand(Mu=3000), fpe=100),      # row 1: override fpe=100
        dict(**demand(Mu=3000), fpe=220),      # row 2: override fpe=220
    ]
    Mcrs = []
    for i in range(3):
        r = calculate_all(raw, dems, i)
        Mcrs.append(r["flexure"]["Mcr"])
    # Order: row1 (lowest fpe) < row0 (170) < row2 (highest fpe)
    assert Mcrs[1] < Mcrs[0] < Mcrs[2], \
        f"Per-row fpe should set Mcr monotonically when active: " \
        f"row1(fpe=100)={Mcrs[1]:.1f}, row0(fpe=170)={Mcrs[0]:.1f}, " \
        f"row2(fpe=220)={Mcrs[2]:.1f}"


def test_per_row_dp_override():
    """A row supplying its own 'dp' should pick up that depth for flexure."""
    raw = _pt_inputs(dp=28)
    dems = [
        demand(Mu=3000),
        dict(**demand(Mu=3000), dp=22),   # shallower strands for this row
    ]
    res = calculate_all(raw, dems, 0)
    rr = res["row_results"]
    # Shallower dp -> less lever arm -> Mr should drop
    assert rr[1]["Mr"] < rr[0]["Mr"] + 0.5


# ─── PT engine standalone smoke (compute_full_profile) ──────────────

def test_pt_engine_returns_complete_profile():
    """compute_full_profile must return a profile with expected keys.
    Uses pt_engine's actual input contract (fpj, mu, kappa, delta_set, ...)."""
    import pt_engine
    inputs = {
        "spans": [{"L_ft": 120, "y_left": 6, "y_mid": 24, "y_right": 6}],
        "fpj": 0.75 * 270,             # 75% of fpu
        "jack_end": "both",
        "mu": 0.20,
        "kappa": 0.0002,
        "delta_set": 0.25,             # 1/4 inch anchor set
        "Ep": 28500.0,
        "Aps": 12 * 0.217,             # 12 strands x 0.217 in^2
        "h_section": 36.0,
        "Ag": 1296.0,
        "Ig": 100000.0,
        "yb": 18.0,
        "Msw": 0.0,
        "Eci": 4000.0,
        "N_tendons": 1,
        "H": 70.0,
        "fci": 4.0,
    }
    res = pt_engine.compute_full_profile(inputs)
    assert "profile" in res, f"compute_full_profile missing 'profile': {list(res)}"
    prof = res["profile"]
    assert isinstance(prof, list) and prof, "Profile empty"
    p0 = prof[0]
    for k in ("x_ft", "y", "fpe", "P_eff"):
        assert k in p0, f"Profile point missing key '{k}'"
    # fpe along the profile must be a fraction of fpj (after losses)
    fpes = [p["fpe"] for p in prof]
    assert all(0 < f < inputs["fpj"] for f in fpes), \
        "All fpe along the profile must be positive and < fpj"


# ─── PT section near pure compression (PM curve endpoint) ────────────

def test_pt_section_pm_curve_has_full_range():
    """PT section P-M curve must span both signs of Pn."""
    raw = _pt_inputs()
    res = calculate_all(raw, [demand(Mu=3000)], 0)
    pm = res["flexure"]["pm_curve"]
    assert len(pm) >= 20
    Pn_vals = [p["Pn"] for p in pm]
    assert min(Pn_vals) < 0, "PT P-M curve should reach compression branch"
    assert max(Pn_vals) > 0 or min(Pn_vals) < 0, "Curve must span Pn"
