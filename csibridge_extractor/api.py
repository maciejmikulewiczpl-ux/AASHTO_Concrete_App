"""JS <-> Python bridge for the extractor window.

Every public method returns a JSON string; failures are {"error": "..."}. pywebview is imported lazily
(only in the file-dialog methods), so this module is importable and testable without it.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict
from pathlib import Path

from csibridge_extractor.extractor.jobs import Job, load_job, save_job, validate
from csibridge_extractor.extractor.runner import default_out_path, run_job
from csibridge_extractor.extractor.source import FakeSource
from csibridge_extractor.extractor.targets import resolve


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _err(msg) -> str:
    return _dump({"error": str(msg)})


def _fmt(exc) -> str:
    return f"{type(exc).__name__}: {exc}"


def _job_from_json(raw: str) -> Job:
    """Build and strictly validate a Job from the UI's JSON (reuses load_job's checks)."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("job must be a JSON object")
    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return load_job(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


class Api:
    def __init__(self, fake: str | None = None, source_factory=None, window=None):
        self._window = window
        self._fake = fake
        self._factory = source_factory
        self._lists = None
        self._info = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._reset_run()

    @property
    def window(self):
        return self._window

    @window.setter
    def window(self, w):
        self._window = w

    def _reset_run(self):
        self._progress = None
        self._log: list = []
        self._cursor = 0
        self._done = False
        self._error = None
        self._error_path = None
        self._result = None

    # -- source -------------------------------------------------------------
    def _new_source(self):
        if self._factory:
            return self._factory()
        if self._fake:
            return FakeSource(self._fake)
        try:
            from csibridge_extractor.extractor.csi_source import CsiSource
        except ModuleNotFoundError as exc:
            if exc.name and exc.name.endswith("csi_source"):
                raise RuntimeError("real CSiBridge adapter not available yet (Task 7)") from exc
            raise
        return CsiSource()

    # -- connection ----------------------------------------------------------
    def connect(self) -> str:
        try:
            if self._thread is not None and self._thread.is_alive():
                return _err("a run is in progress: wait for it to finish or cancel it")
            src = self._new_source()
            try:
                info = src.model_info()
                cases = src.list_cases()
                lists = src.model_lists()
                notes = list(src.notes())
            finally:
                src.close()
            self._lists, self._info = lists, info
            return _dump({
                "model_info": asdict(info),
                "cases": [asdict(c) for c in cases],
                "groups": sorted(lists.groups),
                "n_frames": len(lists.frames),
                "n_joints": len(lists.joints),
                "notes": notes,
            })
        except RuntimeError as exc:
            return _err(exc)
        except Exception as exc:
            return _err(_fmt(exc))

    def resolve(self, job_json: str) -> str:
        try:
            if self._lists is None:
                return _err("not connected: click Connect first")
            job = _job_from_json(job_json)
            r = resolve(job.frames, job.joints, job.groups, self._lists)
            out = asdict(r)
            out["counts"] = {"frames": len(r.frames), "joints": len(r.joints)}
            return _dump(out)
        except Exception as exc:
            return _err(_fmt(exc))

    def preview_output(self, job_json: str) -> str:
        try:
            job = _job_from_json(job_json)
            model_file = self._info.file if self._info else ""
            return _dump({"path": default_out_path(job, model_file)})
        except Exception as exc:
            return _err(_fmt(exc))

    # -- run -----------------------------------------------------------------
    def run(self, job_json: str) -> str:
        try:
            job = _job_from_json(job_json)
            errors = validate(job)
            if errors:
                return _err("; ".join(errors))
            with self._lock:
                if self._thread is not None and self._thread.is_alive():
                    return _err("a run is already in progress")
                self._reset_run()
                self._cancel = threading.Event()
                self._thread = threading.Thread(target=self._worker, args=(job, self._cancel),
                                                daemon=True)
                self._thread.start()
            return _dump({"started": True})
        except Exception as exc:
            return _err(_fmt(exc))

    def _worker(self, job, cancel):
        def progress(p):
            with self._lock:
                self._progress = dict(p)
                if p.get("final"):
                    self._log.append(f"{p['table']}/{p['mode']}: {p.get('table_rows', p['rows'])} rows "
                                     f"({p['seconds']:.1f}s)")
        try:
            # Built here, not on the js_api thread: COM/.NET objects keep thread affinity.
            source = self._new_source()
            res = run_job(job, source, None, progress=progress, cancel=cancel)
            with self._lock:
                for w in res.warnings:
                    self._log.append(f"WARNING: {w}")
                for n in res.notes:
                    self._log.append(f"note: {n}")
                self._log.append(f"{'Complete' if res.complete else 'INCOMPLETE'}: {res.path} "
                                 f"({res.seconds:.1f}s)")
                self._result = {"path": res.path, "rows": res.rows, "tabs": res.tabs,
                                "warnings": res.warnings, "notes": res.notes,
                                "seconds": res.seconds, "complete": res.complete}
        except Exception as exc:
            with self._lock:
                self._error = str(exc) if isinstance(exc, RuntimeError) else _fmt(exc)
                self._error_path = getattr(exc, "workbook_path", None)
                self._log.append(f"FAILED: {self._error}")
                if self._error_path:
                    self._log.append(f"Partial workbook (INCOMPLETE): {self._error_path}")
        finally:
            with self._lock:
                self._done = True

    def poll(self) -> str:
        with self._lock:
            new = self._log[self._cursor:]
            self._cursor = len(self._log)
            return _dump({"progress": self._progress, "log": new, "done": self._done,
                          "running": bool(self._thread and self._thread.is_alive()),
                          "error": self._error, "workbook_path": self._error_path,
                          "result": self._result})

    def cancel(self) -> str:
        self._cancel.set()
        return _dump({"cancelling": True})

    # -- files ---------------------------------------------------------------
    def _dialog(self, kind: str, **kw):
        import webview  # lazy: not needed by the tests
        if self._window is None:
            raise RuntimeError("no window")
        const = {"open": webview.OPEN_DIALOG, "save": webview.SAVE_DIALOG,
                 "folder": webview.FOLDER_DIALOG}[kind]
        res = self._window.create_file_dialog(const, **kw)
        if not res:
            return None
        return res if isinstance(res, str) else res[0]

    def save_job(self, job_json: str, path: str | None = None) -> str:
        try:
            job = _job_from_json(job_json)
            if not path:
                path = self._dialog("save", save_filename="extraction_job.json",
                                    file_types=("Job files (*.json)",))
                if not path:
                    return _dump({"saved": False, "cancelled": True})
            save_job(job, path)
            return _dump({"saved": True, "path": str(path)})
        except Exception as exc:
            return _err(_fmt(exc))

    def load_job(self, path: str | None = None) -> str:
        try:
            if not path:
                path = self._dialog("open", file_types=("Job files (*.json)",))
                if not path:
                    return _dump({"cancelled": True})
            job = load_job(path)
            return _dump({"job": asdict(job), "path": str(path), "warnings": job.warnings})
        except Exception as exc:
            return _err(_fmt(exc))

    def pick_folder(self) -> str:
        try:
            return _dump({"path": self._dialog("folder")})
        except Exception as exc:
            return _err(_fmt(exc))

    def open_file(self, path: str) -> str:
        try:
            p = Path(path)
            if p.suffix.lower() != ".xlsx" or not p.is_file():
                return _err(f"not an existing .xlsx file: {path}")
            if not hasattr(os, "startfile"):
                return _err("opening files is only supported on Windows")
            os.startfile(str(p))
            return _dump({"opened": str(p)})
        except Exception as exc:
            return _err(_fmt(exc))
