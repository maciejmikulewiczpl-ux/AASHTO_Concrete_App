"""
Pin the section-state display-unit contract (index.html, JS layer).

Bug 2026-10-13: with display units = ft/ksf, "New section" loaded the kip/in/ksi
defaults (f'c = 5, s = 4, strand area 0.217, ...) into ft/ksf fields unconverted,
and the ASTM fy sync wrote 60 into a ksf field → engine saw f'c = 0.035 ksi,
fy = 0.42 ksi (circular D = 9.84 ft: Vr = 78 kip instead of ~1600 kip).

Contract:
  1. Section states record the display units their values are stored in.
  2. loadSectionState converts a state stored in other units via applyUnits().
  3. applyAstmFy writes fy through fromEngine (display units).
"""
import os
import re

INDEX_HTML = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, "index.html"))


def _src():
    with open(INDEX_HTML, encoding="utf-8") as f:
        return f.read()


def _func(src, name):
    m = re.search(r"function " + name + r"\(.*?\n\}\n", src, re.S)
    assert m, f"{name} not found in index.html"
    return m.group(0)


def test_default_section_state_is_tagged_kip_in():
    body = _func(_src(), "getDefaultSectionState")
    assert re.search(r"units:\s*\{force:'kip',\s*length:'in'\}", body)


def test_saved_section_state_records_display_units():
    body = _func(_src(), "saveCurrentSectionState")
    assert "state.units = {...displayUnits}" in body


def test_load_section_state_converts_units():
    body = _func(_src(), "loadSectionState")
    assert "state.units" in body
    assert "displayUnits = curUnits" in body
    assert "applyUnits(stateUnits)" in body


def test_astm_fy_written_in_display_units():
    body = _func(_src(), "applyAstmFy")
    assert "fromEngine(spec.fy, 'stress')" in body
    assert "el.value = spec.fy;" not in body
