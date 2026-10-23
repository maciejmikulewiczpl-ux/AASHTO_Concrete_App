"""Streaming XLSX writer: two header rows, continuation tabs, Run info as the first tab."""
from __future__ import annotations

import csv
import logging
import math
import numbers
import os
import re
import tempfile
from pathlib import Path

import xlsxwriter

EXCEL_MAX_ROWS = 1_048_576
HEADER_ROWS = 2
RUN_INFO_TAB = "Run info"
MAX_CELL_CHARS = 32767
_CHUNK = 32000  # Run-info values are split into pieces of this length
_log = logging.getLogger(__name__)
_BAD_CHARS = re.compile(r"[\[\]:*?/\\]")


class WriterError(Exception):
    """A cell could not be written without losing data (e.g. text longer than Excel allows)."""


class OutputLockedError(Exception):
    """The output workbook cannot be written (open in Excel, or folder not writable)."""

    def __init__(self, path, reason: str = ""):
        self.path = str(path)
        self.reason = reason
        super().__init__(f"Cannot write to {self.path}" + (f": {reason}" if reason else ""))


def check_writable(path) -> None:
    path = Path(path)
    folder = path.parent
    if not folder.is_dir():
        raise OutputLockedError(path, "folder does not exist")
    try:
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".wtest_")
        os.close(fd)
        os.remove(tmp)
    except OSError as exc:
        raise OutputLockedError(path, f"folder is not writable ({exc})") from exc
    if path.exists():
        try:
            # r+b never truncates; a file open in Excel denies write sharing and fails here
            with open(path, "r+b"):
                pass
        except OSError as exc:
            raise OutputLockedError(path, f"file is open elsewhere (e.g. in Excel) or read-only ({exc})") from exc


def _tab_name(base: str, n: int, used: set) -> str:
    suffix = "" if n == 1 else f" ({n})"
    clean = _BAD_CHARS.sub("-", base).strip("'") or "Sheet"
    name = clean[: 31 - len(suffix)] + suffix
    i = 0
    while name.lower() in used:  # defensive: truncation collisions between different tables
        i += 1
        tag = f"~{i}"
        name = clean[: 31 - len(suffix) - len(tag)] + tag + suffix
    return name


class TableHandle:
    def __init__(self, writer: "WorkbookWriter", base: str, header: list, units: list):
        self.non_finite_cells = 0  # NaN/inf values (written as text, counted for Run info)
        self.non_numeric_cells = 0  # text/other values found in a column that is numeric
        self._numeric_cols = None  # inferred from the first row written
        self._w = writer
        self._base = base
        self._header = list(header)
        self._units = list(units)
        self.tabs: list = []
        self.rows_written = 0
        self._ws = None
        self._row = 0
        self._in_tab = 0
        self._new_tab()

    def _new_tab(self) -> None:
        name = _tab_name(self._base, len(self.tabs) + 1, self._w._used)
        self._w._used.add(name.lower())
        ws = self._w._wb.add_worksheet(name)
        self.tabs.append(name)
        # constant_memory: whole row 0 first, then whole row 1 (a cell for an earlier row is lost)
        for c, h in enumerate(self._header):
            self._put(ws, name, 0, c, h, self._w._bold)
        for c, u in enumerate(self._units):
            self._put(ws, name, 1, c, u)
        ws.freeze_panes(HEADER_ROWS, 0)
        self._ws, self._row, self._in_tab = ws, HEADER_ROWS, 0

    @staticmethod
    def _put(ws, tab, r, c, text, fmt=None) -> None:
        if ws.write_string(r, c, str(text), fmt) < 0:
            raise WriterError(f"cannot write text to tab {tab!r} row {r + 1} col {c + 1}: "
                              f"{len(str(text))} characters (Excel limit {MAX_CELL_CHARS})")

    def write(self, row: tuple) -> None:
        if self._in_tab >= self._w._data_per_tab:
            self._new_tab()
        if self._numeric_cols is None:
            self._numeric_cols = {c for c, v in enumerate(row)
                                  if isinstance(v, numbers.Real) and not isinstance(v, bool)}
        ws, r, tab = self._ws, self._row, self.tabs[-1]
        for c, v in enumerate(row):
            if v is None:
                continue
            if isinstance(v, bool):
                rc = ws.write_boolean(r, c, v)
            elif isinstance(v, numbers.Real):
                if not math.isfinite(v):
                    self.non_finite_cells += 1
                    self._put(ws, tab, r, c, str(v))
                    continue
                rc = ws.write_number(r, c, int(v) if isinstance(v, numbers.Integral) else float(v))
            else:
                if c in self._numeric_cols:
                    self.non_numeric_cells += 1
                self._put(ws, tab, r, c, v)  # text is never interpreted as a formula
                continue
            if rc < 0:
                raise WriterError(f"cannot write value to tab {tab!r} row {r + 1} col {c + 1}")
        self._row += 1
        self._in_tab += 1
        self.rows_written += 1


class WorkbookWriter:
    """``row_limit`` is the maximum number of DATA rows per tab (the two header rows are extra);
    it is capped so a tab never exceeds Excel's 1,048,576 rows."""

    def __init__(self, path, row_limit: int = EXCEL_MAX_ROWS):
        self.path = self.requested_path = os.path.abspath(str(path))
        self.close_note = None  # set when close() had to use an alternate name
        check_writable(self.path)
        fd, self._tmp = tempfile.mkstemp(dir=Path(self.path).parent, prefix=".part_", suffix=".xlsx")
        os.close(fd)
        self._data_per_tab = max(1, min(int(row_limit), EXCEL_MAX_ROWS - HEADER_ROWS))
        try:
            self._wb = xlsxwriter.Workbook(self._tmp, {"constant_memory": True, "use_zip64": True})
        except BaseException:
            try:
                os.remove(self._tmp)
            except OSError:
                pass
            raise
        self._bold = self._wb.add_format({"bold": True})
        self._used: set = {RUN_INFO_TAB.lower()}
        # Created first so it is tab #1. In constant_memory mode each sheet streams to its own
        # temp file, so its rows can be written later (at the end) as long as they ascend.
        self._info = self._wb.add_worksheet(RUN_INFO_TAB)
        self._info_written = False
        self._closed = False

    def open_table(self, tab_base: str, header: list, units: list) -> TableHandle:
        return TableHandle(self, tab_base, header, units)

    def write_run_info(self, items: list) -> None:
        if self._info_written:
            raise RuntimeError("Run info already written")
        self._info_written = True
        ws = self._info
        ws.set_column(0, 0, 32)
        ws.set_column(1, 1, 100)
        r = 0
        for k, v in items:
            kk, vv = str(k), str(v)
            parts = [vv[i:i + _CHUNK] for i in range(0, len(vv), _CHUNK)] or [""]
            for n, part in enumerate(parts):
                label = kk[:_CHUNK] if n == 0 else f"{kk[:200]} (continued)"
                TableHandle._put(ws, RUN_INFO_TAB, r, 0, label, self._bold)
                TableHandle._put(ws, RUN_INFO_TAB, r, 1, part)
                r += 1

    def _alternates(self):
        p = Path(self.requested_path)
        yield str(p)
        for i in range(1, 100):
            alt = p.with_name(f"{p.stem}_{i}{p.suffix}")
            if not alt.exists():
                yield str(alt)

    def ensure_target(self):
        """If the requested file became locked, switch to the first free alternate name
        (<stem>_1.xlsx ...). Returns a message when the path changed, else None."""
        for cand in self._alternates():
            try:
                check_writable(cand)
            except OutputLockedError:
                continue
            if os.path.normcase(os.path.abspath(cand)) != os.path.normcase(os.path.abspath(self.path)):
                self.path = cand
                return f"output file locked; saving to {cand} instead of {self.requested_path}"
            return None
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._wb.close()
        except BaseException:
            try:
                os.remove(self._tmp)
            except OSError:
                pass
            raise
        first = [self.path] + [c for c in self._alternates()
                               if os.path.normcase(os.path.abspath(c)) != os.path.normcase(os.path.abspath(self.path))]
        for cand in first:
            try:
                os.replace(self._tmp, cand)
            except OSError:
                continue
            if os.path.normcase(os.path.abspath(cand)) != os.path.normcase(os.path.abspath(self.path)):
                self.close_note = f"output file locked at close; saved to {cand} instead of {self.path}"
            self.path = cand
            return
        # nothing could be replaced: keep the data in the .part file rather than delete it
        exc = OutputLockedError(self.requested_path,
                                f"cannot replace the file or any alternate name; data kept in {self._tmp}")
        exc.workbook_path = self._tmp
        raise exc

    def __enter__(self) -> "WorkbookWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.close()
            return
        # Never mask the original exception: best-effort INCOMPLETE workbook, errors only logged.
        try:
            if not self._info_written:
                self.write_run_info([("Status", f"INCOMPLETE: aborted ({exc_type.__name__}: {exc})")])
            self.close()
        except Exception:
            _log.exception("could not finalise workbook after %s", exc_type.__name__)


def csv_name(base: str) -> str:
    return _BAD_CHARS.sub("-", base).replace("\u2013", "-").strip().rstrip(".") + ".csv"


class CsvTableHandle:
    """One CSV per table/mode: a single header row 'Name [unit]' (Power Query friendly), then data."""

    def __init__(self, folder: Path, base: str, header: list, units: list):
        self.non_finite_cells = 0
        self.non_numeric_cells = 0
        self._numeric_cols = None
        name = csv_name(base)
        self.tabs = [name]
        self.rows_written = 0
        self._fh = open(folder / name, "w", newline="", encoding="utf-8-sig")
        self._w = csv.writer(self._fh)
        u = list(units) + [""] * (len(header) - len(units))
        self._w.writerow([f"{h} [{x}]" if x and x.lower() != "text" else str(h) for h, x in zip(header, u)])

    def write(self, row: tuple) -> None:
        if self._numeric_cols is None:
            self._numeric_cols = {c for c, v in enumerate(row)
                                  if isinstance(v, numbers.Real) and not isinstance(v, bool)}
        out = []
        for c, v in enumerate(row):
            if isinstance(v, numbers.Real) and not isinstance(v, bool):
                if not math.isfinite(v):
                    self.non_finite_cells += 1
            elif v is not None and c in self._numeric_cols:
                self.non_numeric_cells += 1
            out.append("" if v is None else v)
        self._w.writerow(out)
        self.rows_written += 1

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()


class CsvWriter:
    """Writes a folder: one CSV per table/mode plus 'Run info.csv'. Same interface as WorkbookWriter.

    overwrite=True reuses the folder and replaces only the files named in ``managed`` (table bases)
    and Run info; otherwise a non-empty folder is never touched and <name>_1, _2 ... is used.
    """

    def __init__(self, path, overwrite: bool = False, managed=()):
        p = Path(os.path.abspath(str(path)))
        if p.suffix.lower() in (".xlsx", ".csv"):
            p = p.with_suffix("")
        self.requested_path = str(p)
        self.close_note = None
        check_writable(p.with_name(p.name + ".check"))  # parent folder exists and is writable
        if overwrite:
            if p.exists() and not p.is_dir():
                raise OutputLockedError(p, "a file with this name exists (expected a folder)")
            p.mkdir(exist_ok=True)
            own = [p / csv_name(b) for b in managed] + [p / f"{RUN_INFO_TAB}.csv"]
            old = [f for f in own if f.exists()]
            for f in old:  # all checked before any is deleted
                check_writable(f)
            for f in old:
                f.unlink()
            cand = p
        else:
            cand = p
            i = 0
            while cand.exists() and (not cand.is_dir() or any(cand.iterdir())):
                i += 1
                cand = p.with_name(f"{p.name}_{i}")
            cand.mkdir(exist_ok=True)
            if cand != p:
                self.close_note = f"folder {p} already had files; wrote to {cand}"
        self.path = str(cand)
        self._folder = cand
        self._handles: list = []
        self._info_written = False

    def open_table(self, tab_base: str, header: list, units: list) -> CsvTableHandle:
        h = CsvTableHandle(self._folder, tab_base, header, units)
        self._handles.append(h)
        return h

    def write_run_info(self, items: list) -> None:
        if self._info_written:
            raise RuntimeError("Run info already written")
        self._info_written = True
        with open(self._folder / f"{RUN_INFO_TAB}.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["Item", "Value"])
            for k, v in items:
                w.writerow([str(k), str(v)])

    def ensure_target(self):
        return None

    def close(self) -> None:
        for h in self._handles:
            h.close()

    def __enter__(self) -> "CsvWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is not None and not self._info_written:
                self.write_run_info([("Status", f"INCOMPLETE: aborted ({exc_type.__name__}: {exc})")])
        except Exception:
            _log.exception("could not write Run info after %s", exc_type.__name__)
        finally:
            self.close()
