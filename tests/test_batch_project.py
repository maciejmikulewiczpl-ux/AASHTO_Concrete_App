"""batch.project: section state (saveCurrentSectionState shape) and project file."""
import json
import re
from pathlib import Path

import pytest

from batch.form import FORM_DEFAULTS
from batch.inputs import bars_from_spacing
from batch.project import build_project, state_from_form, write_project

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
KIP_IN = {"force": "kip", "length": "in"}
RUN_OPTS = {"shearCapacityMethod": "gp",
            "mphi": {"model": "service", "expected_concrete": False, "expected_steel": False}}


def _form(**o):
    f = dict(FORM_DEFAULTS)
    f.update(o)
    return f


def _app_state_input_keys():
    start = HTML.index("state.inputs = {")
    body = HTML[start:HTML.index("};", start)]
    body = re.sub(r"//[^\n]*", "", body)
    inner = body[len("state.inputs = {"):]
    inner = re.sub(r"\{[^{}]*\}", "", inner)  # drop inline fallbacks such as ({value:'BEAM'})
    return set(re.findall(r"(?:^|[,\s])([A-Za-z_][A-Za-z0-9_]*)\s*:", inner))


def test_state_input_keys_match_app():
    st = state_from_form(_form(), [], KIP_IN)
    assert set(st["inputs"]) == _app_state_input_keys()
    assert set(st) == {"units", "inputs", "demandRows", "ptDesign", "mrData"}
    assert st["mrData"] == {"top": None, "bot": None}


def test_demand_rows_stored_in_display_units():
    rows = [{"Pu": -120.0, "Mu": 1200.0, "Vu": 50.0, "Tu": 24.0, "Ps": -60.0, "Ms": 600.0}]
    st = state_from_form(_form(), rows, {"force": "kip", "length": "ft"})
    d = st["demandRows"][0]
    assert d["Mu"] == pytest.approx(100.0) and d["Tu"] == pytest.approx(2.0) and d["Ms"] == pytest.approx(50.0)
    assert d["Pu"] == -120.0 and d["Vu"] == 50.0 and d["Vp"] == 0
    assert d["x"] is None and d["ptMode"] == "layout" and d["loadCase"] == "service_I_full"
    assert st["units"] == {"force": "kip", "length": "ft"}


def test_state_round_trip_inputs_spacing_mode():
    f = _form(memberType="SLAB", bar_mode_bot="spacing", n_bars_bot="8", b_flange="12", h_total="9")
    st = state_from_form(f, [], KIP_IN)["inputs"]
    assert st["mode_bot"] == "spacing" and st["spacing_bot"] == 8
    assert st["nBars_bot"] == bars_from_spacing(8, 9 - 2 - 0.5 - 0.875 / 2, f, KIP_IN)
    assert st["mode_top"] == "count" and st["spacing_top"] is None and st["nBars_top"] == 5


def test_state_auto_fields_like_app_after_calculate():
    st = state_from_form(_form(fc="6"), [], KIP_IN)["inputs"]
    assert st["wc_val"] == "0.146" and float(st["Ec_val"]) > 0  # computed and written back, as the UI does
    assert st["fc"] == 6 and st["secType"] == "RECTANGULAR" and st["shN"] == 4


def test_project_shape():
    s1, s2 = state_from_form(_form(), [], KIP_IN), state_from_form(_form(), [], KIP_IN)
    p = build_project({"B1": s1, "C2": s2}, KIP_IN, RUN_OPTS)
    assert p["version"] == 1 and p["activeSection"] == "B1" and list(p["sections"]) == ["B1", "C2"]
    assert p["displayUnits"] == KIP_IN and p["runOptions"] == RUN_OPTS
    assert set(p["optParams"]) == {"tgt", "flex", "stir"}
    json.dumps(p)


def test_write_project_no_overwrite(tmp_path):
    path = tmp_path / "job.aashto.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_project(str(path), {"version": 1}, overwrite=False)
    assert path.read_text(encoding="utf-8") == "{}"


def test_write_project_overwrite(tmp_path):
    path = tmp_path / "Łódź job.aashto.json"
    out = write_project(str(path), {"version": 1, "sections": {}}, overwrite=True)
    assert out == str(path) and json.loads(path.read_text(encoding="utf-8"))["version"] == 1
