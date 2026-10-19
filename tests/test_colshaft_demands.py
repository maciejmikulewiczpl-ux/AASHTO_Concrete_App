import math
import os

import pytest

from csi_import import ForceRow, parse_csi_frame_forces
import colshaft_demands as cd

FIX = os.path.join(os.path.dirname(__file__), "fixtures_csi", "frame1227_strI1.txt")


def _fixture():
    with open(FIX, encoding="utf-8") as f:
        return parse_csi_frame_forces(f.read())


def _row(frame="F1", st=0.0, case="C", step="", P=-100.0, V2=0.0, V3=0.0,
         T=0.0, M2=0.0, M3=0.0, env=False):
    return ForceRow(frame, st, case, "Combination", step, P, V2, V3, T, M2, M3,
                    env, 1)


CATS = {"Str-I1": "Strength"}


def test_resultants_hypot():
    r = _row(V2=3, V3=4, T=-7, M2=3, M3=4, P=-50)
    (d,) = cd.demand_rows([r], ["F1"], {"C": "Strength"}, "Strength")
    assert d["Mu"] == pytest.approx(5) and d["Vu"] == pytest.approx(5)
    assert d["Tu"] == 7 and d["Pu"] == -50
    assert (d["Vp"], d["Ms"], d["Ps"]) == (0, 0, 0)
    assert d["_bound"] == "concurrent" and d["_Pmin"] == d["_Pmax"] == -50
    assert d["_frame"] == "F1" and d["_case"] == "C" and d["_station"] == 0.0


@pytest.mark.parametrize("name,exp", [
    ("Str-I1", "Strength"), ("DEAD", "Dead"), ("DC1", "Dead"),
    ("EQ-X", "Extreme"), ("EXTREME", "Extreme"), ("Seismic", "Extreme"),
    ("Service-I", "Ignore"), ("FREQ", "Strength"), ("SEQUENCE", "Strength"),
    ("1.0DC+EQ", "Extreme"), ("1.25DC+1.75LL", "Strength"), ("SDC", "Strength"),
    ("DC", "Dead"), ("Dead-Cap", "Dead"), ("Ext-I", "Extreme"), ("Strength-III", "Strength"), ("dead load", "Dead"),
])
def test_category_defaults(name, exp):
    assert cd.default_case_category(name) == exp


def test_category_override_and_fallback():
    rows = [_row(case="A"), _row(case="Str-I1")]
    out = cd.demand_rows(rows, ["F1"], {"A": "Ignore"}, "Strength")
    assert [d["_case"] for d in out] == ["Str-I1"]


def test_envelope_bounding_rows():
    res = _fixture()
    out = cd.demand_rows(res.rows, ["1227"], CATS, "Strength")
    assert len(out) == 3
    d = out[0]
    assert d["_station"] == 0 and d["_bound"] == "envelope"
    assert d["Pu"] == pytest.approx(-2948.932) and d["_Pmax"] == d["Pu"]
    assert d["_Pmin"] == pytest.approx(-4347.776)
    assert d["Mu"] == pytest.approx(math.hypot(4720.0867, 14559.3567) * 12)
    assert d["Vu"] == pytest.approx(math.hypot(647.416, 473.349))
    assert d["Tu"] == pytest.approx(4523.3045 * 12)


def test_envelope_missing_min_warns():
    rows = [_row(step="Max", env=True, M2=5, P=-10)]
    w = []
    (d,) = cd.demand_rows(rows, ["F1"], {"C": "Strength"}, "Strength", warnings=w)
    assert d["Pu"] == -10 and d["_Pmin"] == -10 and d["Mu"] == 5
    assert len(w) == 1


def test_prune_dominated():
    res = _fixture()
    out = cd.demand_rows(res.rows, ["1227"], CATS, "Strength")
    kept = cd.prune_dominated(out)
    assert [k["_station"] for k in kept] == pytest.approx(
        [0, 8.4167 * 12, 16.8333 * 12])


def test_prune_dominated_logic():
    a = {"Pu": -5, "Mu": 1, "Vu": 1, "Tu": 1, "_Pmin": -6, "_Pmax": -5, "_frame": "F"}
    b = {"Pu": -4, "Mu": 2, "Vu": 2, "Tu": 2, "_Pmin": -7, "_Pmax": -4, "_frame": "F"}
    c = dict(b, _frame="G")
    assert cd.prune_dominated([a, b]) == [b]
    assert cd.prune_dominated([a, c]) == [a, c]          # other frame
    assert cd.prune_dominated([b, dict(b)]) == [b]       # equal: keep first
    narrow = dict(b, _Pmin=-5)
    assert len(cd.prune_dominated([a, narrow])) == 2     # range not contained


def test_collapse_member_screenshot():
    res = _fixture()
    out = cd.demand_rows(res.rows, ["1227"], CATS, "Strength")
    (d,) = cd.collapse_member(out)
    assert d["Pu"] == pytest.approx(-2768.491)
    assert d["_Pmin"] == pytest.approx(-4347.776)
    assert d["Mu"] == pytest.approx(math.hypot(5712.5384, 22053.4899) * 12)
    assert d["Vu"] == pytest.approx(math.hypot(647.416, 473.349))
    assert d["Tu"] == pytest.approx(4523.3045 * 12)


def test_detect_base_end_screenshot_is_min():
    res = _fixture()
    assert cd.detect_base_end(res.rows, ["1227"]) == "min"


def test_detect_base_end_tie_and_majority():
    tie = [_row(st=0, P=-5), _row(st=10, P=-5)]
    w = []
    assert cd.detect_base_end(tie, ["F1"], warnings=w) == "max" and w
    rows = [_row("A", 0, P=-9), _row("A", 10, P=-1),
            _row("B", 0, P=-9), _row("B", 10, P=-1),
            _row("C", 0, P=-1), _row("C", 10, P=-9)]
    assert cd.detect_base_end(rows, ["A", "B", "C"]) == "min"


def test_base_axial_picks_base_station():
    res = _fixture()
    p = cd.base_axial(res.rows, ["1227"], CATS, "Strength", "auto")
    assert sorted(p) == pytest.approx([-4347.776, -2948.932])
    p = cd.base_axial(res.rows, ["1227"], CATS, "Strength", "max")
    assert sorted(p) == pytest.approx([-4167.336, -2768.491])


def test_height_from_stations():
    res = _fixture()
    assert cd.column_height_in(res.rows, ["1227"]) == pytest.approx(202.0, abs=0.01)


def _conc():
    return [_row(st=0, case="L", step="Step1", P=-9, M2=10, M3=-20),
            _row(st=100, case="L", step="Step1", P=-1, M2=-30, M3=40),
            _row(st=0, case="L", step="Step2", P=-9, M2=1, M3=2)]


def test_end_moments_signed():
    em = cd.end_moments(_conc(), ["F1"], "L", "Step1")
    # base = min station (more compressive) -> bottom
    assert em == {"M2": (-30, 10), "M3": (40, -20)}


def test_end_moments_envelope_returns_none():
    res = _fixture()
    assert cd.end_moments(res.rows, ["1227"], "Str-I1", "Max") is None
    assert cd.end_moments(_conc(), ["F1"], "L", "Step9") is None
    assert cd.end_moments(_conc(), ["F1"], "L", "Step2") is None  # one end missing


def _stack():
    # given top-then-bottom, opposite station orientations
    def fr(name, p0, p100, m0, m100):
        return [_row(name, 0, case="L", step="S1", P=p0, M2=m0, M3=-m0),
                _row(name, 100, case="L", step="S1", P=p100, M2=m100, M3=-m100)]
    return fr("TOP", -80, -100, 21, 22) + fr("BOT", -200, -150, 11, 12)


def test_column_stack_order_and_axial_and_moments():
    rows = _stack()
    cats = {"L": "Strength"}
    assert cd.column_stack(rows, ["TOP", "BOT"]) == [("BOT", "min"), ("TOP", "max")]
    assert cd.detect_base_end(rows, ["TOP", "BOT"]) == "min"
    assert cd.base_axial(rows, ["TOP", "BOT"], cats, "Strength", "auto") == [-200]
    em = cd.end_moments(rows, ["TOP", "BOT"], "L", "S1")
    assert em == {"M2": (21, 11), "M3": (-21, -11)}


def test_column_stack_ambiguous_warning():
    rows = [_row("A", 0, P=-100), _row("A", 10, P=-50),
            _row("B", 0, P=-50), _row("B", 10, P=-100.2)]
    w = []
    cd.column_stack(rows, ["A", "B"], warnings=w)
    assert any("ambiguous" in x for x in w)


def test_height_multi_frame_sum():
    rows = [_row("A", 0), _row("A", 100), _row("B", 20), _row("B", 170)]
    assert cd.column_height_in(rows, ["A", "B"]) == pytest.approx(250)


def test_base_vote_excludes_extreme_rows():
    rows = [_row(st=0, case="Str-I1", P=-10), _row(st=100, case="Str-I1", P=-20),
            _row(st=0, case="EQ-X", P=-1000), _row(st=100, case="EQ-X", P=-5)]
    assert cd.detect_base_end(rows, ["F1"]) == "max"
    assert cd.base_axial(rows, ["F1"], {}, "Strength", "auto") == [-20]
    assert cd.base_axial(rows, ["F1"], {}, "Extreme", "auto") == [-5]
