import json
import threading
from pathlib import Path

import openpyxl
import pytest

from csibridge_extractor.extractor import cli
from csibridge_extractor.extractor.jobs import Job, save_job
from csibridge_extractor.extractor.runner import run_job
from csibridge_extractor.extractor.source import FakeSource, SourceError
from csibridge_extractor.extractor.writer import OutputLockedError

FIX = Path(__file__).parent / "fixtures" / "fake_model.json"
EN = "–"


def _job(**kw):
    base = dict(frames="1227", joints="10, 11", cases=["Str-I1", "Str-I2"],
                tables={"frame": {"enabled": True, "modes": ["envelope", "correspondence"]},
                        "joint": {"enabled": True, "modes": ["envelope"]}})
    base.update(kw)
    return Job(**base)


def _fixture_count(table, mode, cases, objs):
    d = json.loads(FIX.read_text(encoding="utf-8"))
    ci = 2 if table == "frame" else 1
    return sum(1 for r in d["tables"][table][mode] if r[ci] in cases and r[0] in objs)


def _run_info(path):
    ws = openpyxl.load_workbook(path)["Run info"]
    return [(r[0], r[1]) for r in ws.iter_rows(values_only=True)]


def test_end_to_end_fake(tmp_path):
    out = tmp_path / "o.xlsx"
    src = FakeSource(FIX)
    res = run_job(_job(), src, str(out))
    assert res.complete and src.closed
    assert res.rows == {
        f"Frame Forces {EN} Envelope": _fixture_count("frame", "envelope", {"Str-I1", "Str-I2"}, {"1227"}),
        f"Frame Forces {EN} Corresp.": _fixture_count("frame", "correspondence", {"Str-I1", "Str-I2"}, {"1227"}),
        f"Joint Reactions {EN} Envelope": _fixture_count("joint", "envelope", {"Str-I1", "Str-I2"}, {"10", "11"}),
    }
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["Run info", *res.rows]
    for name, n in res.rows.items():
        assert wb[name].max_row == n + 2
    info = dict(_run_info(out))
    assert info["complete"] == "True" and "1227" in info["Job"]


def test_rerun_reports_missing_targets_and_cases(tmp_path):
    job = _job(frames="1227 9999", joints="10", groups=["Nope"], cases=["Str-I1", "Gone", "Str-III"],
               tables={"frame": {"enabled": True, "modes": ["envelope"]},
                       "joint": {"enabled": False, "modes": ["envelope"]}})
    res = run_job(job, FakeSource(FIX), str(tmp_path / "o.xlsx"))
    text = "\n".join(res.warnings)
    assert "9999" in text and "Nope" in text and "Gone" in text and "Str-III" in text
    assert res.complete
    warns = [v for k, v in _run_info(tmp_path / "o.xlsx") if k == "Warning"]
    assert any("9999" in w for w in warns) and any("Str-III" in w for w in warns)


def test_locked_output_fails_fast(tmp_path):
    calls = []

    class Spy(FakeSource):
        def __getattribute__(self, name):
            if name in ("model_info", "list_cases", "model_lists", "units_row", "iter_rows", "notes"):
                calls.append(name)
            return super().__getattribute__(name)

    src = Spy(FIX)
    # unwritable target (folder missing) is rejected by the writer's check_writable
    with pytest.raises(OutputLockedError):
        run_job(_job(), src, str(tmp_path / "missing" / "o.xlsx"))
    assert calls == [] and src.closed


def test_cancel_writes_incomplete_workbook(tmp_path):
    cancel = threading.Event()

    class Cancelling(FakeSource):
        def iter_rows(self, table, mode, cases, objects):
            for r in super().iter_rows(table, mode, cases, objects):
                yield r
                cancel.set()

    src = Cancelling(FIX)
    res = run_job(_job(), src, str(tmp_path / "o.xlsx"), cancel=cancel)
    assert not res.complete and src.closed
    info = dict(_run_info(tmp_path / "o.xlsx"))
    assert info["complete"] == "False" and info["Status"] == "INCOMPLETE"
    assert 0 < sum(res.rows.values()) < 8


def test_source_error_on_one_object_continues(tmp_path):
    class Flaky(FakeSource):
        def iter_rows(self, table, mode, cases, objects):
            if objects == ["10"]:
                raise SourceError("boom")
            return super().iter_rows(table, mode, cases, objects)

    job = _job(tables={"frame": {"enabled": False, "modes": ["envelope"]},
                       "joint": {"enabled": True, "modes": ["envelope"]}})
    res = run_job(job, Flaky(FIX), str(tmp_path / "o.xlsx"))
    assert res.complete
    assert res.rows[f"Joint Reactions {EN} Envelope"] == _fixture_count("joint", "envelope",
                                                                         {"Str-I1", "Str-I2"}, {"11"})
    assert any("object 10" in w and "boom" in w for w in res.warnings)


def test_default_out_path(tmp_path):
    job = _job(output_dir=str(tmp_path), name_pattern="{model}_x_{stamp}.xlsx")
    res = run_job(job, FakeSource(FIX))
    p = Path(res.path)
    assert p.parent == tmp_path and p.name.startswith("fake_bridge_x_") and p.exists()


def test_cli_exit_codes(tmp_path, capsys):
    jp = tmp_path / "j.json"
    out = str(tmp_path / "o.xlsx")
    save_job(_job(), jp)
    # fake fixture has a case without results only when requested -> clean run is 0
    assert cli.main(["run", str(jp), "--out", out, "--fake", str(FIX)]) == 0
    save_job(_job(frames="1227 9999"), jp)
    assert cli.main(["run", str(jp), "--out", out, "--fake", str(FIX)]) == 2
    save_job(_job(cases=["Str-III"]), jp)
    assert cli.main(["run", str(jp), "--out", out, "--fake", str(FIX)]) == 1
    save_job(_job(), jp)
    assert cli.main(["run", str(jp), "--out", str(tmp_path / "nodir" / "o.xlsx"), "--fake", str(FIX)]) == 1
    assert cli.main(["run", str(jp), "--out", out]) == 1
    assert "not available yet" in capsys.readouterr().err
