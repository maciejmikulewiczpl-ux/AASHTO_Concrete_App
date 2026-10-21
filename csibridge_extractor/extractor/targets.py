"""Label parsing and resolution against the model's frames, joints and groups."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_RANGE = re.compile(r"^([0-9]+)-([0-9]+)$")
_SPLIT = re.compile(r"[,\s]+")


@dataclass(frozen=True)
class RangeToken:
    a: int
    b: int

    def text(self) -> str:
        return f"{self.a}-{self.b}"


@dataclass
class ModelLists:
    frames: set[str] = field(default_factory=set)
    joints: set[str] = field(default_factory=set)
    # group -> (frames, joints)
    groups: dict[str, tuple[set[str], set[str]]] = field(default_factory=dict)


@dataclass
class Resolution:
    frames: list[str] = field(default_factory=list)
    joints: list[str] = field(default_factory=list)
    missing_frames: list[str] = field(default_factory=list)
    missing_joints: list[str] = field(default_factory=list)
    missing_groups: list[str] = field(default_factory=list)
    empty_ranges: list[str] = field(default_factory=list)
    # "group:label" for group members that are not frames/joints of the model (not extracted)
    group_members_not_in_model: list[str] = field(default_factory=list)
    # range-looking tokens that are also literal labels (both interpretations are extracted)
    ambiguous_tokens: list[str] = field(default_factory=list)


def parse_labels(text: str) -> list:
    r"""Split on commas/whitespace; ``\d+-\d+`` with a <= b becomes a RangeToken, else a
    literal str (so ``1227-1`` is a literal label). Order kept, duplicates dropped."""
    out: list = []
    seen: set = set()
    for tok in _SPLIT.split(text or ""):
        if not tok:
            continue
        m = _RANGE.match(tok)
        item = tok
        if m and int(m.group(1)) <= int(m.group(2)):
            item = RangeToken(int(m.group(1)), int(m.group(2)))
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _expand(text: str, existing: set[str], found: list[str], missing: list[str],
            empty_ranges: list[str], ambiguous: list[str]) -> None:
    ints = None  # lazily built: sorted (int, label) pairs of purely numeric labels
    for tok in parse_labels(text):
        if isinstance(tok, RangeToken):
            literal = tok.text() in existing
            if literal:
                found.append(tok.text())
                ambiguous.append(tok.text())
            if ints is None:
                ints = sorted((int(s), s) for s in existing if s.isascii() and s.isdigit())
            lo, hi = tok.a, tok.b
            hits = [s for n, s in ints if lo <= n <= hi]
            if not hits and not literal:
                empty_ranges.append(tok.text())
            found.extend(hits)
        elif tok in existing:
            found.append(tok)
        else:
            missing.append(tok)


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def resolve(frames_text: str, joints_text: str, groups: list[str], model: ModelLists) -> Resolution:
    res = Resolution()
    frames: list[str] = []
    joints: list[str] = []
    empty: list[str] = []
    ambiguous: list[str] = []
    _expand(frames_text, model.frames, frames, res.missing_frames, empty, ambiguous)
    _expand(joints_text, model.joints, joints, res.missing_joints, empty, ambiguous)
    for g in groups:
        if g in model.groups:
            gf, gj = model.groups[g]
            for lab in sorted(gf, key=_sort_key):
                if lab in model.frames:
                    frames.append(lab)
                else:
                    res.group_members_not_in_model.append(f"{g}:{lab}")
            for lab in sorted(gj, key=_sort_key):
                if lab in model.joints:
                    joints.append(lab)
                else:
                    res.group_members_not_in_model.append(f"{g}:{lab}")
        else:
            res.missing_groups.append(g)
    res.frames = _dedupe(frames)
    res.joints = _dedupe(joints)
    res.missing_frames = _dedupe(res.missing_frames)
    res.missing_joints = _dedupe(res.missing_joints)
    res.missing_groups = _dedupe(res.missing_groups)
    res.empty_ranges = _dedupe(empty)
    res.ambiguous_tokens = _dedupe(ambiguous)
    res.group_members_not_in_model = _dedupe(res.group_members_not_in_model)
    return res


def _sort_key(s: str):
    return (0, int(s), s) if s.isascii() and s.isdigit() else (1, 0, s)
