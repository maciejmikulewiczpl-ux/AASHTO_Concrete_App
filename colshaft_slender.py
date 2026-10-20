"""Column-on-shaft slenderness screen and moment magnification.

Sources (CLAUDE.md citation rule):
  * Chapter 5 markdown (verified text):
    - S5.6.4.3: neglect when K*lu/r < 22 (unbraced) or < 34 - 12(M1/M2) (braced);
      M1/M2 positive for single curvature, negative for double curvature.
    - C5.6.4.3: r = 0.25*D for a circular member; "For members braced against
      sidesway, the effective length factor, K, is taken as 1.0, unless it is shown
      by analysis that a lower value may be used." and "For members not braced
      against sidesway, K is determined with due consideration for the effects of
      cracking and reinforcement on relative stiffness and is taken as not less
      than 1.0."
    - S5.6.4.1: approximate procedure only for K*lu/r < 100.
  * `AASHTO 10 Ch 5 MD/Art_4.5.3.2.2b_user_supplied.md` (transcribed from page
    images the user supplied on 2026-10-19; the ONLY source for these):
    - Eq. 4.5.3.2.2b-1  Mc = delta_b*M2b + delta_s*M2s
    - Eq. 4.5.3.2.2b-3  delta_b = Cm / (1 - Pu/(phiK*Pe)) >= 1.0
    - Eq. 4.5.3.2.2b-4  delta_s = 1 / (1 - SumPu/(phiK*SumPe))
    - Eq. 4.5.3.2.2b-5  Pe = pi^2*EI/(K*lu)^2  (delta_b: K for braced frames;
      delta_s: K for unbraced frames); phiK = 0.75 for concrete members
    - Eq. 4.5.3.2.2b-6  Cm = 0.6 + 0.4*(M1b/M2b)  (members braced against
      sidesway without transverse loads between supports; all other cases 1.0)
    - Eq. 5.6.4.3-1  EI = (Ec*Ig/5 + Es*Is)/(1 + beta_d)
    - Eq. 5.6.4.3-2  EI = (Ec*Ig/2.5)/(1 + beta_d); EI = the larger of the two
    - Table C4.6.2.5-1 design values of K (cases (c), (d), (e)).

Implementation choices (user-approved rulings M1-M12, 2026-10-19):
  * K per axis (`resolve_K_unbraced` / `resolve_K_braced`): the unbraced K
    (`K_source`, `end_condition`, `K`) is used for delta_s and for the unbraced
    screen; default = Table C4.6.2.5-1 design value: fixed-free (top rotation and
    translation free) case (e) K = 2.1, fixed-fixed (top rotation fixed,
    translation free) case (d) K = 1.2.  The braced K (`K_braced_source`,
    `K_braced`; default 1.0, C5.6.4.3 / case (c)) is used for delta_b and for the
    braced screen.  "analysis" = a buckling-analysis K (any K > 0; unbraced
    K < 1.0 accepted with a warning).
  * Mc: CSiBridge combinations do not separate the gravity moment M2b from the
    sway moment M2s, so the conservative bound Mc = max(delta_b, delta_s)*M2 is
    used (both deltas >= 1, both moments positive).  Per axis: M2 and M3 are
    magnified separately ("the moment about each axis shall be magnified by
    delta ... about that axis"), then Mu = hypot.
  * Cm from Eq. 4.5.3.2.2b-6 only on braced axes (no transverse loads between
    supports assumed for columns); unbraced axes (delta_b too) use Cm = 1.0.
  * Pu: compression magnitude of the row (envelope rows: _Pmin, most
    compression); tension -> delta = 1.0.
  * beta_d (`beta_d`): user override, else min(1, gamma_p*max|M_dead|/max|Mu|)
    from the Dead-category rows; no Dead rows -> 1.0 with a warning.
  * delta_s group sums (ruling M9): `sway` context from colshaft_engine
    (two-pass approximation for a sway group of several bents).
  * 1 - Pu/(phiK*Pe) <= 0 (or the SumPu form) -> the row is UNSTABLE (`_unstable`)
    and fails in the search.
"""
import math

import circ_engine as cc
import colshaft_demands as cd

REF = ("AASHTO LRFD 10th §5.6.4.3 (limits 22 and 34 - 12(M1/M2)); "
       "r per C5.6.4.3; <100 per §5.6.4.1")
MAG_REF = ("AASHTO LRFD 10th Eqs. 4.5.3.2.2b-1, -3, -4, -5, -6 and 5.6.4.3-1/-2 "
           "(user-supplied text, 2026-10-19)")

ST_NEGLECT = "neglect"
ST_MAGNIFIED = "magnified"
ST_REFINED = "refined analysis required"
_RANK = {ST_NEGLECT: 0, ST_MAGNIFIED: 1, ST_REFINED: 2}

PHI_K = 0.75                     # stiffness reduction factor, concrete members
UNSTABLE_REASON = "magnification unstable (Pu ≥ φK·Pe)"
GAMMA_P_DEFAULT = 1.25

K_SOURCES = ("default", "analysis")
END_CONDITIONS = ("fixed-free", "fixed-fixed")
# Table C4.6.2.5-1 design values (unbraced, translation free at the top)
TABLE_K = {"fixed-free": 2.1, "fixed-fixed": 1.2}
TABLE_CASE = {"fixed-free": "(e)", "fixed-fixed": "(d)"}
BRACED_K_DEFAULT = 1.0           # C5.6.4.3; Table C4.6.2.5-1 case (c)
DEFAULT_K_WARNING = ("Default K values are Table C4.6.2.5-1 design values for idealised end "
                     "conditions — override with a buckling-analysis K if the restraint differs")
UNBRACED_K_LT1_WARNING = ("unbraced K < 1.0 from buckling analysis is below the C5.6.4.3 floor "
                          "('taken as not less than 1.0')")
BRACED_K_LT1_NOTE = "braced K < 1.0 requires supporting analysis"
NO_DEAD_WARNING = ("βd: no Dead-category rows on the column frames; βd = 1.0 (conservative "
                   "upper value) — enter βd or categorise the dead-load cases as Dead")

# Sign convention for single curvature in the CSiBridge frame station output.
# Station moments are INTERNAL forces M(x) on one consistent sign convention,
# so a member with no inflection point (single curvature) has the SAME sign at
# both ends and a member with an inflection point (double curvature) has
# OPPOSITE signs:
#
#   single curvature           double curvature
#   ends: (+30, +10)           ends: (+30, -10)   (M(x) crosses zero)
#
# Controller ruling 6A-1: single curvature = the SAME sign of the station
# (internal) moments at both ends.  Isolated in this one flag (a one-line flip)
# pending confirmation against a user sample (S1).
SINGLE_CURVATURE_OPPOSITE_SIGN = False


def curvature_ratio(Ma: float, Mb: float) -> float:
    """Signed M1/M2 from two end moments (|M1| <= |M2|); + = single curvature."""
    big, small = (Ma, Mb) if abs(Ma) >= abs(Mb) else (Mb, Ma)
    if big == 0.0:
        return 1.0
    mag = abs(small) / abs(big)
    opposite = (big > 0) != (small > 0) and small != 0.0
    single = opposite if SINGLE_CURVATURE_OPPOSITE_SIGN else (not opposite)
    return mag if single else -mag


def slenderness_screen(D: float, K: float, lu: float, braced: bool,
                       M1: float, M2: float) -> dict:
    """Screen K*lu/r against S5.6.4.3.  M1/M2 is taken as M1/M2 (signed by
    curvature, + single); M2 == 0 gives +1 (conservative)."""
    if D <= 0 or lu <= 0:
        raise ValueError("D and lu must be > 0")
    if K <= 0:
        raise ValueError("K must be > 0")
    ratio = 1.0 if M2 == 0 else M1 / M2
    r = 0.25 * D
    klr = K * lu / r
    limit = 34.0 - 12.0 * ratio if braced else 22.0
    out = {"r": r, "klr": klr, "limit": limit, "neglect": klr < limit,
           "approx_ok": klr < 100.0, "ref": REF}
    if K < 1.0:
        out["note"] = BRACED_K_LT1_NOTE if braced else UNBRACED_K_LT1_WARNING
    return out


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _empty(v):
    return v is None or v == ""


def resolve_K_unbraced(spec: dict, axis: str = "") -> dict:
    """Unbraced K (delta_s, unbraced screen) -> {K, source, end_condition, label, warnings}.

    source "default": Table C4.6.2.5-1 design value for `end_condition` (fixed-free
    case (e) 2.1, fixed-fixed case (d) 1.2) with DEFAULT_K_WARNING.  "analysis": the
    entered K (> 0, else ValueError); K < 1.0 is accepted with UNBRACED_K_LT1_WARNING.
    No K_source and a numeric K -> "analysis" (legacy payloads)."""
    spec = spec or {}
    who = f"slenderness axis {axis}: " if axis else ""
    K_in = spec.get("K")
    src = spec.get("K_source")
    if _empty(src):
        src = "analysis" if _is_num(K_in) else "default"
    if src not in K_SOURCES:
        raise ValueError(f"{who}K_source must be one of {K_SOURCES}, got {src!r}")
    end = spec.get("end_condition") or "fixed-free"
    if end not in END_CONDITIONS:
        raise ValueError(f"{who}end_condition must be one of {END_CONDITIONS}, got {end!r}")
    warnings = []
    if src == "analysis":
        if not _is_num(K_in) or not K_in > 0:
            raise ValueError(f"{who}K from buckling analysis must be a number > 0 (got {K_in!r})")
        K = float(K_in)
        label = f"K = {K:g} (buckling analysis)"
        if K < 1.0:
            warnings.append(who + UNBRACED_K_LT1_WARNING)
    else:
        K = TABLE_K[end]
        label = f"K = {K:g} (Table C4.6.2.5-1 case {TABLE_CASE[end]} design value, {end})"
        warnings.append(who + DEFAULT_K_WARNING)
    return {"K": K, "source": src, "end_condition": end, "label": label, "warnings": warnings}


def resolve_K_braced(spec: dict, axis: str = "") -> dict:
    """Braced K (delta_b, braced screen) -> {K, source, label, warnings}.

    `K_braced_source` "default" -> 1.0 (C5.6.4.3; Table C4.6.2.5-1 case (c));
    "analysis" -> `K_braced` (> 0, else ValueError; < 1.0 noted).  Neither given:
    a numeric K_braced -> analysis; else a legacy BRACED axis whose K was a
    buckling-analysis K (K_source "analysis", or a numeric K without K_source)
    keeps that K; else the 1.0 default (ruling M2: legacy states -> 1.0)."""
    spec = spec or {}
    who = f"slenderness axis {axis}: " if axis else ""
    src = spec.get("K_braced_source")
    kb = spec.get("K_braced")
    legacy = False
    if _empty(src):
        if _is_num(kb):
            src = "analysis"
        elif spec.get("braced") and (spec.get("K_source") == "analysis" or (
                _empty(spec.get("K_source")) and _is_num(spec.get("K")))):
            src, kb, legacy = "analysis", spec.get("K"), True
        else:
            src = "default"
    if src not in K_SOURCES:
        raise ValueError(f"{who}K_braced_source must be one of {K_SOURCES}, got {src!r}")
    warnings = []
    if src == "analysis":
        if not _is_num(kb) or not kb > 0:
            raise ValueError(f"{who}braced K from buckling analysis must be a number > 0 "
                             f"(got {kb!r})")
        K = float(kb)
        label = f"K = {K:g} (braced, buckling analysis{'; legacy K field' if legacy else ''})"
        if K < 1.0:
            warnings.append(who + BRACED_K_LT1_NOTE)
    else:
        K = BRACED_K_DEFAULT
        label = "K = 1.0 (braced, C5.6.4.3; Table C4.6.2.5-1 case (c))"
    return {"K": K, "source": src, "label": label, "warnings": warnings}


def resolve_K(spec: dict, axis: str = "") -> dict:
    """K used by the screen for one axis -> {K, source, end_condition, braced, label,
    warnings, K_braced, K_braced_source, K_braced_label, K_unbraced, ...}.

    Braced axis: the braced K (resolve_K_braced).  Unbraced axis: the unbraced K
    (resolve_K_unbraced).  Both K values are always reported (delta_b uses the
    braced K, delta_s the unbraced K; ruling M2)."""
    spec = spec or {}
    braced = bool(spec.get("braced"))
    kb = resolve_K_braced(spec, axis)
    if braced:
        out = {"K": kb["K"], "source": kb["source"],
               "end_condition": spec.get("end_condition") or "fixed-free",
               "label": kb["label"], "warnings": list(kb["warnings"])}
        if out["end_condition"] not in END_CONDITIONS:
            raise ValueError(f"end_condition must be one of {END_CONDITIONS}")
        out.update(K_unbraced=None, K_unbraced_source=None, K_unbraced_label=None)
    else:
        ku = resolve_K_unbraced(spec, axis)
        out = dict(ku)
        out["warnings"] = list(ku["warnings"]) + list(kb["warnings"])
        out.update(K_unbraced=ku["K"], K_unbraced_source=ku["source"],
                   K_unbraced_label=ku["label"])
    out.update(braced=braced, K_braced=kb["K"], K_braced_source=kb["source"],
               K_braced_label=kb["label"])
    return out


def derive(cage_inputs):
    """Derived copy of raw circular inputs (circ_engine.derive_circular)."""
    I = dict(cage_inputs)
    return cc.derive_circular(I) or I


def _Is_bars(bars):
    A = sum(b["As"] for b in bars)
    if A <= 0:
        return 0.0
    yc = sum(b["As"] * b["d_top"] for b in bars) / A
    return sum(b["As"] * (b["d_top"] - yc) ** 2 for b in bars)


def Is_circular(cage_inputs: dict) -> float:
    """sum(As_i * (y_i - yc)^2) over circ_layout bars (about the bar centroid)."""
    bars, _ = cc.circ_layout(derive(cage_inputs))
    return _Is_bars(bars)


def EI_circular(cage_inputs: dict, beta_d: float) -> dict:
    """EI = max(Eq. 5.6.4.3-1, Eq. 5.6.4.3-2) for a circular cage (kip-in^2).

    Ec / Es from circ_engine.derive_circular (the values the LRFD check uses),
    Ig = pi*D^4/64, Is = Is_circular (bars of THIS cage)."""
    I = derive(cage_inputs)
    D = float(I["D"])
    Ec, Es = float(I["Ec"]), float(I["Es"])
    Ig = math.pi * D ** 4 / 64.0
    Is = _Is_bars(I["circ_bars"])
    EI1 = (Ec * Ig / 5.0 + Es * Is) / (1.0 + beta_d)
    EI2 = (Ec * Ig / 2.5) / (1.0 + beta_d)
    return {"Ec": Ec, "Es": Es, "Ig": Ig, "Is": Is, "beta_d": beta_d, "EI1": EI1, "EI2": EI2,
            "EI": max(EI1, EI2), "eq": "5.6.4.3-1" if EI1 >= EI2 else "5.6.4.3-2"}


def euler_Pe(EI: float, K: float, lu: float) -> float:
    """Eq. 4.5.3.2.2b-5: Pe = pi^2*EI/(K*lu)^2 (kip)."""
    return math.pi ** 2 * EI / (K * lu) ** 2


def delta_b(Pu: float, Pe: float, Cm: float):
    """Eq. 4.5.3.2.2b-3 -> delta_b >= 1.0, or None when 1 - Pu/(phiK*Pe) <= 0."""
    den = 1.0 - Pu / (PHI_K * Pe)
    if den <= 0.0:
        return None
    return max(1.0, Cm / den)


def delta_s(sumPu: float, sumPe: float):
    """Eq. 4.5.3.2.2b-4 -> delta_s, or None when 1 - SumPu/(phiK*SumPe) <= 0."""
    den = 1.0 - sumPu / (PHI_K * sumPe)
    if den <= 0.0:
        return None
    return 1.0 / den


def cm_factor(braced: bool, ratio: float) -> float:
    """Eq. 4.5.3.2.2b-6 on braced axes (no transverse loads between supports assumed);
    every other case 1.0."""
    return 0.6 + 0.4 * ratio if braced else 1.0


def _frames(bent, src):
    return src.get("frames") or bent.get("col_frames") or bent.get("frames") or []


def beta_d(bent: dict, rows_by_case: dict, warnings: list = None):
    """(beta_d, source text) for a bent (ruling M7).

    `bent.slender.beta_d` (>= 0) wins.  Else min(1, gamma_p * max|M_dead| / max|Mu|):
    M_dead at a column station = the SUM OF THE ABSOLUTE resultant moments of the
    Dead-category cases there (ruling MF-4: a true upper bound regardless of sign;
    per case the resultant of the per-component |max|), max over the stations;
    Mu = the Strength demand-row resultants of the column frames; gamma_p =
    `bent.slender.gamma_p` (default 1.25; use the largest permanent-load factor of the
    Strength combinations, e.g. 1.5 for DW).  No Dead rows -> 1.0 with NO_DEAD_WARNING."""
    sl = bent.get("slender") or {}
    bd = sl.get("beta_d")
    if not _empty(bd):
        if not _is_num(bd) or bd < 0:
            raise ValueError(f"beta_d must be a number >= 0 (got {bd!r})")
        return float(bd), "user override"
    gp = sl.get("gamma_p")
    gp = GAMMA_P_DEFAULT if _empty(gp) else gp
    if not _is_num(gp) or not gp > 0:
        raise ValueError(f"gamma_p must be a number > 0 (got {gp!r})")
    gp = float(gp)
    src = rows_by_case or {}
    rows, cats = src.get("rows") or [], src.get("categories")
    fs = set(_frames(bent, src))
    dead = [r for r in rows if r.frame in fs and cd._cat(r.case, cats) == "Dead"]
    if not dead:
        if warnings is not None:
            warnings.append(NO_DEAD_WARNING)
        return 1.0, "no Dead rows: 1.0 (conservative upper value)"
    per_case = {}          # (frame, station, case) -> [|M2|, |M3|] maxima
    for r in dead:
        k = (r.frame, round(r.station_in, 6), r.case)
        cur = per_case.setdefault(k, [0.0, 0.0])
        cur[0] = max(cur[0], abs(r.M2))
        cur[1] = max(cur[1], abs(r.M3))
    at = {}
    for (f, st, _), (m2, m3) in per_case.items():
        at[(f, st)] = at.get((f, st), 0.0) + math.hypot(m2, m3)
    Md = max(at.values())
    Ms = max((d["Mu"] for d in cd.demand_rows(rows, list(fs), cats, "Strength")), default=0.0)
    if Ms <= 0:
        return 1.0, "no Strength moment: 1.0 (conservative upper value)"
    v = min(1.0, gp * Md / Ms)
    return v, (f"γp·max Σ|M_dead| / max|Mu| = {gp:g} × {Md / 12.0:.1f} / {Ms / 12.0:.1f} kip-ft"
               + (" (capped at 1.0)" if gp * Md / Ms > 1.0 else ""))


def _axis(bent, ax, warnings=None):
    s = bent["slender"][ax]
    lu = s.get("lu")
    if lu is None:
        lu = bent.get("lu_default_in")
    if lu is None:
        raise ValueError("lu not given and bent['lu_default_in'] missing")
    k = resolve_K(s, ax)
    if warnings is not None:
        warnings.extend(k["warnings"])
    return {"braced": k["braced"], "K": k["K"], "Kb": k["K_braced"],
            "Ku": k["K_unbraced"], "lu": float(lu)}


def _comp(row):
    """Compression magnitude for magnification (ruling M8): concurrent -> -Pu,
    envelope -> -_Pmin; tension (>= 0) -> 0."""
    P = row.get("_Pmin", row["Pu"]) if row.get("_bound") == "envelope" else row["Pu"]
    return -P if P < 0 else 0.0


def _sway_key(row):
    return (row.get("_case"), None if row.get("_bound") == "envelope" else row.get("_step"))


MEMBER_CASE = "(member)"          # colshaft_demands.collapse_member rows
MEMBER_KEY = (MEMBER_CASE, None)
NEGLECT_NOTE = "neglected per §5.6.4.3 screen (δ would be unstable)"


def pu_by_case(rows) -> dict:
    """{(case, step | None for envelope rows): most compressive Pu magnitude} over
    demand rows (ruling M9: the sway-group ΣPu of the other members)."""
    out = {}
    for r in rows or []:
        k = _sway_key(r)
        out[k] = max(out.get(k, 0.0), _comp(r))
    return out


def make_magnifier(bent: dict, rows_by_case: dict, settings: dict, warnings: list = None,
                   sway: dict = None):
    """Transform hook for colshaft_lrfd.  Slenderness off: identity.  On: per row and
    axis the S5.6.4.3 screen, then (not neglected, Pu compressive) the magnification
    of the axis moment by delta = max(delta_b, delta_s) with EI of THIS cage
    (Eqs. 4.5.3.2.2b-1..-6, 5.6.4.3-1/-2; see the module docstring for the M2b/M2s
    bound).  Mu = hypot(delta2*|M2|, delta3*|M3|) (rows without _M2/_M3: Mu *
    max(delta)).  Unstable rows get `_unstable` = True (they fail in the search).

    Tags: _klr2/3, _slender_limit2/3, _slender_status, _delta2/3 (applied),
    _db2/3, _ds2/3, _Pe_b2/3, _Pe_s2/3, _sPe_s2/3, _sPu, _Cm2/3, _EI, _beta_d,
    _Pmag, _Mu1 (first-order Mu), _unstable, _unstable_reason.

    `rows_by_case` = {"rows": [ForceRow...], "frames": [...], "categories": {...}|None}
    (end moments for M1/M2 and the Dead rows for beta_d).  `sway` (colshaft_engine,
    sway group of several bents, two-pass): {"group", "n_members", "Pe_others":
    {"2","3"}, "Pu_others": {(case, step|None): kip}}.  The returned transform has
    `.beta_d`, `.beta_d_source`, `.axes` and `.props(raw)` (EI / Pe per axis)."""
    if not settings.get("slenderness_on"):
        return lambda cage, rows: rows
    axes = {ax: _axis(bent, ax, warnings) for ax in ("2", "3")}
    src = rows_by_case or {}
    bd, bd_src = beta_d(bent, src, warnings)
    cache = {}
    ei_cache = {}
    warned = set()

    def ratios(row):
        if row.get("_bound") != "concurrent" or not src.get("rows"):
            return {"2": 1.0, "3": 1.0}
        key = (row.get("_case"), row.get("_step"))
        if key not in cache:
            em = cd.end_moments(src["rows"], src.get("frames") or bent.get("frames"),
                                key[0], key[1], categories=src.get("categories"))
            cache[key] = (None if em is None else
                          {a: curvature_ratio(*em["M" + a]) for a in ("2", "3")})
        return cache[key] or {"2": 1.0, "3": 1.0}

    def props(raw):
        # ruling MF-1: Is depends on the ring radius (cover, transverse bar size, ring 2)
        # and EI on Ec / Es -> key on every raw input
        k = tuple(sorted((key, repr(v)) for key, v in raw.items()))
        if k not in ei_cache:
            e = EI_circular(raw, bd)
            e["Pe_b"] = {ax: euler_Pe(e["EI"], a["Kb"], a["lu"]) for ax, a in axes.items()}
            e["Pe_s"] = {ax: (euler_Pe(e["EI"], a["Ku"], a["lu"]) if a["Ku"] else None)
                         for ax, a in axes.items()}
            ei_cache[k] = e
        return ei_cache[k]

    def sum_pu(row, P):
        if not sway:
            return P
        key = _sway_key(row)
        if row.get("_case") == MEMBER_CASE:          # ruling MF-3 (collapsed member rows)
            key = MEMBER_KEY
        others = (sway.get("Pu_others") or {}).get(key)
        if others is None:
            n = int(sway.get("n_members") or 1)
            if warnings is not None and key not in warned:
                warned.add(key)
                warnings.append(f"sway group {sway.get('group')}: no matching load case {key[0]!r}"
                                f"{'' if key[1] is None else ' step ' + repr(key[1])} on every "
                                f"member; ΣPu = Pu × {n} members")
            return P * n
        return P + others

    def transform(cage, rows):
        raw = cage["inputs"]
        D = float(raw["D"])
        e = props(raw)
        out = []
        for r in rows:
            rt = ratios(r)
            t = dict(r)
            worst = ST_NEGLECT
            P = _comp(r)
            sP = sum_pu(r, P) if P > 0 else 0.0
            dl = {}
            unstable = False
            for ax, a in axes.items():
                sc = slenderness_screen(D, a["K"], a["lu"], a["braced"], rt[ax], 1.0)
                t["_klr" + ax] = sc["klr"]
                t["_slender_limit" + ax] = sc["limit"]
                st = (ST_REFINED if not sc["approx_ok"] else
                      ST_NEGLECT if sc["neglect"] else ST_MAGNIFIED)
                if _RANK[st] > _RANK[worst]:
                    worst = st
                Cm = cm_factor(a["braced"], rt[ax])
                Pe_b = e["Pe_b"][ax]
                db = delta_b(P, Pe_b, Cm) if P > 0 else 1.0
                if a["braced"]:
                    ds, Pe_s, sPe = 1.0, None, None
                else:
                    Pe_s = e["Pe_s"][ax]
                    sPe = Pe_s + float(((sway or {}).get("Pe_others") or {}).get(ax) or 0.0)
                    ds = delta_s(sP, sPe) if P > 0 else 1.0
                t.update({"_Cm" + ax: Cm, "_Pe_b" + ax: Pe_b, "_Pe_s" + ax: Pe_s,
                          "_sPe_s" + ax: sPe, "_db" + ax: db, "_ds" + ax: ds})
                if st == ST_NEGLECT:
                    dl[ax] = 1.0
                    if P > 0 and (db is None or ds is None):
                        t["_neglect_note" + ax] = NEGLECT_NOTE
                        t["_neglect_note"] = NEGLECT_NOTE
                elif db is None or ds is None:
                    unstable = True
                    dl[ax] = None
                else:
                    dl[ax] = max(db, ds)
                t["_delta" + ax] = dl[ax]
            t["_slender_status"] = worst
            t.update(_EI=e["EI"], _beta_d=bd, _Pmag=P, _sPu=sP, _Mu1=r["Mu"],
                     _unstable=unstable)
            if unstable:
                t["_unstable_reason"] = UNSTABLE_REASON
            else:
                d2, d3 = dl["2"], dl["3"]
                if "_M2" in r and "_M3" in r:
                    Mu = math.hypot(d2 * abs(r["_M2"]), d3 * abs(r["_M3"]))
                else:
                    Mu = abs(r["Mu"]) * max(d2, d3)
                t["Mu"] = math.copysign(Mu, r["Mu"]) if r["Mu"] else Mu
            out.append(t)
        return out

    transform.beta_d = bd
    transform.beta_d_source = bd_src
    transform.axes = axes
    transform.props = props
    transform.sway = sway
    return transform
