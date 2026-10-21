from csibridge_extractor.extractor import targets
from csibridge_extractor.extractor.targets import ModelLists, RangeToken


def model():
    return ModelLists(
        frames={"1301", "1302", "1305", "1310", "1227-1", "A7"},
        joints={"10", "11", "12"},
        groups={"G1": ({"1301", "1999"}, {"12"}), "G2": (set(), set())},
    )


def test_parse_mixed_separators():
    assert targets.parse_labels("1, 2\n3  4,,5\t6") == ["1", "2", "3", "4", "5", "6"]


def test_range_vs_literal():
    toks = targets.parse_labels("1301-1310 1227-1")
    assert toks == [RangeToken(1301, 1310), "1227-1"]


def test_resolve_ranges_only_existing():
    r = targets.resolve("1301-1310", "", [], model())
    assert r.frames == ["1301", "1302", "1305", "1310"]
    r = targets.resolve("2000-2010", "10-11", [], model())
    assert r.frames == [] and r.empty_ranges == ["2000-2010"]
    assert r.joints == ["10", "11"]


def test_resolve_groups_and_missing():
    r = targets.resolve("1301 nope 1227-1", "10 99", ["G1", "G2", "GX"], model())
    assert r.frames == ["1301", "1227-1"]
    assert r.group_members_not_in_model == ["G1:1999"]
    assert r.joints == ["10", "12"]
    assert r.missing_frames == ["nope"]
    assert r.missing_joints == ["99"]
    assert r.missing_groups == ["GX"]


def test_dedupe_keeps_order():
    assert targets.parse_labels("b a b a c") == ["b", "a", "c"]
    r = targets.resolve("1305 1301-1302 1305", "", ["G1"], model())
    assert r.frames == ["1305", "1301", "1302"]


def test_ambiguous_token_extracts_both():
    m = ModelLists(frames={"5", "6", "7", "5-7"}, joints=set())
    r = targets.resolve("5-7", "", [], m)
    assert r.frames == ["5-7", "5", "6", "7"] and r.ambiguous_tokens == ["5-7"]
    assert r.empty_ranges == []
    m2 = ModelLists(frames={"5-7"}, joints=set())
    r2 = targets.resolve("5-7", "", [], m2)
    assert r2.frames == ["5-7"] and r2.ambiguous_tokens == ["5-7"] and r2.empty_ranges == []


def test_non_ascii_digits_not_ranges():
    assert targets.parse_labels("١-٣") == ["١-٣"]
