"""Column-on-Shaft orchestrator (Task 8): `run_colshaft(payload) -> dict`.

Takes the raw CSiBridge "Element Forces - Frames" paste plus the bent / settings
tables and returns everything the Column-on-Shaft UI and report need, strictly
JSON-serialisable (no NaN / Infinity: non-finite floats become None).

Per bent (spec 4.3-4.5, controller rulings 8-1 .. 8-11):
  1. Demand rows: Strength rows of the column (and shaft) frames, reduced by the
     envelope mode ("station" -> prune_dominated, "member" -> collapse_member).
  2. Column LRFD design (colshaft_lrfd.design_member, rho_l limits from the
     selected provisions), with the slenderness screen as `transform`.
  3. Column seismic: Mo from the FINAL column cage; final transverse = override,
     else the larger Av/s of (LRFD, seismic required_transverse), iterated until
     the choice is stable (Mo depends slightly on the transverse cage).
  4. Shaft LRFD: pasted shaft frames, or (soil basis, no shaft frames) the column
     base Strength rows taken through the p-y model (colshaft_shaft, ruling 8-1).
  5. Shaft seismic sizing (ruling 8-2): step the shaft longitudinal (As order)
     until the capacity-protection flexure check passes, then the transverse
     (transverse_candidates order, Av/s >= the LRFD one) until the shaft shear and
     confinement checks pass.
  6. Re-run check_cage (LRFD rows) and seismic_design on the final cages.
Status precedence: NO SOLUTION > REFINED ANALYSIS REQUIRED > NG > OK.  Overrides
are never altered; with an override the status reflects the checks.

Units kip, in, ksi; moments kip-in.  App sign convention Pu < 0 = compression.
No AASHTO citation is added here; check references come from the modules.
"""
from __future__ import annotations

import dataclasses
import math
import re

import calc_engine as ce
import colshaft_demands as cd
import colshaft_lrfd as cl
import colshaft_seismic as cs
import colshaft_shaft as csh
import colshaft_slender as csl
import csi_import as ci
from colshaft_shaft import (SHAFT_FLEX, SHAFT_TRANS, checks_ok, full_cage, long_cage, py_check,
                            py_rows, trans_cage)
from seismic_port.provisions import PROVISIONS, _KEY_ALIASES, get_provisions

ENVELOPE_MODES = ("station", "member")
STATUS_RANK = {"OK": 0, "NG": 1, "REFINED ANALYSIS REQUIRED": 2, "NO SOLUTION": 3}
ROW_KEYS = ("Pu", "Mu", "Vu", "Tu", "_case", "_frame", "_station", "_step", "_bound", "_Pmin",
            "_Pmax", "_source", "_base_Mu", "_base_Vu", "_klr2", "_klr3", "_slender_limit2",
            "_slender_limit3", "_slender_status")
RES_KEYS = ("Mr", "flexStatus", "_flexP", "_flexDC", "Vr2", "shearStatus", "Tr",
            "torsionConsider", "long_ok_2", "long_dc_2", "epsS")
MAX_COL_ITER = 4


# ─── Small utilities ────────────────────────────────────────────────

def validate_code(code):
    """Provisions for a known key or alias (ruling 8-4: no silent fallback)."""
    if not isinstance(code, str) or (code not in PROVISIONS and code not in _KEY_ALIASES):
        known = sorted(set(PROVISIONS) | set(_KEY_ALIASES))
        raise ValueError(f"Unknown seismic code {code!r}; expected one of {known}")
    return get_provisions(code)


CATEGORIES = {c.lower(): c for c in ("Strength", "Extreme", "Dead", "Ignore")}


def validate_categories(given, cases):
    """{case: category} for every parsed case: the user's value (case-insensitive,
    normalised) or the default by name; any other value -> ValueError."""
    given = given or {}
    out = {}
    for c in cases:
        v = given.get(c)
        if v in (None, ""):
            out[c] = cd.default_case_category(c)
            continue
        n = CATEGORIES.get(str(v).strip().lower())
        if n is None:
            raise ValueError(f"Unknown load-case category {v!r} for case {c!r}; expected one of "
                             f"{sorted(CATEGORIES.values())}")
        out[c] = n
    return out


def sanitize(obj):
    """Recursively convert to JSON-safe types; non-finite floats -> None (ruling 8-5)."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        if isinstance(obj, cs.Check):
            return check_dict(obj)
        return sanitize({f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)})
    if isinstance(obj, dict):
        return {str(k): sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return str(obj)


def check_dict(c, group="Seismic"):
    r = c.ratio
    d = {"group": group, "name": c.name, "demand": c.demand, "capacity": c.capacity,
         "ratio": r if math.isfinite(r) else None, "ok": bool(c.ok), "detail": c.detail,
         "ref": c.ref}
    if not math.isfinite(r):
        d["ratio_infinite"] = True
    return sanitize(d)


def _dedupe(seq):
    seen, out = set(), []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _same_trans(a, b):
    return (a["bar"], round(a["s"], 4), a["ties"]) == (b["bar"], round(b["s"], 4), b["ties"])


def rho_l_check(lg, prov, who="Column"):
    """Longitudinal ratio within the selected provisions' rho_l limits (the ref
    cites them).  Always for the column; for the shaft only when its longitudinal
    is overridden (the LRFD search / sizing already honour the limits)."""
    lo, hi, r = prov.rho_l_min, prov.rho_l_max, lg["rho_l"]
    ok = lo - 1e-9 <= r <= hi + 1e-9
    ratio = max(lo / r if r > 0 else math.inf, r / hi)
    return {"group": "Seismic", "name": f"{who} longitudinal ratio (rho_l)", "demand": lo,
            "capacity": r, "ratio": ratio if math.isfinite(ratio) else None,
            "ok": ok, "detail": f"{lo:g} <= rho_l = {r:.4f} <= {hi:g}",
            "ref": prov.ref_longitudinal}


def rows_pass(member, cage, rows, transform):
    """Every LRFD row passes on `cage` (the search criterion, see row_ok)."""
    res = cl.check_cage(member, cage, rows, transform)
    return all(row_ok(x, r) for x, r in zip(res, rows))


def row_ok(res, row):
    return (res.get("flexStatus") != "NG" and res.get("shearStatus") in ("OK", "NR")
            and (not res.get("torsionConsider") or res.get("Tr", 0) >= abs(row["Tu"]))
            and res.get("long_ok_2") is not False)


def _ratio(res, row):
    out = [res.get("_flexDC") or 0.0]
    vr = res.get("Vr2") or 0.0
    out.append(abs(row["Vu"]) / vr if vr > 0 else (math.inf if row["Vu"] else 0.0))
    if res.get("torsionConsider") and abs(row["Tu"]) > 0:
        tr = res.get("Tr") or 0.0
        out.append(abs(row["Tu"]) / tr if tr > 0 else math.inf)
    if res.get("long_dc_2") is not None:
        out.append(res["long_dc_2"])
    return max(out)


def lrfd_check_rows(member, cage, rows, transform, group):
    """check_cage on the final cage -> (row summaries, final_checks entries, transformed rows)."""
    res = cl.check_cage(member, cage, rows, transform)
    rows_t = rows
    if transform is not None:
        raw = cl.cage_inputs(cl.base_circ_inputs(member), cage)
        rows_t = transform(dict(cage, inputs=raw), [dict(r) for r in rows])
    summ, checks = [], []
    for i, (r, x) in enumerate(zip(rows_t, res)):
        ok = row_ok(x, r)
        ratio = _ratio(x, r)
        s = {k: r[k] for k in ROW_KEYS if k in r}
        s.update({k: x.get(k) for k in RES_KEYS})
        s.update(ok=ok, ratio=ratio)
        summ.append(s)
        st = r.get("_station")
        where = f"{r.get('_frame')} @ {st / 12.0:g} ft" if isinstance(st, (int, float)) else \
            (r.get("_source") or str(r.get("_frame")))
        checks.append({"group": group, "name": f"Row {i + 1}: {r.get('_case')} ({where})",
                       "demand": None, "capacity": None,
                       "ratio": ratio if math.isfinite(ratio) else None, "ok": ok,
                       "detail": (f"flexure {x.get('flexStatus')} (D/C {x.get('_flexDC') or 0:.3f} at "
                                  f"P={x.get('_flexP') or 0:.0f} kip), shear {x.get('shearStatus')}, "
                                  f"torsion {'considered' if x.get('torsionConsider') else 'neglected'}, "
                                  f"long. V+T {'OK' if x.get('long_ok_2') is not False else 'NG'}"),
                       "ref": ""})
    return summ, checks, rows_t


# ─── Demand rows / axial ────────────────────────────────────────────

def reduce_rows(rows, mode):
    """Envelope mode (ruling 8-8): station -> prune_dominated, member -> collapse_member."""
    if not rows:
        return []
    return cd.collapse_member(rows) if mode == "member" else cd.prune_dominated(rows)


def base_station(rows, frames, cats, base_end, warnings=None):
    """(bottom frame, base station in) of a column stack."""
    st = cd.column_stack(rows, frames, warnings, cats)
    if not st:
        return None, None
    f, be = st[0]
    if base_end in ("min", "max"):
        be = base_end
    sts = [r.station_in for r in rows if r.frame == f]
    return f, (min(sts) if be == "min" else max(sts))


_PARTIAL_DEAD = re.compile(r"^(DC|DW|SW|SELF)", re.IGNORECASE)


def seismic_axial(bent, rows, frames, cats, base_end, warnings):
    """P_dead / P_ext_min / P_ext_max (app convention) at the base station of the
    bottom column frame.  Ruling 8-14: P_dead = SUM over the Dead-category cases of
    each case's most compressive base axial (spec 4.4 "sum of Dead rows"); none ->
    bent["P_dead"], else ValueError.  Ruling 8-10: P_ext_min / max = min / max of
    every Extreme base axial (Max and Min rows); none -> P_dead for both."""
    bf, bst = base_station(rows, frames, cats, base_end, warnings)
    at = [r for r in rows if bf is not None and r.frame == bf
          and math.isclose(r.station_in, bst, abs_tol=1e-6)]
    dead = {}
    for r in at:
        if cd._cat(r.case, cats) == "Dead":
            dead[r.case] = min(dead.get(r.case, r.P), r.P)
    if dead:
        P_dead = sum(dead.values())
        if len(dead) == 1 and _PARTIAL_DEAD.match(next(iter(dead))) and warnings is not None:
            warnings.append(f"P_dead from the single Dead case '{next(iter(dead))}'; categorise "
                            "any other dead-load cases (e.g. DW) as Dead to include them")
    elif bent.get("P_dead") is not None:
        P_dead = float(bent["P_dead"])
    else:
        raise ValueError(f"Bent {bent.get('name')}: no Dead rows at the column base; "
                         "enter P_dead (kip, compression negative)")
    ext = [r.P for r in at if cd._cat(r.case, cats) == "Extreme"]
    lo, hi = (min(ext), max(ext)) if ext else (P_dead, P_dead)
    return {"P_dead": P_dead, "P_ext_min": lo, "P_ext_max": hi,
            "dead_cases": {c: p for c, p in dead.items()}, "n_extreme": len(ext)}


# ─── LRFD member design with overrides ──────────────────────────────

def lrfd_member(member, rows, params, transform, ov_long, ov_trans):
    """(LongResult, TransResult) honouring overrides (an override is never designed)."""
    D = float(member["D"])
    if ov_long:
        c = long_cage(ov_long["bar"], ov_long["n"], ov_long.get("bundle", 1), D)
        lg = cl.LongResult(True, c["bar"], c["n"], c["bundle"], c["Ast"], c["rho_l"],
                           math.nan, None, "override")
        if ov_trans:
            return lg, None
        return lg, cl.design_transverse(member, lg, rows, params, transform)
    if ov_trans:
        m = dict(member, trans_bar=int(ov_trans["bar"]), trans_s=float(ov_trans["s"]),
                 ties=int(ov_trans.get("ties", 0) or 0))
        return cl.design_longitudinal(m, rows, params, transform), None
    return cl.design_member(member, rows, params, transform)


def _ov_long(ov, D):
    return long_cage(ov["bar"], ov["n"], ov.get("bundle", 1), D) if ov else None


def _ov_trans(ov):
    return trans_cage(ov["bar"], ov["s"], ov.get("ties", 0)) if ov else None


# ─── Bent run ───────────────────────────────────────────────────────

def run_bent(bent, pr, cats, prov, params, settings, mode):
    name = str(bent.get("name") or "")
    w = []
    nosol = []
    col_frames = [str(f) for f in (bent.get("col_frames") or [])]
    shaft_frames = [str(f) for f in (bent.get("shaft_frames") or [])]
    if not col_frames:
        raise ValueError(f"Bent {name}: no column frames given")
    for f in col_frames + shaft_frames:
        if f not in pr.frames:
            w.append(f"frame {f} not found in the paste")
    column, shaft = dict(bent["column"]), dict(bent["shaft"])
    Dc, Ds = float(column["D"]), float(shaft["D"])
    ov = bent.get("override") or {}
    rows_all = pr.rows
    base_end = bent.get("base_end") or "auto"

    H = bent.get("H_in")
    H = float(H) if H not in (None, "") else cd.column_height_in(rows_all, col_frames)
    if not H > 0:
        raise ValueError(f"Bent {name}: column height H is 0; enter H_in")
    axial = seismic_axial(bent, rows_all, col_frames, cats, base_end, w)
    soil = bent.get("soil")
    basis = bent.get("shaft_basis") or ("soil" if soil else "cantilever")
    sbent = dict(bent, H_in=H, shaft_basis=basis)

    col_raw = cd.demand_rows(rows_all, col_frames, cats, "Strength", w)
    col_rows = reduce_rows(col_raw, mode)
    if not col_rows and not (ov.get("col_long") and ov.get("col_trans")):
        raise ValueError(f"Bent {name}: no Strength rows for column frames {col_frames}")

    slender_on = bool(settings.get("slenderness_on"))
    rbc = {"rows": rows_all, "frames": col_frames, "categories": cats}

    def transform_for(Df):
        if not slender_on:
            return None
        if not bent.get("slender"):
            raise ValueError(f"Bent {name}: slenderness is on but bent.slender is missing")
        return csl.make_magnifier(dict(bent, lu_default_in=H + Df), rbc, settings)

    # design pass: Df is known up front only for the cantilever basis; the
    # transform only tags rows (S6), so the final check below is authoritative
    L_eq = bent.get("L_eq_in")
    Df0 = float(L_eq) if basis == "cantilever" and L_eq is not None else 0.0
    tf_design = transform_for(Df0)

    # ── column LRFD ──
    col_lg, col_tr = lrfd_member(column, col_rows, params, tf_design,
                                 ov.get("col_long"), ov.get("col_trans"))
    lrfd = {"col": {"long": col_lg, "trans": col_tr, "n_rows": len(col_rows),
                    "n_rows_raw": len(col_raw)}, "shaft": None}
    if col_lg is not None and not col_lg.ok and not ov.get("col_long"):
        nosol.append("Column LRFD longitudinal: " + col_lg.note)
    if col_tr is not None and not col_tr.ok:
        if ov.get("col_long"):      # designed against the user's cage: the checks decide (NG)
            w.append("Column LRFD transverse for the longitudinal override: " + col_tr.note)
        else:
            nosol.append("Column LRFD transverse: " + col_tr.note)
    col_long = _ov_long(ov.get("col_long"), Dc) or (
        long_cage(col_lg.bar, col_lg.n, col_lg.bundle, Dc) if col_lg and col_lg.bar else None)
    col_trans_lrfd = _ov_trans(ov.get("col_trans")) or (
        trans_cage(col_tr.bar, col_tr.s, col_tr.ties) if col_tr and col_tr.bar else None)
    source = {"col_long": "Override" if ov.get("col_long") else "LRFD",
              "col_trans": "Override" if ov.get("col_trans") else "LRFD"}
    if col_long is None or col_trans_lrfd is None:
        return _bent_result(name, "NO SOLUTION", lrfd, None, None, source, [], nosol, w, axial, H)

    # ── shaft start cage (pasted shaft frames are designed now) ──
    sh_cands = csh.long_candidates(shaft, params)
    if not sh_cands and not ov.get("shaft_long"):
        nosol.append("Shaft longitudinal: no cage fits the bar-size / spacing / rho_l range")
        return _bent_result(name, "NO SOLUTION", lrfd, None, None, source, [], nosol, w, axial, H)
    sh_rows, sh_src = [], None
    if shaft_frames:
        sh_rows = reduce_rows(cd.demand_rows(rows_all, shaft_frames, cats, "Strength", w), mode)
        sh_src = "shaft frames"
    sh_lg = sh_tr = None

    def shaft_lrfd(rows):
        lg, tr = lrfd_member(shaft, rows, params, None, ov.get("shaft_long"), ov.get("shaft_trans"))
        if lg is not None and not lg.ok and not ov.get("shaft_long"):
            nosol.append("Shaft LRFD longitudinal: " + lg.note)
        if tr is not None and not tr.ok:
            if ov.get("shaft_long"):
                w.append("Shaft LRFD transverse for the longitudinal override: " + tr.note)
            else:
                nosol.append("Shaft LRFD transverse: " + tr.note)
        return lg, tr
    if sh_rows:
        sh_lg, sh_tr = shaft_lrfd(sh_rows)

    def shaft_start():
        lgc = _ov_long(ov.get("shaft_long"), Ds)
        if lgc is None and sh_lg is not None and sh_lg.bar:
            lgc = long_cage(sh_lg.bar, sh_lg.n, sh_lg.bundle, Ds)
        if lgc is None:
            a = sh_cands[0]
            lgc = long_cage(a[3], a[1], a[2], Ds)
        trc = _ov_trans(ov.get("shaft_trans"))
        if trc is None and sh_tr is not None and sh_tr.bar:
            trc = trans_cage(sh_tr.bar, sh_tr.s, sh_tr.ties)
        if trc is None:
            t = cl._member_trans(shaft)
            trc = trans_cage(t["trans_bar"], t["s"], t["ties"])
        return lgc, trc

    mc_cache = {}

    def seis(col_c, sh_c):
        return cs.seismic_design(column, shaft, col_c, sh_c, axial, sbent, prov, params=params,
                                 mc_cache=mc_cache)

    sh_long, sh_trans = shaft_start()

    # ── column seismic: final transverse (rulings 8-3 / 8-15) ──
    col_trans = col_trans_lrfd
    S = seis(full_cage(col_long, col_trans), full_cage(sh_long, sh_trans))
    seis_req_ok = True
    if not ov.get("col_trans"):
        for _ in range(MAX_COL_ITER):
            req = S.required_transverse
            if not req.get("ok"):
                seis_req_ok = False
                nosol.append("Column seismic transverse: no hoop/spiral in the search range meets "
                             "Column shear, Transverse steel ratio (min) and the detailing spacing")
                break
            pick, which = csh.merge_trans(col_trans_lrfd, trans_cage(req["bar"], req["s"],
                                                                     req["ties"]))
            if _same_trans(pick, col_trans):
                break
            col_trans = pick
            source["col_trans"] = "LRFD" if which == "a" else "Seismic"
            S = seis(full_cage(col_long, col_trans), full_cage(sh_long, sh_trans))

    # ── shaft LRFD rows through the pile (spec 4.4a, rulings 8-12 / 8-13) ──
    py_ctx = None
    if not shaft_frames and basis == "soil":
        bf, bst = base_station(rows_all, col_frames, cats, base_end, w)
        base_rows = [r for r in col_raw if r["_frame"] == bf
                     and math.isclose(r["_station"], bst, abs_tol=1e-6)]
        py_ctx = (base_rows, float(bent["L_embed_in"]), cs.soil_profile(soil),
                  tuple(float(b) for b in (bent.get("soil_bounds") or (2.0, 0.5))))
        sh_rows, _ = py_rows(py_ctx, S.EI_shaft, Ds)
        sh_src = csh.PY_SOURCE
        if sh_rows:
            sh_lg, sh_tr = shaft_lrfd(sh_rows)
            sh_long, sh_trans = shaft_start()
            S = seis(full_cage(col_long, col_trans), full_cage(sh_long, sh_trans))
    if sh_lg is not None or sh_tr is not None:
        lrfd["shaft"] = {"long": sh_lg, "trans": sh_tr, "n_rows": len(sh_rows), "source": sh_src}
    source["shaft_long"] = "Override" if ov.get("shaft_long") else ("LRFD" if sh_lg else "Seismic")
    source["shaft_trans"] = "Override" if ov.get("shaft_trans") else ("LRFD" if sh_tr else "Seismic")

    # ── shaft seismic sizing (ruling 8-2) ──
    col_full = full_cage(col_long, col_trans)
    if not ov.get("shaft_long") and not checks_ok(S, (SHAFT_FLEX,)):
        cands = [sh_long] + [long_cage(a[3], a[1], a[2], Ds) for a in sh_cands
                             if a[0] > sh_long["Ast"] + 1e-9]
        found = csh.size_shaft_long(cands, lambda c: seis(col_full, full_cage(c, sh_trans)))
        if found is None:
            nosol.append(f"{SHAFT_FLEX}: no shaft longitudinal cage up to "
                         f"{cands[-1]['n']}-{cands[-1]['bundle']}x#{cands[-1]['bar']} passes")
        elif found[0] is not sh_long:
            sh_long, S = found
            source["shaft_long"] = "Seismic"
    if not ov.get("shaft_trans") and not checks_ok(S, SHAFT_TRANS):
        found = csh.size_shaft_transverse(shaft, prov, S, sh_long, sh_trans, params,
                                          lambda t: seis(col_full, full_cage(sh_long, t)))
        if found is None:
            names = [c.name for c in S.checks if c.name in SHAFT_TRANS and not c.ok]
            nosol.append(f"{', '.join(names)}: no shaft transverse cage in the search range passes")
        else:
            sh_trans, S = found
            source["shaft_trans"] = "Seismic"

    # ── final cages (ruling 8-15): when the merged / upsized cage fails the LRFD
    # rows although the LRFD and seismic designs each passed, walk the transverse
    # candidates from it to the first one passing both ──
    S = seis(col_full, full_cage(sh_long, sh_trans))
    Df = S.Df
    if Df is None:
        Df = 0.0
        if slender_on:
            w.append("slenderness: interface basis has no fixity depth; lu default = H (Df = 0)"
                     if basis == "interface" else
                     "slenderness: no stable fixed-free p-y solve; lu default = H (Df = 0)")
    tf_final = transform_for(Df)
    skipped = []
    if py_ctx is not None:
        sh_rows, skipped = py_rows(py_ctx, S.EI_shaft, Ds)
    changed = False
    if (not ov.get("col_trans") and col_tr is not None and col_tr.ok and seis_req_ok
            and col_rows and not rows_pass(column, col_full, col_rows, tf_final)):
        t = csh.walk_trans(col_trans, params, lambda t: (
            csh.col_trans_screen(column, prov, S, col_long, t)
            and rows_pass(column, full_cage(col_long, t), col_rows, tf_final)))
        if t is None:
            nosol.append("Column transverse: no candidate from the merged cage on passes both "
                         "the LRFD rows and the seismic transverse criteria")
        else:
            col_trans, changed = t, True
            source["col_trans"] = "LRFD+Seismic"
    sh_full = full_cage(sh_long, sh_trans)
    if (not ov.get("shaft_trans") and sh_tr is not None and sh_tr.ok and sh_rows
            and not rows_pass(shaft, sh_full, sh_rows, None)):
        t = csh.walk_trans(sh_trans, params, lambda t: (
            csh.shaft_trans_screen(shaft, prov, S, sh_long, t)
            and rows_pass(shaft, full_cage(sh_long, t), sh_rows, None)))
        if t is None:
            nosol.append("Shaft transverse: no candidate from the upsized cage on passes both "
                         "the shaft LRFD rows and the shaft seismic checks")
        else:
            sh_trans, changed = t, True
            source["shaft_trans"] = "LRFD+Seismic"
    col_full, sh_full = full_cage(col_long, col_trans), full_cage(sh_long, sh_trans)
    if changed:
        S = seis(col_full, sh_full)
        Df = S.Df if S.Df is not None else 0.0
        tf_final = transform_for(Df)
        if py_ctx is not None:
            sh_rows, skipped = py_rows(py_ctx, S.EI_shaft, Ds)

    # ── final checks on the final cages ──
    final = {"col_long": col_long, "col_trans": dict(col_trans), "shaft_long": sh_long,
             "shaft_trans": dict(sh_trans)}
    final["col_trans"]["rho_s"] = cs.to_section(column, col_full, prov).rho_s
    final["shaft_trans"]["rho_s"] = cs.to_section(shaft, sh_full, prov).rho_s
    final_checks = [check_dict(c) for c in S.checks] + [rho_l_check(col_long, prov)]
    if ov.get("shaft_long"):
        final_checks.append(rho_l_check(sh_long, prov, "Shaft"))
    col_summ, col_checks, col_rows_t = lrfd_check_rows(column, col_full, col_rows, tf_final,
                                                       "Column LRFD") if col_rows else ([], [], [])
    final_checks += col_checks
    lrfd["col"]["check_rows"] = col_summ
    if py_ctx is not None:
        final_checks.append(py_check(skipped, len(skipped) + len(sh_rows)))
    if sh_rows:
        sh_summ, sh_checks, _ = lrfd_check_rows(shaft, sh_full, sh_rows, None, "Shaft LRFD")
        final_checks += sh_checks
        if lrfd["shaft"] is None:
            lrfd["shaft"] = {"long": None, "trans": None, "n_rows": len(sh_rows), "source": sh_src}
        lrfd["shaft"]["check_rows"] = sh_summ
        lrfd["shaft"]["rows"] = sh_rows

    # ── status (ruling 8-9) ──
    sl = [r.get("_slender_status") for r in col_rows_t]
    if csl.ST_REFINED in sl:
        w.append("slenderness: K*lu/r >= 100 on at least one row; refined analysis required")
    if csl.ST_PENDING in sl:
        w.append("slenderness: K*lu/r exceeds the neglect limit; moment magnification is not "
                 "yet applied (open item S6)")
    status = bent_status(bool(nosol), csl.ST_REFINED in sl,
                         any(not c["ok"] for c in final_checks))
    w += S.warnings
    out = _bent_result(name, status, lrfd, S, final, source, final_checks, nosol, w, axial, H)
    out["Df_for_lu"] = Df
    out["shaft_basis"] = basis
    return out


def bent_status(no_solution: bool, refined: bool, any_ng: bool) -> str:
    """Ruling 8-9: NO SOLUTION > REFINED ANALYSIS REQUIRED > NG > OK."""
    if no_solution:
        return "NO SOLUTION"
    if refined:
        return "REFINED ANALYSIS REQUIRED"
    return "NG" if any_ng else "OK"


def _bent_result(name, status, lrfd, S, final, source, final_checks, nosol, w, axial, H):
    return {"name": name, "status": status, "lrfd": lrfd, "seismic": S, "final": final,
            "final_source": source, "final_checks": final_checks, "no_solution": nosol,
            "warnings": _dedupe(w), "axial": axial, "H_in": H}


# ─── Entry point ────────────────────────────────────────────────────

def run_colshaft(payload: dict) -> dict:
    """Whole-project run.  Payload: {"paste", "units", "categories", "code", "bents",
    "params", "settings"}; see the Task 8 report for the full schema."""
    code = payload.get("code", cl.DEFAULT_CODE)
    prov = validate_code(code)
    settings = dict(payload.get("settings") or {})
    mode = settings.get("envelope_mode") or "station"
    if mode not in ENVELOPE_MODES:
        raise ValueError(f"envelope_mode must be one of {ENVELOPE_MODES}, got {mode!r}")
    params = dict(payload.get("params") or {})
    params["code"] = code
    pr = ci.parse_csi_frame_forces(payload.get("paste") or "", payload.get("units"))
    cats = validate_categories(payload.get("categories"), pr.cases)
    gw = list(pr.warnings)
    bents = []
    for bent in payload.get("bents") or []:
        b = run_bent(bent, pr, cats, prov, params, settings, mode)
        gw += [f"{b['name']}: {x}" for x in b["warnings"]]
        bents.append(b)
    result = {
        "parse": {"n_rows": len(pr.rows), "n_envelope": pr.n_envelope, "cases": pr.cases,
                  "frames": pr.frames, "units": pr.units, "categories": cats,
                  "warnings": _dedupe(gw)},
        "code": prov.key, "settings": {"envelope_mode": mode,
                                        "slenderness_on": bool(settings.get("slenderness_on"))},
        "bents": bents,
    }
    return sanitize(result)
