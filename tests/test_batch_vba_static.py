"""Static checks of the Excel macro (batch/excel/BatchRunner.bas) and template builder."""
import re
from pathlib import Path

from batch import columns as C

XL = Path(__file__).resolve().parents[1] / "batch" / "excel"
BAS = (XL / "BatchRunner.bas").read_text(encoding="utf-8") if (XL / "BatchRunner.bas").exists() else ""
BUILDER = (XL / "build_template.py").read_text(encoding="utf-8") if (XL / "build_template.py").exists() else ""


def _builder_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_template", XL / "build_template.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _proc(name):
    m = re.search(r"(?:Private |Public )?(?:Function|Sub) " + name + r"\b.*?\nEnd (?:Function|Sub)", BAS, re.S)
    assert m, name
    return m.group(0)


def test_numbers_exported_invariant():
    cell = _proc("CellText")
    assert "Str$(" in cell or "Str(" in cell
    code = "\n".join(l for l in BAS.splitlines() if not l.strip().startswith("'"))
    assert "CStr(" not in code and "CDbl(" not in code and "Format(" not in code


def test_import_uses_val():
    imp = _proc("ImportResults")
    assert "Val(" in imp and "CDbl(" not in imp


def test_exe_and_dir_quoted():
    run = _proc("RunBatch")
    assert re.search(r'Chr\(34\)\s*&\s*exe\s*&\s*Chr\(34\)', run)
    assert re.search(r'Chr\(34\)\s*&\s*folder\s*&\s*Chr\(34\)', run)
    assert re.search(r'Chr\(34\)\s*&\s*ThisWorkbook\.FullName\s*&\s*Chr\(34\)', run)


def test_utf8_exchange_files():
    assert BAS.count('Charset = "utf-8"') >= 2  # write TSVs and read results / summary as UTF-8


def test_sheet_names_match_builder():
    sheets = _builder_module().SHEETS
    for name in ("Inputs", "Settings", "Results"):
        assert f'"{name}"' in BAS and name in sheets


def test_layout_constants_match_columns_py():
    for const, val in (("INPUT_HEADER_ROW", C.INPUT_HEADER_ROW), ("INPUT_FIRST_DATA_ROW", C.INPUT_FIRST_DATA_ROW),
                       ("SETTINGS_FIRST_ROW", C.SETTINGS_FIRST_ROW), ("RESULTS_HEADER_ROW", C.RESULTS_HEADER_ROW),
                       ("RESULTS_FIRST_DATA_ROW", C.RESULTS_FIRST_DATA_ROW)):
        assert re.search(rf"Const {const} As Long = {val}\b", BAS), const


def test_header_driven_no_hardcoded_cells():
    code = "\n".join(l for l in BAS.splitlines() if not l.strip().startswith("'"))
    assert not re.search(r'Range\("\$?[A-Z]{1,3}\$?\d', code)
    assert not re.search(r'Columns\("[A-Z]', code)


def test_builder_never_changes_vbom_setting():
    assert "AccessVBOM" in BUILDER
    assert not re.search(r"SetValue|CreateKey|DeleteValue|reg add", BUILDER)


def test_builder_uses_column_spec_and_imports_macro():
    m = _builder_module()
    assert m.XL_XLSM == 52  # xlOpenXMLWorkbookMacroEnabled
    assert "from batch import columns" in BUILDER and "BatchRunner.bas" in BUILDER
    assert "VBComponents.Import" in BUILDER and '"RunBatch"' in BUILDER


def test_builder_unit_formula():
    m = _builder_module()
    assert m.unit_formula("text") == "" and m.unit_formula("dimensionless") == ""
    assert m.unit_formula("fixed:kip-in²") == "kip-in²"
    f = m.unit_formula("stress")
    assert f.startswith("=IFERROR(INDEX(UnitTable,") and '"stress"' in f and "UnitForce" in f and "UnitLength" in f
    assert m.col_letter(1) == "A" and m.col_letter(26) == "Z" and m.col_letter(27) == "AA"


def test_macro_and_builder_are_ascii():
    # VBA imports .bas as ANSI; Windows PowerShell 5.1 reads BOM-less .ps1 as ANSI
    (XL / "BatchRunner.bas").read_bytes().decode("ascii")
    (XL / "build_template.bat").read_bytes().decode("ascii")


def test_template_bat_has_crlf():
    raw = (XL / "build_template.bat").read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n") > 0


def test_bas_has_crlf():
    # VBComponents.Import mis-reads LF-only modules (Attribute VB_Name ends up as code)
    raw = (XL / "BatchRunner.bas").read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n") > 0


def _code():
    return "\n".join(l for l in BAS.splitlines() if not l.strip().startswith("'"))


def test_file_ops_unicode_safe():
    # Final review I2: Dir$ / Kill use the ANSI code page and fail for paths outside it
    code = _code()
    assert not re.search(r"\bDir\$?\(", code) and not re.search(r"^\s*Kill\b", code, re.M)
    assert "Scripting.FileSystemObject" in code and ".FileExists(" in code and ".DeleteFile" in code


def test_results_text_columns_kept_as_text():
    # Final review I1: Section ID "1-2" came back as 1 (Val on a text column)
    imp = _proc("ImportResults")
    assert 'NumberFormat = "@"' in imp or "NumberFormat = \"@\"" in imp
    m = _builder_module()
    assert [C.RESULT_COLUMNS[i].header for i in m.text_result_columns()] == \
        [c.header for c in C.RESULT_COLUMNS if c.kind == "text"]
    assert "text_result_columns()" in BUILDER.split("def build_results", 1)[1]


def test_is_number_text_is_strict():
    body = _proc("IsNumberText")
    # a real number grammar, not "any mix of digits and +-.eE"
    assert 'InStr(1, "+-.eE", ch)' not in body
    for token in ("sign", "mant", "expo"):
        assert token in body
