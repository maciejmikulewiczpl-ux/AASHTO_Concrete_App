"""Command line: python -m csibridge_extractor.extractor.cli run JOB.json [--out PATH] [--fake FIXTURE]"""
from __future__ import annotations

import argparse
import sys

from .jobs import load_job
from .runner import run_job
from .source import FakeSource


def _progress(p: dict) -> None:
    print(f"  {p['table']}/{p['mode']}: {p['rows']} rows ({p['seconds']:.1f}s)", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="csibridge_extractor.extractor.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run an extraction job")
    r.add_argument("job")
    r.add_argument("--out")
    r.add_argument("--fake", metavar="FIXTURE", help="replay a JSON fixture instead of CSiBridge")
    args = ap.parse_args(argv)

    try:
        job = load_job(args.job)
    except (OSError, ValueError) as exc:
        print(f"Cannot load job: {exc}", file=sys.stderr)
        return 1
    if args.fake:
        source = FakeSource(args.fake)
    else:
        try:
            from .csi_source import CsiSource
        except ImportError:
            print("real CSiBridge adapter not available yet (Task 7)", file=sys.stderr)
            return 1
        try:
            source = CsiSource()
        except Exception as exc:
            print(f"Cannot connect to CSiBridge: {exc}", file=sys.stderr)
            return 1
    try:
        result = run_job(job, source, args.out, progress=_progress)
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"{'Complete' if result.complete else 'INCOMPLETE'}: {result.path} ({result.seconds:.1f}s)")
    for tab, n in result.rows.items():
        print(f"  {tab}: {n} rows")
    for w in result.warnings:
        print(f"  WARNING: {w}")
    if not result.complete:
        return 1
    return 2 if result.warnings else 0


if __name__ == "__main__":
    sys.exit(main())
