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
    # user decision 2026-10-19: unbraced K < 1.0 (buckling analysis) accepted with a warning
    s = cs.slenderness_screen(48, 0.9, 100, False, 0, 1)
    assert s["note"] == cs.UNBRACED_K_LT1_WARNING and "C5.6.4.3 floor" in s["note"]
    assert s["klr"] == pytest.approx(0.9 * 100 / 12.0)
    with pytest.raises(ValueError):
        cs.slenderness_screen(48, 0.0, 100, False, 0, 1)
    assert cs.slenderness_screen(48, 0.8, 100, True, 0, 1)["note"] == cs.BRACED_K_LT1_NOTE
    assert cs.slenderness_screen(48, 1, 1, True, 0.3, 0)["limit"] == 22.0  # +1


# ── K per axis (user decision 2026-10-19) ───────────────────────────

def test_resolve_K_defaults():
    k = cs.resolve_K({"braced": True, "K_source": "default"}, "2")
    assert k["K"] == 1.0 and k["source"] == "default" and k["warnings"] == []
    assert "C5.6.4.3" in k["label"]
    # ruling M1: unbraced defaults = Table C4.6.2.5-1 design values (e) 2.1 / (d) 1.2
    k = cs.resolve_K({"braced": False, "K_source": "default", "end_condition": "fixed-free"}, "2")
    assert k["K"] == 2.1 and k["end_condition"] == "fixed-free"
    assert k["label"] == "K = 2.1 (Table C4.6.2.5-1 case (e) design value, fixed-free)"
    assert k["warnings"] == ["slenderness axis 2: " + cs.DEFAULT_K_WARNING]
    assert "Euler" not in cs.DEFAULT_K_WARNING and "Table C4.6.2.5-1" in cs.DEFAULT_K_WARNING
    k = cs.resolve_K({"braced": False, "K_source": "default", "end_condition": "fixed-fixed"})
    assert k["K"] == 1.2 and "case (d) design value, fixed-fixed" in k["label"]
    # end condition defaults to fixed-free (conservative); K ignored for the default source
    k = cs.resolve_K({"braced": False, "K_source": "default", "K": 0.5})
    assert k["K"] == 2.1 and k["end_condition"] == "fixed-free"
    # nothing given at all -> default source
    assert cs.resolve_K({"braced": False})["K"] == 2.1
    assert cs.TABLE_K == {"fixed-free": 2.1, "fixed-fixed": 1.2}


def test_resolve_K_analysis_and_legacy():
    k = cs.resolve_K({"braced": False, "K_source": "analysis", "K": 1.7})
    assert k["K"] == 1.7 and k["source"] == "analysis" and k["warnings"] == []
    k = cs.resolve_K({"braced": False, "K_source": "analysis", "K": 0.8}, "3")
    assert k["K"] == 0.8 and k["warnings"] == ["slenderness axis 3: " + cs.UNBRACED_K_LT1_WARNING]
    k = cs.resolve_K({"braced": True, "K_source": "analysis", "K": 0.8})
    assert k["K"] == 0.8 and k["warnings"] == [cs.BRACED_K_LT1_NOTE]
    for bad in (0.0, -1.0, None, "1.2"):
        with pytest.raises(ValueError, match="buckling analysis"):
            cs.resolve_K({"braced": False, "K_source": "analysis", "K": bad})
    with pytest.raises(ValueError, match="K_source"):
        cs.resolve_K({"braced": False, "K_source": "table", "K": 1.0})
    with pytest.raises(ValueError, match="end_condition"):
        cs.resolve_K({"braced": False, "end_condition": "pinned"})
    # legacy payload: numeric K and no K_source -> analysis (the user typed it)
    k = cs.resolve_K({"braced": False, "K": 2.1})
    assert k["source"] == "analysis" and k["K"] == 2.1


def test_make_magnifier_K_default_and_warnings():
    b = {"slender": {"2": {"braced": False, "K_source": "default", "end_condition": "fixed-free",
                           "lu": 240.0},
                     "3": {"braced": False, "K_source": "analysis", "K": 0.8, "lu": 240.0}}}
    w = []
    (t,) = cs.make_magnifier(b, {}, {"slenderness_on": True}, w)(CGE, [_row()])
    assert t["_klr2"] == pytest.approx(2.1 * 240.0 / 12.0)
    assert t["_klr3"] == pytest.approx(0.8 * 240.0 / 12.0)      # accepted as entered
    assert any(cs.DEFAULT_K_WARNING in x for x in w)
    assert any(cs.UNBRACED_K_LT1_WARNING in x for x in w)
    b["slender"]["3"]["K"] = None
    with pytest.raises(ValueError):
        cs.make_magnifier(b, {}, {"slenderness_on": True})


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
CGE = dict(CAGE, inputs=cl.cage_inputs(cl.base_circ_inputs(MEMBER), CAGE))


def test_toggle_off_is_identity():
    rows = [_row(), _row(bound="envelope")]
    before = [dict(r) for r in rows]
    out = cs.make_magnifier(BENT, {}, {"slenderness_on": False})(CGE, rows)
    assert out == before and out is rows


def test_tagging_magnifies_and_takes_worst():
    rows = [_row(bound="envelope")]
    (t,) = cs.make_magnifier(BENT, {}, {"slenderness_on": True})(CGE, rows)
    assert rows[0].get("_klr2") is None and rows[0]["Mu"] == 100.0     # input untouched
    assert t["_klr2"] == pytest.approx(40.0) and t["_klr3"] == pytest.approx(10.0)
    assert t["_slender_limit2"] == 22.0 and t["_slender_limit3"] == pytest.approx(22.0)
    assert t["_slender_status"] == cs.ST_MAGNIFIED == "magnified"
    # axis 3 neglected -> 1.0; axis 2 magnified (> 1); no _M2/_M3 -> Mu * max(delta)
    assert t["_delta3"] == 1.0 and t["_delta2"] > 1.0
    assert t["Mu"] == pytest.approx(100.0 * t["_delta2"]) and t["_Mu1"] == 100.0
    assert not hasattr(cs, "ST_PENDING")


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


# ── moment magnification (rulings M1-M13, 2026-10-19) ───────────────
# Source of every equation: AASHTO 10 Ch 5 MD/Art_4.5.3.2.2b_user_supplied.md

import math

import colshaft_demands as cd
import colshaft_lrfd as cl2

HEAVY = dict(bar=14, n=24, bundle=1, trans_bar=5, s=6.0, ties=0)


def _cage(c):
    return dict(c, inputs=cl.cage_inputs(cl.base_circ_inputs(MEMBER), c))


def _fr(st, case, P, M2, M3, step="S1", env=False):
    return ForceRow("F1", st, case, "Combination", step, P, 0.0, 0.0, 0.0, M2, M3, env, 1)


def test_hand_calc_braced():
    """Braced worked example (both axes braced, K_braced default 1.0, lu = 504 in).

    D = 48 in, f'c = 4 ksi, cage 24-#14 (Ab 2.25 in², db 1.693 in), #5 hoop, cover 2 in.
      Ec = 120000·K1·wc²·f'c^0.33 = 120000·1·0.145²·4^0.33 = 3986.548 ksi (engine Ec)
      Ig = π·48⁴/64 = 260576.26 in⁴
      ring r = 24 − 2 − 0.625 − 1.693/2 = 20.5285 in; Is = n·Ab·r²/2 = 24·2.25·20.5285²/2
         = 11378.32 in⁴; Es = 29000 ksi
      βd (Dead rows): max|M_dead| = 400 kip-in (DC at the top), max|Mu| (Strength) =
         hypot(1200, 900) = 1500 kip-in; βd = 1.25·400/1500 = 0.33333
      EI (5.6.4.3-1) = (Ec·Ig/5 + Es·Is)/(1 + βd) = 4.032985e8 kip-in²  <- larger
      EI (5.6.4.3-2) = (Ec·Ig/2.5)/(1 + βd)       = 3.116400e8
      Pe (4.5.3.2.2b-5) = π²·EI/(1.0·504)² = 15669.865 kip
      Row: Str S1 top station, Pu = −8000 kip, M2 = 1200, M3 = 900 kip-in.
      End moments: axis 2 (1200 top, 600 base) same sign -> M1/M2 = +0.5 -> Cm2 = 0.6 + 0.4·0.5 = 0.8;
                   axis 3 (900, −450) -> −0.5 -> Cm3 = 0.4  (Eq. 4.5.3.2.2b-6)
      Screen: K·lu/r = 504/12 = 42 > 34 − 12·0.5 = 28 (axis 2) and > 40 (axis 3) -> magnify.
      1 − Pu/(φK·Pe) = 1 − 8000/(0.75·15669.865) = 0.3192879
      δb2 = 0.8/0.3192879 = 2.5055757; δb3 = 0.4/0.3192879 = 1.2527878 (both ≥ 1.0)
      δs = 1.0 (braced).  Mc2 = 2.5055757·1200 = 3006.6908; Mc3 = 1.2527878·900 = 1127.5091
      Mu = hypot(Mc2, Mc3) = 3211.1472 kip-in."""
    src_rows = [_fr(0.0, "Str", -8000.0, 1200.0, 900.0), _fr(504.0, "Str", -8010.0, 600.0, -450.0),
                _fr(0.0, "DC", -300.0, 400.0, 0.0, step=""), _fr(504.0, "DC", -310.0, 300.0, 0.0, step="")]
    src = {"rows": src_rows, "frames": ["F1"], "categories": None}
    bent = {"slender": {"2": {"braced": True, "lu": 504.0}, "3": {"braced": True, "lu": 504.0},
                        "gamma_p": 1.25}}
    rows = [d for d in cd.demand_rows(src_rows, ["F1"], None, "Strength") if d["_station"] == 0.0]
    tf = cs.make_magnifier(bent, src, {"slenderness_on": True})
    (t,) = tf(_cage(HEAVY), rows)
    R = 1e-6
    assert tf.beta_d == pytest.approx(1.0 / 3.0, rel=R)
    e = tf.props(_cage(HEAVY)["inputs"])
    assert e["Ec"] == pytest.approx(3986.5484596626, rel=R)
    assert e["Ig"] == pytest.approx(260576.2610593518, rel=R)
    assert e["Is"] == pytest.approx(11378.32143075, rel=R)
    assert e["EI1"] == pytest.approx(403298474.94143, rel=R)
    assert e["EI2"] == pytest.approx(311639967.64524, rel=R)
    assert t["_EI"] == pytest.approx(403298474.94143, rel=R) and e["eq"] == "5.6.4.3-1"
    assert t["_Pe_b2"] == pytest.approx(15669.864903134, rel=R)
    assert t["_Cm2"] == pytest.approx(0.8) and t["_Cm3"] == pytest.approx(0.4)
    assert t["_db2"] == pytest.approx(2.505575699786, rel=R)
    assert t["_db3"] == pytest.approx(1.252787849893, rel=R)
    assert t["_ds2"] == 1.0 and t["_ds3"] == 1.0 and t["_Pe_s2"] is None
    assert t["_delta2"] == pytest.approx(2.505575699786, rel=R)
    assert t["Mu"] == pytest.approx(3211.1472244727, rel=R)
    assert t["_Mu1"] == pytest.approx(1500.0) and not t["_unstable"]
    assert t["_slender_status"] == cs.ST_MAGNIFIED


def test_hand_calc_unbraced():
    """Unbraced worked example (axis 2 fixed-free, axis 3 fixed-fixed, defaults; lu = 240 in).

    D = 48 in, f'c = 4 ksi, cage 12-#10 (Ab 1.27 in², db 1.27 in), #5 hoop, cover 2 in.
      Ec = 3986.548 ksi; Ig = 260576.26 in⁴
      r = 24 − 2 − 0.625 − 1.27/2 = 20.74 in; Is = 12·1.27·20.74²/2 = 3277.7247 in⁴
      βd = 0.5 (user override)
      EI (5.6.4.3-1) = (Ec·Ig/5 + 29000·Is)/1.5 = 2.018760e8
      EI (5.6.4.3-2) = (Ec·Ig/2.5)/1.5           = 2.770133e8  <- larger
      K: unbraced axis 2 = 2.1 (Table C4.6.2.5-1 (e)), axis 3 = 1.2 ((d)); braced K = 1.0 (δb)
      Screen: 2.1·240/12 = 42 > 22; 1.2·240/12 = 24 > 22 -> magnify both.
      Pe_b = π²·EI/(1.0·240)² = 47465.481; Pe_s2 = π²·EI/(2.1·240)² = 10763.148;
      Pe_s3 = π²·EI/(1.2·240)² = 32962.140 kip
      Envelope row: P_min = −800 kip (ruling M8), |M2| = 1800, |M3| = 600 kip-in; Cm = 1.0 (unbraced)
      δb = 1/(1 − 800/(0.75·47465.481)) = 1.0229891
      δs2 = 1/(1 − 800/(0.75·10763.148)) = 1.1100055 (single bent: ΣPu/ΣPe = Pu/Pe)
      δs3 = 1/(1 − 800/(0.75·32962.140)) = 1.0334426
      Mc = max(δb, δs)·M2 per axis: 1.1100055·1800, 1.0334426·600; Mu = hypot = 2092.0146 kip-in."""
    bent = {"slender": {"2": {"braced": False, "K_source": "default", "end_condition": "fixed-free",
                              "lu": 240.0},
                        "3": {"braced": False, "K_source": "default", "end_condition": "fixed-fixed",
                              "lu": 240.0},
                        "beta_d": 0.5}}
    row = {"Pu": -400.0, "Mu": math.hypot(1800.0, 600.0), "Vu": 1.0, "Tu": 0.0, "_case": "Env",
           "_bound": "envelope", "_Pmin": -800.0, "_Pmax": -400.0, "_M2": 1800.0, "_M3": 600.0,
           "_frame": "F1"}
    tf = cs.make_magnifier(bent, {}, {"slenderness_on": True})
    (t,) = tf(_cage(CAGE), [row])
    R = 1e-6
    assert tf.beta_d == 0.5 and tf.beta_d_source == "user override"
    assert t["_EI"] == pytest.approx(277013304.57355, rel=R)
    assert t["_Pe_b2"] == pytest.approx(47465.48142325, rel=R)
    assert t["_Pe_s2"] == pytest.approx(10763.14771502, rel=R)
    assert t["_Pe_s3"] == pytest.approx(32962.13987726, rel=R)
    assert t["_Cm2"] == 1.0 and t["_Cm3"] == 1.0 and t["_Pmag"] == 800.0
    assert t["_db2"] == pytest.approx(1.022989092981, rel=R)
    assert t["_ds2"] == pytest.approx(1.110005543387, rel=R)
    assert t["_ds3"] == pytest.approx(1.033442572230, rel=R)
    assert t["_delta2"] == pytest.approx(1.110005543387, rel=R)
    assert t["_delta3"] == pytest.approx(1.033442572230, rel=R)
    assert t["Mu"] == pytest.approx(2092.0146152953, rel=R)


def test_tension_row_not_magnified():
    bent = {"slender": {"2": {"braced": False, "lu": 240.0}, "3": {"braced": False, "lu": 240.0},
                        "beta_d": 0.5}}
    r = dict(_row(), Pu=50.0, _Pmin=50.0, _Pmax=50.0)
    (t,) = cs.make_magnifier(bent, {}, {"slenderness_on": True})(_cage(CAGE), [r])
    assert t["_delta2"] == t["_delta3"] == 1.0 and t["Mu"] == 100.0 and t["_Pmag"] == 0.0


def test_unstable_row_flagged_and_fails_search():
    bent = {"slender": {"2": {"braced": False, "lu": 1000.0}, "3": {"braced": False, "lu": 1000.0},
                        "beta_d": 0.5}}
    tf = cs.make_magnifier(bent, {}, {"slenderness_on": True})
    r = dict(_row(), Pu=-3000.0, _Pmin=-3000.0, _Pmax=-3000.0)
    (t,) = tf(_cage(CAGE), [r])
    # Pe_s2 = pi^2 EI / (2.1*1000)^2 ~ 620 kip << 3000 / 0.75
    assert t["_unstable"] and t["_unstable_reason"] == cs.UNSTABLE_REASON
    assert t["_ds2"] is None and t["_delta2"] is None and t["Mu"] == 100.0
    ok, dc, _, _ = cl2._row_flex(None, t)
    assert not ok and dc == math.inf
    lg = cl2.design_longitudinal(MEMBER, [r], None, tf)
    assert not lg.ok and cl2.UNSTABLE_NOTE in lg.note
    assert cl2.UNSTABLE_NOTE.startswith(cs.UNSTABLE_REASON)
    res = cl2.check_cage(MEMBER, CAGE, [r], tf)
    assert res[0]["flexStatus"] == "NG" and res[0]["_unstable"]


def test_magnified_rows_drive_more_steel():
    bent = {"slender": {"2": {"braced": False, "lu": 300.0}, "3": {"braced": False, "lu": 300.0},
                        "beta_d": 0.6}}
    rows = [{"Pu": -1500.0, "Mu": 30000.0, "Vu": 50.0, "Tu": 0.0, "_case": "C", "_step": "S",
             "_bound": "concurrent", "_Pmin": -1500.0, "_Pmax": -1500.0, "_M2": 24000.0,
             "_M3": 18000.0, "_frame": "F1"}]
    tf = cs.make_magnifier(bent, {}, {"slenderness_on": True})
    plain = cl2.design_longitudinal(MEMBER, rows)
    mag = cl2.design_longitudinal(MEMBER, rows, None, tf)
    assert plain.ok and mag.ok
    assert mag.Ast > plain.Ast
    off = cs.make_magnifier(bent, {}, {"slenderness_on": False})
    assert cl2.design_longitudinal(MEMBER, rows, None, off).Ast == plain.Ast


def test_beta_d_default_from_dead_rows_and_fallback():
    rows = [_fr(0.0, "Str", -900.0, 1200.0, 900.0), _fr(240.0, "Str", -910.0, 600.0, 450.0),
            _fr(0.0, "DC", -300.0, 300.0, 0.0, step=""), _fr(240.0, "DC", -310.0, 100.0, 0.0, step=""),
            _fr(0.0, "DW", -50.0, 100.0, 0.0, step="")]
    src = {"rows": rows, "frames": ["F1"], "categories": {"DW": "Dead"}}
    b = {"slender": {"gamma_p": 1.25}}
    w = []
    v, txt = cs.beta_d(b, src, w)
    # DC + DW at the top station: 300 + 100 = 400; max |Mu| = 1500 -> 1.25*400/1500
    assert v == pytest.approx(1.0 / 3.0) and "1.25" in txt and w == []
    # gamma_p default 1.25 (blank); override wins; cap at 1.0
    assert cs.beta_d({"slender": {"gamma_p": None}}, src)[0] == pytest.approx(1.0 / 3.0)
    assert cs.beta_d({"slender": {"beta_d": 0.2}}, src) == (0.2, "user override")
    assert cs.beta_d({"slender": {"gamma_p": 10.0}}, src)[0] == 1.0
    # no Dead rows -> 1.0 with a warning
    w = []
    src2 = {"rows": rows[:2], "frames": ["F1"], "categories": None}
    assert cs.beta_d(b, src2, w)[0] == 1.0 and w == [cs.NO_DEAD_WARNING]
    with pytest.raises(ValueError):
        cs.beta_d({"slender": {"beta_d": -0.1}}, src)
    with pytest.raises(ValueError):
        cs.beta_d({"slender": {"gamma_p": 0.0}}, src)


def test_K_braced_and_legacy():
    k = cs.resolve_K({"braced": False, "K_source": "default", "end_condition": "fixed-fixed"})
    assert (k["K"], k["K_unbraced"], k["K_braced"], k["K_braced_source"]) == (1.2, 1.2, 1.0, "default")
    k = cs.resolve_K({"braced": False, "K_braced_source": "analysis", "K_braced": 0.85, "K": 1.7})
    assert k["K"] == 1.7 and k["K_braced"] == 0.85
    assert any(cs.BRACED_K_LT1_NOTE in x for x in k["warnings"])
    # braced axis: the screen uses the braced K
    k = cs.resolve_K({"braced": True, "K_braced_source": "analysis", "K_braced": 0.9})
    assert k["K"] == 0.9 and k["K_unbraced"] is None
    # legacy state without K_braced: 1.0; a legacy braced analysis K is kept
    assert cs.resolve_K({"braced": False, "K": 2.1})["K_braced"] == 1.0
    assert cs.resolve_K({"braced": True, "K_source": "default"})["K_braced"] == 1.0
    k = cs.resolve_K({"braced": True, "K_source": "analysis", "K": 0.8})
    assert k["K"] == 0.8 and k["K_braced_source"] == "analysis"
    with pytest.raises(ValueError, match="braced K"):
        cs.resolve_K({"braced": False, "K_braced_source": "analysis", "K_braced": 0})
    with pytest.raises(ValueError, match="K_braced_source"):
        cs.resolve_K({"braced": False, "K_braced_source": "x"})
    # delta_b uses the braced K: Pe_b with K_braced, Pe_s with the unbraced K
    bent = {"slender": {"2": {"braced": False, "lu": 240.0, "K_braced_source": "analysis",
                              "K_braced": 0.8},
                        "3": {"braced": False, "lu": 240.0}, "beta_d": 0.5}}
    tf = cs.make_magnifier(bent, {}, {"slenderness_on": True})
    (t,) = tf(_cage(CAGE), [_row()])
    EI = t["_EI"]
    assert t["_Pe_b2"] == pytest.approx(math.pi ** 2 * EI / (0.8 * 240.0) ** 2)
    assert t["_Pe_b3"] == pytest.approx(math.pi ** 2 * EI / (1.0 * 240.0) ** 2)
    assert t["_Pe_s2"] == pytest.approx(math.pi ** 2 * EI / (2.1 * 240.0) ** 2)


def test_sway_group_sums():
    bent = {"slender": {"2": {"braced": False, "lu": 240.0}, "3": {"braced": True, "lu": 240.0},
                        "beta_d": 0.5}}
    sway = {"group": "G", "n_members": 3, "Pe_others": {"2": 20000.0, "3": 0.0},
            "Pu_others": {("C", "S1"): 1500.0}}
    w = []
    tf = cs.make_magnifier(bent, {}, {"slenderness_on": True}, w, sway=sway)
    (t,) = tf(_cage(CAGE), [_row()])
    sPe = t["_Pe_s2"] + 20000.0
    assert t["_sPe_s2"] == pytest.approx(sPe) and t["_sPu"] == pytest.approx(2000.0)
    assert t["_ds2"] == pytest.approx(1.0 / (1.0 - 2000.0 / (0.75 * sPe)))
    assert t["_ds3"] == 1.0 and not [x for x in w if "ΣPu" in x]
    # case not matched on every member -> Pu x n_members with a warning
    (t,) = tf(_cage(CAGE), [_row(case="X")])
    assert t["_sPu"] == pytest.approx(1500.0)
    w = [x for x in w if "ΣPu" in x]
    assert len(w) == 1 and "ΣPu = Pu × 3 members" in w[0]


def test_unstable_note_and_status_texts():
    assert cs.UNSTABLE_REASON == "magnification unstable (Pu ≥ φK·Pe)"
    assert cs.PHI_K == 0.75
    assert cs._RANK == {"neglect": 0, "magnified": 1, "refined analysis required": 2}
