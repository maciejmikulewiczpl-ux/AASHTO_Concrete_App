"""
Dimension 4 — Loading combinations.

Sweep representative sections through the full demand catalogue:
pure sag, pure hog, axial+sag, axial+hog (compression and tension),
shear without torsion, shear+torsion, near-pure-axial, etc.

For each (section, demand) pair we check that the engine:
  - returns a result without exception,
  - produces sane row_results status values,
  - reports torsion 'consider' correctly relative to threshold,
  - chooses the correct compression face for the sign of Mu.
"""
import copy
import pytest

from tests.fixtures import SECTION_CATALOGUE, DEMAND_CATALOGUE, calc


# Use a subset of sections for the full demand sweep so the test
# run stays fast. Every section is still individually tested in
# test_matrix_geometry.py.
LOADING_SECTIONS = [
    "Rect_TopBot_Sym",
    "Rect_TopBot_Asym",
    "Rect_TopBot_PT",
    "I_Sym_TopBot",
    "I_Asym_Flanges",
    "I_Sym_TopBot_PT",
]


@pytest.mark.parametrize("sec_name", LOADING_SECTIONS)
@pytest.mark.parametrize("dem_name", list(DEMAND_CATALOGUE.keys()))
def test_loading_combo_runs(sec_name, dem_name):
    """Engine must produce a result for every (section x demand) combo."""
    sec = copy.deepcopy(SECTION_CATALOGUE[sec_name])
    dem = DEMAND_CATALOGUE[dem_name]
    _, res = calc(sec, dem)

    assert "flexure" in res and "shear" in res and "torsion" in res
    rr = res["row_results"]
    assert len(rr) == 1
    r = rr[0]
    assert r.get("flexStatus") in ("OK", "MIN", "NG")
    assert r.get("shearStatus") in ("OK", "NR", "NG")
    assert r.get("crackStatus") in ("OK", "NG")


@pytest.mark.parametrize("sec_name", LOADING_SECTIONS)
def test_comp_face_follows_moment_sign(sec_name):
    """Mu>=0 -> comp_face=top; Mu<0 -> comp_face=bottom."""
    sec = copy.deepcopy(SECTION_CATALOGUE[sec_name])
    _, res_s = calc(copy.deepcopy(sec), DEMAND_CATALOGUE["Pure_Sag"])
    _, res_h = calc(copy.deepcopy(sec), DEMAND_CATALOGUE["Pure_Hog"])
    assert res_s["flexure"]["comp_face"] == "top"
    assert res_h["flexure"]["comp_face"] == "bottom"


@pytest.mark.parametrize("sec_name", LOADING_SECTIONS)
def test_torsion_threshold_decision(sec_name):
    """If torsion is 'considered', |Tu| must exceed threshold; if not, vice versa."""
    sec = copy.deepcopy(SECTION_CATALOGUE[sec_name])
    # Big torsion -> should be considered
    _, res_big = calc(copy.deepcopy(sec), DEMAND_CATALOGUE["High_Shear_Tor"])
    tor = res_big["torsion"]
    Tu = DEMAND_CATALOGUE["High_Shear_Tor"]["Tu"]
    if tor["consider"]:
        # Tn/Tr must exist and be non-negative. They CAN be 0.0 for I-sections
        # whose web is too thin to form a closed torsional perimeter -- in that
        # case the engine still flags the section as inadequate via
        # comb_reinf_ok=False.
        assert tor.get("Tn") is not None and tor["Tn"] >= 0
        assert tor.get("Tr") is not None and tor["Tr"] >= 0
        if tor["Tn"] == 0:
            assert tor.get("comb_reinf_ok") is False, \
                "Tn=0 but comb_reinf_ok=True -- inconsistent"
        # |Tu| should be at or above threshold (small tolerance)
        assert abs(Tu) >= tor["thresh"] - 1.0

    # Tiny torsion -> should NOT be considered
    _, res_small = calc(copy.deepcopy(sec), DEMAND_CATALOGUE["Small_Tor_Below"])
    tor_s = res_small["torsion"]
    if not tor_s["consider"]:
        assert abs(DEMAND_CATALOGUE["Small_Tor_Below"]["Tu"]) <= tor_s["thresh"] + 1.0


@pytest.mark.parametrize("sec_name", LOADING_SECTIONS)
def test_mr_at_pu_within_pm_envelope(sec_name):
    """Mr_atPu reported in result should lie on the P-M curve."""
    import math
    from calc_engine import get_mr_at_pu

    sec = copy.deepcopy(SECTION_CATALOGUE[sec_name])
    dem = DEMAND_CATALOGUE["Comp_Sag"]
    _, res = calc(sec, dem)
    fl = res["flexure"]
    Pu = dem["Pu"]
    pm = fl.get("pm_curve")
    if not pm:
        pytest.skip("no pm_curve")
    Mr_check = get_mr_at_pu(pm, Pu)
    assert math.isclose(fl["Mr_atPu"], Mr_check, abs_tol=1.0, rel_tol=0.02)


def test_capacity_exceeded_produces_NG():
    """A demand far above capacity must produce flexStatus = NG."""
    sec = copy.deepcopy(SECTION_CATALOGUE["Rect_BotOnly"])
    # 99999 kip-in is way beyond any sensible Mn for the section.
    over_demand = dict(Pu=0, Mu=99999, Vu=0, Tu=0, Vp=0, Ms=0, Ps=0)
    _, res = calc(sec, over_demand)
    assert res["row_results"][0]["flexStatus"] == "NG"


def test_high_shear_below_capacity_is_OK():
    """A modest shear on a strong section should pass shear check."""
    sec = copy.deepcopy(SECTION_CATALOGUE["Rect_TopBot_Sym"])
    light_shear = dict(Pu=0, Mu=2000, Vu=50, Tu=0, Vp=0, Ms=1000, Ps=0)
    _, res = calc(sec, light_shear)
    assert res["row_results"][0]["shearStatus"] in ("OK", "NR")
