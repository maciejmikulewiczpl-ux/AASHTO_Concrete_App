"""Unit tests for the pure helpers of the CSiBridge probe (no CSiBridge / pythonnet needed)."""
import csv

import pytest

from csibridge_extractor.probe import probe_csibridge as probe


def test_parse_args_defaults_and_repeatable_case():
    ns = probe.parse_args([])
    assert ns.frames == []
    assert ns.joints == []
    assert ns.group is None
    assert ns.case == []
    assert ns.out == "probe_out"
    assert ns.dll is None

    ns = probe.parse_args(["--frames", "1227", "1301-1303", "--joints", "5",
                           "--case", "Str-I1", "--case", "DC",
                           "--group", "Pier2", "--out", "x", "--dll", r"C:\a\CSiAPIv1.dll"])
    assert ns.frames == ["1227", "1301-1303"]
    assert ns.joints == ["5"]
    assert ns.case == ["Str-I1", "DC"]
    assert ns.group == "Pier2"
    assert ns.out == "x"
    assert ns.dll == r"C:\a\CSiAPIv1.dll"


def test_unpack_out_return_code_first():
    assert probe.unpack_out((0, 3, ["a"])) == (3, ["a"])
    assert probe.unpack_out((0,)) == ()
    assert probe.unpack_out(0) == ()
    with pytest.raises(probe.ProbeCallError) as ei:
        probe.unpack_out((1, 3, ["a"]), "LoadCases.GetNameList")
    assert ei.value.name == "LoadCases.GetNameList"
    assert ei.value.code == 1
    with pytest.raises(probe.ProbeCallError):
        probe.unpack_out(2, "X")


def test_rows_to_csv_roundtrip(tmp_path):
    p = tmp_path / "sub" / "rows.csv"
    header = ["Frame", "Station", "StepType", "P"]
    rows = [["1227", 0.0, "Max", -12.5], ["1227", 10.0, "", 3]]
    probe.rows_to_csv(p, header, rows)
    with open(p, newline="", encoding="utf-8") as fh:
        back = list(csv.reader(fh))
    assert back[0] == header
    assert back[1] == ["1227", "0.0", "Max", "-12.5"]
    assert back[2] == ["1227", "10.0", "", "3"]


def test_summarise_lists_routes_and_errors():
    result = {
        "attach": {"success": True, "method": "pythonnet cHelper", "errors": []},
        "version": "27.1.0",
        "model_file": r"C:\m\bridge.bdb",
        "present_units": "kip_ft_F",
        "routes": {
            "database_tables": {
                "fetches": [{"table": "frame", "mode": "combo_3", "rows": 12, "seconds": 0.5,
                             "step_types": ["Max P", "Min P"], "error": None}],
                "errors": ["GetTableForDisplayArray failed: boom"],
            },
            "direct": {
                "fetches": [{"table": "joint", "mode": "combo_1", "rows": 0, "seconds": 0.1,
                             "step_types": [], "error": "ProbeCallError JointReact rc=1"}],
                "errors": [],
            },
        },
        "restored": {"all_ok": True},
        "output_dir": r"C:\probe_out",
    }
    text = probe.summarise(result)
    assert "database_tables" in text and "direct" in text
    assert "boom" in text
    assert "JointReact rc=1" in text
    assert "Max P" in text
    assert "27.1.0" in text
    assert "NEXT: send me the JSON + CSV folder" in text
    assert r"C:\probe_out" in text


def test_summarise_survives_failed_attach():
    text = probe.summarise({"attach": {"success": False, "errors": ["no dll"]}, "routes": {}})
    assert "no dll" in text
    assert "NEXT" in text
