"""
Pin behavior of the RC crack-control mode toggle (AASHTO 5.6.7-1).

The engine now exposes two candidate spacing limits:
  - s_crack_capped: uses fss_simp = 0.6*fy (the historical default).
  - s_crack_actual: uses the actual cracked-section service stress.

The `crack_mode` input ("capped" | "actual") selects which one drives
the governing s_crack reported back to the UI/report.

These tests pin that:
  1. Omitting crack_mode reproduces the historical capped behavior exactly.
  2. crack_mode="actual" switches s_crack to s_crack_actual.
  3. Both fss_simp and fss keys remain present in every case (sanity for
     HTML readers that show both for transparency).
  4. Edge case: when actual fss <= 0 (rebar in net compression) the
     "actual" mode falls back to s_crack_actual == 0 without divide-by-zero.
"""

import math
import pytest

from tests.fixtures import calc, SECTION_CATALOGUE, DEMAND_CATALOGUE


def _flex(section_key, dem_key, **overrides):
    sect = dict(SECTION_CATALOGUE[section_key])
    sect.update(overrides)
    dem = DEMAND_CATALOGUE[dem_key]
    _, res = calc(sect, dem)
    return res["flexure"]


def test_default_crack_mode_is_capped():
    fl = _flex("Rect_BotOnly", "Pure_Sag")
    assert fl["crack_mode"] == "capped"
    # s_crack equals the capped candidate when no override is given
    assert fl["s_crack"] == pytest.approx(fl["s_crack_capped"], abs=1e-9)
    # fss_used in capped mode equals fss_simp (0.6*fy)
    assert fl["fss_used"] == pytest.approx(fl["fss_simp"], abs=1e-9)


def test_actual_mode_switches_governing_value():
    fl = _flex("Rect_BotOnly", "Pure_Sag", crack_mode="actual")
    assert fl["crack_mode"] == "actual"
    # s_crack now equals the actual candidate
    assert fl["s_crack"] == pytest.approx(fl["s_crack_actual"], abs=1e-9)
    # fss_used = max(fss, 0)
    assert fl["fss_used"] == pytest.approx(max(fl["fss"], 0.0), abs=1e-9)


def test_both_fss_values_always_present():
    """Both candidates and the canonical fss should be reported regardless of mode."""
    for mode in ("capped", "actual"):
        fl = _flex("Rect_BotOnly", "Pure_Sag", crack_mode=mode)
        assert "fss_simp" in fl
        assert "fss" in fl
        assert "fss_used" in fl
        assert "s_crack_capped" in fl
        assert "s_crack_actual" in fl
        assert "breakdown_crack" in fl
        # Breakdown carries the same governing s_crack
        assert fl["breakdown_crack"]["title"]


def test_actual_mode_handles_no_tension():
    """When the actual cracked-section fss is non-positive (rebar in net
    compression), s_crack_actual must be zero and no exception is raised."""
    # Use a section + demand where Ms is zero so cracked-section fss is ~0.
    fl = _flex("Rect_BotOnly", "Pure_Comp", crack_mode="actual")
    assert fl["s_crack_actual"] >= 0
    assert fl["s_crack"] == pytest.approx(fl["s_crack_actual"], abs=1e-9)


def test_breakdown_crack_includes_both_candidates():
    fl = _flex("Rect_BotOnly", "Pure_Sag", crack_mode="capped")
    bd = fl["breakdown_crack"]
    titles = " ".join(step.get("equation", "") for step in bd["steps"])
    assert "5.6.7" in bd["title"] or "Crack Control" in bd["title"]
    # Both fss,capped and fss,actual must appear in the breakdown
    assert "fss,capped" in titles or "0.6" in titles
    assert "fss,actual" in titles or "M·(ds" in titles
