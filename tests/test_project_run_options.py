"""Project file stores and restores the run options (shear capacity method for D/C, M-phi options).

The batch runner writes project.runOptions (batch/project.py); the app must save the same shape and
restore it on load. Old project files without runOptions must load unchanged.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
SRC = "\n".join(re.findall(r"<script>([\s\S]*?)</script>", HTML))
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _block(start: str) -> str:
    i = SRC.index(start)
    j = SRC.index("{", i)
    depth = 0
    for k in range(j, len(SRC)):
        if SRC[k] == "{":
            depth += 1
        elif SRC[k] == "}":
            depth -= 1
            if not depth:
                return SRC[i:k + 1]
    raise AssertionError(start)


@pytest.mark.parametrize("fn", ["saveProject", "saveProjectQuick"])
def test_save_paths_write_run_options(fn):
    assert re.search(r"runOptions\s*[:=]\s*getRunOptions\(\)", _block(f"function {fn}("))


def test_load_restores_run_options():
    assert "applyRunOptions(data.runOptions)" in _block("function applyProjectData(")


def test_get_run_options_shape_matches_batch_project():
    body = _block("function getRunOptions(")
    for k in ("shearCapacityMethod", "mphi_materials", "mphi_exp_c", "mphi_exp_s",
              "expected_concrete", "expected_steel", "model"):
        assert k in body


HARNESS = r"""
'use strict';
const code = require('fs').readFileSync(process.argv[2], 'utf8');
const scenarios = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const out = [];
for (const sc of scenarios) {
  const els = {
    mphi_materials: {value: 'service', disabled: false},
    mphi_exp_c: {checked: false, disabled: false},
    mphi_exp_s: {checked: false, disabled: false},
    mphi_point: {value: 'yield'},
  };
  if (sc.withSelect) els.shearCapSelect = {value: 'gp'};
  global.document = {getElementById: id => els[id] || null};
  let runs = 0;
  const f = new Function('runMphiStub', 'mphiResInit',
    'let shearCapacityMethod="gp"; let _mphiRes=mphiResInit; function runMphi(){ runMphiStub(); }\n' + code +
    '\nreturn {apply: applyRunOptions, get: getRunOptions, scm: () => shearCapacityMethod};');
  const api = f(() => { runs++; }, sc.mphiRes ? {} : null);
  api.apply(sc.runOptions);
  out.push({scm: api.scm(), model: els.mphi_materials.value, c: els.mphi_exp_c.checked,
            s: els.mphi_exp_s.checked, cDisabled: els.mphi_exp_c.disabled,
            select: els.shearCapSelect ? els.shearCapSelect.value : null, runs, saved: api.get()});
}
console.log(JSON.stringify(out));
"""


def _run(scenarios, tmp_path):
    code = ";\n".join(_block(f"function {f}(") for f in ("mphiModelChanged", "getRunOptions", "applyRunOptions"))
    (tmp_path / "code.js").write_text(code, encoding="utf-8")
    (tmp_path / "sc.json").write_text(json.dumps(scenarios), encoding="utf-8")
    (tmp_path / "h.js").write_text(HARNESS, encoding="utf-8")
    p = subprocess.run(["node", str(tmp_path / "h.js"), str(tmp_path / "code.js"), str(tmp_path / "sc.json")],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


@needs_node
def test_restore_and_round_trip(tmp_path):
    ro = {"shearCapacityMethod": "b5", "mphi": {"model": "sgs", "expected_concrete": True, "expected_steel": True}}
    r = _run([{"runOptions": ro, "withSelect": True}], tmp_path)[0]
    assert (r["scm"], r["select"], r["model"], r["c"], r["s"], r["cDisabled"]) == ("b5", "b5", "sgs", True, True, True)
    assert r["runs"] == 0  # no M-phi result yet -> nothing re-run
    assert r["saved"] == ro


@needs_node
def test_old_file_without_run_options_unchanged(tmp_path):
    r = _run([{"runOptions": None}], tmp_path)[0]
    assert (r["scm"], r["model"], r["c"], r["s"]) == ("gp", "service", False, False)
    assert r["saved"] == {"shearCapacityMethod": "gp",
                          "mphi": {"model": "service", "expected_concrete": False, "expected_steel": False}}


@needs_node
def test_invalid_values_ignored(tmp_path):
    ro = {"shearCapacityMethod": "xyz", "mphi": {"model": "bogus", "expected_concrete": "yes", "expected_steel": 1}}
    r = _run([{"runOptions": ro}], tmp_path)[0]
    assert (r["scm"], r["model"], r["c"], r["s"]) == ("gp", "service", False, False)


@needs_node
def test_rerun_only_when_result_exists(tmp_path):
    ro = {"shearCapacityMethod": "simp", "mphi": {"model": "confined", "expected_concrete": True, "expected_steel": False}}
    r = _run([{"runOptions": ro, "mphiRes": True}], tmp_path)[0]
    assert (r["scm"], r["model"], r["c"], r["s"], r["cDisabled"]) == ("simp", "confined", True, False, False)
    assert r["runs"] == 1
