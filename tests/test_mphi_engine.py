"""Moment-curvature secant stiffness (mphi_engine) — pinned against closed-form / existing engines."""
import math

import pytest

import mphi_engine as me
from calc_engine import BARS, calculate_all
from tests.fixtures import demand, make_inputs
from tests.test_circular import circ_inputs


def _engine_icr(inp, Ms):
    return calculate_all(inp, [demand(Mu=abs(Ms) * 1.5, Ms=Ms)], 0)["flexure"]["Icr"]


@pytest.mark.parametrize("name,inp", [
    ("rect", make_inputs(nBars_bot=6, barN_bot=9)),
    ("I_na_in_web", make_inputs(secType="T-SECTION", b=30, bw_input=10, hf_top=4, hf_bot=6, h=48,
                                nBars_bot=6, barN_bot=10)),
    ("circ", circ_inputs()),
])
def test_linear_no_tension_secant_equals_engine_icr(name, inp):
    Ms = 3000.0
    r = me.moment_curvature_section(inp, Ms=Ms, linear=True, tension=False, n_strips=600)
    Icr = _engine_icr(inp, Ms)
    assert r["service"]["Ieff"] == pytest.approx(Icr, rel=0.005), name


def test_uncracked_secant_equals_transformed_section():
    inp = make_inputs(nBars_bot=4, barN_bot=8)
    r = me.moment_curvature_section(inp, Ms=500.0, linear=True, tension=True, n_strips=600)
    b, h, Ec, Es = inp["b"], inp["h"], inp["Ec"], inp["Es"]
    n = Es / Ec
    As, d = 4 * BARS[8]["a"], inp["d_bot"]
    A = b * h + (n - 1) * As
    yc = (b * h * h / 2 + (n - 1) * As * d) / A
    It = b * h ** 3 / 12 + b * h * (yc - h / 2) ** 2 + (n - 1) * As * (d - yc) ** 2
    assert r["service"]["Ieff"] == pytest.approx(It, rel=0.005)
    fr = 0.24 * math.sqrt(inp["fc"])
    assert r["cracking"]["M"] == pytest.approx(fr * It / (h - yc), rel=0.02)


def test_service_between_icr_and_ig_after_cracking():
    inp = make_inputs(nBars_bot=6, barN_bot=9)
    Icr = _engine_icr(inp, 6000.0)
    r = me.moment_curvature_section(inp, Ms=6000.0)
    assert r["cracking"]["M"] < 6000.0
    assert 0.9 * Icr < r["service"]["Ieff"] < r["Ig"]


def test_hogging_mirrors_sagging():
    sag = make_inputs(nBars_bot=6, barN_bot=9, nBars_top=3, barN_top=6)
    h, cover, ds = sag["h"], sag["cover"], BARS[4]["d"]
    hog = make_inputs(nBars_bot=3, barN_bot=6, nBars_top=6, barN_top=9,
                      d_bot=h - sag["d_top"], d_top=h - sag["d_bot"])
    assert hog["d_bot"] == pytest.approx(h - cover - ds - BARS[6]["d"] / 2)
    a = me.moment_curvature_section(sag, Ms=4000.0)
    b = me.moment_curvature_section(hog, Ms=-4000.0)
    assert b["direction"] == "hogging"
    for key in ("service", "first_yield"):
        assert b[key]["EI"] == pytest.approx(a[key]["EI"], rel=1e-6)
    assert b["ultimate"]["M"] == pytest.approx(a["ultimate"]["M"], rel=1e-6)


@pytest.mark.parametrize("axial", [0.0, 500.0])
def test_circular_expected_matches_seismic_port(axial):
    from seismic_port.moment_curvature import moment_curvature
    from seismic_port.section import CircularSection
    inp = circ_inputs(D=36, cover=2.0, bar1=9, n1=12, trans="hoop", shN=5, s=6)
    sec = CircularSection(D=36, fc=4, cover=2.0, n_bars=12, long_bar_no=9, spiral_bar_no=5,
                          spiral_spacing=6, hoops=True)
    ref = moment_curvature(sec, axial)
    r = me.moment_curvature_section(inp, Ms=1000.0, Ps=-axial, materials="expected")
    assert r["first_yield"]["M"] == pytest.approx(ref.M_yield_first, rel=0.02)
    assert r["first_yield"]["phi"] == pytest.approx(ref.phi_yield_first, rel=0.03)
    assert r["idealised"]["Mp"] == pytest.approx(ref.Mp, rel=0.03)
    assert r["idealised"]["EI"] == pytest.approx(ref.EI_eff, rel=0.04)


def test_compression_raises_cracking_moment():
    inp = make_inputs(nBars_bot=6, barN_bot=9)
    r0 = me.moment_curvature_section(inp, Ms=1000.0)
    r1 = me.moment_curvature_section(inp, Ms=1000.0, Ps=-300.0)
    # compression adds P*(Ig/Ag)/yt = P*h/6 for a rectangle
    assert r1["cracking"]["M"] == pytest.approx(r0["cracking"]["M"] + 300.0 * inp["h"] / 6, rel=0.05)


def test_prestressed_not_available():
    inp = make_inputs(nStrands=10, strand_area=0.153, dp=30, fpe=160)
    r = me.moment_curvature_section(inp, Ms=1000.0)
    assert r["available"] is False and "prestressed" in r["reason"]


def test_ms_beyond_capacity_reported():
    r = me.moment_curvature_section(make_inputs(), Ms=1e6)
    assert "service" not in r and "capacity" in r["service_error"]
    assert r["first_yield"]["EI"] > 0


def test_curve_json_ready_and_bounded():
    import json
    r = me.moment_curvature_section(circ_inputs(), Ms=2000.0, materials="expected")
    assert len(r["curve"]["phi"]) <= me.CURVE_POINTS
    assert r["curve"]["phi"][0] == 0.0 and r["curve"]["phi"] == sorted(r["curve"]["phi"])
    json.dumps(r)


def test_api_moment_curvature_uses_active_row():
    import json
    import api
    inp = make_inputs(nBars_bot=6, barN_bot=9)
    rows = [demand(Ms=500.0), demand(Ms=-3000.0, Ps=-100.0)]
    raw = api.Api().moment_curvature(json.dumps({"inputs": inp, "demandRows": rows, "activeRow": 1,
                                                 "options": {"materials": "nominal"}}))
    r = json.loads(raw)
    assert r["available"] and r["direction"] == "hogging" and r["Ms"] == -3000.0 and r["Ps"] == -100.0
    bad = json.loads(api.Api().moment_curvature(json.dumps({"inputs": inp, "demandRows": rows,
                                                            "options": {"materials": "x"}})))
    assert "error" in bad


# CSiBridge v27.1 Section Designer, Caltrans round section (user benchmark 2026-10-25): D = 8 ft, 2 in clear
# cover, 40 bundles of 2 #14, #8 hoops at 5 ft (as entered), f'ce = 1.3 x 4 = 5.2 ksi, A615 Gr60 at fy = 60 ksi.
# Values in kip-ft and 1/ft: (P tension +, phi_yield_first, M_yield_first, phi_y_idealised, Mp, Mmax).
CSI_ROUND_8FT = [
    (0.0, 3.9759e-4, 22590.322, 5.7920e-4, 32909.0, 34589.16),
    (-1000.0, 4.1423e-4, 25424.533, 5.7051e-4, 35016.0, 36324.481),
    (-4000.0, 4.5689e-4, 31415.852, 5.8841e-4, 40459.0, 41023.192),
]


@pytest.mark.parametrize("P,phi_fy,M_fy,phi_yi,Mp,Mmax", CSI_ROUND_8FT)
def test_circular_expected_matches_csibridge_section_designer(monkeypatch, P, phi_fy, M_fy, phi_yi, Mp, Mmax):
    monkeypatch.setattr(me, "FYE_RATIO", 1.0)  # CSiBridge used fy = 60 ksi for A615 Gr60
    monkeypatch.setattr(me, "FUE_RATIO", 1.5)
    inp = circ_inputs(D=96, cover=2.0, bar1=14, n1=40, bundle1=2, trans="hoop", shN=8, s=60, fc=4.0, fy=60)
    r = me.moment_curvature_section(inp, Ms=1000.0, Ps=P, materials="expected")
    assert r["first_yield"]["phi"] * 12 == pytest.approx(phi_fy, rel=0.02)
    assert r["first_yield"]["M"] / 12 == pytest.approx(M_fy, rel=0.03)
    assert r["idealised"]["phi_y"] * 12 == pytest.approx(phi_yi, rel=0.02)
    assert r["idealised"]["Mp"] / 12 == pytest.approx(Mp, rel=0.02)
    assert max(r["curve"]["M"]) / 12 == pytest.approx(Mmax, rel=0.02)
