"""Column-on-Shaft: shaft helpers for the orchestrator (Task 8, controller rulings 8-1 / 8-2).

* Strength rows through the pile (spec 4.4a, rulings 8-1 / 8-12 / 8-13): a
  column-base Strength row (Pu, M, V, T) is applied directly at the top of the
  shaft (shaft-alone p-y solve, Hcol = 0); see the section comment below.
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


def shaft_trans_screen(shaft, prov, S, long_c, t) -> bool:
    """The shaft shear / confinement checks of seismic_design for transverse cage t,
    evaluated directly against the demands of seismic run S: the same section
    (to_section of the shaft with long_c + t), the same axial (-S.P_vc,
    compression-positive), mu_d = 1, outside the hinge, the same rho_s demand."""
    sec = to_section(shaft, full_cage(long_c, t), prov)
    conf = check_of(S, SHAFT_TRANS[1])
    if conf is not None and sec.rho_s < conf.demand:
        return False
    return shear_capacity(sec, -S.P_vc, 1.0, False, prov)[0] >= check_of(S, SHAFT_TRANS[0]).demand


def size_shaft_transverse(shaft, prov, S, long_c, start, params, run):
    """First transverse cage in transverse_candidates order with Av/s >= the start
    cage's for which the shaft shear and confinement checks pass (ruling 8-2).
    Each candidate is screened (shaft_trans_screen) against the demands of the last
    seismic run, then confirmed with a full seismic_design.
    -> (trans cage, SeismicResult) or None."""
    floor = av_per_s(start)
    seen = set()
    for bar, ties, s in cl.transverse_candidates(params):
        t = trans_cage(bar, s, ties)
        if t["Av_s"] < floor - 1e-12 or (bar, s) in seen:
            continue
        seen.add((bar, s))
        if not shaft_trans_screen(shaft, prov, S, long_c, t):
            continue
        R = run(t)
        if checks_ok(R, SHAFT_TRANS):
            return t, R
    return None


def col_trans_screen(column, prov, S, long_c, t) -> bool:
    """The column seismic transverse criteria of required_transverse (phiVn >= Vo
    inside the hinge at -S.P_vc and mu_d, rho_s >= rho_s,min, s <= the detailing
    maximum, bar >= the minimum size) for cage t, against seismic run S."""
    if int(t["bar"]) < (S.min_trans_bar or 0):
        return False
    if S.s_max_detailing is not None and float(t["s"]) > S.s_max_detailing + 1e-9:
        return False
    sec = to_section(column, full_cage(long_c, t), prov)
    if sec.rho_s < S.rho_s_min:
        return False
    return shear_capacity(sec, -S.P_vc, S.mu_d, True, prov)[0] >= S.Vo


def merge_trans(lrfd: dict, seis: dict):
    """Ruling 8-15: bar / pitch from the larger Av/s (heavier_trans), cross-ties =
    max of the two.  -> (cage, 'a' (LRFD) | 'b' (seismic))."""
    pick, which = heavier_trans(lrfd, seis)
    ties = max(int(lrfd.get("ties", 0) or 0), int(seis.get("ties", 0) or 0))
    return trans_cage(pick["bar"], pick["s"], ties), which


def walk_trans(start: dict, params: dict, ok):
    """First transverse_candidates entry at or after `start` (in that order) for
    which ok(trans cage) is True; None if none passes.  A start that is not in the
    list (e.g. a merged cage with extra ties) starts at the first candidate whose
    Av/s >= the start's; none such -> None."""
    seq = list(cl.transverse_candidates(params))
    key = (int(start["bar"]), int(start.get("ties", 0) or 0), round(float(start["s"]), 2))
    k = next((i for i, c in enumerate(seq) if (c[0], c[1], round(c[2], 2)) == key), None)
    if k is None:
        floor = av_per_s(start)
        k = next((i for i, c in enumerate(seq)
                  if av_per_s({"bar": c[0], "s": c[2], "ties": c[1]}) >= floor - 1e-12), len(seq))
    for bar, ties, s in seq[k:]:
        t = trans_cage(bar, s, ties)
        if ok(t):
            return t
    return None


# ─── Strength rows through the pile (spec 4.4a, ruling 8-12) ────────
# The CSiBridge column-base forces already contain the column P-Delta, so they
# are applied directly at the top of the shaft: the shaft alone (Hcol = 0), with
# only the shaft P-Delta (axial = most compression).  With Hcol = 0 the solver's
# interface moment is -M_head (interface M = V*H - M_head), so M_head = -M_base
# puts M_base at the top of shaft in the same sense as V: the moment grows below
# the top as for a cantilever load (the conservative pairing of two resultant
# magnitudes).  The solver's own stability guard (head deflection in the direction
# of V) is valid for this loading and is used as reported.

V_MIN = 1e-6        # kip; the solver treats V_head == 0 as unstable (no Df_eq)


def head_loads(M_base: float, V_base: float):
    """(V_head, M_head) for the shaft-alone solve (Hcol = 0)."""
    return max(V_base, V_MIN), -M_base


def interface_forces(sol, prof, Ds: float) -> tuple:
    """(M, V) at the top of shaft of a shaft-alone PileSolution: the head-node
    moment, and the head-node element shear plus the p-y spring force at that
    node (its tributary half element)."""
    k = prof.secant_modulus(0.0, sol.y[0], Ds) * 0.5 * (sol.x[1] - sol.x[0])
    return sol.moment[0], sol.shear[0] + k * sol.y[0]


N_RAMP = 4          # axial ramp P_k = P*k/N_RAMP, k = 0..N_RAMP (ruling 8-16)


def ramp_stable(L_embed, EI_sh, Ds, axial_comp, prof, V_h, M_h, M_b):
    """Axial-ramp stability guard for a shaft-alone strength solve (ruling 8-16).

    The solver's `stable` flag (y_top * V > 0) can accept a post-buckled (wavy)
    state at high axial load.  The bound is accepted only if, at every ramp level
    P_k = P*k/4 (k = 0..4, cached solves):
      * the solver reports stable;
      * |y_top| does not decrease along the ramp (P-Delta can only amplify);
      * the top-of-shaft moment keeps the sign of M_b and is >= (1 - 0.005)*|M_b|.
    -> (solution at the full axial load, None) or (last solution, reason)."""
    prev_y = None
    s = None
    for k in range(N_RAMP + 1):
        P = axial_comp * k / N_RAMP + 0.0
        s = _cached_pile_solve(0.0, L_embed, EI_sh, EI_sh, Ds, P, prof, V_h, M_h)
        if not s.stable:
            return s, f"solver unstable at P = {P:.0f} kip"
        y = abs(s.head_deflection)
        if prev_y is not None and y < prev_y * (1.0 - 1e-9):
            return s, f"head deflection decreases along the axial ramp at P = {P:.0f} kip"
        prev_y = y
        if M_b > 0:
            Mi = s.moment[0]
            if Mi <= 0 or abs(Mi) < (1.0 - 0.005) * M_b:
                return s, f"top-of-shaft moment {Mi:.0f} != M_base {M_b:.0f} at P = {P:.0f} kip"
    return s, None


def pile_strength_row(row: dict, L_embed: float, EI_sh: float, Ds: float, prof, bounds,
                      axial_comp: float = None):
    """Shaft demand row for one column-base Strength row, or None if every soil
    bound fails the axial-ramp guard (ramp_stable).  axial_comp (compression +) defaults to
    -_Pmin (most compression).  Mu / Vu = the max below-ground |M| / |V| over the
    stable bounds (upstream inground_demand envelope), never less than the base
    values.  Returns (row | None, info) with the interface (M, V) per bound."""
    M_b, V_b = abs(float(row["Mu"])), abs(float(row["Vu"]))
    if axial_comp is None:
        axial_comp = -float(row.get("_Pmin", row["Pu"]))
    V_h, M_h = head_loads(M_b, V_b)
    info = {"V_head": V_h, "M_head": M_h, "axial_comp": axial_comp, "bounds": []}
    M_ig = V_ig = 0.0
    n_ok = 0
    for f in bounds:
        p = replace(prof, stiffness_factor=prof.stiffness_factor * f)
        s, why = ramp_stable(L_embed, EI_sh, Ds, axial_comp, p, V_h, M_h, M_b)
        ok = why is None
        Mi, Vi = interface_forces(s, p, Ds) if ok else (None, None)
        info["bounds"].append({"factor": f, "stable": ok, "solver_stable": bool(s.stable),
                               "reject": why, "M_interface": Mi, "V_interface": Vi,
                               "Mmax": s.max_inground_moment if ok else None})
        if ok:
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


def strength_rows_through_pile(base_rows: list, L_embed: float, EI_sh: float, Ds: float,
                               prof, bounds):
    """Shaft LRFD rows from the governing base rows (ruling 8-12).
    -> (rows, skipped): skipped = the governing base rows unstable on every bound
    (ruling 8-13: they make the final check "Shaft p-y strength solve" NG)."""
    out, skipped = [], []
    for r in governing_base_rows(base_rows):
        sr, _ = pile_strength_row(r, L_embed, EI_sh, Ds, prof, bounds)
        if sr is None:
            skipped.append(r)
        else:
            out.append(sr)
    return out, skipped


def py_rows(ctx, EI_shaft, Ds):
    """Shaft strength rows through the pile (ruling 8-12): -> (rows, skipped)."""
    base_rows, L_embed, prof, bounds = ctx
    return strength_rows_through_pile(base_rows, L_embed, EI_shaft, Ds, prof, bounds)


def py_check(skipped, n):
    """Ruling 8-13: NG when any governing strength row is unstable on every bound."""
    rows = "; ".join(f"{r.get('_case')} (M={abs(r['Mu']):.0f} kip-in, V={abs(r['Vu']):.0f} kip)"
                     for r in skipped)
    return {"group": "Shaft LRFD", "name": "Shaft p-y strength solve", "demand": len(skipped),
            "capacity": n, "ratio": len(skipped) / n if n else 0.0, "ok": not skipped,
            "detail": (f"{n - len(skipped)}/{n} governing strength rows solved on a stable soil bound"
                       + (f"; UNSTABLE on every bound (row skipped from the shaft LRFD design): {rows}"
                          if skipped else "")),
            "ref": ""}
