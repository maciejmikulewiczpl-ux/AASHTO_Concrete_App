"""Regenerate the rectangular / I-section golden baseline.

Only run this when a rect/I behaviour change is INTENDED and reviewed:
    python tests/golden/make_rect_i_baseline.py
"""
import copy
import hashlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, os.pardir, os.pardir)))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, os.pardir)))

from calc_engine import calculate_all  # noqa: E402
from tests.fixtures import SECTION_CATALOGUE, DEMAND_CATALOGUE, make_inputs  # noqa: E402

BASELINE_PATH = os.path.join(HERE, "rect_i_baseline.json")

EXTRA_VARIANTS = {
    "multirow": dict(
        mr_rows_bot=[{"d": 33.0, "As": 3.16}, {"d": 30.0, "As": 2.37}],
        mr_rows_top=[{"d": 2.5, "As": 1.58}],
    ),
    "caltrans_lw": dict(codeEdition="CA", lam=0.75, fc=6),
    "crack_actual": dict(crack_mode="actual"),
    "torsion_add": dict(at_add_bar_N=5, s_at_add=6),
}


def normalize(obj):
    if isinstance(obj, dict):
        return {str(k): normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [normalize(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj):
            return "NaN"
        if math.isinf(obj):
            return "Inf" if obj > 0 else "-Inf"
        return obj
    if isinstance(obj, (int, str, bool)) or obj is None:
        return obj
    return repr(obj)


def build_cases():
    demands = list(DEMAND_CATALOGUE.values())
    cases = {}
    for sec_name, sec in SECTION_CATALOGUE.items():
        kw = {k: v for k, v in copy.deepcopy(sec).items() if k != "desc"}
        variants = {"base": {}}
        variants.update(EXTRA_VARIANTS)
        for var_name, var_kw in variants.items():
            merged = dict(kw)
            merged.update(var_kw)
            for active in (0, 3, 9):
                key = f"{sec_name}|{var_name}|active{active}"
                cases[key] = (make_inputs(**merged), demands, active)
    return cases


def compute_all():
    out = {}
    for key, (raw, dems, active) in build_cases().items():
        res = calculate_all(copy.deepcopy(raw), copy.deepcopy(dems), active)
        out[key] = normalize(res)
    return out


def digest(result):
    return hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()


def compute_digests():
    return {k: digest(v) for k, v in compute_all().items()}


if __name__ == "__main__":
    data = compute_digests()
    with open(BASELINE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, sort_keys=True)
    print(f"Wrote {len(data)} cases to {BASELINE_PATH}")
