"""batch.inputs.inputs_from_form must reproduce the app's gatherInputs() exactly (node parity)."""
import pytest

from tests.batch_parity import CASES, assert_same, full_form, needs_node, run_harness


@pytest.fixture(scope="module")
def js_results():
    return run_harness([{"form": full_form(o), "units": u} for _, o, u in CASES])


@needs_node
@pytest.mark.parametrize("idx", range(len(CASES)), ids=[c[0] for c in CASES])
def test_inputs_match_gatherInputs(idx, js_results):
    from batch.inputs import inputs_from_form
    name, overrides, units = CASES[idx]
    py = inputs_from_form(full_form(overrides), units)
    assert_same(js_results[idx]["gather"], py, name)


def test_js_round_half_up():
    from batch.inputs import js_round
    assert [js_round(x) for x in (0.5, 1.5, 2.5, -0.5, 2.4)] == [1, 2, 3, 0, 2]


def test_js_parse_float_leading_number():
    from batch.inputs import js_parse_float
    import math
    assert js_parse_float("12.5abc") == 12.5
    assert js_parse_float("  3e2 ") == 300
    assert math.isnan(js_parse_float(""))
    assert math.isnan(js_parse_float("abc"))
