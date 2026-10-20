"""Column-on-Shaft seismic capacity design (Task 7, colshaft_seismic).

App sign convention in `axial`: Pu < 0 compression.  seismic_port is
compression-POSITIVE, so colshaft_seismic converts with P_comp = -Pu.
Golden values: tests/golden/seismic_port_golden.json, block "seismic", made from
UPSTREAM primitives (tools/make_seismic_golden.py, Ruling P4).
"""
import json
import os
import time

import pytest

import colshaft_lrfd as cl
import colshaft_seismic as cs
from seismic_port import moment_curvature as mcmod
from seismic_port import pile_solver as ps
from seismic_port.provisions import get_provisions
from seismic_port.shear import shear_capacity

with open(os.path.join(os.path.dirname(__file__), "golden",
                       "seismic_port_golden.json"), encoding="utf-8") as _f:
    GOLDEN = json.load(_f)
SEIS = GOLDEN["seismic"]
REL = 5e-3
CODES = ["SDC 2.1", "AASHTO SGS 3rd Ed."]

# The golden pair: col_D72_24-#11_#6@5_spiral on shaft_D96_30-#11_#8@6_spiral.
COLUMN = dict(D=72.0, fc=4.0, fy=60.0, cover=2.0, trans_type="spiral")
SHAFT = dict(D=96.0, fc=4.0, fy=60.0, cover=3.0, trans_type="spiral")
COL_CAGE = dict(bar=11, n=24, bundle=1, trans_bar=6, s=5.0, ties=0)
SHAFT_CAGE = dict(bar=11, n=30, bundle=1, trans_bar=8, s=6.0, ties=0)
DEAD_ONLY = {"P_dead": -SEIS["P_dead"], "P_ext_min": None, "P_ext_max": None}


def soil(name=SEIS["profile"], layers=None):
    layers = layers or GOLDEN["pile"]["profiles"][name]
    out = []
    for t, m, g, kw in layers:
        d = dict(kw, thickness_ft=t, py_model=m, gamma_pcf=g)
        out.append(d)
    return {"layers": out, "J": 0.5, "cyclic": True}


def bent(**kw):
    b = dict(H_in=SEIS["H"], shaft_basis="interface")
    b.update(kw)
    return b


def run(code="SDC 2.1", axial=DEAD_ONLY, column=COLUMN, col_cage=COL_CAGE, **bkw):
    return cs.seismic_design(column, SHAFT, col_cage, SHAFT_CAGE, axial, bent(**bkw),
                             get_provisions(code))


def chk(res, name):
    m = [c for c in res.checks if c.name == name]
    assert len(m) == 1, (name, [c.name for c in res.checks])
    return m[0]


# ── sections / sign convention ──────────────────────────────────────

@pytest.mark.parametrize("code", CODES)
def test_to_section_expected_properties(code):
    prov = get_provisions(code)
    s = cs.to_section(COLUMN, COL_CAGE, prov)
    assert (s.D, s.fc, s.cover, s.n_bars, s.long_bar_no, s.long_bundle) == (72.0, 4.0, 2.0, 24, 11, 1)
    assert (s.spiral_bar_no, s.spiral_spacing, s.hoops) == (6, 5.0, False)
    assert s.fce_factor == prov.fce_factor and s.fce_floor == prov.fce_floor
    assert (s.fye, s.fue, s.fyh) == (68.0, 95.0, 68.0)          # upstream expected defaults
    assert cs.to_section(dict(COLUMN, trans_type="hoop"), COL_CAGE, prov).hoops is True
    g = cs.to_section(dict(COLUMN, fye=70.0, fue=100.0, fyh=66.0), COL_CAGE, prov)
    assert (g.fye, g.fue, g.fyh) == (70.0, 100.0, 66.0)


def test_app_compression_negative_matches_upstream_positive():
    """App Pu = -800 (compression) gives upstream's Mp at axial +800."""
    r = run()
    g = SEIS["by_code"]["SDC 2.1"]
    assert r.Mp_by_P == [(pytest.approx(-800.0), pytest.approx(g["Mp_col"], rel=REL))]
    assert r.Mp == pytest.approx(g["Mp_col"], rel=REL)
    # and a tension Pu must NOT give the compression Mp
    t = run(axial={"P_dead": 800.0, "P_ext_min": None, "P_ext_max": None})
    assert t.Mp < 0.9 * g["Mp_col"]


# ── Mo / Mp sampling ────────────────────────────────────────────────

def test_mo_is_lambda_times_max_mp():
    ax = {"P_dead": -800.0, "P_ext_min": -2000.0, "P_ext_max": -200.0}
    r = run(axial=ax)
    assert len(r.Mp_by_P) == 6
    Ps = [p for p, _ in r.Mp_by_P]
    assert Ps[0] == -800.0
    assert Ps[1:] == pytest.approx([-2000.0, -1550.0, -1100.0, -650.0, -200.0])
    mp_max = max(m for _, m in r.Mp_by_P)
    assert r.Mp == mp_max and r.lambda_mo == 1.2
    assert r.Mo == pytest.approx(1.2 * mp_max)
    assert r.Mp_P == [p for p, m in r.Mp_by_P if m == mp_max][0]
    r13 = run(axial=ax, lambda_mo=1.3)
    assert r13.Mo == pytest.approx(1.3 * mp_max)


def test_mp_sampled_inside_axial_range():
    """A range spanning the balance point: max Mp is at an interior sample."""
    ax = {"P_dead": -500.0, "P_ext_min": -14000.0, "P_ext_max": 1000.0}
    r = run(axial=ax)
    assert r.Mp_P not in (-14000.0, 1000.0, -500.0)
    assert -14000.0 < r.Mp_P < 1000.0
    ends = [m for p, m in r.Mp_by_P if p in (-14000.0, 1000.0, -500.0)]
    assert r.Mp > max(ends)


def test_empty_extreme_range_uses_p_dead_only():
    r = run(axial={"P_dead": -800.0})
    assert [p for p, _ in r.Mp_by_P] == [-800.0]


def test_mphi_failure_skipped_with_warning(monkeypatch):
    real = cs.moment_curvature

    def flaky(section, axial, *a, **k):
        if abs(axial - 2000.0) < 1e-6:
            raise RuntimeError("boom")
        return real(section, axial, *a, **k)

    monkeypatch.setattr(cs, "moment_curvature", flaky)
    r = run(axial={"P_dead": -800.0, "P_ext_min": -2000.0, "P_ext_max": -200.0})
    assert len(r.Mp_by_P) == 5 and -2000.0 not in [p for p, _ in r.Mp_by_P]
    assert any("-2000" in w for w in r.warnings)

    def broken(section, axial, *a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(cs, "moment_curvature", broken)
    with pytest.raises(ValueError):
        run(axial={"P_dead": -800.0, "P_ext_min": -2000.0, "P_ext_max": -200.0})


# ── shear / Vo ─────────────────────────────────────────────────────

@pytest.mark.parametrize("code", CODES)
def test_seismic_vc_uses_least_compression(code):
    prov = get_provisions(code)
    sec = cs.to_section(COLUMN, COL_CAGE, prov)
    ax = {"P_dead": -800.0, "P_ext_min": -2000.0, "P_ext_max": -200.0}
    r = run(code, axial=ax)
    assert r.P_vc == -200.0
    exp = shear_capacity(sec, 200.0, prov.mu_d_limit_single, True, prov)
    assert r.col_shear == pytest.approx(exp)
    assert r.col_shear[1] < shear_capacity(sec, 800.0, prov.mu_d_limit_single, True, prov)[1]
    sh = cs.to_section(SHAFT, SHAFT_CAGE, prov)
    assert r.shaft_phiVn == pytest.approx(shear_capacity(sh, 200.0, 1.0, False, prov)[0])
    # net tension at the least-compression end -> vc = 0 (port rule)
    t = run(code, axial={"P_dead": -800.0, "P_ext_min": -2000.0, "P_ext_max": 100.0})
    assert t.col_shear[1] == 0.0
    # no Extreme rows -> P_dead
    d = run(code)
    assert d.P_vc == -800.0


def test_vo_fixed_fixed_doubles():
    ff = run(end_condition_long="fixed-free", end_condition_trans="fixed-free")
    fx = run(end_condition_long="fixed-free", end_condition_trans="fixed-fixed")
    assert ff.Vo == pytest.approx(ff.Mo / SEIS["H"])
    assert ff.end_condition == "fixed-free"
    assert fx.Vo == pytest.approx(2.0 * ff.Vo)
    assert fx.end_condition == "fixed-fixed"
    assert run().end_condition == "fixed-free"          # default both directions


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("end", ["fixed-free", "fixed-fixed"])
def test_matches_seismic_app_checks(code, end):
    g = SEIS["by_code"][code]
    prov = get_provisions(code)
    r = run(code, end_condition_long=end)
    assert r.Mo == pytest.approx(g["Mo"], rel=REL)
    assert r.Vo == pytest.approx(g["Vo"][end], rel=REL)
    assert r.col_shear == pytest.approx(g["col_shear"], rel=REL)
    assert r.shaft_Mp == pytest.approx(g["Mp_shaft"], rel=REL)
    assert r.shaft_phiVn == pytest.approx(g["shaft_shear"][0], rel=REL)
    assert r.shaft_Mdemand == pytest.approx(g["shaft_demand_interface"], rel=REL)
    assert r.rho_s_min == pytest.approx(g["rho_s_min"][0], rel=REL)
    assert r.s_max_detailing == pytest.approx(g["s_max"], rel=REL)
    # D/C of the column shear, shaft flexure and shaft shear checks
    c = chk(r, "Column shear")
    assert c.demand / c.capacity == pytest.approx(g["Vo"][end] / g["col_shear"][0], rel=REL)
    assert c.ok == (g["col_shear"][0] >= g["Vo"][end])
    assert c.ref == prov.ref_shear
    f = chk(r, "Shaft flexure (capacity protection)")
    assert f.demand / f.capacity == pytest.approx(g["shaft_demand_interface"] / g["Mp_shaft"], rel=REL)
    assert f.ref == prov.ref_shaft_capacity
    v = chk(r, "Shaft shear (capacity protection)")
    assert v.demand / v.capacity == pytest.approx(g["Vo"][end] / g["shaft_shear"][0], rel=REL)
    assert v.ref == prov.ref_shaft_capacity
    m = chk(r, "Transverse steel ratio (min)")
    assert m.ref == prov.ref_transverse
    assert chk(r, "Transverse spacing (max)").ref == prov.ref_detailing


def test_shaft_confinement_and_oversize_checks():
    sgs = run("AASHTO SGS 3rd Ed.")
    g = SEIS["by_code"]["AASHTO SGS 3rd Ed."]
    c = chk(sgs, "Shaft confinement (oversized)")
    assert c.demand == pytest.approx(0.5 * g["col_rho_s"], rel=REL)
    assert c.capacity == pytest.approx(g["shaft_rho_s"], rel=REL)
    o = chk(sgs, "Shaft oversize")
    assert o.demand == pytest.approx(0.0) and o.capacity == pytest.approx(24.0) and o.ok
    for x in (c, o):
        assert x.ref == "" and cs.UNVERIFIED_REF in x.detail
    sdc = run("SDC 2.1")
    assert not [x for x in sdc.checks if x.name == "Shaft confinement (oversized)"]
    o = chk(sdc, "Shaft oversize")          # Caltrans: Ds - D >= 24 in
    assert o.demand == pytest.approx(24.0) and o.ok
    small = cs.seismic_design(COLUMN, dict(SHAFT, D=84.0), COL_CAGE, SHAFT_CAGE, DEAD_ONLY,
                              bent(), get_provisions("SDC 2.1"))
    assert chk(small, "Shaft oversize").ok is False


# ── shaft basis ────────────────────────────────────────────────────

def test_cantilever_basis_amplifies():
    L = 300.0
    i = run(shaft_basis="interface")
    c = run(shaft_basis="cantilever", L_eq_in=L)
    assert c.shaft_Mdemand == pytest.approx(i.shaft_Mdemand * (1.0 + c.Vo * L / c.Mo))
    assert len(c.shaft_profile) == 11
    assert c.shaft_profile[0] == pytest.approx((0.0, c.Mo, c.Vo))
    assert c.shaft_profile[-1] == pytest.approx((L, c.Mo + c.Vo * L, c.Vo))
    assert c.Df == L and c.pile is None
    assert i.shaft_profile == [pytest.approx((0.0, i.Mo, i.Vo))]


def test_missing_L_eq_without_soil_raises():
    with pytest.raises(ValueError, match="Enter the pile equivalent cantilever length or a soil profile"):
        cs.seismic_design(COLUMN, SHAFT, COL_CAGE, SHAFT_CAGE, DEAD_ONLY,
                          {"H_in": 240.0}, get_provisions("SDC 2.1"))
    with pytest.raises(ValueError, match="Enter the pile equivalent cantilever length or a soil profile"):
        run(shaft_basis="cantilever")


def test_basis_defaults():
    r = cs.seismic_design(COLUMN, SHAFT, COL_CAGE, SHAFT_CAGE, DEAD_ONLY,
                          {"H_in": 240.0, "L_eq_in": 200.0}, get_provisions("SDC 2.1"))
    assert r.shaft_basis == "cantilever"
    r = cs.seismic_design(COLUMN, SHAFT, COL_CAGE, SHAFT_CAGE, DEAD_ONLY,
                          {"H_in": 240.0, "soil": soil(), "L_embed_in": 720.0},
                          get_provisions("SDC 2.1"))
    assert r.shaft_basis == "soil"


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("end", ["fixed-free", "fixed-fixed"])
def test_soil_basis_matches_upstream_inground(code, end):
    g = SEIS["by_code"][code]
    prov = get_provisions(code)
    r = run(code, shaft_basis="soil", soil=soil(), L_embed_in=SEIS["L_embed"],
            end_condition_trans=end)
    up = g["soil"][end]
    assert r.shaft_Mdemand == pytest.approx(prov.shaft_demand_factor * up["M"], rel=REL)
    assert r.pile["M_inground"] == pytest.approx(up["M"], rel=REL)
    assert r.pile["V_inground"] == pytest.approx(up["V"], rel=REL)
    v = chk(r, "Shaft shear (capacity protection)")
    assert v.demand == pytest.approx(max(up["V"], g["Vo"][end]), rel=REL)
    assert chk(r, "Shaft p-y solve").ok is True
    assert len(r.pile["bounds"]) == 2
    assert [b["factor"] for b in r.pile["bounds"]] == [2.0, 0.5]


def test_df_eq_from_fixed_free_solve_on_softest_stable_bound():
    """Even when fixed-fixed governs, Df_eq_gov comes from the fixed-free solve."""
    r = run(shaft_basis="soil", soil=soil(), L_embed_in=SEIS["L_embed"],
            end_condition_long="fixed-fixed")
    assert r.end_condition == "fixed-fixed"
    soft = [b for b in r.pile["bounds"] if b["stable"]]
    soft = min(soft, key=lambda b: b["factor"])
    assert r.pile["Df_eq_gov"] == soft["Df_eq"] == r.Df
    # recompute the fixed-free solve directly with the port
    from dataclasses import replace
    prof = cs.soil_profile(soil())
    g0 = SEIS["by_code"]["SDC 2.1"]
    assert r.EI_col == pytest.approx(g0["Mp_col"] / g0["phi_y_col"], rel=REL)
    assert r.EI_shaft == pytest.approx(g0["Mp_shaft"] / g0["phi_y_shaft"], rel=REL)
    sol = ps.solve_lateral(SEIS["H"], SEIS["L_embed"], r.EI_col, r.EI_shaft, SHAFT["D"],
                           SEIS["P_dead"], replace(prof, stiffness_factor=soft["factor"]),
                           r.Mo / SEIS["H"], M_head=0.0)
    assert r.pile["Df_eq_gov"] == pytest.approx(sol.Df_eq, rel=1e-9)
    g = SEIS["by_code"]["SDC 2.1"]["soil"]["fixed-free"]
    assert r.pile["Df_eq_gov"] == pytest.approx(g["gov_Df_eq"], rel=REL)


def test_soil_moment_exceeds_interface():
    r = run(shaft_basis="soil", soil=soil(), L_embed_in=SEIS["L_embed"])
    gov = max((b for b in r.pile["bounds"] if b["stable"]), key=lambda b: b["Mmax"])
    assert gov["Mmax"] > r.Mo and gov["z_Mmax"] > 0.0
    assert r.shaft_Mdemand > r.Mo
    zs = [z for z, *_ in r.pile["profile_gov"]]
    assert zs[0] == pytest.approx(0.0) and all(b > a for a, b in zip(zs, zs[1:]))
    assert len(r.pile["profile_gov"][0]) == 4


def test_unstable_soil_is_NG_not_pass():
    u = GOLDEN["pile"]["unstable"]
    r = run(shaft_basis="soil", soil=soil(layers=u["profile"]), L_embed_in=u["L_embed"],
            soil_bounds=(0.5,))
    c = chk(r, "Shaft p-y solve")
    assert c.ok is False and "soil too soft or shaft too short" in c.detail
    assert c.ratio == 1.0                                 # finite
    assert chk(r, "Soil-pile stability (p-y)").ok is False
    assert r.pile["Df_eq_gov"] is None and r.Df is None
    assert r.shaft_Mdemand > 0.0                          # never zero demand
    assert not all(x.ok for x in r.checks)


def test_partially_unstable_soil_is_NG_demand_from_stable_bound():
    """Golden soft clay (ruling 7-1): the x0.5 bound is unstable.  Upstream
    inground_demand drops it from the overstrength envelope (the demand comes
    from the stable bound), but upstream check 13 "Soil-pile stability (p-y)"
    fails because a bound is unstable at the yield force F_y = Mp/H."""
    g = SEIS["by_code"]["SDC 2.1"]["soil"]["fixed-free"]
    r = run(shaft_basis="soil", soil=soil(), L_embed_in=SEIS["L_embed"])
    st = {b["factor"]: b["stable"] for b in r.pile["bounds"]}
    assert st == {2.0: True, 0.5: False}
    stab = chk(r, "Soil-pile stability (p-y)")
    assert stab.ok is False and stab.demand == 1 and stab.capacity == 0
    assert stab.ref == ""
    assert stab.detail == ("1/2 soil bounds converged to a physical solution; UNSTABLE: "
                           "soil too soft / shaft too short or slender for the pile-head "
                           "force (increase embedment or shaft size, or improve the soil)")
    c = chk(r, "Shaft p-y solve")              # demand was established
    assert c.ok is True and c.demand == 1 and c.capacity == 2 and "x0.5" in c.detail
    assert c.ratio == 0.5
    assert r.pile["M_inground"] == pytest.approx(g["M"], rel=REL)   # stable bound only
    assert any("x0.5" in w for w in r.warnings)
    soft = [b for b in r.pile["bounds"] if not b["stable"]][0]
    assert soft["Df_eq"] is None and soft["Mmax"] is None
    assert not all(x.ok for x in r.checks)


STAB = SEIS["stability"]


@pytest.mark.parametrize("key", list(STAB))
def test_soil_pile_stability_matches_upstream_yield_level(key):
    """Per-bound stability at F_y (x2, head fixed for fixed-fixed) = upstream _specs_for."""
    pname, head = key.split("|")
    end = "fixed-fixed" if head == "fixed" else "fixed-free"
    r = run(shaft_basis="soil", soil=soil(pname), L_embed_in=SEIS["L_embed"],
            end_condition_long=end, end_condition_trans=end)
    exp = STAB[key]["bounds"]
    got = r.pile["stability"][end]
    assert [b["factor"] for b in got] == [b["bound"] for b in exp]
    assert [b["stable"] for b in got] == [b["stable"] for b in exp]
    for gb, eb in zip(got, exp):
        if eb["stable"]:
            assert gb["Df_eq"] == pytest.approx(eb["Df_eq"], rel=REL)
    n_bad = sum(not b["stable"] for b in exp)
    c = chk(r, "Soil-pile stability (p-y)")
    assert c.demand == n_bad and c.ok == (n_bad == 0)
    assert "governs" not in c.detail                    # both directions identical


def test_soil_pile_stability_envelopes_directions():
    """soft clay: fixed-free unstable at F_y, fixed-fixed stable -> NG, longitudinal governs."""
    r = run(shaft_basis="soil", soil=soil(), L_embed_in=SEIS["L_embed"],
            end_condition_long="fixed-free", end_condition_trans="fixed-fixed")
    c = chk(r, "Soil-pile stability (p-y)")
    assert c.ok is False and c.detail.endswith("  [longitudinal governs]")
    assert set(r.pile["stability"]) == {"fixed-free", "fixed-fixed"}


def test_cached_pile_solutions_not_mutated():
    ps._PILE_CACHE.clear()
    run(shaft_basis="soil", soil=soil(), L_embed_in=SEIS["L_embed"])
    snap = {k: (list(v.x), list(v.moment), list(v.shear), list(v.y))
            for k, v in ps._PILE_CACHE.items()}
    run(shaft_basis="soil", soil=soil(), L_embed_in=SEIS["L_embed"],
        end_condition_long="fixed-fixed")
    for k, (x, m, v, y) in snap.items():
        s = ps._PILE_CACHE[k]
        assert (s.x, s.moment, s.shear, s.y) == (x, m, v, y)


# ── required transverse ───────────────────────────────────────────

@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("probe", range(4))
def test_required_transverse_matches_upstream_probes(code, probe):
    """Upstream cross-check: each golden (bar, pitch) probe's phiVn and rho_s.  With the
    search limited to that one candidate, required_transverse accepts it just below
    the upstream phiVn / rho_s and rejects it just above."""
    g = SEIS["by_code"][code]
    pr = g["trans_probes"][probe]
    prov = get_provisions(code)
    params = dict(stirMin=pr["bar"], stirMax=pr["bar"], sMax=pr["s"], sMin=pr["s"], maxLegs=2)
    P = SEIS["P_dead"]
    mu = prov.mu_d_limit_single

    def req(Vo, rho_min):
        return cs.required_transverse(COLUMN, COL_CAGE, prov, Vo, P, mu, rho_min, None, 0, params)

    ok = req(pr["phiVn"] * (1 - 1e-2), pr["rho_s"] * (1 - 1e-2))
    assert ok["ok"] and (ok["bar"], ok["s"]) == (pr["bar"], pr["s"])
    assert ok["phiVn"] == pytest.approx(pr["phiVn"], rel=REL)
    assert ok["rho_s"] == pytest.approx(pr["rho_s"], rel=REL)
    assert req(pr["phiVn"] * (1 + 1e-2), 0.0)["ok"] is False
    assert req(0.0, pr["rho_s"] * (1 + 1e-2))["ok"] is False


@pytest.mark.parametrize("code", CODES)
def test_required_transverse_meets_criteria(code):
    r = run(code, end_condition_long="fixed-fixed")
    q = r.required_transverse
    assert q["ok"] is True and q["phiVn"] >= r.Vo
    assert q["rho_s"] >= r.rho_s_min and q["s"] <= r.s_max_detailing + 1e-9
    assert q["bar"] >= r.min_trans_bar


def test_required_transverse_solves_each_bar_pitch_once(monkeypatch):
    calls = []
    real = cs.shear_capacity

    def counting(sec, *a, **k):
        calls.append((sec.spiral_bar_no, sec.spiral_spacing))
        return real(sec, *a, **k)

    monkeypatch.setattr(cs, "shear_capacity", counting)
    prov = get_provisions("SDC 2.1")
    out = cs.required_transverse(COLUMN, COL_CAGE, prov, 1e9, 800.0, 5.0, 0.0, None, 0,
                                 dict(maxLegs=4))
    assert out["ok"] is False
    assert len(calls) == len(set(calls)) > 0


def test_soil_input_validation():
    r = run(shaft_basis="soil", soil=soil(), L_embed_in=SEIS["L_embed"], soil_bounds=None)
    assert [b["factor"] for b in r.pile["bounds"]] == [2.0, 0.5]
    for bad in (None, 0.0, -10.0):
        with pytest.raises(ValueError, match="L_embed_in"):
            run(shaft_basis="soil", soil=soil(), L_embed_in=bad)
    with pytest.raises(ValueError, match="L_embed_in"):
        cs.seismic_design(COLUMN, SHAFT, COL_CAGE, SHAFT_CAGE, DEAD_ONLY,
                          {"H_in": 240.0, "soil": soil()}, get_provisions("SDC 2.1"))


def test_required_transverse_none_when_unreachable():
    r = run(H_in=40.0, end_condition_long="fixed-fixed")   # huge Vo
    assert r.required_transverse["ok"] is False
    assert r.required_transverse["bar"] is None


def test_seismic_design_speed():
    t0 = time.perf_counter()
    run(shaft_basis="soil", soil=soil(), L_embed_in=SEIS["L_embed"],
        axial={"P_dead": -800.0, "P_ext_min": -2000.0, "P_ext_max": -200.0},
        end_condition_long="fixed-fixed")
    assert time.perf_counter() - t0 < 10.0
