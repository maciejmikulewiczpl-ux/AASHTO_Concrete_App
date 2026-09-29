"""Pin: rectangular and I-section results must stay identical to the golden
baseline captured before the CIRCULAR section was added (SHA-256 per case).

To see what changed on failure: `git stash`, dump `compute_all()` for the
failing key, `git stash pop`, dump again and diff.
Regenerate only for an intended, reviewed rect/I change:
    python tests/golden/make_rect_i_baseline.py
"""
import json
import os

import pytest

from tests.golden.make_rect_i_baseline import BASELINE_PATH, compute_digests


@pytest.mark.skipif(not os.path.exists(BASELINE_PATH), reason="baseline not generated")
def test_rect_i_results_unchanged():
    with open(BASELINE_PATH, encoding="utf-8") as f:
        baseline = json.load(f)
    current = compute_digests()
    assert set(current) == set(baseline)
    changed = sorted(k for k in baseline if baseline[k] != current[k])
    assert not changed, f"{len(changed)} rect/I cases changed, e.g. {changed[:10]}"
