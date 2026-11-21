"""batch.columns / batch.sheet_io: column spec, TSV exchange, grouping and validation."""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from batch import columns as C
from batch.form import FORM_DEFAULTS
from batch.sheet_io import group_rows, parse_settings, read_tsv

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
KIP_IN = {"force": "kip", "length": "in"}
HDR = [c.header for c in C.INPUT_COLUMNS]


def row(**cells):
    """One Inputs row as the VBA exports it (header order, strings)."""
    by_key = {c.key: c.header for c in C.INPUT_COLUMNS}
    vals = {by_key[k]: str(v) for k, v in cells.items()}
    return [vals.get(h, "") for h in HDR]


RECT = dict(section_id="B1", sectionType="RECTANGULAR", fc=5, b_flange=16, h_total=30, cover=2,
            bot_bar=9, n_bars_bot=4, shear_bar=4, shear_s=6, Mu=3000, Vu=60)
CIRC = dict(section_id="C1", sectionType="CIRCULAR", fc=4, circ_D=48, circ_bar1=10, circ_n1=16, cover=2,
            shear_bar=5, shear_s=4, Pu=-500, Mu=8000)


def base_form(**o):
    f = dict(FORM_DEFAULTS)
    f.update(o)
    return f


class _Opts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.o, self.cur = {}, None

    def handle_starttag(self, t, a):
        a = dict(a)
        if t == "select" and a.get("id"):
            self.cur = a["id"]
            self.o[self.cur] = []
        elif t == "option" and self.cur:
            self.o[self.cur].append(a.get("value"))

    def handle_endtag(self, t):
        if t == "select":
            self.cur = None


def test_choices_match_index_html_selects():
    p = _Opts()
    p.feed(HTML)
    for col in C.INPUT_COLUMNS + C.SETTINGS_ROWS:
        if col.choices and col.key in p.o:
            assert list(col.choices) == p.o[col.key], col.key


def test_astm_fy_map_matches_index_html():
    m = re.search(r"const ASTM_FY_MAP = \{(.*?)\};", HTML, re.S)
    found = {k: float(v) for k, v in re.findall(r"'(\w+)':\s*\{fy:\s*(\d+)", m.group(1))}
    assert C.ASTM_FY == found


def test_blank_rows_skipped():
    secs, errs = group_rows([HDR, row(**RECT), [""] * len(HDR), ["  "] * len(HDR)], base_form(), KIP_IN)
    assert [s.id for s in secs] == ["B1"] and not errs and secs[0].row_numbers == [C.INPUT_FIRST_DATA_ROW]


def test_missing_required_cell_errors_section_only():
    bad = dict(RECT, section_id="B2")
    del bad["h_total"]
    secs, errs = group_rows([HDR, row(**bad), row(**CIRC)], base_form(), KIP_IN)
    assert [s.id for s in secs] == ["C1"]
    assert len(errs) == 1 and errs[0].section_id == "B2" and "h" in errs[0].message
    assert errs[0].row == C.INPUT_FIRST_DATA_ROW


def test_noncontiguous_ids_group_in_first_appearance_order():
    rows = [HDR, row(**RECT), row(**CIRC), row(section_id="B1", Mu=-2000, Vu=40)]
    secs, errs = group_rows(rows, base_form(), KIP_IN)
    assert not errs and [s.id for s in secs] == ["B1", "C1"]
    first = C.INPUT_FIRST_DATA_ROW
    assert secs[0].row_numbers == [first, first + 2] and secs[1].row_numbers == [first + 1]
    assert [d["Mu"] for d in secs[0].demands] == [3000, -2000]


def test_later_row_conflicting_geometry_errors():
    rows = [HDR, row(**RECT), row(section_id="B1", h_total=36, Mu=100)]
    secs, errs = group_rows(rows, base_form(), KIP_IN)
    assert secs == [] and errs[0].section_id == "B1" and "differs" in errs[0].message


def test_later_row_blank_or_equal_geometry_ok():
    rows = [HDR, row(**RECT), row(section_id="B1", h_total="30.0", Mu=100)]
    secs, errs = group_rows(rows, base_form(), KIP_IN)
    assert not errs and len(secs[0].demands) == 2


def test_cells_not_applicable_ignored():
    secs, errs = group_rows([HDR, row(**dict(RECT, circ_D=99, hf_top=3))], base_form(), KIP_IN)
    assert not errs and secs[0].form["circ_D"] == FORM_DEFAULTS["circ_D"]
    assert secs[0].form["hf_top"] == FORM_DEFAULTS["hf_top"]  # flanges apply to T-SECTION only
    assert secs[0].form["h_total"] == "30"


def test_comma_decimal_rejected():
    secs, errs = group_rows([HDR, row(**dict(RECT, fc="5,5"))], base_form(), KIP_IN)
    assert secs == [] and "use '.' as decimal separator" in errs[0].message


def test_bad_choice_rejected():
    secs, errs = group_rows([HDR, row(**dict(RECT, bot_bar=12))], base_form(), KIP_IN)
    assert secs == [] and "Bottom bar" in errs[0].message


def test_fy_blank_uses_astm_filled_overrides():
    secs, _ = group_rows([HDR, row(**RECT), row(**dict(CIRC, fy=75))], base_form(astm_spec="A706_80"), KIP_IN)
    assert secs[0].form["fy"] == "80" and secs[0].form["fy_ovr"] is False
    assert secs[1].form["fy"] == "75" and secs[1].form["fy_ovr"] is True


def test_units_ft_converted():
    ft = {"force": "kip", "length": "ft"}
    secs, errs = group_rows([HDR, row(**dict(RECT, h_total=2.5, Mu=100, Tu=5))], base_form(), ft)
    assert not errs and secs[0].form["h_total"] == "2.5"  # display units kept in the form
    assert secs[0].demands[0]["Mu"] == pytest.approx(1200) and secs[0].demands[0]["Tu"] == pytest.approx(60)
    assert secs[0].form["fy"] == str(60 * 144)  # ASTM fy written in display units (ksf)


def test_settings_defaults_when_blank():
    form, units, opts = parse_settings([["Setting", "Value"]])
    assert units == KIP_IN and form["codeEdition"] == "CA" and form["crack_mode"] == "capped"
    assert opts == {"shearCapacityMethod": "gp",
                    "mphi": {"model": "service", "expected_concrete": False, "expected_steel": False},
                    "project_path": "", "overwrite_project": True}


def test_settings_values_parsed():
    lab = {c.key: c.header for c in C.SETTINGS_ROWS}
    rows = [["Setting", "Value"], [lab["unit_length"], "ft"], [lab["shear_method"], "B5"],
            [lab["mphi_model"], "sgs"], [lab["phi_f_f_ovr"], "TRUE"], [lab["phi_f_f_ovr_val"], "0.85"],
            [lab["overwrite_project"], "no"]]
    form, units, opts = parse_settings(rows)
    assert units["length"] == "ft" and opts["shearCapacityMethod"] == "b5" and opts["mphi"]["model"] == "sgs"
    assert form["phi_f_f_ovr"] is True and form["phi_f_f_ovr_val"] == "0.85"
    assert opts["overwrite_project"] is False


def test_read_tsv_utf8_bom(tmp_path):
    p = tmp_path / "in.tsv"
    p.write_bytes("﻿Section ID\tf'c\r\nŁ1\t5\r\n".encode("utf-8"))
    assert read_tsv(str(p)) == [["Section ID", "f'c"], ["Ł1", "5"]]


def test_columns_json_round_trip():
    d = json.loads(C.columns_json())
    assert [c["key"] for c in d["input"]] == [c.key for c in C.INPUT_COLUMNS]
    assert d["layout"]["input_first_data_row"] == C.INPUT_FIRST_DATA_ROW
    assert {"settings", "results"} <= set(d)
