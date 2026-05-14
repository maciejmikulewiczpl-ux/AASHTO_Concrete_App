"""
Cross-cutting invariants and monotonicity properties.

These tests don't reproduce a specific AASHTO equation -- they check
properties that MUST hold across the design space (regardless of which
formula is in use). If one of these breaks, it suggests a sign error,
inverted lookup, or accidental coupling between unrelated parameters.
"""
import math
import pytest

from tests.fixtures import make_inputs, demand
from calc_engine import calculate_all


# ─── Symmetry invariants ──────────────────────────────────────────────

def test_symmetric_rect_section_sag_hog_symmetry():
    """For a doubly-symmetric rectangular section, every reported
    capacity must be the same under +Mu and -Mu."""
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                      barN_top=8, nBars_top=4)
    res_s = calculate_all(raw, [demand(Mu=3000, Vu=100, Tu=50)], 0)
    res_h = calculate_all(raw, [demand(Mu=-3000, Vu=100, Tu=50)], 0)

    assert math.isclose(res_s["flexure"]["Mr"], res_h["flexure"]["Mr"],
                        rel_tol=0.005)
    assert math.isclose(res_s["flexure"]["Mn"], res_h["flexure"]["Mn"],
                        rel_tol=0.005)
    for m in (1, 2):
        assert math.isclose(res_s["shear"][f"Vr{m}"],
                            res_h["shear"][f"Vr{m}"], rel_tol=0.05)


def test_symmetric_isection_sag_hog_symmetry():
    """I-section with equal top/bottom flanges + equal top/bot steel
    must give identical sag/hog capacity."""
    raw = make_inputs(h=36, b=36, secType="T-SECTION", bw_input=12,
                      hf_top=8, hf_bot=8,
                      barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4)
    res_s = calculate_all(raw, [demand(Mu=3000)], 0)
    res_h = calculate_all(raw, [demand(Mu=-3000)], 0)
    assert math.isclose(res_s["flexure"]["Mr"], res_h["flexure"]["Mr"],
                        rel_tol=0.005)


def test_asymmetric_reinforcement_sag_hog_differ():
    """Asymmetric reinforcement (more bot steel than top) must give
    sag Mr > hog Mr -- the deeper-reinforced face has more lever-arm
    when in tension."""
    raw = make_inputs(h=36, b=36, secType="T-SECTION", bw_input=12,
                      hf_top=8, hf_bot=12,
                      barN_bot=9, nBars_bot=6, barN_top=5, nBars_top=2)
    res_s = calculate_all(raw, [demand(Mu=3000)], 0)
    res_h = calculate_all(raw, [demand(Mu=-3000)], 0)
    assert not math.isclose(res_s["flexure"]["Mr"], res_h["flexure"]["Mr"],
                            rel_tol=0.02), \
        f"Asymmetric reinforcement should differ: " \
        f"sag={res_s['flexure']['Mr']:.1f} vs hog={res_h['flexure']['Mr']:.1f}"
    assert res_s["flexure"]["Mr"] > res_h["flexure"]["Mr"], \
        "Sag with strong bot steel should exceed hog with weak top steel"


# ─── Monotonicity invariants ──────────────────────────────────────────

def test_more_bottom_steel_increases_Mr_sag():
    """Adding tension steel must increase (or hold) sagging capacity."""
    raw_3 = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=3)
    raw_6 = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=6)
    res_3 = calculate_all(raw_3, [demand(Mu=2000)], 0)
    res_6 = calculate_all(raw_6, [demand(Mu=2000)], 0)
    assert res_6["flexure"]["Mn"] > res_3["flexure"]["Mn"], \
        f"6 bars Mn={res_6['flexure']['Mn']:.1f} not > 3 bars " \
        f"Mn={res_3['flexure']['Mn']:.1f}"


def test_deeper_section_increases_Mr():
    """Increasing depth h must increase Mr (more lever arm)."""
    raw_24 = make_inputs(h=24, b=36, barN_bot=8, nBars_bot=4)
    raw_36 = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4)
    res_24 = calculate_all(raw_24, [demand(Mu=1000)], 0)
    res_36 = calculate_all(raw_36, [demand(Mu=1000)], 0)
    assert res_36["flexure"]["Mn"] > res_24["flexure"]["Mn"]


def test_more_stirrups_increases_Vs():
    """More transverse legs OR tighter spacing must increase Vs."""
    raw_loose = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                            shN=4, shear_legs=2, s_shear=18)
    raw_tight = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                            shN=4, shear_legs=2, s_shear=6)
    res_loose = calculate_all(raw_loose, [demand(Mu=2000, Vu=200)], 0)
    res_tight = calculate_all(raw_tight, [demand(Mu=2000, Vu=200)], 0)
    assert res_tight["shear"]["Vs1"] > res_loose["shear"]["Vs1"]


def test_higher_fc_does_not_decrease_Vc():
    """Vc scales with sqrt(fc); higher fc must not reduce it."""
    raw_4 = make_inputs(h=36, b=36, fc=4, barN_bot=8, nBars_bot=4)
    raw_8 = make_inputs(h=36, b=36, fc=8, barN_bot=8, nBars_bot=4)
    res_4 = calculate_all(raw_4, [demand(Mu=2000, Vu=100)], 0)
    res_8 = calculate_all(raw_8, [demand(Mu=2000, Vu=100)], 0)
    assert res_8["shear"]["Vc1"] > res_4["shear"]["Vc1"]


# ─── Edge / fail-safe behaviors ──────────────────────────────────────

def test_zero_shear_demand_does_not_crash():
    """Vu=0 must produce a result without exception."""
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4)
    res = calculate_all(raw, [demand(Mu=2000, Vu=0)], 0)
    assert "shear" in res
    # Shear status should be 'NR' (not required) or 'OK' when Vu=0
    assert res["row_results"][0]["shearStatus"] in ("OK", "NR")


def test_zero_moment_demand_runs():
    """Mu=0 with axial compression -> column case must not crash."""
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                      barN_top=8, nBars_top=4)
    res = calculate_all(raw, [demand(Pu=-100, Mu=0)], 0)
    assert "flexure" in res


def test_all_zero_demand_runs():
    """All-zero demand row must not crash (degenerate but legal)."""
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4)
    res = calculate_all(raw, [demand()], 0)
    assert res["row_results"][0]["flexStatus"] in ("OK", "MIN", "NG")


# ─── Multi-row determinism ────────────────────────────────────────────

def test_multi_demand_rows_independent():
    """Each row in a multi-row demand list must be processed independently."""
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                      barN_top=8, nBars_top=4)
    dems = [
        demand(Mu=3000, Vu=100),
        demand(Mu=-2000, Vu=80),
        demand(Pu=-100, Mu=4000, Vu=200, Tu=50),
    ]
    res = calculate_all(raw, dems, 0)
    assert len(res["row_results"]) == 3
    # No row should have an identical (Mr, Vr2) signature to another
    sigs = [(round(r["Mr"], 1), round(r["Vr2"], 1)) for r in res["row_results"]]
    assert len(set(sigs)) >= 2, f"Rows look identical: {sigs}"


def test_active_row_index_changes_displayed_result():
    """Changing activeRow should change which row's detail appears in `flexure`."""
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                      barN_top=8, nBars_top=4)
    dems = [demand(Mu=3000), demand(Mu=-3000)]
    res_0 = calculate_all(raw, dems, 0)
    res_1 = calculate_all(raw, dems, 1)
    assert res_0["flexure"]["comp_face"] == "top"
    assert res_1["flexure"]["comp_face"] == "bottom"


# ─── Report-key contract ──────────────────────────────────────────────
#
# The HTML report relies on a documented set of keys being present in
# the result dict. This test pins the contract so that any rename or
# removal will be caught immediately.

REQUIRED_FLEX_KEYS = [
    "c", "a", "beta1", "alpha1", "phi_f",
    "Mn", "Mr", "Mr_atPu",
    "eps_t", "sec_status", "ds", "As", "As_comp", "comp_face",
    "dv", "de", "hf",
    "gamma1", "gamma3", "fr", "Sc", "Mcr", "Mcond", "min_flex_ok",
    "dc", "beta_s", "fss_simp", "s_crack", "s_min_ck", "s_max_ck",
    "c_cr", "Icr", "fss", "eps_rb", "curv", "Ieff", "Ig",
    "n_mod", "M_serv", "addlBM",
    "pm_data", "pm_curve",
    "c_ds_ratio", "c_ds_limit", "c_ds_ok",
    "phi_cc", "phi_tc", "phi_k",
]
REQUIRED_SHEAR_KEYS = [
    "dv", "bv", "Vnmax", "eps_s", "fpo",
    "th1", "bt1", "Vc1", "Vs1", "Vn1", "Vr1",
    "bt2", "th2", "Vc2", "Vs2", "Vn2", "Vr2",
    "th3", "bt3", "Vc3", "Vs3", "Vn3", "Vr3",
    "sh_reqd", "Av_min", "s_max_sh",
    "long_dem", "long_cap", "long_ok",
    # AASHTO Eq. 5.7.3.6.3-1 equation breakdown (rendered in PDF report)
    "breakdown_long_comb",
]
REQUIRED_TORSION_KEYS = [
    "Tcr", "thresh", "consider", "pc", "Acp", "Ao", "ph",
    # AASHTO Eq. 5.7.3.6.3-1 combined longitudinal check (read by HTML report).
    # Eq. 5.7.3.6.3-2 (Al for torsion) is box-section only and intentionally
    # NOT computed by the engine -- the report shows an I-section warning
    # instead.
    "long_dem_comb", "long_cap_val", "long_comb_ok",
    "Av_s_prov",
]


def test_report_keys_present_rc():
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4)
    res = calculate_all(raw, [demand(Mu=2500, Vu=120, Tu=50, Ms=1500)], 0)
    for k in REQUIRED_FLEX_KEYS:
        assert k in res["flexure"], f"flexure key missing: {k}"
    for k in REQUIRED_SHEAR_KEYS:
        assert k in res["shear"], f"shear key missing: {k}"
    for k in REQUIRED_TORSION_KEYS:
        assert k in res["torsion"], f"torsion key missing: {k}"


def test_report_keys_present_pt():
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4,
                      nStrands=2, strand_area=0.196, dp=28, fpe=170,
                      sectionClass="CIP_PT")
    res = calculate_all(raw, [demand(Mu=2500, Vu=120, Tu=50, Ms=1500)], 0)
    for k in REQUIRED_FLEX_KEYS:
        assert k in res["flexure"], f"flexure key missing (PT): {k}"
    for k in REQUIRED_SHEAR_KEYS:
        assert k in res["shear"], f"shear key missing (PT): {k}"


def test_long_comb_breakdown_structure():
    """The Eq. 5.7.3.6.3-1 breakdown must be a non-empty EqBreakdown dict
    with both symbolic equation and numeric substitution per step."""
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                      barN_top=8, nBars_top=4)
    res = calculate_all(raw, [demand(Mu=2500, Vu=120, Tu=200, Ms=1500)], 0)
    bd = res["shear"].get("breakdown_long_comb")
    assert bd is not None, "breakdown_long_comb missing from shear result"
    assert "AASHTO 5.7.3.6.3-1" in bd["title"]
    assert len(bd["steps"]) >= 6, f"Expected >=6 steps, got {len(bd['steps'])}"
    for s in bd["steps"]:
        assert s["equation"], "step missing symbolic equation"
        assert s["desc"], "step missing numeric substitution"
        assert "result" in s
        assert "units" in s


def test_al_keys_removed_from_torsion():
    """ANTI-REGRESSION PIN: AASHTO Eq. 5.7.3.6.3-2 keys must stay absent.

    This test exists because the keys Al_tors / Al_min / Al_gov have been
    incorrectly added to the torsion result TWICE in this project's
    history:

      - Initial commit (0bd99ec) shipped with them.
      - Commit 7939745 removed them (correct: Eq. 5.7.3.6.3-2 is
        box-section only and this app does not model box sections).
      - A later AI-assisted session reintroduced them while "fixing
        missing HTML report keys".
      - 2026-05-13 they were removed again and this test was added.

    AASHTO Eq. 5.7.3.6.3-2 applies to BOX SECTIONS ONLY. There is also no
    "Eq. 5.7.3.6.3-3" in AASHTO LRFD (the minimum-Al formula from earlier
    code was an ACI 318 holdover). If you are looking at the calc engine
    and feel that an Al check is "missing": it is NOT. It is intentionally
    absent. See CODE_PROTECTION.md § "Removed checks — DO NOT re-add" and
    the inline notice atop do_torsion in calc_engine.py.

    DO NOT remove, skip, or weaken this test without owner approval.
    """
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                      barN_top=8, nBars_top=4)
    res = calculate_all(raw, [demand(Mu=2500, Vu=120, Tu=200, Ms=1500)], 0)
    for k in ("Al_tors", "Al_min", "Al_gov"):
        assert k not in res["torsion"], (
            f"Box-section-only key '{k}' should NOT be in torsion result. "
            f"See CODE_PROTECTION.md § 'Removed checks — DO NOT re-add'."
        )


# ─── Audit 2026-05-14 pinning tests (D3/D4, D15, D1) ────────────────

def test_fr_scales_with_lambda():
    """AASHTO 5.4.2.6: fr = 0.24·λ·√fc'.

    PINNING: lightweight concrete (lam < 1.0) must reduce fr proportionally.
    This was an audit fix on 2026-05-14 (decision D3/D4) — earlier code
    omitted the λ multiplier, over-predicting fr for lightweight concrete.
    """
    raw_nw = make_inputs(h=36, b=36, fc=4.0, lam=1.0,
                         barN_bot=8, nBars_bot=4)
    raw_lw = make_inputs(h=36, b=36, fc=4.0, lam=0.75,
                         barN_bot=8, nBars_bot=4)
    res_nw = calculate_all(raw_nw, [demand(Mu=2000, Vu=100)], 0)
    res_lw = calculate_all(raw_lw, [demand(Mu=2000, Vu=100)], 0)
    fr_nw = res_nw["shear"]["fr"]
    fr_lw = res_lw["shear"]["fr"]
    assert math.isclose(fr_lw, 0.75 * fr_nw, rel_tol=1e-9), (
        f"fr should scale linearly with λ: NW={fr_nw:.4f}, "
        f"LW(λ=0.75)={fr_lw:.4f}, expected {0.75*fr_nw:.4f}"
    )
    expected_nw = 0.24 * 1.0 * math.sqrt(4.0)
    assert math.isclose(fr_nw, expected_nw, rel_tol=1e-9), (
        f"fr (NW) should equal 0.24·√fc' = {expected_nw:.4f}, got {fr_nw:.4f}"
    )


def test_av_min_scales_with_lambda():
    """AASHTO 5.7.2.5-1: Av_min = 0.0316·λ·√fc'·bv·s/fy.

    PINNING: λ multiplier applied per audit decision D15 (2026-05-14).
    Lightweight concrete must reduce Av_min proportionally.
    """
    raw_nw = make_inputs(h=36, b=36, fc=4.0, lam=1.0,
                         shN=4, shear_legs=2, s_shear=12,
                         barN_bot=8, nBars_bot=4)
    raw_lw = make_inputs(h=36, b=36, fc=4.0, lam=0.75,
                         shN=4, shear_legs=2, s_shear=12,
                         barN_bot=8, nBars_bot=4)
    res_nw = calculate_all(raw_nw, [demand(Mu=2000, Vu=100)], 0)
    res_lw = calculate_all(raw_lw, [demand(Mu=2000, Vu=100)], 0)
    avmin_nw = res_nw["shear"]["Av_min"]
    avmin_lw = res_lw["shear"]["Av_min"]
    assert avmin_nw > 0, f"Av_min should be > 0 with stirrups, got {avmin_nw}"
    assert math.isclose(avmin_lw, 0.75 * avmin_nw, rel_tol=1e-9), (
        f"Av_min should scale linearly with λ: NW={avmin_nw:.5f}, "
        f"LW(λ=0.75)={avmin_lw:.5f}, expected {0.75*avmin_nw:.5f}"
    )


def test_long_comb_Nu_phi_sign_dependent():
    """AASHTO 5.7.3.6.3-1: φ used for the Nu term must be sign-dependent.

    PINNING: per audit decision D1 (2026-05-14), ld_N = 0.5·Pu/φ where:
      - φ = φ_c (compression)            when Pu < 0
      - φ = φ_f (strain-region flexure)  when Pu > 0 (tension)

    Earlier code always used φ_c regardless of Pu sign.
    """
    raw = make_inputs(h=36, b=36, barN_bot=8, nBars_bot=4,
                      barN_top=8, nBars_top=4)
    # Construct two cases that differ ONLY in Pu sign (same magnitude).
    res_comp = calculate_all(raw, [demand(Pu=-100, Mu=2500, Vu=120, Tu=200)], 0)
    res_tens = calculate_all(raw, [demand(Pu=+100, Mu=2500, Vu=120, Tu=200)], 0)

    ldN_comp = res_comp["shear"]["ld_N"]
    ldN_tens = res_tens["shear"]["ld_N"]
    phi_c = res_comp["shear"]["phi_c"]
    phi_f = res_tens["flexure"]["phi_f"]

    # Compression: ld_N = 0.5·(-100)/φ_c
    expected_comp = 0.5 * (-100) / phi_c
    assert math.isclose(ldN_comp, expected_comp, rel_tol=1e-6), (
        f"ld_N for compression Pu must use φ_c={phi_c:.3f}: "
        f"expected {expected_comp:.3f}, got {ldN_comp:.3f}"
    )
    # Tension: ld_N = 0.5·(+100)/φ_f
    expected_tens = 0.5 * (+100) / phi_f
    assert math.isclose(ldN_tens, expected_tens, rel_tol=1e-6), (
        f"ld_N for tension Pu must use φ_f={phi_f:.3f}: "
        f"expected {expected_tens:.3f}, got {ldN_tens:.3f}"
    )
