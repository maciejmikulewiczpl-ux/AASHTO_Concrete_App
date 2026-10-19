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
"""
import circ_engine as cc
import colshaft_demands as cd

REF = ("AASHTO LRFD 10th §5.6.4.3 (limits 22 and 34 - 12(M1/M2)); "
       "r per C5.6.4.3; <100 per §5.6.4.1")

ST_NEGLECT = "neglect"
ST_PENDING = "magnification pending verification (S6)"
ST_REFINED = "refined analysis required"
_RANK = {ST_NEGLECT: 0, ST_PENDING: 1, ST_REFINED: 2}

# Sign convention for single curvature in the CSiBridge frame station output.
# Station moments are INTERNAL forces M(x) on one consistent sign convention,
# so a member with no inflection point (single curvature) has the SAME sign at
# both ends and a member with an inflection point (double curvature) has
# OPPOSITE signs:
#
#   single curvature           double curvature
#   ends: (+30, +10)           ends: (+30, -10)   (M(x) crosses zero)
#
# The controller brief (P1) ruled the opposite ("opposite sign = single
# curvature", end-reaction reading).  That contradicts the internal-force
# reading above, and the wrong choice is unconservative for true single
# curvature, so the default follows the internal-force reading and the choice
# is isolated in this one flag, pending controller/S1 confirmation.
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
    if not braced and K < 1.0:
        raise ValueError("Unbraced K must be >= 1.0 (C5.6.4.3)")
    ratio = 1.0 if M2 == 0 else M1 / M2
    r = 0.25 * D
    klr = K * lu / r
    limit = 34.0 - 12.0 * ratio if braced else 22.0
    out = {"r": r, "klr": klr, "limit": limit, "neglect": klr < limit,
           "approx_ok": klr < 100.0, "ref": REF}
    if braced and K < 1.0:
        out["note"] = "braced K < 1.0 requires supporting analysis"
    return out


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


def _axis(bent, ax):
    s = bent["slender"][ax]
    lu = s.get("lu")
    if lu is None:
        lu = bent.get("lu_default_in")
    if lu is None:
        raise ValueError("lu not given and bent['lu_default_in'] missing")
    return bool(s["braced"]), float(s["K"]), float(lu)


def make_magnifier(bent: dict, rows_by_case: dict, settings: dict):
    """Transform hook for colshaft_lrfd.  With slenderness off: identity.  On:
    row copies tagged _klr2/_klr3, _slender_limit2/3, _slender_status and
    _delta2 = _delta3 = None; Mu is UNCHANGED (magnification blocked, S6).

    `rows_by_case` = {"rows": [ForceRow...], "frames": [...], "categories":
    {...}|None}; missing/empty gives M1/M2 = +1 for every row."""
    if not settings.get("slenderness_on"):
        return lambda cage, rows: rows
    axes = {ax: _axis(bent, ax) for ax in ("2", "3")}
    for ax, (braced, K, _) in axes.items():
        if not braced and K < 1.0:
            raise ValueError(f"Unbraced K must be >= 1.0 (axis {ax})")
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
