"""batch_runner.py CLI (frozen to AASHTO_Batch.exe)."""
import subprocess
import sys
from pathlib import Path

from tests.test_batch_runner import CIRC, RECT, row, write_job

ROOT = Path(__file__).resolve().parents[1]


def _run(*args):
    return subprocess.run([sys.executable, str(ROOT / "batch_runner.py"), *args],
                          capture_output=True, text=True, timeout=300, cwd=str(ROOT))


def _summary(folder):
    lines = (folder / "_batch_summary.txt").read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def test_cli_runs_in_dir_with_spaces_and_unicode(tmp_path):
    job = tmp_path / "My Jobs" / "Łódź beam"
    job.mkdir(parents=True)
    write_job(job, [row(**RECT), row(**CIRC)])
    wb = job / "Bridge Ł-1.xlsm"
    p = _run("--dir", str(job), "--workbook", str(wb))
    assert p.returncode == 0, p.stderr
    assert (job / "_batch_results.tsv").exists()
    s = _summary(job)
    assert s["status"] == "done" and s["sections"] == "2" and s["rows"] == "2" and s["errors"] == "0"
    assert s["project"] == str(job / "Bridge Ł-1.aashto.json") and Path(s["project"]).exists()


def test_cli_missing_inputs_exit_2(tmp_path):
    p = _run("--dir", str(tmp_path))
    assert p.returncode == 2 and "_batch_inputs.tsv" in p.stderr
    s = _summary(tmp_path)
    assert s["status"] == "fatal" and "_batch_inputs.tsv" in s["message"]


def test_cli_bad_setting_is_fatal_with_message(tmp_path):
    write_job(tmp_path, [row(**RECT)], {"shear_method": "xyz"})
    p = _run("--dir", str(tmp_path))
    assert p.returncode == 2 and "Shear capacity for D/C" in _summary(tmp_path)["message"]


def test_cli_version():
    p = _run("--version")
    assert p.returncode == 0 and p.stdout.startswith("AASHTO_Batch ")
