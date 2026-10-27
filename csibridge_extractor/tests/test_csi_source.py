import pytest

from csibridge_extractor.extractor import csi_source as cs
from csibridge_extractor.extractor.csi_source import CsiConnectError, CsiSource
from csibridge_extractor.extractor.source import TABLE_COLUMNS, SourceError

# Rows recorded by the probe on "Structure A_v2.1" (CSiBridge 27.1.0), X Str-I1.
FRAME_FIELDS = ["Frame", "Station", "OutputCase", "CaseType", "StepType", "P", "V2", "V3", "T", "M2", "M3",
                "FrameElem", "ElemStation"]
FRAME_ENV = [
    ["5417", "0", "X Str-I1", "Combination", "Max", "-531.497", "447.541", "526.192", "43789.522", "65587.545",
     "12744.282", "5417-1", "0"],
    ["9999", "0", "X Str-I1", "Combination", "Max", "1", "1", "1", "1", "1", "1", "9999-1", "0"],
]
FRAME_COR = [
    ["5417", "0", "X Str-I1", "Combination", "Max P", "-531.497", "80.287", "-130.079", "8408.752", "-11268.501",
     "-13824.706", "5417-1", "0"],
]
JOINT_FIELDS = ["Joint", "OutputCase", "CaseType", "StepType", "F1", "F2", "F3", "M1", "M2", "M3"]
JOINT_ENV = [["5073", "X Str-I1", "Combination", "Max", "4179.662", "126.709", "784.955", "13564.462",
              "65587.262", "304294.961"]]
JOINT_COR = [["5073", "X Str-I1", "Combination", "Max F3", "1964.521", "126.709", "784.955", "13564.462",
              "64433.784", "200766.481"]]
OPTS = [("BaseReactionGX", 0.0), ("IsAllModes", True), ("Combo", 1), ("BridgeDesign", 1)]


class FakeApi:
    def __init__(self, version="27.1.0", file="C:/m/Structure A_v2.1.bdb", fail_table=False, joint_cor=True):
        self.v, self.f, self.fail_table, self.joint_cor = version, file, fail_table, joint_cor
        self.opts = list(OPTS)
        self.sel = (["DC"], ["X Str-I1", "Str-V1"])
        self.calls = []

    def model_file(self): return self.f
    def version(self): return self.v
    def present_units(self): return "kip_in_F"
    def case_names(self): return ["DC", "LL", "WIND"]
    def case_status(self): return {"DC": 4, "LL": 4, "WIND": 1}
    def case_type(self, n): return "LinearStatic"
    def combo_names(self): return ["X Str-I1", "Str-W", "Env", "Bad"]
    def combo_type(self, n): return {"Env": 1}.get(n, 0)
    def combo_items(self, n):
        return {"X Str-I1": ["DC", "LL"], "Str-W": ["DC", "WIND"], "Env": ["X Str-I1"], "Bad": []}[n]
    def group_names(self): return ["ALL", "PIER", "PROBE2"]
    def group_items(self, g):
        return {"ALL": [(2, "5417"), (2, "9999"), (2, "7"), (1, "5073"), (1, "6588")],
                "PIER": [(2, "5417"), (2, "9999"), (1, "5073")],
                "PROBE2": [(2, "5417")]}[g]
    def frame_names(self): return ["5417", "9999", "7"]
    def joint_names(self): return ["5073", "6588"]
    def table_units(self, key):
        if key == "Joint Reactions":
            return dict(zip(JOINT_FIELDS, ["", "", "", "", "Kip", "Kip", "Kip", "Kip-in", "Kip-in", "Kip-in"]))
        return dict(zip(FRAME_FIELDS, ["", "in", "", "", "", "Kip", "Kip", "Kip", "Kip-in", "Kip-in", "Kip-in",
                                       "", "in"]))
    def get_options(self): return list(self.opts)
    def set_options(self, values):
        self.calls.append(("set_options", list(values)))
        self.opts = [(k, v) for (k, _), v in zip(self.opts, values)]
    def get_selection(self): return (list(self.sel[0]), list(self.sel[1]))
    def set_selection(self, cases, combos):
        self.calls.append(("set_selection", list(cases), list(combos)))
        self.sel = (list(cases), list(combos))
    def table(self, key, group):
        combo = dict(self.opts)["Combo"]
        self.calls.append(("table", key, group, combo, self.sel))
        if self.fail_table:
            raise RuntimeError("GetTableForDisplayArray returned 1")
        if key == "Joint Reactions":
            rows = JOINT_COR if combo == 3 and self.joint_cor else JOINT_ENV
            return JOINT_FIELDS, [x for r in rows for x in r]
        rows = FRAME_ENV if combo == 1 else FRAME_COR
        return FRAME_FIELDS, [x for r in rows for x in r]


def test_frame_envelope_rows_mapped_and_numeric():
    api = FakeApi()
    rows = list(CsiSource(api=api).iter_rows("frame", "envelope", ["X Str-I1"], ["5417"]))
    assert rows == [("5417", 0.0, "X Str-I1", "Combination", "Max", -531.497, 447.541, 526.192, 43789.522,
                     65587.545, 12744.282, "5417-1", 0.0)]
    assert all(len(r) == len(TABLE_COLUMNS["frame"]) for r in rows)


def test_correspondence_uses_combo_option_3_and_smallest_group():
    api = FakeApi()
    rows = list(CsiSource(api=api).iter_rows("frame", "correspondence", ["X Str-I1"], ["5417"]))
    assert rows[0][4] == "Max P"
    t = [c for c in api.calls if c[0] == "table"][0]
    assert t[2] == "PROBE2" and t[3] == 3
    assert t[4] == ([], ["X Str-I1"])  # combos selected separately from cases


def test_options_and_selection_restored_after_fetch_and_on_error():
    api = FakeApi()
    list(CsiSource(api=api).iter_rows("frame", "envelope", ["X Str-I1", "DC"], ["5417"]))
    assert api.opts == OPTS and api.sel == (["DC"], ["X Str-I1", "Str-V1"])
    bad = FakeApi(fail_table=True)
    src = CsiSource(api=bad)
    with pytest.raises(SourceError):
        list(src.iter_rows("frame", "envelope", ["X Str-I1"], ["5417"]))
    assert bad.opts == OPTS and bad.sel == (["DC"], ["X Str-I1", "Str-V1"])
    src.close()
    src.close()


def test_whole_table_read_noted():
    api = FakeApi()
    src = CsiSource(api=api)
    list(src.iter_rows("frame", "envelope", ["X Str-I1"], ["5417", "7"]))
    assert [c for c in api.calls if c[0] == "table"][0][2] == "ALL"
    assert any("whole" in n for n in src.notes())


def test_joint_correspondence_requested():
    api = FakeApi()
    src = CsiSource(api=api)
    rows = list(src.iter_rows("joint", "correspondence", ["X Str-I1"], ["5073"]))
    assert rows[0][3] == "Max F3" and rows[0][4] == 1964.521
    assert [c for c in api.calls if c[0] == "table"][0][3] == 3
    assert not any("Max/Min" in n for n in src.notes())
    assert list(src.iter_rows("joint", "envelope", ["X Str-I1"], ["5073"]))[0][4] == 4179.662


def test_joint_correspondence_envelope_fallback_noted():
    src = CsiSource(api=FakeApi(joint_cor=False))
    rows = list(src.iter_rows("joint", "correspondence", ["X Str-I1"], ["5073"]))
    assert rows[0][3] == "Max"
    assert any("Max/Min" in n and "X Str-I1" in n for n in src.notes())


def test_has_results_cases_and_nested_combos():
    c = {x.name: x for x in CsiSource(api=FakeApi()).list_cases()}
    assert c["DC"].has_results and not c["WIND"].has_results
    assert c["X Str-I1"].has_results and not c["Str-W"].has_results
    assert c["Env"].has_results and c["Env"].type == "Envelope"
    assert not c["Bad"].has_results


def test_model_info_units_lists_and_units_row():
    src = CsiSource(api=FakeApi())
    m = src.model_info()
    assert m.analysed and m.units == {"present": "kip_in_F", "force": "Kip", "length": "in"}
    lists = src.model_lists()
    assert lists.groups["PIER"] == ({"5417", "9999"}, {"5073"})
    assert src.units_row("joint")[4] == "Kip" and len(src.units_row("frame")) == 13


def test_version_mismatch_warns():
    assert any("26.0" in n for n in CsiSource(api=FakeApi(version="26.0.0")).notes())
    assert not any("verified" in n for n in CsiSource(api=FakeApi()).notes())


def test_list_instances_parses_tasklist(monkeypatch):
    out = ('"CSiBridge.exe","20076","Console","1","900,000 K","Running","ARUP\\me","0:01:46",'
           '"CSiBridge v27.1.0 Advanced with Rating 64-bit - Structure A_v2.0_wind test"\n'
           '"CSiBridge.exe","36740","Console","1","800,000 K","Running","ARUP\\me","0:00:30",'
           '"CSiBridge v27.1.0 Advanced with Rating 64-bit - Structure A_v2.1"\n')
    monkeypatch.setattr(cs.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": out})())
    assert cs.list_instances() == [{"pid": 20076, "model": "Structure A_v2.0_wind test"},
                                   {"pid": 36740, "model": "Structure A_v2.1"}]
    assert cs.count_instances() == 2


def test_connect_messages(monkeypatch):
    with pytest.raises(CsiConnectError, match="no model"):
        CsiSource(api=FakeApi(file=""))
    assert "not running" in cs.connect_message("not_running")
    assert "CSiAPIv1.dll" in cs.connect_message("no_dll")
    assert "analysis" in cs.connect_message("not_analysed")

    from csibridge_extractor.probe import probe_csibridge as pc
    monkeypatch.setattr(pc, "find_dlls", lambda explicit=None: [])
    with pytest.raises(CsiConnectError, match="CSiAPIv1.dll"):
        cs._NetApi()
    monkeypatch.setattr(pc, "find_dlls", lambda explicit=None: ["x.dll"])
    monkeypatch.setattr(pc, "attach", lambda args, rec: (None, None, None))
    with pytest.raises(CsiConnectError, match="not running"):
        cs._NetApi()


def test_whole_table_read_one_case_at_a_time():
    api = FakeApi()
    src = CsiSource(api=api)
    list(src.iter_rows("frame", "envelope", ["X Str-I1", "DC"], ["5417", "7"]))
    sels = [c[4] for c in api.calls if c[0] == "table"]
    assert sels == [([], ["X Str-I1"]), (["DC"], [])]
    api2 = FakeApi()
    list(CsiSource(api=api2).iter_rows("frame", "envelope", ["X Str-I1", "DC"], ["5417"]))
    assert len([c for c in api2.calls if c[0] == "table"]) == 1  # small group: one call


def test_joint_displacements_table_and_correspondence():
    disp_fields = ["Joint", "OutputCase", "CaseType", "StepType", "U1", "U2", "U3", "R1", "R2", "R3"]
    row = ["5073", "X Str-I1", "Combination", "Max", "0.184676", "0.103956", "0.032669", "0.008583", "0.010739",
           "0.005613"]
    cor = ["5073", "X Str-I1", "Combination", "Max U3", "0.1", "0.2", "0.032669", "0.001", "0.002", "0.003"]

    class DispApi(FakeApi):
        def table_units(self, key):
            if key == "Joint Displacements":
                return dict(zip(disp_fields, ["", "", "", "", "ft", "ft", "ft", "Radians", "Radians", "Radians"]))
            return super().table_units(key)

        def table(self, key, group):
            if key == "Joint Displacements":
                combo = dict(self.opts)["Combo"]
                self.calls.append(("table", key, group, combo, self.sel))
                return disp_fields, list(cor if combo == 3 and self.joint_cor else row)
            return super().table(key, group)

    api = DispApi()
    src = CsiSource(api=api)
    rows = list(src.iter_rows("disp", "envelope", ["X Str-I1"], ["5073"]))
    assert rows == [("5073", "X Str-I1", "Combination", "Max", 0.184676, 0.103956, 0.032669, 0.008583, 0.010739,
                     0.005613)]
    assert [c for c in api.calls if c[0] == "table"][0][2] == "PIER"  # smallest group with joint 5073
    assert src.units_row("disp")[4:] == ["ft", "ft", "ft", "Radians", "Radians", "Radians"]
    rows = list(src.iter_rows("disp", "correspondence", ["X Str-I1"], ["5073"]))
    assert rows[0][3] == "Max U3" and [c for c in api.calls if c[0] == "table"][-1][3] == 3
    assert not any("Max/Min" in n for n in src.notes())
    src2 = CsiSource(api=DispApi(joint_cor=False))
    assert list(src2.iter_rows("disp", "correspondence", ["X Str-I1"], ["5073"]))[0][3] == "Max"
    assert any(n.startswith("joint displacements") and "Max/Min" in n for n in src2.notes())
