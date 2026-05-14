# GitHub Copilot — project instructions

This file is auto-loaded by GitHub Copilot. The same content is mirrored in `CLAUDE.md` at the repo root for Claude Code.

## ⚠️ IN-PROGRESS WORK — read `AUDIT_2026_05_13_IN_PROGRESS.md` FIRST

There is an audit-and-fix session in progress as of 2026-05-13. A consolidated decision sheet has been agreed with the user but **no implementation has happened yet**. The user is reviewing the decisions and will resume tomorrow.

Before doing anything in this repo:
1. Open `AUDIT_2026_05_13_IN_PROGRESS.md` and read it through.
2. Understand which decisions are pending (D1–D16) and which questions are parked (Q9 Tcr/Ao for I-section, Q10 B5 tables).
3. Do NOT start implementing those decisions until the user confirms.
4. Do NOT re-investigate the questions that already have decisions — the answers are in the audit doc.

If the audit file is gone, it means the work has been completed and committed — check `FIXES_SUMMARY.md` for the resolution record.


## Project at a glance

AASHTO LRFD reinforced/prestressed concrete section design app. Python calculation engine (`calc_engine.py`, `pt_engine.py`) + HTML/JS frontend (`index.html`) bridged via pywebview (`api.py`, `app.py`). Units throughout: **kip, inch, ksi**.

Section types modelled: `RECTANGULAR` and `T-SECTION` (I-section). **Box sections are NOT modelled.**

## Before you suggest any change

1. **Read `CODE_PROTECTION.md`** — covers the code-safety policy and the anti-regression list. Pay particular attention to the "Removed checks — DO NOT re-add" section.
2. **Read `FIXES_SUMMARY.md`** — contains the regression-history record. The same anti-pattern has come back twice; do not be the third.
3. **Read `TEST_PROCEDURE.md`** — describes the verification suite and how to run it.

## Citing AASHTO / ACI equations — STRICT RULE

**Do not fabricate code citations.** Every AASHTO/ACI/AISC equation reference you add (in code, comments, docs, HTML labels) must be one you have actually verified against a published edition.

- **You do not have the AASHTO LRFD text in your training data with sufficient fidelity to cite specific equation numbers from memory.** Do not pattern-complete equation numbers (if `-1` and `-2` exist, do NOT assume `-3` exists).
- **Do not cross-pollinate codes.** ACI 318 and AASHTO LRFD use similar formulas with different coefficients and scope. A formula that "looks right" is not a justification for citing AASHTO.
- **An HTML label like `(5.7.3.6.3)` is a section number, not an equation citation.** Do not treat its existence as evidence that a specific equation exists.
- **When uncertain, flag uncertainty** — write `# AASHTO 5.7.3.6 region, exact equation number unverified` rather than inventing a number to look authoritative.

This rule was added after a prior AI session fabricated a citation to a non-existent "AASHTO Eq. 5.7.3.6.3-3" in 2026-05. See `CODE_PROTECTION.md` § "Verifiable-citations rule" for the full policy.

## Critical anti-regressions (READ THIS BEFORE EDITING calc_engine.py)

If you find yourself "fixing missing HTML report keys" or "implementing missing AASHTO checks" in the torsion section, **STOP** and re-read `CODE_PROTECTION.md` § "Removed checks — DO NOT re-add". Specifically:

- **Do NOT re-add `Al_tors`, `Al_min`, `Al_gov`** or any implementation of AASHTO **Eq. 5.7.3.6.3-2** (longitudinal A_l for torsion). That equation applies to **box sections only**. This app does not model box sections. These keys have been removed twice already. The HTML report displays an I-section warning instead.
- **Do NOT invent a "5.7.3.6.3-3" minimum-A_l equation.** No such equation exists in current AASHTO LRFD. The formula `5·√fc·Acp/fy − (At_min/s)·ph` is an ACI 318 holdover; do not import ACI formulas into this AASHTO app.

The combined longitudinal check that IS correct and stays:
- AASHTO **Eq. 5.7.3.6.3-1** (`long_dem_comb`, `long_cap_val`, `long_comb_ok` with `breakdown_long_comb` for the equation breakdown).

Pinning test: `tests/test_invariants.py::test_al_keys_removed_from_torsion` — do not remove or weaken.

## Required workflow for app-code changes

App code = `calc_engine.py`, `pt_engine.py`, `api.py`, `app.py`, `index.html`, and any `.bat` build script.

1. **Notify the user before any app-code edit**, even one-liners. The user has explicitly stated this is required.
2. **Do not delete >5 lines from `calc_engine.py`, `index.html`, or `api.py`** — the pre-commit hook will block you (and it's correct to do so).
3. **Add new tests for any behaviour change** under `tests/`. Pin the contract.
4. **Run the full test suite before saying you're done**:
   ```
   python run_test_suite.py --full
   ```
   All 17 stages should PASS. If any fail, do not claim the task is complete.

## Sign conventions you need to know

The engine uses several intentional sign conventions. Do **not** "fix" them.

- `row_results[i].Mr` is signed by demand moment direction: `Mr_signed = -Mr if Mu < 0 else Mr` (see `calc_engine.py:2842`). Compare magnitudes (`abs(...)`) in tests.
- P-M curve points use Mn>0 for `comp_face='top'` (sagging) and Mn<0 for `comp_face='bottom'` (hogging). `get_mr_at_pu()` applies `abs()` when interpolating, so external callers see magnitudes only.
- `Pn` in the P-M curve: compression is **negative**, tension is positive. `Pn_max` (compression capacity) is therefore `min(p["Pn"] for p in pm)`.

## Tests

Authoritative test suite under `tests/` (pytest, 230+ cases). Legacy verification scripts at project root remain in active rotation. See `TEST_PROCEDURE.md` for the full matrix.

Quick commands:
- `pytest tests/ -q` — fast sanity (~1.5s)
- `python run_test_suite.py` — default suite (lightweight scripts + pytest)
- `python run_test_suite.py --full` — includes heavy verification scripts

## When in doubt

- Check `git log -S "<symbol>"` to see if something was previously removed.
- Read the surrounding code before adding "missing" features.
- Ask the user before adding any AASHTO check the engine appears to be missing — it may be missing on purpose.
