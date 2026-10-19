"""Column-on-Shaft demand grouping (pure functions, stdlib only).

Turns csi_import ForceRow lists (kip, kip-in, in) into demand-row dicts for the
circular AASHTO engine: {"Pu","Mu","Vu","Tu","Vp","Ms","Ps"} with Pu < 0 =
compression, plus tags _frame, _station (in), _case, _bound, _Pmin, _Pmax
(and _step for concurrent rows).  Envelope rows follow spec 4.1a.
"""
import math
import re

_DEAD = re.compile(r"DEAD|^DC", re.IGNORECASE)
_EXTREME = re.compile(r"EQ|EXT|SEIS", re.IGNORECASE)
_IGNORE = re.compile(r"SERV", re.IGNORECASE)


def default_case_category(case):
    """Strength / Extreme / Dead / Ignore; first match wins."""
    if _DEAD.search(case):
        return "Dead"
    if _EXTREME.search(case):
        return "Extreme"
    if _IGNORE.search(case):
        return "Ignore"
    return "Strength"


def _cat(case, categories):
    c = categories.get(case) if categories else None
    return c if c is not None else default_case_category(case)


def _select(rows, frames, categories, category):
    fs = set(frames)
    return [r for r in rows
            if r.frame in fs and _cat(r.case, categories) == category]


def demand_rows(rows, frames, categories, category, warnings=None):
    """Demand dicts for rows of `frames` whose case maps to `category`.

    Concurrent rows -> one dict each (hypot resultants).  Envelope (Max/Min)
    rows -> one dict per (frame, station, case): Pu = P_max (algebraic max,
    least compression), M/V = hypot of the per-component absolute maxima over
    the Max and Min rows, T = max |T|, _Pmin/_Pmax bound P.  A case with only
    Max or only Min rows uses the one present for both and appends a warning
    to `warnings` (if given).
    """
    out = []
    groups = {}   # envelope key -> rows; the key itself holds the slot in `out`
    for r in _select(rows, frames, categories, category):
        if r.envelope:
            key = (r.frame, round(r.station_in, 6), r.case)
            if key not in groups:
                groups[key] = []
                out.append(key)
            groups[key].append(r)
        else:
            out.append({
                "Pu": r.P, "Mu": math.hypot(r.M2, r.M3),
                "Vu": math.hypot(r.V2, r.V3), "Tu": abs(r.T),
                "Vp": 0, "Ms": 0, "Ps": 0,
                "_frame": r.frame, "_station": r.station_in, "_case": r.case,
                "_step": r.step_type, "_bound": "concurrent",
                "_Pmin": r.P, "_Pmax": r.P})
    res = []
    for item in out:
        if not isinstance(item, tuple):
            res.append(item)
            continue
        g = groups[item]
        steps = {x.step_type.strip().lower() for x in g}
        if not ("max" in steps and "min" in steps) and warnings is not None:
            warnings.append(
                f"Frame {item[0]} station {g[0].station_in / 12.0:g} ft case "
                f"{item[2]}: only {'/'.join(sorted(steps))} envelope row "
                "present; used for both bounds")
        ps = [x.P for x in g]
        res.append({
            "Pu": max(ps),
            "Mu": math.hypot(max(abs(x.M2) for x in g), max(abs(x.M3) for x in g)),
            "Vu": math.hypot(max(abs(x.V2) for x in g), max(abs(x.V3) for x in g)),
            "Tu": max(abs(x.T) for x in g),
            "Vp": 0, "Ms": 0, "Ps": 0,
            "_frame": item[0], "_station": g[0].station_in, "_case": item[2],
            "_bound": "envelope", "_Pmin": min(ps), "_Pmax": max(ps)})
    return res


def _rng(d):
    return d.get("_Pmin", d["Pu"]), d.get("_Pmax", d["Pu"])


def _dominates(b, a):
    bl, bh = _rng(b)
    al, ah = _rng(a)
    return (b["Pu"] >= a["Pu"] and b["Mu"] >= a["Mu"] and b["Vu"] >= a["Vu"]
            and b["Tu"] >= a["Tu"] and bl <= al and ah <= bh)


def prune_dominated(rows):
    """Drop rows dominated by another row of the same frame.  Exactly equal
    rows: the first in input order is kept."""
    keep = []
    for i, a in enumerate(rows):
        dominated = False
        for j, b in enumerate(rows):
            if i == j or b.get("_frame") != a.get("_frame"):
                continue
            if _dominates(b, a):
                if _dominates(a, b) and i < j:   # mutual (equal): first wins
                    continue
                dominated = True
                break
        if not dominated:
            keep.append(a)
    return keep


def collapse_member(rows):
    """One envelope row per frame (member mode): max P_max, max M/V/T, min P_min."""
    by = {}
    for d in rows:
        by.setdefault(d.get("_frame"), []).append(d)
    out = []
    for f, g in by.items():
        out.append({
            "Pu": max(_rng(d)[1] for d in g),
            "Mu": max(d["Mu"] for d in g), "Vu": max(d["Vu"] for d in g),
            "Tu": max(d["Tu"] for d in g), "Vp": 0, "Ms": 0, "Ps": 0,
            "_frame": f, "_station": None, "_case": "(member)",
            "_bound": "envelope",
            "_Pmin": min(_rng(d)[0] for d in g),
            "_Pmax": max(_rng(d)[1] for d in g)})
    return out


def _extent(rows, frame):
    st = [r.station_in for r in rows if r.frame == frame]
    return (min(st), max(st)) if st else (None, None)


def _mean_at(rows, frame, station):
    ps = [r.P for r in rows if r.frame == frame
          and math.isclose(r.station_in, station, abs_tol=1e-6)]
    return sum(ps) / len(ps) if ps else None


def detect_base_end(rows, frames, warnings=None):
    """'min' or 'max': the station end with the lower (more compressive) mean P
    over all rows, decided per frame, majority over frames.  A frame whose two
    ends tie casts no vote; an overall tie returns 'max' and appends a warning
    to `warnings` (if given)."""
    votes = {"min": 0, "max": 0}
    for f in frames:
        lo, hi = _extent(rows, f)
        if lo is None or lo == hi:
            continue
        a, b = _mean_at(rows, f, lo), _mean_at(rows, f, hi)
        if math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9):
            continue
        votes["min" if a < b else "max"] += 1
    if votes["min"] > votes["max"]:
        return "min"
    if votes["max"] > votes["min"]:
        return "max"
    if warnings is not None:
        warnings.append("Base end could not be determined from axial force "
                        "(tie); assuming the maximum station is the base")
    return "max"


def base_axial(rows, frames, categories, category, base_end="auto", warnings=None):
    """P values at the base station of each frame over all rows of `category`
    (both Max and Min rows for envelopes)."""
    be = detect_base_end(rows, frames, warnings) if base_end == "auto" else base_end
    out = []
    for f in frames:
        lo, hi = _extent(rows, f)
        if lo is None:
            continue
        s = lo if be == "min" else hi
        out.extend(r.P for r in _select(rows, [f], categories, category)
                   if math.isclose(r.station_in, s, abs_tol=1e-6))
    return out


def column_height_in(rows, frames):
    """Sum over frames of (max station - min station), inches."""
    h = 0.0
    for f in frames:
        lo, hi = _extent(rows, f)
        if lo is not None:
            h += hi - lo
    return h


def end_moments(rows, frames, case, step, warnings=None):
    """{"M2": (top, bottom), "M3": (top, bottom)} signed kip-in for one
    concurrent (case, step), or None if the case has only envelope rows or the
    step is missing at either end.  Uses the first frame in `frames`; the
    bottom is the detected base end (detect_base_end over `frames`)."""
    if not frames:
        return None
    f = frames[0]
    lo, hi = _extent(rows, f)
    if lo is None or lo == hi:
        return None
    be = detect_base_end(rows, frames, warnings)
    bot_s, top_s = (lo, hi) if be == "min" else (hi, lo)

    def find(s):
        for r in rows:
            if (r.frame == f and r.case == case and not r.envelope
                    and r.step_type == step
                    and math.isclose(r.station_in, s, abs_tol=1e-6)):
                return r
        return None
    top, bot = find(top_s), find(bot_s)
    if top is None or bot is None:
        return None
    return {"M2": (top.M2, bot.M2), "M3": (top.M3, bot.M3)}
