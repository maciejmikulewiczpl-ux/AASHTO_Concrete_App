"""Column-on-Shaft LRFD strength design search (Task 6, colshaft_lrfd).

Sign convention: Pu < 0 compression.  Moments kip-in.
"""
import math
import random
import time

import pytest

import calc_engine as ce
import circ_engine as cc
import colshaft_lrfd as cl
from tests.fixtures import make_inputs

MEMBER = dict(D=48.0, fc=4.0, fy=60.0, fyt=60.0, cover=2.0, ag=0.75,
              trans_type="hoop", hoop_closure="lap")


def row(Pu=-800.0, Mu=0.0, Vu=0.0, Tu=0.0, Pmin=None, Pmax=None, bound="concurrent"):
    return {"Pu": Pu, "Mu": Mu, "Vu": Vu, "Tu": Tu, "Vp": 0, "Ms": 0, "Ps": 0,
            "_frame": "F1", "_station": 0.0, "_case": "STR",
            "_bound": bound,
            "_Pmin": Pu if Pmin is None else Pmin, "_Pmax": Pu if Pmax is None else Pmax}


def env(Pmin, Pmax, Mu=0.0, Vu=0.0, Tu=0.0):
    return row(Pu=Pmax, Mu=Mu, Vu=Vu, Tu=Tu, Pmin=Pmin, Pmax=Pmax, bound="envelope")


def curves(bar=10, n=20, bundle=1, member=MEMBER):
    raw = cl.cage_inputs(cl.base_circ_inputs(member),
                         {"bar": bar, "n": n, "bundle": bundle, "trans_bar": 5, "s": 6.0, "ties": 0})
    I = cc.derive_circular(dict(raw))
    return I, cc.build_pm_curve_circ(I, "top"), cc.build_pm_curve_circ(I, "bottom")


def brute_min(curve, Pmin, Pmax, n=200):
    ps = [Pmin + (Pmax - Pmin) * i / (n - 1) for i in range(n)]
    return min(ce.get_mr_at_pu(curve, p) for p in ps)


# ── base inputs ──────────────────────────────────────────────────────

def test_base_circ_inputs_complete_and_mapped():
    raw = cl.base_circ_inputs(MEMBER)
    # every key of the circular fixture builder is present
    fixture_keys = set(make_inputs(secType="CIRCULAR", D=48))
    assert fixture_keys <= set(raw)
    assert raw["secType"] == "CIRCULAR" and raw["D"] == 48.0
    assert raw["fc"] == 4.0 and raw["fy"] == 60.0 and raw["fy_trans"] == 60.0
    assert raw["cover"] == 2.0 and raw["ag"] == 0.75
    assert raw["circ_trans_type"] == "hoop" and raw["circ_hoop_closure"] == "lap"
    res = cc.calculate_all_circ(raw, [row()], 0)
    assert res["row_results"][0]["flexStatus"] in ("OK", "MIN", "NG")


def test_base_circ_inputs_does_not_share_state():
    a = cl.base_circ_inputs(MEMBER)
    a["fc"] = 99
    assert cl.base_circ_inputs(MEMBER)["fc"] == 4.0


# ── longitudinal search ─────────────────────────────────────────────

@pytest.mark.parametrize("Mu,params,pinned", [
    # the ruling's case: rho_l,min = 0.01 (SDC 2.1) governs; among the sizes within 5 % of
    # the least As (23-#8 = 18.17 in2) the fewest bars wins -> 12-#11 (18.72 in2)
    (12000.0, {}, (11, 12, 1)),
    # same row with the rho floor removed: the six-bar minimum governs
    (12000.0, {"rho_min": 0.0}, (8, 6, 1)),
    # strength governs: n - 1 bars must fail
    (40000.0, {"rho_min": 0.0}, (11, 21, 1)),
])
def test_single_row_minimal_cage(Mu, params, pinned):
    """Controller ruling P3 (replaces test_single_row_matches_existing_tab).

    D = 48 in, f'c = 4 ksi, one row Pu = -800 kip.  The cage passes, n - 1 bars of
    the same size/bundle fail (unless n is the minimum 6 or rho_min governs), and
    (bar, n, bundle) is pinned as a regression value (recorded from this
    implementation on 2026-10-18; search order and tie-breaks checked by reading
    index.html optimizeFlexureCirc, lines 3682-3728).
    """
    rows = [row(-800.0, Mu)]
    res = cl.design_longitudinal(MEMBER, rows, params)
    assert res.ok
    assert (res.bar, res.n, res.bundle) == pinned
    cage = {"bar": res.bar, "n": res.n, "bundle": res.bundle, "trans_bar": 5, "s": 6.0, "ties": 0}
    assert cl.check_cage(MEMBER, cage, rows)[0]["flexStatus"] != "NG"
    Ag = math.pi * 48.0 ** 2 / 4
    a = ce.BARS[res.bar]["a"] * res.bundle
    rho_min = params.get("rho_min", 0.01)
    rho_min_n = math.ceil(rho_min * Ag / a - 1e-9)
    if res.n - 1 >= max(6, rho_min_n):
        out = cl.check_cage(MEMBER, dict(cage, n=res.n - 1), rows)
        assert out[0]["flexStatus"] == "NG"
    else:
        assert res.n == max(6, rho_min_n)


def test_minimum_six_bars():
    res = cl.design_longitudinal(dict(MEMBER, D=24.0), [row(-10.0, 1.0)],
                                 {"rho_min": 0.0, "minBar": 11, "maxBar": 11})
    assert res.ok and res.n >= 6 and res.n == 6


def test_rho_min_enforced():
    res = cl.design_longitudinal(MEMBER, [row(-10.0, 1.0)], {})
    Ag = math.pi * 48.0 ** 2 / 4
    assert res.ok and res.n >= 6
    assert res.rho_l >= 0.01 - 1e-12
    assert res.Ast == pytest.approx(res.n * res.bundle * ce.BARS[res.bar]["a"])
    assert res.rho_l == pytest.approx(res.Ast / Ag)


def test_more_demand_never_less_steel():
    asts = []
    for Mu in (20000.0, 40000.0, 60000.0):
        res = cl.design_longitudinal(MEMBER, [row(-800.0, Mu)], {})
        assert res.ok
        asts.append(res.Ast)
    assert asts[0] <= asts[1] <= asts[2]
    assert asts[0] < asts[2]


def test_lrfd_no_solution_reported():
    res = cl.design_longitudinal(MEMBER, [row(-100000.0, 100.0)], {})
    assert res.ok is False
    assert "NO SOLUTION" in res.note
    assert math.isfinite(res.dc_max) and res.dc_max > 1.0
    assert res.governing_row == 0


def test_transform_hook_applied():
    seen = []

    def double_mu(cage, rows):
        seen.append(cage)
        return [dict(r, Mu=2 * r["Mu"]) for r in rows]

    rows = [row(-800.0, 20000.0)]
    plain = cl.design_longitudinal(MEMBER, rows, {})
    mag = cl.design_longitudinal(MEMBER, rows, {}, transform=double_mu)
    assert seen and {"bar", "n", "bundle", "trans_bar", "s", "ties", "inputs"} <= set(seen[0])
    assert mag.Ast > plain.Ast
    assert rows[0]["Mu"] == 20000.0   # caller's rows untouched


# ── envelope rows ───────────────────────────────────────────────────

def test_envelope_flexure_uses_worst_P():
    _, sag, _ = curves()
    # balance point = vertex with the largest Mr
    pb = max(sag, key=lambda p: p["Mr"])["Pr"]
    Pmin, Pmax = pb - 1500.0, pb + 900.0
    ps = cl.flexure_axial_star(sag, Pmin, Pmax)
    assert ps in (Pmin, Pmax)
    lo = min(ce.get_mr_at_pu(sag, Pmin), ce.get_mr_at_pu(sag, Pmax))
    assert ce.get_mr_at_pu(sag, ps) == pytest.approx(lo, rel=1e-9)
    assert ce.get_mr_at_pu(sag, ps) == pytest.approx(brute_min(sag, Pmin, Pmax), rel=1e-6)
    # high-compression envelope (entirely above balance) -> most compression governs
    Pmin, Pmax = sag[0]["Pr"] * 0.95, pb - 300.0
    ps = cl.flexure_axial_star(sag, Pmin, Pmax)
    assert ps == Pmin
    assert ce.get_mr_at_pu(sag, ps) == pytest.approx(brute_min(sag, Pmin, Pmax), rel=1e-6)


@pytest.mark.parametrize("pts", [
    # Pr folds back (phi bump); continuous upper envelope
    [(-1000, 0), (-800, 500), (-600, 300), (-700, 200), (-400, 600), (0, 400), (200, 0)],
    # fold whose vertex value is above the continuing branch: the infimum just right of
    # P = -600 is a one-sided limit (266.7), lower than get_mr_at_pu(-600) = 300
    [(-1000, 0), (-800, 500), (-600, 300), (-700, 100), (-400, 600), (0, 400), (200, 0)],
])
def test_flexure_axial_star_exact_on_folded_curve(pts):
    curve = [{"Pr": p, "Mr": m} for p, m in pts]
    for Pmin, Pmax in ((-900, -100), (-1000, 200), (-750, -650), (-650, -450), (-600, -500)):
        ps, mr = cl._flex_star(cl._Curve(curve), Pmin, Pmax)
        assert Pmin <= ps <= Pmax
        assert ps == cl.flexure_axial_star(curve, Pmin, Pmax)
        b = brute_min(curve, Pmin, Pmax, 4001)
        assert mr <= b + 1e-9                    # never above any sampled value
        assert mr >= b - 1.0                     # and within the grid resolution
        assert mr <= ce.get_mr_at_pu(curve, ps) + 1e-9


def test_envelope_flexure_judged_at_P_star_in_search():
    _, sag, _ = curves()
    pb = max(sag, key=lambda p: p["Mr"])["Pr"]
    # a concurrent row at Pmax alone needs less steel than the envelope (worst P in range)
    Pmin, Pmax = sag[0]["Pr"] * 0.6, pb
    Mu = 40000.0
    only_max = cl.design_longitudinal(MEMBER, [row(Pmax, Mu)], {"rho_min": 0.0})
    envelope = cl.design_longitudinal(MEMBER, [env(Pmin, Pmax, Mu)], {"rho_min": 0.0})
    assert envelope.ok and only_max.ok
    assert envelope.Ast > only_max.Ast
    assert envelope.governing_P == pytest.approx(Pmin)


def test_envelope_shear_uses_Pmax():
    cage = {"bar": 10, "n": 20, "bundle": 1, "trans_bar": 5, "s": 6.0, "ties": 0}
    Pmin, Pmax = -2500.0, -100.0
    r_env = env(Pmin, Pmax, Mu=8000.0, Vu=300.0)
    out = cl.check_cage(MEMBER, cage, [r_env])[0]
    I, sag, hog = curves()
    at_max = cc.compute_row_capacities_circ(I, sag, hog, Pmax, 8000.0, 300.0, 0, 0, 0, 0)
    at_min = cc.compute_row_capacities_circ(I, sag, hog, Pmin, 8000.0, 300.0, 0, 0, 0, 0)
    assert out["Vr2"] == pytest.approx(at_max["Vr2"], rel=1e-12)
    assert at_min["Vr2"] >= at_max["Vr2"]
    assert out["_flexP"] == pytest.approx(cl.flexure_axial_star(sag, Pmin, Pmax))
    tr = cl.design_transverse(MEMBER, cl.design_longitudinal(MEMBER, [r_env], {}), [r_env], {})
    assert tr.ok


def test_check_cage_concurrent_matches_engine():
    """Even bar count, concurrent rows: the two-face flexure equals the engine's own."""
    cage = {"bar": 10, "n": 20, "bundle": 1, "trans_bar": 5, "s": 6.0, "ties": 0}
    rows = [row(-800.0, 12000.0, Vu=200.0, Tu=100.0), row(-3000.0, 30000.0), row(-800.0, 12000.0, Vu=200.0, Tu=100.0)]
    out = cl.check_cage(MEMBER, cage, rows)
    assert len(out) == 3 and out[0] == out[2] and out[0] is not out[2]
    I, sag, hog = curves()
    for r, o in zip(rows, out):
        eng = cc.compute_row_capacities_circ(I, sag, hog, r["Pu"], r["Mu"], r["Vu"], r["Tu"], 0, 0, 0)
        assert o["Mr"] == pytest.approx(eng["Mr"], rel=1e-12)
        assert o["flexStatus"] == eng["flexStatus"]
        assert o["Vr2"] == eng["Vr2"] and o["Tr"] == eng["Tr"]
        assert o["_flexP"] == r["Pu"]


# ── transverse search ───────────────────────────────────────────────

def test_transverse_candidates_order():
    c = list(cl.transverse_candidates({"stirMin": 5, "stirMax": 6, "sMax": 6.0, "sMin": 5.5,
                                       "sStep": 0.25, "maxLegs": 3}))
    assert c[0] == (5, 0, 6.0) and c[1] == (5, 0, 5.75) and c[2] == (5, 0, 5.5)
    assert c[3] == (5, 1, 6.0)
    assert c[6] == (6, 0, 6.0) and len(c) == 12


def test_torsion_drives_transverse():
    rows0 = [row(-800.0, 12000.0, Vu=400.0, Tu=0.0)]
    rowsT = [row(-800.0, 12000.0, Vu=400.0, Tu=6000.0)]
    lg = cl.design_longitudinal(MEMBER, rowsT, {})
    t0 = cl.design_transverse(MEMBER, lg, rows0, {})
    tT = cl.design_transverse(MEMBER, lg, rowsT, {})
    assert t0.ok and tT.ok
    assert tT.Av / tT.s > t0.Av / t0.s
    out = cl.check_cage(MEMBER, {"bar": lg.bar, "n": lg.n, "bundle": lg.bundle,
                                 "trans_bar": tT.bar, "s": tT.s, "ties": tT.ties}, rowsT)[0]
    assert out["torsionConsider"] and out["Tr"] >= 6000.0
    assert out["shearStatus"] in ("OK", "NR")


def test_transverse_no_solution_reported():
    lg = cl.design_longitudinal(MEMBER, [row(-800.0, 12000.0)], {})
    tr = cl.design_transverse(MEMBER, lg, [row(-800.0, 12000.0, Vu=20000.0)], {})
    assert tr.ok is False and "NO SOLUTION" in tr.note
    assert math.isfinite(tr.dc_v) and tr.dc_v > 1.0


# ── speed ───────────────────────────────────────────────────────────

def test_500_rows_under_20s():
    rnd = random.Random(1227)
    rows = []
    for i in range(500):
        Pmax = -rnd.uniform(200.0, 1500.0)
        Pmin = Pmax - rnd.uniform(0.0, 1200.0)
        r = env(Pmin, Pmax, Mu=rnd.uniform(2000.0, 30000.0),
                Vu=rnd.uniform(20.0, 350.0), Tu=rnd.uniform(0.0, 500.0))
        r["_station"] = float(i)
        rows.append(r)
    t = time.perf_counter()
    lg = cl.design_longitudinal(MEMBER, rows, {})
    tr = cl.design_transverse(MEMBER, lg, rows, {})
    dt = time.perf_counter() - t
    assert lg.ok and tr.ok
    assert dt < 20.0, f"{dt:.1f} s"
