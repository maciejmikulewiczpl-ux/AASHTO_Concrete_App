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
from .writer import CsvWriter, WorkbookWriter

TOOL_VERSION = "0.1.0"
PROGRESS_EVERY = 1000
TAB_BASE = {
    ("frame", "envelope"): "Frame Forces – Envelope",
    ("frame", "correspondence"): "Frame Forces – Corresp.",
    ("joint", "envelope"): "Joint Reactions – Envelope",
    ("joint", "correspondence"): "Joint Reactions – Corresp.",
    ("disp", "envelope"): "Joint Displacements – Envelope",
    ("disp", "correspondence"): "Joint Displ. – Corresp.",
}


@dataclass
class RunResult:
    path: str
    rows: dict = field(default_factory=dict)
    tabs: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    seconds: float = 0.0
    complete: bool = False
    notes: list = field(default_factory=list)  # informational, never affect the exit code


def default_out_path(job: Job, model_file: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    p = Path(model_file.replace("\\", "/")) if model_file else Path("model")
    folder = job.output_dir or (str(p.parent) if model_file else ".")
    try:
        name = job.name_pattern.format(model=p.stem, stamp=now.strftime("%Y-%m-%d_%H%M"))
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(f"name_pattern is malformed ({exc!r}); use {{model}} and {{stamp}}") from exc
    if job.output_format == "csv" and name.lower().endswith(".xlsx"):
        name = name[:-5]  # CSV output is a folder
    return str(Path(folder) / name)


def _job_json(job: Job) -> str:
    data = {f.name: getattr(job, f.name) for f in fields(job) if f.name != "warnings"}
    return json.dumps(data, ensure_ascii=False)


def _short(items, n=10) -> str:
    items = list(items)
    return ", ".join(items[:n]) + (f", ... (+{len(items) - n} more)" if len(items) > n else "")


def run_job(job: Job, source: ResultSource, out_path: str | None = None,
            progress: Callable[[dict], None] | None = None,
            cancel: threading.Event | None = None) -> RunResult:
    t0 = time.monotonic()
    started = datetime.now()
    pre: list = []
    writer = None
    try:
        errors = validate(job)
        if errors:
            raise ValueError("; ".join(errors))
        if out_path is None:
            model_file = source.model_info().file
            if not model_file:
                pre.append("model file path is empty: using the current folder for the output")
            out_path = default_out_path(job, model_file, started)
        try:
            # The writer checks the output is writable in __init__: fail fast, before extraction.
            if job.output_format == "csv":
                writer_cm = CsvWriter(out_path, overwrite=job.overwrite, managed=TAB_BASE.values())
            else:
                writer_cm = WorkbookWriter(out_path)
            with writer_cm as writer:
                result = _run(job, source, writer, progress, cancel, t0, started, pre)
        except Exception as exc:
            if writer is not None and not getattr(exc, "workbook_path", None):
                exc.workbook_path = writer.path
            raise
        result.path = writer.path
        if writer.close_note:
            result.warnings.append(writer.close_note)
        return result
    finally:
        source.close()


def _run(job, source, writer, progress, cancel, t0, started, pre) -> RunResult:
    warnings: list = list(pre) + [f"job file: {w}" for w in job.warnings]
    rows: dict = {}
    tabs: list = []
    cases: list = []
    nfr = njt = 0
    info = None
    error = None
    cancelled = False
    try:
        info = source.model_info()
        if not info.analysed:
            warnings.append("model is not analysed: results may be missing")
        if not str(info.version).startswith("27.1"):
            warnings.append(f"CSiBridge version {info.version} (this tool targets 27.1)")

        res = resolve(job.frames, job.joints, job.groups, source.model_lists())
        nfr, njt = len(res.frames), len(res.joints)
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
        missing_cases, no_results = [], []
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
        if not cases:
            warnings.append("no cases with results: nothing extracted")

        bsize = getattr(source, "batch_objects", None)
        total = 0
        plan = [(t, m) for t in TABLE_KEYS if job.tables.get(t, {}).get("enabled")
                for m in job.tables[t]["modes"] if m in MODES]
        for table, mode in plan:
            if cancelled:
                break
            objects = res.frames if table == "frame" else res.joints
            base = TAB_BASE[(table, mode)]
            ncols = len(TABLE_COLUMNS[table])
            t_tab = time.monotonic()
            units = source.units_row(table)
            if len(units) != ncols:
                warnings.append(f"{base}: units row has {len(units)} cells, expected {ncols}")
            handle = writer.open_table(base, TABLE_COLUMNS[table], units)
            if not objects:
                warnings.append(f"{base}: no {table}s resolved, tab is empty")
            size = bsize if bsize and bsize > 0 else max(len(objects), 1)
            seen: set = set()
            considered: list = []
            bad_len = 0
            try:
                for i in range(0, len(objects) if cases else 0, size):
                    if cancel is not None and cancel.is_set():
                        cancelled = True
                        break
                    batch = objects[i:i + size]
                    before = handle.rows_written
                    failed = False
                    try:
                        for row in source.iter_rows(table, mode, cases, batch):
                            handle.write(row)
                            seen.add(str(row[0]))
                            if len(row) != ncols:
                                bad_len += 1
                            total += 1
                            if progress and total % PROGRESS_EVERY == 0:
                                progress({"table": table, "mode": mode, "rows": total,
                                          "seconds": time.monotonic() - t_tab})
                            if cancel is not None and cancel.is_set():
                                cancelled = True
                                break
                    except SourceError as exc:
                        failed = True
                        warnings.append(f"{base}: batch [{_short(batch)}]: {exc} "
                                        f"({handle.rows_written - before} rows kept)")
                    if cancelled:
                        break
                    if not failed:
                        considered.extend(batch)
                        if handle.rows_written == before:
                            warnings.append(f"{base}: no rows for the selected cases for "
                                            f"[{_short(batch)}]")
            finally:
                rows[base] = handle.rows_written
                tabs.extend(handle.tabs)
                if bad_len:
                    warnings.append(f"{base}: {bad_len} rows with a wrong number of cells "
                                    f"(expected {ncols}); written as received")
                if handle.non_finite_cells:
                    warnings.append(f"{base}: {handle.non_finite_cells} non-finite cells written as text")
                if handle.non_numeric_cells:
                    warnings.append(f"{base}: {handle.non_numeric_cells} text cells in numeric columns")
            absent = [o for o in considered if o not in seen]
            if absent and len(absent) < len(considered):
                warnings.append(f"{base}: requested but absent from the rows: {_short(absent, 30)}")
            if progress:
                progress({"table": table, "mode": mode, "rows": total, "final": True,
                          "table_rows": handle.rows_written, "seconds": time.monotonic() - t_tab})
    except KeyboardInterrupt:
        cancelled = True
    except Exception as exc:
        error = exc
        warnings.append(f"ABORTED: {type(exc).__name__}: {exc}")

    if cancelled:
        warnings.append("cancelled: workbook is INCOMPLETE")
    notes: list = []
    try:
        notes = list(source.notes())
    except Exception as exc:
        warnings.append(f"could not read source notes: {exc}")
    complete = not cancelled and error is None and bool(cases)
    moved = writer.ensure_target()
    if moved:
        warnings.append(moved)

    seconds = time.monotonic() - t0
    items = [
        ("Status", "COMPLETE" if complete else "INCOMPLETE"),
        ("complete", str(complete)),
        ("Output file", writer.path),
        ("Model file", info.file if info else ""),
        ("CSiBridge version", info.version if info else ""),
        ("Units", json.dumps(info.units, ensure_ascii=False) if info else ""),
        ("Job", _job_json(job)),
        ("Resolved frames", nfr),
        ("Resolved joints", njt),
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
    items += [("Note", n) for n in notes]
    writer.write_run_info(items)
    if error is not None:
        raise error
    return RunResult(writer.path, rows, tabs, warnings, seconds, complete, notes)
