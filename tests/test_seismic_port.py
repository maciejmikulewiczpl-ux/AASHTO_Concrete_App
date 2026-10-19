"""Pins the pure-Python seismic port to golden values from the upstream numpy code."""
import json
import math
import os

import pytest

from seismic_port.materials import bar_area, bar_diameter
from seismic_port.section import CircularSection

with open(os.path.join(os.path.dirname(__file__), "golden",
                       "seismic_port_golden.json")) as _f:
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
        eps = s.confined.eps_cu if k in ("eps_cu", "stress_at_eps_cu") else float(k)
        if k == "eps_cu":
            continue
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
