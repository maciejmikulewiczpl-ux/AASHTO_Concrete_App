"""Run an extraction job: resolve targets, stream rows into a workbook, write Run info."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Callable

from .jobs import Job, TABLE_KEYS, validate
from .source import MODES, TABLE_COLUMNS, ResultSource, SourceError
from .targets import resolve
from .writer import WorkbookWriter

TOOL_VERSION = "0.1.0"
PROGRESS_EVERY = 1000
TAB_BASE = {
    ("frame", "envelope"): "Frame Forces – Envelope",
    ("frame", "correspondence"): "Frame Forces – Corresp.",
    ("joint", "envelope"): "Joint Reactions – Envelope",
    ("joint", "correspondence"): "Joint Reactions – Corresp.",
}


@dataclass
class RunResult:
    path: str
    rows: dict = field(default_factory=dict)
    tabs: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    seconds: float = 0.0
    complete: bool = False


def default_out_path(job: Job, model_file: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    p = Path(model_file.replace("\\", "/"))
    folder = job.output_dir or str(p.parent)
    name = job.name_pattern.format(model=p.stem, stamp=now.strftime("%Y-%m-%d_%H%M"))
    return str(Path(folder) / name)


def _job_json(job: Job) -> str:
    data = {f.name: getattr(job, f.name) for f in fields(job) if f.name != "warnings"}
    return json.dumps(data, ensure_ascii=False)


def run_job(job: Job, source: ResultSource, out_path: str | None = None,
            progress: Callable[[dict], None] | None = None,
            cancel: threading.Event | None = None) -> RunResult:
    t0 = time.monotonic()
    started = datetime.now()
    try:
        errors = validate(job)
        if errors:
            raise ValueError("; ".join(errors))
        if out_path is None:
            out_path = default_out_path(job, source.model_info().file, started)
        # The writer checks the output is writable in __init__: fail fast, before extraction.
        with WorkbookWriter(out_path) as writer:
            return _run(job, source, writer, str(out_path), progress, cancel, t0, started)
    finally:
        source.close()


def _run(job, source, writer, out_path, progress, cancel, t0, started) -> RunResult:
    warnings: list = [f"job file: {w}" for w in job.warnings]
    info = source.model_info()
    if not info.analysed:
        warnings.append("model is not analysed: results may be missing")
    if not str(info.version).startswith("27.1"):
        warnings.append(f"CSiBridge version {info.version} (this tool targets 27.1)")

    res = resolve(job.frames, job.joints, job.groups, source.model_lists())
    for label, items in (("frames not in model", res.missing_frames),
                         ("joints not in model", res.missing_joints),
                         ("groups not in model", res.missing_groups),
                         ("ranges matching no label", res.empty_ranges),
                         ("group members not frames/joints of the model", res.group_members_not_in_model),
                         ("range-like tokens that are also literal labels (both extracted)",
                          res.ambiguous_tokens)):
        if items:
            warnings.append(f"{label}: {', '.join(items)}")

    known = {c.name: c for c in source.list_cases()}
    cases, missing_cases, no_results = [], [], []
    for c in job.cases:
        if c not in known:
            missing_cases.append(c)
        elif not known[c].has_results:
            no_results.append(c)
        else:
            cases.append(c)
    if missing_cases:
        warnings.append(f"cases not in model: {', '.join(missing_cases)}")
    if no_results:
        warnings.append(f"cases without results (skipped): {', '.join(no_results)}")
    complete = True
    if not cases:
        warnings.append("no cases with results: nothing extracted")
        complete = False

    rows: dict = {}
    tabs: list = []
    cancelled = False
    total = 0
    plan = [(t, m) for t in TABLE_KEYS if job.tables.get(t, {}).get("enabled")
            for m in job.tables[t]["modes"] if m in MODES]
    for table, mode in plan:
        objects = res.frames if table == "frame" else res.joints
        base = TAB_BASE[(table, mode)]
        t_tab = time.monotonic()
        handle = writer.open_table(base, TABLE_COLUMNS[table], source.units_row(table))
        if not objects:
            warnings.append(f"{base}: no {table}s resolved, tab is empty")
        for obj in (objects if cases else []):
            if cancel is not None and cancel.is_set():
                cancelled = True
                break
            before = handle.rows_written
            try:
                for row in source.iter_rows(table, mode, cases, [obj]):
                    handle.write(row)
                    total += 1
                    if progress and total % PROGRESS_EVERY == 0:
                        progress({"table": table, "mode": mode, "rows": total,
                                  "seconds": time.monotonic() - t_tab})
                    if cancel is not None and cancel.is_set():
                        cancelled = True
                        break
            except SourceError as exc:
                warnings.append(f"{base}: object {obj}: {exc} "
                                f"({handle.rows_written - before} rows kept)")
            if cancelled:
                break
        rows[base] = handle.rows_written
        tabs.extend(handle.tabs)
        if handle.non_finite_cells:
            warnings.append(f"{base}: {handle.non_finite_cells} non-finite cells written as text")
        if handle.non_numeric_cells:
            warnings.append(f"{base}: {handle.non_numeric_cells} text cells in numeric columns")
        if cancelled:
            break
    if cancelled:
        complete = False
        warnings.append("cancelled: workbook is INCOMPLETE")
    warnings.extend(source.notes())

    seconds = time.monotonic() - t0
    items = [
        ("Status", "COMPLETE" if complete else "INCOMPLETE"),
        ("complete", str(complete)),
        ("Model file", info.file),
        ("CSiBridge version", info.version),
        ("Units", json.dumps(info.units, ensure_ascii=False)),
        ("Job", _job_json(job)),
        ("Resolved frames", len(res.frames)),
        ("Resolved joints", len(res.joints)),
        ("Cases extracted", ", ".join(cases)),
        ("Tool version", TOOL_VERSION),
        ("Started", started.isoformat(timespec="seconds")),
        ("Ended", datetime.now().isoformat(timespec="seconds")),
        ("Seconds", f"{seconds:.1f}"),
    ]
    items += [(f"Rows: {b}", n) for b, n in rows.items()]
    items.append(("Tabs", ", ".join(tabs)))
    items.append(("Warnings", len(warnings)))
    items += [("Warning", w) for w in warnings]
    writer.write_run_info(items)
    return RunResult(out_path, rows, tabs, warnings, seconds, complete)
