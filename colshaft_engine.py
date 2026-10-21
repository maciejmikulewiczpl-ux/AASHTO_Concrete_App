"""Column-on-Shaft orchestrator (Task 8): `run_colshaft(payload) -> dict`.

Takes the raw CSiBridge "Element Forces - Frames" paste plus the bent / settings
tables and returns everything the Column-on-Shaft UI and report need, strictly
JSON-serialisable (no NaN / Infinity: non-finite floats become None).

Per bent (spec 4.3-4.5, controller rulings 8-1 .. 8-11):
  1. Demand rows: Strength rows of the column (and shaft) frames, reduced by the
     envelope mode ("station" -> prune_dominated, "member" -> collapse_member).
  2. Column LRFD design (colshaft_lrfd.design_member, rho_l limits from the
     selected provisions), with the slenderness screen + moment magnification
     (colshaft_slender.make_magnifier, rulings M1-M12) as `transform`.
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
The longitudinal V(+T) check (long_ok_2) counts only where it is enforced
(colshaft_lrfd.long_check_enforced: member `bars_terminated` or torsion considered;
user decision 2026-10-19); lrfd[col|shaft]["long_check"] reports it per member.
Status precedence (ruling M10): NO SOLUTION > UNSTABLE (Pu ≥ φK·Pe) > REFINED
ANALYSIS REQUIRED > NG > OK.  Overrides are never altered; with an override the
status reflects the checks.
Sway groups (ruling M9): bents with the same non-empty `sway_group` share δs
(ΣPu, ΣPe).  Two-pass approximation: pass 1 designs every bent alone; pass 2
re-runs each member of a group with ΣPe = its own candidate Pe_s + the other
members' Pe_s from their pass-1 final cages, and ΣPu = its row Pu + the other
members' most compressive Pu of the same load case and step (envelope rows: the
same case); an unmatched case falls back to Pu × n_members with a warning.

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
ST_UNSTABLE = "UNSTABLE (Pu ≥ φK·Pe)"
STATUS_RANK = {"OK": 0, "NG": 1, "REFINED ANALYSIS REQUIRED": 2, ST_UNSTABLE: 3,
               "NO SOLUTION": 4}
ROW_KEYS = ("Pu", "Mu", "Vu", "Tu", "_case", "_frame", "_station", "_step", "_bound", "_Pmin",
            "_Pmax", "_source", "_base_Mu", "_base_Vu", "_klr2", "_klr3", "_slender_limit2",
            "_slender_limit3", "_slender_status", "_M2", "_M3", "_Mu1", "_delta2", "_delta3",
            "_db2", "_ds2", "_db3", "_ds3", "_Pe_b2", "_Pe_s2", "_Pe_b3", "_Pe_s3", "_sPe_s2",
            "_sPe_s3", "_Cm2", "_Cm3", "_EI", "_beta_d", "_Pmag", "_sPu", "_unstable",
            "_unstable_reason", "_neglect_note", "_neglect_note2", "_neglect_note3")
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
    return all(row_ok(member, x, r) for x, r in zip(res, rows))


def row_ok(member, res, row):
    """The LRFD row pass; the longitudinal V(+T) check counts only where it is
    enforced (cl.long_check_enforced, user decision 2026-10-19)."""
    return (res.get("flexStatus") != "NG" and res.get("shearStatus") in ("OK", "NR")
            and (not res.get("torsionConsider") or res.get("Tr", 0) >= abs(row["Tu"]))
            and cl.long_check_ok(member, res))


def _ratio(member, res, row):
    out = [res.get("_flexDC") or 0.0]
    vr = res.get("Vr2") or 0.0
    out.append(abs(row["Vu"]) / vr if vr > 0 else (math.inf if row["Vu"] else 0.0))
    if res.get("torsionConsider") and abs(row["Tu"]) > 0:
        tr = res.get("Tr") or 0.0
        out.append(abs(row["Tu"]) / tr if tr > 0 else math.inf)
    if res.get("long_dc_2") is not None and cl.long_check_enforced(member, res):
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
        ok = row_ok(member, x, r)
        ratio = _ratio(member, x, r)
        enf = cl.long_check_enforced(member, x)
        s = {k: r[k] for k in ROW_KEYS if k in r}
        s.update({k: x.get(k) for k in RES_KEYS})
        s.update(ok=ok, ratio=ratio, long_enforced=enf)
        long_txt = ("OK" if x.get("long_ok_2") is not False else "NG") if enf else cl.LONG_NA
        unst = (csl.UNSTABLE_REASON + "; ") if r.get("_unstable") else ""
        summ.append(s)
        st = r.get("_station")
        where = f"{r.get('_frame')} @ {st / 12.0:g} ft" if isinstance(st, (int, float)) else \
            (r.get("_source") or str(r.get("_frame")))
        checks.append({"group": group, "name": f"Row {i + 1}: {r.get('_case')} ({where})",
                       "demand": None, "capacity": None,
                       "ratio": ratio if math.isfinite(ratio) else None, "ok": ok,
                       "detail": (f"{unst}flexure {x.get('flexStatus')} (D/C {x.get('_flexDC') or 0:.3f} at "
                                  f"P={x.get('_flexP') or 0:.0f} kip), shear {x.get('shearStatus')}, "
                                  f"torsion {'considered' if x.get('torsionConsider') else 'neglected'}, "
                                  f"long. V+T {long_txt}"),
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

def run_bent(bent, pr, cats, prov, params, settings, mode, sway=None, design_Df=None,
             lu_iter=0, lu_max=None, lu_margin=False):
    """One bent.  `sway`: the sway-group context of pass 2 (colshaft_slender
    make_magnifier; None = the bent alone).  `design_Df`: the Df for the design-pass
    ℓu (rulings MF-5 / MF-5b redesign; None = the up-front estimate); `lu_iter`: the
    redesign iteration count; `lu_max`: the largest ℓu seen so far; `lu_margin`: this is
    the MF-5c margin run (no further redesign)."""
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
    H_auto = H in (None, "")
    H = float(H) if not H_auto else cd.column_height_in(rows_all, col_frames)
    if not H > 0:
        raise ValueError(f"Bent {name}: column height H is 0; enter H_in")
    if H_auto:                                  # ruling F-5
        w.append(f"H taken from the frame station span ({H / 12.0:.2f} ft); for fixed-fixed "
                 "bents verify it is the CLEAR height (Vo = 2·Mo/H)")
    exp_steel = {}
    for who, m in (("column", column), ("shaft", shaft)):      # ruling F-1
        try:
            exp_steel[who] = cs.expected_steel(m)
        except ValueError as e:
            raise ValueError(f"Bent {name} {who}: {e}") from None
    fy_col = float(column.get("fy", cs.GR60_FY))
    if abs(fy_col - cs.GR60_FY) > 1e-9:
        w.append(f"column fy = {fy_col:g} ksi: lambda_mo = {float(bent.get('lambda_mo', 1.2)):g} "
                 "is used; 1.2 is the A706 Gr60 value and must be checked for this grade")
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
        return csl.make_magnifier(dict(bent, lu_default_in=H + Df, col_frames=col_frames), rbc,
                                  settings, w, sway=sway)

    # design pass: Df is known up front only for the cantilever basis; the final
    # check below (final Df -> lu) is authoritative
    L_eq = bent.get("L_eq_in")
    Df0 = float(L_eq) if basis == "cantilever" and L_eq is not None else 0.0
    if design_Df is not None:
        Df0 = float(design_Df)
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
    chk = bent.get("_check_only") or ()        # ruling MF-2 / O1: check-only parts
    source = {"col_long": (SRC_CHECK_ONLY if "col_long" in chk else "Override")
              if ov.get("col_long") else "LRFD",
              "col_trans": (SRC_CHECK_ONLY if "col_trans" in chk else "Override")
              if ov.get("col_trans") else "LRFD"}
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
    elif basis in ("cantilever", "interface") and col_raw:
        # ruling F-4: the governing column-base Strength rows taken down the shaft
        if basis == "cantilever" and not (isinstance(L_eq, (int, float)) and L_eq >= 0):
            raise ValueError(cs.L_EQ_MSG)
        bf, bst = base_station(rows_all, col_frames, cats, base_end, w)
        base_rows = [r for r in col_raw if r["_frame"] == bf
                     and math.isclose(r["_station"], bst, abs_tol=1e-6)]
        sh_rows = csh.base_strength_rows(base_rows, basis,
                                         float(L_eq) if basis == "cantilever" else 0.0)
        sh_src = csh.CANT_SOURCE if basis == "cantilever" else csh.IFACE_SOURCE
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
    sh_long, sh_trans, S = size_shaft(shaft, prov, params, ov, sh_cands, sh_long, sh_trans, S,
                                      lambda c: seis(col_full, c), nosol, source)

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
    changed = col_changed = False
    Mo_walk = S.Mo
    # ruling F-6: the merged cage is also walked when it fails the column seismic
    # transverse criteria (the port ignores cross-ties, so a merged LRFD cage with
    # ties can carry a larger Av/s but a smaller rho_s / seismic phiVn)
    if (not ov.get("col_trans") and col_tr is not None and col_tr.ok and seis_req_ok
            and not (csh.col_trans_screen(column, prov, S, col_long, col_trans)
                     and (not col_rows or rows_pass(column, col_full, col_rows, tf_final)))):
        t = csh.walk_trans(col_trans, params, lambda t: (
            csh.col_trans_screen(column, prov, S, col_long, t)
            and (not col_rows or rows_pass(column, full_cage(col_long, t), col_rows, tf_final))))
        if t is None:
            nosol.append(WALK_NOSOL + " passes both "
                         "the LRFD rows and the seismic transverse criteria")
        else:
            col_trans, changed, col_changed = t, True, True
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
        # minor 7e: the column walk changed Mo -> size the shaft once more
        if col_changed and abs(S.Mo - Mo_walk) > 1e-9 * max(1.0, abs(Mo_walk)):
            l0, t0 = sh_long, sh_trans
            sh_long, sh_trans, S = size_shaft(shaft, prov, params, ov, sh_cands, sh_long, sh_trans,
                                              S, lambda c: seis(col_full, c), nosol, source)
            if sh_long is not l0 or sh_trans is not t0:
                sh_full = full_cage(sh_long, sh_trans)
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
    lrfd["col"]["long_check"] = cl.long_check_summary(column, col_summ)
    if py_ctx is not None:
        final_checks.append(py_check(skipped, len(skipped) + len(sh_rows)))
    if sh_rows:
        sh_summ, sh_checks, _ = lrfd_check_rows(shaft, sh_full, sh_rows, None, "Shaft LRFD")
        final_checks += sh_checks
        if lrfd["shaft"] is None:
            lrfd["shaft"] = {"long": None, "trans": None, "n_rows": len(sh_rows), "source": sh_src}
        lrfd["shaft"]["check_rows"] = sh_summ
        lrfd["shaft"]["long_check"] = cl.long_check_summary(shaft, sh_summ)
        lrfd["shaft"]["rows"] = sh_rows

    # ── status (rulings 8-9 / M10) ──
    sl = [r.get("_slender_status") for r in col_rows_t]
    unstable = any(r.get("_unstable") for r in col_rows_t)
    if csl.ST_REFINED in sl:
        w.append("slenderness: K*lu/r >= 100 on at least one row; refined analysis required")
    if unstable:
        w.append(f"slenderness: {csl.UNSTABLE_REASON} on at least one row of the final cage")
    if csl.ST_MAGNIFIED in sl:
        dmax = {ax: max((r.get("_delta" + ax) or 1.0) for r in col_rows_t) for ax in ("2", "3")}
        w.append(f"slenderness: moments magnified (Art. 4.5.3.2.2b, Mc = max(δb, δs)·M2 per axis); "
                 f"max δ axis 2 = {dmax['2']:.3f}, axis 3 = {dmax['3']:.3f}")
    status = bent_status(bool(nosol), csl.ST_REFINED in sl,
                         any(not c["ok"] for c in final_checks), unstable)
    # rulings MF-5 / MF-5b: the design pass used ℓu = H + Df0; while the final check
    # (ℓu = H + Df) fails only on magnified column rows and ℓu moved by > 1 %, redesign the
    # column with the final ℓu (max LU_MAX_ITER times: the heavier column deepens Df)
    mag_ng = (slender_on and not ov.get("col_long") and not ov.get("col_trans")
              and default_lu_axes(bent) and magnified_only_ng(col_summ, final_checks, nosol))
    moved = mag_ng and lu_not_settled(bent, Df, Df0, H)
    if mag_ng and lu_iter and not moved:
        w.append(f"slenderness: ℓu settled within {LU_TOL:.0%} (design Df = {Df0 / 12.0:.2f} ft, "
                 f"final Df = {Df / 12.0:.2f} ft) but the column still fails on magnified rows at "
                 "the final ℓu")
    lu_seen = max(lu_max or 0.0, H + Df, H + Df0)
    if moved and not lu_margin:
        if lu_iter < LU_MAX_ITER:
            return run_bent(bent, pr, cats, prov, params, settings, mode, sway=sway,
                            design_Df=Df, lu_iter=lu_iter + 1, lu_max=lu_seen)
        nonconv = (f"slenderness: ℓu/Df did not converge (column ↔ fixity coupling) after "
                   f"{LU_MAX_ITER} redesigns (design Df = {Df0 / 12.0:.2f} ft, final Df = "
                   f"{Df / 12.0:.2f} ft)")
        w.append(nonconv + "; last result kept")
    # ruling MF-5c: the loop stopped (settled or max) and still fails only on magnified
    # column rows -> one final redesign for max(ℓu seen) × 1.02; kept if it passes at its
    # own final ℓu
    if mag_ng and not lu_margin:
        lu_d = LU_MARGIN * lu_seen
        res = run_bent(bent, pr, cats, prov, params, settings, mode, sway=sway,
                       design_Df=lu_d - H, lu_iter=lu_iter, lu_max=lu_seen, lu_margin=True)
        col_rows_m = ((res.get("lrfd") or {}).get("col") or {}).get("check_rows") or []
        if (not res["no_solution"] and res["status"] not in ("NO SOLUTION", ST_UNSTABLE)
                and col_rows_m and all(r.get("ok") for r in col_rows_m)):
            res["warnings"].insert(0, f"slenderness: column designed for ℓu × {LU_MARGIN:g} "
                                      f"(ℓu = {lu_d / 12.0:.2f} ft) to close the column↔fixity loop")
            res["lu_margin"] = LU_MARGIN
            if any("did not converge" in x for x in w):        # O3
                res["warnings"].insert(1, f"slenderness: ℓu/Df did not converge after {LU_MAX_ITER} "
                                          "redesigns; resolved by the margin run (ℓu × "
                                          f"{LU_MARGIN:g})")
            return res
        w.append(f"slenderness: margin redesign at ℓu × {LU_MARGIN:g} tried; did not pass")
    if lu_iter:
        w.insert(0, f"slenderness: column redesigned {lu_iter} time(s) with the final ℓu (final "
                    f"Df = {Df / 12.0:.2f} ft, design Df = {Df0 / 12.0:.2f} ft)")
    w += S.warnings
    out = _bent_result(name, status, lrfd, S, final, source, final_checks, nosol, w, axial, H)
    out["Df_for_lu"] = Df
    if slender_on:
        out["lu_iterations"] = lu_iter
        if lu_iter:
            out["redesigned_final_lu"] = True
    out["shaft_basis"] = basis
    out["H_auto"] = H_auto
    out["expected_steel"] = exp_steel
    if slender_on:      # K per axis as used (user decision 2026-10-19)
        out["slender_input"] = bent.get("_slender_input") or "axes"      # ruling U-1
        out["slender_K"] = {ax: {k: v for k, v in csl.resolve_K(bent["slender"][ax], ax).items()
                                 if k != "warnings"} for ax in ("2", "3")}
        if tf_final is not None:
            raw = cl.cage_inputs(cl.base_circ_inputs(column), col_full)
            out["magnification"] = magnification_summary(tf_final, raw, col_rows_t, col_raw)
    return out


WALK_NOSOL = "Column transverse: no candidate from the merged cage on"
LU_MAX_ITER = 4
LU_TOL = 0.01
LU_MARGIN = 1.02
SRC_CHECK_ONLY = "LRFD (sway check-only)"


def axis_lu(bent, H, Df):
    """ℓu per axis as the magnifier uses it: the explicit `slender[ax].lu`, else H + Df."""
    sl = bent.get("slender") or {}
    out = {}
    for ax in ("2", "3"):
        lu = (sl.get(ax) or {}).get("lu")
        out[ax] = float(lu) if lu is not None else H + Df
    return out


def default_lu_axes(bent):
    """True when at least one axis uses the default ℓu = H + Df."""
    sl = bent.get("slender") or {}
    return any((sl.get(ax) or {}).get("lu") is None for ax in ("2", "3"))


def lu_not_settled(bent, Df, Df0, H):
    """Rulings MF-5b / O2: the actual ℓu of some axis at the final Df differs from the
    design-pass ℓu (Df0) by > 1 %.  Explicit ℓu on both axes -> never."""
    a, b = axis_lu(bent, H, Df), axis_lu(bent, H, Df0)
    return any(abs(a[ax] - b[ax]) > LU_TOL * a[ax] for ax in ("2", "3"))


def magnified_only_ng(col_summ, final_checks, nosol):
    """Ruling MF-5: True when the final checks fail ONLY on column LRFD rows that are
    magnified (applied δ > 1) or unstable.  The only NO SOLUTION entry allowed is the
    column transverse walk's (it fails on the same final-ℓu LRFD rows)."""
    if any(not x.startswith(WALK_NOSOL) for x in nosol):
        return False
    bad = [c for c in final_checks if not c["ok"]]
    bad_rows = [r for r in col_summ if not r.get("ok")]
    if not bad or not bad_rows or len(bad) != len(bad_rows):
        return False
    if any(c.get("group") != "Column LRFD" for c in bad):
        return False
    return all(r.get("_unstable") or max(r.get("_delta2") or 1.0, r.get("_delta3") or 1.0) > 1.0
               for r in bad_rows)


def magnification_summary(tf, raw, rows_t, raw_rows):
    """Per-bent moment-magnification report (ruling M12) on the final column cage:
    beta_d, EI (both §5.6.4.3 equations), per axis K_braced / K_unbraced / Pe_b / Pe_s
    and the governing row's Cm, δb, δs, δ applied (the row with the largest applied δ,
    unstable rows first), plus the pass-1 sway data (Pe_s, Pu per load case)."""
    e = tf.props(raw)
    axes = {}
    for ax in ("2", "3"):
        a = tf.axes[ax]
        gi = None
        for i, r in enumerate(rows_t):
            key = (bool(r.get("_unstable")), bool(r.get("_neglect_note" + ax)),
                   r.get("_delta" + ax) or 0.0)
            if gi is None or key > gi[0]:
                gi = (key, i)
        r = rows_t[gi[1]] if gi else {}
        axes[ax] = {"braced": a["braced"], "K_braced": a["Kb"], "K_unbraced": a["Ku"],
                    "lu": a["lu"], "Pe_b": e["Pe_b"][ax], "Pe_s": e["Pe_s"][ax],
                    "row": (gi[1] + 1) if gi else None, "case": r.get("_case"),
                    "Pu": r.get("_Pmag"), "sPu": r.get("_sPu"), "sPe_s": r.get("_sPe_s" + ax),
                    "Cm": r.get("_Cm" + ax), "db": r.get("_db" + ax), "ds": r.get("_ds" + ax),
                    "delta": r.get("_delta" + ax), "klr": r.get("_klr" + ax),
                    "limit": r.get("_slender_limit" + ax), "status": r.get("_slender_status"),
                    "unstable": bool(r.get("_unstable")),
                    "neglect_note": r.get("_neglect_note" + ax)}
    sw = tf.sway
    return {"beta_d": tf.beta_d, "beta_d_source": tf.beta_d_source, "phi_K": csl.PHI_K,
            "Ec": e["Ec"], "Es": e["Es"], "Ig": e["Ig"], "Is": e["Is"], "EI1": e["EI1"],
            "EI2": e["EI2"], "EI": e["EI"], "EI_eq": e["eq"], "axes": axes,
            "Pe_s": dict(e["Pe_s"]),
            "Pu_cases": [[k[0], k[1], v] for k, v in csl.pu_by_case(raw_rows).items()],
            "sway": None if not sw else {"group": sw.get("group"), "n_members": sw.get("n_members"),
                                         "Pe_others": sw.get("Pe_others"), "pass": 2},
            "ref": csl.MAG_REF}


def size_shaft(shaft, prov, params, ov, sh_cands, sh_long, sh_trans, S, run, nosol, source):
    """Shaft seismic sizing (ruling 8-2): step the longitudinal (As order) until the
    capacity-protection flexure check passes, then the transverse until the shaft
    shear / confinement checks pass.  run(shaft full cage) -> SeismicResult.
    -> (sh_long, sh_trans, S); the inputs are returned unchanged when they pass."""
    Ds = float(shaft["D"])
    if not ov.get("shaft_long") and not checks_ok(S, (SHAFT_FLEX,)):
        cands = [sh_long] + [long_cage(a[3], a[1], a[2], Ds) for a in sh_cands
                             if a[0] > sh_long["Ast"] + 1e-9]
        found = csh.size_shaft_long(cands, lambda c: run(full_cage(c, sh_trans)))
        if found is None:
            nosol.append(f"{SHAFT_FLEX}: no shaft longitudinal cage up to "
                         f"{cands[-1]['n']}-{cands[-1]['bundle']}x#{cands[-1]['bar']} passes")
        elif found[0] is not sh_long:
            sh_long, S = found
            source["shaft_long"] = "Seismic"
    if not ov.get("shaft_trans") and not checks_ok(S, SHAFT_TRANS):
        lg = sh_long
        found = csh.size_shaft_transverse(shaft, prov, S, lg, sh_trans, params,
                                          lambda t: run(full_cage(lg, t)))
        if found is None:
            names = [c.name for c in S.checks if c.name in SHAFT_TRANS and not c.ok]
            nosol.append(f"{', '.join(names)}: no shaft transverse cage in the search range passes")
        else:
            sh_trans, S = found
            source["shaft_trans"] = "Seismic"
    return sh_long, sh_trans, S


def bent_status(no_solution: bool, refined: bool, any_ng: bool, unstable: bool = False) -> str:
    """Rulings 8-9 / M10: NO SOLUTION > UNSTABLE (Pu ≥ φK·Pe) (a final-cage row has
    1 − Pu/(φK·Pe) ≤ 0 or 1 − ΣPu/(φK·ΣPe) ≤ 0) > REFINED ANALYSIS REQUIRED > NG > OK."""
    if no_solution:
        return "NO SOLUTION"
    if unstable:
        return ST_UNSTABLE
    if refined:
        return "REFINED ANALYSIS REQUIRED"
    if any_ng:
        return "NG"
    return "OK"


def _bent_result(name, status, lrfd, S, final, source, final_checks, nosol, w, axial, H):
    return {"name": name, "status": status, "lrfd": lrfd, "seismic": S, "final": final,
            "final_source": source, "final_checks": final_checks, "no_solution": _dedupe(nosol),
            "warnings": _dedupe(w), "axial": axial, "H_in": H}


# ─── Sway groups (ruling M9) ────────────────────────────────────────

def sway_groups(specs):
    """{group name: [bent indices]} for groups with two or more bents."""
    g = {}
    for i, b in enumerate(specs):
        name = str(b.get("sway_group") or "").strip()
        if name:
            g.setdefault(name, []).append(i)
    return {k: v for k, v in g.items() if len(v) > 1}


def sway_context(group, infos, i):
    """Pass-2 context for member i of a group from the members' pass-1 summaries.
    ΣPu keys present on EVERY other member only (else the magnifier falls back)."""
    others = [m for j, m in enumerate(infos) if j != i]
    pe = {ax: sum(float((m.get("Pe_s") or {}).get(ax) or 0.0) for m in others) for ax in ("2", "3")}
    tabs = [{(c, st): float(p) for c, st, p in (m.get("Pu_cases") or [])} for m in others]
    keys = set(tabs[0]).intersection(*tabs[1:]) if tabs else set()
    pu = {k: sum(t[k] for t in tabs) for k in keys}
    # ruling MF-3: collapsed member-mode rows -> each other member's maximum compression
    # over all its Strength cases (non-ambiguous, conservative)
    pu[csl.MEMBER_KEY] = sum(max(t.values(), default=0.0) for t in tabs)
    return {"group": group, "n_members": len(infos), "Pe_others": pe, "Pu_others": pu}


SWAY_MAX_ITER = 3


def _pe_s(info, fallback=None):
    """{axis: Pe_s} from a magnification summary, or from a bent result (its
    `magnification`; a result without one -> `fallback`)."""
    m = info.get("magnification") if info and "status" in info else info
    if not m:
        return dict(fallback) if fallback else None
    return {ax: float((m.get("Pe_s") or {}).get(ax) or 0.0) for ax in ("2", "3")}


def _check_only_spec(spec, res):
    """The bent spec with its final column cages as overrides (check-only column)."""
    F = res.get("final") or {}
    ov = dict(spec.get("override") or {})
    added = []
    if F.get("col_long") and F.get("col_trans"):
        cl_, ct = F["col_long"], F["col_trans"]
        if not ov.get("col_long"):          # a real user override stays "Override" (O1)
            ov["col_long"] = {"bar": cl_["bar"], "n": cl_["n"], "bundle": cl_.get("bundle", 1)}
            added.append("col_long")
        if not ov.get("col_trans"):
            ov["col_trans"] = {"bar": ct["bar"], "s": ct["s"], "ties": ct.get("ties", 0)}
            added.append("col_trans")
    return dict(spec, override=ov, _check_only=added)


def sway_pass2(specs, results, rerun, max_iter=SWAY_MAX_ITER):
    """Re-run every member of a multi-bent sway group with the group sums (in place).
    A member without a pass-1 magnification summary (no final cage) stops the group:
    the pass-1 (bent alone) results stay, with a warning on every member.

    Ruling MF-2 (consistency): after a pass-2 run, every member's final Pe_s must be >=
    the Pe_s the other members counted for it.  If not, pass 2 is re-run with, per
    member, min(counted, latest) Pe_s, up to `max_iter` runs; still inconsistent -> a
    warning and a final check-only run (final column cages as overrides) with the min
    values, so the status reflects them."""
    for group, idx in sway_groups(specs).items():
        infos = [results[i].get("magnification") for i in idx]
        if any(not m for m in infos):
            for i in idx:
                results[i]["warnings"].append(
                    f"sway group {group}: a member has no final cage; δs computed for each bent "
                    "alone (ΣPu/ΣPe of the group not applied)")
            continue
        used = [_pe_s(m) for m in infos]

        def run_all(spec_of):
            ctx = [dict(m, Pe_s=used[k]) for k, m in enumerate(infos)]
            new = [rerun(spec_of(k, i), sway_context(group, ctx, k)) for k, i in enumerate(idx)]
            for k, i in enumerate(idx):
                results[i] = new[k]
            return [_pe_s(r, used[k]) for k, r in enumerate(new)]

        consistent = False
        for it in range(max_iter):
            latest = run_all(lambda k, i: specs[i])
            low = [k for k in range(len(idx)) if any(
                latest[k][ax] < used[k][ax] * (1.0 - 1e-9) - 1e-9 for ax in ("2", "3"))]
            if not low:
                consistent = True
                break
            used = [{ax: min(used[k][ax], latest[k][ax]) for ax in ("2", "3")}
                    for k in range(len(idx))]
        if consistent:
            if it:
                for i in idx:
                    results[i]["warnings"].append(
                        f"sway group {group}: pass 2 repeated {it + 1} times until every member's "
                        "Pe_s ≥ the value the others counted (ruling MF-2)")
            continue
        final_res = [results[i] for i in idx]
        run_all(lambda k, i: _check_only_spec(specs[i], final_res[k]))
        for i in idx:
            results[i]["warnings"].append(
                f"sway group {group}: Pe_s not consistent after {max_iter} pass-2 runs; final "
                "check-only run of the column cages with the minimum Pe_s values (ruling MF-2)")


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
    # user ruling U-1 (2026-10-20): a single (resultant) slenderness spec is mapped onto
    # identical axes "2" / "3"; a legacy two-axis spec passes through unchanged
    specs = [dict(b, slender=csl.axes_spec(b),
                  _slender_input="single" if csl.is_single_spec(b.get("slender")) else "axes")
             if isinstance(b, dict) and b.get("slender") else b
             for b in (payload.get("bents") or [])]
    bents = [run_bent(bent, pr, cats, prov, params, settings, mode) for bent in specs]
    if settings.get("slenderness_on"):
        sway_pass2(specs, bents, lambda bent, sw: run_bent(bent, pr, cats, prov, params,
                                                            settings, mode, sway=sw))
    for b in bents:
        gw += [f"{b['name']}: {x}" for x in b["warnings"]]
    result = {
        "parse": {"n_rows": len(pr.rows), "n_envelope": pr.n_envelope, "cases": pr.cases,
                  "frames": pr.frames, "units": pr.units, "categories": cats,
                  "warnings": _dedupe(gw)},
        "code": prov.key, "settings": {"envelope_mode": mode,
                                        "slenderness_on": bool(settings.get("slenderness_on"))},
        "bents": bents,
    }
    return sanitize(result)
