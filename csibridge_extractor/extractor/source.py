"""Result-source interface and a fixture-replaying fake used by tests."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

from .targets import ModelLists

TABLE_COLUMNS = {
    "frame": ["Frame", "Station", "OutputCase", "CaseType", "StepType", "P", "V2", "V3", "T",
              "M2", "M3", "FrameElem", "ElemStation"],
    "joint": ["Joint", "OutputCase", "CaseType", "StepType", "F1", "F2", "F3", "M1", "M2", "M3"],
}
# index of the OutputCase column per table
_CASE_COL = {"frame": 2, "joint": 1}
MODES = ("envelope", "correspondence")


class SourceError(Exception):
    """A results source could not provide the requested rows."""


@dataclass
class ModelInfo:
    file: str
    version: str
    units: dict
    analysed: bool


@dataclass
class CaseInfo:
    name: str
    kind: str  # "case" | "combo"
    type: str
    has_results: bool


class ResultSource(Protocol):
    # max objects per iter_rows call (None = all objects in one call)
    batch_objects: int | None

    def model_info(self) -> ModelInfo: ...
    def list_cases(self) -> list[CaseInfo]: ...
    def model_lists(self) -> ModelLists: ...
    def units_row(self, table: str) -> list[str]: ...
    def iter_rows(self, table: str, mode: str, cases: list[str], objects: list[str]) -> Iterator[tuple]: ...
    def notes(self) -> list[str]: ...
    def close(self) -> None: ...


class FakeSource:
    """Replays a JSON fixture; rows are returned exactly as stored, in fixture order."""

    def __init__(self, fixture_path, batch_objects: int | None = None):
        self.batch_objects = batch_objects
        with open(Path(fixture_path), encoding="utf-8") as fh:
            self._d = json.load(fh)
        self.closed = False

    def model_info(self) -> ModelInfo:
        m = self._d["model"]
        return ModelInfo(m["file"], m["version"], dict(m["units"]), bool(m["analysed"]))

    def list_cases(self) -> list[CaseInfo]:
        return [CaseInfo(c["name"], c["kind"], c["type"], bool(c["has_results"])) for c in self._d["cases"]]

    def model_lists(self) -> ModelLists:
        l = self._d["lists"]
        return ModelLists(
            frames=set(l["frames"]), joints=set(l["joints"]),
            groups={g: (set(v["frames"]), set(v["joints"])) for g, v in l["groups"].items()})

    def units_row(self, table: str) -> list[str]:
        return list(self._d["units_rows"][table])

    def iter_rows(self, table: str, mode: str, cases: list[str], objects: list[str]) -> Iterator[tuple]:
        if table not in TABLE_COLUMNS:
            raise SourceError(f"unknown table {table!r}")
        if mode not in MODES:
            raise SourceError(f"unknown mode {mode!r}")
        case_set, obj_set = set(cases), set(objects)
        ci = _CASE_COL[table]
        for row in self._d["tables"][table][mode]:
            if row[ci] in case_set and row[0] in obj_set:
                yield tuple(row)

    def notes(self) -> list[str]:
        return list(self._d.get("notes", []))

    def close(self) -> None:
        self.closed = True
