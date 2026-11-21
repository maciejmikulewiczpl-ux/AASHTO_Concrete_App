"""Helpers for running tests/batch_parity_harness.js (the app's own JS) from pytest."""
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from batch.form import FORM_DEFAULTS

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "batch_parity_harness.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")

KIP_IN = {"force": "kip", "length": "in"}

# (case id, form overrides, units)
CASES = [
    ("rect_defaults", {}, KIP_IN),
    ("tsection_flanges", {"sectionType": "T-SECTION", "b_flange": "48", "b_web": "14", "h_total": "54",
                          "hf_top": "7", "hf_bot": "9", "bot_bar": "10", "n_bars_bot": "6"}, KIP_IN),
    ("circ_hoop_2rings", {"sectionType": "CIRCULAR", "circ_D": "60", "circ_bar1": "11", "circ_n1": "20",
                          "circ_bundle1": "2", "circ_ring2": True, "circ_bar2": "9", "circ_n2": "10",
                          "circ_Dr2": "40", "circ_tie_legs": "2", "shear_bar": "5", "shear_s": "6"}, KIP_IN),
    ("circ_spiral", {"sectionType": "CIRCULAR", "circ_trans_type": "spiral", "circ_hoop_closure": "lap",
                     "shear_s": "3"}, KIP_IN),
    ("slab_spacing", {"memberType": "SLAB", "b_flange": "12", "h_total": "9", "bar_mode_top": "spacing",
                      "n_bars_top": "12", "top_bar": "5", "bar_mode_bot": "spacing", "n_bars_bot": "8",
                      "bot_bar": "6", "shear_bar": "0"}, KIP_IN),
    ("stirrup_none", {"shear_bar": "0", "shear_legs": "4", "shear_s": "9"}, KIP_IN),
    ("units_kip_ft", {"b_flange": "1.5", "h_total": "3", "b_web": "1", "hf_top": "0.5", "hf_bot": "0.75",
                      "cover": "0.1667", "fc": "720", "fy": "8640", "fy_trans": "8640", "Es": "4176000",
                      "shear_s": "0.5", "ag": "0.0625"}, {"force": "kip", "length": "ft"}),
    ("units_lbf_in", {"fc": "5000", "fy": "60000", "fy_trans": "60000", "Es": "29000000",
                      "fpu": "270000", "Ept": "28500000"}, {"force": "lbf", "length": "in"}),
    ("high_fc_fy80", {"fc": "8", "astm_spec": "A615_80", "fy": "80", "fy_trans": "80"}, KIP_IN),
    ("factor_override", {"phi_f_f_ovr": True, "phi_f_f_ovr_val": "0.85", "gamma3_f_ovr": True,
                         "gamma3_f_ovr_val": "0.75"}, KIP_IN),
    ("crack_mode_other", {"crack_mode": "uncapped"}, KIP_IN),
    ("torsion_add_bar", {"at_add_bar": "5", "at_add_s": "6"}, KIP_IN),
    ("overrides_wc_Ec_fy", {"wc_ovr": True, "wc": "0.15", "Ec_ovr": True, "Ec": "4500", "fy_ovr": True,
                            "fy": "65", "K1": "0.9"}, KIP_IN),
]


def full_form(overrides):
    f = dict(FORM_DEFAULTS)
    f.update(overrides)
    return f


def run_harness(cases):
    """cases: list of {form, units, state?} -> list of {gather, fromState?} from the app's JS."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "cases.json"
        p.write_text(json.dumps(cases), encoding="utf-8")
        out = subprocess.run([NODE, str(HARNESS), str(ROOT / "index.html"), str(p)],
                             capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def normalise(v):
    """JSON view of a value: NaN/inf -> None (as JSON.stringify), tuples -> lists."""
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, dict):
        return {k: normalise(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [normalise(x) for x in v]
    return v


def assert_same(js, py, label):
    js, py = normalise(js), normalise(py)
    assert set(js) == set(py), (label, sorted(set(js) ^ set(py)))
    for k in js:
        a, b = js[k], py[k]
        if isinstance(a, dict) and isinstance(b, dict):
            assert_same(a, b, f"{label}.{k}")
        elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
            assert b == pytest.approx(a, rel=1e-12, abs=1e-12), (label, k, a, b)
        else:
            assert a == b, (label, k, a, b)
