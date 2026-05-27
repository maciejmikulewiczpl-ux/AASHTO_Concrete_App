"""
Pin the v2 per-row PT service-stress checks (AASHTO LRFD 10th Ed., 2024 §5.9.2.3).

v2 architecture:
  - Each demand row carries a `load_case` ∈ {"temporary", "service_I_sust",
    "service_I_full", "service_III"}.
  - Engine reads pt_limits + pt_flags from inputs (with legacy v1 key migration).
  - compute_row_capacities returns `pt_stress` (full subdict) + `ptStressStatus`
    per row. No more section-level `result["pt_service"]` block.

Tests:
  - Defaults match AASHTO Tables 5.9.2.3.1b-1, 5.9.2.3.2a-1, 5.9.2.3.2b-1
  - 4 load cases pick the correct sigma_c_lim / sigma_t_lim
  - Case selectors swap limits correctly (temp_comp_case, temp_tens_case,
    srv3_tens_case, φw)
  - Tensile caps (0.2, 0.3, 0.6 ksi) actually kick in for high f'c
  - Unbonded Service III returns NOT_ALLOWED when net tension exists
  - Legacy v1 pt_limits keys are silently migrated
  - Numeric: rectangular + I-section (asymmetric) match hand-derived gross-section
    f_top/f_bot to ~1e-3 ksi
  - Sign convention holds (e_cgs flip → fiber stress flip)
  - Breakdown carries AASHTO-table references (no [UNVERIFIED] tags)
"""
import math
import pytest

from tests.fixtures import make_inputs, demand, PT_STRAND_AREA
from calc_engine import (
    calculate_all,
    _pt_row_service_check,
    _pt_fiber_stress,
    _resolve_pt_lims_and_flags,
    _PT_LIMITS_DEFAULTS,
    _PT_FLAGS_DEFAULTS,
    _PT_TENS_CAPS,
)


def _pt_inputs(**extra):
    """Rectangular PT section with one strand group, 1-pt flat profile."""
    Aps = 2 * PT_STRAND_AREA
    dp = 28.0
    fpe = 170.0
    base = dict(
        h=36, b=18, secType="RECTANGULAR",
        barN_bot=8, nBars_bot=4, barN_top=0, nBars_top=0,
        nStrands=2, strand_area=PT_STRAND_AREA, dp=dp, fpe=fpe, ductDia=2.0,
        sectionClass="CIP_PT",
        fci=4.0, fc=5.0,
    )
    base.update(extra)
    raw = make_inputs(**base)
    raw["pt_loss_summary"] = {"fpi": 185.0, "fpe_avg": fpe}
    return raw


def _row(load_case, Mu=4000, Ms=4500, dp=28, fpe=170, **extra):
    d = demand(Mu=Mu, Ms=Ms, dp=dp, fpe=fpe, **extra)
    d["load_case"] = load_case
    return d


# ─── Defaults & migration ──────────────────────────────────────────────

def test_v2_defaults_match_aashto_10th_ed():
    """Defaults are the AASHTO 10th Ed. (2024) values from the verified PDF."""
    assert _PT_LIMITS_DEFAULTS["kc_xfr_gen"] == 0.65
    assert _PT_LIMITS_DEFAULTS["kc_xfr_peak"] == 0.70
    assert _PT_LIMITS_DEFAULTS["kt_xfr_bonded"] == 0.24
    assert _PT_LIMITS_DEFAULTS["kt_xfr_plain"] == 0.0948
    assert _PT_LIMITS_DEFAULTS["kc_srv1_sust"] == 0.45
    assert _PT_LIMITS_DEFAULTS["kc_srv1_full"] == 0.60
    assert _PT_LIMITS_DEFAULTS["kt_srv3_mod"] == 0.19
    assert _PT_LIMITS_DEFAULTS["kt_srv3_sev"] == 0.0948


def test_v2_default_flags():
    assert _PT_FLAGS_DEFAULTS["bonded"] is True
    assert _PT_FLAGS_DEFAULTS["temp_comp_case"] == "general"
    assert _PT_FLAGS_DEFAULTS["temp_tens_case"] == "bonded"
    assert _PT_FLAGS_DEFAULTS["srv3_tens_case"] == "moderate"
    assert _PT_FLAGS_DEFAULTS["phi_w"] == 1.0


def test_legacy_v2_flag_names_migrated():
    """Pre-refactor v2 flag names (allow_peak_xfr / temp_bonded_reinf / corrosion)
    are silently migrated to the new case-selector schema."""
    from calc_engine import _resolve_pt_lims_and_flags
    I = {"pt_flags": {"allow_peak_xfr": True, "temp_bonded_reinf": False,
                       "bonded": True, "corrosion": "severe"}}
    _, flg = _resolve_pt_lims_and_flags(I)
    assert flg["temp_comp_case"] == "peak"
    assert flg["temp_tens_case"] == "plain"
    assert flg["srv3_tens_case"] == "severe"
    # Legacy "bonded=False" should override corrosion → none
    I2 = {"pt_flags": {"bonded": False, "corrosion": "moderate"}}
    _, flg2 = _resolve_pt_lims_and_flags(I2)
    assert flg2["srv3_tens_case"] == "none"


def test_tensile_caps_constants():
    assert _PT_TENS_CAPS["kt_xfr_plain"] == 0.2
    assert _PT_TENS_CAPS["kt_srv3_mod"] == 0.6
    assert _PT_TENS_CAPS["kt_srv3_sev"] == 0.3


def test_legacy_v1_keys_silently_migrated():
    """v1 used kc_xfr / kt_xfr / kc_srv1 / kc_sust / kt_srv3 — must map to v2."""
    I = {"pt_limits": {"kc_xfr": 0.55, "kc_srv1": 0.50, "kc_sust": 0.40,
                       "kt_xfr": 0.1, "kt_srv3": 0.20}}
    lim, _ = _resolve_pt_lims_and_flags(I)
    assert lim["kc_xfr_gen"] == 0.55
    assert lim["kc_srv1_full"] == 0.50
    assert lim["kc_srv1_sust"] == 0.40
    assert lim["kt_xfr_plain"] == 0.1
    assert lim["kt_srv3_mod"] == 0.20


def test_v2_keys_win_over_legacy_when_both_present():
    I = {"pt_limits": {"kc_xfr": 0.55, "kc_xfr_gen": 0.62}}
    lim, _ = _resolve_pt_lims_and_flags(I)
    assert lim["kc_xfr_gen"] == 0.62


# ─── 4 load cases produce correct limits ───────────────────────────────

def test_temporary_compression_limit_uses_kc_xfr_gen():
    raw = _pt_inputs()
    res = calculate_all(raw, [_row("temporary", Ms=500)], 0)
    pt = res["row_results"][0]["pt_stress"]
    assert pt["sigma_c_lim"] == pytest.approx(-0.65 * 4.0, abs=1e-6)


def test_temporary_compression_uses_peak_when_case_set():
    raw = _pt_inputs()
    raw["pt_flags"] = {"temp_comp_case": "peak"}
    res = calculate_all(raw, [_row("temporary", Ms=500)], 0)
    pt = res["row_results"][0]["pt_stress"]
    assert pt["sigma_c_lim"] == pytest.approx(-0.70 * 4.0, abs=1e-6)


def test_temporary_tension_with_bonded_reinf_uses_024():
    raw = _pt_inputs()
    # flag defaults True → use 0.24·λ·√f'ci
    res = calculate_all(raw, [_row("temporary", Ms=500)], 0)
    pt = res["row_results"][0]["pt_stress"]
    assert pt["sigma_t_lim"] == pytest.approx(0.24 * 1.0 * math.sqrt(4.0), abs=1e-6)


def test_temporary_tension_plain_case_uses_0_0948_with_cap():
    raw = _pt_inputs(fci=20.0)   # high f'ci to trigger the 0.2 ksi cap
    raw["pt_flags"] = {"temp_tens_case": "plain"}
    res = calculate_all(raw, [_row("temporary", Ms=500)], 0)
    pt = res["row_results"][0]["pt_stress"]
    raw_val = 0.0948 * 1.0 * math.sqrt(20.0)
    assert raw_val > 0.2, "test premise: raw should exceed cap"
    assert pt["sigma_t_lim"] == pytest.approx(0.2, abs=1e-9), "cap must be enforced"


def test_service_I_sust_uses_045fc_no_tension_check():
    raw = _pt_inputs()
    res = calculate_all(raw, [_row("service_I_sust", Ms=2000)], 0)
    pt = res["row_results"][0]["pt_stress"]
    assert pt["sigma_c_lim"] == pytest.approx(-0.45 * 5.0, abs=1e-6)
    assert pt["sigma_t_lim"] is None
    assert pt["ratio_t_top"] is None and pt["ratio_t_bot"] is None


def test_service_I_full_uses_060_phi_w_fc():
    raw = _pt_inputs()
    raw["pt_flags"] = {"phi_w": 0.85}   # slender section
    res = calculate_all(raw, [_row("service_I_full", Ms=2000)], 0)
    pt = res["row_results"][0]["pt_stress"]
    assert pt["sigma_c_lim"] == pytest.approx(-0.60 * 0.85 * 5.0, abs=1e-6)
    assert pt["sigma_t_lim"] is None


def test_service_III_moderate_uses_019_with_cap():
    raw = _pt_inputs(fc=20.0)   # high f'c to trigger 0.6 ksi cap
    res = calculate_all(raw, [_row("service_III", Ms=2000)], 0)
    pt = res["row_results"][0]["pt_stress"]
    raw_val = 0.19 * 1.0 * math.sqrt(20.0)
    assert raw_val > 0.6, "test premise"
    assert pt["sigma_t_lim"] == pytest.approx(0.6, abs=1e-9)
    assert pt["sigma_c_lim"] is None


def test_service_III_severe_uses_0_0948_with_cap():
    raw = _pt_inputs(fc=20.0)
    raw["pt_flags"] = {"srv3_tens_case": "severe"}
    res = calculate_all(raw, [_row("service_III", Ms=2000)], 0)
    pt = res["row_results"][0]["pt_stress"]
    raw_val = 0.0948 * 1.0 * math.sqrt(20.0)
    assert raw_val > 0.3, "test premise"
    assert pt["sigma_t_lim"] == pytest.approx(0.3, abs=1e-9)


def test_service_III_none_case_returns_not_allowed_when_tension_present():
    """Service III dropdown set to 'No Tension' (unbonded) → engine fails any tensile fiber."""
    raw = _pt_inputs()
    raw["pt_flags"] = {"srv3_tens_case": "none"}
    # Large Ms → tensile bottom fiber
    res = calculate_all(raw, [_row("service_III", Ms=6000)], 0)
    pt = res["row_results"][0]["pt_stress"]
    assert pt["sigma_t_lim"] == 0.0
    assert pt["status"] == "NOT_ALLOWED"


def test_service_III_none_case_ok_when_no_tension():
    """For 'No Tension' Service III selection, OK only when both fibers in compression.
    Use a concentric tendon (dp = centroid) so prestress alone is pure axial compression."""
    raw = _pt_inputs(dp=18.0)   # tendon at centroid → e = 0
    raw["pt_flags"] = {"srv3_tens_case": "none"}
    res = calculate_all(raw, [_row("service_III", Ms=0, dp=18, fpe=170)], 0)
    pt = res["row_results"][0]["pt_stress"]
    assert pt["sigma_t_lim"] == 0.0
    assert pt["f_top"] <= 0 and pt["f_bot"] <= 0, "concentric P, M=0 → pure compression"
    assert pt["status"] == "OK"


# ─── Status / row-level ────────────────────────────────────────────────

def test_per_row_pt_stress_status_present_for_pt():
    raw = _pt_inputs()
    rows = [_row("service_I_full", Ms=1500), _row("service_III", Ms=4500)]
    res = calculate_all(raw, rows, 0)
    for cap in res["row_results"]:
        assert "ptStressStatus" in cap
        assert cap["ptStressStatus"] in ("OK", "NG", "NOT_ALLOWED")
        assert cap["pt_stress"] is not None


def test_per_row_pt_stress_na_for_rc():
    raw = make_inputs(h=36, b=18, barN_bot=8, nBars_bot=4)
    res = calculate_all(raw, [demand(Mu=2000, Ms=1500)], 0)
    cap = res["row_results"][0]
    assert cap["ptStressStatus"] == "NA"
    assert cap["pt_stress"] is None


def test_no_section_level_pt_service_block():
    """v1's result['pt_service'] aggregate is gone in v2."""
    raw = _pt_inputs()
    res = calculate_all(raw, [_row("service_I_full")], 0)
    assert "pt_service" not in res


# ─── Sign convention + numeric closed form ─────────────────────────────

def test_fiber_stress_helper_sign_convention():
    # e_cgs > 0 (CGS below centroid), M = 0 → top tension, bot compression
    f_top, f_bot = _pt_fiber_stress(P=400, M_kipin=0, Ag=648, Ig=69984,
                                     e_cgs=12, yt=18, yb=18)
    assert f_top > 0
    assert f_bot < 0
    # Flip e → flip stresses
    f_top2, f_bot2 = _pt_fiber_stress(P=400, M_kipin=0, Ag=648, Ig=69984,
                                       e_cgs=-12, yt=18, yb=18)
    assert f_top2 < 0
    assert f_bot2 > 0


def test_rectangular_closed_form_match():
    raw = _pt_inputs()
    res = calculate_all(raw, [_row("service_I_full", Ms=4500)], 0)
    pt = res["row_results"][0]["pt_stress"]
    Ag = 18 * 36
    Ig = 18 * 36 ** 3 / 12.0
    yb_c = 18.0
    yt = yb_c
    yb = 36 - yb_c
    Aps = 2 * PT_STRAND_AREA
    P = 170.0 * Aps
    e = 28.0 - yb_c
    M = 4500.0
    f_top_expected = -P / Ag + P * e * yt / Ig - M * yt / Ig
    f_bot_expected = -P / Ag - P * e * yb / Ig + M * yb / Ig
    assert pt["f_top"] == pytest.approx(f_top_expected, abs=1e-3)
    assert pt["f_bot"] == pytest.approx(f_bot_expected, abs=1e-3)


def test_isection_asymmetric_closed_form_match():
    """Asymmetric I-section uses gross-section formula with shifted centroid."""
    Aps = 2 * PT_STRAND_AREA
    raw = make_inputs(
        h=36, b=36, secType="T-SECTION",
        bw_input=12, hf_top=8, hf_bot=14,
        barN_bot=8, nBars_bot=4,
        nStrands=2, strand_area=PT_STRAND_AREA, dp=28, fpe=170,
        sectionClass="CIP_PT", fci=4.0, fc=5.0,
    )
    raw["pt_loss_summary"] = {"fpi": 185.0, "fpe_avg": 170.0}
    res = calculate_all(raw, [_row("service_I_full", Ms=4500)], 0)
    pt = res["row_results"][0]["pt_stress"]

    b_fl, bw, h = 36.0, 12.0, 36.0
    hf_t, hf_b = 8.0, 14.0
    h_web = h - hf_t - hf_b
    A_top = b_fl * hf_t
    A_web = bw * h_web
    A_bot = b_fl * hf_b
    Ag = A_top + A_web + A_bot
    y_top = hf_t / 2.0
    y_web = hf_t + h_web / 2.0
    y_bot = hf_t + h_web + hf_b / 2.0
    yb_c = (A_top * y_top + A_web * y_web + A_bot * y_bot) / Ag
    Ig = (b_fl * hf_t ** 3 / 12.0 + A_top * (yb_c - y_top) ** 2
          + bw * h_web ** 3 / 12.0 + A_web * (yb_c - y_web) ** 2
          + b_fl * hf_b ** 3 / 12.0 + A_bot * (yb_c - y_bot) ** 2)
    yt = yb_c
    yb = h - yb_c
    P = 170.0 * Aps
    e = 28.0 - yb_c
    M = 4500.0
    f_top_expected = -P / Ag + P * e * yt / Ig - M * yt / Ig
    f_bot_expected = -P / Ag - P * e * yb / Ig + M * yb / Ig
    assert pt["Ag"] == pytest.approx(Ag, abs=1e-6)
    assert pt["Ig"] == pytest.approx(Ig, abs=1e-3)
    assert pt["f_top"] == pytest.approx(f_top_expected, abs=1e-3)
    assert pt["f_bot"] == pytest.approx(f_bot_expected, abs=1e-3)


def test_temporary_uses_fpi_not_fpe():
    """Transfer stage P must come from loss_summary['fpi'] (pre-time-dep losses)."""
    raw = _pt_inputs()
    res = calculate_all(raw, [_row("temporary", Ms=1200)], 0)
    pt = res["row_results"][0]["pt_stress"]
    Aps = 2 * PT_STRAND_AREA
    assert pt["P_used"] == pytest.approx(185.0 * Aps, abs=1e-3)


def test_service_I_uses_fpe():
    """Service I (sust + full) use fpe, not fpi."""
    raw = _pt_inputs()
    res = calculate_all(raw, [_row("service_I_full", Ms=2000)], 0)
    pt = res["row_results"][0]["pt_stress"]
    Aps = 2 * PT_STRAND_AREA
    assert pt["P_used"] == pytest.approx(170.0 * Aps, abs=1e-3)


# ─── Breakdown / citations ─────────────────────────────────────────────

def test_breakdown_carries_aashto_table_reference():
    raw = _pt_inputs()
    res = calculate_all(raw, [_row("service_III", Ms=2000)], 0)
    pt = res["row_results"][0]["pt_stress"]
    bd = pt["breakdown"]
    full = " ".join(s.get("desc", "") + s.get("equation", "") for s in bd["steps"])
    # No fabricated equation numbers
    assert "5.9.2.3.1a-1" not in full
    assert "5.9.2.3.2b-1" in full or "Table 5.9.2.3.2b-1" in full or "moderate corrosion" in full
    # No leftover [UNVERIFIED] tags now that coefficients are AASHTO-verified
    assert "UNVERIFIED" not in full
    assert "UNVERIFIED" not in bd["title"]


def test_load_case_label_in_breakdown_title():
    raw = _pt_inputs()
    for lc, marker in [
        ("temporary", "Temporary"),
        ("service_I_sust", "Permanent"),
        ("service_I_full", "Full"),
        ("service_III", "Service III"),
    ]:
        res = calculate_all(raw, [_row(lc, Ms=2000)], 0)
        bd = res["row_results"][0]["pt_stress"]["breakdown"]
        assert marker in bd["title"], f"{lc}: title missing marker '{marker}': {bd['title']}"


def test_external_axial_demand_Ps_shifts_fibers_by_Ps_over_Ag():
    """Per-row Ps must show up as a +Ps/Ag axial shift on both top and bottom fibers."""
    raw = _pt_inputs()
    # Same row twice — once Ps=0, once Ps=-100 (compression).
    rows = [
        _row("service_I_full", Ms=5000, Ps=0),
        _row("service_I_full", Ms=5000, Ps=-100),
    ]
    res = calculate_all(raw, rows, 0)
    pt0 = res["row_results"][0]["pt_stress"]
    pt1 = res["row_results"][1]["pt_stress"]
    Ag = 18 * 36
    expected_delta = -100 / Ag
    assert pt1["f_top"] - pt0["f_top"] == pytest.approx(expected_delta, abs=1e-6)
    assert pt1["f_bot"] - pt0["f_bot"] == pytest.approx(expected_delta, abs=1e-6)
    # Ps_used echoed back to the result dict
    assert pt0["Ps_used"] == 0
    assert pt1["Ps_used"] == -100


def test_breakdown_defines_yt_yb_e_cgs_and_prestress():
    """The EqBreakdown must contain plain-language definitions of yt, yb, e_cgs
    and show how P was built from fp · Aps."""
    raw = _pt_inputs()
    res = calculate_all(raw, [_row("service_I_full", Ms=5000, Ps=-100)], 0)
    pt = res["row_results"][0]["pt_stress"]
    bd = pt["breakdown"]
    full = "\n".join(s.get("equation", "") + " | " + s.get("desc", "") for s in bd["steps"])
    # Symbol definitions present
    assert "y_t" in full and "TOP fiber" in full
    assert "y_b" in full and "BOT fiber" in full
    assert "e_cgs" in full and "BELOW" in full
    # Prestress force build-up shown
    assert "P — prestress force" in full or "P — prestress force on the section" in full
    assert "f_pe" in full or "f_pi" in full
    # External axial demand documented
    assert "P_s" in full and "tension" in full
    # Combined fiber-stress equation includes the Ps/Ag term
    assert "P_s/A_g" in full or "P_s / A_g" in full


def test_temporary_uses_fpi_in_prestress_buildup():
    """At Temporary stage, the breakdown's fp = fpi (not fpe)."""
    raw = _pt_inputs()
    res = calculate_all(raw, [_row("temporary", Ms=1200)], 0)
    pt = res["row_results"][0]["pt_stress"]
    assert pt["fp_used"] == pt["fpi_used"]
    assert pt["fp_used"] != pt["fpe_used"]


def test_unknown_load_case_falls_back_gracefully():
    """Unknown load_case → silently treated as Service I full (safe default)."""
    raw = _pt_inputs()
    row = _row("not_a_real_case", Ms=1500)
    res = calculate_all(raw, [row], 0)
    pt = res["row_results"][0]["pt_stress"]
    # Should produce a valid result without raising
    assert pt["sigma_c_lim"] is not None
    assert pt["label"]
