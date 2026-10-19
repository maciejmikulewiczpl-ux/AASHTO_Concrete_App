"""Column-on-Shaft orchestrator (Task 8, colshaft_engine.run_colshaft).

Fixtures: tests/fixtures_csi/frame1227_strI1.txt (user sample, Strength envelope
only) and tests/fixtures_csi/colshaft_2bent.txt (synthetic, kip/ft/kip-ft):
  bent 1 = column frame 101 (D 60 in, H 20 ft) + shaft frame 102 (Ds 84 in);
  bent 2 = column frame 201 (D 54 in, H 25 ft), no shaft frames (soil basis).
Cases DEAD (Dead), Str-I / Str-II / Str-III (Strength envelopes), EQ-X (Extreme).
"""
import copy
import json
import math
import os
import time

import pytest

import colshaft_engine as ee
import colshaft_lrfd as cl
import colshaft_seismic as cs
import colshaft_shaft as csh
import csi_import as ci
from seismic_port.provisions import get_provisions

HERE = os.path.dirname(__file__)


def _read(name):
    with open(os.path.join(HERE, "fixtures_csi", name), encoding="utf-8") as f:
        return f.read()


PASTE_1227 = _read("frame1227_strI1.txt")
PASTE_2B = _read("colshaft_2bent.txt")

SOIL = {"layers": [
    {"thickness_ft": 20.0, "py_model": "welch_stiff_clay", "gamma_pcf": 125.0,
     "su_top_ksf": 2.5, "su_bot_ksf": 3.0, "eps50": 0.005},
    {"thickness_ft": 60.0, "py_model": "api_sand", "gamma_pcf": 125.0,
     "phi_deg": 36.0, "k_pci": 90.0, "submerged": True}], "J": 0.5, "cyclic": True}
COL1 = dict(D=60.0, fc=4.0, fy=60.0, cover=2.0, trans_type="hoop")
SHAFT1 = dict(D=84.0, fc=4.0, fy=60.0, cover=3.0, trans_type="hoop")
COL2 = dict(D=54.0, fc=4.0, fy=60.0, cover=2.0, trans_type="hoop")
SHAFT2 = dict(D=78.0, fc=4.0, fy=60.0, cover=3.0, trans_type="hoop")


def bent1(**kw):
    b = {"name": "B1", "col_frames": ["101"], "shaft_frames": ["102"], "column": dict(COL1),
         "shaft": dict(SHAFT1), "end_condition_long": "fixed-free",
         "end_condition_trans": "fixed-free", "shaft_basis": "cantilever", "L_eq_in": 120.0}
    b.update(kw)
    return b


def bent2(**kw):
    b = {"name": "B2", "col_frames": ["201"], "column": dict(COL2), "shaft": dict(SHAFT2),
         "soil": copy.deepcopy(SOIL), "L_embed_in": 720.0}
    b.update(kw)
    return b


def payload(bents, code="SDC 2.1", paste=PASTE_2B, **kw):
    p = {"paste": paste, "code": code, "bents": bents}
    p.update(kw)
    return p


def strict_json(r):
    s = json.dumps(r, allow_nan=False)
    assert json.loads(s) == r
    return s


_CACHE = {}


def run_cached(key, pl):
    if key not in _CACHE:
        _CACHE[key] = ee.run_colshaft(pl)
    return _CACHE[key]


def base_2b():
    return run_cached("2b", payload([bent1(), bent2()]))


def chk(b, name):
    m = [c for c in b["final_checks"] if c["name"] == name]
    assert len(m) == 1, (name, [c["name"] for c in b["final_checks"]])
    return m[0]


# ── end to end ──────────────────────────────────────────────────────

def test_end_to_end_fixture():
    """The user's kip-ft sample, two bents on frame 1227 (no Dead rows -> P_dead given)."""
    col = dict(D=84.0, fc=5.0, fy=60.0, cover=2.0, trans_type="hoop", hoop_closure="weld")
    shaft = dict(D=108.0, fc=5.0, fy=60.0, cover=3.0, trans_type="hoop")
    pl = payload([
        {"name": "A", "col_frames": ["1227"], "column": col, "shaft": shaft, "P_dead": -2500.0,
         "shaft_basis": "cantilever", "L_eq_in": 120.0, "H_in": 480.0},
        {"name": "B", "col_frames": ["1227"], "column": col, "shaft": shaft, "P_dead": -2500.0,
         "shaft_basis": "interface"}], paste=PASTE_1227)
    t = time.time()
    r = ee.run_colshaft(pl)
    dt = time.time() - t
    assert dt < 30.0, dt
    strict_json(r)
    assert r["parse"]["n_rows"] == 6 and r["parse"]["cases"] == ["Str-I1"]
    assert r["parse"]["categories"] == {"Str-I1": "Strength"}
    assert r["code"] == "SDC 2.1"
    a, b = r["bents"]
    assert (a["name"], b["name"]) == ("A", "B")
    for x in (a, b):
        assert x["status"] in ee.STATUS_RANK
        assert set(x["final"]) == {"col_long", "col_trans", "shaft_long", "shaft_trans"}
        assert x["lrfd"]["shaft"] is None                      # no shaft frames, no soil
        assert x["axial"]["P_dead"] == -2500.0 and x["axial"]["n_dead"] == 0
        assert x["axial"]["P_ext_min"] == x["axial"]["P_ext_max"] == -2500.0
        assert {c["group"] for c in x["final_checks"]} == {"Seismic", "Column LRFD"}
    assert a["H_in"] == 480.0
    assert b["H_in"] == pytest.approx(16.8333 * 12.0)          # station span (ruling 8-11)
    # same column / rows -> same LRFD cage on both bents
    assert a["final"]["col_long"] == b["final"]["col_long"]
    # the short bent cannot meet the seismic column shear: named NO SOLUTION
    assert b["status"] == "NO SOLUTION"
    assert any("Column seismic transverse" in s for s in b["no_solution"])


def test_end_to_end_two_bent_synthetic():
    t = time.time()
    r = base_2b()
    assert time.time() - t < 30.0
    strict_json(r)
    assert r["parse"]["categories"] == {"DEAD": "Dead", "Str-I": "Strength", "Str-II": "Strength",
                                        "Str-III": "Strength", "EQ-X": "Extreme"}
    b1, b2 = r["bents"]
    assert b1["status"] == b2["status"] == "OK"
    # ruling 8-10: P_dead = most compressive base Dead axial; Extreme range at the base
    assert b1["axial"]["P_dead"] == -950.0
    assert (b1["axial"]["P_ext_min"], b1["axial"]["P_ext_max"]) == (-1400.0, -500.0)
    assert b1["H_in"] == pytest.approx(240.0) and b2["H_in"] == pytest.approx(300.0)
    assert b1["lrfd"]["shaft"]["source"] == "shaft frames"
    assert b2["lrfd"]["shaft"]["source"] == csh.PY_SOURCE
    for b in (b1, b2):
        groups = {c["group"] for c in b["final_checks"]}
        assert groups == {"Seismic", "Column LRFD", "Shaft LRFD"}
        assert all(c["ok"] for c in b["final_checks"])
        # final longitudinal never lighter than the LRFD result
        assert b["final"]["col_long"]["Ast"] >= b["lrfd"]["col"]["long"]["Ast"] - 1e-9
        assert b["final"]["shaft_long"]["Ast"] >= b["lrfd"]["shaft"]["long"]["Ast"] - 1e-9


def test_strict_json_with_infinite_ratio():
    c = cs.Check("Soil-pile stability (p-y)", 1, 0, False, "x")
    d = ee.check_dict(c)
    assert d["ratio"] is None and d["ratio_infinite"] is True
    assert ee.sanitize({"a": math.inf, "b": [math.nan, 1.5, (2, -math.inf)], 3: True}) == \
        {"a": None, "b": [None, 1.5, [2, None]], "3": True}
    strict_json(ee.sanitize(c))


# ── overrides / final cage ──────────────────────────────────────────

def test_override_kept_and_fails():
    ov = {"col_long": {"bar": 5, "n": 6, "bundle": 1}}
    r = ee.run_colshaft(payload([bent1(override=ov)]))
    strict_json(r)
    b = r["bents"][0]
    assert b["final_source"]["col_long"] == "Override"
    assert {k: b["final"]["col_long"][k] for k in ("bar", "n", "bundle")} == \
        {"bar": 5, "n": 6, "bundle": 1}
    assert b["status"] == "NG"
    assert any(not c["ok"] and c["group"] == "Column LRFD" for c in b["final_checks"])
    assert b["no_solution"] == []
    rl = chk(b, "Column longitudinal ratio (rho_l)")
    assert rl["ok"] is False and rl["capacity"] == pytest.approx(6 * 0.31 / (math.pi * 900.0))


def test_override_transverse_kept():
    ov = {"col_trans": {"bar": 4, "s": 6.0, "ties": 0}, "shaft_trans": {"bar": 4, "s": 6.0}}
    b = ee.run_colshaft(payload([bent1(override=ov)]))["bents"][0]
    assert b["final_source"]["col_trans"] == b["final_source"]["shaft_trans"] == "Override"
    for k in ("col_trans", "shaft_trans"):
        assert (b["final"][k]["bar"], b["final"][k]["s"], b["final"][k]["ties"]) == (4, 6.0, 0)
    assert b["status"] in ("OK", "NG")                    # never "improved", never NO SOLUTION


def test_seismic_governs_transverse():
    b = base_2b()["bents"][0]
    assert b["final_source"]["col_trans"] == "Seismic"
    tr = b["lrfd"]["col"]["trans"]
    lrfd_avs = csh.av_per_s({"bar": tr["bar"], "s": tr["s"], "ties": tr["ties"]})
    assert b["final"]["col_trans"]["Av_s"] > lrfd_avs
    req = b["seismic"]["required_transverse"]
    assert (b["final"]["col_trans"]["bar"], b["final"]["col_trans"]["s"]) == (req["bar"], req["s"])
    assert chk(b, "Column shear")["ok"]


def test_heavier_trans_rule():
    a = {"bar": 5, "s": 4.0, "ties": 0}
    b = {"bar": 6, "s": 6.0, "ties": 0}            # 2*0.44/6 = 0.1467 < 2*0.31/4 = 0.155
    assert csh.heavier_trans(a, b) == (a, "a")
    c = {"bar": 6, "s": 0.44 / 0.31 * 4.0, "ties": 0}   # equal Av/s -> larger bar
    assert csh.heavier_trans(a, c)[1] == "b"
    assert csh.av_per_s({"bar": 5, "s": 4.0, "ties": 2}) == pytest.approx(4 * 0.31 / 4.0)


def test_mo_uses_final_cage():
    out = []
    for n in (14, 22):
        ov = {"col_long": {"bar": 10, "n": n, "bundle": 1}}
        out.append(ee.run_colshaft(payload([bent1(override=ov)]))["bents"][0]["seismic"])
    lo, hi = out
    assert hi["Mo"] > lo["Mo"] * 1.1
    assert hi["shaft_Mdemand"] > lo["shaft_Mdemand"]
    assert hi["Vo"] > lo["Vo"]


def test_bent_without_shaft_frames():
    r = run_cached("noshaft", payload([bent1(shaft_frames=[])]))
    b = r["bents"][0]
    assert b["lrfd"]["shaft"] is None
    names = {c["name"] for c in b["final_checks"] if c["group"] == "Seismic"}
    assert {"Shaft flexure (capacity protection)", "Shaft shear (capacity protection)",
            "Shaft oversize"} <= names
    assert not any(c["group"] == "Shaft LRFD" for c in b["final_checks"])
    assert b["final_source"]["shaft_long"] == "Seismic"
    assert b["final"]["shaft_long"]["n"] >= 6


# ── shaft seismic sizing (ruling 8-2) ───────────────────────────────

def test_first_passing_bisection():
    calls = []

    def pred(i):
        calls.append(i)
        return i >= 37
    assert csh.first_passing(list(range(100)), pred) == 37
    assert len(calls) <= 9
    assert csh.first_passing(list(range(10)), lambda i: False) is None
    assert csh.first_passing(list(range(10)), lambda i: True) == 0


def test_long_candidates_sorted_and_bounded():
    c = csh.long_candidates(SHAFT1, {"code": "SDC 2.1"})
    As = [x[0] for x in c]
    assert As == sorted(As) and len(c) > 50
    Ag = math.pi * 84.0 ** 2 / 4.0
    prov = get_provisions("SDC 2.1")
    assert all(prov.rho_l_min - 1e-9 <= a / Ag <= prov.rho_l_max + 1e-9 for a in As)
    assert all(x[1] >= cl.N_MIN for x in c)


def test_shaft_longitudinal_sized_for_capacity_protection():
    """SGS (factor 1.25) on bent 1: the LRFD shaft cage fails the shaft flexure
    check, so the shaft longitudinal steps up until it passes."""
    b = run_cached("sgs", payload([bent1()], code="AASHTO_SGS"))["bents"][0]
    assert b["final_source"]["shaft_long"] == "Seismic"
    assert b["final"]["shaft_long"]["Ast"] > b["lrfd"]["shaft"]["long"]["Ast"]
    assert chk(b, "Shaft flexure (capacity protection)")["ok"]
    assert chk(b, "Shaft confinement (oversized)")["ok"]
    # the next lighter candidate fails (lightest passing cage, bisection over As)
    c = [x for x in csh.long_candidates(SHAFT1, {"code": "AASHTO_SGS"})
         if x[0] < b["final"]["shaft_long"]["Ast"] - 1e-9]
    a = c[-1]
    S = cs.seismic_design(COL1, SHAFT1, ee.full_cage(b["final"]["col_long"], b["final"]["col_trans"]),
                          ee.full_cage(ee.long_cage(a[3], a[1], a[2], 84.0), b["final"]["shaft_trans"]),
                          {k: b["axial"][k] for k in ("P_dead", "P_ext_min", "P_ext_max")},
                          dict(bent1(), H_in=b["H_in"]), get_provisions("AASHTO_SGS"))
    assert not csh.checks_ok(S, (csh.SHAFT_FLEX,))


def test_shaft_transverse_sized_for_confinement():
    """SGS shaft confinement (rho_s,shaft >= 0.5 rho_s,col) with a heavy column
    transverse override drives the shaft transverse: the first candidate in
    transverse_candidates order (Av/s >= the LRFD one) that passes is taken."""
    pl = payload([bent1(override={"col_trans": {"bar": 8, "s": 3.0}})], code="AASHTO_SGS")
    b = ee.run_colshaft(pl)["bents"][0]
    strict_json(b)
    assert b["status"] == "OK"
    assert b["final_source"]["shaft_trans"] == "Seismic"
    t = b["final"]["shaft_trans"]
    assert (t["bar"], t["s"], t["ties"]) == (7, 3.0, 0)
    tr = b["lrfd"]["shaft"]["trans"]
    assert t["Av_s"] >= csh.av_per_s(tr)
    assert chk(b, "Shaft confinement (oversized)")["ok"]
    assert chk(b, "Shaft shear (capacity protection)")["ok"]
    # every earlier candidate fails the confinement demand
    prov = get_provisions("AASHTO_SGS")
    need = chk(b, "Shaft confinement (oversized)")["demand"]
    lg = b["final"]["shaft_long"]
    for bar, ties, s in cl.transverse_candidates({"code": "AASHTO_SGS"}):
        if (bar, s) == (7, 3.0):
            break
        sec = cs.to_section(SHAFT1, ee.full_cage(lg, ee.trans_cage(bar, s, ties)), prov)
        assert sec.rho_s < need


def test_shaft_sizing_no_solution_names_check():
    """A very long equivalent cantilever: no shaft cage within rho_l,max carries it."""
    pl = payload([bent1(shaft_frames=[], L_eq_in=2400.0)])
    b = ee.run_colshaft(pl)["bents"][0]
    assert b["status"] == "NO SOLUTION"
    assert any(s.startswith("Shaft flexure (capacity protection)") for s in b["no_solution"])


# ── strength rows through the pile (spec 4.4a, ruling 8-1) ─────────

def test_strength_rows_through_pile():
    b = base_2b()["bents"][1]
    sh = b["lrfd"]["shaft"]
    assert sh["source"] == csh.PY_SOURCE
    rows = sh["rows"]
    # 3 Strength cases -> 3 base rows; the top-5 M + top-5 V union is all of them
    assert len(rows) == 3
    assert {r["_case"] for r in rows} == {"Str-I", "Str-II", "Str-III"}
    for r in rows:
        assert r["_source"] == "p-y strength" and r["_station"] is None
        assert r["Mu"] >= r["_base_Mu"] and r["Vu"] >= r["_base_Vu"]
        assert r["_Pmin"] <= r["Pu"] <= r["_Pmax"]
    # interface M and V equal the base M and V (axial 0) within 0.5 %
    prof = cs.soil_profile(SOIL)
    S = b["seismic"]
    for r in rows:
        base = {"Pu": r["Pu"], "Mu": r["_base_Mu"], "Vu": r["_base_Vu"], "Tu": r["Tu"],
                "_Pmin": r["_Pmin"], "_Pmax": r["_Pmax"]}
        out, info = csh.pile_strength_row(base, b["H_in"], 720.0, S["EI_col"], S["EI_shaft"],
                                          78.0, prof, (2.0, 0.5), axial_comp=0.0)
        assert out is not None
        for x in info["bounds"]:
            assert x["stable"]
            assert x["M_interface"] == pytest.approx(r["_base_Mu"], rel=5e-3)
            assert x["V_interface"] == pytest.approx(r["_base_Vu"], rel=5e-3)


def test_head_moment_convention_and_physical_guard():
    """M_head = V*H - M_base (ruling 8-1).  With M_head close to V*H the solver's
    head-deflection guard reports 'unstable' although the shaft is loaded
    normally; the interface-based test accepts it and the interface carries M_base."""
    assert csh.head_loads(30000.0, 130.0, 240.0) == (130.0, 130.0 * 240.0 - 30000.0)
    prof = cs.soil_profile(SOIL)
    row = {"Pu": -1000.0, "Mu": 5000.0, "Vu": 400.0, "Tu": 10.0, "_Pmin": -1500.0}
    out, info = csh.pile_strength_row(row, 240.0, 720.0, 4e8, 9e8, 84.0, prof, (2.0, 0.5),
                                      axial_comp=0.0)
    stiff = info["bounds"][0]
    assert stiff["solver_stable"] is False and stiff["stable"] is True
    assert stiff["M_interface"] == pytest.approx(5000.0, rel=5e-3)
    assert out["Mu"] > 5000.0 and out["Vu"] >= 400.0
    # default axial = most compression (-_Pmin), compression-positive for the solver
    _, info2 = csh.pile_strength_row(row, 240.0, 720.0, 4e8, 9e8, 84.0, prof, (2.0,))
    assert info2["axial_comp"] == 1500.0


def test_governing_base_rows_top5_union():
    rows = [{"Mu": float(i), "Vu": float(20 - i), "_case": str(i)} for i in range(20)]
    sel = csh.governing_base_rows(rows)
    assert [r["_case"] for r in sel] == ["0", "1", "2", "3", "4", "15", "16", "17", "18", "19"]
    rows2 = [{"Mu": float(i), "Vu": float(i), "_case": str(i)} for i in range(20)]
    assert len(csh.governing_base_rows(rows2)) == 5


def test_unstable_strength_row_skipped_with_warning():
    soft = {"layers": [{"thickness_ft": 80.0, "py_model": "matlock_soft_clay",
                        "gamma_pcf": 110.0, "su_top_ksf": 0.1, "su_bot_ksf": 0.15,
                        "eps50": 0.02, "submerged": True}], "J": 0.5, "cyclic": True}
    w = []
    prof = cs.soil_profile(soft)
    rows = [{"Pu": -1000.0, "Mu": 9e5, "Vu": 3000.0, "Tu": 0.0, "_case": "X",
             "_Pmin": -1500.0, "_Pmax": -1000.0}]
    out = csh.strength_rows_through_pile(rows, 240.0, 120.0, 4e8, 9e8, 66.0, prof,
                                         (0.5,), w)
    assert out == [] and len(w) == 1 and "unstable" in w[0]


# ── slenderness (ruling 8-7) ────────────────────────────────────────

SLENDER = {"2": {"braced": False, "K": 2.1, "lu": None},
           "3": {"braced": False, "K": 2.1, "lu": None}, "beta_d": None, "gamma_p": 1.25}


def test_slenderness_toggle_changes_only_when_on():
    off = base_2b()["bents"][0]
    off2 = ee.run_colshaft(payload([bent1(slender=SLENDER), bent2()],
                                   settings={"slenderness_on": False}))["bents"][0]
    assert off2["final"] == off["final"] and off2["status"] == off["status"]
    assert all("_slender_status" not in r for r in off2["lrfd"]["col"]["check_rows"])
    on = ee.run_colshaft(payload([bent1(slender=SLENDER)],
                                 settings={"slenderness_on": True}))["bents"][0]
    # lu = H + L_eq = 240 + 120 in; r = 15 in; K lu / r = 2.1*360/15 = 50.4 -> pending (S6)
    rows = on["lrfd"]["col"]["check_rows"]
    assert rows and all(r["_slender_status"] == "magnification pending verification (S6)"
                        for r in rows)
    assert rows[0]["_klr2"] == pytest.approx(2.1 * 360.0 / 15.0)
    assert on["final"] == off["final"] and on["status"] == "OK"
    assert any("not yet applied" in x for x in on["warnings"])
    # K lu / r >= 100 -> refined analysis required, never OK
    big = dict(SLENDER, **{"2": {"braced": False, "K": 2.1, "lu": 800.0}})
    rf = ee.run_colshaft(payload([bent1(slender=big)],
                                 settings={"slenderness_on": True}))["bents"][0]
    assert rf["status"] == "REFINED ANALYSIS REQUIRED"
    assert rf["final"] == off["final"]


def test_slenderness_lu_default_uses_soil_df():
    on = ee.run_colshaft(payload([bent2(slender=SLENDER)],
                                 settings={"slenderness_on": True}))["bents"][0]
    Df = on["seismic"]["pile"]["Df_eq_gov"]
    assert Df and on["Df_for_lu"] == Df
    r0 = on["lrfd"]["col"]["check_rows"][0]
    assert r0["_klr2"] == pytest.approx(2.1 * (300.0 + Df) / (0.25 * 54.0))


def test_bent_status_precedence():
    assert ee.bent_status(True, True, True) == "NO SOLUTION"
    assert ee.bent_status(False, True, True) == "REFINED ANALYSIS REQUIRED"
    assert ee.bent_status(False, False, True) == "NG"
    assert ee.bent_status(False, False, False) == "OK"


# ── envelope mode (ruling 8-8) ──────────────────────────────────────

def test_member_mode_never_less_steel_than_station_mode():
    st = base_2b()["bents"]
    mb = ee.run_colshaft(payload([bent1(), bent2()],
                                 settings={"envelope_mode": "member"}))
    assert mb["settings"]["envelope_mode"] == "member"
    for s, m in zip(st, mb["bents"]):
        assert m["lrfd"]["col"]["n_rows"] == 1
        assert m["lrfd"]["col"]["long"]["Ast"] >= s["lrfd"]["col"]["long"]["Ast"] - 1e-9
        assert m["final"]["col_long"]["Ast"] >= s["final"]["col_long"]["Ast"] - 1e-9
        assert m["final"]["col_trans"]["Av_s"] >= s["final"]["col_trans"]["Av_s"] - 1e-12
        assert m["final"]["shaft_long"]["Ast"] >= s["final"]["shaft_long"]["Ast"] - 1e-9


def test_envelope_mode_validated():
    with pytest.raises(ValueError, match="envelope_mode"):
        ee.run_colshaft(payload([bent1()], settings={"envelope_mode": "bent"}))


# ── input validation / warnings ─────────────────────────────────────

def test_unknown_code_raises():
    with pytest.raises(ValueError, match="Unknown seismic code"):
        ee.run_colshaft(payload([bent1()], code="SDC 9.9"))
    for k in ("SDC_2_0", "AASHTO_SGS", "SDC 2.1", "AASHTO SGS 3rd Ed."):
        assert ee.validate_code(k) is get_provisions(k)


def test_missing_dead_requires_p_dead():
    with pytest.raises(ValueError, match="P_dead"):
        ee.run_colshaft(payload([{"name": "X", "col_frames": ["1227"], "column": COL1,
                                  "shaft": SHAFT1, "L_eq_in": 120.0}], paste=PASTE_1227))


def test_p_dead_is_most_compressive_dead_row():
    w = []
    pr = ci.parse_csi_frame_forces(PASTE_2B)
    ax = ee.seismic_axial({"name": "B1"}, pr.rows, ["101"], None, "auto", w)
    assert ax["P_dead"] == -950.0
    ax = ee.seismic_axial({"name": "B1"}, pr.rows, ["101"], None, "max", w)
    assert ax["P_dead"] == -900.0           # forced base end -> top-of-frame row


def test_warnings_collected():
    r = ee.run_colshaft(payload([bent1(col_frames=["101", "999"])]))
    b = r["bents"][0]
    assert any("frame 999 not found" in x for x in b["warnings"])
    assert any(x.startswith("B1: ") and "frame 999" in x for x in r["parse"]["warnings"])
