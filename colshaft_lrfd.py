"""Column-on-Shaft: LRFD strength design search over the circular engine (Task 6).

Searches the lightest longitudinal cage (outer ring) and then the lightest
transverse cage (hoop/spiral + cross-ties) that pass every demand row with the
EXISTING circular AASHTO engine (`circ_engine`, `calc_engine`), which is
imported and never modified.  Pure Python, stdlib only.

Units kip, in, ksi; moments kip-in.  Pu < 0 = compression.  Demand rows come
from `colshaft_demands.demand_rows` (spec section 4.1a / 4.3).

Search order and tie-breaks are a port of `optimizeFlexureCirc` /
`optimizeShearCirc` in index.html:
  longitudinal - bundles 1 -> 3; within a bundle level every bar size (small to
    large) whose largest fitting count passes is bisected for the fewest bars
    that pass; a size whose minimum count already uses >= 1.05 x the least As
    found is skipped; the first bundle level with any passing size wins, and
    among its sizes within 5 % of the least As the fewest bars wins (then the
    least As).
  transverse - hoop/spiral bar smallest first, cross-tie legs fewest first,
    pitch largest first; the first passing candidate is returned.
Additions over the JS optimiser (spec 4.3): the rho_l floor / ceiling of the
selected seismic provisions bound the bar count; envelope rows use the worst
axial load in [P_min, P_max] for flexure (spec 4.1a); both faces' P-M curves
are checked and the lower Mr is used (odd bar counts, open item D-C5).

Transverse pass also requires the engine's longitudinal check for V(+T)
(`long_ok_2`, Eq. 5.7.3.5-1 / 5.7.3.6.3-1) WHERE IT IS ENFORCED (see
`long_check_enforced`; user decision 2026-10-19, superseding rulings 6-1 / 6-3 in
part): only when the member's `bars_terminated` flag is set (S5.7.3.5: "Eq.
5.7.3.5-1 shall be evaluated where simply-supported girders are made continuous
for live loads and where longitudinal reinforcement is discontinuous") or the row
requires torsion consideration (S5.7.3.6.3: "The longitudinal reinforcement in
solid sections shall be proportioned to satisfy Eq. 5.7.3.6.3-1").  `design_member`
steps the longitudinal cage up when an enforced check fails.

Longitudinal steel is designed with a nominal transverse cage (#5 hoop @ 6 in,
no ties, the member's `trans_type`/`hoop_closure`) unless the member supplies
`trans_bar` / `trans_s` / `ties`.  The transverse search keeps the longitudinal
cage and re-checks flexure for each candidate (a larger hoop moves the ring
inward); a candidate whose flexure fails is skipped.
"""
import bisect
import functools
import math
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import calc_engine as ce
import circ_engine as cc
from seismic_port.provisions import get_provisions

SIZES = (5, 6, 7, 8, 9, 10, 11, 14, 18)      # index.html optimizeFlexureCirc
N_MIN = 6                                     # AASHTO 5.6.4.2 (open item C12, resolved)
NOMINAL_TRANS = {"trans_bar": 5, "trans_s": 6.0, "ties": 0}
DEFAULT_CODE = "SDC 2.1"
DEFAULT_PARAMS = {
    "minBar": 8, "maxBar": 14, "minSpacing": 1.5,
    "stirMin": 5, "stirMax": 8, "sMax": 6.0, "sMin": 3.0, "sStep": 0.25, "maxLegs": 2,
}

Transform = Optional[Callable[[dict, List[dict]], List[dict]]]


# ─── Longitudinal reinforcement for V(+T): when it is enforced ───────
# User decision 2026-10-19 (supersedes rulings 6-1 / 6-3 in part).  Verified text,
# AASHTO LRFD 10th Ed. Chapter 5:
#   S5.7.3.5   "Eq. 5.7.3.5-1 shall be evaluated where simply-supported girders are
#               made continuous for live loads and where longitudinal reinforcement
#               is discontinuous."
#   S5.7.3.6.3 "The longitudinal reinforcement in solid sections shall be
#               proportioned to satisfy Eq. 5.7.3.6.3-1" (no discontinuity exemption).
LONG_NA = "n/a: bars continuous (§5.7.3.5)"
LONG_NA_REASON = ('§5.7.3.5: "Eq. 5.7.3.5-1 shall be evaluated where simply-supported girders '
                  'are made continuous for live loads and where longitudinal reinforcement is '
                  'discontinuous."')


def long_check_enforced(member: dict, res: dict) -> bool:
    """True when the engine's longitudinal check for V(+T) (`long_ok_2`) governs a row:
    the member's longitudinal bars are terminated / discontinuous within it
    (`bars_terminated`, Eq. 5.7.3.5-1), or the row requires torsion consideration
    (`torsionConsider`, Eq. 5.7.3.6.3-1 always applies to solid sections).  The single
    source for every pass criterion, step, final check and status that uses long_ok_2."""
    return bool((member or {}).get("bars_terminated")) or bool(res.get("torsionConsider"))


def long_check_ok(member: dict, res: dict) -> bool:
    """The row's longitudinal V(+T) criterion: passes when not enforced."""
    return not long_check_enforced(member, res) or res.get("long_ok_2") is not False


def long_check_summary(member: dict, results: list) -> dict:
    """Per-member report entry: whether the longitudinal V(+T) check was enforced."""
    bt = bool((member or {}).get("bars_terminated"))
    n = len(results)
    n_t = sum(1 for r in results if r.get("torsionConsider"))
    if bt:
        mode = "all"
        note = ("enforced on every row: longitudinal bars terminated/discontinuous within the "
                "member (Eq. 5.7.3.5-1 / 5.7.3.6.3-1)")
    elif n_t:
        mode = "torsion"
        note = (f"enforced on the {n_t} of {n} row(s) where torsion is considered "
                f"(§5.7.3.6.3, Eq. 5.7.3.6.3-1, solid sections); other rows {LONG_NA}. "
                + LONG_NA_REASON)
    else:
        mode = "none"
        note = f"not enforced, {LONG_NA}. " + LONG_NA_REASON
    return {"bars_terminated": bt, "enforced": mode, "n_rows": n, "n_torsion_rows": n_t,
            "note": note}


@dataclass
class LongResult:
    ok: bool
    bar: int
    n: int
    bundle: int
    Ast: float
    rho_l: float
    dc_max: float
    governing_row: Optional[int]
    note: str
    governing_P: Optional[float] = None


@dataclass
class TransResult:
    ok: bool
    bar: int
    s: float
    ties: int
    Av: float
    rho_s: float
    dc_v: float
    dc_t: float
    governing_row: Optional[int]
    note: str
    long_vt_ng_rows: List[int] = field(default_factory=list)
    # criteria that failed at the strongest candidate when ok is False, subset of
    # {"flexure", "shear", "torsion", "long"} (see REASON_TEXT)
    fail_reasons: List[str] = field(default_factory=list)


# ─── Raw inputs ─────────────────────────────────────────────────────

def _wc(fc):
    """Concrete unit weight (kcf) as the app computes it (index.html computeWc)."""
    return 0.145 if fc <= 5 else 0.140 + 0.001 * fc


# Raw-input template: the keys of the app's own payload for a circular section
# (index.html buildInputsFromState + circPayload); every key of the test
# fixture builder (tests/fixtures.make_inputs) is included, which a test pins.
_TEMPLATE = dict(
    fc=4.0, fy=60.0, fy_trans=60.0, Es=29000.0, Ec=None, wc=None, K1=1.0, concType="NORMAL",
    fpu=270.0, fpy=243.0, Ept=28500.0, ecl=0.0, etl=0.0, ecl_override=False, etl_override=False,
    ag=0.75, lam=1.0, phi_v=0.9, gamma_e=0.75, codeEdition="AASHTO", sectionClass="RC",
    astm_spec="A615_60", secType="CIRCULAR", memberType="BEAM",
    D=48.0, b=48.0, h=48.0, bw_input=48.0, hf_top=0, hf_bot=0, cover=2.0,
    barN_top=0, nBars_top=0, d_top=None, barN_bot=8, nBars_bot=0, d_bot=None,
    As_top_ovr=None, As_bot_ovr=None, mr_rows_top=None, mr_rows_bot=None,
    nStrands=0, strand_area=0.217, dp=0, fpe=0, ductDia=0,
    shN=5, shear_legs=2, s_shear=6.0, tN=5, s_torsion=6.0, at_add_bar_N=0, s_at_add=0,
    circ_bar1=8, circ_n1=6, circ_bundle1=1, circ_ring2=False, circ_bar2=8, circ_n2=0,
    circ_bundle2=1, circ_Dr2=0, circ_trans_type="hoop", circ_hoop_closure="lap",
    circ_tie_legs=0, circ_tie_bar=5,
)
_MEMBER_OPTIONAL = ("Es", "codeEdition", "sectionClass", "astm_spec", "lam", "phi_v", "gamma_e")


@functools.lru_cache(maxsize=1)
def _template_checked():
    """Run the template once through calculate_all_circ so a missing key fails loudly."""
    raw = _fill(dict(_TEMPLATE))
    cc.calculate_all_circ(raw, [{"Pu": -100.0, "Mu": 100.0, "Vu": 10.0, "Tu": 0.0,
                                 "Vp": 0, "Ms": 0, "Ps": 0}], 0)
    return True


def _fill(raw):
    D, fc, cover = float(raw["D"]), float(raw["fc"]), float(raw["cover"])
    raw["b"] = raw["h"] = raw["bw_input"] = D
    raw["wc"] = _wc(fc)
    raw["Ec"] = ce._ec_aashto(fc, raw["K1"], raw["wc"])
    raw["d_top"] = cover
    raw["d_bot"] = D - cover
    return raw


def base_circ_inputs(member: dict) -> dict:
    """Map bent-table member fields to a raw circ_engine input dict (fresh copy)."""
    _template_checked()
    raw = dict(_TEMPLATE)
    raw.update(D=float(member["D"]), fc=float(member["fc"]), fy=float(member["fy"]),
               fy_trans=float(member.get("fyt", member["fy"])), cover=float(member["cover"]),
               ag=float(member.get("ag", 0.75)),
               circ_trans_type=member.get("trans_type", "hoop"),
               circ_hoop_closure=member.get("hoop_closure", "lap"))
    for k in _MEMBER_OPTIONAL:
        if k in member:
            raw[k] = member[k]
    return _fill(raw)


def cage_inputs(base: dict, cage: dict) -> dict:
    """Raw inputs for a cage {bar, n, bundle, trans_bar, s, ties} on top of `base`."""
    raw = dict(base)
    tb = int(cage["trans_bar"])
    s = float(cage["s"])
    raw.update(circ_bar1=int(cage["bar"]), circ_n1=int(cage["n"]), circ_bundle1=int(cage["bundle"]),
               shN=tb, tN=tb, circ_tie_bar=tb, circ_tie_legs=int(cage.get("ties", 0)),
               s_shear=s, s_torsion=s, shear_legs=2)
    return raw


def _params(params):
    p = dict(DEFAULT_PARAMS)
    p.update(params or {})
    prov = get_provisions(p.get("code", DEFAULT_CODE))
    p.setdefault("rho_min", prov.rho_l_min)
    p.setdefault("rho_max", prov.rho_l_max)
    return p


def transverse_candidates(params: dict = None):
    """(bar, ties, s) in search order: bar smallest first, ties fewest first, s largest first."""
    p = _params(params)
    max_ties = max(0, int(p["maxLegs"]) - 2)
    step = max(0.25, float(p["sStep"]))
    for bar in range(int(p["stirMin"]), int(p["stirMax"]) + 1):
        if bar not in ce.BARS:
            continue
        for ties in range(max_ties + 1):
            k = 0
            while True:
                s = round(float(p["sMax"]) - k * step, 2)
                if s < float(p["sMin"]) - 1e-6:
                    break
                yield bar, ties, s
                k += 1


# ─── Envelope flexure: exact minimum of Mr(P) over [Pmin, Pmax] ─────

class _Curve:
    """Precomputed breakpoints of F(P) = get_mr_at_pu(curve, P).

    F is the max over the curve segments covering P of |linear Mr|.  Between
    consecutive breakpoints (vertices, zero crossings of a segment, and - when
    Pr folds back - crossings of two overlapping segments) the active segment
    set is fixed and no two of them cross, so F is linear there.  The minimum
    over a closed range is therefore at an end, a breakpoint, or a one-sided
    limit at a breakpoint (F may jump down just past a fold vertex).
    """

    def __init__(self, curve):
        self.curve = curve
        self.lo = curve[0]["Pr"] if curve else 0.0
        self.hi = curve[-1]["Pr"] if curve else 0.0
        segs = []
        for i in range(len(curve) - 1):
            P1, M1 = curve[i]["Pr"], curve[i]["Mr"]
            P2, M2 = curve[i + 1]["Pr"], curve[i + 1]["Mr"]
            if abs(P2 - P1) >= 1e-10:
                segs.append((min(P1, P2), max(P1, P2), P1, M1, (M2 - M1) / (P2 - P1)))
        self.segs = segs
        bps = {p["Pr"] for p in curve}
        for lo, hi, P1, M1, k in segs:
            if k != 0:
                z = P1 - M1 / k
                if lo < z < hi:
                    bps.add(z)
        prs = [p["Pr"] for p in curve]
        if any(prs[i + 1] < prs[i] for i in range(len(prs) - 1)):
            for a in range(len(segs)):
                la, ha, Pa, Ma, ka = segs[a]
                for b in range(a + 1, len(segs)):
                    lb, hb, Pb, Mb, kb = segs[b]
                    lo, hi = max(la, lb), min(ha, hb)
                    if lo >= hi:
                        continue
                    ca, cb = Ma - ka * Pa, Mb - kb * Pb   # M = k*P + c
                    for sgn in (1.0, -1.0):               # la = lb and la = -lb
                        den = ka - sgn * kb
                        if den != 0:
                            x = (sgn * cb - ca) / den
                            if lo < x < hi:
                                bps.add(x)
        self.bp = sorted(bps)
        n = len(self.bp)
        self.F = [ce.get_mr_at_pu(curve, b) for b in self.bp]
        self.active = []
        for j in range(n - 1):
            mid = 0.5 * (self.bp[j] + self.bp[j + 1])
            self.active.append([s for s in segs if s[0] <= mid <= s[1]])
        # g[j] = lowest of F and both one-sided limits at breakpoint j
        self.g = []
        for j, b in enumerate(self.bp):
            v = self.F[j]
            if j > 0:
                v = min(v, self._lin_max(self.active[j - 1], b))
            if j < n - 1:
                v = min(v, self._lin_max(self.active[j], b))
            self.g.append(v)

    @staticmethod
    def _lin_max(segs, P):
        return max((abs(M1 + k * (P - P1)) for _, _, P1, M1, k in segs), default=0.0)

    def F_at(self, P):
        return ce.get_mr_at_pu(self.curve, P)

    def _interval(self, P):
        j = bisect.bisect_right(self.bp, P) - 1
        return j if 0 <= j < len(self.active) else None

    def right_lim(self, P):
        j = self._interval(P)
        return self.F_at(P) if j is None else self._lin_max(self.active[j], P)

    def left_lim(self, P):
        j = bisect.bisect_left(self.bp, P) - 1
        if not (0 <= j < len(self.active)):
            return self.F_at(P)
        return self._lin_max(self.active[j], P)


def _flex_star(c: _Curve, Pmin: float, Pmax: float):
    """(P*, Mr*): the lowest flexural resistance over [Pmin, Pmax] and where it occurs.
    Ties prefer Pmax, then Pmin, then the lowest inner breakpoint."""
    if Pmin > Pmax:
        Pmin, Pmax = Pmax, Pmin
    if Pmax - Pmin <= 0:
        return Pmax, c.F_at(Pmax)
    # the tie tolerance only chooses P; the returned value is the true minimum
    best_P, best = Pmax, min(c.F_at(Pmax), c.left_lim(Pmax))
    true_min = best
    i = bisect.bisect_right(c.bp, Pmin)
    j = bisect.bisect_left(c.bp, Pmax)
    others = [(Pmin, min(c.F_at(Pmin), c.right_lim(Pmin)))] + [(c.bp[k], c.g[k]) for k in range(i, j)]
    for P, v in others:
        true_min = min(true_min, v)
        if v < best - 1e-9 * max(1.0, abs(best)):
            best_P, best = P, v
    return best_P, true_min


def flexure_axial_star(pm_curve: list, Pmin: float, Pmax: float) -> float:
    """The axial load in [Pmin, Pmax] at which the factored P-M curve gives the lowest Mr
    (exact for the piecewise-linear curve; see _Curve)."""
    return _flex_star(_Curve(pm_curve), Pmin, Pmax)[0]


# ─── Candidate evaluation ───────────────────────────────────────────

def _is_env(r):
    return r.get("_bound") == "envelope"


def _prange(r):
    if _is_env(r):
        a, b = r.get("_Pmin", r["Pu"]), r.get("_Pmax", r["Pu"])
        return min(a, b), max(a, b)
    return r["Pu"], r["Pu"]


def _row_flex(curves, r):
    """Flexure check of one row on both faces -> (ok, dc, P_used, Mr_used)."""
    Pmin, Pmax = _prange(r)
    Mu = abs(r["Mu"])
    worst = None
    for c in curves:
        if Pmin < c.lo or Pmax > c.hi:
            ax = max(Pmin / c.lo if (Pmin < 0 and c.lo < 0) else 0.0,
                     Pmax / c.hi if (Pmax > 0 and c.hi > 0) else 0.0)
            cand = (False, max(ax, 1.0 + 1e-9), Pmin if Pmin < c.lo else Pmax, 0.0)
        else:
            if _is_env(r):
                P, mr = _flex_star(c, Pmin, Pmax)
            else:
                P, mr = r["Pu"], c.F_at(r["Pu"])
            ok = mr >= Mu
            dc = Mu / mr if mr > 0 else (0.0 if Mu == 0 else math.inf)
            cand = (ok, dc, P, mr)
        # failing face first, then the higher D/C, then the lower Mr
        if worst is None or (cand[0], -cand[1], cand[3]) < (worst[0], -worst[1], worst[3]):
            worst = cand
    return worst


def _row_key(r):
    Pmin, Pmax = _prange(r)
    return (r["Pu"], r["Mu"], r["Vu"], r["Tu"], r.get("Vp", 0), r.get("Ms", 0), r.get("Ps", 0),
            Pmin, Pmax, _is_env(r))


class _Search:
    def __init__(self, member, rows, transform):
        self.member = member
        self.base = base_circ_inputs(member)
        self.rows = rows
        self.transform = transform
        self.hot = []                      # original row indices that failed recently

    def build(self, cage):
        raw = cage_inputs(self.base, cage)
        I = cc.derive_circular(dict(raw))
        sag, hog = cc.build_pm_curve_circ(I, "top"), cc.build_pm_curve_circ(I, "bottom")
        rows = self.rows
        if self.transform is not None:
            rows = self.transform(dict(cage, inputs=dict(raw)), [dict(r) for r in rows])
        uniq, first, seen = [], [], {}
        for i, r in enumerate(rows):
            k = _row_key(r)
            if k not in seen:
                seen[k] = len(uniq)
                uniq.append(r)
                first.append(i)
        return {"I": I, "sag": sag, "hog": hog, "raw": raw, "rows": uniq, "first": first,
                "curves": None}

    def curves(self, cand):
        if cand["curves"] is None:
            cand["curves"] = (_Curve(cand["sag"]), _Curve(cand["hog"]))
        return cand["curves"]

    def order(self, cand):
        pos = {o: u for u, o in enumerate(cand["first"])}
        pri = [pos[h] for h in self.hot if h in pos]
        done = set(pri)
        return pri + [u for u in range(len(cand["rows"])) if u not in done]

    def failed(self, orig):
        if orig in self.hot:
            self.hot.remove(orig)
        self.hot.insert(0, orig)
        del self.hot[16:]

    def flex(self, cand, full=False):
        """-> (pass, worst dc, governing original row, P used there).  Stops at the
        first failing row unless `full` (worst dc is then a lower bound)."""
        curves = self.curves(cand)
        ok_all, worst, gov, gP = True, -1.0, None, None
        for u in self.order(cand):
            ok, dc, P, _ = _row_flex(curves, cand["rows"][u])
            if dc > worst:
                worst, gov, gP = dc, cand["first"][u], P
            if not ok:
                ok_all = False
                self.failed(cand["first"][u])
                if not full:
                    break
        return ok_all, max(worst, 0.0), gov, gP

    def shear(self, cand, full=False):
        """-> (pass, dc_v, dc_t, governing original row, long-V+T NG rows, failing criteria).

        Row pass = shearStatus in {OK, NR}, Tr >= |Tu| where torsion is considered, and
        the engine's longitudinal check for V (+T) `long_ok_2` (Eq. 5.7.3.5-1 /
        5.7.3.6.3-1, Method 2) not False where it is enforced (long_check_enforced).  The
        failing criteria (of the rows evaluated) are returned as a subset of
        {"shear", "torsion", "long"}; the NG rows list holds enforced failures only."""
        I, sag, hog = cand["I"], cand["sag"], cand["hog"]
        ok_all, dv, dt, gov, gdc, long_ng = True, 0.0, 0.0, None, -1.0, []
        reasons = set()
        for u in self.order(cand):
            r = cand["rows"][u]
            Tu = abs(r["Tu"])
            res = cc.compute_row_capacities_circ(I, sag, hog, r["Pu"], r["Mu"], r["Vu"], r["Tu"],
                                                 r.get("Vp", 0), r.get("Ms", 0), r.get("Ps", 0))
            tors = bool(res["torsionConsider"])
            sh_ok = res["shearStatus"] in ("OK", "NR")
            t_ok = not tors or res["Tr"] >= Tu
            long_ok = long_check_ok(self.member, res)
            ok = sh_ok and t_ok and long_ok
            if not sh_ok:
                reasons.add("shear")
            if not t_ok:
                reasons.add("torsion")
            if not long_ok:
                reasons.add("long")
            vr = res["Vr2"]
            v = abs(r["Vu"]) / vr if vr > 0 else (0.0 if r["Vu"] == 0 else math.inf)
            t = (Tu / res["Tr"] if res["Tr"] > 0 else math.inf) if (tors and Tu > 0) else 0.0
            dv, dt = max(dv, v), max(dt, t)
            if max(v, t) > gdc:
                gdc, gov = max(v, t), cand["first"][u]
            if not long_ok:
                long_ng.append(cand["first"][u])
            if not ok:
                if ok_all:
                    gdc, gov = math.inf, cand["first"][u]
                ok_all = False
                self.failed(cand["first"][u])
                if not full:
                    break
        return ok_all, dv, dt, gov, sorted(long_ng), reasons


def _ring_fit(base, bar, nb, min_clear, trans):
    """Largest bar count with chord clear spacing >= min_clear (index.html circMaxBarsInRing)."""
    raw = cage_inputs(base, dict(trans, bar=bar, n=N_MIN, bundle=nb))
    raw["circ_ring2"] = False
    try:
        rg = cc.derive_circular(dict(raw))["circ_rings"][0]
    except (ValueError, IndexError):
        return 0
    r = rg["r"]
    if r <= 0:
        return 0
    w = 2.0 * r * math.sin(math.pi / N_MIN) - rg["s_clear"]   # bundle width
    x = (min_clear + w) / (2.0 * r)
    return 0 if x >= 1 else int(math.floor(math.pi / math.asin(x)))


def _member_trans(member):
    return {"trans_bar": int(member.get("trans_bar", NOMINAL_TRANS["trans_bar"])),
            "s": float(member.get("trans_s", NOMINAL_TRANS["trans_s"])),
            "ties": int(member.get("ties", NOMINAL_TRANS["ties"]))}


def _count_range(base, p, bar, nb, Ag, ag, trans):
    """(area per position, n_lo, n_hi): bar-count bounds from the six-bar minimum, rho_l
    limits and the clear-spacing fit (index.html optimizeFlexureCirc)."""
    a = ce.BARS[bar]["a"] * nb
    d_eq = ce.BARS[bar]["d"] * math.sqrt(nb)
    min_clear = max(p["minSpacing"], 1.5 * d_eq, 1.5 * ag)
    n_hi = min(_ring_fit(base, bar, nb, min_clear, trans),
               int(math.floor(p["rho_max"] * Ag / a + 1e-9)))
    n_lo = max(N_MIN, int(math.ceil(p["rho_min"] * Ag / a - 1e-9)))
    return a, n_lo, n_hi


# ─── Public searches ────────────────────────────────────────────────

def design_longitudinal(member: dict, rows: list, params: dict = None,
                        transform: Transform = None) -> LongResult:
    """Lightest outer-ring cage whose flexure passes (flexStatus != NG) on every row."""
    p = _params(params)
    S = _Search(member, rows, transform)
    trans = _member_trans(member)
    D = float(member["D"])
    Ag = math.pi * D * D / 4.0
    ag = float(member.get("ag", 0.75))
    sizes = [b for b in SIZES if p["minBar"] <= b <= p["maxBar"]]
    tr_note = (f"longitudinal designed with transverse #{trans['trans_bar']} @ {trans['s']:.2f} in, "
               f"{trans['ties']} tie leg(s)")
    best_fail = None   # (dc, bar, n, nb, gov, gP) over the full top-count evaluations

    def evaluate(bar, n, nb, full=False):
        cand = S.build(dict(trans, bar=bar, n=n, bundle=nb))
        return S.flex(cand, full)

    for nb in (1, 2, 3):
        cands = []
        for bar in sizes:
            a, n_lo, n_hi = _count_range(S.base, p, bar, nb, Ag, ag, trans)
            if n_hi < n_lo:
                continue
            min_as = min((c["As"] for c in cands), default=math.inf)
            if n_lo * a >= 1.05 * min_as:
                continue
            top = evaluate(bar, n_hi, nb, full=True)
            if best_fail is None or top[1] < best_fail[0]:
                best_fail = (top[1], bar, n_hi, nb, top[2], top[3])
            if not top[0]:
                continue
            lo, hi, hi_res = n_lo - 1, n_hi, top
            while hi - lo > 1:
                mid = (lo + hi) // 2
                r = evaluate(bar, mid, nb)
                if r[0]:
                    hi, hi_res = mid, r
                else:
                    lo = mid
            cands.append({"bar": bar, "n": hi, "nb": nb, "As": hi * a})
        if cands:
            lim = 1.05 * min(c["As"] for c in cands)
            best = sorted((c for c in cands if c["As"] <= lim), key=lambda c: (c["n"], c["As"]))[0]
            ok, dc, gov, gP = evaluate(best["bar"], best["n"], nb, full=True)
            if not ok:
                raise RuntimeError("colshaft_lrfd: the selected longitudinal cage failed its re-check")
            return LongResult(ok, best["bar"], best["n"], nb, best["As"], best["As"] / Ag,
                              dc, gov, tr_note, gP)
    if best_fail is None:
        return LongResult(False, 0, 0, 0, 0.0, 0.0, math.inf, None,
                          "NO SOLUTION: no cage in the bar-size / spacing / rho_l range fits. " + tr_note)
    dc, bar, n, nb, gov, gP = best_fail
    As = n * nb * ce.BARS[bar]["a"]
    return LongResult(False, bar, n, nb, As, As / Ag, dc, gov,
                      f"NO SOLUTION: best cage {n}-{nb}x#{bar} reaches flexural D/C {dc:.3f}. " + tr_note, gP)


def design_transverse(member: dict, long: LongResult, rows: list, params: dict = None,
                      transform: Transform = None) -> TransResult:
    """First transverse cage (search order of transverse_candidates) for which flexure
    and shear (shearStatus in OK/NR, Tr >= |Tu| where torsion is considered, long_ok_2 not
    False where enforced - long_check_enforced) pass on every row.  Does not change the longitudinal cage (see design_member)."""
    if not long.bar or not long.n:
        return TransResult(False, 0, 0.0, 0, 0.0, 0.0, math.inf, math.inf, None,
                           "NO SOLUTION: no longitudinal cage to design transverse steel for")
    S = _Search(member, rows, transform)
    D, cover = float(member["D"]), float(member["cover"])
    spiral = member.get("trans_type", "hoop") == "spiral"
    skipped_flex = 0
    last = None
    for bar, ties, s in transverse_candidates(params):
        last = (bar, ties, s)
        cand = S.build({"bar": long.bar, "n": long.n, "bundle": long.bundle,
                        "trans_bar": bar, "s": s, "ties": ties})
        if not S.flex(cand)[0]:
            skipped_flex += 1
            continue
        ok, dv, dt, gov, long_ng, _ = S.shear(cand)
        if ok:
            note = "; ".join(_trans_note(skipped_flex, long_ng)) or "OK"
            return _trans_result(True, cand, bar, ties, s, D, cover, dv, dt, gov, long_ng, note)
    if last is None:
        return TransResult(False, 0, 0.0, 0, 0.0, 0.0, math.inf, math.inf, None,
                           "NO SOLUTION: empty transverse search range")
    bar, ties, s = last          # strongest candidate: report its D/C
    cand = S.build({"bar": long.bar, "n": long.n, "bundle": long.bundle,
                    "trans_bar": bar, "s": s, "ties": ties})
    _, dv, dt, gov, long_ng, reasons = S.shear(cand, full=True)
    if not S.flex(cand, full=True)[0]:
        reasons.add("flexure")
    reasons = sorted(reasons)
    note = (f"NO SOLUTION: strongest candidate #{bar} @ {s:.2f} in + {ties} tie leg(s) fails "
            + ", ".join(REASON_TEXT[r] for r in reasons))
    if spiral:
        note += "; spiral is not counted as torsion reinforcement (C6) - use hoops if torsion must be considered"
    note = "; ".join([note] + _trans_note(skipped_flex, long_ng))
    res = _trans_result(False, cand, bar, ties, s, D, cover, dv, dt, gov, long_ng, note)
    res.fail_reasons = reasons
    return res


REASON_TEXT = {
    "flexure": "flexure (P-M) with this hoop size",
    "shear": "shear (Vr / min. Av / max. spacing)",
    "torsion": "torsion (Tr < |Tu|)",
    "long": "longitudinal reinforcement for V+T (Eq. 5.7.3.5-1 / 5.7.3.6.3-1)",
}


def _trans_note(skipped_flex, long_ng):
    parts = []
    if skipped_flex:
        parts.append(f"{skipped_flex} candidate(s) skipped because flexure failed with that hoop size")
    if long_ng:
        parts.append(f"longitudinal reinforcement for V+T NG (Eq. 5.7.3.5-1 / 5.7.3.6.3-1) at rows {long_ng}")
    return parts


def _trans_result(ok, cand, bar, ties, s, D, cover, dv, dt, gov, long_ng, note):
    I = cand["I"]
    summ = cc.circ_transverse_summary(I)
    if "rho_s" in summ:
        rho_s = summ["rho_s"]
    else:   # unconfined (lap-closed) hoop: same volumetric expression as circ_transverse_summary
        Dc = D - 2.0 * cover
        rho_s = 4.0 * I["shBar_a"] / (Dc * s) if (Dc > 0 and s > 0) else 0.0
    return TransResult(ok, bar, s, ties, I["Av"], rho_s, dv, dt, gov, note, list(long_ng))


def check_cage(member: dict, cage: dict, rows: list, transform: Transform = None) -> list:
    """compute_row_capacities_circ for every row on `cage` {bar, n, bundle, trans_bar, s, ties}.

    Shear-side keys are the engine's, judged at the row's Pu (= P_max for envelope rows).
    Flexure keys (Mr, flexStatus) are replaced by the search's evaluation: both faces, and
    for envelope rows the worst P in [P_min, P_max]; `_flexP` is the P used, `_flexDC` the
    D/C, and the engine's own values are kept as `Mr_engine` / `flexStatus_engine`."""
    S = _Search(member, [], None)
    cand = S.build(cage)
    I, sag, hog = cand["I"], cand["sag"], cand["hog"]
    curves = S.curves(cand)
    mcr = {}
    by_key = {}
    out = []
    rows_t = rows if transform is None else transform(dict(cage, inputs=dict(cand["raw"])),
                                                      [dict(r) for r in rows])
    for r in rows_t:
        k = _row_key(r)
        if k in by_key:
            out.append(dict(by_key[k]))
            continue
        res = cc.compute_row_capacities_circ(I, sag, hog, r["Pu"], r["Mu"], r["Vu"], r["Tu"],
                                             r.get("Vp", 0), r.get("Ms", 0), r.get("Ps", 0))
        ok, dc, P, mr = _row_flex(curves, r)
        sgn = 1 if r["Mu"] >= 0 else -1
        if sgn not in mcr:
            mcr[sgn] = cc.do_flexure_circ(I, 0.0, float(sgn), 0.0, 0.0, pm=(sag, hog))["Mcr"]
        if not ok:
            status = "NG"
        elif mr < min(1.33 * abs(r["Mu"]), mcr[sgn]):
            status = "MIN"
        else:
            status = "OK"
        res["Mr_engine"], res["flexStatus_engine"] = res["Mr"], res["flexStatus"]
        res["Mr"] = -mr if r["Mu"] < 0 else mr
        res["flexStatus"] = status
        res["_flexP"], res["_flexDC"] = P, dc
        by_key[k] = res
        out.append(res)
    return out


STEP_NOTE = "longitudinal steel increased for shear/torsion"


def design_member(member: dict, rows: list, params: dict = None,
                  transform: Transform = None):
    """Longitudinal then transverse design -> (LongResult, TransResult).

    Controller ruling 6-3: when the transverse search finds no passing candidate for
    the flexure-designed cage, for any shear-side reason (shear NG, Tr < |Tu|, an
    ENFORCED long_ok_2 (long_check_enforced; user decision 2026-10-19) - Vr2, Tr and the Eq. 5.7.3.5-1 / 5.7.3.6.3-1 demand all depend on the
    longitudinal cage, non-monotonically), every heavier fitting cage (bundle 1-3, bar
    sizes and counts within the rho_l / spacing range) is tried in order of increasing
    As (then fewer bars).  A step is screened with the strongest transverse candidate
    (fail-fast; skipped with `continue` if it fails), must pass flexure, and then gets
    the full transverse search; the first passing step is returned.  NO SOLUTION only
    after the whole list.  A stepped LongResult note says which criterion forced it."""
    lg = design_longitudinal(member, rows, params, transform)
    tr = design_transverse(member, lg, rows, params, transform)
    if not lg.ok or tr.ok:
        return lg, tr
    forced = [r for r in tr.fail_reasons if r != "flexure"] or list(tr.fail_reasons)
    p = _params(params)
    S = _Search(member, rows, transform)
    trans = _member_trans(member)
    D = float(member["D"])
    Ag = math.pi * D * D / 4.0
    ag = float(member.get("ag", 0.75))
    tb, ties, s = list(transverse_candidates(params))[-1]
    steps = []
    for nb in (1, 2, 3):
        for bar in (b for b in SIZES if p["minBar"] <= b <= p["maxBar"]):
            a, n_lo, n_hi = _count_range(S.base, p, bar, nb, Ag, ag, trans)
            steps += [(n * a, n, nb, bar) for n in range(n_lo, n_hi + 1) if n * a > lg.Ast + 1e-9]
    steps.sort()
    screened = searched = 0
    for As, n, nb, bar in steps:
        screened += 1
        probe = S.build({"bar": bar, "n": n, "bundle": nb, "trans_bar": tb, "s": s, "ties": ties})
        if not S.shear(probe)[0]:
            continue
        cand = S.build(dict(trans, bar=bar, n=n, bundle=nb))
        fl = S.flex(cand, full=True)
        if not fl[0]:
            continue
        searched += 1
        note = (lg.note + "; " + STEP_NOTE + ": " + ", ".join(REASON_TEXT[r] for r in forced)
                + f" failed with {lg.n}-{lg.bundle}x#{lg.bar}")
        lg2 = LongResult(True, bar, n, nb, As, As / Ag, fl[1], fl[2], note, fl[3])
        tr2 = design_transverse(member, lg2, rows, params, transform)
        if tr2.ok:
            return lg2, tr2
    tr.note += (f"; {screened} heavier longitudinal cage(s) tried (screen: #{tb} @ {s:.2f} in + "
                f"{ties} tie leg(s)), {searched} given the full transverse search: none passes")
    return lg, tr
