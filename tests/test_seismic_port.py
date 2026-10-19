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


# ---------------------------------------------------------------- Task 3A ----
from dataclasses import replace as _replace

from seismic_port import pile_solver as ps
from seismic_port.pile_solver import (PileSolution, equivalent_fixity_depth,
                                      inground_demand, solve_lateral)
from seismic_port.soil import PY_MODELS, SoilLayer, SoilProfile

PILE = GOLDEN["pile"]
PILE_FIELDS = ("head_deflection", "head_stiffness", "head_flexibility", "Df_eq",
               "max_inground_moment", "max_moment_depth", "max_inground_shear")


def _pile_profile(layers, factor=1.0):
    return SoilProfile(tuple(SoilLayer.from_engineering(t, m, g, **kw)
                             for t, m, g, kw in layers), stiffness_factor=factor)


def _pile_solve(c, layers=None):
    prof = _pile_profile(layers or PILE["profiles"][c["profile"]], c["bound"])
    return solve_lateral(c["Hcol"], c["L_embed"], PILE["EI_col"], PILE["EI_shaft"],
                         PILE["D_shaft"], PILE["axial"], prof, c["V_head"],
                         M_head=c["M_head"])


def _case_id(c):
    return "%s-H%.0f-%s-b%s" % (c["profile"], c["Hcol"], c["end"], c["bound"])


def test_pile_golden_records_inputs():
    assert PILE["axial"] == 800.0
    assert PILE["EI_col"] > 0 and PILE["EI_shaft"] > PILE["EI_col"]
    assert PY_MODELS == ("matlock_soft_clay", "welch_stiff_clay", "api_sand",
                         "elastic_subgrade")
    assert len(PILE["cases"]) == 3 * 2 * 2 * 2


@pytest.mark.parametrize("c", PILE["cases"], ids=_case_id)
def test_pile_matches_golden(c):
    g, s = c["result"], _pile_solve(c)
    assert isinstance(s, PileSolution)
    assert s.stable == g["stable"]
    if not g["stable"]:
        return
    assert s.converged and s.ground_index == g["ground_index"]
    assert isinstance(s.x, list) and len(s.x) == g["n_nodes"]
    assert abs(s.iterations - g["iterations"]) <= 1
    for k in PILE_FIELDS:
        if g[k] == 0.0:
            assert abs(getattr(s, k)) < 1e-6, k
        else:
            assert getattr(s, k) == pytest.approx(g[k], rel=REL), k
    assert s.moment[s.ground_index] == pytest.approx(g["M_ground"], rel=REL)
    for arr in ("x", "y", "moment", "shear"):
        ref = g[arr]
        scale = max(abs(v) for v in ref)
        got = [getattr(s, arr)[i] for i in g["sample_index"]]
        for a, b in zip(got, ref):
            assert abs(a - b) <= REL * scale, arr


@pytest.mark.parametrize("d", PILE["inground_demand"],
                         ids=lambda d: "%s-H%.0f-%s" % (d["profile"], d["Hcol"], d["end"]))
def test_inground_demand_matches_golden(d):
    prof = _pile_profile(PILE["profiles"][d["profile"]])
    M, V, gov = inground_demand(d["Hcol"], 720.0, PILE["EI_col"], PILE["EI_shaft"],
                                PILE["D_shaft"], PILE["axial"], prof, d["V_head"],
                                soil_bounds=tuple(PILE["bounds"]),
                                M_head=d["M_head"])
    assert (gov is None) == d["gov_none"]
    assert M == pytest.approx(d["M"], rel=REL)
    assert V == pytest.approx(d["V"], rel=REL)
    assert gov.max_inground_moment == M


def test_unstable_flagged():
    u = PILE["unstable"]
    c = dict(u, M_head=0.0)
    s = _pile_solve(c, layers=u["profile"])
    assert s.stable is False and u["result"]["stable"] is False
    assert s.converged == u["result"]["converged"]
    assert s.Df_eq == pytest.approx(50.0 * PILE["D_shaft"])   # flexible sentinel
    assert s.head_stiffness == 0.0 and s.head_flexibility == float("inf")
    assert all(math.isfinite(v) for v in s.y)
    # every bound unstable -> inground_demand returns (0, 0, None)
    prof = _pile_profile(u["profile"])
    M, V, gov = inground_demand(u["Hcol"], u["L_embed"], PILE["EI_col"],
                                PILE["EI_shaft"], PILE["D_shaft"], PILE["axial"],
                                prof, u["V_head"], soil_bounds=(u["bound"],))
    assert (M, V, gov) == (0.0, 0.0, None)


def test_singular_solve_degrades_to_unstable(monkeypatch):
    def _raise(*_a, **_k):
        raise ps.LinAlgError("singular matrix")

    monkeypatch.setattr(ps, "_solve_banded", _raise)
    prof = _pile_profile(PILE["profiles"]["sand_water_table"])
    s = solve_lateral(198.0, 720.0, 3e10, 3e10, 124.0, 1360.0, prof, 500.0)
    assert not s.stable and not s.converged
    assert s.Df_eq == pytest.approx(50.0 * 124.0)
    assert all(math.isfinite(v) for v in s.y)


def test_nonfinite_solve_degrades_to_unstable(monkeypatch):
    monkeypatch.setattr(ps, "_solve_banded",
                        lambda ab, b, bw=3: [float("inf")] * len(b))
    prof = _pile_profile(PILE["profiles"]["sand_water_table"])
    s = solve_lateral(198.0, 720.0, 3e10, 3e10, 124.0, 1360.0, prof, 500.0)
    assert not s.stable
    assert all(math.isfinite(v) for v in s.y)


def test_solve_banded_matches_dense_with_pivoting():
    # non-symmetric, indefinite banded system that needs row pivoting (zero
    # leading diagonal), solution known by construction
    n, bw = 9, 3
    K = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(max(0, i - bw), min(n, i + bw + 1)):
            K[i][j] = ((i * 7 + j * 3) % 11) - 5.0 + (0.5 if i == j else 0.0)
    K[0][0] = 0.0
    ab = [[0.0] * n for _ in range(2 * bw + 1)]
    for i in range(n):
        for j in range(max(0, i - bw), min(n, i + bw + 1)):
            ab[bw + i - j][j] = K[i][j]
    x_true = [1.0 + 0.1 * i for i in range(n)]
    b = [sum(K[i][j] * x_true[j] for j in range(n)) for i in range(n)]
    x = ps._solve_banded(ab, b, bw)
    for a, e in zip(x, x_true):
        assert a == pytest.approx(e, rel=1e-9)
    singular = [[0.0] * 3 for _ in range(2 * bw + 1)]
    with pytest.raises(ps.LinAlgError):
        ps._solve_banded(singular, [1.0, 1.0, 1.0], bw)


@pytest.mark.parametrize("prof_name", ["stiff_clay_over_sand", "sand_water_table"])
@pytest.mark.parametrize("end", ["free", "fixed"])
def test_interface_moment_equals_Mo(prof_name, end):
    """First-order (axial 0): M at the ground node = Mo for both end conditions.

    Fixed-fixed uses V = 2Mo/H with M_head = +Mo: upstream's DOF-1 convention
    (seismic-column sdc_capacity passes ``M_head=Mo``; -Mo lands 3Mo at the
    interface, see test_head_moment_wrong_sign_gives_3Mo).  At axial 800 kip the
    P-Delta amplification adds 3-11 %, which the golden cases pin instead.
    """
    Mo, H = PILE["Mo"], 480.0
    V, Mh = (Mo / H, 0.0) if end == "free" else (2.0 * Mo / H, Mo)
    s = solve_lateral(H, 720.0, PILE["EI_col"], PILE["EI_shaft"], PILE["D_shaft"],
                      0.0, _pile_profile(PILE["profiles"][prof_name]), V, M_head=Mh)
    assert s.stable
    assert abs(s.moment[s.ground_index]) == pytest.approx(Mo, rel=5e-3)


def test_head_moment_wrong_sign_gives_3Mo():
    Mo, H = PILE["Mo"], 480.0
    s = solve_lateral(H, 720.0, PILE["EI_col"], PILE["EI_shaft"], PILE["D_shaft"],
                      0.0, _pile_profile(PILE["profiles"]["sand_water_table"]),
                      2.0 * Mo / H, M_head=-Mo)
    assert abs(s.moment[s.ground_index]) > 2.0 * Mo


def _elastic(ks, L):
    return SoilProfile((SoilLayer(thickness=L, py_model="elastic_subgrade",
                                  gamma_eff=0.0, k_py=ks),))


def test_elastic_closed_form():
    """Hetenyi semi-infinite beam on elastic foundation, free head, point load H:
    y0 = 2*H*beta/k and M_max = 0.3224*H/beta (upstream's validation case)."""
    EI, ks, D, H = 3.0e9, 2.0, 48.0, 50.0
    beta = (ks / (4 * EI)) ** 0.25
    L = 12.0 / beta
    s = solve_lateral(0.0, L, EI, EI, D, 0.0, _elastic(ks, L), H, max_nodes=401)
    assert s.converged and s.stable
    assert s.head_deflection == pytest.approx(2 * H * beta / ks, rel=0.01)
    assert s.max_inground_moment == pytest.approx(0.3224 * H / beta, rel=0.01)


def test_equivalent_fixity_depth():
    f_col = 240.0 ** 3 / (3.0 * 2.5e9)
    assert equivalent_fixity_depth(0.5 * f_col, 240.0, 2.5e9, 5.0e9) == 0.0
    d1 = equivalent_fixity_depth(2 * f_col, 240.0, 2.5e9, 5.0e9)
    d2 = equivalent_fixity_depth(5 * f_col, 240.0, 2.5e9, 5.0e9)
    assert 0 < d1 < d2
    # closed-form free-head inversion round-trips the cantilever flexibility
    f = 240.0 ** 3 / (3 * 2.5e9) + ((240.0 + d1) ** 3 - 240.0 ** 3) / (3 * 5.0e9)
    assert f == pytest.approx(2 * f_col, rel=1e-9)
    df = equivalent_fixity_depth(2 * f_col, 240.0, 2.5e9, 5.0e9, end_fixity="fixed")
    assert df > d1
    with pytest.raises(ValueError):
        equivalent_fixity_depth(2 * f_col, 240.0, 2.5e9, 5.0e9, end_fixity="x")
    assert equivalent_fixity_depth(float("inf"), 240.0, 2.5e9, 5.0e9) == 0.0


def test_soil_layer_from_engineering_and_profile():
    lyr = SoilLayer.from_engineering(10, "api_sand", 120, phi_deg=35, k_pci=90,
                                     submerged=True)
    assert lyr.thickness == 120.0
    assert lyr.gamma_eff == pytest.approx((120 - 62.4) / 1728000.0)
    assert lyr.k_py == pytest.approx(0.09)
    with pytest.raises(ValueError):
        SoilLayer(thickness=120, py_model="nope", gamma_eff=1e-5)
    p = _pile_profile(PILE["profiles"]["stiff_clay_over_sand"])
    assert p.depth == p.total_depth == 960.0
    assert not hasattr(p, "below") and not hasattr(p, "surface_offset")
    assert p.layer_at(300.0)[0].py_model == "api_sand"
    assert p.p_of_y(100.0, 0.5, 96.0) > p.p_of_y(100.0, 0.1, 96.0) > 0
    assert _replace(p, stiffness_factor=2.0).p_of_y(100.0, 0.5, 96.0) == \
        pytest.approx(2.0 * p.p_of_y(100.0, 0.5, 96.0))


def test_pile_solve_under_2s():
    worst = max((c for c in PILE["cases"] if c["result"]["stable"]),
                key=lambda c: c["result"]["iterations"])
    t0 = time.perf_counter()
    _pile_solve(worst)
    assert time.perf_counter() - t0 < 2.0
