"""AASHTO batch runner CLI — called by the Excel template's Run button (frozen as AASHTO_Batch.exe).

    AASHTO_Batch.exe --dir <folder> [--workbook <path to .xlsm>]

Reads  <folder>/_batch_inputs.tsv and _batch_settings.tsv (written by the macro),
writes <folder>/_batch_results.tsv, _batch_progress.txt and _batch_summary.txt (key=value lines:
status done|fatal, sections, rows, errors, project, project_error, message).
Exit 0 when the run completed (section errors are reported per row), 2 when it could not run.
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

VERSION = "1.0.0"


def _write_summary(folder: str, **kv) -> None:
    lines = [f"{k}={str(v).replace(chr(10), ' ').replace(chr(13), ' ')}" for k, v in kv.items()]
    with open(os.path.join(folder, "_batch_summary.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="AASHTO_Batch")
    ap.add_argument("--dir", help="folder holding the _batch_*.tsv exchange files")
    ap.add_argument("--workbook", help="workbook path; default project file = <workbook>.aashto.json")
    ap.add_argument("--version", action="store_true")
    a = ap.parse_args(argv)
    if a.version:
        print(f"AASHTO_Batch {VERSION}")
        return 0
    if not a.dir:
        ap.error("--dir is required")
    folder = a.dir
    try:
        if not os.path.isdir(folder):
            raise FileNotFoundError(f"folder not found: {folder}")
        inputs = os.path.join(folder, "_batch_inputs.tsv")
        settings = os.path.join(folder, "_batch_settings.tsv")
        for p in (inputs, settings):
            if not os.path.isfile(p):
                raise FileNotFoundError(f"missing {os.path.basename(p)} in {folder}")
        default_project = None
        if a.workbook:
            default_project = os.path.splitext(a.workbook)[0] + ".aashto.json"
        from batch.runner import run_batch
        s = run_batch(inputs, settings, os.path.join(folder, "_batch_results.tsv"),
                      os.path.join(folder, "_batch_progress.txt"), default_project)
    except Exception as e:  # anything here means the run could not happen at all
        msg = str(e) or e.__class__.__name__
        print(f"AASHTO_Batch: {msg}", file=sys.stderr)
        traceback.print_exc()
        if os.path.isdir(folder):
            _write_summary(folder, status="fatal", message=msg)
        return 2
    _write_summary(folder, status="done", sections=s["sections"], rows=s["rows"], errors=s["errors"],
                   project=s["project"] or "", project_error=s["project_error"], message="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
