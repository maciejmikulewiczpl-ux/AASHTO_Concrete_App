"""Pins for provisions verified against AASHTO LRFD BDS 10th Ed. (2024) Chapter 5
text on 2026-09-29 (OPEN_VERIFICATION_ITEMS.md: F1, F2, M3, M4, M5, R1).

F1/M5  §5.7.3.4.2: one εs equation (Eq. 5.7.3.4.2-4) for sections with and without
       minimum Av, denominator (EsAs + EpAps); εs < 0 → denominator
       (EsAs + EpAps + EcAct), εs ≥ −0.40e-3. The factor 2 is Appendix B5 only (Eq. B5.2-3).
M4     §5.7.3.4.2 / §B5.2: axial tension cracking the flexural compression face →
       εs (and εx) doubled — applied in the active section AND in demand rows.
F2     Table 5.6.3.3: "For prestressing steel, γ3 shall be taken as 1.0."
M3     §5.7.3.4.1 scope: nonprestressed, no axial tension, ≥ min Av or h < 16 in.
"""
import pytest

from calc_engine import calculate_all, derive_constants
from tests.fixtures import make_inputs, demand, PT_STRAND_AREA

PT = dict(nStrands=4, strand_area=PT_STRAND_AREA, dp=28, fpe=170, ductDia=2.0, sectionClass="CIP_PT")
RECT = dict(h=36, b=18, barN_bot=9, nBars_bot=4, barN_top=5, nBars_top=2, shN=4, s_shear=8)


def _run(sec, dems, active=0):
    raw = make_inputs(**sec)
    I = dict(raw)
    derive_constants(I)
    return I, calculate_all(raw, dems if isinstance(dems, list) else [dems], active)


def _eps_expected(sh, Pu, Vu, Vp=0.0):
    return (sh["Mu_c"] / sh["dv"] + 0.5 * Pu + abs(Vu - Vp) - sh["Aps_tens"] * sh["fpo"]) / sh["denom"]


def test_f1_single_denominator_with_min_av():
    _, res = _run(RECT, demand(Mu=3000, Vu=80, Ms=100))
    sh = res["shear"]
    assert sh["has_min_av"]
    assert not sh["dbl_eps"]
    assert sh["eps_s"] == pytest.approx(_eps_expected(sh, 0, 80))


def test_f1_same_equation_without_min_av():
    _, res = _run(dict(RECT, shear_legs=0, s_shear=0), demand(Mu=3000, Vu=30, Ms=100))
    sh = res["shear"]
    assert not sh["has_min_av"]
    assert sh["eps_s"] == pytest.approx(_eps_expected(sh, 0, 30))


def test_m5_negative_eps_denominator_includes_ec_act_once():
    _, res = _run(dict(RECT, **PT), demand(Mu=200, Vu=20, Ms=100))
    sh = res["shear"]
    assert sh["eps_s_neg_recalc"]
    num = sh["Mu_c"] / sh["dv"] + abs(20) - sh["Aps_tens"] * sh["fpo"]
    expect = max(num / (sh["denom"] + sh["Ec_gp"] * sh["Act_gp"]), -0.0004)
    assert sh["eps_s"] == pytest.approx(expect)


def test_row_eps_uses_single_denominator():
    """Row εs agrees with the active-section εs (row dv/As are computed independently,
    so allow a few %; the old factor-2 bug would give a 2× difference)."""
    dems = [demand(Mu=3000, Vu=80, Ms=100), demand(Mu=-2500, Vu=60, Ms=-100)]
    for active in (0, 1):
        _, res = _run(RECT, dems, active)
        assert res["shear"]["has_min_av"]
        assert res["row_results"][active]["epsS"] == pytest.approx(res["shear"]["eps_s"], rel=0.05)


TENSION = demand(Pu=400, Mu=300, Vu=40, Ms=100)   # gross compression-face stress 0.54 > fr 0.48 ksi


def test_m4_axial_tension_doubles_eps_in_active_and_rows():
    _, res = _run(RECT, TENSION)
    sh = res["shear"]
    assert sh["dbl_eps"]
    assert sh["eps_s"] == pytest.approx(min(2 * _eps_expected(sh, 400, 40), 0.006))
    row = res["row_results"][0]
    assert row["dblEps"] is True
    assert row["epsS"] == pytest.approx(sh["eps_s"], rel=0.05)
    _, no = _run(RECT, demand(Pu=50, Mu=3000, Vu=40, Ms=100))
    assert not no["shear"]["dbl_eps"] and no["row_results"][0]["dblEps"] is False


def test_m4_b5_ex_doubled_when_compression_face_cracks():
    _, res = _run(RECT, TENSION)
    sh = res["shear"]
    assert sh["dbl_eps"] and not sh["b5_ex_neg_recalc"]
    assert sh["ex_b5"] == pytest.approx(2 * sh["b5_ex_num"] / sh["b5_denom_used"])


def test_f2_gamma3_is_one_with_tension_side_prestress():
    _, res = _run(dict(RECT, **PT), demand(Mu=3000, Vu=50, Ms=100))
    assert res["flexure"]["Aps_tens"] > 0
    assert res["flexure"]["gamma3"] == 1.0
    _, rc = _run(RECT, demand(Mu=3000, Vu=50, Ms=100))
    assert rc["flexure"]["gamma3"] == pytest.approx(0.67)


def test_f2_gamma3_override_still_wins():
    _, res = _run(dict(RECT, factor_overrides={"gamma3_f": 0.75}, **PT), demand(Mu=3000, Vu=50, Ms=100))
    assert res["flexure"]["gamma3"] == 0.75


@pytest.mark.parametrize("sec,dem,ok,reason", [
    (RECT, demand(Mu=3000, Vu=80, Ms=100), True, ""),
    (dict(RECT, **PT), demand(Mu=3000, Vu=80, Ms=100), False, "prestressed"),
    (RECT, demand(Pu=50, Mu=3000, Vu=80, Ms=100), False, "axial tension"),
    (dict(RECT, shear_legs=0, s_shear=0), demand(Mu=3000, Vu=30, Ms=100), False, "min Av"),
    (dict(RECT, h=14, shear_legs=0, s_shear=0, barN_top=0, nBars_top=0), demand(Mu=500, Vu=5, Ms=100), True, ""),
])
def test_m3_method1_scope_flag(sec, dem, ok, reason):
    _, res = _run(sec, dem)
    assert res["shear"]["m1_applicable"] is ok
    assert reason in res["shear"]["m1_na_reason"]
