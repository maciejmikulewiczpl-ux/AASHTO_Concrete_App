"""Engine-contract test for the rebar-spacing UI feature.

The Count/Spacing mode toggle in the Flexural Reinforcement card lives
entirely in the frontend (index.html). The Python engine continues to
receive `nBars_top` / `nBars_bot` as integers exactly as today; any
spacing-related state (`mode_top`, `mode_bot`, `spacing_top`,
`spacing_bot`) is persisted in the saved file but is irrelevant to the
engine.

This test pins that contract: adding those keys to an engine payload
must produce bit-identical results.
"""
from __future__ import annotations

import pytest

from tests.fixtures import make_inputs, demand
from calc_engine import calculate_all


def _strip_non_comparable(res):
    """Drop any keys that legitimately vary between runs (timestamps,
    debug dumps, etc.). Currently none — the engine output is
    deterministic — but keep this hook so future additions don't
    silently break the test."""
    return res


@pytest.mark.parametrize("section_kwargs", [
    # Plain rectangular, bottom-only
    dict(h=36, b=36, secType="RECTANGULAR",
         barN_bot=8, nBars_bot=4, barN_top=0, nBars_top=0),
    # Rectangular, symmetric top+bot
    dict(h=36, b=36, secType="RECTANGULAR",
         barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4),
    # T-section (modelled as I-section in this app)
    dict(h=36, b=36, secType="T-SECTION", bw_input=12,
         hf_top=8, hf_bot=8,
         barN_bot=7, nBars_bot=5, barN_top=5, nBars_top=3),
])
def test_spacing_keys_are_inert(section_kwargs):
    """Engine output must be identical whether spacing-mode keys are
    present or absent in the input payload."""
    baseline_inputs = make_inputs(**section_kwargs)
    demand_rows = [demand(Pu=-200, Mu=2000, Vu=80, Tu=10)]

    res_without = calculate_all(dict(baseline_inputs), demand_rows, 0)

    augmented_inputs = dict(baseline_inputs)
    augmented_inputs.update({
        "mode_top": "spacing",
        "mode_bot": "count",
        "spacing_top": 4.0,
        "spacing_bot": None,
    })
    res_with = calculate_all(augmented_inputs, demand_rows, 0)

    assert _strip_non_comparable(res_without) == _strip_non_comparable(res_with), (
        "Engine output changed when spacing-mode keys were added to the "
        "payload. The engine must treat those keys as inert; if you "
        "deliberately added engine awareness of mode_top / mode_bot / "
        "spacing_top / spacing_bot, this test needs to be updated and the "
        "frontend-only contract in CLAUDE.md / the rebar-spacing plan revisited."
    )


def test_payload_with_only_extra_mode_keys_does_not_raise():
    """A minimal smoke check: even with weird-but-typed-correct extra
    keys, the engine doesn't blow up."""
    inputs = make_inputs(barN_bot=8, nBars_bot=4)
    inputs.update({
        "mode_top": "count", "mode_bot": "count",
        "spacing_top": None, "spacing_bot": None,
    })
    demand_rows = [demand(Pu=0, Mu=100)]
    # Just confirm it runs to completion.
    res = calculate_all(inputs, demand_rows, 0)
    assert res is not None
    assert "flexure" in res
