import json
from pathlib import Path

import pytest

from csibridge_extractor.api import Api
from csibridge_extractor.extractor.csi_source import CsiSource
from csibridge_extractor.extractor.groups import GroupError, create_joint_group, edit_joint_group, joint_range
from csibridge_extractor.extractor.source import FakeSource

FIX = Path(__file__).parent / "fixtures" / "fake_model.json"


class FakeWriteApi:
    """Records every call; only create_group / assign_joint / delete_group may write."""

    def __init__(self, joints=("1", "3", "5", "7", "9", "11"), fail_assign=None, refuse_create=False,
                 fail_unassign=None):
        self.joints = list(joints)
        self.groups = {"ALL": [(1, j) for j in joints], "PIER": [(2, "100")], "J": [(1, "1"), (1, "3")],
                       "MIXED": [(1, "5"), (5, "A1")]}
        self.status = {"DC": 4}
        self.locked = True
        self.fail_assign, self.refuse_create, self.fail_unassign = fail_assign, refuse_create, fail_unassign
        self.writes = []

    def group_names(self): return list(self.groups)
    def joint_names(self): return list(self.joints)
    def group_items(self, g): return list(self.groups[g])
    def model_locked(self): return self.locked
    def case_status(self): return dict(self.status)

    def create_group(self, name):
        self.writes.append(("create_group", name))
        if self.refuse_create:
            raise RuntimeError("SetGroup returned 1")
        self.groups[name] = []

    def assign_joint(self, joint, group):
        self.writes.append(("assign_joint", joint, group))
        if joint == self.fail_assign:
            raise RuntimeError("SetGroupAssign returned 1")
        self.groups[group].append((1, joint))

    def unassign_joint(self, joint, group):
        self.writes.append(("unassign_joint", joint, group))
        if joint == self.fail_unassign:
            raise RuntimeError("SetGroupAssign returned 1")
        self.groups[group].remove((1, joint))

    def delete_group(self, name):
        self.writes.append(("delete_group", name))
        del self.groups[name]


def test_joint_range_increment():
    assert joint_range(1, 10, 2) == ["1", "3", "5", "7", "9"]
    assert joint_range("5", "5", "3") == ["5"]
    assert joint_range(1, 4, 1) == ["1", "2", "3", "4"]


@pytest.mark.parametrize("args", [(1, 10, 0), (10, 1, 1), ("a", 2, 1), (-1, 5, 1), (1, 10, -2)])
def test_joint_range_rejects(args):
    with pytest.raises(GroupError):
        joint_range(*args)


def test_create_only_writes_new_group():
    api = FakeWriteApi()
    res = create_joint_group(api, "SPAN1", joint_range(1, 10, 2))
    assert res.added == ["1", "3", "5", "7", "9"] and res.missing == [] and res.joints == res.added
    assert api.writes == [("create_group", "SPAN1")] + [("assign_joint", j, "SPAN1") for j in res.added]
    assert api.groups["PIER"] == [(2, "100")] and len(api.groups["ALL"]) == 6
    assert res.notes == []


def test_create_empty_group():
    api = FakeWriteApi()
    res = create_joint_group(api, "EMPTY", [])
    assert api.writes == [("create_group", "EMPTY")] and res.joints == []


def test_add_joints():
    api = FakeWriteApi()
    res = edit_joint_group(api, "add", "j", ["3", "5", "6"])
    assert res.name == "J" and res.added == ["5"] and res.skipped == ["3"] and res.missing == ["6"]
    assert api.writes == [("assign_joint", "5", "J")]
    assert res.joints == ["1", "3", "5"] and res.notes == []


def test_replace_joints():
    api = FakeWriteApi()
    res = edit_joint_group(api, "replace", "J", joint_range(3, 7, 2))
    assert res.removed == ["1"] and res.added == ["5", "7"]
    assert {n for _, n in api.groups["J"]} == {"3", "5", "7"} and res.notes == []
    assert not any(w[0] == "create_group" for w in api.writes)


def test_remove_joints():
    api = FakeWriteApi()
    res = edit_joint_group(api, "remove", "J", joint_range(1, 9, 2))
    assert res.removed == ["1", "3"] and res.skipped == ["5", "7", "9"]
    assert api.groups["J"] == [] and res.joints == []


@pytest.mark.parametrize("name,msg", [("ALL", "ALL"), ("PIER", "non-joint"), ("MIXED", "non-joint"),
                                      ("NOPE", "does not exist")])
@pytest.mark.parametrize("action", ["add", "replace", "remove"])
def test_edit_only_joint_only_groups(action, name, msg):
    api = FakeWriteApi()
    before = {g: list(v) for g, v in api.groups.items()}
    with pytest.raises(GroupError, match=msg):
        edit_joint_group(api, action, name, ["1"])
    assert api.writes == [] and api.groups == before


@pytest.mark.parametrize("action", ["add", "replace", "remove"])
def test_edit_needs_a_range(action):
    api = FakeWriteApi()
    with pytest.raises(GroupError):
        edit_joint_group(api, action, "J", [])
    assert api.writes == []


def test_blank_named_members_untouched():
    # CSiBridge 27.1 reported group "Rail Bottom" as 4 joints named "" (2026-11-07)
    api = FakeWriteApi()
    api.groups["RB"] = [(1, "")] * 4
    res = edit_joint_group(api, "replace", "RB", joint_range(1, 5, 2))
    assert res.added == ["1", "3", "5"] and res.removed == []
    assert not any(w[0] == "unassign_joint" for w in api.writes)
    assert any("without a name" in n for n in res.notes)
    assert not any("expected" in n for n in res.notes)


def test_failed_replace_restores_group():
    api = FakeWriteApi(fail_assign="7")
    with pytest.raises(GroupError, match="restored"):
        edit_joint_group(api, "replace", "J", ["5", "7"])
    assert sorted(n for _, n in api.groups["J"]) == ["1", "3"]


def test_failed_remove_restores_group():
    api = FakeWriteApi(fail_unassign="3")
    with pytest.raises(GroupError, match="restored"):
        edit_joint_group(api, "remove", "J", ["1", "3"])
    assert sorted(n for _, n in api.groups["J"]) == ["1", "3"]


def test_missing_joints_skipped():
    res = create_joint_group(FakeWriteApi(), "G", joint_range(1, 4, 1))
    assert res.added == ["1", "3"] and res.missing == ["2", "4"]


@pytest.mark.parametrize("name", ["ALL", "all", " PIER "])
def test_existing_group_never_touched(name):
    api = FakeWriteApi()
    with pytest.raises(GroupError, match="already exists"):
        create_joint_group(api, name, ["1"])
    assert api.writes == []


def test_nothing_written_when_no_joint_exists():
    api = FakeWriteApi()
    with pytest.raises(GroupError, match="nothing was changed"):
        create_joint_group(api, "G", ["2", "4"])
    assert api.writes == []


def test_empty_name_rejected():
    api = FakeWriteApi()
    with pytest.raises(GroupError):
        create_joint_group(api, "  ", ["1"])
    assert api.writes == []


def test_refused_create_reports():
    api = FakeWriteApi(refuse_create=True)
    with pytest.raises(GroupError, match="refused"):
        create_joint_group(api, "G", ["1"])
    assert "G" not in api.groups


def test_failed_assign_rolls_back_new_group():
    api = FakeWriteApi(fail_assign="5")
    with pytest.raises(GroupError, match="removed again"):
        create_joint_group(api, "G", ["1", "3", "5"])
    assert "G" not in api.groups and api.writes[-1] == ("delete_group", "G")


def test_status_change_is_flagged():
    api = FakeWriteApi()
    orig = api.assign_joint

    def assign(j, g):
        orig(j, g)
        api.status, api.locked = {"DC": 1}, False
    api.assign_joint = assign
    res = create_joint_group(api, "G", ["1"])
    assert any(n.startswith("WARNING") for n in res.notes)


def test_csi_source_delegates_and_refreshes_lists():
    from csibridge_extractor.tests.test_csi_source import FakeApi
    fake = FakeApi()
    w = FakeWriteApi(joints=fake.joint_names())
    for m in ("model_locked", "create_group", "assign_joint", "unassign_joint", "delete_group"):
        setattr(fake, m, getattr(w, m))
    fake.group_items = lambda g: w.groups[g] if g in w.groups else FakeApi.group_items(fake, g)
    fake.group_names = lambda: FakeApi.group_names(fake) + [g for g in w.groups if g not in ("ALL", "PIER")]
    src = CsiSource(api=fake)
    src.model_lists()
    res = src.edit_joint_group("create", "NEWG", ["5073", "6588"])
    assert res.added == ["5073", "6588"]
    assert src.model_lists().groups["NEWG"] == (set(), {"5073", "6588"})
    src.edit_joint_group("remove", "NEWG", ["5073"])
    assert src.model_lists().groups["NEWG"] == (set(), {"6588"})


def test_api_preview_and_edit_group():
    api = Api(fake=str(FIX))
    assert "error" in json.loads(api.preview_group("create", "X", 10, 12, 1))  # not connected
    api.connect()
    p = json.loads(api.preview_group("create", "Even", 10, 13, 2))
    assert p["added"] == ["10", "12"] and p["missing"] == []
    assert json.loads(api.preview_group("create", "Even", 10, 13, 1))["missing"] == ["13"]
    assert "error" in json.loads(api.preview_group("create", "Even", 10, 13, 0))
    assert "already exists" in json.loads(api.preview_group("create", "girdera", "", "", ""))["error"]
    assert "not joint-only" in json.loads(api.preview_group("add", "GirderA", 10, 11, 1))["error"]
    r = json.loads(api.edit_group("create", "Even", 10, 13, 2))
    assert r["joints"] == ["10", "12"] and "Even" in r["groups"]
    res = json.loads(api.resolve(json.dumps(dict(frames="", joints="", groups=["Even"], cases=["Str-I1"],
                                                 output_dir=None, name_pattern="x.xlsx"))))
    assert res["joints"] == ["10", "12"]
    assert "already exists" in json.loads(api.edit_group("create", "GirderA", 10, 11, 1))["error"]
    p = json.loads(api.preview_group("replace", "Even", 11, 12, 1))
    assert p["added"] == ["11"] and p["removed"] == ["10"]
    assert json.loads(api.edit_group("replace", "Even", 11, 12, 1))["joints"] == ["11", "12"]
    assert json.loads(api.edit_group("add", "Even", 10, 10, ""))["joints"] == ["10", "11", "12"]
    assert json.loads(api.edit_group("remove", "Even", 10, 11, 1))["joints"] == ["12"]
    assert "non-joint" in json.loads(api.edit_group("add", "GirderA", 10, 11, 1))["error"]
    assert json.loads(api.edit_group("create", "Empty", "", "", ""))["joints"] == []


def test_fake_source_file_untouched(tmp_path):
    before = FIX.read_text(encoding="utf-8")
    FakeSource(FIX).edit_joint_group("create", "X", ["10"])
    assert FIX.read_text(encoding="utf-8") == before
