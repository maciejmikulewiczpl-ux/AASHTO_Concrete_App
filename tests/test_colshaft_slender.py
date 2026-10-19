import pytest

import circ_engine as cc
import colshaft_lrfd as cl
import colshaft_slender as cs
from csi_import import ForceRow

MEMBER = dict(D=48.0, fc=4.0, fy=60.0, fyt=60.0, cover=2.0, ag=0.75,
              trans_type="hoop", hoop_closure="lap")
CAGE = dict(bar=10, n=12, bundle=1, trans_bar=5, s=6.0, ties=0)


def test_r_is_quarter_D():
    assert cs.slenderness_screen(48, 1.0, 240, False, 1, 1)["r"] == 12.0


def test_unbraced_limit_22():
    s = cs.slenderness_screen(48, 2.0, 120, False, 0.5, 1)  # klr = 20
    assert s["limit"] == 22.0 and s["neglect"]
    assert not cs.slenderness_screen(48, 2.0, 144, False, 0.5, 1)["neglect"]  # 24


def test_braced_limit_double_curvature():
    s = cs.slenderness_screen(48, 1.0, 1, True, -0.5, 1.0)
    assert s["limit"] == pytest.approx(40.0)


def test_braced_limit_single_curvature():
    s = cs.slenderness_screen(48, 1.0, 1, True, 0.5, 1.0)
    assert s["limit"] == pytest.approx(28.0)


def test_klr_100_requires_refined():
    assert not cs.slenderness_screen(48, 1.0, 1200, True, 0, 1)["approx_ok"]  # 100
    assert cs.slenderness_screen(48, 1.0, 1188, True, 0, 1)["approx_ok"]


def test_k_validation_and_zero_m2():
    with pytest.raises(ValueError):
        cs.slenderness_screen(48, 0.9, 100, False, 0, 1)
    assert "note" in cs.slenderness_screen(48, 0.8, 100, True, 0, 1)
    assert cs.slenderness_screen(48, 1, 1, True, 0.3, 0)["limit"] == 22.0  # +1


def test_curvature_sign_convention_pinned():
    # internal-force reading: same sign = single curvature (flag False)
    assert cs.curvature_ratio(30, 10) == pytest.approx(1 / 3)
    assert cs.curvature_ratio(10, -30) == pytest.approx(-1 / 3)
    assert cs.curvature_ratio(0, 0) == 1.0
    cs.SINGLE_CURVATURE_OPPOSITE_SIGN = True
    try:
        assert cs.curvature_ratio(30, -10) == pytest.approx(1 / 3)
    finally:
        cs.SINGLE_CURVATURE_OPPOSITE_SIGN = False


def test_Is_circular_closed_form():
    raw = cl.cage_inputs(cl.base_circ_inputs(MEMBER), CAGE)
    _, rings = cc.circ_layout(cs.derive(raw))
    r, Ab, n = rings[0]["r"], rings[0]["bar_a"], rings[0]["n"]
    assert cs.Is_circular(raw) == pytest.approx(n * Ab * r * r / 2, rel=1e-9)


def _row(case="C", bound="concurrent", step="S1"):
    return {"Pu": -500.0, "Mu": 100.0, "Vu": 1.0, "Tu": 0.0, "_case": case,
            "_step": step, "_bound": bound, "_frame": "F1"}


BENT = {"slender": {"2": {"braced": False, "K": 2.0, "lu": 240.0},
                    "3": {"braced": True, "K": 1.0, "lu": None}, "gamma_p": 1.0},
        "lu_default_in": 120.0}
CGE = {"inputs": {"D": 48.0}}


def test_toggle_off_is_identity():
    rows = [_row(), _row(bound="envelope")]
    before = [dict(r) for r in rows]
    out = cs.make_magnifier(BENT, {}, {"slenderness_on": False})(CGE, rows)
    assert out == before and out is rows


def test_tagging_keeps_Mu_and_takes_worst():
    rows = [_row(bound="envelope")]
    (t,) = cs.make_magnifier(BENT, {}, {"slenderness_on": True})(CGE, rows)
    assert t["Mu"] == 100.0 and rows[0].get("_klr2") is None
    assert t["_klr2"] == pytest.approx(40.0) and t["_klr3"] == pytest.approx(10.0)
    assert t["_slender_limit2"] == 22.0 and t["_slender_limit3"] == pytest.approx(22.0)
    assert t["_slender_status"] == cs.ST_PENDING
    assert t["_delta2"] is None and t["_delta3"] is None


def test_refined_and_neglect_status():
    b = {"slender": {"2": {"braced": True, "K": 1.0, "lu": 1300.0},
                     "3": {"braced": True, "K": 1.0, "lu": 10.0}}}
    (t,) = cs.make_magnifier(b, {}, {"slenderness_on": True})(CGE, [_row()])
    assert t["_slender_status"] == cs.ST_REFINED
    b["slender"]["2"]["lu"] = 10.0
    (t,) = cs.make_magnifier(b, {}, {"slenderness_on": True})(CGE, [_row()])
    assert t["_slender_status"] == cs.ST_NEGLECT


def test_missing_lu_raises():
    b = {"slender": {"2": {"braced": True, "K": 1.0, "lu": None},
                     "3": {"braced": True, "K": 1.0, "lu": 5.0}}}
    with pytest.raises(ValueError):
        cs.make_magnifier(b, {}, {"slenderness_on": True})


def test_concurrent_row_uses_end_moments():
    def fr(st, M2, M3):
        return ForceRow("F1", st, "C", "Combination", "S1", -100.0, 0, 0, 0,
                        M2, M3, False, 1)
    src = {"rows": [fr(0, 30.0, 30.0), fr(100, 10.0, -10.0)], "frames": ["F1"]}
    lu = 0.25 * 48 * 32  # klr = 32
    b = {"slender": {"2": {"braced": True, "K": 1.0, "lu": lu},
                     "3": {"braced": True, "K": 1.0, "lu": lu}}}
    (t,) = cs.make_magnifier(b, src, {"slenderness_on": True})(CGE, [_row()])
    # axis 2 ends (30,10) same sign -> +1/3 -> limit 30; axis 3 (30,-10) -> -1/3 -> 38
    assert t["_slender_limit2"] == pytest.approx(30.0)
    assert t["_slender_limit3"] == pytest.approx(38.0)
