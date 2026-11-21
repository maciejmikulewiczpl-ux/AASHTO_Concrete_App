"""Builds AASHTO_Batch_Template.xlsm (repo root) from the column spec in batch/columns.py.

    batch\\excel\\build_template.bat            (installs pywin32 into .build_venv and runs this)
    python batch/excel/build_template.py [--out PATH] [--layout-only]

Drives Excel through plain IDispatch late binding (win32com dynamic dispatch). The Office interop
assembly binding that PowerShell uses fails on some machines ("Interface not registered"); late
binding is what VBScript uses and does not depend on that registration.

Needs "Trust access to the VBA project object model" (Excel > File > Options > Trust Center >
Trust Center Settings > Macro Settings) to import BatchRunner.bas. This script only reads that
setting (registry AccessVBOM); it never changes it. --layout-only skips the macro and saves a
plain .xlsx, to check the sheets without that access.
"""
from __future__ import annotations

import argparse
import os
import sys
import winreg

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from batch import columns as C  # noqa: E402

BAS = os.path.join(HERE, "BatchRunner.bas")
COMBOS = ("kip|in", "kip|ft", "lbf|in", "lbf|ft")
TYPES = ("RECTANGULAR", "T-SECTION", "CIRCULAR")
SHEETS = ("Instructions", "Inputs", "Settings", "Results", "_Lists")
N_DATA_ROWS = 1000
XL_VALIDATE_LIST, XL_ALERT_STOP, XL_BETWEEN, XL_EXPRESSION = 3, 1, 1, 2
XL_XLSX, XL_XLSM, XL_SHEET_HIDDEN = 51, 52, 0
GREY, GREY_TEXT, HEADER_FILL, GROUP_TEXT = 0xD9D9D9, 0x808080, 0xF2E6DD, 0x7F3F1F  # BGR

MPHI_NOTE = ("Moment-curvature values (SGS preset, AdSec-style secant EI) are pending verification - "
             "see OPEN_VERIFICATION_ITEMS.md MP1-MP3.")
INSTRUCTIONS = [
    "AASHTO concrete section batch",
    "",
    "1. Settings sheet: pick the force and length units first - every input and result uses them.",
    "   Other AASHTO factors keep the app defaults unless you change them there.",
    "2. Inputs sheet: one row per load case. Rows with the same Section ID are load cases of one section;",
    "   geometry and bars are read from that section's first row. Greyed cells do not apply to the row's section type.",
    "3. Press Run (Inputs sheet). AASHTO_Batch.exe must be next to this workbook (or set 'Engine exe' in Settings).",
    "   No Python install is needed.",
    "4. Results sheet: one row per input row, full-precision numbers. ERROR rows carry the reason in Message.",
    "   A project file (<workbook name>.aashto.json unless set in Settings) is written; open it in the app.",
    "",
    "Notes",
    "- Flexure Mr and its D/C are the app's demand-table (row) values, as shown in the app.",
    "- " + MPHI_NOTE,
    "- Exchange files _batch_*.tsv / _batch_*.txt are written next to the workbook on each run.",
    "- Numbers are exchanged in a locale-independent form, so any Windows decimal separator works.",
]
UNIT_KINDS = tuple(C.UNIT_LABELS)


def vbom_enabled() -> bool:
    for ver in ("16.0", "15.0"):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Office\{ver}\Excel\Security") as k:
                return winreg.QueryValueEx(k, "AccessVBOM")[0] == 1
        except OSError:
            continue
    return False


def col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, m = divmod(n - 1, 26)
        s = chr(65 + m) + s
    return s


def unit_formula(kind: str) -> str:
    """Units-cell content for a column kind (English formula driven by the Settings unit cells)."""
    if kind.startswith("fixed:"):
        return kind[6:]
    if kind not in UNIT_KINDS:
        return ""
    combo = 'IF(UnitForce="","kip",UnitForce)&"|"&IF(UnitLength="","in",UnitLength)'
    return f'=IFERROR(INDEX(UnitTable,MATCH("{kind}",UnitKinds,0),MATCH({combo},UnitCombos,0)),"")'


def default_text(col) -> str:
    d = col.default
    if d is None or d == "" or isinstance(d, bool):
        return "" if not isinstance(d, bool) else ("TRUE" if d else "FALSE")
    return str(d)


class Builder:
    def __init__(self, xl, layout_only: bool):
        global pythoncom
        import pythoncom
        self.xl, self.layout_only = xl, layout_only
        self.wb = xl.Workbooks.Add()
        while self.wb.Worksheets.Count < len(SHEETS):
            self.wb.Worksheets.Add(pythoncom.Missing, self.wb.Worksheets(self.wb.Worksheets.Count))
        for i, name in enumerate(SHEETS, 1):
            self.wb.Worksheets(i).Name = name
        self.ws = {n: self.wb.Worksheets(n) for n in SHEETS}
        self.lists: dict[tuple, str] = {}
        self.next_list_col = 8

    # Excel UI-language version of an English formula (conditional formats take local formulas).
    def local_formula(self, f: str) -> str:
        cell = self.ws["_Lists"].Cells(1, 200)
        cell.Formula = f
        out = cell.FormulaLocal
        cell.ClearContents()
        return out

    def list_ref(self, choices) -> str:
        key = tuple(str(c) for c in choices)
        if key not in self.lists:
            ws, col = self.ws["_Lists"], self.next_list_col
            self.next_list_col += 1
            ws.Columns(col).NumberFormat = "@"
            for i, c in enumerate(key, 1):
                ws.Cells(i, col).Value = c
            L = col_letter(col)
            self.lists[key] = f"='_Lists'!${L}$1:${L}${len(key)}"
        return self.lists[key]

    @staticmethod
    def add_list(rng, ref: str) -> None:
        rng.Validation.Delete()
        rng.Validation.Add(XL_VALIDATE_LIST, XL_ALERT_STOP, XL_BETWEEN, ref)
        rng.Validation.IgnoreBlank = True

    def build_lists(self) -> None:
        ws = self.ws["_Lists"]
        ws.Cells(1, 1).Value = "kind"
        for c, combo in enumerate(COMBOS, 2):
            ws.Cells(1, c).Value = combo
        for k, kind in enumerate(UNIT_KINDS, 2):
            ws.Cells(k, 1).Value = kind
            for c, combo in enumerate(COMBOS, 2):
                ws.Cells(k, c).Value = C.UNIT_LABELS[kind][combo]
        last = 1 + len(UNIT_KINDS)
        self.wb.Names.Add("UnitKinds", f"='_Lists'!$A$2:$A${last}")
        self.wb.Names.Add("UnitCombos", "='_Lists'!$B$1:$E$1")
        self.wb.Names.Add("UnitTable", f"='_Lists'!$B$2:$E${last}")
        ws.Cells(1, 7).Value = True
        ws.Cells(2, 7).Value = False
        self.bool_ref = "='_Lists'!$G$1:$G$2"

    def build_settings(self) -> None:
        ws = self.ws["Settings"]
        for c, h in enumerate(("Setting", "Value", "Units", "Note"), 1):
            ws.Cells(C.SETTINGS_FIRST_ROW - 1, c).Value = h
        ws.Rows(C.SETTINGS_FIRST_ROW - 1).Font.Bold = True
        for r, s in enumerate(C.SETTINGS_ROWS, C.SETTINGS_FIRST_ROW):
            ws.Cells(r, 1).Value = s.header
            cell, note = ws.Cells(r, 2), s.note or ""
            if s.kind == "bool":
                cell.Value = bool(s.default)
                self.add_list(cell, self.bool_ref)
            elif s.kind in UNIT_KINDS:
                # Left blank on purpose: a pre-filled number would change meaning when the units change.
                if default_text(s):
                    note = f"Blank = {s.default} in kip / in units (converted to the chosen units). {note}".strip()
            elif default_text(s):
                cell.NumberFormat = "@"
                cell.Value = default_text(s)
            if s.choices:
                self.add_list(cell, self.list_ref(s.choices))
            if s.key == "unit_force":
                self.wb.Names.Add("UnitForce", f"=Settings!$B${r}")
            if s.key == "unit_length":
                self.wb.Names.Add("UnitLength", f"=Settings!$B${r}")
            if s.key == "engine_exe":
                note = f"Blank = AASHTO_Batch.exe in the workbook folder. {note}".strip()
            if s.key == "project_path":
                note = f"Blank = <workbook name>.aashto.json next to the workbook. {note}".strip()
            f = unit_formula(s.kind)
            if f:
                ws.Cells(r, 3).Formula = f
            ws.Cells(r, 4).Value = note
        for c, w in enumerate((36, 18, 10, 90), 1):
            ws.Columns(c).ColumnWidth = w

    def build_inputs(self) -> None:
        ws, hr, fr = self.ws["Inputs"], C.INPUT_HEADER_ROW, C.INPUT_FIRST_DATA_ROW
        last = fr + N_DATA_ROWS - 1
        type_col = next(i for i, c in enumerate(C.INPUT_COLUMNS, 1) if c.key == "sectionType")
        tL = col_letter(type_col)
        prev = None
        for n, col in enumerate(C.INPUT_COLUMNS, 1):
            L = col_letter(n)
            if col.group != prev:
                ws.Cells(hr - 1, n).Value = col.group
                prev = col.group
            h = ws.Cells(hr, n)
            h.Value = col.header
            f = unit_formula(col.kind)
            if f:
                ws.Cells(hr + 1, n).Formula = f
            tip = [t for t in (col.note,) if t]
            if default_text(col):
                tip.append(f"Blank = {default_text(col)}")
            if col.required:
                tip.append("Required.")
            if len(col.applies) < len(TYPES):
                tip.append("Applies to: " + ", ".join(col.applies))
            if tip:
                h.AddComment("\n".join(tip))
            data = ws.Range(f"{L}{fr}:{L}{last}")
            if col.kind == "text":
                data.NumberFormat = "@"
            if col.choices:
                self.add_list(data, self.list_ref(col.choices))
            elif col.kind == "bool":
                self.add_list(data, self.bool_ref)
            if len(col.applies) < len(TYPES):
                conds = ",".join(f'${tL}{fr}="{t}"' for t in TYPES if t not in col.applies)
                fc = data.FormatConditions.Add(XL_EXPRESSION, 1, self.local_formula(f"=OR({conds})"))
                fc.Interior.Color = GREY
                fc.Font.Color = GREY_TEXT
        lastL = col_letter(len(C.INPUT_COLUMNS))
        ws.Rows(hr - 1).Font.Bold = True
        ws.Rows(hr - 1).Font.Color = GROUP_TEXT
        ws.Rows(hr).Font.Bold = True
        ws.Rows(hr).WrapText = True
        ws.Rows(hr + 1).Font.Italic = True
        ws.Range(f"A{hr}:{lastL}{hr}").Interior.Color = HEADER_FILL
        ws.Range(f"A1:{lastL}1").Columns.ColumnWidth = 11
        ws.Columns(1).ColumnWidth = 14

    def build_results(self) -> None:
        ws, rh = self.ws["Results"], C.RESULTS_HEADER_ROW
        prev = None
        for n, col in enumerate(C.RESULT_COLUMNS, 1):
            if col.group != prev:
                ws.Cells(rh - 1, n).Value = col.group
                prev = col.group
            ws.Cells(rh, n).Value = col.header
        n_r = len(C.RESULT_COLUMNS)
        ws.Cells(rh - 1, n_r + 2).Value = MPHI_NOTE
        ws.Rows(rh - 1).Font.Bold = True
        ws.Rows(rh).Font.Bold = True
        ws.Rows(rh).WrapText = True
        ws.Rows(rh + 1).Font.Italic = True
        ws.Range(f"A1:{col_letter(n_r)}1").Columns.ColumnWidth = 11
        ws.Columns(4).ColumnWidth = 40  # Message

    def build_instructions(self) -> None:
        ws = self.ws["Instructions"]
        for i, line in enumerate(INSTRUCTIONS, 1):
            ws.Cells(i, 1).Value = line
        ws.Cells(1, 1).Font.Bold = True
        ws.Cells(1, 1).Font.Size = 14
        ws.Cells(INSTRUCTIONS.index("Notes") + 1, 1).Font.Bold = True

    def add_macro(self) -> None:
        self.wb.VBProject.VBComponents.Import(BAS)
        ws = self.ws["Inputs"]
        ws.Rows(1).RowHeight = 20
        cell = ws.Cells(1, 1)
        btn = ws.Buttons().Add(cell.Left + 2, cell.Top + 1, 90, 17)
        btn.Caption = "Run"
        btn.OnAction = "RunBatch"
        ws.Cells(1, 1).Value = ""  # the group label of column A sits under the button

    def freeze(self) -> None:
        for name, row, col in (("Inputs", C.INPUT_FIRST_DATA_ROW - 1, 1), ("Results", C.RESULTS_HEADER_ROW + 1, 2)):
            try:
                self.ws[name].Activate()
                win = self.xl.ActiveWindow
                win.FreezePanes = False
                win.SplitRow, win.SplitColumn = row, col
                win.FreezePanes = True
            except Exception as e:  # cosmetic only
                print(f"note: could not freeze panes on {name}: {e}")
        self.ws["Instructions"].Activate()

    def build(self, out: str) -> None:
        self.build_lists()
        self.build_settings()
        self.build_inputs()
        self.build_results()
        self.build_instructions()
        if not self.layout_only:
            self.add_macro()
        self.ws["_Lists"].Visible = XL_SHEET_HIDDEN
        self.freeze()
        if os.path.exists(out):
            os.remove(out)
        self.wb.SaveAs(out, XL_XLSX if self.layout_only else XL_XLSM)
        self.wb.Close(False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--layout-only", action="store_true",
                    help="sheets only (no macro / button), saved as .xlsx")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out or os.path.join(REPO, "AASHTO_Batch_Template.xlsx" if a.layout_only
                                                else "AASHTO_Batch_Template.xlsm"))
    if not a.layout_only and not vbom_enabled():
        print("Excel blocks access to the VBA project, so the macro cannot be imported.\n"
              "Enable it once: Excel > File > Options > Trust Center > Trust Center Settings >\n"
              "Macro Settings > tick 'Trust access to the VBA project object model', then re-run.")
        return 1
    import win32com.client.dynamic as dyn
    xl = dyn.Dispatch("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    try:
        Builder(xl, a.layout_only).build(out)
    finally:
        xl.Quit()
    print(f"Built {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
