"""Pins the pure-Python seismic port to golden values from the upstream numpy code."""
import json
import math
import os
import time

import pytest

from seismic_port.materials import bar_area, bar_diameter
from seismic_port.moment_curvature import _brentq, moment_curvature
from seismic_port.section import CircularSection

with open(os.path.join(os.path.dirname(__file__), "golden",
                       "seismic_port_golden.json"), encoding="utf-8") as _f:
    GOLDEN = json.load(_f)
NAMES = list(GOLDEN["sections"])
REL = 5e-3


def _sec(name):
    return CircularSection(**GOLDEN["sections"][name]["params"])


def test_golden_has_source_commit():
    assert GOLDEN["source_commit"].startswith("9265d67")


def test_bar_catalogue():
    assert bar_area(11) == 1.56 and bar_diameter(11) == 1.410


@pytest.mark.parametrize("name", NAMES)
def test_materials_match_golden(name):
    g, s = GOLDEN["sections"][name], _sec(name)
    assert s.confined.eps_cu == pytest.approx(g["confined"]["eps_cu"], rel=REL)
    for k, v in g["confined"].items():
        if k == "eps_cu":
            continue
        eps = s.confined.eps_cu if k == "stress_at_eps_cu" else float(k)
        assert s.confined.stress(eps) == pytest.approx(v, rel=REL)
    for k, v in g["steel"].items():
        assert s.steel.stress(float(k)) == pytest.approx(v, rel=REL)


@pytest.mark.parametrize("name", NAMES)
def test_section_props_match_golden(name):
    g, s = GOLDEN["sections"][name], _sec(name)
    for attr in ("Ag", "Acore", "rho_l", "rho_s"):
        assert getattr(s, attr) == pytest.approx(g[attr], rel=REL)


@pytest.mark.parametrize("name", NAMES)
def test_fibres_consistent(name):
    s = _sec(name)
    y, Ac, Au = s.concrete_fibres()
    assert isinstance(y, list) and len(y) == len(Ac) == len(Au) == s.n_strips
    assert math.fsum(Ac) == pytest.approx(s.Acore, rel=REL)
    assert math.fsum(Ac) + math.fsum(Au) == pytest.approx(s.Ag, rel=REL)
    ys, As = s.steel_fibres()
    assert len(ys) == len(As) == s.n_bars
    assert math.fsum(As) == pytest.approx(s.Ast, rel=1e-9)
    assert abs(math.fsum(ys)) < 1e-6


MPHI_CASES = [(n, a) for n in NAMES
              for a in GOLDEN["sections"][n]["moment_curvature"]]


@pytest.mark.parametrize("name,axial", MPHI_CASES)
def test_mphi_matches_golden(name, axial):
    g = GOLDEN["sections"][name]["moment_curvature"][axial]
    r = moment_curvature(_sec(name), float(axial))
    assert r.failure_mode == g["failure_mode"]
    for attr in ("phi_y", "Mp", "phi_u", "Mu"):
        assert getattr(r, attr) == pytest.approx(g[attr], rel=REL), attr
    assert r.phi_yield_first == pytest.approx(g["phi_yield_first"], rel=REL)
    assert r.M_yield_first == pytest.approx(g["M_yield_first"], rel=REL)
    assert isinstance(r.phi, list) and isinstance(r.M, list)
    assert r.EI_eff == pytest.approx(r.Mp / r.phi_y)


def test_mphi_speed_48in_section():
    s = _sec(NAMES[0])
    t0 = time.perf_counter()
    moment_curvature(s, 500.0)
    assert time.perf_counter() - t0 < 0.5


def test_brentq_contract():
    assert _brentq(lambda x: x * x - 2, 0.0, 2.0, xtol=1e-12) == pytest.approx(math.sqrt(2), abs=1e-10)
    with pytest.raises(ValueError):
        _brentq(lambda x: x * x + 1, -1.0, 1.0)


def test_brentq_raises_runtimeerror_when_not_converged():
    # scipy.optimize.brentq (disp=True) raises RuntimeError when maxiter is exhausted
    with pytest.raises(RuntimeError):
        _brentq(lambda x: x ** 3 - 2, 0.0, 5.0, xtol=1e-14, maxiter=1)


# ---------------------------------------------------------------- Task 3 -----
import dataclasses

from seismic_port import shear as sh
from seismic_port.provisions import CodeProvisions, get_provisions

PROV_KEYS = ["SDC 2.1", "AASHTO SGS 3rd Ed."]
BALANCE = {"balance_k_ratio_adjacent", "balance_k_ratio_any", "balance_T_ratio",
           "ref_balanced_stiffness", "ref_balanced_stiffness_any",
           "ref_balanced_geometry", "ref_balance_tuning"}


def _close(a, b):
    return a == pytest.approx(b, rel=REL, abs=1e-9)


@pytest.mark.parametrize("name", NAMES)
def test_shear_matches_golden(name):
    s = _sec(name)
    for key, g in GOLDEN["sections"][name]["shear"].items():
        pk, P, mu, hinge = key.split("|")
        prov = get_provisions(pk)
        phi_vn, vc, vs = sh.shear_capacity(s, float(P), float(mu), hinge == "True", prov)
        assert _close(phi_vn, g["phiVn"]), key
        assert _close(vc, g["Vc"]), key
        assert _close(vs, g["Vs"]), key
        b = sh.shear_breakdown(s, float(P), float(mu), hinge == "True", prov)
        for k, v in g["breakdown"].items():
            if isinstance(v, str):
                assert getattr(b, k) == v, (key, k)
            else:
                assert _close(getattr(b, k), v), (key, k)


def test_shear_tension_gives_zero_vc():
    s = _sec(NAMES[0])
    for pk in PROV_KEYS:
        assert sh.shear_capacity(s, -200.0, 3.0, True, get_provisions(pk))[1] == 0.0


@pytest.mark.parametrize("name", NAMES)
def test_min_transverse_matches_golden(name):
    g, s = GOLDEN["sections"][name], _sec(name)
    d = GOLDEN["detailing"][name]
    p = g["params"]
    dbl, dsp = bar_diameter(p["long_bar_no"]), bar_diameter(p["spiral_bar_no"])
    assert _close(sh.longitudinal_bar_spacing(p["D"], p["cover"], dsp, dbl, p["n_bars"]), d["lng_spacing"])
    for got, exp in ((sh.max_transverse_spacing(p["D"], dbl, False), d["max_trans"]),
                     (sh.max_transverse_spacing(p["D"], dbl, True), d["max_trans_bundled"]),
                     (sh.max_transverse_spacing_caltrans(dbl), d["max_trans_caltrans"]),
                     (sh.max_longitudinal_spacing_caltrans(p["D"]), d["max_long_caltrans"])):
        assert _close(got[0], exp[0]) and got[1] == exp[1]
    assert sh.min_transverse_bar_no(p["long_bar_no"], p.get("long_bundle", 1) > 1) == d["min_bar_no"]
    assert _close(sh.max_bar_diameter(p["fc"], 300.0, p["D"], 68.0), d["max_bar_diameter"])
    for b, a in zip((1, 2, 3), d["anchorage"]):
        assert _close(sh.anchorage_length(dbl, 68.0, p["fc"], b), a)
    for b, a in zip((1, 2, 3), d["eff_bar_d"]):
        assert _close(sh.effective_bar_diameter(dbl, b), a)
    assert _close(sh.min_transverse_ratio(p["fc"], 68.0, s.Ag, s.Acore, 0.0, 0.0, 0.005), d["min_ratio_aashto"])
    assert _close(sh.min_transverse_ratio(p["fc"], 68.0, s.Ag, s.Acore), d["min_ratio_aci"])
    assert _close(sh.axial_load_ratio(400.0, p["fc"], s.Ag), d["axial_ratio"])
    for (H, Pd), exp in zip(d["caltrans_min_args"], d["caltrans_min"]):
        got = sh.caltrans_min_transverse_ratio(p["D"], H, s.rho_l, Pd, p["fc"], s.Ag)
        assert _close(got[0], exp[0]) and got[1] == exp[1] and got[2] == exp[2]


@pytest.mark.parametrize("pk", PROV_KEYS)
def test_refs_copied_verbatim(pk):
    prov = get_provisions(pk)
    gold = GOLDEN["provisions"][pk]
    got = dataclasses.asdict(prov)
    assert set(got) == set(gold)              # same fields, balance fields dropped
    assert not (set(got) & BALANCE)
    for k, v in gold.items():
        assert got[k] == v, k                 # every ref_* string and number identical
    assert sum(k.startswith("ref_") for k in gold) >= 14


def test_provision_key_aliases():
    assert get_provisions("SDC_2_0") is get_provisions("SDC 2.1")
    assert get_provisions("SDC 2.0") is get_provisions("SDC 2.1")
    assert get_provisions("AASHTO_SGS") is get_provisions("AASHTO SGS 3rd Ed.")
    assert get_provisions("AASHTO_SGS").shaft_demand_factor == 1.25
    assert isinstance(get_provisions("SDC_2_0"), CodeProvisions)
