"""
Pin the Beam/Slab Section Type contract.

The Beam/Slab toggle is implemented entirely in `index.html` (JS layer).
The Python engine (`calc_engine.py`) is intentionally unchanged: pro-rated
As in Slab mode is fed via the existing `As_top_ovr` / `As_bot_ovr` keys
that the multi-row override already uses. These tests verify:

  1. Beam-mode (no `memberType` key, default) and `memberType='SLAB'`
     with no override produce identical engine output — i.e. the engine
     ignores `memberType`.
  2. When `As_bot_ovr` is supplied (the JS-side slab pro-rating result),
     the engine consumes it as the final `As_bot` and downstream Mn
     reflects the pro-rated value.
  3. The JS slab branches required for the UI contract exist in
     index.html (smoke check against accidental removal).

Units: kip, inch, ksi.
"""
import os
import re

from calc_engine import BARS, calculate_all
from tests.fixtures import demand, make_inputs


HERE = os.path.dirname(__file__)
INDEX_HTML = os.path.abspath(os.path.join(HERE, os.pardir, "index.html"))


def _row(res, idx=0):
    """Extract the first row_results dict from a calculate_all() return."""
    rr = res["row_results"]
    return rr[idx] if isinstance(rr, list) else rr


def _Mn(res):
    """Nominal flexural capacity from a calculate_all() return."""
    return res["flexure"]["Mn"]


def test_engine_ignores_memberType_when_no_override():
    """memberType is JS-only metadata; the engine must produce identical
    output whether or not the key is present, as long as As_*_ovr is None."""
    base = make_inputs(h=24, b=22, secType="RECTANGULAR",
                       barN_bot=7, nBars_bot=4, barN_top=0, nBars_top=0)
    dem = demand(Pu=0, Mu=2000, Vu=80, Ms=1000)

    res_no_key = calculate_all(base, [dem], 0)
    base_slab = dict(base, memberType="SLAB")
    res_with_slab = calculate_all(base_slab, [dem], 0)

    assert abs(_Mn(res_no_key) - _Mn(res_with_slab)) < 1e-6, \
        "memberType must not affect engine output without As_*_ovr"
    r0, r1 = _row(res_no_key), _row(res_with_slab)
    assert abs(r0["Mr"] - r1["Mr"]) < 1e-6
    assert abs(r0["Vnmax"] - r1["Vnmax"]) < 1e-6


def test_slab_spacing_prorates_via_As_bot_ovr():
    """User example: b=22, #7 (a=0.60), spacing=6 in slab mode.
    JS computes As_bot_ovr = 22/6 * 0.60 = 2.20.
    Engine must use 2.20 as the final As_bot."""
    bar = BARS[7]
    assert abs(bar["a"] - 0.60) < 1e-6, "fixture assumption: #7 area = 0.60 in^2"

    b, s = 22.0, 6.0
    expected_As = (b / s) * bar["a"]  # 2.20

    inp = make_inputs(
        h=24, b=b, secType="RECTANGULAR",
        barN_bot=7, nBars_bot=4,        # the integer count the JS sends (floor(clearW/s)+1)
        barN_top=0, nBars_top=0,
        As_bot_ovr=expected_As,         # the pro-rated As from JS slab branch
        memberType="SLAB",
    )
    res = calculate_all(inp, [demand(Pu=0, Mu=1500, Vu=60, Ms=800)], 0)

    # The engine writes As_bot into the inputs dict during _prepare_inputs.
    # We read it back from the row result via the input echo.
    assert abs(res["inputs"]["As_bot"] - expected_As) < 1e-9, (
        f"engine As_bot should equal pro-rated override "
        f"{expected_As}, got {res['inputs']['As_bot']}"
    )


def test_slab_prorated_As_differs_from_beam_count_As():
    """Sanity: with b=22, s=6, #7, beam-mode As (count×a) ≠ slab-mode As (b/s×a).
    Beam count = floor((22 - 2*2 - 2*0.5)/6) + 1 = floor(17/6)+1 = 3 → As=1.80
    Slab pro-rated As = 22/6 * 0.60 = 2.20
    Their Mn must differ."""
    bar = BARS[7]
    beam_As = 3 * bar["a"]              # 1.80
    slab_As = (22.0 / 6.0) * bar["a"]   # 2.20
    assert beam_As != slab_As

    common = dict(h=24, b=22, secType="RECTANGULAR",
                  barN_bot=7, nBars_bot=3,
                  barN_top=0, nBars_top=0)
    dem = demand(Pu=0, Mu=1500, Vu=60, Ms=800)

    res_beam = calculate_all(make_inputs(**common), [dem], 0)
    res_slab = calculate_all(make_inputs(As_bot_ovr=slab_As, memberType="SLAB", **common), [dem], 0)

    Mn_beam = _Mn(res_beam)
    Mn_slab = _Mn(res_slab)
    assert Mn_slab > Mn_beam, (
        f"Slab pro-rated As (2.20) should give larger Mn than beam count As (1.80); "
        f"got Mn_beam={Mn_beam}, Mn_slab={Mn_slab}"
    )


def test_slab_count_mode_does_not_prorate():
    """In count mode, slab does NOT pro-rate — As = N × A_b exactly.
    This mirrors the JS guard `_modeBot==='spacing'` before applying override."""
    inp = make_inputs(
        h=24, b=22, secType="RECTANGULAR",
        barN_bot=7, nBars_bot=4, barN_top=0, nBars_top=0,
        memberType="SLAB",
        # No As_bot_ovr — JS would not set one in count mode.
    )
    res = calculate_all(inp, [demand(Pu=0, Mu=1500, Vu=60, Ms=800)], 0)
    expected_As = 4 * BARS[7]["a"]  # 2.40
    assert abs(res["inputs"]["As_bot"] - expected_As) < 1e-9


def _read_index_html():
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        return f.read()


def test_index_html_has_member_type_dropdown_and_shape_label():
    """UI contract: new memberType dropdown exists, original sectionType
    select is kept (id unchanged so engine-facing JS still works), and the
    visible label is renamed to 'Section Shape'."""
    html = _read_index_html()
    assert 'id="memberType"' in html, "Beam/Slab dropdown missing"
    assert re.search(r'<option value="BEAM"[^>]*>Beam</option>', html), "Beam option missing"
    assert re.search(r'<option value="SLAB"[^>]*>Slab</option>', html), "Slab option missing"
    assert 'id="sectionType"' in html, "Section Shape select must keep id='sectionType' for engine compatibility"
    assert "Section Shape" in html, "Existing dropdown must be relabeled to 'Section Shape'"


def test_index_html_has_slab_prorating_js_branches():
    """JS contract: gatherInputs and buildInputsFromState must contain a
    slab+spacing branch that sets As_*_ovr = (b/s) * bar.a. Drawing must
    contain the slab exact-spacing branch (centered on b/2)."""
    html = _read_index_html()
    # Pro-rating override in gatherInputs (single-row) — matches "(b/V('n_bars_bot'))*bar_bot.a"
    assert re.search(r"As_bot_ovr\s*=\s*\(\s*b\s*/\s*V\(\s*'n_bars_bot'\s*\)\s*\)\s*\*\s*bar_bot\.a", html), \
        "single-row slab pro-rating for bottom missing"
    assert re.search(r"As_top_ovr\s*=\s*\(\s*b\s*/\s*V\(\s*'n_bars_top'\s*\)\s*\)\s*\*\s*bar_top\.a", html), \
        "single-row slab pro-rating for top missing"
    # Per-row slab pro-rating in multi-row reducer
    assert "isSlab&&r.mode==='spacing'&&r.val>0" in html or \
           "isSlab && r.mode==='spacing' && r.val>0" in html, \
        "multi-row slab pro-rating branch missing"
    # buildInputsFromState parallel (uses inp.mode_top / spacing_top)
    assert "inp.mode_top==='spacing'" in html, \
        "buildInputsFromState slab branch (top) missing"
    assert "inp.mode_bot==='spacing'" in html, \
        "buildInputsFromState slab branch (bot) missing"
    # Drawing: exact-spacing centered placement (bottom + top branches)
    assert "b/2+(i-(nFit-1)/2)*_sBot" in html, "slab drawing branch (bot) missing"
    assert "b/2+(i-(nFit_t-1)/2)*_sTop" in html, "slab drawing branch (top) missing"


def test_index_html_locks_shape_to_rectangular_when_slab():
    """UI contract: in Slab mode the Section Shape select is forced to
    RECTANGULAR and disabled (T-section rows hidden via existing
    updateSectionFields)."""
    html = _read_index_html()
    # The onMemberTypeChange handler forces shape value and disables
    assert "function onMemberTypeChange()" in html, "onMemberTypeChange handler missing"
    assert "shapeSel.value='RECTANGULAR'" in html, "Slab mode must force shape to RECTANGULAR"
    assert "shapeSel.disabled=true" in html, "Slab mode must disable the Section Shape dropdown"
    # And the slab info banner must be present + toggled
    assert 'id="slabAsNote"' in html, "Slab info banner missing"
