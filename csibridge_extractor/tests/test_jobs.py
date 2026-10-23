import json

import pytest

from csibridge_extractor.extractor import jobs
from csibridge_extractor.extractor.jobs import Job


def full_job():
    return Job(frames="1301-1310", joints="10", groups=["G1"], cases=["DEAD", "STR-I"],
               tables={"frame": {"enabled": True, "modes": ["envelope", "correspondence"]},
                       "joint": {"enabled": True, "modes": ["envelope"]}},
               output_dir="C:/out", open_when_done=False)


def test_roundtrip(tmp_path):
    p = tmp_path / "j.json"
    j = full_job()
    jobs.save_job(j, p)
    j2 = jobs.load_job(p)
    assert j2 == j and j2.warnings == []
    assert json.loads(p.read_text(encoding="utf-8"))["version"] == 1


def test_unknown_keys_warn(tmp_path):
    p = tmp_path / "j.json"
    p.write_text(json.dumps({"frames": "1", "cases": ["A"], "bogus": 1}), encoding="utf-8")
    j = jobs.load_job(p)
    warnings = j.warnings
    assert j.version == 1 and j.frames == "1"
    assert len(warnings) == 1 and "bogus" in warnings[0]


def test_invalid_mode_raises(tmp_path):
    p = tmp_path / "j.json"
    p.write_text(json.dumps({"tables": {"frame": {"enabled": True, "modes": ["nope"]}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="tables.frame.modes"):
        jobs.load_job(p)


def test_validate_messages():
    assert jobs.validate(full_job()) == []
    errs = jobs.validate(Job())
    assert any("nothing to extract" in e.lower() for e in errs)
    assert any("no cases" in e.lower() for e in errs)
    j = full_job()
    j.tables["joint"]["modes"] = []
    errs = jobs.validate(j)
    assert len(errs) == 1 and "joint" in errs[0]


@pytest.mark.parametrize("raw,field", [
    ({"cases": "DEAD"}, "cases"),
    ({"tables": []}, "tables"),
    ({"tables": {"frame": "x"}}, "tables.frame"),
    ({"tables": {"frame": {"modes": "envelope"}}}, "modes"),
    ({"frames": 5}, "frames"),
])
def test_load_type_validation(tmp_path, raw, field):
    p = tmp_path / "j.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match=field):
        jobs.load_job(p)


def test_load_future_version_warns_and_dedupes(tmp_path):
    p = tmp_path / "j.json"
    p.write_text(json.dumps({"version": 2, "cases": ["A", "B", "A"],
                             "tables": {"frame": {"enabled": True, "modes": ["envelope", "envelope"]}}}),
                 encoding="utf-8")
    j = jobs.load_job(p)
    assert j.cases == ["A", "B"] and j.tables["frame"]["modes"] == ["envelope"]
    assert any("version" in w for w in j.warnings)


def test_output_format_roundtrip_and_validation(tmp_path):
    import json as _json
    from csibridge_extractor.extractor.jobs import Job, load_job, save_job
    p = tmp_path / "j.json"
    save_job(Job(frames="1", cases=["A"], output_format="csv"), p)
    assert load_job(p).output_format == "csv"
    d = _json.loads(p.read_text(encoding="utf-8"))
    del d["output_format"]
    p.write_text(_json.dumps(d), encoding="utf-8")
    assert load_job(p).output_format == "xlsx"
    d["output_format"] = "parquet"
    p.write_text(_json.dumps(d), encoding="utf-8")
    import pytest as _pytest
    with _pytest.raises(ValueError, match="output_format"):
        load_job(p)
