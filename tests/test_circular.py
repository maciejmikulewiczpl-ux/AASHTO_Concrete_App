"""Circular section tests: geometry, strain compatibility, P-M, shear/torsion
geometry, service, spiral and report-key contract. Independent checks use
numerical strip integration rather than the engine's closed forms.

Items tagged UNVERIFIED in circ_engine.CIRC_UNVERIFIED are pinned here as the
implemented contract, not as verified AASHTO citations.
"""
import math

import pytest

from calc_engine import BARS, calculate_all
from circ_engine import (CIRC_UNVERIFIED, circle_segment, cracked_section_circ,
                         derive_circular, _rows_cf)
from tests.fixtures import make_inputs, demand
from tests.test_invariants import REQUIRED_FLEX_KEYS, REQUIRED_SHEAR_KEYS, REQUIRED_TORSION_KEYS


def circ_inputs(D=36, cover=2.0, bar1=9, n1=12, bundle1=1, ring2=False, bar2=8, n2=0,
                bundle2=1, Dr2=0, trans="hoop", shN=5, s=6, ties=0, tie_bar=4, shear_legs=2, **kw):
    return make_inputs(secType="CIRCULAR", h=D, b=D, D=D, cover=cover,
                       circ_bar1=bar1, circ_n1=n1, circ_bundle1=bundle1,
                       circ_ring2=ring2, circ_bar2=bar2, circ_n2=n2, circ_bundle2=bundle2,
                       circ_Dr2=Dr2, circ_trans_type=trans, circ_tie_legs=ties,
                       circ_tie_bar=tie_bar, shN=shN, s_shear=s, shear_legs=shear_legs, **kw)


def run(dem=None, **kw):
    raw = circ_inputs(**kw)
    return raw, calculate_all(raw, [dem or demand(Mu=4000, Vu=100, Ms=2000)], 0)


def strips(R, a, n=20000):
    """Numerical segment (depth a from top): area, centroid depth, I about centre."""
    A = Q = Ic = 0.0
    dy = a / n
    for i in range(n):
        y = (i + 0.5) * dy
        z = R - y
        w = 2 * math.sqrt(max(R * R - z * z, 0))
        A += w * dy
        Q += w * dy * y
        Ic += w * dy * z * z
    return A, Q / A, Ic


# ─── Geometry ──────────────────────────────────────────────────────

@pytest.mark.parametrize("a", [0.5, 5, 18, 25, 35.9])
def test_circle_segment_matches_strip_integration(a):
    R = 18.0
    A, y, Ic = circle_segment(R, a)
    A2, y2, Ic2 = strips(R, a)
    assert A == pytest.approx(A2, rel=1e-4)
    assert y == pytest.approx(y2, rel=1e-4)
    assert Ic == pytest.approx(Ic2, rel=1e-4)


def test_circle_segment_full_and_half():
    R = 10.0
    A, y, Ic = circle_segment(R, 2 * R)
    assert A == pytest.approx(math.pi * R * R)
    assert y == pytest.approx(R)
    assert Ic == pytest.approx(math.pi * R ** 4 / 4)
    A, y, _ = circle_segment(R, R)
    assert A == pytest.approx(math.pi * R * R / 2)
    assert y == pytest.approx(R - 4 * R / (3 * math.pi))


def test_gross_props_and_layout():
    I = derive_circular(circ_inputs(D=36, bar1=9, n1=12, shN=5))
    assert I["Ag"] == pytest.approx(math.pi * 18 ** 2)
    assert I["Ig"] == pytest.approx(math.pi * 36 ** 4 / 64)
    assert I["yb_centroid"] == pytest.approx(18)
    r = 18 - 2.0 - BARS[5]["d"] - BARS[9]["d"] / 2
    assert I["circ_rings"][0]["Dr"] == pytest.approx(2 * r)
    assert I["circ_Ast"] == pytest.approx(12 * BARS[9]["a"])
    assert len(I["circ_bars"]) == 12
    assert I["circ_bars"][0]["d_top"] == pytest.approx(18 - r)  # first bar at top


def test_bundles_and_second_ring():
    I = derive_circular(circ_inputs(bar1=10, n1=10, bundle1=2, ring2=True, bar2=8, n2=8, Dr2=20))
    assert I["circ_Ast"] == pytest.approx(10 * 2 * BARS[10]["a"] + 8 * BARS[8]["a"])
    assert I["circ_rings"][1]["Dr"] == pytest.approx(20)
    I3 = derive_circular(circ_inputs(bar1=10, n1=10, bundle1=3))
    r1 = 18 - 2.0 - BARS[5]["d"] - BARS[10]["d"] / 2
    assert I3["circ_rings"][0]["r"] == pytest.approx(r1 - BARS[10]["d"] * math.sqrt(3) / 6)


def test_invalid_diameter_raises():
    with pytest.raises(ValueError):
        derive_circular(circ_inputs(D=0))


# ─── Strength ──────────────────────────────────────────────────────

def _independent_mn(I):
    """Pure-bending Mn by strain compatibility using strip integration (no PT)."""
    R, D = I["D"] / 2, I["D"]
    fc, fy, Es, a1, b1 = I["fc"], I["fy_long"], I["Es"], I["alpha1"], I["beta1"]
    bars = [(b["d_top"], b["As"]) for b in I["circ_bars"]]

    def state(c):
        A, y, _ = strips(R, min(b1 * c, D), n=4000)
        Cc = a1 * fc * A
        F = [(As * max(-fy, min(fy, Es * 0.003 * (d - c) / c)), d) for d, As in bars]
        net = sum(f for f, _ in F) - Cc
        M = Cc * (R - y) + sum(f * (d - R) for f, d in F)
        return net, M

    lo, hi = 0.01, 3 * D
    for _ in range(80):
        mid = (lo + hi) / 2
        if state(mid)[0] > 0:
            lo = mid
        else:
            hi = mid
    return lo, state(lo)[1]


def test_pure_flexure_matches_independent_strain_compat():
    raw, res = run()
    I = derive_circular(dict(raw))
    c_ind, Mn_ind = _independent_mn(I)
    fl = res["flexure"]
    assert fl["c"] == pytest.approx(c_ind, rel=2e-3)
    assert fl["Mn"] == pytest.approx(Mn_ind, rel=2e-3)
    assert fl["Mr"] == pytest.approx(fl["phi_f"] * fl["Mn"])


@pytest.mark.parametrize("trans,closure,factor", [("hoop", "lap", 0.80), ("hoop", "hooked", 0.85),
                                                  ("spiral", "lap", 0.85)])
def test_pn_max_factor(trans, closure, factor):
    # AASHTO 5.6.4.4: Eq. 5.6.4.4-2 (0.85) spirals / hoops closed by weld, coupler or hooks;
    # Eq. 5.6.4.4-3 (0.80) ties / lap-spliced hoops
    raw, res = run(trans=trans, circ_hoop_closure=closure)
    I = derive_circular(dict(raw))
    Ast = I["circ_Ast"]
    expect = -factor * (I["alpha1"] * I["fc"] * (I["Ag"] - Ast) + I["fy_long"] * Ast)
    assert min(p["Pn"] for p in res["flexure"]["pm_curve_sag"]) == pytest.approx(expect)
    assert res["flexure"]["circ"]["pn_factor"] == factor


def test_pm_sag_hog_mirror_and_phi_consistency():
    _, res = run()
    sag, hog = res["flexure"]["pm_curve_sag"], res["flexure"]["pm_curve_hog"]
    assert len(sag) == len(hog)
    for s, h in zip(sag, hog):
        assert s["Pn"] == pytest.approx(h["Pn"], abs=1e-6)
        assert s["Mn"] == pytest.approx(-h["Mn"], abs=1e-6)
        assert s["Pr"] == pytest.approx(s["phi"] * s["Pn"])
        assert s["Mr"] == pytest.approx(s["phi"] * s["Mn"])


def test_row_mr_at_zero_axial_matches_flexure():
    raw = circ_inputs()
    res = calculate_all(raw, [demand(Mu=4000, Vu=50, Ms=100), demand(Mu=-4000, Vu=50, Ms=-100)], 0)
    Mr = res["flexure"]["Mr"]
    assert abs(res["row_results"][0]["Mr"]) == pytest.approx(Mr, rel=0.01)
    assert res["row_results"][1]["Mr"] < 0
    assert abs(res["row_results"][1]["Mr"]) == pytest.approx(Mr, rel=0.01)


def test_axial_compression_raises_mr_below_balance():
    raw = circ_inputs()
    res = calculate_all(raw, [demand(Pu=0, Mu=1000), demand(Pu=-500, Mu=1000)], 0)
    assert abs(res["row_results"][1]["Mr"]) > abs(res["row_results"][0]["Mr"])


# ─── Shear / torsion geometry (implemented contract, UNVERIFIED citations) ──

def test_shear_depths_and_widths():
    raw, res = run()
    I = derive_circular(dict(raw))
    fl = res["flexure"]
    Dr = I["circ_rings"][0]["Dr"]
    de = 18 + Dr / math.pi
    assert fl["de"] == pytest.approx(de)
    assert fl["dv"] == pytest.approx(max(0.9 * de, 0.72 * 36))
    assert fl["bv"] == 36
    assert res["shear"]["dv"] == pytest.approx(fl["dv"])
    # 12 bars, one at top & bottom → 5 below + half of 2 on the centreline = 6 bars
    assert fl["As"] == pytest.approx(6 * BARS[9]["a"])


def test_av_hoop_plus_ties():
    raw, res = run(shN=5, ties=2, tie_bar=4)
    assert res["inputs"]["Av"] == pytest.approx(2 * BARS[5]["a"] + 2 * BARS[4]["a"])
    s = res["shear"]
    assert s["Vs1"] == pytest.approx(res["inputs"]["Av"] * 60 * s["dv"] / 6)


def test_no_transverse_reinforcement():
    raw, res = run(s=0, shear_legs=0)
    assert res["inputs"]["Av"] == 0
    assert res["shear"]["Vs1"] == 0


def test_torsion_geometry():
    _, res = run(dem=demand(Mu=2000, Vu=100, Tu=800, Ms=1000))
    t = res["torsion"]
    D = 36
    be = D / 4
    Dh = D - 2 * 2.0 - BARS[5]["d"]
    assert t["Acp"] == pytest.approx(math.pi * D * D / 4)
    assert t["pc"] == pytest.approx(math.pi * D)
    assert t["Ao"] == pytest.approx(math.pi * (D - be) ** 2 / 4)
    assert t["ph"] == pytest.approx(math.pi * Dh)
    assert t["Tcr"] == pytest.approx(0.126 * math.sqrt(4) * t["Acp"] ** 2 / t["pc"])
    assert t["Tr"] > 0


def test_spiral_not_counted_for_torsion():
    _, res = run(trans="spiral", dem=demand(Mu=2000, Vu=100, Tu=800, Ms=1000))
    t = res["torsion"]
    assert t["consider"]
    assert t["Tr"] == 0
    assert t["comb_reinf_ok"] is False
    assert t["circ_spiral_excluded"] is True


def test_spiral_ratio():
    raw, res = run(trans="spiral", shN=4, s=3)
    tr = res["flexure"]["circ"]["trans"]
    Dc = 36 - 4.0
    rho = 4 * BARS[4]["a"] / (Dc * 3)
    Ac = math.pi * Dc ** 2 / 4
    assert tr["rho_s"] == pytest.approx(rho)
    assert tr["rho_s_min"] == pytest.approx(0.45 * (math.pi * 18 ** 2 / Ac - 1) * 4 / 60)


def test_rho_s_for_hooked_hoops_only_and_fyh_cap():
    # §5.6.4.6 applies to spirals and hoops closed by weld/coupler/hooks; fyh ≤ 75 ksi
    _, lap = run(trans="hoop", shN=4, s=3)
    assert "rho_s" not in lap["flexure"]["circ"]["trans"]
    _, hk = run(trans="hoop", circ_hoop_closure="hooked", shN=4, s=3, fy_trans=100)
    tr = hk["flexure"]["circ"]["trans"]
    Ac = math.pi * 32 ** 2 / 4
    assert tr["fyh"] == 75.0
    assert tr["rho_s_min"] == pytest.approx(0.45 * (math.pi * 18 ** 2 / Ac - 1) * 4 / 75)


def _detail(res, item):
    return [d for d in res["flexure"]["circ"]["trans"]["detailing"] if d["item"].startswith(item)]


def test_detailing_min_bars_and_size():
    _, res = run(n1=5, bar1=4)
    assert _detail(res, "Longitudinal bars in outer ring")[0]["ok"] is False     # §5.6.4.2: ≥ 6
    assert _detail(res, "Smallest longitudinal bar")[0]["ok"] is False           # §5.6.4.2: ≥ #5
    _, ok = run()
    assert all(d["ok"] for d in _detail(ok, "Longitudinal") + _detail(ok, "Smallest"))


def test_detailing_spiral_pitch_and_clear_spacing():
    # §5.10.4.2: c/c ≤ min(6·db, 6 in); clear ≥ max(1 in, 1.33·ag); spiral ≥ 0.375 in
    _, res = run(trans="spiral", shN=3, s=7)
    assert _detail(res, "Centre-to-centre")[0]["ok"] is False
    assert _detail(res, "Spiral bar diameter")[0]["ok"] is True
    _, tight = run(trans="spiral", shN=4, s=1.2)
    assert _detail(tight, "Clear spacing")[0]["ok"] is False


def test_detailing_lap_hoop_treated_as_tie():
    # §5.10.4.3: #11+ longitudinal → ties ≥ #4; spacing ≤ min(D, 12 in)
    _, res = run(bar1=11, n1=10, shN=3, s=14)
    assert _detail(res, "Tie bar size")[0]["ok"] is False
    assert _detail(res, "Tie spacing")[0]["ok"] is False


def test_detailing_bundle_limit_large_bars():
    # §5.10.3.1.5: bars larger than #11 → at most 2 per bundle in flexural members
    _, res = run(D=60, bar1=14, n1=8, bundle1=3)
    assert _detail(res, "Ring 1 bundle")[0]["ok"] is False
    _, ok = run(D=60, bar1=11, n1=8, bundle1=3)
    assert _detail(ok, "Ring 1 bundle")[0]["ok"] is True


# ─── Service ───────────────────────────────────────────────────────

def test_cracked_section_matches_strip_integration():
    raw, res = run()
    I = derive_circular(dict(raw))
    rows = _rows_cf(I["circ_bars"], "top", I["D"])
    cr = cracked_section_circ(I, rows, 0)
    R, n = 18.0, I["n_mod"]

    def Qs(c):
        A, y, _ = strips(R, c, n=4000)
        q = A * (c - y)
        for r in rows:
            k = (n - 1) if r["d_cf"] < c else n
            q += k * r["As"] * (c - r["d_cf"])
        return q

    lo, hi = 0.01, 36
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if Qs(mid) > 0 else (mid, hi)
    assert cr["c_cr"] == pytest.approx(lo, rel=1e-3)
    A, y, Ic = strips(R, cr["c_cr"])
    z_na, zbar = R - cr["c_cr"], R - y
    I_seg = Ic - 2 * z_na * A * zbar + A * z_na ** 2
    assert cr["I_seg"] == pytest.approx(I_seg, rel=1e-3)
    fl = res["flexure"]
    assert fl["fss"] == pytest.approx(2000 * (fl["serv_ds"] - fl["c_cr"]) / fl["Icr"] * n, rel=1e-9)


def test_crack_control_dc_and_mcr():
    raw, res = run()
    fl = res["flexure"]
    I = derive_circular(dict(raw))
    assert fl["dc"] == pytest.approx(36 - max(b["d_top"] for b in I["circ_bars"]))
    assert fl["Sc"] == pytest.approx(math.pi * 36 ** 3 / 32)
    assert fl["Mcr"] == pytest.approx(0.67 * 1.6 * 0.24 * 2 * fl["Sc"])


# ─── PT ────────────────────────────────────────────────────────────

def test_pt_circular_runs_and_adds_capacity():
    _, base = run()
    _, pt = run(nStrands=4, strand_area=0.153, dp=26, fpe=160, ductDia=2.5, sectionClass="CIP_PT")
    assert pt["flexure"]["Aps_tens"] > 0
    assert pt["flexure"]["gamma3"] == 1.0   # Table 5.6.3.3: γ3 = 1.0 for prestressing steel
    assert pt["flexure"]["Mn"] > base["flexure"]["Mn"]
    assert pt["shear"]["lambda_duct"] < 1
    assert pt["row_results"][0]["ptStressStatus"] in ("OK", "NG", "NOT_ALLOWED")


# ─── Report / UI contract ──────────────────────────────────────────

@pytest.mark.parametrize("trans", ["hoop", "spiral"])
def test_report_keys_present(trans):
    _, res = run(trans=trans, dem=demand(Pu=-200, Mu=3000, Vu=150, Tu=300, Ms=1500, Ps=-50))
    for k in REQUIRED_FLEX_KEYS:
        assert k in res["flexure"], k
    for k in REQUIRED_SHEAR_KEYS:
        assert k in res["shear"], k
    for k in REQUIRED_TORSION_KEYS:
        assert k in res["torsion"], k
    assert res["inputs"]["isCirc"] is True
    assert res["flexure"]["pm_key_points"]
    for k in ("Al_tors", "Al_min", "Al_gov"):
        assert k not in res["torsion"]


def test_unverified_list_is_exposed():
    _, res = run()
    assert res["flexure"]["circ"]["unverified"] == CIRC_UNVERIFIED
