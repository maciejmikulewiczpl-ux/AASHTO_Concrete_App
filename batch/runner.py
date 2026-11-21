"""Batch run loop: Inputs/Settings TSV -> engine per (section, load row) -> Results TSV + project.

Each demand row is run as the app's ACTIVE row (calculate_all(inputs, all_rows, i)), because the
detailed flexure / shear / torsion blocks exist only for the active row — this is what the app
shows when the user clicks that row. Every value written comes from the engine result dicts; the
batch layer only selects (shear method) and forms the D/C ratios the app's table shows.
"""
from __future__ import annotations

import math
import os
import traceback

import calc_engine
import mphi_engine
from batch.columns import INPUT_COLUMNS, INPUT_FIRST_DATA_ROW, RESULT_COLUMNS, unit_label
from batch.form import from_engine
from batch.inputs import inputs_from_form
from batch.project import build_project, state_from_form, write_project
from batch.sheet_io import default_base_form, group_rows, parse_settings, read_tsv

_METHOD_K = {"simp": 1, "gp": 2, "b5": 3}


def _get(ctx: dict, path: str):
    cur = ctx
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _dc(demand: float, capacity) -> float | str | None:
    """setDC (index.html ~3000): 0/0 -> blank, capacity 0 -> 'inf'."""
    if capacity is None:
        return None
    if capacity == 0 and demand == 0:
        return None
    if capacity == 0:
        return "inf"
    return abs(demand) / abs(capacity)


def _fmt(v, kind: str, units: dict) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        if not math.isfinite(v):
            return "inf" if v > 0 else ("-inf" if v < 0 else "")
        if kind not in ("text", "dimensionless") and not kind.startswith("fixed:"):
            v = from_engine(v, kind, units)
        return format(v, ".10g")
    return str(v).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _calc_fields(res, rr, mp, demand, method, status_parts):
    k = _METHOD_K[method]
    sh = res.get("shear", {})
    vr = rr.get(f"Vr{k}")
    calc = {"shear_method": method, "Vr": vr,
            "beta": sh.get(f"bt{k}"), "theta": sh.get(f"th{k}"),
            "Vc": sh.get(f"Vc{k}"), "Vs": sh.get(f"Vs{k}"),
            "long_dc": rr.get(f"long_dc_{k}"), "long_ok": rr.get(f"long_ok_{k}"),
            "dc_M": _dc(demand["Mu"], abs(rr["Mr"]) if rr.get("Mr") is not None else None),
            "dc_V": _dc(demand["Vu"], vr),
            "dc_T": _dc(demand["Tu"], rr.get("Tr"))}
    notes = []
    if not mp.get("available", False):
        notes.append(mp.get("reason", "M-phi not available"))
    if mp.get("service_error"):
        notes.append(mp["service_error"])
    notes += mp.get("notes", [])
    calc["mphi_note"] = "; ".join(notes)
    svc = mp.get("service") or {}
    if svc.get("Ieff") is not None and mp.get("Ig"):
        calc["mphi_Ieff_Ig_service"] = svc["Ieff"] / mp["Ig"]
    for key in ("dc_M", "dc_V", "dc_T"):
        v = calc[key]
        if v == "inf" or (isinstance(v, float) and v > 1.0):
            status_parts.append(key)
    if rr.get("flexStatus") in ("NG", "MIN"):
        status_parts.append("flexure " + rr["flexStatus"])
    if rr.get("crackStatus") == "NG":
        status_parts.append("crack control")
    if rr.get("shearStatus") == "NG":
        status_parts.append("shear (engine)")
    return calc


def _run_section(sec, units, run):
    """-> list of per-row contexts {res, row, mphi, calc}. Raises on engine failure."""
    inputs = inputs_from_form(sec.form, units)
    rows = [dict(d, Vp=0, x=None, dp=None, fpe=None, load_case="service_I_full") for d in sec.demands]
    m = run["mphi"]
    out = []
    for i, demand in enumerate(rows):
        res = calc_engine.calculate_all(inputs, rows, i)
        rr = res["row_results"][i]
        try:
            mp = mphi_engine.moment_curvature_section(
                inputs, Ms=demand["Ms"], Ps=demand["Ps"], model=m["model"],
                expected_concrete=m["expected_concrete"], expected_steel=m["expected_steel"])
        except Exception as e:  # M-phi problems are notes, never a section failure
            mp = {"available": False, "reason": f"M-phi failed: {e}"}
        if not mp.get("available", False):
            mp = {"available": False, "reason": mp.get("reason", "")}
        parts = []
        calc = _calc_fields(res, rr, mp, demand, run["shearCapacityMethod"], parts)
        calc["status"] = "NG" if parts else "OK"
        calc["message"] = ("Not satisfied: " + ", ".join(parts)) if parts else ""
        row_ctx = dict(rr)
        if row_ctx.get("Mr") is not None:
            row_ctx["Mr"] = abs(row_ctx["Mr"])
        out.append({"res": res, "row": row_ctx, "mphi": mp, "calc": calc})
    return out


def _write_progress(path, text):
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        pass


def run_batch(inputs_tsv: str, settings_tsv: str, results_tsv: str, progress_path: str | None = None,
              default_project_path: str | None = None) -> dict:
    settings_form, units, run = parse_settings(read_tsv(settings_tsv))
    rows = read_tsv(inputs_tsv)
    sections, errors = group_rows(rows, default_base_form(settings_form, units), units)

    by_row: dict[int, dict] = {}
    row_errors: dict[int, list[str]] = {}
    bad_ids: dict[str, list[str]] = {}
    for e in errors:
        row_errors.setdefault(e.row, []).append(e.message)
        if e.section_id:
            bad_ids.setdefault(e.section_id, []).append(e.message)

    states = {}
    for n, sec in enumerate(sections, 1):
        _write_progress(progress_path, f"{n}/{len(sections)} {sec.id}")
        try:
            ctxs = _run_section(sec, units, run)
        except Exception as e:
            msg = f"engine error: {e}"
            bad_ids.setdefault(sec.id, []).append(msg)
            traceback.print_exc()
            continue
        for row_no, ctx in zip(sec.row_numbers, ctxs):
            by_row[row_no] = ctx
        states[sec.id] = state_from_form(sec.form, sec.demands, units)

    # Output: one line per input data row, same order; blank lines stay blank.
    id_idx = next((i for i, h in enumerate(rows[0]) if h.strip().lower() ==
                   INPUT_COLUMNS[0].header.lower()), 0) if rows else 0
    header = [c.header for c in RESULT_COLUMNS]
    lines = [header, [unit_label(c.kind, units) if c.kind != "text" else "" for c in RESULT_COLUMNS]]
    n_rows = n_err = 0
    for i, r in enumerate(rows[1:]):
        row_no = INPUT_FIRST_DATA_ROW + i
        if all(not c.strip() for c in r):
            lines.append([""] * len(header))
            continue
        n_rows += 1
        sid = r[id_idx].strip() if id_idx < len(r) else ""
        ctx = by_row.get(row_no)
        if ctx is None or sid in bad_ids:
            n_err += 1
            msgs = row_errors.get(row_no) or bad_ids.get(sid) or ["not run"]
            ctx = {"calc": {"status": "ERROR", "message": "; ".join(msgs)}}
        ctx["calc"]["section_id"] = sid
        ctx["calc"]["input_row"] = str(row_no)
        lines.append([_fmt(_get(ctx, c.source), c.kind, units) for c in RESULT_COLUMNS])
    with open(results_tsv, "w", encoding="utf-8", newline="") as fh:
        fh.write("\r\n".join("\t".join(x) for x in lines) + "\r\n")

    summary = {"sections": len(sections) + len({e.section_id for e in errors if e.section_id} - {s.id for s in sections}),
               "rows": n_rows, "errors": n_err, "project": None, "project_error": ""}
    project_path = run.get("project_path") or default_project_path
    if states and project_path:
        run_opts = {"shearCapacityMethod": run["shearCapacityMethod"], "mphi": run["mphi"]}
        try:
            summary["project"] = write_project(project_path, build_project(states, units, run_opts),
                                               run["overwrite_project"])
        except (OSError, FileExistsError) as e:
            summary["project_error"] = f"Project file not written: {e}" if not isinstance(
                e, FileExistsError) else f"Project file not written: file exists ({project_path})"
    _write_progress(progress_path, f"{len(sections)}/{len(sections)} done")
    return summary
