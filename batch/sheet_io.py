"""Read the TSV files the Excel macro exports; group rows into sections; validate.

Numbers must use "." as the decimal separator (the macro exports with VBA Str(), which is
locale-independent); a "," is reported, never guessed at.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from batch.columns import (ASTM_FY, DEMAND_KEYS, INPUT_COLUMNS, INPUT_FIRST_DATA_ROW, RUN_KEYS,
                           SETTINGS_ROWS, Col)
from batch.form import (DEFAULT_UNITS, apply_section_class, form_defaults_for, from_engine, js_num_str,
                        to_engine)

NUMERIC_KINDS = {"length", "stress", "force", "moment", "dimensionless", "unit_weight"}
UNIT_KINDS = NUMERIC_KINDS - {"dimensionless"}
POSITIVE_KEYS = {"fc", "b_flange", "h_total", "b_web", "circ_D"}
SIGNED_KEYS = set(DEMAND_KEYS)
_TRUE = {"true", "1", "yes", "y"}
_FALSE = {"false", "0", "no", "n", ""}


class CellError(ValueError):
    pass


@dataclass
class Section:
    id: str
    sec_type: str
    form: dict
    demands: list = field(default_factory=list)
    row_numbers: list = field(default_factory=list)


@dataclass
class RowError:
    row: int
    section_id: str
    message: str


def read_tsv(path: str) -> list[list[str]]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        text = fh.read()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    return [ln.split("\t") for ln in lines]


def parse_bool(text) -> bool:
    if isinstance(text, bool):
        return text
    t = str(text).strip().lower()
    if t in _TRUE:
        return True
    if t in _FALSE:
        return False
    raise CellError(f"'{text}' is not TRUE / FALSE")


def parse_cell(col: Col, text: str):
    """Validated cell value: str for numbers / choices / text (as the page field would hold it),
    bool for checkboxes. Raises CellError."""
    t = text.strip()
    if col.kind == "bool":
        return parse_bool(t)
    if col.kind in NUMERIC_KINDS:
        if "," in t:
            raise CellError("use '.' as decimal separator")
        try:
            v = float(t)
        except ValueError:
            raise CellError(f"'{t}' is not a number") from None
        if not math.isfinite(v):
            raise CellError(f"'{t}' is not a number")
        if col.key in POSITIVE_KEYS and v <= 0:
            raise CellError("must be greater than 0")
        if col.key not in SIGNED_KEYS and v < 0:
            raise CellError("must not be negative")
        return t
    if col.kind == "choice":
        if col.choices and all(c.isdigit() for c in col.choices):
            try:
                f = float(t)
                t = str(int(f)) if f.is_integer() else t
            except ValueError:
                pass
        for c in col.choices or ():
            if c.lower() == t.lower():
                return c
        raise CellError(f"'{t}' is not one of {', '.join(col.choices)}")
    return t


def _same(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12)
        except ValueError:
            return a.lower() == b.lower()
    return a == b


def parse_settings(rows: list[list[str]]) -> tuple[dict, dict, dict]:
    """(form overrides, units, run options) from the Settings TSV (Setting | Value ...).
    Blank values take the column default. Raises ValueError naming the setting on a bad value."""
    by_label = {}
    for r in rows[1:]:
        if r and r[0].strip():
            by_label[r[0].strip().lower()] = r[1] if len(r) > 1 else ""
    vals = {}
    unit_cols = [c for c in SETTINGS_ROWS if c.key in ("unit_force", "unit_length")]
    rest = [c for c in SETTINGS_ROWS if c not in unit_cols]
    for col in unit_cols + rest:  # units first: blank unit-bearing defaults are converted to them
        raw = by_label.get(col.header.lower(), "")
        if str(raw).strip() == "":
            if col.kind in UNIT_KINDS and col.default not in ("", None):
                u = {"force": vals["unit_force"], "length": vals["unit_length"]}
                vals[col.key] = js_num_str(from_engine(float(col.default), col.kind, u))
            else:
                vals[col.key] = col.default
            continue
        try:
            vals[col.key] = parse_cell(col, raw)
        except CellError as e:
            raise ValueError(f"Settings, {col.header}: {e}") from None
    form = {k: v for k, v in vals.items() if k not in RUN_KEYS}
    units = {"force": vals["unit_force"], "length": vals["unit_length"]}
    run = {"shearCapacityMethod": vals["shear_method"],
           "mphi": {"model": vals["mphi_model"], "expected_concrete": bool(vals["mphi_exp_c"]),
                    "expected_steel": bool(vals["mphi_exp_s"])},
           "project_path": vals["project_path"] or "", "overwrite_project": bool(vals["overwrite_project"])}
    return form, units, run


def _astm_fy(base_form: dict, units: dict) -> str:
    fy = ASTM_FY.get(base_form.get("astm_spec") or "A615_60", 60.0)
    return js_num_str(round(from_engine(fy, "stress", units), 4))


def group_rows(rows: list[list[str]], base_form: dict, units: dict):
    """Inputs TSV (header row + data rows) -> (sections in first-appearance order, row errors).

    base_form = FORM_DEFAULTS updated with the Settings overrides. Section forms are in display
    units (strings, as page fields); demands are converted to engine units (kip, kip-in)."""
    header = [h.strip().lower() for h in rows[0]] if rows else []
    cols = {c.header.lower(): c for c in INPUT_COLUMNS}
    idx = {cols[h].key: i for i, h in enumerate(header) if h in cols}
    col_by_key = {c.key: c for c in INPUT_COLUMNS}

    sections: dict[str, Section] = {}
    first_vals: dict[str, dict] = {}
    first_row: dict[str, int] = {}
    errors: list[RowError] = []
    bad: set[str] = set()

    def cell(r, key):
        i = idx.get(key)
        return r[i].strip() if i is not None and i < len(r) else ""

    for n, r in enumerate(rows[1:]):
        row_no = INPUT_FIRST_DATA_ROW + n
        if all(not c.strip() for c in r):
            continue
        sid = cell(r, "section_id")
        if not sid:
            errors.append(RowError(row_no, "", f"row {row_no}: Section ID is blank"))
            continue

        def err(msg, sid=sid, row_no=row_no):
            errors.append(RowError(row_no, sid, f"row {row_no}, {msg}"))
            bad.add(sid)

        new = sid not in sections
        if new:
            try:
                st = parse_cell(col_by_key["sectionType"], cell(r, "sectionType"))
            except CellError as e:
                err(f"Section type: {e}")
                st = None
            sections[sid] = Section(sid, st, dict(base_form))
            first_vals[sid], first_row[sid] = {}, row_no
        sec = sections[sid]
        if not new:
            st_cell = cell(r, "sectionType")
            if st_cell and sec.sec_type and st_cell.upper() != sec.sec_type:
                err(f"Section type: differs from the first row of section {sid} (row {first_row[sid]})")
        for col in INPUT_COLUMNS:
            if col.key in ("section_id", "sectionType") or col.key in DEMAND_KEYS:
                continue
            if sec.sec_type is None or sec.sec_type not in col.applies:
                continue
            text = cell(r, col.key)
            if not new:
                if text:
                    try:
                        v = parse_cell(col, text)
                    except CellError as e:
                        err(f"{col.header}: {e}")
                        continue
                    if col.key not in first_vals[sid]:
                        # the first row left it blank (default / ASTM value), so this value would be ignored
                        err(f"{col.header}: set here but blank on the first row of section {sid} "
                            f"(row {first_row[sid]}); put section properties on its first row")
                    elif not _same(v, first_vals[sid][col.key]):
                        err(f"{col.header}: differs from the first row of section {sid} (row {first_row[sid]})")
                continue
            if not text:
                if col.required:
                    err(f"{col.header}: required for {sec.sec_type}")
                elif col.key in ("fy", "fy_trans"):
                    sec.form[col.key] = _astm_fy(base_form, units)
                    sec.form[col.key + "_ovr"] = False
                elif col.kind not in UNIT_KINDS and col.default is not None:
                    sec.form[col.key] = col.default  # unit-bearing blanks keep the converted base form
                continue
            try:
                v = parse_cell(col, text)
            except CellError as e:
                err(f"{col.header}: {e}")
                continue
            sec.form[col.key] = v
            first_vals[sid][col.key] = v
            if col.key in ("fy", "fy_trans"):
                sec.form[col.key + "_ovr"] = True
        if sec.sec_type:
            sec.form["sectionType"] = sec.sec_type
        demand = {}
        for key in DEMAND_KEYS:
            text = cell(r, key)
            try:
                v = float(parse_cell(col_by_key[key], text)) if text else 0.0
            except CellError as e:
                err(f"{col_by_key[key].header}: {e}")
                v = 0.0
            demand[key] = to_engine(v, col_by_key[key].kind, units)
        sec.demands.append(demand)
        sec.row_numbers.append(row_no)

    good = [s for s in sections.values() if s.id not in bad]
    return good, errors


def default_base_form(settings_form: dict, units: dict = DEFAULT_UNITS) -> dict:
    f = form_defaults_for(units)
    f.update(settings_form)
    return apply_section_class(f)  # NP: the page zeroes the strand inputs (updatePTFields)
