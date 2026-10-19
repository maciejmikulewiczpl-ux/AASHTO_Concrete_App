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
