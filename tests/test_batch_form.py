"""Batch field model (batch/form.py) — guarded against drift from index.html."""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from batch import form

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")


class _Defaults(HTMLParser):
    """Default value of every input / select / checkbox, as a new page shows it."""

    def __init__(self):
        super().__init__()
        self.el, self.factors, self._sel = {}, [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        i = a.get("id")
        if tag == "input":
            if "factor-ovr-cb" in (a.get("class") or ""):
                self.factors.append(a["data-factor"])
            if i:
                self.el[i] = ("checked" in a) if a.get("type") == "checkbox" else a.get("value", "")
        elif tag == "select" and i:
            self._sel, self.el[i] = i, None
        elif tag == "option" and self._sel:
            if self.el[self._sel] is None or "selected" in a:
                self.el[self._sel] = a.get("value")

    def handle_endtag(self, tag):
        if tag == "select":
            self._sel = None


@pytest.fixture(scope="module")
def ui():
    p = _Defaults()
    p.feed(HTML)
    return p


def _js_object(name):
    m = re.search(r"const " + name + r"\s*=\s*\{(.*?)\};", HTML, re.S)
    assert m, name
    body = re.sub(r"//[^\n]*", "", m.group(1))
    body = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*|\d+)\s*:", r'\1"\2":', "{" + body + "}")
    body = re.sub(r",\s*\}", "}", body.replace("'", '"'))  # JS trailing commas
    return json.loads(body)


def test_defaults_match_index_html(ui):
    for key, val in form.FORM_DEFAULTS.items():
        if key.endswith("_ovr") and key[:-4] in form.FACTOR_KEYS:
            continue  # factor checkboxes have no id; checked separately
        assert key in ui.el, key
        assert ui.el[key] == val, (key, ui.el[key], val)


def test_factor_keys_and_defaults(ui):
    assert form.FACTOR_KEYS == ui.factors
    for f in ui.factors:
        assert form.FORM_DEFAULTS[f + "_ovr"] is False
        assert form.FORM_DEFAULTS[f + "_ovr_val"] == ui.el[f + "_ovr_val"]


def test_section_state_default_differences_reported(ui):
    # 'hooked' is the welded / mechanical / hooks (0.85) option and the UI default since c9d52e0
    assert form.FORM_DEFAULTS["circ_hoop_closure"] == ui.el["circ_hoop_closure"] == "hooked"


def test_bars_and_kinds_match_index_html():
    bars = {int(k): v for k, v in _js_object("BARS").items()}
    assert form.BARS == bars
    assert form.FIELD_KINDS == _js_object("INPUT_FIELD_KINDS")


@pytest.mark.parametrize("kind,units,expected", [
    ("moment", {"force": "kip", "length": "ft"}, 1 / 12),
    ("stress", {"force": "lbf", "length": "in"}, 1000),
    ("stress", {"force": "kip", "length": "ft"}, 144),
    ("area_per_length", {"force": "kip", "length": "ft"}, 1 / 12),
    ("dimensionless", {"force": "lbf", "length": "ft"}, 1),
    ("unknown", {"force": "lbf", "length": "ft"}, 1),
])
def test_unit_factor(kind, units, expected):
    assert form.unit_factor(kind, units) == pytest.approx(expected)
    assert form.to_engine(form.from_engine(7.5, kind, units), kind, units) == pytest.approx(7.5)


def test_non_prestressed_class_zeroes_pt_fields_like_updatePTFields():
    # updatePTFields (index.html): NP -> strand_area, n_strands, duct_dia set to '0' (dp_input untouched)
    f = form.apply_section_class(dict(form.FORM_DEFAULTS))
    assert f["n_strands"] == "0" and f["strand_area"] == "0" and f["duct_dia"] == "0"
    assert f["dp_input"] == form.FORM_DEFAULTS["dp_input"]
    pt = form.apply_section_class(dict(form.FORM_DEFAULTS, sectionClass="CIP_PT", n_strands="0"))
    assert pt["n_strands"] == "10"  # restored from PT_DEFAULTS when switching back to a PT class
    assert "PT_DEFAULTS={strand_area:'0.217',n_strands:'10',dp_input:'15.5',duct_dia:'6'}" in HTML


def test_form_defaults_converted_to_display_units():
    ft = form.form_defaults_for({"force": "kip", "length": "ft"})
    assert float(ft["at_add_s"]) == pytest.approx(1.0) and float(ft["h_total"]) == pytest.approx(27.5 / 12)
    assert float(ft["Es"]) == pytest.approx(29000 * 144) and ft["d_top_override"] == ""
    assert form.form_defaults_for({"force": "kip", "length": "in"}) == form.FORM_DEFAULTS
