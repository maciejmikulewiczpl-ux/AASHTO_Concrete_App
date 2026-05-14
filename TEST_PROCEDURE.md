# Test Procedure — AASHTO Concrete App

This document describes the verification procedure to run after any
non-trivial change to the calculation engine, UI calculation hooks,
or the PT engine. It complements `CODE_PROTECTION.md` (which guards
against accidental deletions) by giving an objective regression
check.

## When to run

| Trigger | What to run |
|---|---|
| Quick sanity after small refactor | `python run_test_suite.py --quick` |
| Before committing changes to `calc_engine.py` or `pt_engine.py` | `python run_test_suite.py` |
| Before tagging a release / building a new `.exe` | `python run_test_suite.py --full` |
| Investigating a single regression | `pytest tests/<specific>.py -v` |

The orchestrator exits with code `0` only if every stage passes. CI
pipelines (if ever added) should treat a non-zero exit as a hard
failure.

## What's covered

### Dimension 1 — Section geometry
Rectangular (slim/deep, wide/shallow) and I-section (symmetric and
asymmetric flanges). 12 canonical sections in `tests/fixtures.py:SECTION_CATALOGUE`.

### Dimension 2 — Reinforcement layout
Bottom only, top + bottom symmetric, top + bottom asymmetric, and
multi-row bottom steel (`mr_rows_bot`).

### Dimension 3 — Prestressing
- Non-PT (RC, NP)
- CIP_PT with varying strand count, dp, and fpe

### Dimension 4 — Loading
12 canonical demand combinations in `DEMAND_CATALOGUE`:
- Pure sagging / pure hogging
- Axial compression + sag / + hog
- Axial tension + sag / + hog
- Pure compression / pure tension
- High shear without torsion
- High shear + torsion (above threshold)
- Small torsion (below threshold)
- Full 4-axis combination (P, M, V, T)

### Dimension 5 — Materials
- `fc` swept from 3 ksi to 10 ksi (covers β1 = 0.85 → 0.65 transition)
- `fy` = 60 and 80 ksi
- `λ` = 1.0 (normal-weight) and 0.75 (lightweight) — affects Vc

### Dimension 6 — Shear method
All three methods (Simplified θ=45°, General Procedure, Appendix B5)
are exercised on every shear test section. Method 1 Vc and Vs are
also pinned to closed-form hand calculations.

### Dimension 7 — Code edition / section class
- `AASHTO` × {RC, CIP_PT}
- `CA`     × {RC, NP, CIP_PT}

### Hand-calc benchmarks (`tests/test_handcalcs.py`)
Independent first-principles checks — these are the strongest guard
against silent formula drift:

| Reference | What it checks |
|---|---|
| Singly-reinforced rect Mn | Stress-block formula `a = As·fy / (α₁·fc·b)`, `Mn = As·fy·(d − a/2)` |
| Method 1 shear hand calc | `Vc = 0.0316 · β · λ · √fc · bv · dv` and `Vs = Av·fy·dv/s` |
| β1 vs fc | Linear transition from 0.85 (fc ≤ 4) to 0.65 (fc ≥ 8) |
| φ transitions | φ = 0.75 at ε_t ≤ ε_cl; φ = 0.9 at ε_t ≥ ε_tl |
| Mr = φ · Mn invariant | Every fc value |
| a = β1 · c invariant | Every fc value |
| Sag = Hog for symmetric | Doubly-symmetric rect |
| P-M curve consistency | Every point has Mr = φ·Mn and Pr = φ·Pn |
| Pn,max formula | AASHTO 10th Ed Eq. 5.6.4.4-3 (compression is **negative** in engine sign convention) |
| Tcr scales as √fc | Cracking torque (AASHTO 5.7.2.1-4) |
| PT raises Mcr but not Mn | Per AASHTO 5.7.2.2-1, fps at ultimate is fpe-independent |

### Invariants (`tests/test_invariants.py`)
- Symmetric section: sag Mr == hog Mr
- Asymmetric reinforcement: sag Mr ≠ hog Mr (and the strong side wins)
- More tension steel ⇒ higher Mn
- Deeper section ⇒ higher Mn
- Tighter stirrups ⇒ higher Vs
- Higher fc ⇒ no Vc decrease
- Multi-row demands processed independently
- `activeRow` index changes the reported `flexure` block
- **Report-key contract** pinned: every key the HTML report reads must
  exist in the result dict

### PT integration (`tests/test_pt_full.py`)
- PT increases Mn vs identical RC section
- More strands / deeper dp ⇒ higher Mn
- Higher fpe ⇒ higher Mcr (Mn is unaffected at ultimate)
- Per-row fpe override propagates when row is active
- Per-row dp override propagates
- Vp shear demand augments Vr
- `pt_engine.compute_full_profile` returns a complete profile with
  fpe-after-losses < fpj at every point

### Existing scripts (all repaired 2026-05-13, all run by the orchestrator)
The legacy standalone scripts have been brought back into the active
suite:

| Script | What it covers |
|---|---|
| `test_pt.py` | 22 pytest cases for `pt_engine` internals (parabola, friction, anchor set, ES, time-dependent) |
| `test_compliance.py` | Rect + T-section torsion + no-torsion smoke check |
| `test_fixes.py` | Regression tests for prior bug fixes |
| `test_multirow_pm.py` | Multi-row reinforcement P-M curve |
| `test_pm_curve.py` | Symmetric/asymmetric rect + I-section P-M endpoints |
| `test_pnmax.py` | Pn,max (Eq. 5.6.4.4-3) |
| `test_none_shear.py` | `shN=0`/`None` shear reinforcement handling |
| `adsec_comparison.py` | External-tool comparison (heavy — `--full` only) |
| `full_verification.py` | 20,436 cross-section consistency checks (heavy — `--full` only) |
| `deep_audit.py` | 31,158 detailed cross-section traces (heavy — `--full` only) |

### Sign conventions to know
Two engine-internal sign conventions surfaced during the May 2026
verification cleanup:

- **`row_results[i].Mr` is signed by Mu direction** —
  `Mr_signed = -Mr if Mu < 0 else Mr` ([calc_engine.py:2842](calc_engine.py#L2842)).
  Tests should compare `abs(r["Mr"])`.
- **`pm_curve` Mn/Mr are signed by `comp_face`** — points on the
  hog branch (`comp_face="bottom"`) have negative Mn/Mr.
  `get_mr_at_pu()` applies `abs()` when interpolating, so callers see
  unsigned magnitudes. Tests that walk the curve directly should
  compare magnitudes.

## File layout

```
tests/
  fixtures.py                   Shared make_inputs() and catalogues
  test_matrix_geometry.py       Dim 1 + 2 (section × reinforcement)
  test_matrix_loading.py        Dim 4 (full demand sweep)
  test_matrix_materials.py      Dim 5 + 7 (materials, code)
  test_shear_methods.py         Dim 6 (3-method cross-check)
  test_handcalcs.py             Golden hand-calc benchmarks
  test_invariants.py            Symmetry + report-key contract
  test_pt_full.py               PT engine integration
run_test_suite.py               Orchestrator (this is what you run)
TEST_PROCEDURE.md               You are here
```

## Adding a new test

1. If the new check fits an existing dimension, add it to the
   corresponding `tests/test_matrix_*.py` or `test_invariants.py`.
2. If it's a brand-new dimension, create `tests/test_matrix_<name>.py`
   and register it in `run_test_suite.py:PYTEST_STAGES`.
3. Hand-calc benchmarks (where you compute the expected value
   independently in the test body) always belong in
   `tests/test_handcalcs.py` — those are the most valuable defenses
   against silent formula drift, and grouping them helps reviewers.
4. Use `tests/fixtures.py` helpers (`make_inputs`, `demand`,
   `SECTION_CATALOGUE`, `DEMAND_CATALOGUE`) rather than rebuilding
   input dicts from scratch.

## Interpreting failures

| Failure type | What it usually means |
|---|---|
| `test_handcalcs.py` test fails | A formula in `calc_engine.py` changed coefficients — likely regression |
| `test_invariants.py` symmetry test fails | Sign error or sag/hog code path divergence |
| `test_invariants.py` report-key test fails | Result dict lost a key the HTML report needs — UI will break |
| `test_matrix_geometry.py` parametric fail | One section variant broke; check `secType`, flange handling |
| `test_matrix_loading.py` parametric fail | One load combination broke; check sign convention |
| `test_pt_full.py` fail | PT input flow regressed (per-row override, Vp, fpe→Mcr) |
| B5 convergence warning | Known iteration sensitivity; not a hard failure |

## Tolerance philosophy

- Engine internal consistency (`Mr = φ·Mn`, `a = β1·c`): tight,
  `rel_tol = 1e-3`.
- Hand-calc vs engine: `rel_tol = 0.005-0.02`, accommodating small
  effects (cover, β1 lookup interpolation).
- Cross-section monotonicity (more steel ⇒ higher Mn): strict `>`
  with a small absolute slack (1 kip·in) to absorb floating-point
  jitter.

## See also

- `CODE_PROTECTION.md` — pre-commit hook + critical-file deletion guards
- `verification_report.txt` / `verification_report_final.txt` — prior
  detailed verification traces (fy_long vs fy_trans audit)
- `FIXES_SUMMARY.md` — log of previous fixes verified by the suite
