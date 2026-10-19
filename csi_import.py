"""CSiBridge "Element Forces - Frames" clipboard parser (stdlib only).

Assumption: unit "tonf" is the metric tonne-force (1000 kgf = 9.80665 kN),
CSiBridge's metric unit, not the short ton.

Parses, converts to kip / kip-in / inch, de-duplicates sub-element station
duplicates and flags Max/Min envelope rows.  No grouping or reduction here.
"""
import math
import re
from dataclasses import dataclass, field

DEFAULT_UNITS = {"force": "kip", "moment": "kip-ft", "length": "ft"}

_LBF_N = 4.4482216152605
_FORCE_KIP = {  # to kip
    "kip": 1.0, "kips": 1.0, "k": 1.0,
    "lb": 1.0 / 1000.0, "lbf": 1.0 / 1000.0,
    "n": 1.0 / (_LBF_N * 1000.0), "kn": 1.0 / _LBF_N,
    "tonf": 9.80665 / _LBF_N,  # metric tonne-force (CSi); see report
}
_LEN_IN = {"in": 1.0, "ft": 12.0, "m": 1.0 / 0.0254, "mm": 1.0 / 25.4}

_REQUIRED = ["frame", "station", "outputcase", "p", "v2", "v3", "t", "m2", "m3"]
_FORCE_COLS = ("p", "v2", "v3")
_MOMENT_COLS = ("t", "m2", "m3")
_NUMERIC = ("station",) + _FORCE_COLS + _MOMENT_COLS
_CANON = {"frame": "Frame", "station": "Station", "outputcase": "OutputCase",
          "p": "P", "v2": "V2", "v3": "V3", "t": "T", "m2": "M2", "m3": "M3"}


@dataclass
class ForceRow:
    frame: str
    station_in: float
    case: str
    case_type: str
    step_type: str
    P: float
    V2: float
    V3: float
    T: float
    M2: float
    M3: float
    envelope: bool
    src_line: int


@dataclass
class ParseResult:
    rows: list = field(default_factory=list)
    cases: list = field(default_factory=list)
    frames: list = field(default_factory=list)
    units: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    n_envelope: int = 0


_CANON_UNIT = {"kips": "kip", "k": "kip", "lbf": "lb", "kn": "kN", "n": "N"}


def _canon_unit(u):
    return "-".join(_CANON_UNIT.get(p, p) for p in u.strip().lower().split("-"))


def _split(line):
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    return [c.strip() for c in re.split(r"\s{2,}", line.strip())]


_THOUSANDS = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d*)?$")


def _num(s):
    """Parse a numeric cell; commas only as valid thousands grouping."""
    t = s.strip()
    if "," in t:
        if not _THOUSANDS.match(t):
            raise ValueError(
                f"'{s}': comma is not valid thousands grouping "
                "(decimal comma / non-US locale is not supported)")
        t = t.replace(",", "")
    v = float(t)
    if not math.isfinite(v):
        raise ValueError(f"'{s}': non-finite value")
    return v


def _is_num(s):
    try:
        float(s.replace(",", ""))
        return True
    except ValueError:
        return False


def _force_factor(unit, col):
    f = _FORCE_KIP.get(unit.strip().lower())
    if f is None:
        raise ValueError(f"Unknown unit '{unit}' in column {col}")
    return f


def _length_factor(unit, col):
    f = _LEN_IN.get(unit.strip().lower())
    if f is None:
        raise ValueError(f"Unknown unit '{unit}' in column {col}")
    return f


def _moment_factor(unit, col):
    parts = unit.strip().lower().split("-")
    if len(parts) != 2:
        raise ValueError(f"Unknown unit '{unit}' in column {col}")
    try:
        return _force_factor(parts[0], col) * _length_factor(parts[1], col)
    except ValueError:
        raise ValueError(f"Unknown unit '{unit}' in column {col}") from None


def parse_csi_frame_forces(text, default_units=None):
    dflt = dict(DEFAULT_UNITS)
    if default_units:
        dflt.update(default_units)
    lines = re.split(r"\r\n|\n|\r", text)
    res = ParseResult()

    hi = next((i for i, ln in enumerate(lines)
               if "frame" in ln.lower() and "outputcase" in ln.lower()), None)
    if hi is None:
        raise ValueError("Header row not found (needs Frame and OutputCase columns)")

    # header: name -> (index, unit-from-header-cell)
    cols, hdr_units = {}, {}
    for idx, cell in enumerate(_split(lines[hi])):
        bits = cell.split(None, 1)
        if not bits:
            continue
        name = bits[0].lower()
        if name not in cols:
            cols[name] = idx
            if len(bits) > 1:
                hdr_units[name] = bits[1].strip()
    missing = [_CANON[c] for c in _REQUIRED if c not in cols]
    if missing:
        raise ValueError("Missing required column(s): " + ", ".join(missing))

    # optional units row: next non-blank line whose P cell is non-numeric
    start = hi + 1
    row_units, have_units_row = {}, False
    j = hi + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j < len(lines):
        cells = _split(lines[j])
        pi = cols["p"]
        if pi < len(cells) and not _is_num(cells[pi]):
            have_units_row = True
            start = j + 1
            for name in _NUMERIC:
                i = cols[name]
                if i < len(cells) and cells[i]:
                    row_units[name] = cells[i]

    # resolve units per numeric column
    factor, unit_name = {}, {}
    missing_any = False
    for name in _NUMERIC:
        kind = ("length" if name == "station" else
                "force" if name in _FORCE_COLS else "moment")
        u = row_units.get(name) if have_units_row else None
        if u is None:
            u = hdr_units.get(name)
        if u is None:
            u = dflt[kind]
            if have_units_row:
                res.warnings.append(
                    f"Units row has no unit for column {_CANON[name]}; "
                    f"using default '{u}'")
            else:
                missing_any = True
        fn = {"length": _length_factor, "force": _force_factor,
              "moment": _moment_factor}[kind]
        factor[name] = fn(u, _CANON[name])
        unit_name[name] = _canon_unit(u)
    if not have_units_row and missing_any:
        res.warnings.append("No units row found; using default units "
                            f"({dflt['force']}, {dflt['moment']}, {dflt['length']})")
    res.units = {"force": unit_name["p"], "moment": unit_name["m3"],
                 "length": unit_name["station"],
                 "columns": {_CANON[n]: unit_name[n] for n in
                             ("p", "v2", "v3", "t", "m2", "m3", "station")}}

    def cell(cells, name):
        i = cols.get(name)
        return cells[i] if i is not None and i < len(cells) else ""

    kept = {}  # key -> list of ForceRow
    order = []
    bad = []
    for n in range(start, len(lines)):
        ln = lines[n]
        if not ln.strip():
            continue
        cells = _split(ln)
        vals, errs = {}, []
        for k in _NUMERIC:
            try:
                vals[k] = _num(cell(cells, k)) * factor[k]
            except ValueError as e:
                errs.append(f"column {_CANON[k]}: {e}")
        if errs:
            bad.append(f"line {n + 1}: " + "; ".join(errs))
            continue
        step = cell(cells, "steptype")
        row = ForceRow(
            frame=cell(cells, "frame"), station_in=vals["station"],
            case=cell(cells, "outputcase"), case_type=cell(cells, "casetype"),
            step_type=step, P=vals["p"], V2=vals["v2"], V3=vals["v3"],
            T=vals["t"], M2=vals["m2"], M3=vals["m3"],
            envelope=step.strip().lower() in ("max", "min"), src_line=n + 1)
        key = (row.frame, round(row.station_in / 12.0, 4), row.case, step)
        bucket = kept.setdefault(key, [])
        if not bucket:
            order.append(key)
        nums = (row.P, row.V2, row.V3, row.T, row.M2, row.M3)
        if any(all(math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
                   for a, b in zip(nums, (o.P, o.V2, o.V3, o.T, o.M2, o.M3)))
               for o in bucket):
            continue
        if bucket:
            res.warnings.append(
                f"Line {n + 1}: duplicate key (frame {row.frame}, station "
                f"{key[1]} ft, case {row.case}, {step or 'no step'}) with "
                "different values; both kept")
        bucket.append(row)

    if bad:
        raise ValueError("Unparseable data line(s): " + " | ".join(bad))
    res.rows = [r for k in order for r in kept[k]]
    for r in res.rows:
        if r.case not in res.cases:
            res.cases.append(r.case)
        if r.frame not in res.frames:
            res.frames.append(r.frame)
    res.n_envelope = sum(r.envelope for r in res.rows)
    return res
