from pathlib import Path

import pytest

from csibridge_extractor.extractor.source import TABLE_COLUMNS, FakeSource, SourceError

FIXTURE = Path(__file__).parent / "fixtures" / "fake_model.json"
CONCRETE = Path(__file__).resolve().parents[2] / "tests" / "fixtures_csi"


def _parse_txt(path):
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        c = ln.split("\t")
        if len(c) == 13 and c[0] == "1227":
            rows.append((c[0], float(c[1]), c[2], c[3], c[4], *[float(x) for x in c[5:11]], c[11], float(c[12])))
    return rows


@pytest.fixture
def src():
    s = FakeSource(FIXTURE)
    yield s
    s.close()


@pytest.mark.skipif(not CONCRETE.exists(), reason="concrete-app fixtures not present")
def test_fake_rows_match_concrete_fixtures(src):
    env = _parse_txt(CONCRETE / "frame1227_strI1.txt")
    cor = _parse_txt(CONCRETE / "frame1227_strI1_concurrent.txt")
    assert len(env) == 8 and len(cor) == 8
    assert list(src.iter_rows("frame", "envelope", ["Str-I1"], ["1227"])) == env
    assert list(src.iter_rows("frame", "correspondence", ["Str-I1"], ["1227"])) == cor


def test_filters_by_case_and_object(src):
    assert list(src.iter_rows("frame", "envelope", ["Other"], ["1227"])) == []
    assert list(src.iter_rows("frame", "envelope", ["Str-I1"], ["9999"])) == []
    rows = list(src.iter_rows("joint", "envelope", ["Str-I1"], ["11"]))
    assert rows and all(r[0] == "11" and r[1] == "Str-I1" for r in rows)
    with pytest.raises(SourceError):
        list(src.iter_rows("frame", "bogus", ["Str-I1"], ["1227"]))


def test_units_row_lengths(src):
    for t in ("frame", "joint"):
        assert len(src.units_row(t)) == len(TABLE_COLUMNS[t])
    assert len(TABLE_COLUMNS["frame"]) == 13 and len(TABLE_COLUMNS["joint"]) == 10
    assert src.model_info().units == {"force": "Kip", "length": "ft"}
    for t in ("frame", "joint"):
        for mode in ("envelope", "correspondence"):
            for r in src.iter_rows(t, mode, [c.name for c in src.list_cases()], sorted(src.model_lists().frames | src.model_lists().joints)):
                assert len(r) == len(TABLE_COLUMNS[t])


def test_case_without_results_flagged(src):
    cases = {c.name: c for c in src.list_cases()}
    assert cases["Str-III"].has_results is False
    assert cases["Str-I1"].has_results is True and cases["Str-I1"].kind == "combo"
    ml = src.model_lists()
    assert set(ml.groups) == {"GirderA", "Piers"}
    assert ml.groups["GirderA"] == ({"1227", "1301"}, {"10", "11"})


def test_close_idempotent(src):
    src.close()
    src.close()
