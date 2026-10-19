"""Column-on-Shaft orchestrator (Task 8, colshaft_engine.run_colshaft).

Fixtures: tests/fixtures_csi/frame1227_strI1.txt (user sample, Strength envelope
only) and tests/fixtures_csi/colshaft_2bent.txt (synthetic, kip/ft/kip-ft):
  bent 1 = column frame 101 (D 60 in, H 20 ft) + shaft frame 102 (Ds 84 in);
  bent 2 = column frame 201 (D 54 in, H 25 ft), no shaft frames (soil basis).
Cases DEAD (Dead), Str-I / Str-II / Str-III (Strength envelopes), EQ-X (Extreme).

Runs are expensive (seconds), so each distinct payload runs once per session
(RUNS) and several tests share it.
"""
import copy
import json
import math
import os
import time
from dataclasses import replace

import pytest

import colshaft_engine as ee
import colshaft_lrfd as cl
import colshaft_seismic as cs
import colshaft_shaft as csh
import csi_import as ci
from seismic_port.pile_solver import solve_lateral
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
SOFT = {"layers": [{"thickness_ft": 80.0, "py_model": "matlock_soft_clay", "gamma_pcf": 110.0,
                    "su_top_ksf": 0.1, "su_bot_ksf": 0.15, "eps50": 0.02, "submerged": True}],
        "J": 0.5, "cyclic": True}
COL1 = dict(D=60.0, fc=4.0, fy=60.0, cover=2.0, trans_type="hoop")
SHAFT1 = dict(D=84.0, fc=4.0, fy=60.0, cover=3.0, trans_type="hoop")
COL2 = dict(D=54.0, fc=4.0, fy=60.0, cover=2.0, trans_type="hoop")
SHAFT2 = dict(D=78.0, fc=4.0, fy=60.0, cover=3.0, trans_type="hoop")
SLENDER = {"2": {"braced": False, "K": 2.1, "lu": None},
           "3": {"braced": False, "K": 2.1, "lu": None}, "beta_d": None, "gamma_p": 1.25}


def bent1(**kw):
    b = {"name": "B1", "col_frames": ["101"], "shaft_frames": ["102"], "column": dict(COL1),
         "shaft": dict(SHAFT1), "end_condition_long": "fixed-free",
         "end_condition_trans": "fixed-free", "shaft_basis": "cantilever", "L_eq_in": 120.0,
         "slender": copy.deepcopy(SLENDER)}
    b.update(kw)
    return b


def bent2(**kw):
    b = {"name": "B2", "col_frames": ["201"], "column": dict(COL2), "shaft": dict(SHAFT2),
         "soil": copy.deepcopy(SOIL), "L_embed_in": 720.0, "slender": copy.deepcopy(SLENDER)}
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


BIG = dict(SLENDER, **{"2": {"braced": False, "K": 2.1, "lu": 800.0}})
PAYLOADS = {
    # base run (slender key present, slenderness off by default)
    "2b": lambda: payload([bent1(), bent2()]),
    # 6-#5 column override + #4 @ 6 shaft transverse override + a missing frame
    "ov": lambda: payload([bent1(col_frames=["101", "999"], override={
        "col_long": {"bar": 5, "n": 6, "bundle": 1}, "col_trans": {"bar": 4, "s": 6.0},
        "shaft_trans": {"bar": 4, "s": 6.0}})]),
    "mo_hi": lambda: payload([bent1(override={"col_long": {"bar": 10, "n": 22, "bundle": 1}})]),
    # SGS + heavy column transverse override: drives shaft long + trans sizing
    "sgs": lambda: payload([bent1(override={"col_trans": {"bar": 8, "s": 3.0}})],
                           code="AASHTO_SGS"),
    # no shaft frames, very long cantilever: shaft flexure cannot be met
    "nosol": lambda: payload([bent1(shaft_frames=[], L_eq_in=2400.0)]),
    "slender": lambda: payload([bent1(), bent1(name="B1R", slender=BIG)],
                               settings={"slenderness_on": True}),
    "member": lambda: payload([bent1(), bent2()], settings={"envelope_mode": "member"}),
}
RUNS = {}


def run(key):
    if key not in RUNS:
        t = time.time()
        RUNS[key] = ee.run_colshaft(PAYLOADS[key]())
        RUNS[key + ":t"] = time.time() - t
    return RUNS[key]


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
        assert x["axial"]["P_dead"] == -2500.0 and x["axial"]["dead_cases"] == {}
        assert x["axial"]["P_ext_min"] == x["axial"]["P_ext_max"] == -2500.0
        assert {c["group"] for c in x["final_checks"]} == {"Seismic", "Column LRFD"}
    assert a["H_in"] == 480.0
    assert b["H_in"] == pytest.approx(16.8333 * 12.0)          # station span (ruling 8-11)
    assert a["final"]["col_long"] == b["final"]["col_long"]
    # the short bent cannot meet the seismic column shear: named NO SOLUTION
    assert b["status"] == "NO SOLUTION"
    assert any("Column seismic transverse" in s for s in b["no_solution"])


def test_end_to_end_two_bent_synthetic():
    r = run("2b")
    assert RUNS["2b:t"] < 30.0
    strict_json(r)
    assert r["parse"]["categories"] == {"DEAD": "Dead", "Str-I": "Strength", "Str-II": "Strength",
                                        "Str-III": "Strength", "EQ-X": "Extreme"}
    b1, b2 = r["bents"]
    assert b1["status"] == b2["status"] == "OK"
    assert b1["axial"]["P_dead"] == -950.0 and b1["axial"]["dead_cases"] == {"DEAD": -950.0}
    assert (b1["axial"]["P_ext_min"], b1["axial"]["P_ext_max"]) == (-1400.0, -500.0)
    assert b1["H_in"] == pytest.approx(240.0) and b2["H_in"] == pytest.approx(300.0)
    assert b1["lrfd"]["shaft"]["source"] == "shaft frames"
    assert b2["lrfd"]["shaft"]["source"] == csh.PY_SOURCE
    for b in (b1, b2):
        groups = {c["group"] for c in b["final_checks"]}
        assert groups == {"Seismic", "Column LRFD", "Shaft LRFD"}
        assert all(c["ok"] for c in b["final_checks"])
        assert b["final"]["col_long"]["Ast"] >= b["lrfd"]["col"]["long"]["Ast"] - 1e-9
        assert b["final"]["shaft_long"]["Ast"] >= b["lrfd"]["shaft"]["long"]["Ast"] - 1e-9
        # slenderness off (default) although bent.slender is given: no tags
        assert all("_slender_status" not in x for x in b["lrfd"]["col"]["check_rows"])
    assert chk(b2, "Shaft p-y strength solve")["ok"]


def test_strict_json_with_infinite_ratio():
    c = cs.Check("Soil-pile stability (p-y)", 1, 0, False, "x")
    d = ee.check_dict(c)
    assert d["ratio"] is None and d["ratio_infinite"] is True
    assert ee.sanitize({"a": math.inf, "b": [math.nan, 1.5, (2, -math.inf)], 3: True}) == \
        {"a": None, "b": [None, 1.5, [2, None]], "3": True}
    strict_json(ee.sanitize(c))


# ── overrides / final cage ──────────────────────────────────────────

def test_override_kept_and_fails():
    r = run("ov")
    strict_json(r)
    b = r["bents"][0]
    assert b["final_source"]["col_long"] == "Override"
    assert {k: b["final"]["col_long"][k] for k in ("bar", "n", "bundle")} == \
        {"bar": 5, "n": 6, "bundle": 1}
    assert b["status"] == "NG"
    assert any(not c["ok"] and c["group"] == "Column LRFD" for c in b["final_checks"])
    assert b["no_solution"] == []
    rl = chk(b, "Column longitudinal ratio (rho_l)")
    r_l = 6 * 0.31 / (math.pi * 900.0)
    assert rl["ok"] is False and rl["capacity"] == pytest.approx(r_l)
    assert rl["ratio"] == pytest.approx(0.01 / r_l)              # max(lo/r, r/hi)


def test_override_transverse_kept():
    sh = run("ov")["bents"][0]                           # shaft_trans #4 @ 6 override
    assert sh["final_source"]["shaft_trans"] == "Override"
    t = sh["final"]["shaft_trans"]
    assert (t["bar"], t["s"], t["ties"]) == (4, 6.0, 0)
    # weak COLUMN transverse override #4 @ 6: kept as entered (never upgraded by the
    # seismic merge or the 8-15 walk), checks fail -> NG, not NO SOLUTION
    assert sh["final_source"]["col_trans"] == "Override"
    t = sh["final"]["col_trans"]
    assert (t["bar"], t["s"], t["ties"]) == (4, 6.0, 0)
    assert sh["lrfd"]["col"]["trans"] is None
    assert chk(sh, "Transverse steel ratio (min)")["ok"] is False      # rho_s #4 @ 6 too low
    assert sh["status"] == "NG" and sh["no_solution"] == []
    col = run("sgs")["bents"][0]                         # col_trans #8 @ 3 override
    assert col["final_source"]["col_trans"] == "Override"
    t = col["final"]["col_trans"]
    assert (t["bar"], t["s"], t["ties"]) == (8, 3.0, 0)
    assert col["status"] == "OK"
    assert col["lrfd"]["col"]["trans"] is None           # never designed


def test_shaft_rho_l_checked_only_when_overridden():
    names = {c["name"] for c in run("2b")["bents"][0]["final_checks"]}
    assert "Shaft longitudinal ratio (rho_l)" not in names
    prov = get_provisions("SDC 2.1")
    c = ee.rho_l_check(ee.long_cage(5, 6, 1, 84.0), prov, "Shaft")
    assert c["name"] == "Shaft longitudinal ratio (rho_l)" and c["ok"] is False
    hi = ee.rho_l_check({"rho_l": 0.05}, prov)
    assert hi["ok"] is False and hi["ratio"] == pytest.approx(0.05 / prov.rho_l_max)


def test_seismic_governs_transverse():
    b = run("2b")["bents"][0]
    assert b["final_source"]["col_trans"] == "Seismic"
    tr = b["lrfd"]["col"]["trans"]
    assert b["final"]["col_trans"]["Av_s"] > csh.av_per_s(tr)
    req = b["seismic"]["required_transverse"]
    assert (b["final"]["col_trans"]["bar"], b["final"]["col_trans"]["s"]) == (req["bar"], req["s"])
    assert b["final"]["col_trans"]["ties"] == max(tr["ties"], req["ties"])
    assert chk(b, "Column shear")["ok"]


def test_merge_trans_rule():
    a = {"bar": 5, "s": 4.0, "ties": 0}
    b = {"bar": 6, "s": 6.0, "ties": 0}            # 2*0.44/6 = 0.1467 < 2*0.31/4 = 0.155
    assert csh.heavier_trans(a, b) == (a, "a")
    c = {"bar": 6, "s": 0.44 / 0.31 * 4.0, "ties": 0}   # equal Av/s -> larger bar
    assert csh.heavier_trans(a, c)[1] == "b"
    assert csh.av_per_s({"bar": 5, "s": 4.0, "ties": 2}) == pytest.approx(4 * 0.31 / 4.0)
    # ruling 8-15: bar / pitch of the larger Av/s, ties = max of both
    m, which = csh.merge_trans({"bar": 5, "s": 4.0, "ties": 2}, {"bar": 8, "s": 4.0, "ties": 0})
    assert (m["bar"], m["s"], m["ties"], which) == (8, 4.0, 2, "b")


def test_walk_trans_from_start():
    seq = list(cl.transverse_candidates(None))
    start = csh.trans_cage(*[seq[10][i] for i in (0, 2, 1)])
    seen = []

    def ok(t):
        seen.append((t["bar"], t["ties"], t["s"]))
        return len(seen) == 4
    t = csh.walk_trans(start, None, ok)
    assert seen == [(b, n, s) for b, n, s in seq[10:14]]
    assert (t["bar"], t["ties"], t["s"]) == seq[13]
    assert csh.walk_trans(start, None, lambda t: False) is None


def test_merged_cage_failing_lrfd_walks_to_next(monkeypatch):
    """If the merged column cage fails the LRFD rows (both designs passed
    separately), the next candidate passing both is taken (ruling 8-15)."""
    base = run("2b")["bents"][0]["final"]["col_trans"]
    bad = (base["bar"], base["s"], base["ties"])
    real = ee.rows_pass

    def fake(member, cage, rows, tf):
        if member is not None and float(member["D"]) == 60.0 and \
                (cage["trans_bar"], cage["s"], cage["ties"]) == bad:
            return False
        return real(member, cage, rows, tf)
    monkeypatch.setattr(ee, "rows_pass", fake)
    b = ee.run_colshaft(payload([bent1()]))["bents"][0]
    strict_json(b)
    t = b["final"]["col_trans"]
    assert b["final_source"]["col_trans"] == "LRFD+Seismic"
    seq = [(x[0], x[1], round(x[2], 2)) for x in cl.transverse_candidates({"code": "SDC 2.1"})]
    k = seq.index((bad[0], bad[2], round(bad[1], 2)))
    assert seq.index((t["bar"], t["ties"], round(t["s"], 2))) > k
    assert b["status"] == "OK"


def test_merged_shaft_cage_failing_lrfd_walks_to_next(monkeypatch):
    """Shaft branch of ruling 8-15: the shaft cage fails its LRFD rows on the final
    cages although the LRFD design passed -> walk to the next candidate passing the
    shaft LRFD rows and the shaft seismic checks."""
    base = run("2b")["bents"][0]["final"]["shaft_trans"]
    bad = (base["bar"], base["s"], base["ties"])
    real = ee.rows_pass

    def fake(member, cage, rows, tf):
        if float(member["D"]) == 84.0 and (cage["trans_bar"], cage["s"], cage["ties"]) == bad:
            return False
        return real(member, cage, rows, tf)
    monkeypatch.setattr(ee, "rows_pass", fake)
    b = ee.run_colshaft(payload([bent1()]))["bents"][0]
    strict_json(b)
    t = b["final"]["shaft_trans"]
    assert b["final_source"]["shaft_trans"] == "LRFD+Seismic"
    seq = [(x[0], x[1], round(x[2], 2)) for x in cl.transverse_candidates({"code": "SDC 2.1"})]
    assert seq.index((t["bar"], t["ties"], round(t["s"], 2))) > \
        seq.index((bad[0], bad[2], round(bad[1], 2)))
    assert b["status"] == "OK"
    assert b["Df_for_lu"] == 120.0                  # recomputed after the walk (cantilever L_eq)


def test_walk_trans_start_not_in_candidates():
    """A merged cage with extra ties is not a candidate: the walk starts at the
    first candidate whose Av/s >= the merged cage's, never at index 0."""
    start = csh.trans_cage(5, 4.0, 3)               # maxLegs 2 -> ties 0 only in the list
    floor = csh.av_per_s(start)
    seq = list(cl.transverse_candidates(None))
    first = next(c for c in seq if csh.av_per_s({"bar": c[0], "s": c[2], "ties": c[1]}) >= floor)
    seen = []
    csh.walk_trans(start, None, lambda t: seen.append((t["bar"], t["ties"], t["s"])) or True)
    assert seen == [first] and seq.index(first) > 0
    assert csh.walk_trans(csh.trans_cage(8, 0.5, 6), None, lambda t: True) is None


def test_mo_uses_final_cage():
    lo = run("ov")["bents"][0]["seismic"]                  # 6-#5
    hi = run("mo_hi")["bents"][0]["seismic"]               # 22-#10
    assert hi["Mo"] > lo["Mo"] * 1.1
    assert hi["shaft_Mdemand"] > lo["shaft_Mdemand"]
    assert hi["Vo"] > lo["Vo"]


def test_bent_without_shaft_frames():
    r = run("nosol")
    strict_json(r)
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


def _seis(b, sh_long, sh_trans, code):
    return cs.seismic_design(COL1, SHAFT1, ee.full_cage(b["final"]["col_long"], b["final"]["col_trans"]),
                             ee.full_cage(sh_long, sh_trans),
                             {k: b["axial"][k] for k in ("P_dead", "P_ext_min", "P_ext_max")},
                             dict(bent1(), H_in=b["H_in"]), get_provisions(code))


def test_shaft_longitudinal_sized_for_capacity_protection():
    """SGS (factor 1.25): the LRFD shaft cage fails the shaft flexure check, so the
    shaft longitudinal steps up until it passes; the next lighter cage fails."""
    b = run("sgs")["bents"][0]
    strict_json(b)
    assert b["final_source"]["shaft_long"] == "Seismic"
    assert b["final"]["shaft_long"]["Ast"] > b["lrfd"]["shaft"]["long"]["Ast"]
    assert chk(b, "Shaft flexure (capacity protection)")["ok"]
    c = [x for x in csh.long_candidates(SHAFT1, {"code": "AASHTO_SGS"})
         if x[0] < b["final"]["shaft_long"]["Ast"] - 1e-9]
    a = c[-1]
    tr = b["lrfd"]["shaft"]["trans"]                # the transverse the long sizing used
    S = _seis(b, ee.long_cage(a[3], a[1], a[2], 84.0), ee.trans_cage(tr["bar"], tr["s"], tr["ties"]),
              "AASHTO_SGS")
    assert not csh.checks_ok(S, (csh.SHAFT_FLEX,))


def test_shaft_transverse_sized_for_confinement():
    """SGS shaft confinement (rho_s,shaft >= 0.5 rho_s,col) with a heavy column
    transverse override drives the shaft transverse: the first candidate in
    transverse_candidates order (Av/s >= the LRFD one) that passes is taken."""
    b = run("sgs")["bents"][0]
    assert b["status"] == "OK"
    assert b["final_source"]["shaft_trans"] == "Seismic"
    t = b["final"]["shaft_trans"]
    assert (t["bar"], t["s"], t["ties"]) == (7, 3.0, 0)
    assert t["Av_s"] >= csh.av_per_s(b["lrfd"]["shaft"]["trans"])
    assert chk(b, "Shaft confinement (oversized)")["ok"]
    assert chk(b, "Shaft shear (capacity protection)")["ok"]
    prov = get_provisions("AASHTO_SGS")
    need = chk(b, "Shaft confinement (oversized)")["demand"]
    lg = b["final"]["shaft_long"]
    for bar, ties, s in cl.transverse_candidates({"code": "AASHTO_SGS"}):
        if (bar, s) == (7, 3.0):
            break
        sec = cs.to_section(SHAFT1, ee.full_cage(lg, ee.trans_cage(bar, s, ties)), prov)
        assert sec.rho_s < need


def test_shaft_trans_screen_matches_full_check():
    """The cheap screen of size_shaft_transverse uses exactly seismic_design's shaft
    shear / confinement inputs: screen pass <=> full-check pass."""
    b = run("sgs")["bents"][0]
    lg = b["final"]["shaft_long"]
    S0 = _seis(b, lg, b["final"]["shaft_trans"], "AASHTO_SGS")
    prov = get_provisions("AASHTO_SGS")
    outcomes = set()
    for bar, s in ((6, 3.0), (7, 3.25), (7, 3.0), (8, 4.0)):
        t = ee.trans_cage(bar, s, 0)
        scr = csh.shaft_trans_screen(SHAFT1, prov, S0, lg, t)
        full = csh.checks_ok(_seis(b, lg, t, "AASHTO_SGS"), csh.SHAFT_TRANS)
        assert scr == full, (bar, s)
        outcomes.add(scr)
    assert outcomes == {True, False}


def test_shaft_sizing_no_solution_names_check():
    """A very long equivalent cantilever: no shaft cage within rho_l,max carries it."""
    b = run("nosol")["bents"][0]
    assert b["status"] == "NO SOLUTION"
    assert any(s.startswith("Shaft flexure (capacity protection)") for s in b["no_solution"])


# ── strength rows through the pile (spec 4.4a, rulings 8-12 / 8-13) ─

def test_strength_rows_through_pile():
    b = run("2b")["bents"][1]
    sh = b["lrfd"]["shaft"]
    assert sh["source"] == csh.PY_SOURCE
    rows = sh["rows"]
    # 3 Strength cases -> 3 base rows; the top-5 M + top-5 V union is all of them
    assert len(rows) == 3
    assert {r["_case"] for r in rows} == {"Str-I", "Str-II", "Str-III"}
    prof = cs.soil_profile(SOIL)
    EI = b["seismic"]["EI_shaft"]
    for r in rows:
        assert r["_source"] == "p-y strength" and r["_station"] is None
        assert r["Mu"] >= r["_base_Mu"] and r["Vu"] >= r["_base_Vu"]
        assert r["_Pmin"] <= r["Pu"] <= r["_Pmax"]
        base = {"Pu": r["Pu"], "Mu": r["_base_Mu"], "Vu": r["_base_Vu"], "Tu": r["Tu"],
                "_Pmin": r["_Pmin"], "_Pmax": r["_Pmax"]}
        # interface M and V equal the base M and V (axial 0) within 0.5 %
        out, info = csh.pile_strength_row(base, 720.0, EI, 78.0, prof, (2.0, 0.5), axial_comp=0.0)
        assert out is not None
        for x in info["bounds"]:
            assert x["stable"]
            assert x["M_interface"] == pytest.approx(r["_base_Mu"], rel=5e-3)
            assert x["V_interface"] == pytest.approx(r["_base_Vu"], rel=5e-3)


def test_head_moment_same_sense_as_shear():
    """Shaft alone (Hcol = 0): M_head = -M_base puts +M_base at the top of shaft and
    the moment grows below it (same sense as V); the result matches a cantilever
    load V at height M/V on the column + shaft model (mesh difference < 5 %)."""
    assert csh.head_loads(5000.0, 400.0) == (400.0, -5000.0)
    prof = cs.soil_profile(SOIL)
    s = solve_lateral(0.0, 720.0, 9e8, 9e8, 84.0, 0.0, prof, 400.0, M_head=-5000.0)
    assert s.stable and s.ground_index == 0
    assert s.moment[0] == pytest.approx(5000.0, rel=1e-6)
    assert s.moment[1] > s.moment[0] > 0
    cant = solve_lateral(12.5, 720.0, 9e8, 9e8, 84.0, 0.0, prof, 400.0)
    assert s.max_inground_moment == pytest.approx(cant.max_inground_moment, rel=0.05)
    assert s.max_moment_depth == pytest.approx(cant.max_moment_depth, abs=1e-6)
    wrong = solve_lateral(0.0, 720.0, 9e8, 9e8, 84.0, 0.0, prof, 400.0, M_head=+5000.0)
    assert wrong.moment[0] == pytest.approx(-5000.0, rel=1e-6)


def test_inground_moment_grows_with_axial():
    prof = cs.soil_profile(SOIL)
    row = {"Pu": -1000.0, "Mu": 5000.0, "Vu": 400.0, "Tu": 0.0}
    ms = []
    for P in (0.0, 2000.0, 6000.0, 12000.0):
        _, info = csh.pile_strength_row(row, 720.0, 9e8, 84.0, prof, (0.5,), axial_comp=P)
        x = info["bounds"][0]
        assert x["stable"] and x["M_interface"] == pytest.approx(5000.0, rel=5e-3)
        ms.append(x["Mmax"])
    assert ms == sorted(ms) and ms[-1] > ms[0]
    # default axial = most compression (-_Pmin), compression-positive for the solver
    _, info = csh.pile_strength_row(dict(row, _Pmin=-1500.0), 720.0, 9e8, 84.0, prof, (2.0,))
    assert info["axial_comp"] == 1500.0


def test_unstable_strength_row_rejected_by_solver_guard():
    prof = cs.soil_profile(SOFT)
    rows = [{"Pu": -1000.0, "Mu": 9e5, "Vu": 3000.0, "Tu": 0.0, "_case": "X",
             "_Pmin": -1500.0, "_Pmax": -1000.0}]
    out, info = csh.pile_strength_row(rows[0], 120.0, 9e8, 66.0, prof, (0.5,))
    assert out is None and info["bounds"][0]["stable"] is False
    got, skipped = csh.strength_rows_through_pile(rows, 120.0, 9e8, 66.0, prof, (0.5,))
    assert got == [] and skipped == rows


def test_py_strength_check_ng_when_row_skipped(monkeypatch):
    """Ruling 8-13: a governing strength row unstable on every bound makes the
    final check "Shaft p-y strength solve" NG (bent 2 run with slenderness on, which
    also pins lu = H + Df_eq_gov)."""
    real = csh.pile_strength_row

    def fake(row, *a, **k):
        out, info = real(row, *a, **k)
        return (None, info) if row.get("_case") == "Str-II" else (out, info)
    monkeypatch.setattr(csh, "pile_strength_row", fake)
    b = ee.run_colshaft(payload([bent2()], settings={"slenderness_on": True}))["bents"][0]
    strict_json(b)
    c = chk(b, "Shaft p-y strength solve")
    assert c["ok"] is False and c["demand"] == 1 and c["capacity"] == 3
    assert "Str-II" in c["detail"]
    assert b["status"] == "NG"
    assert len(b["lrfd"]["shaft"]["rows"]) == 2
    Df = b["seismic"]["pile"]["Df_eq_gov"]
    assert Df and b["Df_for_lu"] == Df
    r0 = b["lrfd"]["col"]["check_rows"][0]
    assert r0["_klr2"] == pytest.approx(2.1 * (300.0 + Df) / (0.25 * 54.0))


SOFT2 = {"layers": [{"thickness_ft": 80.0, "py_model": "matlock_soft_clay", "gamma_pcf": 110.0,
                     "su_top_ksf": 0.3, "su_bot_ksf": 0.5, "eps50": 0.02, "submerged": True}],
         "J": 0.5, "cyclic": True}


@pytest.mark.parametrize("P", [8000.0, 12000.0])
def test_ramp_guard_rejects_post_buckled_state(P):
    """Ruling 8-16: soft clay x0.5, M 5000 / V 400.  The solver reports a stable
    (post-buckled, wavy) state at the full axial load, but the solve at P = 0
    runs away: the axial-ramp guard rejects the bound and the row is skipped."""
    prof = cs.soil_profile(SOFT2)
    p = replace(prof, stiffness_factor=prof.stiffness_factor * 0.5)
    assert csh._cached_pile_solve(0.0, 720.0, 9e8, 9e8, 84.0, P, p, 400.0, -5000.0).stable
    row = {"Pu": -P, "Mu": 5000.0, "Vu": 400.0, "Tu": 0.0, "_case": "X", "_Pmin": -P}
    out, info = csh.pile_strength_row(row, 720.0, 9e8, 84.0, prof, (0.5,))
    assert out is None and info["bounds"][0]["stable"] is False
    assert "unstable at P = 0" in info["bounds"][0]["reject"]
    rows, skipped = csh.strength_rows_through_pile([row], 720.0, 9e8, 84.0, prof, (0.5,))
    assert rows == [] and skipped == [row]
    assert ee.py_check(skipped, 1)["ok"] is False


def test_ramp_guard_engine_soft_soil_ng():
    b = ee.run_colshaft(payload([bent2(soil=copy.deepcopy(SOFT2), soil_bounds=[0.5])]))["bents"][0]
    strict_json(b)
    c = chk(b, "Shaft p-y strength solve")
    assert c["ok"] is False and c["demand"] == c["capacity"] == 3
    assert b["lrfd"]["shaft"] is None and b["status"] == "NG"


def test_ramp_guard_accepts_stiff_case_unchanged():
    prof = cs.soil_profile(SOIL)
    p = replace(prof, stiffness_factor=prof.stiffness_factor * 2.0)
    row = {"Pu": -12000.0, "Mu": 5000.0, "Vu": 400.0, "Tu": 0.0, "_Pmin": -12000.0}
    out, info = csh.pile_strength_row(row, 720.0, 9e8, 84.0, prof, (2.0,))
    full = csh._cached_pile_solve(0.0, 720.0, 9e8, 9e8, 84.0, 12000.0, p, 400.0, -5000.0)
    assert info["bounds"][0]["stable"] and info["bounds"][0]["reject"] is None
    assert out["Mu"] == full.max_inground_moment and out["Vu"] == max(full.max_inground_shear, 400.0)


class _Sol:
    def __init__(self, stable, y, m):
        self.stable, self.head_deflection, self.moment = stable, y, [m, m]


@pytest.mark.parametrize("sols, why", [
    ([(True, 1.0, 5000.0)] * 5, None),
    ([(True, 1.0, 5000.0), (True, 1.1, 5000.0), (False, 9.0, 5000.0)] + [(True, 2.0, 5000.0)] * 2,
     "solver unstable"),
    ([(True, 1.0, 5000.0), (True, 1.2, 5000.0), (True, 0.9, 5000.0)] + [(True, 2.0, 5000.0)] * 2,
     "head deflection decreases"),
    ([(True, 1.0, 5000.0), (True, 1.1, -5000.0)] + [(True, 2.0, 5000.0)] * 3, "top-of-shaft moment"),
    ([(True, 1.0, 5000.0), (True, 1.1, 4900.0)] + [(True, 2.0, 5000.0)] * 3, "top-of-shaft moment"),
])
def test_ramp_stable_criteria(monkeypatch, sols, why):
    calls = []

    def fake(Hcol, L, EIc, EIs, Ds, P, prof, V, M):
        calls.append(P)
        return _Sol(*sols[len(calls) - 1])
    monkeypatch.setattr(csh, "_cached_pile_solve", fake)
    s, reason = csh.ramp_stable(720.0, 9e8, 84.0, 8000.0, None, 400.0, -5000.0, 5000.0)
    if why is None:
        assert reason is None and calls == [0.0, 2000.0, 4000.0, 6000.0, 8000.0]
    else:
        assert reason.startswith(why)


def test_py_check_unit():
    ok = ee.py_check([], 4)
    assert ok["ok"] and ok["name"] == "Shaft p-y strength solve" and ok["group"] == "Shaft LRFD"
    ng = ee.py_check([{"_case": "S1", "Mu": 1e4, "Vu": 100.0}], 4)
    assert ng["ok"] is False and "S1" in ng["detail"] and ng["ratio"] == 0.25


def test_governing_base_rows_top5_union():
    rows = [{"Mu": float(i), "Vu": float(20 - i), "_case": str(i)} for i in range(20)]
    sel = csh.governing_base_rows(rows)
    assert [r["_case"] for r in sel] == ["0", "1", "2", "3", "4", "15", "16", "17", "18", "19"]
    rows2 = [{"Mu": float(i), "Vu": float(i), "_case": str(i)} for i in range(20)]
    assert len(csh.governing_base_rows(rows2)) == 5


# ── slenderness (ruling 8-7) ────────────────────────────────────────

def test_slenderness_toggle_changes_only_when_on():
    off = run("2b")["bents"][0]
    r = run("slender")
    strict_json(r)
    on, rf = r["bents"]
    # lu = H + L_eq = 240 + 120 in; r = 15 in; K lu / r = 2.1*360/15 = 50.4 -> pending (S6)
    rows = on["lrfd"]["col"]["check_rows"]
    assert rows and all(x["_slender_status"] == "magnification pending verification (S6)"
                        for x in rows)
    assert rows[0]["_klr2"] == pytest.approx(2.1 * 360.0 / 15.0)
    assert on["final"] == off["final"] and on["status"] == "OK"
    assert any("not yet applied" in x for x in on["warnings"])
    # K lu / r >= 100 -> refined analysis required, never OK; cages unchanged
    assert rf["status"] == "REFINED ANALYSIS REQUIRED"
    assert rf["final"] == off["final"]


def test_bent_status_precedence():
    assert ee.bent_status(True, True, True) == "NO SOLUTION"
    assert ee.bent_status(False, True, True) == "REFINED ANALYSIS REQUIRED"
    assert ee.bent_status(False, False, True) == "NG"
    assert ee.bent_status(False, False, False) == "OK"


# ── envelope mode (ruling 8-8) ──────────────────────────────────────

def test_member_mode_never_less_steel_than_station_mode():
    r = run("member")
    strict_json(r)
    assert r["settings"]["envelope_mode"] == "member"
    for s, m in zip(run("2b")["bents"], r["bents"]):     # bent 1 (shaft frames), bent 2 (p-y)
        assert m["lrfd"]["col"]["n_rows"] == 1
        assert m["lrfd"]["col"]["long"]["Ast"] >= s["lrfd"]["col"]["long"]["Ast"] - 1e-9
        assert m["final"]["col_long"]["Ast"] >= s["final"]["col_long"]["Ast"] - 1e-9
        assert m["final"]["col_trans"]["Av_s"] >= s["final"]["col_trans"]["Av_s"] - 1e-12
        assert m["final"]["shaft_long"]["Ast"] >= s["final"]["shaft_long"]["Ast"] - 1e-9
    assert r["bents"][0]["lrfd"]["shaft"]["n_rows"] == 1
    # p-y bent: base rows come from the station rows, so the same governing rows are solved
    assert r["bents"][1]["lrfd"]["shaft"]["source"] == csh.PY_SOURCE
    assert len(r["bents"][1]["lrfd"]["shaft"]["rows"]) == 3


def test_envelope_mode_validated():
    with pytest.raises(ValueError, match="envelope_mode"):
        ee.run_colshaft(payload([bent1()], settings={"envelope_mode": "bent"}))


# ── input validation / warnings ─────────────────────────────────────

def test_unknown_code_raises():
    with pytest.raises(ValueError, match="Unknown seismic code"):
        ee.run_colshaft(payload([bent1()], code="SDC 9.9"))
    for k in ("SDC_2_0", "AASHTO_SGS", "SDC 2.1", "AASHTO SGS 3rd Ed."):
        assert ee.validate_code(k) is get_provisions(k)


def test_categories_validated_and_normalised():
    cases = ["DEAD", "Str-I", "EQ-X", "DW"]
    out = ee.validate_categories({"Str-I": "extreme", "DW": " dead ", "EQ-X": ""}, cases)
    assert out == {"DEAD": "Dead", "Str-I": "Extreme", "EQ-X": "Extreme", "DW": "Dead"}
    with pytest.raises(ValueError, match="Unknown load-case category"):
        ee.validate_categories({"Str-I": "Service"}, cases)
    with pytest.raises(ValueError, match="Unknown load-case category"):
        ee.run_colshaft(payload([bent1()], categories={"DEAD": "Permanent"}))


def test_missing_dead_requires_p_dead():
    with pytest.raises(ValueError, match="P_dead"):
        ee.run_colshaft(payload([{"name": "X", "col_frames": ["1227"], "column": COL1,
                                  "shaft": SHAFT1, "L_eq_in": 120.0}], paste=PASTE_1227))


def _with_dw(paste):
    out = []
    for ln in paste.splitlines():
        out.append(ln)
        c = ln.split("\t")
        if len(c) > 5 and c[2] == "DEAD":
            c[2] = "DW"
            c[5] = f"{float(c[5]) * 0.1:.3f}"
            out.append("\t".join(c))
    return "\n".join(out) + "\n"


def test_p_dead_is_sum_of_dead_cases():
    """Ruling 8-14: P_dead = sum over the Dead cases of each case's most compressive
    base axial (DC + DW)."""
    pr = ci.parse_csi_frame_forces(_with_dw(PASTE_2B))
    cats = ee.validate_categories({"DW": "Dead"}, pr.cases)
    w = []
    ax = ee.seismic_axial({"name": "B1"}, pr.rows, ["101"], cats, "auto", w)
    assert ax["dead_cases"] == {"DEAD": -950.0, "DW": -95.0}
    assert ax["P_dead"] == pytest.approx(-1045.0)
    assert (ax["P_ext_min"], ax["P_ext_max"]) == (-1400.0, -500.0)
    # forced base end -> the top-of-frame rows
    ax = ee.seismic_axial({"name": "B1"}, pr.rows, ["101"], cats, "max", w)
    assert ax["P_dead"] == pytest.approx(-990.0)
    # a single partial-looking Dead case warns
    pr2 = ci.parse_csi_frame_forces(PASTE_2B.replace("\tDEAD\t", "\tDC\t"))
    w2 = []
    ax2 = ee.seismic_axial({"name": "B1"}, pr2.rows, ["101"],
                           ee.validate_categories(None, pr2.cases), "auto", w2)
    assert ax2["P_dead"] == -950.0 and any("single Dead case 'DC'" in x for x in w2)


def test_warnings_collected():
    r = run("ov")
    b = r["bents"][0]
    assert any("frame 999 not found" in x for x in b["warnings"])
    assert any(x.startswith("B1: ") and "frame 999" in x for x in r["parse"]["warnings"])


def test_seismic_mc_cache_is_transparent():
    """seismic_design(mc_cache=...) memoises M-phi only; results are identical."""
    b = run("2b")["bents"][0]
    f = b["final"]
    args = (COL1, SHAFT1, ee.full_cage(f["col_long"], f["col_trans"]),
            ee.full_cage(f["shaft_long"], f["shaft_trans"]),
            {k: b["axial"][k] for k in ("P_dead", "P_ext_min", "P_ext_max")},
            dict(bent1(), H_in=b["H_in"]), get_provisions("SDC 2.1"))
    cache = {}
    plain = cs.seismic_design(*args)
    c1 = cs.seismic_design(*args, mc_cache=cache)
    n = len(cache)
    c2 = cs.seismic_design(*args, mc_cache=cache)
    assert n == len(plain.Mp_by_P) + 1 and len(cache) == n
    for r in (c1, c2):
        assert (r.Mo, r.shaft_Mp, r.EI_col, r.EI_shaft) == \
            (plain.Mo, plain.shaft_Mp, plain.EI_col, plain.EI_shaft)
