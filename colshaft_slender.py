"""Column-on-shaft slenderness screen (AASHTO LRFD 10th Ed. S5.6.4.3).

Only the *screen* is implemented.  Moment magnification (delta_b, delta_s, Cm,
Pe, EI; Art. 4.5.3.2.2b and the S5.6.4.3 EI equations) is BLOCKED on spec item
S6: those equations are not in the verified text, so none are written here.
`make_magnifier` therefore only TAGS rows; Mu is never changed.

Cited, verified text (Chapter 5 markdown):
  * S5.6.4.3: neglect when K*lu/r < 22 (unbraced) or < 34 - 12(M1/M2) (braced);
    M1/M2 positive for single curvature, negative for double curvature.
  * C5.6.4.3: r = 0.25*D for a circular member.
  * S5.6.4.1: approximate procedure only for K*lu/r < 100.
  * C5.6.4.3: "For members braced against sidesway, the effective length factor,
    K, is taken as 1.0, unless it is shown by analysis that a lower value may be
    used." and "For members not braced against sidesway, K is determined with due
    consideration for the effects of cracking and reinforcement on relative
    stiffness and is taken as not less than 1.0."

K per axis (user decision 2026-10-19, `resolve_K`): `K_source` "default" (braced
1.0 per C5.6.4.3; unbraced = the Euler ideal value for the axis `end_condition`,
fixed-free 2.0 / fixed-fixed 1.0 - NOT the Art. 4.6.2.5 / Table C4.6.2.5-1 design
values, which are not available here: open item) or "analysis" (the entered `K`
from a buckling analysis, any K > 0; unbraced K < 1.0 is accepted with a warning).
A legacy axis with a numeric `K` and no `K_source` is treated as "analysis".
"""
import circ_engine as cc
import colshaft_demands as cd

REF = ("AASHTO LRFD 10th §5.6.4.3 (limits 22 and 34 - 12(M1/M2)); "
       "r per C5.6.4.3; <100 per §5.6.4.1")

ST_NEGLECT = "neglect"
ST_PENDING = "magnification pending verification (S6)"
ST_REFINED = "refined analysis required"
_RANK = {ST_NEGLECT: 0, ST_PENDING: 1, ST_REFINED: 2}

K_SOURCES = ("default", "analysis")
END_CONDITIONS = ("fixed-free", "fixed-fixed")
EULER_K = {"fixed-free": 2.0, "fixed-fixed": 1.0}     # theoretical (Euler) ideal values
DEFAULT_K_WARNING = ("Default K is the theoretical Euler value; AASHTO design values "
                     "(Art. 4.6.2.5) are higher — override with a buckling-analysis K if available")
UNBRACED_K_LT1_WARNING = ("unbraced K < 1.0 from buckling analysis is below the C5.6.4.3 floor "
                          "('taken as not less than 1.0')")
BRACED_K_LT1_NOTE = "braced K < 1.0 requires supporting analysis"

# Sign convention for single curvature in the CSiBridge frame station output.
# Station moments are INTERNAL forces M(x) on one consistent sign convention,
# so a member with no inflection point (single curvature) has the SAME sign at
# both ends and a member with an inflection point (double curvature) has
# OPPOSITE signs:
#
#   single curvature           double curvature
#   ends: (+30, +10)           ends: (+30, -10)   (M(x) crosses zero)
#
# Controller ruling 6A-1 (spec rulings appendix; supersedes the earlier P1
# "opposite sign = single curvature" statement): single curvature = the SAME
# sign of the station (internal) moments at both ends; opposite signs = double
# curvature.  The choice is isolated in this one flag (a one-line flip) pending
# confirmation against a user sample (S1).
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
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def resolve_K(spec: dict, axis: str = "") -> dict:
    """K for one slenderness axis -> {K, source, end_condition, braced, label, warnings}.

    source "default": braced -> 1.0 (C5.6.4.3); unbraced -> EULER_K[end_condition]
    with DEFAULT_K_WARNING.  source "analysis": the entered K (> 0, else ValueError);
    unbraced K < 1.0 is accepted with UNBRACED_K_LT1_WARNING.  No K_source and a
    numeric K -> "analysis" (legacy payloads: the user typed K)."""
    spec = spec or {}
    who = f"slenderness axis {axis}: " if axis else ""
    braced = bool(spec.get("braced"))
    K_in = spec.get("K")
    src = spec.get("K_source")
    if src in (None, ""):
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
            warnings.append(who + (BRACED_K_LT1_NOTE if braced else UNBRACED_K_LT1_WARNING))
    elif braced:
        K = 1.0
        label = "K = 1.0 (braced, C5.6.4.3)"
    else:
        K = EULER_K[end]
        label = (f"K = {K:.1f} (Euler ideal, {end}; not the AASHTO Table C4.6.2.5-1 "
                 "design value)")
        warnings.append(who + DEFAULT_K_WARNING)
    return {"K": K, "source": src, "end_condition": end, "braced": braced, "label": label,
            "warnings": warnings}


def derive(cage_inputs):
    """Derived copy of raw circular inputs (circ_engine.derive_circular)."""
    I = dict(cage_inputs)
    return cc.derive_circular(I) or I


def Is_circular(cage_inputs: dict) -> float:
    """sum(As_i * (y_i - yc)^2) over circ_layout bars (about the bar centroid)."""
    bars, _ = cc.circ_layout(derive(cage_inputs))
    A = sum(b["As"] for b in bars)
    if A <= 0:
        return 0.0
    yc = sum(b["As"] * b["d_top"] for b in bars) / A
    return sum(b["As"] * (b["d_top"] - yc) ** 2 for b in bars)


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
    return k["braced"], k["K"], float(lu)


def make_magnifier(bent: dict, rows_by_case: dict, settings: dict, warnings: list = None):
    """Transform hook for colshaft_lrfd.  With slenderness off: identity.  On:
    row copies tagged _klr2/_klr3, _slender_limit2/3, _slender_status and
    _delta2 = _delta3 = None; Mu is UNCHANGED (magnification blocked, S6).

    `rows_by_case` = {"rows": [ForceRow...], "frames": [...], "categories":
    {...}|None}; missing/empty gives M1/M2 = +1 for every row.  K per axis from
    resolve_K; its warnings are appended to `warnings` when given."""
    if not settings.get("slenderness_on"):
        return lambda cage, rows: rows
    axes = {ax: _axis(bent, ax, warnings) for ax in ("2", "3")}
    src = rows_by_case or {}
    cache = {}

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

    def transform(cage, rows):
        D = float(cage["inputs"]["D"])
        out = []
        for r in rows:
            rt = ratios(r)
            t = dict(r)
            worst = ST_NEGLECT
            for ax, (braced, K, lu) in axes.items():
                sc = slenderness_screen(D, K, lu, braced, rt[ax], 1.0)
                t["_klr" + ax] = sc["klr"]
                t["_slender_limit" + ax] = sc["limit"]
                st = (ST_REFINED if not sc["approx_ok"] else
                      ST_NEGLECT if sc["neglect"] else ST_PENDING)
                if _RANK[st] > _RANK[worst]:
                    worst = st
            t["_slender_status"] = worst
            t["_delta2"] = t["_delta3"] = None
            out.append(t)
        return out
    return transform
