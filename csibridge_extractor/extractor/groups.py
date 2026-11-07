"""Create a joint group, or add / replace / remove the joints of one: the only model edits this tool makes.

Write calls used: GroupDef.SetGroup (new names only), PointObj.SetGroupAssign (joints only), and GroupDef.Delete
(only to roll back a group this module just created). Edits are limited to groups that hold nothing but joints
(never "ALL" or groups holding frames, areas or other objects, e.g. bridge-generated ones). No other object,
bridge object or bridge-wizard data is changed; the model is never unlocked and never saved.
"""
from __future__ import annotations

from dataclasses import dataclass, field

OBJ_POINT = 1  # GroupDef.GetAssignments ObjectType of a joint (same as csi_source.OBJ_POINT)
MAX_JOINTS = 100_000
ACTIONS = ("create", "add", "replace", "remove")


class GroupError(RuntimeError):
    """The group was not changed; the message is meant for the user."""


@dataclass
class GroupResult:
    name: str
    action: str = "create"
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)   # requested labels that are not joints of the model
    skipped: list[str] = field(default_factory=list)   # already in the group (add) / not in it (remove)
    joints: list[str] = field(default_factory=list)    # group joints after the edit
    notes: list[str] = field(default_factory=list)


def joint_range(start, end, step) -> list[str]:
    """Joint labels start, start+step, ... <= end (e.g. 1, 10, 2 -> 1, 3, 5, 7, 9)."""
    try:
        a, b, s = int(start), int(end), int(step)
    except (TypeError, ValueError):
        raise GroupError("start, end and increment must be whole numbers") from None
    if a < 0 or b < 0:
        raise GroupError("start and end must not be negative")
    if s < 1:
        raise GroupError("increment must be 1 or more")
    if a > b:
        raise GroupError("start must not be greater than end")
    if (b - a) // s + 1 > MAX_JOINTS:
        raise GroupError(f"more than {MAX_JOINTS} joints in the range: narrow it or raise the increment")
    return [str(n) for n in range(a, b + 1, s)]


def _sort_key(s: str):
    return (0, int(s), s) if s.isascii() and s.isdigit() else (1, 0, s)


def _find(api, name: str) -> str | None:
    return next((g for g in api.group_names() if g.casefold() == name.casefold()), None)


def plan(action: str, current: set[str], joints: list[str], in_model: set[str]) -> GroupResult:
    """What an edit would do (no model access): fills added / removed / missing / skipped / joints."""
    if action not in ACTIONS:
        raise GroupError(f"unknown action {action!r}")
    current = {c for c in current if c.strip()}  # CSiBridge can report members with blank names: never touched
    res = GroupResult("", action, missing=[j for j in joints if j not in in_model])
    want = [j for j in dict.fromkeys(joints) if j in in_model]
    if action in ("create", "add"):
        res.added = [j for j in want if j not in current]
        res.skipped = [j for j in want if j in current]
        after = current | set(want)
    elif action == "remove":
        res.removed = sorted(current & set(want), key=_sort_key)
        res.skipped = [j for j in want if j not in current]
        after = current - set(want)
    else:
        res.added = [j for j in want if j not in current]
        res.removed = sorted(current - set(want), key=_sort_key)
        after = set(want)
    res.joints = sorted(after, key=_sort_key)
    return res


def editable(api, name: str) -> str:
    """The model's spelling of group ``name``; GroupError unless it exists and holds only joints."""
    g = _find(api, name)
    if g is None:
        raise GroupError(f"group '{name}' does not exist")
    if g.casefold() == "all":
        raise GroupError("the built-in group ALL cannot be edited")
    if any(t != OBJ_POINT for t, _ in api.group_items(g)):
        raise GroupError(f"group '{g}' holds frames, areas or other non-joint objects (e.g. bridge-generated); "
                         "only joint-only groups can be edited by this tool")
    return g


def edit_joint_group(api, action: str, name: str, joints: list[str]) -> GroupResult:
    """``action``: create (new group; ``joints`` may be empty) | add | replace | remove. ``api`` is a
    csi_source._NetApi (or a fake with the same methods)."""
    name = (name or "").strip()
    if not name:
        raise GroupError("enter a group name")
    if action not in ACTIONS:
        raise GroupError(f"unknown action {action!r}")
    if action != "create" and not joints:
        raise GroupError("enter the joint range")
    in_model = set(api.joint_names())
    if action == "create":
        if _find(api, name) is not None:
            raise GroupError(f"group '{name}' already exists: pick a new name, or use Add / Replace / Remove")
        current: set[str] = set()
    else:
        name = editable(api, name)
        members = [n for _, n in api.group_items(name)]
        current = {n for n in members if n.strip()}
    res = plan(action, current, joints, in_model)
    res.name = name
    unnamed = 0 if action == "create" else sum(1 for n in members if not n.strip())
    if unnamed:
        res.notes.append(f"CSiBridge reports {unnamed} member(s) of '{name}' without a name; they cannot be "
                         "addressed through the API and were left as they are")
    if joints and len(res.missing) == len(joints):
        raise GroupError("none of the joints in the range exist in the model: nothing was changed")
    locked, status = api.model_locked(), api.case_status()
    if action == "create":
        try:
            api.create_group(name)
        except Exception as exc:
            raise GroupError(f"CSiBridge refused to create group '{name}' ({exc}); nothing was changed") from exc
    done: list[tuple[str, str]] = []
    j = ""
    try:
        for j in res.removed:
            api.unassign_joint(j, name)
            done.append(("removed", j))
        for j in res.added:
            api.assign_joint(j, name)
            done.append(("added", j))
    except Exception as exc:
        raise GroupError(f"editing '{name}' failed at joint {j!r} ({exc}); " + _undo(api, action, name, done)) from exc
    got = {n for t, n in api.group_items(name) if t == OBJ_POINT and n.strip()}
    if got != set(res.joints):
        res.notes.append(f"CSiBridge reports {len(got)} joints in '{name}', expected {len(res.joints)}")
    if api.case_status() != status or (locked and not api.model_locked()):
        res.notes.append("WARNING: the model's analysis status changed after editing the group (results may "
                         "have been cleared). Close the model without saving if that is not wanted.")
    return res


def _undo(api, action, name, done) -> str:
    try:
        if action == "create":
            api.delete_group(name)
            return "the new group was removed again"
        for what, j in reversed(done):
            (api.assign_joint if what == "removed" else api.unassign_joint)(j, name)
        return "the group was restored to its previous joints"
    except Exception as exc:
        return f"undoing the partial edit also failed ({exc}): check group '{name}' in CSiBridge"


def create_joint_group(api, name: str, joints: list[str]) -> GroupResult:
    return edit_joint_group(api, "create", name, joints)
