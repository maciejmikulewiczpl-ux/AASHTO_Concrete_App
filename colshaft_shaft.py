"""Column-on-Shaft: shaft helpers for the orchestrator (Task 8, controller rulings 8-1 / 8-2).

* Strength rows through the pile (spec 4.4a, ruling 8-1): a column-base Strength
  row (Pu, M, V, T) is applied to the p-y column + shaft model so that the
  interface (top of shaft) carries exactly (M, V).  The solver's convention is
  interface M = V*H - M_head (fixed-fixed: V = 2*Mo/H with M_head = +Mo lands Mo
  at the interface), so M_head = V*H - M_base.  The base M and V are magnitudes
  (resultants), applied in the same direction (cantilever-like: the shear adds to
  the moment below the interface, the conservative pairing).
* Seismic shaft sizing (ruling 8-2): small stepping helpers over the same
  longitudinal candidate generator / constraints as colshaft_lrfd and over
  colshaft_lrfd.transverse_candidates.

Units kip, in, ksi; moments kip-in.  App sign convention Pu < 0 = compression;
the pile solver is compression-positive (axial = -Pu).  Pure Python, stdlib only.
"""
from __future__ import annotations

import math
from dataclasses import replace

import calc_engine as ce
import colshaft_lrfd as cl
from colshaft_seismic import to_section
from seismic_port.pile_solver import _cached_pile_solve
from seismic_port.shear import shear_capacity

SHAFT_FLEX = "Shaft flexure (capacity protection)"
SHAFT_TRANS = ("Shaft shear (capacity protection)", "Shaft confinement (oversized)")
N_TOP = 5                     # top-5 by base M plus top-5 by base V (spec 4.4a)
PY_SOURCE = "p-y strength"


# ─── Cage helpers ───────────────────────────────────────────────────

def long_candidates(member: dict, params: dict = None) -> list:
    """Every fitting outer-ring cage (bundle 1-3, bar sizes / counts within the
    rho_l and clear-spacing range of colshaft_lrfd) as (As, n, bundle, bar),
    sorted by increasing As, then fewer bars."""
    p = cl._params(params)
    base = cl.base_circ_inputs(member)
    trans = cl._member_trans(member)
    D = float(member["D"])
    Ag = math.pi * D * D / 4.0
    ag = float(member.get("ag", 0.75))
    out = []
    for nb in (1, 2, 3):
        for bar in (b for b in cl.SIZES if p["minBar"] <= b <= p["maxBar"]):
            a, n_lo, n_hi = cl._count_range(base, p, bar, nb, Ag, ag, trans)
            out += [(n * a, n, nb, bar) for n in range(n_lo, n_hi + 1)]
    out.sort(key=lambda c: (c[0], c[1]))
    return out


def av_per_s(t: dict) -> float:
    """(2 + ties) * A_bar / s for a transverse cage {bar, s, ties} (in^2/in): the
    circular engine's Av = 2*A_hoop + n_ties*A_tie (open item C4) per unit length."""
    return (2 + int(t.get("ties", 0) or 0)) * ce.BARS[int(t["bar"])]["a"] / float(t["s"])


def heavier_trans(a: dict, b: dict):
    """(cage, 'a'|'b'): the larger Av/s; on equal Av/s the larger bar; then a."""
    ka, kb = av_per_s(a), av_per_s(b)
    if abs(ka - kb) <= 1e-9 * max(ka, kb, 1.0):
        return (b, "b") if int(b["bar"]) > int(a["bar"]) else (a, "a")
    return (a, "a") if ka > kb else (b, "b")


def first_passing(cands: list, pred, start: int = 0):
    """Index of the first candidate (from `start`) for which pred(i) is True,
    found by bisection (pred assumed monotone in the candidate order, as Mp is in
    As); None when the last candidate fails.  pred results are cached."""
    if start >= len(cands):
        return None
    memo = {}

    def ok(i):
        if i not in memo:
            memo[i] = bool(pred(i))
        return memo[i]
    if ok(start):
        return start
    hi = len(cands) - 1
    if not ok(hi):
        return None
    lo = start
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ok(mid):
            hi = mid
        else:
            lo = mid
    return hi


def long_cage(bar, n, bundle, D):
    Ast = int(n) * int(bundle) * ce.BARS[int(bar)]["a"]
    return {"bar": int(bar), "n": int(n), "bundle": int(bundle), "Ast": Ast,
            "rho_l": Ast / (math.pi * D * D / 4.0)}


def trans_cage(bar, s, ties):
    t = {"bar": int(bar), "s": float(s), "ties": int(ties or 0)}
    t["Av_s"] = av_per_s(t)
    return t


def full_cage(lg, tr):
    return {"bar": lg["bar"], "n": lg["n"], "bundle": lg["bundle"],
            "trans_bar": tr["bar"], "s": tr["s"], "ties": tr["ties"]}


def check_of(S, name):
    m = [c for c in S.checks if c.name == name]
    return m[0] if m else None


def checks_ok(S, names):
    return all(c.ok for c in (check_of(S, n) for n in names) if c is not None)


def size_shaft_long(cands: list, run):
    """First longitudinal cage of `cands` (the current cage first, then heavier
    ones in As order) whose seismic run passes the shaft capacity-protection
    flexure check (ruling 8-2; Mo is fixed by the column).  Bisection: Mp grows
    with As.  run(cage) -> SeismicResult.  -> (cage, SeismicResult) or None."""
    memo = {}

    def pred(i):
        memo[i] = run(cands[i])
        return checks_ok(memo[i], (SHAFT_FLEX,))
    k = first_passing(cands, pred)
    return None if k is None else (cands[k], memo[k])


def size_shaft_transverse(shaft, prov, S, long_c, start, params, run):
    """First transverse cage in transverse_candidates order with Av/s >= the start
    cage's for which the shaft shear and confinement checks pass (ruling 8-2).
    Each candidate is screened with the ported shear_capacity / rho_s against the
    demands of the last seismic run, then confirmed with a full seismic_design.
    -> (trans cage, SeismicResult) or None."""
    floor = av_per_s(start)
    v_dem = check_of(S, SHAFT_TRANS[0]).demand
    conf = check_of(S, SHAFT_TRANS[1])
    seen = set()
    for bar, ties, s in cl.transverse_candidates(params):
        t = trans_cage(bar, s, ties)
        if t["Av_s"] < floor - 1e-12 or (bar, s) in seen:
            continue
        seen.add((bar, s))
        sec = to_section(shaft, full_cage(long_c, t), prov)
        if conf is not None and sec.rho_s < conf.demand:
            continue
        if shear_capacity(sec, -S.P_vc, 1.0, False, prov)[0] < v_dem:
            continue
        R = run(t)
        if checks_ok(R, SHAFT_TRANS):
            return t, R
    return None


# ─── Strength rows through the pile (spec 4.4a) ─────────────────────

def head_loads(M_base: float, V_base: float, H: float):
    """(V_head, M_head) that put (M_base, V_base) at the interface (ruling 8-1)."""
    return V_base, V_base * H - M_base


def interface_forces(sol) -> tuple:
    """(M, V) at the top of shaft of a PileSolution: the moment at the ground node
    and the shear in the column element just above it."""
    g = sol.ground_index
    return sol.moment[g], sol.shear[max(g - 1, 0)]


def physical(sol, M_b: float, V_b: float, L_total: float) -> bool:
    """Physical-solution test for a strength solve with a head moment.

    The solver's own guard (`stable`) requires the column-top deflection to have
    the sign of V_head, which is only valid without a head moment: with
    M_head = V*H - M_base close to V*H the head legitimately deflects backwards
    while the shaft is loaded normally (verified: Mbase = 5000 kip-in, V = 400 kip,
    H = 240 in -> y_top < 0, interface M = 5000 exactly).  The same idea is
    applied at the INTERFACE instead: converged, bounded head deflection
    (< 5 x total length, as the solver) and the top-of-shaft deflection in the
    direction of the applied interface load (M_base, V_base >= 0)."""
    if not sol.converged:
        return False
    if not abs(sol.head_deflection) < 5.0 * L_total:
        return False
    if M_b == 0 and V_b == 0:
        return True
    return sol.y[sol.ground_index] > 0.0


def pile_strength_row(row: dict, H: float, L_embed: float, EI_col: float, EI_sh: float,
                      Ds: float, prof, bounds, axial_comp: float = None):
    """Shaft demand row for one column-base Strength row, or None if every soil
    bound is unstable.  axial_comp (compression +) defaults to -_Pmin (most
    compression, so the column P-Delta is included; conservative).
    Mu / Vu = the max below-ground |M| / |V| over the physical bounds (the upstream
    inground_demand envelope, with the interface-based test of `physical` in place of
    the solver's head-deflection guard), never less than the interface (base) values.
    Returns (row | None, info) where info lists the interface (M, V) per bound."""
    M_b, V_b = abs(float(row["Mu"])), abs(float(row["Vu"]))
    if axial_comp is None:
        axial_comp = -float(row.get("_Pmin", row["Pu"]))
    V_h, M_h = head_loads(M_b, V_b, H)
    info = {"V_head": V_h, "M_head": M_h, "axial_comp": axial_comp, "bounds": []}
    M_ig = V_ig = 0.0
    n_ok = 0
    for f in bounds:
        p = replace(prof, stiffness_factor=prof.stiffness_factor * f)
        s = _cached_pile_solve(H, L_embed, EI_col, EI_sh, Ds, axial_comp, p, V_h, M_h)
        ok = physical(s, M_b, V_b, H + L_embed)
        Mi, Vi = interface_forces(s) if ok else (None, None)
        info["bounds"].append({"factor": f, "stable": ok, "solver_stable": bool(s.stable),
                               "M_interface": Mi, "V_interface": Vi})
        if ok:                      # inground_demand envelope over the physical bounds
            n_ok += 1
            M_ig = max(M_ig, s.max_inground_moment)
            V_ig = max(V_ig, s.max_inground_shear)
    if not n_ok:
        return None, info
    out = {k: row[k] for k in ("Pu", "Tu") if k in row}
    out.update(Mu=max(M_ig, M_b), Vu=max(V_ig, V_b), Vp=0, Ms=0, Ps=0,
               _source=PY_SOURCE, _case=row.get("_case"), _frame=row.get("_frame"),
               _station=None, _bound=row.get("_bound", "envelope"),
               _Pmin=row.get("_Pmin", row["Pu"]), _Pmax=row.get("_Pmax", row["Pu"]),
               _base_Mu=M_b, _base_Vu=V_b)
    if "_step" in row:
        out["_step"] = row["_step"]
    return out, info


def governing_base_rows(rows: list, n: int = N_TOP) -> list:
    """Top-n by base Mu plus top-n by base Vu (union, de-duplicated, input order)."""
    idx = sorted(range(len(rows)), key=lambda i: -abs(rows[i]["Mu"]))[:n]
    idx += sorted(range(len(rows)), key=lambda i: -abs(rows[i]["Vu"]))[:n]
    return [rows[i] for i in sorted(set(idx))]


def strength_rows_through_pile(base_rows: list, H: float, L_embed: float, EI_col: float,
                               EI_sh: float, Ds: float, prof, bounds, warnings: list = None):
    """Shaft LRFD rows from the governing base rows (ruling 8-1).  An unstable
    solve -> warning, row skipped (the seismic stability check reports NG)."""
    out = []
    for r in governing_base_rows(base_rows):
        sr, _ = pile_strength_row(r, H, L_embed, EI_col, EI_sh, Ds, prof, bounds)
        if sr is None:
            if warnings is not None:
                warnings.append(
                    f"p-y strength solve unstable for case {r.get('_case')} "
                    f"(M={abs(r['Mu']):.0f} kip-in, V={abs(r['Vu']):.0f} kip) on every "
                    "soil bound; row skipped from the shaft LRFD design")
            continue
        out.append(sr)
    return out
