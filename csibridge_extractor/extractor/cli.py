"""Command line: python -m csibridge_extractor.extractor.cli run JOB.json [--out PATH] [--fake FIXTURE]"""
from __future__ import annotations

import argparse
import sys
import threading

from .jobs import load_job
from .runner import run_job
from .source import FakeSource


def _progress(p: dict) -> None:
    tag = "done" if p.get("final") else "..."
    print(f"  {p['table']}/{p['mode']}: {p['rows']} rows ({p['seconds']:.1f}s) {tag}", flush=True)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
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
        try:
            source = FakeSource(args.fake)
        except Exception as exc:
            print(f"Cannot load fixture {args.fake}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    else:
        try:
            from .csi_source import CsiSource
        except ModuleNotFoundError as exc:
            if exc.name and exc.name.endswith("csi_source"):
                print("real CSiBridge adapter not available yet (Task 7)", file=sys.stderr)
            else:
                print(f"CSiBridge adapter could not be imported (missing module {exc.name}): {exc}",
                      file=sys.stderr)
            return 1
        except ImportError as exc:
            print(f"CSiBridge adapter could not be imported: {exc}", file=sys.stderr)
            return 1
        try:
            source = CsiSource()
        except Exception as exc:
            print(f"Cannot connect to CSiBridge: {exc}", file=sys.stderr)
            return 1
    cancel = threading.Event()
    try:
        result = run_job(job, source, args.out, progress=_progress, cancel=cancel)
    except KeyboardInterrupt:
        cancel.set()
        print("Interrupted.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        wb = getattr(exc, "workbook_path", None)
        if wb:
            print(f"Partial workbook (INCOMPLETE): {wb}", file=sys.stderr)
        return 1
    print(f"{'Complete' if result.complete else 'INCOMPLETE'}: {result.path} ({result.seconds:.1f}s)")
    for tab, n in result.rows.items():
        print(f"  {tab}: {n} rows")
    for w in result.warnings:
        print(f"  WARNING: {w}")
    for n in result.notes:
        print(f"  note: {n}")
    if not result.complete:
        return 1
    return 2 if result.warnings else 0


if __name__ == "__main__":
    sys.exit(main())
