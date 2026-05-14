"""
One-shot test orchestrator.

Runs the full verification battery -- new pytest suite in tests/ plus
the existing standalone scripts at the project root -- and prints a
single summary table.

Usage:
    python run_test_suite.py           # full suite
    python run_test_suite.py --quick   # skip the slowest scripts

Exit code is 0 only if every stage passes.
"""
import argparse
import os
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Stage 1: pytest discovery in tests/  (the new structured suite)
PYTEST_STAGES = [
    ("Pytest:  geometry matrix",         ["tests/test_matrix_geometry.py"]),
    ("Pytest:  loading matrix",          ["tests/test_matrix_loading.py"]),
    ("Pytest:  material matrix",         ["tests/test_matrix_materials.py"]),
    ("Pytest:  shear methods",           ["tests/test_shear_methods.py"]),
    ("Pytest:  hand-calc benchmarks",    ["tests/test_handcalcs.py"]),
    ("Pytest:  invariants & report keys", ["tests/test_invariants.py"]),
    ("Pytest:  PT integration",          ["tests/test_pt_full.py"]),
    ("Pytest:  existing test_pt.py",     ["test_pt.py"]),
]

# Stage 2: existing standalone scripts at project root (kept for back-compat).
# These print their own output; we just check the exit code.
STANDALONE_SCRIPTS = [
    ("Script:  test_compliance.py",   "test_compliance.py"),
    ("Script:  test_fixes.py",        "test_fixes.py"),
    ("Script:  test_multirow_pm.py",  "test_multirow_pm.py"),
    ("Script:  test_pm_curve.py",     "test_pm_curve.py"),
    ("Script:  test_pnmax.py",        "test_pnmax.py"),
    ("Script:  test_none_shear.py",   "test_none_shear.py"),
]

# All previously known-broken scripts were repaired on 2026-05-13.
# Kept as an empty dict so future regressions can be parked here if
# needed without touching the orchestrator structure.
KNOWN_BROKEN = {}

# Heavy / optional scripts: run only when --full is given.
HEAVY_SCRIPTS = [
    ("Script:  adsec_comparison.py",  "adsec_comparison.py"),
    ("Script:  full_verification.py", "full_verification.py"),
    ("Script:  deep_audit.py",        "deep_audit.py"),
]


def run(label, cmd):
    print(f"\n{'=' * 78}")
    print(f"  {label}")
    print(f"  $ {' '.join(cmd)}")
    print('=' * 78)
    t0 = time.time()
    # Force UTF-8 stdout for the child process so legacy scripts that
    # print Unicode glyphs (box-drawing, checkmarks, etc.) don't crash
    # on Windows cp1252 consoles.
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    rc = subprocess.call(cmd, cwd=PROJECT_ROOT, env=env)
    dt = time.time() - t0
    status = "PASS" if rc == 0 else f"FAIL (rc={rc})"
    return label, status, dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="Skip heavy verification scripts")
    ap.add_argument("--full", action="store_true",
                    help="Include full_verification.py, adsec_comparison.py, deep_audit.py")
    ap.add_argument("--pytest-only", action="store_true",
                    help="Only run pytest discovery in tests/")
    args = ap.parse_args()

    results = []

    for label, files in PYTEST_STAGES:
        cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short", *files]
        results.append(run(label, cmd))

    if not args.pytest_only:
        scripts = STANDALONE_SCRIPTS[:]
        if args.full and not args.quick:
            scripts.extend(HEAVY_SCRIPTS)
        for label, script in scripts:
            if not os.path.isfile(os.path.join(PROJECT_ROOT, script)):
                results.append((label, "SKIP (not found)", 0.0))
                continue
            cmd = [sys.executable, script]
            results.append(run(label, cmd))

        # Emit visible SKIP entries for known-broken scripts so they
        # remain on the radar without breaking the overall run.
        for script, reason in KNOWN_BROKEN.items():
            results.append((f"Script:  {script}", f"SKIP ({reason})", 0.0))

    # ─── Summary table ────────────────────────────────────────────
    print("\n" + "=" * 78)
    print(f"  {'STAGE':<46} {'STATUS':<18} {'TIME':>8}")
    print("-" * 78)
    overall_ok = True
    for label, status, dt in results:
        marker = "OK " if status == "PASS" else ("-- " if status.startswith("SKIP") else "!! ")
        if status != "PASS" and not status.startswith("SKIP"):
            overall_ok = False
        print(f"  {marker}{label:<43} {status:<18} {dt:>6.2f}s")
    print("=" * 78)
    if overall_ok:
        print("  ALL STAGES PASS")
    else:
        print("  ONE OR MORE STAGES FAILED -- review output above")
    print("=" * 78)
    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
