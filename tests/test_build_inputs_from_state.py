"""buildInputsFromState(state) (Project Summary D/C, optimiser) must build the same engine inputs as
gatherInputs() does for the same section on screen, in every display-unit system.

The state is the one the page saves after a Calculate (batch.project.state_from_form mirrors
saveCurrentSectionState; pinned in tests/test_batch_project.py). Both functions run in the app's own
JavaScript through tests/batch_parity_harness.js.
"""
import re
from pathlib import Path

import pytest

from batch.project import state_from_form
from tests.batch_parity import CASES, assert_same, full_form, needs_node, run_harness

ROOT = Path(__file__).resolve().parents[1]


@needs_node
@pytest.mark.parametrize("name,overrides,units", CASES, ids=[c[0] for c in CASES])
def test_build_inputs_from_state_matches_gatherInputs(name, overrides, units):
    form = full_form(overrides)
    state = state_from_form(form, [], units)
    out = run_harness([{"form": form, "units": units, "state": state}])[0]
    assert_same(out["gather"], out["fromState"], name)


@needs_node
def test_state_saved_in_other_units_converts_with_state_units():
    # A section saved in kip/ft, rebuilt while the page shows kip/in: same engine inputs.
    name, overrides, units = next(c for c in CASES if c[0] == "units_kip_ft")
    form = full_form(overrides)
    state = state_from_form(form, [], units)
    out = run_harness([{"form": form, "units": units, "state": state},
                       {"form": form, "units": {"force": "kip", "length": "in"}, "state": state}])
    assert_same(out[0]["gather"], out[1]["fromState"], name)


def test_section_class_fallback_is_ui_default():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    i = html.index("function buildInputsFromState(")
    body = html[i:html.index("\n}\n", i)]
    assert "'CIP_PT'" not in body
    ui_default = re.search(r'<select id="sectionClass"[^>]*>([\s\S]*?)</select>', html).group(1)
    sel = re.search(r'<option value="(\w+)"[^>]*selected', ui_default).group(1)
    assert f"inp.sectionClass||'{sel}'" in body
