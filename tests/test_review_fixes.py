"""Pins for the review fixes applied 2026-09-28 (REVIEW_FINDINGS_2026-06-11.md):
F3 hogging fcpe sign, F4 tension-fibre Sc, F6 pure-tension key-point sign,
M1 dc to the bar centre, M2 cracked-section transformed area with NA in the web.
These are mechanics / internal-consistency fixes, not AASHTO-text citations.
"""
import math

import pytest

from calc_engine import BARS, calculate_all, derive_constants
from tests.fixtures import make_inputs, demand, PT_STRAND_AREA

PT = dict(nStrands=4, strand_area=PT_STRAND_AREA, dp=28, fpe=170, ductDia=2.0, sectionClass="CIP_PT")
I_ASYM = dict(h=36, b=36, secType="T-SECTION", bw_input=12, hf_top=8, hf_bot=12,
              barN_bot=9, nBars_bot=6, barN_top=5, nBars_top=4)


def _run(sec, dem):
    raw = make_inputs(**sec)
    I = dict(raw)
    derive_constants(I)
    return I, calculate_all(raw, [dem], 0)


@pytest.mark.parametrize("Mu", [3000, -3000])
def test_f3_fcpe_sign_follows_tension_face(Mu):
    I, res = _run(dict(h=36, b=36, barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4, **PT), demand(Mu=Mu, Vu=50, Ms=100))
    P = I["Aps"] * I["fpe"]
    e = I["dp"] - I["yb_centroid"]
    yt = (I["h"] - I["yb_centroid"]) if Mu >= 0 else I["yb_centroid"]
    sign = 1 if Mu >= 0 else -1
    assert res["flexure"]["fcpe"] == pytest.approx(max(P / I["Ag"] + sign * P * e * yt / I["Ig"], 0))


@pytest.mark.parametrize("Mu", [3000, -3000])
def test_f4_sc_at_tension_fibre(Mu):
    I, res = _run(I_ASYM, demand(Mu=Mu, Vu=50, Ms=100))
    yb = I["yb_centroid"]
    y_t = (I["h"] - yb) if Mu >= 0 else yb
    assert res["flexure"]["Sc"] == pytest.approx(I["Ig"] / y_t)


def test_f6_pure_tension_key_point_matches_curve():
    _, res = _run(I_ASYM, demand(Mu=-3000, Vu=50, Ms=100))
    fl = res["flexure"]
    kp = [p for p in fl["pm_key_points"] if p["name"] == "Pure Tension"][0]
    assert kp["Mn"] == pytest.approx(fl["pm_curve_hog"][-1]["Mn"])
    assert kp["Mn"] == pytest.approx(fl["pm_curve_sag"][-1]["Mn"])


def test_m1_dc_to_bar_centre():
    _, res = _run(dict(h=36, b=36, barN_bot=8, nBars_bot=4, shN=5), demand(Mu=3000, Vu=50, Ms=100))
    assert res["flexure"]["dc"] == pytest.approx(2.0 + BARS[5]["d"] + BARS[8]["d"] / 2)
    _, res0 = _run(dict(h=36, b=36, barN_bot=8, nBars_bot=4, shear_legs=0, s_shear=0), demand(Mu=3000, Ms=100))
    assert res0["flexure"]["dc"] == pytest.approx(2.0 + BARS[8]["d"] / 2)


def test_m2_transformed_area_uses_web_below_flange():
    sec = dict(h=36, b=36, secType="T-SECTION", bw_input=10, hf_top=3, hf_bot=0,
               barN_bot=11, nBars_bot=8, barN_top=0, nBars_top=0)
    I, res = _run(sec, demand(Mu=3000, Vu=50, Ms=4000, Ps=20))
    fl = res["flexure"]
    assert fl["c_cr"] > 3
    A_c = 36 * 3 + 10 * (fl["c_cr"] - 3)
    expect = (fl["M_serv"] + fl["addlBM"]) * (fl["serv_ds"] - fl["c_cr"]) / fl["Icr"] * fl["n_mod"] \
        + 20 / (fl["nAs"] + fl["nAps"] + A_c) * fl["n_mod"]
    assert fl["fss"] == pytest.approx(expect)
