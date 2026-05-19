"""Standalone Oasys GSA -> concrete-app demand-table force extractor.

Reads a JSON or YAML config that describes one or more *jobs*. Each job:
  - identifies a target (element, list of elements, group, or property);
  - names the GSA combination to envelope across (its permutations are
    enumerated automatically);
  - lists which forces (Pu, Mu, Vu, Tu, Vp, Ps, Ms) to output and how each
    GSA local-axis force/moment maps to those names;
  - lists envelope rules (max / min / max_abs on a chosen force, top-N).

For each envelope rule the script writes ONE row per rank, preserving all
*coexistent* forces from the same GSA permutation (so e.g. the "max Mu"
row carries the actual Pu, Vu, Tu that occurred in that permutation).

Output is:
  - a pretty-printed table to stdout (one block per job);
  - a CSV file (paste-friendly into Excel or the concrete app's demand
    table; column order matches the app);
  - optionally a TSV file (handy for direct cell-paste into spreadsheets).

This tool is fully decoupled from the AASHTO concrete app. It does not
import calc_engine, api, or app, and writing/running it cannot affect any
of the app's tests or behaviour.

Usage:
    python gsa_force_extractor.py <config.json|.yaml>

Run `python gsa_force_extractor.py --help` for CLI options.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

# ---------------------------------------------------------------------------
# Force naming
# ---------------------------------------------------------------------------

APP_FORCE_ORDER = ["Pu", "Mu", "Vu", "Tu", "Ps", "Ms"]
APP_REACTION_ORDER = ["Rx", "Ry", "Rz", "Rxx", "Ryy", "Rzz"]
META_COLUMNS = ["Job", "Note", "Element", "Position", "Combo", "Permutation"]

# Internal-use only: the force kind -> "force" or "moment", controls unit conv.
FORCE_KIND = {
    "Pu": "force", "Vu": "force", "Ps": "force",
    "Mu": "moment", "Tu": "moment", "Ms": "moment",
}
REACTION_KIND = {
    "Rx": "force", "Ry": "force", "Rz": "force",
    "Rxx": "moment", "Ryy": "moment", "Rzz": "moment",
}

# App sign convention (kept here so it's discoverable):
#   Pu < 0 = compression, Pu > 0 = tension
#   Mu < 0 = hogging,     Mu > 0 = sagging
# (Same applies to Ps and Ms.) The signs config below describes GSA's
# convention; if GSA disagrees with the app, the script flips on read.
BENDING_FORCES = ("Mu", "Ms")
AXIAL_FORCES = ("Pu", "Ps")
REACTION_BENDING = ("Ryy", "Rzz")
REACTION_AXIAL = ("Rz",)

# GSA local-axis names this script understands.
GSA_AXES = {"Fx", "Fy", "Fz", "Mxx", "Myy", "Mzz"}

# ---------------------------------------------------------------------------
# Unit conversion (kept tiny on purpose; no third-party deps)
# ---------------------------------------------------------------------------

# Force conversions to kip
_FORCE_TO_KIP = {
    "kip": 1.0, "kips": 1.0,
    "lbf": 1.0 / 1000.0, "lb": 1.0 / 1000.0,
    "n": 1.0 / 4448.2216,
    "kn": 1000.0 / 4448.2216,
    "mn": 1_000_000.0 / 4448.2216,
}

# Length conversions to inch (used inside moment conversion)
_LENGTH_TO_IN = {
    "in": 1.0, "inch": 1.0, "inches": 1.0,
    "ft": 12.0, "feet": 12.0,
    "mm": 1.0 / 25.4,
    "cm": 1.0 / 2.54,
    "m": 1000.0 / 25.4,
}


def _parse_moment_unit(name: str) -> tuple[str, str]:
    """Split a moment-unit string into (force_unit, length_unit).

    Accepts forms like "kN.m", "kN-m", "kN*m", "kN m", "kip-in", "lbf-ft".
    """
    s = name.strip()
    for sep in (".", "-", "*", " "):
        if sep in s:
            f, _, l = s.partition(sep)
            return f.strip(), l.strip()
    raise ValueError(
        f"Cannot parse moment unit {name!r}; expected forms like 'kN.m', "
        f"'kip-in', 'lbf*ft'."
    )


def force_factor(from_unit: str) -> float:
    key = from_unit.strip().lower()
    if key not in _FORCE_TO_KIP:
        raise ValueError(
            f"Unknown force unit {from_unit!r}. Known: {sorted(_FORCE_TO_KIP)}"
        )
    return _FORCE_TO_KIP[key]


def moment_factor(from_unit: str) -> float:
    f, l = _parse_moment_unit(from_unit)
    return force_factor(f) * length_factor(l)


def length_factor(from_unit: str) -> float:
    key = from_unit.strip().lower()
    if key not in _LENGTH_TO_IN:
        raise ValueError(
            f"Unknown length unit {from_unit!r}. Known: {sorted(_LENGTH_TO_IN)}"
        )
    return _LENGTH_TO_IN[key]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class UnitsCfg:
    """User-configured output units. GSA source units are detected at runtime."""
    output_force: str = "kip"
    output_moment: str = "kip-in"


# Default GSA units used as fallback when auto-detection fails.
DEFAULT_GSA_FORCE = "kN"
DEFAULT_GSA_MOMENT = "kN.m"


@dataclass
class SignsCfg:
    # Each flag describes GSA's convention. The script flips iff GSA's
    # convention disagrees with the app's convention.
    #
    # axial_compression_positive_in_gsa:
    #   GSA's typical convention is tension-positive (Fx<0 = compression),
    #   which matches the app -- no flip needed -> default False.
    #
    # moment_hogging_positive_in_gsa:
    #   Set True only if your GSA model uses hogging-positive moments
    #   and you need the output flipped to app convention (Mu<0 = hogging).
    #   Default False (no flip) — the envelope then operates directly on
    #   the GSA values, which is the most intuitive for extraction.
    axial_compression_positive_in_gsa: bool = False
    moment_hogging_positive_in_gsa: bool = False


@dataclass
class EnvelopeRule:
    action: str        # "max" | "min" | "max_abs"
    on: str            # one of forces_to_output, e.g. "Mu"
    top_n: int = 1


@dataclass
class JobCfg:
    name: str
    location: dict           # one of element / elements / group / property + position
    combo: str
    axes: dict[str, str]     # app-name -> GSA axis (e.g. {"Pu": "Fx", "Mu": "Mzz"})
    forces_to_output: list[str]
    envelopes: list[EnvelopeRule]
    result_type: str = "element_forces"  # "element_forces" or "node_reactions"
    in_batch: bool = True    # whether this job is ticked for batch extraction


@dataclass
class Config:
    gsa_file: str
    output_csv: Optional[str]
    output_tsv: Optional[str]
    units: UnitsCfg
    signs: SignsCfg
    jobs: list[JobCfg]


def _read_config_file(path: str) -> dict:
    """Read a JSON or YAML config file. YAML requires PyYAML installed."""
    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if ext in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                f"Config {path} is YAML but PyYAML is not installed. "
                f"Either `pip install pyyaml` or convert the config to JSON."
            ) from e
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return _strip_comments(data)


def _strip_comments(obj: Any) -> Any:
    """Recursively drop keys beginning with '_' (used as JSON comments)."""
    if isinstance(obj, dict):
        return {k: _strip_comments(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_strip_comments(v) for v in obj]
    return obj


def _parse_units(d: dict) -> UnitsCfg:
    """Build UnitsCfg from a config dict, accepting both new and legacy keys.

    New-style keys: ``output_force``, ``output_moment``.
    Legacy keys:    ``gsa_force``, ``gsa_moment`` (treated as output units
                    for backward compatibility — old configs assumed
                    kip/kip-in output but declared GSA source units in the
                    same block; new configs name them explicitly).
    """
    out_f = d.get("output_force") or d.get("gsa_force") or "kip"
    out_m = d.get("output_moment") or d.get("gsa_moment") or "kip-in"
    return UnitsCfg(output_force=out_f, output_moment=out_m)


def load_config(path: str) -> Config:
    raw = _read_config_file(path)
    if not isinstance(raw, dict):
        raise ValueError(f"Top-level config in {path} must be a mapping.")

    units = _parse_units(raw.get("units") or {})
    signs = SignsCfg(**(raw.get("signs") or {}))

    jobs_raw = raw.get("jobs")
    if not jobs_raw:
        raise ValueError(f"Config {path} has no 'jobs' list.")
    jobs: list[JobCfg] = []
    for i, j in enumerate(jobs_raw):
        try:
            jobs.append(_parse_job(j))
        except Exception as e:
            raise ValueError(f"Job #{i + 1} ({j.get('name', '<unnamed>')}): {e}") from e

    cfg = Config(
        gsa_file=raw["gsa_file"],
        output_csv=raw.get("output_csv"),
        output_tsv=raw.get("output_tsv"),
        units=units,
        signs=signs,
        jobs=jobs,
    )
    _validate_config(cfg)
    return cfg


def _parse_job(j: dict) -> JobCfg:
    envelopes = [
        EnvelopeRule(
            action=e["action"],
            on=e["on"],
            top_n=int(e.get("top_n", 1)),
        )
        for e in j["envelopes"]
    ]
    return JobCfg(
        name=j["name"],
        location=dict(j["location"]),
        combo=j["combo"],
        axes=dict(j["axes"]),
        forces_to_output=list(j["forces_to_output"]),
        envelopes=envelopes,
        result_type=j.get("result_type", "element_forces"),
        in_batch=bool(j.get("in_batch", True)),
    )


def config_to_dict(cfg: Config) -> dict:
    """Inverse of load_config: produce a JSON/YAML-ready dict."""
    return {
        "gsa_file": cfg.gsa_file,
        "output_csv": cfg.output_csv,
        "output_tsv": cfg.output_tsv,
        "units": {
            "output_force": cfg.units.output_force,
            "output_moment": cfg.units.output_moment,
        },
        "signs": {
            "axial_compression_positive_in_gsa": cfg.signs.axial_compression_positive_in_gsa,
            "moment_hogging_positive_in_gsa": cfg.signs.moment_hogging_positive_in_gsa,
        },
        "jobs": [
            {
                "name": j.name,
                "location": dict(j.location),
                "combo": j.combo,
                "axes": dict(j.axes),
                "forces_to_output": list(j.forces_to_output),
                "envelopes": [
                    {"action": e.action, "on": e.on, "top_n": e.top_n}
                    for e in j.envelopes
                ],
                "result_type": j.result_type,
                "in_batch": j.in_batch,
            }
            for j in cfg.jobs
        ],
    }


def save_config(cfg: Config, path: str) -> None:
    """Write config to disk as JSON or YAML (by file extension)."""
    _validate_config(cfg)
    data = config_to_dict(cfg)
    ext = os.path.splitext(path)[1].lower()
    with open(path, "w", encoding="utf-8") as f:
        if ext in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
            except ImportError as e:
                raise RuntimeError(
                    "Cannot write YAML: PyYAML is not installed. "
                    "Use a .json extension or install pyyaml."
                ) from e
            yaml.safe_dump(data, f, sort_keys=False)
        else:
            json.dump(data, f, indent=2)


def _validate_config(cfg: Config) -> None:
    for j in cfg.jobs:
        is_reaction = (j.result_type == "node_reactions")
        allowed_forces = APP_REACTION_ORDER if is_reaction else APP_FORCE_ORDER
        rtype_label = "Node Reactions" if is_reaction else "Element Forces"

        # Forces requested must be supported names.
        for f in j.forces_to_output:
            if f not in allowed_forces:
                # Check if the name belongs to the other result type.
                other = APP_FORCE_ORDER if is_reaction else APP_REACTION_ORDER
                if f in other:
                    hint = (
                        f" ('{f}' is a {'element force' if is_reaction else 'reaction'} "
                        f"name — switch the job's Result Type to "
                        f"'{'Element Forces' if is_reaction else 'Node Reactions'}' "
                        f"or choose the correct force names)"
                    )
                else:
                    hint = ""
                raise ValueError(
                    f"Job {j.name!r} (Result Type: {rtype_label}): "
                    f"forces_to_output contains {f!r} which is not valid "
                    f"for this result type; allowed names are "
                    f"{allowed_forces}.{hint}"
                )
            if f not in j.axes:
                raise ValueError(
                    f"Job {j.name!r}: forces_to_output lists {f!r} but no "
                    f"axis mapping is given in 'axes'."
                )
        # Axis mappings must point at known GSA axes.
        for app_name, gsa_axis in j.axes.items():
            if app_name not in allowed_forces:
                raise ValueError(
                    f"Job {j.name!r} (Result Type: {rtype_label}): "
                    f"axis mapping for unknown force {app_name!r}; "
                    f"allowed names are {allowed_forces}."
                )
            if gsa_axis not in GSA_AXES:
                raise ValueError(
                    f"Job {j.name!r}: axes[{app_name!r}] = {gsa_axis!r}; "
                    f"allowed axes are {sorted(GSA_AXES)}."
                )
        # Envelope `on` must be in forces_to_output.
        for e in j.envelopes:
            if e.action not in ("max", "min", "max_abs"):
                raise ValueError(
                    f"Job {j.name!r}: envelope action {e.action!r} not in "
                    f"('max','min','max_abs')."
                )
            if e.on not in j.forces_to_output:
                if e.on in allowed_forces:
                    hint = (
                        f" — tick the '{e.on}' checkbox in the job editor, "
                        f"or remove this envelope rule"
                    )
                else:
                    other = APP_FORCE_ORDER if is_reaction else APP_REACTION_ORDER
                    if e.on in other:
                        hint = (
                            f" — '{e.on}' is a "
                            f"{'element force' if is_reaction else 'reaction'} name "
                            f"but this job's Result Type is '{rtype_label}'; "
                            f"switch the Result Type or fix the envelope"
                        )
                    else:
                        hint = ""
                raise ValueError(
                    f"Job {j.name!r} (Result Type: {rtype_label}): "
                    f"envelope on={e.on!r} is not in the job's "
                    f"forces_to_output {j.forces_to_output}.{hint}"
                )
            if e.top_n < 1:
                raise ValueError(
                    f"Job {j.name!r}: envelope top_n must be >= 1, got {e.top_n}."
                )
        # Location selector validation — different for reactions vs element forces.
        if is_reaction:
            sel = [k for k in ("node", "nodes") if k in j.location]
            if len(sel) != 1:
                raise ValueError(
                    f"Job {j.name!r} (Result Type: {rtype_label}): "
                    f"location must contain exactly one of node / nodes "
                    f"(got {sel}). Switch to the 'Node Reactions' result "
                    f"type and set a node ID."
                )
        else:
            sel = [k for k in ("element", "elements", "group", "property") if k in j.location]
            if len(sel) != 1:
                raise ValueError(
                    f"Job {j.name!r} (Result Type: {rtype_label}): "
                    f"location must contain exactly one of "
                    f"element / elements / group / property (got {sel})."
                )
            if "position" not in j.location:
                raise ValueError(f"Job {j.name!r}: location.position is required.")
            pos = j.location["position"]
            if not _is_max_position(pos):
                try:
                    float(pos)
                except (TypeError, ValueError):
                    raise ValueError(
                        f"Job {j.name!r}: location.position must be a number "
                        f"(0..1) or the string 'max'; got {pos!r}."
                    )


# ---------------------------------------------------------------------------
# Envelope (pure, fully testable without gsapy)
# ---------------------------------------------------------------------------

def envelope(perm_rows: list[dict], action: str, on: str, top_n: int = 1) -> list[dict]:
    """Pick the top-N permutations for the given action on the given key.

    `perm_rows` is a list of dicts already converted to app units/signs
    (so `on` is e.g. "Mu" and the value is in kip-in). Each row carries
    *all* coexistent forces; this function returns the N rows themselves
    (a list slice, not per-component envelopes).
    """
    if action == "max":
        keyfn: Callable[[dict], float] = lambda r: r[on]
        reverse = True
    elif action == "min":
        keyfn = lambda r: r[on]
        reverse = False
    elif action == "max_abs":
        keyfn = lambda r: abs(r[on])
        reverse = True
    else:
        raise ValueError(f"Unknown envelope action {action!r}")
    ranked = sorted(perm_rows, key=keyfn, reverse=reverse)
    return ranked[:top_n]


def envelope_note(action: str, on: str, rank: int, total: int) -> str:
    pretty = {"max": f"max {on}", "min": f"min {on}", "max_abs": f"max |{on}|"}[action]
    return f"{pretty} (rank {rank}/{total})"


# ---------------------------------------------------------------------------
# Convert raw GSA permutation force dicts to app-named, app-unit dicts
# ---------------------------------------------------------------------------

def _conversion_factors(gsa_force_unit: str, gsa_moment_unit: str,
                        output_units: UnitsCfg) -> tuple[float, float]:
    """Pre-compute force and moment conversion factors (call once)."""
    f = force_factor(gsa_force_unit) / force_factor(output_units.output_force)
    m = moment_factor(gsa_moment_unit) / moment_factor(output_units.output_moment)
    return f, m


def gsa_perm_to_app_row(
    perm: dict,
    axes: dict[str, str],
    forces_to_output: list[str],
    gsa_force_unit: str,
    gsa_moment_unit: str,
    output_units: UnitsCfg,
    signs: SignsCfg,
    *,
    _factors: Optional[tuple[float, float]] = None,
) -> dict:
    """Translate ONE GSA permutation force-dict into output-unit force values.

    `perm` shape: {"perm_id": "Cp7", "Fx": ..., "Fy": ..., "Mzz": ..., ...}
    Values are in GSA display units.  Returns a dict containing the
    requested app force names (Pu, Mu, ...) converted to the user's chosen
    output units plus "perm_id".

    Pass *_factors* (from ``_conversion_factors()``) to avoid recomputing
    unit ratios on every call.
    """
    out: dict[str, Any] = {"perm_id": perm["perm_id"]}
    if _factors is not None:
        f_factor, m_factor = _factors
    else:
        f_factor = force_factor(gsa_force_unit) / force_factor(output_units.output_force)
        m_factor = moment_factor(gsa_moment_unit) / moment_factor(output_units.output_moment)
    for app_name in forces_to_output:
        gsa_axis = axes[app_name]
        v = float(perm[gsa_axis])
        if FORCE_KIND[app_name] == "force":
            v *= f_factor
        else:
            v *= m_factor
        # Flip iff GSA's convention disagrees with the app's.
        if app_name in AXIAL_FORCES and signs.axial_compression_positive_in_gsa:
            v = -v
        if app_name in BENDING_FORCES and signs.moment_hogging_positive_in_gsa:
            v = -v
        out[app_name] = v
    return out


def gsa_perm_to_app_reaction_row(
    perm: dict,
    axes: dict[str, str],
    forces_to_output: list[str],
    gsa_force_unit: str,
    gsa_moment_unit: str,
    output_units: UnitsCfg,
    signs: SignsCfg,
) -> dict:
    """Translate ONE GSA permutation reaction-dict into output-unit values.

    Same logic as gsa_perm_to_app_row but uses REACTION_KIND for the
    force/moment classification and REACTION_AXIAL / REACTION_BENDING
    for sign flips.
    """
    out: dict[str, Any] = {"perm_id": perm["perm_id"]}
    f_factor = force_factor(gsa_force_unit) / force_factor(output_units.output_force)
    m_factor = moment_factor(gsa_moment_unit) / moment_factor(output_units.output_moment)
    for app_name in forces_to_output:
        gsa_axis = axes[app_name]
        v = float(perm[gsa_axis])
        if REACTION_KIND[app_name] == "force":
            v *= f_factor
        else:
            v *= m_factor
        if app_name in REACTION_AXIAL and signs.axial_compression_positive_in_gsa:
            v = -v
        if app_name in REACTION_BENDING and signs.moment_hogging_positive_in_gsa:
            v = -v
        out[app_name] = v
    return out


# ---------------------------------------------------------------------------
# gsapy adapter (kept thin and version-tolerant)
# ---------------------------------------------------------------------------

class GsaAdapter:
    """Thin wrapper over a gsapy.GSA model.

    Real gsapy is the Arup-hosted package
    (`pip install https://packages.arup.com/gsapy.tar.gz`), version 0.9.16+.
    Its model exposes `get_elements`, `case_num_perm`, `case_perm_string`,
    and `get_1D_elem_resultants`.

    Tests substitute a duck-typed MockGsaModel for `model`; the mock only
    needs to provide those four methods (see tests/test_gsa_force_extractor.py).
    """

    # Resolution along the element. POSITION_RESOLUTION=4 -> 5 result points
    # at fractions 0.00, 0.25, 0.50, 0.75, 1.00. Coarse enough to scan
    # quickly, fine enough for design-action extraction at standard
    # quarter-points.
    POSITION_RESOLUTION = 4  # number of intervals between end points

    def __init__(self, model: Any, gsapy_version: str = "unknown"):
        self.model = model
        self.gsapy_version = gsapy_version
        self._forces_cache: dict[tuple[int, str], list[tuple[float, dict]]] = {}
        self._perm_cache: dict[str, list[str]] = {}

    @classmethod
    def from_file(cls, path: str) -> "GsaAdapter":
        try:
            import gsapy  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "gsapy is not installed. The PyPI 'gsapy' package is an empty "
                "placeholder; install the real Arup-hosted package via "
                "`pip install https://packages.arup.com/gsapy.tar.gz`."
            ) from e
        version = getattr(gsapy, "__version__", "unknown")
        model = gsapy.GSA(path)
        return cls(model, gsapy_version=version)

    # --- unit discovery ------------------------------------------------

    def discover_units(self) -> Optional[tuple[str, str]]:
        """Read the model's display units via gsapy.

        Returns (force_unit, moment_unit) strings matching the model's
        display settings, or None if discovery fails. gsapy returns
        numbers in these units, so they are the authoritative source.
        """
        try:
            names = self.model.get_unit_names()
        except Exception:
            return None
        force = str(names.get("FORCE", "")).strip()
        length = str(names.get("LENGTH", "")).strip()
        if not force or not length:
            return None
        moment = f"{force}.{length}"
        try:
            force_factor(force)
            moment_factor(moment)
        except ValueError:
            return None
        return (force, moment)

    # --- element selection ---------------------------------------------

    def elements_in_group(self, name: str) -> list[int]:
        """Resolve a GSA saved-list name to its element IDs.

        In GSA, what users typically call a 'group' is a saved list of
        elements. gsapy's `get_elements(name)` accepts the saved-list name
        directly and returns a {element_id: Element} dict.
        """
        elems = self.model.get_elements(name)
        return sorted(int(k) for k in elems.keys())

    def elements_with_property(self, prop: int) -> list[int]:
        """Return element IDs whose section-property number matches `prop`."""
        elems = self.model.get_elements()  # dict {id: Element}
        prop = int(prop)
        return sorted(
            int(idx) for idx, e in elems.items()
            if int(getattr(e, "prop", -1)) == prop
        )

    # --- permutation enumeration ---------------------------------------

    def list_permutations(self, combo: str) -> list[str]:
        """Return one case-string per permutation of `combo` (e.g. 'C1').

        If the combo has no permutations (deterministic combination), returns
        a single-element list with the bare combo string so the caller's
        envelope loop still does one pass.  Results are cached per combo.
        """
        cached = self._perm_cache.get(combo)
        if cached is not None:
            return cached
        case_type, case_ref = _parse_case_id(combo)
        n = int(self.model.case_num_perm(case_type=case_type, case_ref=case_ref))
        if n <= 0:
            result = [combo]
        else:
            result = [
                str(self.model.case_perm_string(
                    case_type=case_type, case_ref=case_ref, perm_num=i,
                ))
                for i in range(1, n + 1)
            ]
        self._perm_cache[combo] = result
        return result

    # --- force extraction ----------------------------------------------

    def elem_forces_at(self, elem: int, position: float, perm: str) -> dict:
        """Return GSA local-axis forces at (elem, position) for one case.

        gsapy's `get_1D_elem_resultants` returns a list of 6-item lists
        [Fx, Fy, Fz, Mxx, Myy, Mzz] at evenly-spaced points along the
        element. With addl_pts=99 there are 101 points (resolution 0.01);
        we pick the index closest to `position` (which must be in [0, 1]).
        """
        all_pts = self.elem_forces_all_positions(elem, perm)
        idx = round(float(position) * (len(all_pts) - 1))
        idx = max(0, min(len(all_pts) - 1, idx))
        return all_pts[idx][1]

    def elem_forces_all_positions(self, elem: int, perm: str) -> list[tuple[float, dict]]:
        """Return forces at every sample point along the element.

        Output is a list of (position_fraction, {axis: float}) tuples, one
        per point; positions span 0.0..1.0 in equal increments. Used by the
        "position=max" feature to scan along the element.

        Results are cached per (elem, perm) for the lifetime of this adapter.
        """
        key = (elem, perm)
        cached = self._forces_cache.get(key)
        if cached is not None:
            return cached
        addl = self.POSITION_RESOLUTION - 1
        try:
            # axis='local' is mandatory: 'default' follows the model's view
            # axis and on inclined members returns globally-resolved forces,
            # which are nonsense for beam design.
            results = self.model.get_1D_elem_resultants(
                index=elem, case=perm, axis="local", addl_pts=addl,
            )
        except Exception as e:
            # gsapy raises gsapy.util.GSAError (and sometimes triggers
            # an internal TypeError on its empty-result recursion path).
            # Translate to an actionable message.
            raise RuntimeError(
                f"GSA returned no forces for element {elem} in case {perm!r}.\n"
                f"  Likely causes (check in GSA itself):\n"
                f"    - Element {elem} does not exist in the model.\n"
                f"    - Element {elem} is not a 1D beam element "
                f"(get_1D_elem_resultants only works on beams).\n"
                f"    - Case {perm!r} has no analysis results — re-run analysis in GSA.\n"
                f"    - Combo name in the config doesn't match GSA "
                f"(e.g. 'C1' vs 'A1' vs case sensitivity).\n"
                f"  gsapy underlying error: {e}"
            ) from None
        if not results:
            raise RuntimeError(
                f"No 1D resultants for element {elem} case {perm!r}. "
                f"Check the case has analysis results in GSA."
            )
        n = len(results)
        out: list[tuple[float, dict]] = []
        for i, f in enumerate(results):
            pos = i / (n - 1) if n > 1 else 0.0
            out.append((pos, {
                "Fx":  float(f[0]),
                "Fy":  float(f[1]),
                "Fz":  float(f[2]),
                "Mxx": float(f[3]),
                "Myy": float(f[4]),
                "Mzz": float(f[5]),
            }))
        self._forces_cache[key] = out
        return out


def _parse_case_id(s: str) -> tuple[str, int]:
    """Parse a GSA case identifier like 'C1', 'A12', 'L3' into (letter, n)."""
    s = str(s).strip().upper()
    if not s or not s[0].isalpha():
        raise ValueError(
            f"Cannot parse case id {s!r}; expected forms like 'C1' or 'A2'."
        )
    try:
        return s[0], int(s[1:])
    except ValueError as e:
        raise ValueError(f"Cannot parse case id {s!r}: {e}")


# ---------------------------------------------------------------------------
# GsaAPI (.NET) adapter — batch result fetching for dramatically faster runs
# ---------------------------------------------------------------------------

# Map GsaAPI enum names to the unit strings our converter understands.
_GSAAPI_FORCE_UNIT = {
    "Newton": "N", "KiloNewton": "kN", "MegaNewton": "MN",
    "PoundForce": "lbf", "KiloPoundForce": "kip",
}
_GSAAPI_LENGTH_UNIT = {
    "Meter": "m", "Centimeter": "cm", "Millimeter": "mm",
    "Foot": "ft", "Inch": "in",
}


class GsaApiAdapter:
    """GsaAPI (.NET) backend — uses batch queries for dramatically faster
    extraction.

    Requires ``pythonnet`` and Oasys GSA 10.x installed.  The key advantage
    over the gsapy COM adapter is that ``Element1dForce`` returns results for
    *all* requested elements and *all* permutations in a single API call,
    avoiding the per-element x per-permutation COM round-trip overhead.

    Callers must invoke ``prefetch(combo, elements)`` before querying
    permutations or forces; ``run_job`` does this automatically.
    """

    POSITION_RESOLUTION = 4  # same as GsaAdapter

    # Default DLL search paths (newest first).
    _DLL_SEARCH = [
        r"C:\Program Files\Oasys\GSA 10.2\GsaAPI",
        r"C:\Program Files\Oasys\GSA 10.1\GsaAPI",
        r"C:\Program Files\Oasys\GSA 10.0\GsaAPI",
    ]

    def __init__(self, model: Any):
        self._model = model
        # Populated by prefetch(): combo -> {elem_id -> perm_list}
        # Each perm_list entry is a list of position dicts.
        self._combo_cache: dict[str, dict[int, list[list[dict]]]] = {}
        self._perm_count_cache: dict[str, int] = {}
        # Warning messages surfaced in the GUI's extraction-warnings dialog.
        # Currently populated by:
        #   - _lazy_fetch when an element missing from prefetch cache is
        #     recovered on-demand (signals a prefetch regression).
        #   - run_job when prefetch skips elements that have no
        #     Element1dForce data (springs/links/excluded-from-analysis).
        self._lazy_fetch_log: list[str] = []
        # Populated by prefetch(): combo -> list of element IDs that
        # Element1dForce returned no data for. run_job reads this to filter
        # the candidate iteration so a single bad element doesn't fail the
        # whole job.
        self._missing_in_prefetch: dict[str, list[int]] = {}

    @classmethod
    def from_file(cls, path: str) -> "GsaApiAdapter":
        """Open a GSA model via GsaAPI (.NET).

        Raises RuntimeError if pythonnet or GsaAPI.dll is not available.
        """
        try:
            import clr  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "pythonnet is not installed. Install it with "
                "`pip install pythonnet`."
            ) from e

        loaded = False
        for dll in cls._DLL_SEARCH:
            try:
                clr.AddReference(dll)
                loaded = True
                break
            except Exception:
                continue
        if not loaded:
            raise RuntimeError(
                "GsaAPI.dll not found. Searched:\n  "
                + "\n  ".join(cls._DLL_SEARCH)
                + "\nInstall Oasys GSA 10.x or adjust _DLL_SEARCH."
            )

        from GsaAPI import Model as GsaModel  # type: ignore
        model = GsaModel(path)
        return cls(model)

    # --- unit discovery ------------------------------------------------

    def discover_units(self) -> Optional[tuple[str, str]]:
        """Return the units GsaAPI results are expressed in.

        GsaAPI **always** returns forces in Newtons and moments in N·m
        (SI base) regardless of the model's display-unit settings.  This
        differs from gsapy which returns values in the model's display units.
        """
        return ("N", "N.m")

    # --- element selection ---------------------------------------------

    def elements_in_group(self, name: str) -> list[int]:
        """Resolve a GSA saved-list name to its element IDs."""
        from GsaAPI import EntityType as ET  # type: ignore
        lists = self._model.Lists()
        for lid in lists.Keys:
            lst = lists[lid]
            if lst.Name == name and lst.Type == ET.Element:
                ids = self._model.ExpandList(lst)
                return sorted(int(i) for i in ids)
        raise RuntimeError(f"No GSA element list named {name!r} found.")

    def elements_with_property(self, prop: int) -> list[int]:
        """Return element IDs whose section-property number matches `prop`."""
        elements = self._model.Elements()
        prop = int(prop)
        result = []
        for eid in elements.Keys:
            e = elements[eid]
            if int(e.Property) == prop:
                result.append(int(eid))
        return sorted(result)

    # --- batch prefetch ------------------------------------------------

    def prefetch(self, combo: str, elements: list[int],
                 progress_cb: Optional[Callable[[int, int], None]] = None,
                 ) -> None:
        """Batch-fetch forces for `elements` x all permutations of `combo`.

        After this call, ``list_permutations``, ``elem_forces_all_positions``,
        and ``elem_forces_at`` all serve from cache with zero latency.

        If *progress_cb* is given it is called as
        ``progress_cb(elem_idx, n_elements)`` after each element is fetched.
        """
        if combo in self._combo_cache:
            cached = self._combo_cache[combo]
            if all(e in cached for e in elements):
                return

        _case_type, case_ref = _parse_case_id(combo)
        # Validate the combo exists up-front (cheap; throws early).
        combo_results = self._model.CombinationCaseResults()
        if case_ref not in combo_results:
            raise RuntimeError(
                f"Combination case {combo!r} (ref {case_ref}) not found in "
                f"model results. Has analysis been run in GSA?"
            )

        # Query elements individually — GsaAPI batch Element1dForce
        # only returns position data for the lowest element ID, and the
        # underlying Results1D is not thread-safe (AccessViolationException).
        # CRITICAL: bind the intermediate CombinationCaseResults() to a
        # NAMED Python variable before indexing it — i.e.
        #     combo_results = self._model.CombinationCaseResults()
        #     ccr = combo_results[case_ref]
        # NOT the chained form `ccr = self._model.CombinationCaseResults()[case_ref]`.
        # In the chained form pythonnet discards the intermediate wrapper
        # and the underlying .NET object can finalize before Element1dForce
        # runs, returning an empty Dict for every element. _lazy_fetch uses
        # the named-intermediate pattern and works reliably; keep them in
        # sync.
        cache: dict[int, list[list[dict]]] = {}
        n_perms = 0
        n_elems = len(elements)
        for ei, eid in enumerate(elements):
            if progress_cb is not None:
                progress_cb(ei, n_elems)
            combo_results = self._model.CombinationCaseResults()
            ccr = combo_results[case_ref]
            elem_data, perms_returned = self._parse_element1d_force(ccr, int(eid))
            if elem_data is not None:
                cache[int(eid)] = elem_data
                n_perms = max(n_perms, perms_returned)

        if combo in self._combo_cache:
            self._combo_cache[combo].update(cache)
        else:
            self._combo_cache[combo] = cache
        self._perm_count_cache[combo] = max(
            self._perm_count_cache.get(combo, 0), n_perms
        )
        # Record elements that Element1dForce returned no data for (after
        # merging into the persistent cache, so previously-cached elements
        # from lazy_fetch or prior prefetch calls aren't falsely flagged).
        final_cache = self._combo_cache[combo]
        self._missing_in_prefetch[combo] = [
            int(eid) for eid in elements if int(eid) not in final_cache
        ]

    def _parse_element1d_force(self, ccr: Any, eid: int
                               ) -> tuple[Optional[list[list[dict]]], int]:
        """Query Element1dForce for one element and translate the result.

        Returns (elem_data, n_perms) where elem_data is a list of perm rows
        (each a list of position dicts), or (None, 0) if GsaAPI returned
        no data for `eid`. Reused by prefetch() and the lazy fallback in
        elem_forces_all_positions().
        """
        n_pts = self.POSITION_RESOLUTION + 1
        forces = ccr.Element1dForce(str(eid), n_pts, None)
        for elem_id in forces.Keys:
            if int(elem_id) != eid:
                continue
            perm_list = forces[elem_id]
            elem_data: list[list[dict]] = []
            for perm_positions in perm_list:
                positions: list[dict] = []
                for d6 in perm_positions:
                    positions.append({
                        "Fx": float(d6.X), "Fy": float(d6.Y),
                        "Fz": float(d6.Z), "Mxx": float(d6.XX),
                        "Myy": float(d6.YY), "Mzz": float(d6.ZZ),
                    })
                elem_data.append(positions)
            return elem_data, len(perm_list)
        return None, 0

    def _lazy_fetch(self, combo: str, elem: int) -> bool:
        """Lazy single-element prefetch. Returns True if `elem` was added
        to the cache, False if GsaAPI has no Element1dForce data for it.

        Used as a fallback in elem_forces_all_positions/elem_forces_at
        when an element is unexpectedly missing from the prefetch cache.
        """
        _case_type, case_ref = _parse_case_id(combo)
        combo_results = self._model.CombinationCaseResults()
        if case_ref not in combo_results:
            return False
        ccr = combo_results[case_ref]
        elem_data, n_perms = self._parse_element1d_force(ccr, elem)
        if elem_data is None:
            return False
        cache = self._combo_cache.setdefault(combo, {})
        cache[elem] = elem_data
        self._perm_count_cache[combo] = max(
            self._perm_count_cache.get(combo, 0), n_perms
        )
        msg = (
            f"[gsa_force_extractor] WARNING: element {elem} was missing "
            f"from prefetch cache for {combo!r}; recovered via lazy fetch "
            f"({n_perms} perms). This indicates a silent drop in prefetch."
        )
        self._lazy_fetch_log.append(msg)
        if sys.stderr is not None:
            try:
                sys.stderr.write(msg + "\n")
            except Exception:
                pass
        return True

    # --- permutation enumeration ---------------------------------------

    def list_permutations(self, combo: str) -> list[str]:
        """Return permutation name strings for `combo`.

        Requires ``prefetch()`` to have been called first (so the perm
        count is known from the result data).
        """
        n = self._perm_count_cache.get(combo)
        if n is None:
            raise RuntimeError(
                f"Call prefetch({combo!r}, elements) before "
                f"list_permutations. GsaApiAdapter requires prefetch."
            )
        if n <= 0:
            return [combo]
        case_type, case_ref = _parse_case_id(combo)
        return [f"{case_type}{case_ref}p{i}" for i in range(1, n + 1)]

    # --- force extraction (from cache) ---------------------------------

    def elem_forces_all_positions(
        self, elem: int, perm: str,
    ) -> list[tuple[float, dict]]:
        """Return forces at every sample point along the element (from cache)."""
        combo, perm_idx = self._parse_perm_string(perm)
        cache = self._combo_cache.get(combo)
        if cache is None or elem not in cache:
            if not self._lazy_fetch(combo, elem):
                raise RuntimeError(
                    f"Element {elem} has no Element1dForce results in "
                    f"combo {combo!r} (perm {perm!r}). The element may be a "
                    f"non-beam type (spring, link, mass), excluded from this "
                    f"analysis task, or deleted from the model while still "
                    f"referenced by a saved list."
                )
            cache = self._combo_cache[combo]
        positions = cache[elem][perm_idx]
        n = len(positions)
        return [
            (i / (n - 1) if n > 1 else 0.0, dict(p))
            for i, p in enumerate(positions)
        ]

    def elem_forces_at(self, elem: int, position: float, perm: str) -> dict:
        """Return GSA local-axis forces at (elem, position) for one case."""
        all_pts = self.elem_forces_all_positions(elem, perm)
        idx = round(float(position) * (len(all_pts) - 1))
        idx = max(0, min(len(all_pts) - 1, idx))
        return all_pts[idx][1]

    @staticmethod
    def _parse_perm_string(perm: str) -> tuple[str, int]:
        """Parse 'C1p3' → ('C1', 2): combo string + 0-based perm index."""
        if "p" in perm:
            combo, _, num = perm.rpartition("p")
            return combo, int(num) - 1
        return perm, 0

    # --- node reaction batch prefetch & query --------------------------

    def prefetch_reactions(self, combo: str, nodes: list[int]) -> None:
        """Batch-fetch node reactions for `nodes` x all permutations of `combo`.

        After this call, ``node_reactions`` serves from cache.
        Signature mirrors ``NodeReactionForce(node_list_str, axis)``
        which returns Dict[int, ReadOnlyCollection[Double6]].
        """
        cache_key = f"_rxn_{combo}"
        if hasattr(self, "_reaction_cache") and cache_key in self._reaction_cache:
            cached = self._reaction_cache[cache_key]
            if all(n in cached for n in nodes):
                return

        _case_type, case_ref = _parse_case_id(combo)
        combo_results = self._model.CombinationCaseResults()
        if case_ref not in combo_results:
            raise RuntimeError(
                f"Combination case {combo!r} (ref {case_ref}) not found in "
                f"model results. Has analysis been run in GSA?"
            )
        ccr = combo_results[case_ref]
        node_str = " ".join(str(n) for n in nodes)
        # axis=None → global axes (reactions are at supports)
        reactions = ccr.NodeReactionForce(node_str, None)

        cache: dict[int, list[dict]] = {}
        n_perms = 0
        for node_id in reactions.Keys:
            nid = int(node_id)
            perm_list = reactions[node_id]
            n_perms = max(n_perms, len(perm_list))
            node_data: list[dict] = []
            for d6 in perm_list:
                node_data.append({
                    "Fx": float(d6.X), "Fy": float(d6.Y),
                    "Fz": float(d6.Z), "Mxx": float(d6.XX),
                    "Myy": float(d6.YY), "Mzz": float(d6.ZZ),
                })
            cache[nid] = node_data

        if not hasattr(self, "_reaction_cache"):
            self._reaction_cache: dict[str, dict[int, list[dict]]] = {}
        if cache_key in self._reaction_cache:
            self._reaction_cache[cache_key].update(cache)
        else:
            self._reaction_cache[cache_key] = cache
        # Update perm count (shared with element forces)
        self._perm_count_cache[combo] = max(
            self._perm_count_cache.get(combo, 0), n_perms
        )

    def node_reactions(self, node: int, perm: str) -> dict:
        """Return reaction forces at a node for one permutation (from cache)."""
        combo, perm_idx = self._parse_perm_string(perm)
        cache_key = f"_rxn_{combo}"
        cache = getattr(self, "_reaction_cache", {}).get(cache_key)
        if cache is None or node not in cache:
            raise RuntimeError(
                f"Node {node} perm {perm!r} not in reaction cache. "
                f"Call prefetch_reactions() first."
            )
        return dict(cache[node][perm_idx])


# ---------------------------------------------------------------------------
# Factory: prefer GsaAPI, fall back to gsapy
# ---------------------------------------------------------------------------

def open_gsa_model(path: str) -> Any:
    """Open a GSA model file, preferring GsaAPI (.NET) over gsapy (COM).

    GsaAPI is dramatically faster due to batch result queries. If neither
    backend is available, raises RuntimeError.
    """
    try:
        return GsaApiAdapter.from_file(path)
    except Exception:
        return GsaAdapter.from_file(path)


# ---------------------------------------------------------------------------
# Element resolution from a location spec
# ---------------------------------------------------------------------------

def resolve_target_elements(adapter: Any, location: dict) -> list[int]:
    if "element" in location:
        return [int(location["element"])]
    if "elements" in location:
        return [int(e) for e in location["elements"]]
    if "group" in location:
        return adapter.elements_in_group(str(location["group"]))
    if "property" in location:
        return adapter.elements_with_property(int(location["property"]))
    raise ValueError("location must contain element / elements / group / property")


def resolve_target_nodes(location: dict) -> list[int]:
    """Resolve node IDs from a reaction job's location spec."""
    if "node" in location:
        return [int(location["node"])]
    if "nodes" in location:
        return [int(n) for n in location["nodes"]]
    raise ValueError("Reaction job location must contain 'node' or 'nodes'.")


# ---------------------------------------------------------------------------
# Run a single job: returns the list of output rows (each row a dict)
# ---------------------------------------------------------------------------

def _is_max_position(position: Any) -> bool:
    return isinstance(position, str) and position.strip().lower() == "max"


def _format_group_label(location: dict, elements: list[int]) -> str:
    """Readable label for a summed element group, used in the Element column."""
    if "group" in location:
        return f"sum({location['group']})"
    if "property" in location:
        return f"sum(prop {location['property']})"
    if len(elements) <= 4:
        return f"sum({','.join(str(e) for e in elements)})"
    return f"sum({elements[0]}..{elements[-1]} n={len(elements)})"


def _summed_forces_at(adapter: GsaAdapter, elements: list[int], position: float, perm: str) -> dict:
    """Sum element-local force components across `elements` at a fixed
    (position, permutation). NOTE: this assumes axes/local frames are
    consistent across the summed elements -- the user's responsibility."""
    summed = {a: 0.0 for a in GSA_AXES}
    for e in elements:
        raw = adapter.elem_forces_at(e, position, perm)
        for a in GSA_AXES:
            summed[a] += raw[a]
    return summed


def _summed_sweeps(adapter: GsaAdapter, elements: list[int], perm: str
                   ) -> list[tuple[float, dict]]:
    """All-position summed forces across a list of elements for ONE perm.
    Each element's sweep must have the same number of points (same
    POSITION_RESOLUTION); zips them and sums element-wise."""
    sweeps = [adapter.elem_forces_all_positions(e, perm) for e in elements]
    n_pts = len(sweeps[0])
    if any(len(s) != n_pts for s in sweeps):
        raise RuntimeError(
            "Cannot sum across elements: position-sweep lengths differ. "
            "All summed elements must use the same gsapy point resolution."
        )
    out = []
    for i in range(n_pts):
        pos = sweeps[0][i][0]
        summed = {a: sum(s[i][1][a] for s in sweeps) for a in GSA_AXES}
        out.append((pos, summed))
    return out


def _candidates_for_target(adapter: GsaAdapter, elements: list[int], job: JobCfg,
                           gsa_force_unit: str, gsa_moment_unit: str,
                           output_units: UnitsCfg, signs: SignsCfg,
                           position: Any, use_max_position: bool,
                           sum_across: bool,
                           progress_cb: Optional[Callable[[int, int], None]] = None,
                           ) -> list[dict]:
    """Build envelope-input rows for one extraction target.

    A 'target' is either ONE element (per-element output) or a group of
    elements whose forces are summed component-wise (one synthetic output).

    If *progress_cb* is given it is called as ``progress_cb(i, n)`` after
    each permutation is fetched (i = 0-based index, n = total perms).
    """
    perm_names = adapter.list_permutations(job.combo)
    if not perm_names:
        raise RuntimeError(
            f"Job {job.name!r}: combo {job.combo!r} has no permutations."
        )
    candidates: list[dict] = []
    n_perms = len(perm_names)
    factors = _conversion_factors(gsa_force_unit, gsa_moment_unit, output_units)
    if use_max_position:
        for pi, p in enumerate(perm_names):
            if sum_across:
                points = _summed_sweeps(adapter, elements, p)
            else:
                points = adapter.elem_forces_all_positions(elements[0], p)
            for pos, raw in points:
                raw = dict(raw)  # don't mutate the cached dict
                raw["perm_id"] = p
                app_row = gsa_perm_to_app_row(
                    raw, job.axes, job.forces_to_output,
                    gsa_force_unit, gsa_moment_unit, output_units, signs,
                    _factors=factors,
                )
                app_row["_position"] = pos
                candidates.append(app_row)
            if progress_cb is not None:
                progress_cb(pi, n_perms)
    else:
        pos_f = float(position)
        for pi, p in enumerate(perm_names):
            if sum_across:
                raw = _summed_forces_at(adapter, elements, pos_f, p)
            else:
                raw = dict(adapter.elem_forces_at(elements[0], pos_f, p))
            raw["perm_id"] = p
            app_row = gsa_perm_to_app_row(
                raw, job.axes, job.forces_to_output,
                gsa_force_unit, gsa_moment_unit, output_units, signs,
                _factors=factors,
            )
            app_row["_position"] = pos_f
            candidates.append(app_row)
            if progress_cb is not None:
                progress_cb(pi, n_perms)
    return candidates


def _format_node_label(location: dict, nodes: list[int]) -> str:
    """Readable label for a summed node group, used in the Element column."""
    if len(nodes) <= 4:
        return f"sum(n{','.join(str(n) for n in nodes)})"
    return f"sum(n{nodes[0]}..n{nodes[-1]} n={len(nodes)})"


def _summed_reactions(adapter: Any, nodes: list[int], perm: str) -> dict:
    """Sum reaction forces across `nodes` for one permutation."""
    summed = {a: 0.0 for a in GSA_AXES}
    for n in nodes:
        raw = adapter.node_reactions(n, perm)
        for a in GSA_AXES:
            summed[a] += raw[a]
    return summed


def _candidates_for_reaction_target(
    adapter: Any, nodes: list[int], job: JobCfg,
    gsa_force_unit: str, gsa_moment_unit: str,
    output_units: UnitsCfg, signs: SignsCfg,
    sum_across: bool,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> list[dict]:
    """Build envelope-input rows for a reaction extraction target.

    Simpler than _candidates_for_target: no position scanning (reactions
    are at nodes, not along elements).
    """
    perm_names = adapter.list_permutations(job.combo)
    if not perm_names:
        raise RuntimeError(
            f"Job {job.name!r}: combo {job.combo!r} has no permutations."
        )
    candidates: list[dict] = []
    n_perms = len(perm_names)
    for pi, p in enumerate(perm_names):
        if sum_across:
            raw = _summed_reactions(adapter, nodes, p)
        else:
            raw = dict(adapter.node_reactions(nodes[0], p))
        raw["perm_id"] = p
        app_row = gsa_perm_to_app_reaction_row(
            raw, job.axes, job.forces_to_output,
            gsa_force_unit, gsa_moment_unit, output_units, signs,
        )
        app_row["_position"] = 0.0
        candidates.append(app_row)
        if progress_cb is not None:
            progress_cb(pi, n_perms)
    return candidates


def run_job(adapter: Any, job: JobCfg,
            gsa_force_unit: str, gsa_moment_unit: str,
            output_units: UnitsCfg, signs: SignsCfg,
            progress_cb: Optional[Callable[[int, int, int, int], None]] = None,
            ) -> list[dict]:
    """Run a single extraction job.

    If *progress_cb* is given it is called as
    ``progress_cb(target_idx, n_targets, perm_idx, n_perms)`` after each
    permutation is fetched, allowing the caller to update a progress dialog.
    """
    if job.result_type == "node_reactions":
        return _run_reaction_job(adapter, job, gsa_force_unit, gsa_moment_unit,
                                 output_units, signs, progress_cb)

    elements = resolve_target_elements(adapter, job.location)
    if not elements:
        raise RuntimeError(f"Job {job.name!r}: no elements resolved from location.")

    position = job.location["position"]
    use_max_position = _is_max_position(position)
    sum_across = bool(job.location.get("sum_across_elements", False))

    # Batch-prefetch if supported (GsaApiAdapter). Progress callback is
    # forwarded so the GUI can show per-element fetch progress.
    if hasattr(adapter, "prefetch"):
        def _prefetch_progress(ei: int, n: int) -> None:
            if progress_cb is not None:
                progress_cb(ei, n, 0, 1)
        adapter.prefetch(job.combo, elements,
                         progress_cb=_prefetch_progress)

        # Drop elements that have no Element1dForce data — saved lists can
        # include springs/links/masses or elements excluded from this
        # analysis task. Continuing with the remaining elements is more
        # useful than failing the whole job on the first bad one; we
        # surface the skip in the GUI's warnings dialog.
        missing = list(getattr(adapter, "_missing_in_prefetch", {})
                       .get(job.combo, []))
        if missing:
            preview = ", ".join(str(e) for e in missing[:20])
            tail = (f", ... (+{len(missing) - 20} more)"
                    if len(missing) > 20 else "")
            adapter._lazy_fetch_log.append(
                f"[{job.name}] Skipped {len(missing)} element(s) with no "
                f"Element1dForce data in {job.combo!r} (likely non-beam "
                f"types or excluded from analysis): {preview}{tail}"
            )
            missing_set = set(missing)
            elements = [e for e in elements if e not in missing_set]
            if not elements:
                raise RuntimeError(
                    f"Job {job.name!r}: every element in the target list "
                    f"has no Element1dForce data in combo {job.combo!r}. "
                    f"Check that the saved list resolves to beam elements "
                    f"and that the analysis covers this combination."
                )

    # Build the list of targets. Each target produces its own table block.
    # Per-element targets keep the int element ID; summed targets use a
    # human-readable label ("sum(...)") so the Element column makes sense.
    rows: list[dict] = []
    force_order = APP_FORCE_ORDER

    if sum_across:
        # Sum mode: merge forces across elements into one synthetic target.
        targets: list[tuple[list[int], Any]] = [
            (elements, _format_group_label(job.location, elements))
        ]
        n_targets = len(targets)
        for ti, (target_elements, target_label) in enumerate(targets):
            def _target_progress(pi: int, n_perms: int) -> None:
                if progress_cb is not None:
                    progress_cb(ti, n_targets, pi, n_perms)
            candidates = _candidates_for_target(
                adapter, target_elements, job,
                gsa_force_unit, gsa_moment_unit, output_units, signs,
                position, use_max_position, sum_across,
                progress_cb=_target_progress,
            )
            for rule in job.envelopes:
                picked = envelope(candidates, rule.action, rule.on, rule.top_n)
                for rank, rec in enumerate(picked, start=1):
                    note = envelope_note(rule.action, rule.on, rank, rule.top_n)
                    if use_max_position:
                        note += " @ x/L=" + f"{rec['_position']:.2f}"
                    row = {
                        "Job": job.name,
                        "Note": note,
                        "Element": target_label,
                        "Position": rec["_position"],
                        "Combo": job.combo,
                        "Permutation": rec["perm_id"],
                    }
                    for f in force_order:
                        row[f] = rec.get(f, "")
                    rows.append(row)
    else:
        # Global envelope: pool candidates from all elements so the
        # envelope picks the governing element across the whole group.
        all_candidates: list[dict] = []
        n_elems = len(elements)
        for ei, e in enumerate(elements):
            # Lightweight progress: update GUI every ~200 elements
            # so the app doesn't appear frozen during candidate building.
            if progress_cb is not None and ei % 200 == 0:
                progress_cb(ei, n_elems, 0, 1)
            cands = _candidates_for_target(
                adapter, [e], job,
                gsa_force_unit, gsa_moment_unit, output_units, signs,
                position, use_max_position, False,
            )
            for c in cands:
                c["_element"] = e
            all_candidates.extend(cands)
        for rule in job.envelopes:
            picked = envelope(all_candidates, rule.action, rule.on, rule.top_n)
            for rank, rec in enumerate(picked, start=1):
                note = envelope_note(rule.action, rule.on, rank, rule.top_n)
                if use_max_position:
                    note += " @ x/L=" + f"{rec['_position']:.2f}"
                row = {
                    "Job": job.name,
                    "Note": note,
                    "Element": rec["_element"],
                    "Position": rec["_position"],
                    "Combo": job.combo,
                    "Permutation": rec["perm_id"],
                }
                for f in force_order:
                    row[f] = rec.get(f, "")
                rows.append(row)
    return rows


def _run_reaction_job(
    adapter: Any, job: JobCfg,
    gsa_force_unit: str, gsa_moment_unit: str,
    output_units: UnitsCfg, signs: SignsCfg,
    progress_cb: Optional[Callable[[int, int, int, int], None]] = None,
) -> list[dict]:
    """Run a node-reaction extraction job."""
    if not hasattr(adapter, "node_reactions"):
        raise RuntimeError(
            f"Job {job.name!r}: node reactions require the GsaAPI backend. "
            f"The current adapter ({type(adapter).__name__}) does not support "
            f"node reactions."
        )

    nodes = resolve_target_nodes(job.location)
    if not nodes:
        raise RuntimeError(f"Job {job.name!r}: no nodes resolved from location.")

    if hasattr(adapter, "prefetch_reactions"):
        adapter.prefetch_reactions(job.combo, nodes)

    sum_across = bool(job.location.get("sum_across_nodes", False))

    if sum_across:
        targets: list[tuple[list[int], Any]] = [
            (nodes, _format_node_label(job.location, nodes))
        ]
    else:
        targets = [([n], n) for n in nodes]

    rows: list[dict] = []
    n_targets = len(targets)
    for ti, (target_nodes, target_label) in enumerate(targets):
        def _target_progress(pi: int, n_perms: int) -> None:
            if progress_cb is not None:
                progress_cb(ti, n_targets, pi, n_perms)
        candidates = _candidates_for_reaction_target(
            adapter, target_nodes, job,
            gsa_force_unit, gsa_moment_unit, output_units, signs,
            sum_across,
            progress_cb=_target_progress,
        )
        for rule in job.envelopes:
            picked = envelope(candidates, rule.action, rule.on, rule.top_n)
            for rank, rec in enumerate(picked, start=1):
                note = envelope_note(rule.action, rule.on, rank, rule.top_n)
                row = {
                    "Job": job.name,
                    "Note": note,
                    "Element": target_label,
                    "Position": 0.0,
                    "Combo": job.combo,
                    "Permutation": rec["perm_id"],
                }
                for f in APP_REACTION_ORDER:
                    row[f] = rec.get(f, "")
                rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_table(rows: list[dict], columns: list[str]) -> str:
    """Pretty-print a table without external deps. Numeric values are
    right-aligned with 2 decimals; everything else is left-aligned."""
    if not rows:
        return "(no rows)"

    def fmt_cell(v: Any) -> str:
        if v == "" or v is None:
            return ""
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)

    table = [[fmt_cell(r.get(c, "")) for c in columns] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in table)) for i, c in enumerate(columns)]

    def line(cells: list[str]) -> str:
        return "| " + " | ".join(
            cell.rjust(widths[i]) if _is_numericish(cell) else cell.ljust(widths[i])
            for i, cell in enumerate(cells)
        ) + " |"

    sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    out = [line(columns), sep]
    out.extend(line(row) for row in table)
    return "\n".join(out)


def _is_numericish(s: str) -> bool:
    if not s:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def write_csv(rows: list[dict], columns: list[str], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


def write_tsv(rows: list[dict], columns: list[str], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore", delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


def unified_columns(jobs: list[JobCfg]) -> list[str]:
    """Build the column list: meta columns + force/reaction columns (only those
    that any job actually outputs)."""
    used: set[str] = set()
    for j in jobs:
        used.update(j.forces_to_output)
    forces = [f for f in APP_FORCE_ORDER if f in used]
    reactions = [f for f in APP_REACTION_ORDER if f in used]
    return META_COLUMNS + forces + reactions


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_gsa_units(adapter: GsaAdapter) -> tuple[str, str]:
    """Auto-detect GSA model units; fall back to kN / kN.m if detection fails."""
    detected = adapter.discover_units()
    if detected is not None:
        return detected
    import warnings
    warnings.warn(
        f"Could not auto-detect GSA units; assuming "
        f"{DEFAULT_GSA_FORCE} / {DEFAULT_GSA_MOMENT}. "
        f"Verify a known value by hand before trusting the output.",
        stacklevel=2,
    )
    return (DEFAULT_GSA_FORCE, DEFAULT_GSA_MOMENT)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Extract enveloped element forces from an Oasys GSA model "
                    "(via gsapy) and emit a paste-friendly demand table."
    )
    p.add_argument("config", help="Path to JSON or YAML config file.")
    p.add_argument("--no-open", action="store_true",
                   help="Do not open the GSA file (useful with --dry-run-config).")
    p.add_argument("--dry-run-config", action="store_true",
                   help="Parse and validate the config, then exit.")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    if args.dry_run_config:
        print(f"Config OK: {len(cfg.jobs)} job(s).")
        return 0

    adapter = open_gsa_model(cfg.gsa_file)
    backend = type(adapter).__name__
    print(f"Backend: {backend}")

    # Auto-detect the GSA model's display units.
    gsa_f, gsa_m = _resolve_gsa_units(adapter)
    print(f"GSA model units: force={gsa_f}, moment={gsa_m}")
    print(f"Output units: force={cfg.units.output_force}, moment={cfg.units.output_moment}")

    columns = unified_columns(cfg.jobs)
    all_rows: list[dict] = []
    for job in cfg.jobs:
        rows = run_job(adapter, job, gsa_f, gsa_m, cfg.units, cfg.signs)
        if rows:
            print(f"\n=== {job.name} (combo {job.combo}) ===")
            print(format_table(rows, columns))
        all_rows.extend(rows)

    if cfg.output_csv:
        write_csv(all_rows, columns, cfg.output_csv)
        print(f"\nWrote {cfg.output_csv} ({len(all_rows)} rows).")
    if cfg.output_tsv:
        write_tsv(all_rows, columns, cfg.output_tsv)
        print(f"Wrote {cfg.output_tsv} ({len(all_rows)} rows).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
