"""Api bridge for Column on Shaft: parse_csi / run_colshaft and project round-trip."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:  # pywebview is a GUI dependency; the Api class itself does not need it here
    import webview  # noqa: F401
except ImportError:
    import types
    sys.modules["webview"] = types.ModuleType("webview")
from api import Api  # noqa: E402

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "fixtures_csi", "colshaft_2bent.txt"), encoding="utf-8") as _f:
    PASTE = _f.read()


def test_api_parse_csi_summary():
    r = json.loads(Api().parse_csi(json.dumps({"paste": PASTE, "units": None})))
    assert "error" not in r
    assert r["n_rows"] > 0 and r["n_envelope"] > 0
    names = {c["name"]: c for c in r["cases"]}
    assert names["DEAD"]["default_category"] == "Dead"
    assert names["Str-I"]["default_category"] == "Strength"
    assert all(c["count"] > 0 for c in r["cases"])
    # 2026-10-20: frames per case (the UI asks for P_dead only without Dead rows)
    assert {"101", "201"} <= set(names["DEAD"]["frames"])
    assert all(isinstance(c["frames"], list) for c in r["cases"])
    fr = {f["name"]: f for f in r["frames"]}
    assert {"101", "102", "201"} <= set(fr)
    assert fr["101"]["height_in"] == 240.0
    assert fr["101"]["base_end_guess"] in ("min", "max")
    assert fr["101"]["n_rows"] > 0
    assert set(r["units"]) >= {"force", "moment", "length"}
    assert isinstance(r["warnings"], list)


def _payload():
    col = dict(D=60.0, fc=4.0, fy=60.0, cover=2.0, trans_type="hoop")
    shaft = dict(D=84.0, fc=4.0, fy=60.0, cover=3.0, trans_type="hoop")
    bent = {"name": "B1", "col_frames": ["101"], "shaft_frames": ["102"], "column": col,
            "shaft": shaft, "end_condition_long": "fixed-free", "end_condition_trans": "fixed-free",
            "shaft_basis": "cantilever", "L_eq_in": 120.0}
    return {"paste": PASTE, "code": "SDC 2.1", "bents": [bent]}


def test_api_run_colshaft_roundtrip():
    s = Api().run_colshaft(json.dumps(_payload()))
    r = json.loads(s)
    assert "error" not in r
    assert r["code"] and r["bents"][0]["name"] == "B1"
    assert r["bents"][0]["status"] in ("OK", "NG", "REFINED ANALYSIS REQUIRED", "NO SOLUTION")
    assert "NaN" not in s and "Infinity" not in s


def test_api_error_is_json():
    for fn, arg in (("parse_csi", {"paste": "not a table"}),
                    ("run_colshaft", {"paste": "garbage", "bents": []}),
                    ("run_colshaft", dict(_payload(), code="nope"))):
        r = json.loads(getattr(Api(), fn)(json.dumps(arg)))
        assert isinstance(r.get("error"), str) and r["error"]
    r = json.loads(Api().parse_csi("{not json"))
    assert "error" in r


def test_project_without_colshaft_roundtrips(tmp_path):
    proj = {"version": 1, "sections": [{"name": "S1", "inputs": {"b": 12}}]}
    path = str(tmp_path / "p.aashto.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{}")
    api = Api()
    assert json.loads(api.save_project_to_path(json.dumps(proj), path)) == {"path": path}
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == proj
    assert "columnShaft" not in proj
    proj2 = dict(proj, columnShaft={"paste": PASTE, "bents": [{"name": "B1"}]})
    api.save_project_to_path(json.dumps(proj2), path)
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == proj2
