"""Streaming XLSX writer: two header rows, continuation tabs, Run info as the first tab."""
from __future__ import annotations

import math
import os
import re
import tempfile
from pathlib import Path

import xlsxwriter

EXCEL_MAX_ROWS = 1_048_576
HEADER_ROWS = 2
RUN_INFO_TAB = "Run info"
_BAD_CHARS = re.compile(r"[\[\]:*?/\\]")


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
            ws.write_string(0, c, h, self._w._bold)
        for c, u in enumerate(self._units):
            ws.write_string(1, c, u)
        ws.freeze_panes(HEADER_ROWS, 0)
        self._ws, self._row, self._in_tab = ws, HEADER_ROWS, 0

    def write(self, row: tuple) -> None:
        if self._in_tab >= self._w._data_per_tab:
            self._new_tab()
        ws, r = self._ws, self._row
        for c, v in enumerate(row):
            if v is None:
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                ws.write_string(r, c, str(v))  # text is never interpreted as a formula
            elif isinstance(v, float) and not math.isfinite(v):
                ws.write_string(r, c, str(v))
            else:
                ws.write_number(r, c, v)
        self._row += 1
        self._in_tab += 1
        self.rows_written += 1


class WorkbookWriter:
    """``row_limit`` is the maximum number of DATA rows per tab (the two header rows are extra);
    it is capped so a tab never exceeds Excel's 1,048,576 rows."""

    def __init__(self, path, row_limit: int = EXCEL_MAX_ROWS):
        self.path = str(path)
        self._data_per_tab = max(1, min(int(row_limit), EXCEL_MAX_ROWS - HEADER_ROWS))
        self._wb = xlsxwriter.Workbook(self.path, {"constant_memory": True})
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
        for r, (k, v) in enumerate(items):
            ws.write_string(r, 0, str(k), self._bold)
            ws.write_string(r, 1, str(v))

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._wb.close()

    def __enter__(self) -> "WorkbookWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
