"""Real CSiBridge v27.1 results source.

Route decision (probe 2026-10-23 on "Structure A_v2.1", CSiBridge 27.1.0; probe_out/probe_result_20261023_144738.json,
probe_out_joints/, probe_out_frames/): DatabaseTables.GetTableForDisplayArray. It returns the Show Tables rows
(OutputCase, CaseType, StepType, CSiBridge rounding). The direct Results.FrameForce / JointReact route gave
different joint maxima for joint 5073, so it is not used.
Table output option "Combo": 1 = envelope (Max/Min), 3 = correspondence (Max P, Min M3, ...). On "Structure A_v2.1"
joint reactions came back as Max/Min for every Combo value, but other models return joint reaction and displacement
correspondence (user, 2026-10-27), so it is requested and a note is added when only Max/Min rows come back.
Speed: ~0.5 s filtered by a group, 8-40+ s unfiltered (whole model), so the smallest existing group that contains
every requested object is used as the filter. The model is never modified (no temporary groups: editing a locked,
analysed model would delete its results).
"""
from __future__ import annotations

import csv
import subprocess
from types import SimpleNamespace
from typing import Iterator

from .source import MODES, TABLE_COLUMNS, CaseInfo, ModelInfo, SourceError
from .targets import ModelLists

TABLE_KEYS = {"frame": "Element Forces - Frames", "joint": "Joint Reactions", "disp": "Joint Displacements"}
COMBO_OPTION = {"envelope": 1, "correspondence": 3}
NUMERIC = {"frame": {"Station", "P", "V2", "V3", "T", "M2", "M3", "ElemStation"},
           "joint": {"F1", "F2", "F3", "M1", "M2", "M3"},
           "disp": {"U1", "U2", "U3", "R1", "R2", "R3"}}
CASE_FINISHED = 4  # Analyze.GetCaseStatus value of an analysed case (probe: analysed cases = 4)
COMBO_TYPES = {0: "Linear Add", 1: "Envelope", 2: "Absolute Add", 3: "SRSS", 4: "Range Add"}
OBJ_POINT, OBJ_FRAME = 1, 2  # GroupDef.GetAssignments ObjectType (probe: joint 5073 -> 1, frame 5417 -> 2)


class CsiConnectError(RuntimeError):
    """Attaching to CSiBridge failed; the message is meant for the user."""


def connect_message(kind: str, detail: str = "") -> str:
    msgs = {
        "no_pythonnet": "pythonnet is not installed: run run.bat (it installs requirements.txt).",
        "no_dll": "CSiAPIv1.dll not found: is CSiBridge 27 installed under C:\\Program Files\\Computers and Structures?",
        "not_running": "CSiBridge is not running, or it runs 'as administrator' while this tool does not "
                       "(start both the same way).",
        "no_model": "CSiBridge is running but no model is open.",
        "not_analysed": "The model has no analysis results: run the analysis in CSiBridge first.",
    }
    m = msgs.get(kind, kind)
    return f"{m} ({detail})" if detail else m


def list_instances() -> list[dict]:
    """Running CSiBridge windows: [{pid, model}] (model = the part of the window title after ' - ')."""
    try:
        out = subprocess.run(["tasklist", "/V", "/FI", "IMAGENAME eq CSiBridge.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return []
    found = []
    for row in csv.reader(out.splitlines()):
        if len(row) >= 9 and row[0].lower() == "csibridge.exe":
            title = row[-1]
            found.append({"pid": int(row[1]),
                          "model": title.split(" - ", 1)[1].strip() if " - " in title else title})
    return found


def count_instances() -> int:
    return len(list_instances())


def _l(v) -> list:
    if v is None:
        return []
    try:
        return [x for x in v]
    except TypeError:
        return [v]


class _NetApi:
    """The OAPI calls the source needs, via the probe's reflection-backed caller (proven on v27.1)."""

    def __init__(self, dll_path: str | None = None, pid: int | None = None):
        from csibridge_extractor.probe import probe_csibridge as pc
        try:
            import clr  # noqa: F401
        except Exception as exc:
            raise CsiConnectError(connect_message("no_pythonnet", str(exc))) from exc
        if not pc.find_dlls(dll_path):
            raise CsiConnectError(connect_message("no_dll"))
        rec: dict = {}
        net, _sap, model = pc.attach(SimpleNamespace(dll=dll_path, pid=pid), rec)
        if model is None:
            errs = [a.get("error") for a in rec.get("attach", {}).get("attempts", [])
                    if a.get("error") and a.get("step", "").startswith("cHelper")]
            raise CsiConnectError(connect_message("not_running", errs[0] if errs else ""))
        self._net, self._m = net, model
        self._o = {k: getattr(model, k) for k in
                   ("DatabaseTables", "LoadCases", "RespCombo", "GroupDef", "FrameObj", "PointObj", "Analyze")}

    def _c(self, label, name, *args):
        obj = self._m if label == "SapModel" else self._o[label]
        return self._net.call_rc(obj, label, name, *args)

    def model_file(self) -> str:
        return str(self._net.call(self._m, "SapModel", "GetModelFilename", True)["__ret__"] or "")

    def version(self) -> str:
        return str(self._c("SapModel", "GetVersion").get("Version") or "")

    def present_units(self) -> str:
        return str(self._net.call(self._m, "SapModel", "GetPresentUnits")["__ret__"])

    def case_names(self) -> list:
        return [str(x) for x in _l(self._c("LoadCases", "GetNameList").get("MyName"))]

    def case_status(self) -> dict:
        r = self._c("Analyze", "GetCaseStatus")
        return {str(n): int(s) for n, s in zip(_l(r.get("CaseName")), _l(r.get("Status")))}

    def case_type(self, name) -> str:
        return str(self._c("LoadCases", "GetTypeOAPI", name).get("CaseType"))

    def combo_names(self) -> list:
        return [str(x) for x in _l(self._c("RespCombo", "GetNameList").get("MyName"))]

    def combo_type(self, name) -> int:
        return int(self._c("RespCombo", "GetTypeOAPI", name).get("ComboType"))

    def combo_items(self, name) -> list:
        return [str(x) for x in _l(self._c("RespCombo", "GetCaseList", name).get("CName"))]

    def group_names(self) -> list:
        return [str(x) for x in _l(self._c("GroupDef", "GetNameList").get("MyName"))]

    def group_items(self, name) -> list:
        r = self._c("GroupDef", "GetAssignments", name)
        return [(int(t), str(n)) for t, n in zip(_l(r.get("ObjectType")), _l(r.get("ObjectName")))]

    def frame_names(self) -> list:
        return [str(x) for x in _l(self._c("FrameObj", "GetNameList").get("MyName"))]

    def joint_names(self) -> list:
        return [str(x) for x in _l(self._c("PointObj", "GetNameList").get("MyName"))]

    def table_units(self, key) -> dict:
        r = self._c("DatabaseTables", "GetAllFieldsInTable", key)
        return {str(k): str(u) for k, u in zip(_l(r.get("FieldKey")), _l(r.get("UnitsString")))}

    def get_options(self) -> list:
        r = self._c("DatabaseTables", "GetTableOutputOptionsForDisplay")
        return [(k, v) for k, v in r.items() if k != "__ret__"]

    def set_options(self, values: list) -> None:
        self._c("DatabaseTables", "SetTableOutputOptionsForDisplay", *values)

    def get_selection(self) -> tuple:
        cs = self._c("DatabaseTables", "GetLoadCasesSelectedForDisplay").get("LoadCaseList")
        cb = self._c("DatabaseTables", "GetLoadCombinationsSelectedForDisplay").get("LoadCombinationList")
        return [str(x) for x in _l(cs)], [str(x) for x in _l(cb)]

    def set_selection(self, cases: list, combos: list) -> None:
        self._c("DatabaseTables", "SetLoadCasesSelectedForDisplay", list(cases))
        self._c("DatabaseTables", "SetLoadCombinationsSelectedForDisplay", list(combos))

    def table(self, key, group) -> tuple:
        r = self._c("DatabaseTables", "GetTableForDisplayArray", key, [], group)
        return [str(x) for x in _l(r.get("FieldsKeysIncluded"))], [x for x in _l(r.get("TableData"))]


class CsiSource:
    batch_objects = None  # one table fetch per (table, mode)

    def __init__(self, dll_path: str | None = None, pid: int | None = None, api=None):
        self._api = api if api is not None else _NetApi(dll_path, pid)
        self._notes: list = []
        self._cases = None
        self._lists = None
        self._units = {}
        self._pending = None  # (options, selection) snapshot while a fetch has changed them
        self.closed = False
        self._file = self._api.model_file()
        if not self._file:
            raise CsiConnectError(connect_message("no_model"))
        self._version = self._api.version()
        if not self._version.startswith("27.1"):
            self._notes.append(f"CSiBridge version {self._version}: this tool was verified on 27.1")
        if api is None and pid is None and count_instances() > 1:
            self._notes.append(f"Several CSiBridge windows are open; connected to {self._file}. "
                               "Pick the model in the list next to Connect to choose another.")

    # -- metadata --------------------------------------------------------------------------
    def model_info(self) -> ModelInfo:
        status = self._status()
        units = {"present": self._api.present_units()}
        fu = self._table_units("frame")
        units.update(force=fu.get("P", ""), length=fu.get("Station", ""))
        return ModelInfo(self._file, self._version, units, any(s == CASE_FINISHED for s in status.values()))

    def _status(self) -> dict:
        if not hasattr(self, "_st"):
            self._st = self._api.case_status()
        return self._st

    def list_cases(self) -> list[CaseInfo]:
        if self._cases is None:
            st = self._status()
            cases = [CaseInfo(n, "case", self._api.case_type(n), st.get(n) == CASE_FINISHED)
                     for n in self._api.case_names()]
            combo_names = self._api.combo_names()
            items = {n: self._api.combo_items(n) for n in combo_names}
            done = {c.name: c.has_results for c in cases}

            def ok(name, seen=()):
                if name in done:
                    return done[name]
                if name not in items or name in seen:
                    return False
                return bool(items[name]) and all(ok(x, seen + (name,)) for x in items[name])

            combos = []
            for n in combo_names:
                t = self._api.combo_type(n)
                combos.append(CaseInfo(n, "combo", COMBO_TYPES.get(t, str(t)), ok(n)))
            self._cases = cases + combos
        return list(self._cases)

    def model_lists(self) -> ModelLists:
        if self._lists is None:
            groups = {}
            for g in self._api.group_names():
                items = self._api.group_items(g)
                groups[g] = ({n for t, n in items if t == OBJ_FRAME}, {n for t, n in items if t == OBJ_POINT})
            self._lists = ModelLists(frames=set(self._api.frame_names()), joints=set(self._api.joint_names()),
                                     groups=groups)
        return self._lists

    def _table_units(self, table) -> dict:
        if table not in self._units:
            self._units[table] = self._api.table_units(TABLE_KEYS[table])
        return self._units[table]

    def units_row(self, table: str) -> list[str]:
        u = self._table_units(table)
        return [u.get(c, "") for c in TABLE_COLUMNS[table]]

    # -- rows ------------------------------------------------------------------------------
    def _group_for(self, table, objects) -> str | None:
        want = set(objects)
        best = None
        for g, (fr, jt) in self.model_lists().groups.items():
            members = fr if table == "frame" else jt
            if want <= members and (best is None or len(members) < best[1]):
                best = (g, len(members))
        return best[0] if best else None

    def iter_rows(self, table: str, mode: str, cases: list[str], objects: list[str]) -> Iterator[tuple]:
        if table not in TABLE_COLUMNS:
            raise SourceError(f"unknown table {table!r}")
        if mode not in MODES:
            raise SourceError(f"unknown mode {mode!r}")
        if not objects or not cases:
            return
        group = self._group_for(table, objects)
        lists = self.model_lists()
        total = len(lists.frames if table == "frame" else lists.joints)
        members = lists.groups[group][0 if table == "frame" else 1] if group else ()
        whole = group is None or len(members) >= total
        if whole:
            group = group or "All"
            self._notes.append(f"{table}s: no existing group contains all requested objects, so the whole "
                               "table was read one case at a time (slow on big models). A CSiBridge group "
                               "with them makes it fast.")
        kinds = {c.name: c.kind for c in self.list_cases()}
        # Whole-model reads go one case at a time so CSiBridge never builds the full table at once.
        chunks = [[c] for c in cases] if whole else [list(cases)]
        env_only = set()
        for chunk in chunks:
            for row in self._rows(table, objects, *self._fetch(
                    table, mode, [c for c in chunk if kinds.get(c) == "case"],
                    [c for c in chunk if kinds.get(c) == "combo"], group)):
                if mode == "correspondence" and table != "frame" and row[3] in ("Max", "Min"):
                    env_only.add(row[1])
                yield row
        if env_only:
            what = "joint reactions" if table == "joint" else "joint displacements"
            self._notes.append(f"{what}, Correspondence: CSiBridge returned envelope (Max/Min) rows for "
                               + ", ".join(sorted(env_only)) + "; those rows are envelope values, not "
                               "corresponding sets.")

    def _rows(self, table, objects, fields, data):
        w = len(fields)
        if not w:
            return
        idx = [fields.index(c) if c in fields else None for c in TABLE_COLUMNS[table]]
        num = NUMERIC[table]
        want = set(objects)
        for i in range(0, len(data) - w + 1, w):
            raw = data[i:i + w]
            if idx[0] is None or str(raw[idx[0]]) not in want:
                continue
            row = []
            for col, j in zip(TABLE_COLUMNS[table], idx):
                v = None if j is None else str(raw[j])
                if v is not None and col in num:
                    try:
                        v = float(v)
                    except ValueError:
                        pass
                row.append(v)
            yield tuple(row)

    def _fetch(self, table, mode, case_list, combo_list, group):
        api = self._api
        try:
            opts = api.get_options()
            sel = api.get_selection()
        except Exception as exc:
            raise SourceError(f"could not read the table display options: {exc}") from exc
        self._pending = (opts, sel)
        try:
            names = [k for k, _ in opts]
            if "Combo" not in names:
                raise SourceError("table output option 'Combo' not found")
            values = [COMBO_OPTION[mode] if k == "Combo" else v for k, v in opts]
            api.set_selection(case_list, combo_list)
            api.set_options(values)
            return api.table(TABLE_KEYS[table], group)
        except SourceError:
            raise
        except Exception as exc:
            raise SourceError(f"{TABLE_KEYS[table]}: {exc}") from exc
        finally:
            self._restore()

    def _restore(self):
        if self._pending is None:
            return
        opts, sel = self._pending
        errors = []
        try:
            self._api.set_options([v for _, v in opts])
        except Exception as exc:
            errors.append(f"table options: {exc}")
        try:
            self._api.set_selection(*sel)
        except Exception as exc:
            errors.append(f"case selection: {exc}")
        self._pending = None
        if errors:
            self._notes.append("Could not restore CSiBridge display settings (" + "; ".join(errors) +
                               "). Results are unaffected; check Display > Show Tables options.")

    def notes(self) -> list[str]:
        return list(dict.fromkeys(self._notes))

    def close(self) -> None:
        if self.closed:
            return
        self._restore()
        self.closed = True
