"""Extraction job: save / load / validate (UTF-8 JSON)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path

MODES = ("envelope", "correspondence")
TABLE_KEYS = ("frame", "joint")


def _default_tables() -> dict:
    return {"frame": {"enabled": True, "modes": ["envelope"]},
            "joint": {"enabled": False, "modes": ["envelope"]}}


@dataclass
class Job:
    version: int = 1
    frames: str = ""
    joints: str = ""
    groups: list[str] = field(default_factory=list)
    cases: list[str] = field(default_factory=list)
    tables: dict = field(default_factory=_default_tables)
    output_dir: str | None = None
    name_pattern: str = "{model}_results_{stamp}.xlsx"
    open_when_done: bool = True
    # load-time notes (unknown keys); never saved, ignored in comparisons
    warnings: list[str] = field(default_factory=list, compare=False)


_SAVED = [f.name for f in fields(Job) if f.name != "warnings"]


def save_job(job: Job, path) -> None:
    data = {k: getattr(job, k) for k in _SAVED}
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_job(path) -> Job:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("job file: top level must be an object")
    warnings = [f"unknown key ignored: {k}" for k in raw if k not in _SAVED]
    kw = {k: raw[k] for k in _SAVED if k in raw}
    kw.setdefault("version", 1)
    tables = _default_tables()
    for t, spec in (kw.get("tables") or {}).items():
        if t not in TABLE_KEYS:
            warnings.append(f"unknown key ignored: tables.{t}")
            continue
        modes = list(spec.get("modes", tables[t]["modes"]))
        for m in modes:
            if m not in MODES:
                raise ValueError(f"tables.{t}.modes: invalid mode {m!r} (allowed: {', '.join(MODES)})")
        tables[t] = {"enabled": bool(spec.get("enabled", tables[t]["enabled"])), "modes": modes}
    kw["tables"] = tables
    job = Job(**kw)
    job.warnings = warnings
    return job


def validate(job: Job) -> list[str]:
    errors: list[str] = []
    if not (job.frames.strip() or job.joints.strip() or job.groups):
        errors.append("Nothing to extract: give frames, joints or groups.")
    if not job.cases:
        errors.append("No cases selected.")
    for t in TABLE_KEYS:
        spec = job.tables.get(t, {})
        if spec.get("enabled") and not spec.get("modes"):
            errors.append(f"Table '{t}' is enabled but has no mode selected.")
    return errors
