"""CSiBridge OAPI probe (run once, on the PC where CSiBridge v27.1 is open with an analysed model).

It attaches to the running CSiBridge, reads model metadata and tries two routes for extracting
frame forces and joint reactions (envelope / correspondence):
  (a) the database-tables API (the same tables the "Show Tables" viewer shows);
  (b) the direct result calls (Results.Setup + FrameForce / JointReact).

EVERY API NAME USED HERE IS A CANDIDATE, NOT A VERIFIED FACT for v27.1: each call is wrapped in
try/except and its outcome (or exception text) is recorded in the JSON, together with the list of
methods that .NET reflection reports on each API object. The script never saves the model and never
runs the analysis; every option / selection it changes is snapshotted first and restored in a
`finally` block. It always writes the JSON, even if attaching fails.

Usage (see README.md):
  .venv\\Scripts\\python.exe csibridge_extractor\\probe\\probe_csibridge.py --group PROBE --frames 1227 --joints 5 --case Str-I1 --out probe_out
"""
import argparse
import csv
import datetime as _dt
import glob
import json
import os
import sys
import time
import traceback

PROGIDS = ["CSI.CSiBridge.API.SapObject"]
# Candidate assembly names and the namespaces they might expose (unverified for v27.1).
DLL_NAMES = ["CSiAPIv1.dll", "CSiBridge1.dll"]
DLL_SEARCH_GLOBS = [
    r"C:\Program Files\Computers and Structures\CSiBridge*",
    r"C:\Program Files (x86)\Computers and Structures\CSiBridge*",
    r"C:\Program Files\Computers and Structures\*",
]
# Interface names we look up by reflection to list their methods (candidates).
IFACE_NAMES = {
    "SapModel": "cSapModel",
    "DatabaseTables": "cDatabaseTables",
    "Results": "cAnalysisResults",
    "Results.Setup": "cAnalysisResultsSetup",
    "LoadCases": "cLoadCases",
    "RespCombo": "cCombo",
    "GroupDef": "cGroup",
    "FrameObj": "cFrameObj",
    "PointObj": "cPointObj",
    "Analyze": "cAnalyze",
}
CSV_ROWS = 2000          # filtered rows written to each sample CSV
MAX_SECONDS = 60.0       # huge-fetch guard: skip remaining modes of a table above this
MAX_ROWS = 200000        # ... or above this many rows / NumberRecords
CALL_LOG_CAP = 3000


# --------------------------------------------------------------------------------------------
# Pure helpers (unit-tested without CSiBridge)
# --------------------------------------------------------------------------------------------
class ProbeCallError(Exception):
    """An OAPI call returned a non-zero return code."""

    def __init__(self, name, code):
        super().__init__("%s returned %r" % (name, code))
        self.name = name
        self.code = code


def parse_args(argv):
    p = argparse.ArgumentParser(description="Probe the CSiBridge OAPI (read-only; never saves the model).")
    p.add_argument("--frames", nargs="*", default=[], help="frame labels (space separated)")
    p.add_argument("--joints", nargs="*", default=[], help="joint labels (space separated)")
    p.add_argument("--group", default=None, help="a group name (optional)")
    p.add_argument("--case", action="append", default=[], help="load case or combination name (repeatable)")
    p.add_argument("--out", default="probe_out", help="output folder")
    p.add_argument("--dll", default=None, help="full path to CSiAPIv1.dll (optional)")
    p.add_argument("--pid", type=int, default=None,
                   help="process id of the CSiBridge instance (when several are open)")
    return p.parse_args(argv)


def unpack_out(ret, name="call"):
    """Normalise a pythonnet out-parameter result.

    pythonnet returns ``(return_code, out1, out2, ...)`` for methods with ref/out parameters, or
    the bare return value otherwise. The OAPI return code is 0 on success. Returns the out values
    as a tuple; raises ProbeCallError for a non-zero return code.
    """
    if isinstance(ret, (tuple, list)):
        if not ret:
            return ()
        code, outs = ret[0], tuple(ret[1:])
    else:
        code, outs = ret, ()
    try:
        bad = int(code) != 0
    except (TypeError, ValueError):
        bad = True
    if bad:
        raise ProbeCallError(name, code)
    return outs


def rows_to_csv(path, header, rows):
    path = str(path)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(list(header))
        for r in rows:
            w.writerow(list(r))


def summarise(result):
    L = []
    att = result.get("attach") or {}
    L.append("=== CSiBridge probe summary ===")
    L.append("Attach: %s (%s)" % ("OK" if att.get("success") else "FAILED", att.get("method") or "-"))
    for e in att.get("errors") or []:
        L.append("  attach error: %s" % e)
    L.append("CSiBridge version: %s" % result.get("version"))
    L.append("Model file: %s" % result.get("model_file"))
    L.append("Present units: %s" % result.get("present_units"))
    for w in result.get("warnings") or []:
        L.append("WARNING: %s" % w)
    for route_name, route in (result.get("routes") or {}).items():
        L.append("--- route %s ---" % route_name)
        if not isinstance(route, dict):
            L.append("  %r" % (route,))
            continue
        for f in route.get("fetches") or []:
            L.append("  %-6s %-22s rows=%-6s %6.2fs  StepType=%s%s" % (
                f.get("table"), f.get("mode"), f.get("rows"), float(f.get("seconds") or 0.0),
                ",".join(str(s) for s in (f.get("step_types") or [])) or "-",
                ("  ERROR: %s" % f["error"]) if f.get("error") else ""))
        for e in route.get("errors") or []:
            L.append("  error: %s" % e)
        for e in route.get("skipped") or []:
            L.append("  skipped: %s" % e)
    rest = result.get("restored")
    if rest is not None:
        L.append("Restored: %s" % (rest.get("all_ok") if isinstance(rest, dict) else rest))
    if result.get("fatal"):
        L.append("FATAL: %s" % result["fatal"])
    if result.get("output_dir"):
        L.append("Output folder: %s" % result["output_dir"])
    if result.get("json_path"):
        L.append("JSON: %s" % result["json_path"])
    L.append("NEXT: send me the JSON + CSV folder (the whole output folder), plus the CSiBridge table exports.")
    return "\n".join(L)


def selection_args(param_info, names):
    """Arguments for Set...SelectedForDisplay: (count, list) if the first parameter is an int, else (list,).

    Returns None when the parameter list is unknown (reflection failed): the caller must not guess.
    """
    if not param_info:
        return None
    names = list(names)
    if param_info[0].get("type", "").startswith("Int"):
        return [len(names), names]
    return [names]


def over_cap(seconds, rows, number_records):
    """Reason string if a fetch is too big to repeat for other modes, else None."""
    if seconds is not None and seconds > MAX_SECONDS:
        return "fetch took %.1f s > %.0f seconds" % (seconds, MAX_SECONDS)
    if rows is not None and rows > MAX_ROWS:
        return "%d rows > %d" % (rows, MAX_ROWS)
    try:
        if number_records is not None and int(number_records) > MAX_ROWS:
            return "NumberRecords %s > %d" % (number_records, MAX_ROWS)
    except (TypeError, ValueError):
        pass
    return None


class Tee:
    """Write console output to the real stream and to a file (console.txt)."""

    def __init__(self, stream, path):
        self.stream = stream
        self.fh = open(path, "a", encoding="utf-8")

    def write(self, s):
        try:
            self.stream.write(s)
        except Exception:
            pass
        try:
            self.fh.write(s)
            self.fh.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        for f in (self.stream, self.fh):
            try:
                f.flush()
            except Exception:
                pass

    def close(self):
        try:
            self.fh.close()
        except Exception:
            pass


def say(msg):
    print(msg, flush=True)


def _jsonable(v, depth=0):
    """Convert .NET / odd values to JSON-friendly Python values."""
    if depth > 6:
        return str(v)
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, dict):
        return {str(k): _jsonable(x, depth + 1) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_jsonable(x, depth + 1) for x in v]
    try:  # .NET arrays / IEnumerable (but not strings)
        if hasattr(v, "__iter__") and not hasattr(v, "upper"):
            return [_jsonable(x, depth + 1) for x in list(v)]
    except Exception:
        pass
    try:
        return float(v) if isinstance(v, float) else str(v)
    except Exception:
        return repr(v)


def _err(e):
    return "%s: %s" % (type(e).__name__, e)


# --------------------------------------------------------------------------------------------
# .NET plumbing (only runs on the CSiBridge PC)
# --------------------------------------------------------------------------------------------
class Net:
    """Holds the loaded assembly and performs logged calls with reflection-built placeholders."""

    def __init__(self, result):
        self.result = result
        self.asm = None
        self.ns = None
        self.mode = "pythonnet"  # or "comtypes"
        self.calls = result.setdefault("call_log", [])

    # ---- type helpers
    def iface_type(self, obj, label):
        """System.Type for the API interface behind ``obj`` (tries several ways)."""
        if self.mode != "pythonnet":
            return None
        cands = []
        if self.asm is not None and label in IFACE_NAMES:
            for ns in ([self.ns] if self.ns else []) + ["CSiAPIv1", "CSiBridge1"]:
                try:
                    t = self.asm.GetType("%s.%s" % (ns, IFACE_NAMES[label]))
                    if t is not None:
                        cands.append(t)
                except Exception:
                    pass
        try:
            import clr  # noqa: F401
            cands.append(clr.GetClrType(type(obj)))
        except Exception:
            pass
        try:
            cands.append(obj.GetType())
        except Exception:
            pass
        for t in cands:
            try:
                if t is not None and t.FullName != "System.__ComObject" and len(t.GetMethods()) > 4:
                    return t
            except Exception:
                continue
        return None

    def list_methods(self, obj, label):
        t = self.iface_type(obj, label)
        if t is None:
            return {"type": None, "methods": sorted(n for n in dir(obj) if not n.startswith("_"))}
        out = []
        for m in t.GetMethods():
            try:
                ps = ["%s%s %s" % ("out/ref " if p.ParameterType.IsByRef else "",
                                   p.ParameterType.Name.rstrip("&"), p.Name) for p in m.GetParameters()]
                out.append("%s %s(%s)" % (m.ReturnType.Name, m.Name, ", ".join(ps)))
            except Exception as e:
                out.append("%s(<%s>)" % (m.Name, _err(e)))
        return {"type": str(t.FullName), "methods": sorted(set(out))}

    def method_infos(self, obj, label, name):
        t = self.iface_type(obj, label)
        if t is None:
            return []
        ms = [m for m in t.GetMethods() if m.Name == name]
        ms.sort(key=lambda m: len(m.GetParameters()))
        return ms

    def param_info(self, obj, label, name):
        ms = self.method_infos(obj, label, name)
        if not ms:
            return None
        info = []
        for p in ms[0].GetParameters():
            pt = p.ParameterType
            et = pt.GetElementType() if pt.IsByRef else pt
            d = {"name": str(p.Name), "type": str(et.Name), "byref": bool(pt.IsByRef)}
            try:
                if et.IsEnum:
                    import System
                    names = list(System.Enum.GetNames(et))
                    vals = [int(System.Convert.ToInt32(x)) for x in System.Enum.GetValues(et)]
                    d["enum"] = dict(zip(names, vals))
            except Exception as e:
                d["enum_error"] = _err(e)
            info.append(d)
        return info

    @staticmethod
    def _placeholder(t):
        import System
        if t.IsByRef:
            t = t.GetElementType()
        if t.IsArray:
            return System.Array.CreateInstance(t.GetElementType(), 0)
        if t.IsEnum:
            return System.Enum.ToObject(t, 0)
        n = t.FullName
        if n == "System.String":
            return ""
        if n == "System.Boolean":
            return False
        if n in ("System.Double", "System.Single"):
            return 0.0
        if n in ("System.Int32", "System.Int16", "System.Int64"):
            return 0
        return None

    @staticmethod
    def _convert(v, t):
        import System
        if t.IsByRef:
            t = t.GetElementType()
        if t.IsArray and isinstance(v, (list, tuple)):
            et = t.GetElementType()
            arr = System.Array.CreateInstance(et, len(v))
            for i, x in enumerate(v):
                arr[i] = x
            return arr
        if t.IsEnum and isinstance(v, int) and not isinstance(v, bool):
            return System.Enum.ToObject(t, v)
        return v

    @staticmethod
    def _box_into(objarr, i, v, t):
        """Store v into objarr[i] boxed as the exact .NET type t (via a 1-element typed array + Array.Copy)."""
        import System
        if t.IsByRef:
            t = t.GetElementType()
        if v is None:
            return
        if t.IsArray or t.FullName == "System.String":
            objarr[i] = v
            return
        if t.IsEnum:
            try:
                if not isinstance(v, bool) and isinstance(v, int):
                    v = System.Enum.ToObject(t, v)
            except Exception:
                pass
        try:
            tmp = System.Array.CreateInstance(t, 1)
            tmp[0] = v
            System.Array.Copy(tmp, 0, objarr, i, 1)
        except Exception:
            objarr[i] = v

    def _build(self, mi, args):
        ps = list(mi.GetParameters())
        if len(args) > len(ps):
            raise TypeError("too many args for %s" % mi.Name)
        full = [self._convert(a, p.ParameterType) for a, p in zip(args, ps)]
        for p in ps[len(args):]:
            if getattr(p, "IsOptional", False):
                try:
                    import System
                    dv = p.DefaultValue
                    if dv is not None and not isinstance(dv, type(System.DBNull.Value)) and                             str(type(dv).__name__) != "Missing":
                        full.append(dv)
                        continue
                except Exception:
                    pass
            full.append(self._placeholder(p.ParameterType))
        return ps, full

    def call(self, obj, label, name, *args):
        """Call obj.<name>(args + placeholders). Returns dict {"__ret__": rc, <out param name>: value}.

        Tries the plain pythonnet call first, then MethodInfo.Invoke (reflection). Logs outcome.
        """
        entry = {"call": "%s.%s" % (label, name), "args": _jsonable(list(args))}
        t0 = time.perf_counter()
        errors = []
        try:
            if self.mode == "comtypes":
                raw = getattr(obj, name)(*args)
                entry["via"] = "comtypes"
                if isinstance(raw, (list, tuple)) and raw:
                    raw = (raw[-1],) + tuple(raw[:-1])  # comtypes: return code is usually last
                outs = unpack_out(raw, entry["call"]) if isinstance(raw, (list, tuple)) else ()
                res = {"__ret__": 0 if isinstance(raw, (list, tuple)) else raw}
                for i, v in enumerate(outs):
                    res["out%d" % i] = v
                entry["ok"] = True
                return res
            mis = self.method_infos(obj, label, name)
            if not mis:
                raise AttributeError("no method %s on %s (reflection)" % (name, label))
            for mi in mis:
                try:
                    ps, full = self._build(mi, args)
                except Exception as e:
                    errors.append("build: " + _err(e))
                    continue
                byref = [p for p in ps if p.ParameterType.IsByRef]
                # 1) plain pythonnet call
                try:
                    raw = getattr(obj, name)(*full)
                    if byref:
                        if not isinstance(raw, tuple):
                            raw = (raw,)
                        res = {"__ret__": raw[0]}
                        for p, v in zip(byref, raw[1:]):
                            res[str(p.Name)] = v
                    else:
                        res = {"__ret__": raw}
                    entry["via"] = "pythonnet"
                    entry["ok"] = True
                    return res
                except Exception as e:
                    errors.append("pythonnet: " + _err(e))
                # 2) reflection invoke
                try:
                    import System
                    arr = System.Array.CreateInstance(System.Object, len(full))
                    for i, (v, p) in enumerate(zip(full, ps)):
                        self._box_into(arr, i, v, p.ParameterType)
                    raw = mi.Invoke(obj, arr)
                    res = {"__ret__": raw}
                    for i, p in enumerate(ps):
                        if p.ParameterType.IsByRef:
                            res[str(p.Name)] = arr[i]
                    entry["via"] = "reflection"
                    entry["ok"] = True
                    return res
                except Exception as e:
                    inner = getattr(e, "InnerException", None)
                    errors.append("reflection: " + _err(e) + (" / inner: %s" % inner if inner else ""))
            raise RuntimeError(" | ".join(errors))
        except Exception as e:
            entry["ok"] = False
            entry["error"] = _err(e)
            raise
        finally:
            entry["seconds"] = round(time.perf_counter() - t0, 4)
            if errors and entry.get("ok"):
                entry["earlier_errors"] = errors
            if len(self.calls) < CALL_LOG_CAP:
                self.calls.append(entry)

    def call_rc(self, obj, label, name, *args):
        """call() and require return code 0 (ProbeCallError otherwise)."""
        res = self.call(obj, label, name, *args)
        unpack_out((res["__ret__"],), "%s.%s" % (label, name))
        return res


def _list(v):
    if v is None:
        return []
    try:
        return [x for x in v]
    except TypeError:
        return [v]


def _s(v):
    return None if v is None else str(v)


def _pyval(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    try:
        return float(v)
    except Exception:
        return str(v)


# --------------------------------------------------------------------------------------------
# Attach
# --------------------------------------------------------------------------------------------
def find_dlls(explicit=None):
    found = []
    if explicit:
        found.append(explicit)
    for g in DLL_SEARCH_GLOBS:
        for d in sorted(glob.glob(g), reverse=True):
            for n in DLL_NAMES:
                p = os.path.join(d, n)
                if os.path.isfile(p) and p not in found:
                    found.append(p)
    return found


def attach(args, result):
    """Attach to the running CSiBridge. Returns (net, sap_object, sap_model) or (net, None, None)."""
    att = result["attach"] = {"success": False, "method": None, "progid": None, "dll": None,
                              "attempts": [], "errors": []}
    net = Net(result)
    try:
        dlls = find_dlls(args.dll)
    except Exception as e:
        dlls = [args.dll] if args.dll else []
        att["errors"].append("dll search: " + _err(e))
    att["dll_candidates"] = dlls
    try:
        import clr  # pythonnet
        att["pythonnet"] = getattr(sys.modules.get("pythonnet"), "__version__", "imported")
    except Exception as e:
        clr = None
        att["errors"].append("import clr (pythonnet): " + _err(e))
    if clr is not None:
        for dll in dlls:
            try:
                clr.AddReference(dll)
            except Exception as e:
                att["attempts"].append({"dll": dll, "step": "clr.AddReference", "error": _err(e)})
                try:
                    import System
                    System.Reflection.Assembly.LoadFrom(dll)
                except Exception as e2:
                    att["attempts"].append({"dll": dll, "step": "Assembly.LoadFrom", "error": _err(e2)})
                    continue
            for ns in ("CSiAPIv1", "CSiBridge1"):
                try:
                    mod = __import__(ns)
                    Helper = getattr(mod, "Helper")
                    cHelper = getattr(mod, "cHelper")
                except Exception as e:
                    att["attempts"].append({"dll": dll, "namespace": ns, "step": "import", "error": _err(e)})
                    continue
                for progid in PROGIDS:
                    a = {"dll": dll, "namespace": ns, "progid": progid, "step": "cHelper(Helper()).GetObject"}
                    try:
                        helper = cHelper(Helper())
                        pid = getattr(args, "pid", None)
                        sap = helper.GetObjectProcess(progid, pid) if pid else helper.GetObject(progid)
                        if sap is None:
                            raise RuntimeError("GetObject returned None (is CSiBridge running?)")
                        model = sap.SapModel
                        if model is None:
                            raise RuntimeError("SapObject.SapModel is None")
                        a["ok"] = True
                        att["attempts"].append(a)
                        att.update(success=True, method="pythonnet cHelper.GetObject", progid=progid, dll=dll,
                                   namespace=ns)
                        try:
                            net.asm = clr.GetClrType(Helper).Assembly
                        except Exception as e3:
                            net.asm = None
                            att["errors"].append("assembly lookup (reflection may be limited): " + _err(e3))
                        net.ns = ns
                        try:
                            att["assembly"] = str(net.asm.FullName) if net.asm is not None else None
                        except Exception:
                            pass
                        return net, sap, model
                    except Exception as e:
                        a["error"] = _err(e)
                        att["attempts"].append(a)
    # Fallback: comtypes
    try:
        import comtypes.client as cc
        for progid in PROGIDS:
            a = {"progid": progid, "step": "comtypes.client.GetActiveObject"}
            try:
                sap = cc.GetActiveObject(progid)
                model = sap.SapModel
                a["ok"] = True
                att["attempts"].append(a)
                att.update(success=True, method="comtypes GetActiveObject (limited probing)", progid=progid)
                net.mode = "comtypes"
                return net, sap, model
            except Exception as e:
                a["error"] = _err(e)
                att["attempts"].append(a)
    except Exception as e:
        att["attempts"].append({"step": "import comtypes", "error": _err(e)})
    if not att["errors"] and not att["success"]:
        att["errors"].append("all attach attempts failed (see attempts)")
    return net, None, None


# --------------------------------------------------------------------------------------------
# Metadata
# --------------------------------------------------------------------------------------------
def probe_metadata(net, model, args, result):
    meta_err = result.setdefault("metadata_errors", [])

    def tryit(key, fn):
        try:
            return fn()
        except Exception as e:
            meta_err.append("%s: %s" % (key, _err(e)))
            return None

    # Reflection listing of every API object we touch (REQUIRED evidence for the next task).
    refl = result["reflection"] = {}
    objs = {"SapModel": model}
    for label in ["DatabaseTables", "Results", "LoadCases", "RespCombo", "GroupDef", "FrameObj", "PointObj",
                  "Analyze"]:
        o = tryit("get " + label, lambda label=label: getattr(model, label))
        if o is not None:
            objs[label] = o
    if "Results" in objs:
        o = tryit("get Results.Setup", lambda: objs["Results"].Setup)
        if o is not None:
            objs["Results.Setup"] = o
    for label, o in objs.items():
        refl[label] = tryit("reflect " + label, lambda o=o, label=label: net.list_methods(o, label))

    result["model_file"] = tryit("GetModelFilename", lambda: _s(net.call(model, "SapModel", "GetModelFilename",
                                                                         True)["__ret__"]))
    v = tryit("GetVersion", lambda: net.call_rc(model, "SapModel", "GetVersion"))
    if v:
        result["version"] = _s(v.get("Version", v.get("out0")))
        result["version_number"] = _pyval(v.get("MyVersionNumber", v.get("out1")))
        if result["version"] and not str(result["version"]).startswith("27.1"):
            result.setdefault("warnings", []).append("CSiBridge version %s is not 27.1 (target)" % result["version"])
    pu = tryit("GetPresentUnits", lambda: net.call(model, "SapModel", "GetPresentUnits")["__ret__"])
    result["present_units"] = _s(pu)
    pu2 = tryit("GetPresentUnits_2", lambda: net.call_rc(model, "SapModel", "GetPresentUnits_2"))
    if pu2:
        result["present_units_2"] = {k: _s(x) for k, x in pu2.items() if k != "__ret__"}

    # Cases / combos
    cases = []
    lc = objs.get("LoadCases")
    names = tryit("LoadCases.GetNameList", lambda: _list(net.call_rc(lc, "LoadCases", "GetNameList").get("MyName")))
    status = {}
    an = objs.get("Analyze")
    st = tryit("Analyze.GetCaseStatus", lambda: net.call_rc(an, "Analyze", "GetCaseStatus"))
    if st:
        for n, s in zip(_list(st.get("CaseName")), _list(st.get("Status"))):
            status[str(n)] = _pyval(s)
    for n in names or []:
        d = {"name": str(n), "analysis_status": status.get(str(n))}
        t = tryit("LoadCases.GetTypeOAPI(%s)" % n, lambda n=n: net.call_rc(lc, "LoadCases", "GetTypeOAPI", str(n)))
        if t:
            d["type"] = {k: _s(x) for k, x in t.items() if k != "__ret__"}
        d["has_results"] = (status.get(str(n)) == 4) if str(n) in status else None  # 4 = finished (candidate)
        cases.append(d)
    result["cases"] = cases
    result["case_status_note"] = "has_results assumes Analyze.GetCaseStatus Status 4 = finished (unverified)"
    combos = []
    rc = objs.get("RespCombo")
    cn = tryit("RespCombo.GetNameList", lambda: _list(net.call_rc(rc, "RespCombo", "GetNameList").get("MyName")))
    for n in cn or []:
        d = {"name": str(n), "has_results": None}
        t = tryit("RespCombo.GetTypeOAPI(%s)" % n, lambda n=n: net.call_rc(rc, "RespCombo", "GetTypeOAPI", str(n)))
        if t:
            d["type"] = {k: _s(x) for k, x in t.items() if k != "__ret__"}
        combos.append(d)
    result["combos"] = combos
    case_names = {c["name"] for c in cases}
    combo_names = {c["name"] for c in combos}
    result["requested_cases"] = [{"name": c, "is_case": c in case_names, "is_combo": c in combo_names}
                                 for c in args.case]
    missing = [c for c in args.case if c not in case_names and c not in combo_names]
    if missing:
        result.setdefault("warnings", []).append("cases/combos not found in model: %s" % ", ".join(missing))

    # Groups / objects
    gd = objs.get("GroupDef")
    result["groups"] = tryit("GroupDef.GetNameList",
                             lambda: [str(x) for x in _list(net.call_rc(gd, "GroupDef", "GetNameList").get("MyName"))])
    if args.group:
        ga = tryit("GroupDef.GetAssignments(%s)" % args.group,
                   lambda: net.call_rc(gd, "GroupDef", "GetAssignments", args.group))
        if ga:
            types = [_pyval(x) for x in _list(ga.get("ObjectType"))]
            onames = [str(x) for x in _list(ga.get("ObjectName"))]
            result["group_assignments"] = {
                "group": args.group, "n_items": len(onames),
                "object_type_counts": {str(t): types.count(t) for t in sorted(set(types), key=str)},
                "note": "ObjectType candidates: 1=point, 2=frame (unverified)",
                "first_items": list(zip(types, onames))[:200],
            }
    fo, po = objs.get("FrameObj"), objs.get("PointObj")
    result["n_frames"] = tryit("FrameObj.Count", lambda: _pyval(net.call(fo, "FrameObj", "Count")["__ret__"]))
    result["n_joints"] = tryit("PointObj.Count", lambda: _pyval(net.call(po, "PointObj", "Count")["__ret__"]))
    fl = tryit("FrameObj.GetNameList", lambda: {str(x) for x in _list(net.call_rc(fo, "FrameObj", "GetNameList")
                                                                        .get("MyName"))})
    if fl is not None:
        result["frames_missing"] = [f for f in args.frames if f not in fl]
    pl = tryit("PointObj.GetNameList", lambda: {str(x) for x in _list(net.call_rc(po, "PointObj", "GetNameList")
                                                                        .get("MyName"))})
    if pl is not None:
        result["joints_missing"] = [j for j in args.joints if j not in pl]
    return objs, case_names, combo_names


# --------------------------------------------------------------------------------------------
# Shared row helpers
# --------------------------------------------------------------------------------------------
def _option_values(pinfo, default=(1, 2, 3, 4)):
    """Values to try for an option parameter: enum members if it is an enum, else candidate ints."""
    if pinfo and pinfo.get("enum"):
        return [(k, v) for k, v in pinfo["enum"].items()]
    return [(str(v), v) for v in default]


def _safe(s):
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(s))[:60]




def _restore_rec(result, key):
    return result["restored"].setdefault(key, {"changed": [], "attempted": [], "restored": [], "errors": []})


def _data_outs(r):
    """Out values of a call that are arrays/lists (not the return code, not counts)."""
    return [v for k, v in r.items() if k != "__ret__" and not isinstance(v, (bool, int, float, str))]


# --------------------------------------------------------------------------------------------
# Route (a): database tables
# --------------------------------------------------------------------------------------------
def probe_database_tables(net, objs, args, case_names, combo_names, out_dir, result, save=None):
    route = result["routes"]["database_tables"] = {"fetches": [], "errors": [], "skipped": [], "tables_found": {}}
    restored = _restore_rec(result, "database_tables")
    dt = objs.get("DatabaseTables")
    if dt is None:
        route["errors"].append("SapModel.DatabaseTables not available")
        return
    L = "DatabaseTables"

    def rec(msg, e):
        route["errors"].append("%s: %s" % (msg, _err(e)))

    # GetAvailableTables scans every table for data and hangs on large models; use the known keys.
    say("Route A (database tables): using known table keys ...")
    targets = {"frame": "Element Forces - Frames", "joint": "Joint Reactions"}
    route["tables_found"] = targets
    for tbl, key in targets.items():
        if key is None:
            continue
        try:
            r = net.call_rc(dt, L, "GetAllFieldsInTable", key)
            route.setdefault("fields", {})[tbl] = {
                "table_key": key, "table_version": _pyval(r.get("TableVersion")),
                "field_keys": [str(x) for x in _list(r.get("FieldKey"))],
                "field_names": [str(x) for x in _list(r.get("FieldName"))],
                "units": [str(x) for x in _list(r.get("UnitsString"))],
            }
        except Exception as e:
            rec("GetAllFieldsInTable(%s)" % key, e)

    # Snapshot display selection (raw values kept for restoring)
    sel_raw, sel_snap_ok = {}, {}
    getters = {"cases": ("GetLoadCasesSelectedForDisplay", "SetLoadCasesSelectedForDisplay"),
               "combos": ("GetLoadCombinationsSelectedForDisplay", "SetLoadCombinationsSelectedForDisplay")}
    setter_params = {}
    for kind, (getter, setter) in getters.items():
        try:
            setter_params[kind] = net.param_info(dt, L, setter)
            route.setdefault("selection_setter_params", {})[setter] = setter_params[kind]
        except Exception as e:
            rec("param_info %s" % setter, e)
        try:
            r = net.call_rc(dt, L, getter)
            outs = _data_outs(r)
            sel_raw[kind] = [str(x) for x in _list(outs[0])] if outs else []
            sel_snap_ok[kind] = True
        except Exception as e:
            rec(getter, e)
    route["original_display_selection"] = dict(sel_raw)

    def read_selection():
        out = {}
        for kind, (getter, _setter) in getters.items():
            outs = _data_outs(net.call_rc(dt, L, getter))
            out[kind] = [str(x) for x in _list(outs[0])] if outs else []
        return out

    # Snapshot output options (raw values for restoring, _pyval only for JSON)
    opt_raw, opt_set = None, None
    try:
        route["output_option_params_get"] = net.param_info(dt, L, "GetTableOutputOptionsForDisplay")
        opt_set = net.param_info(dt, L, "SetTableOutputOptionsForDisplay")
        route["output_option_params_set"] = opt_set
        r = net.call_rc(dt, L, "GetTableOutputOptionsForDisplay")
        opt_raw = {k: v for k, v in r.items() if k != "__ret__"}
        route["original_output_options"] = {k: _pyval(v) for k, v in opt_raw.items()}
    except Exception as e:
        rec("GetTableOutputOptionsForDisplay", e)

    def set_options(over):
        if not opt_set or opt_raw is None:
            raise RuntimeError("output options snapshot/parameters unavailable; not changing them")
        lower = {k.lower(): v for k, v in opt_raw.items()}
        raw_list = list(opt_raw.values())
        vals = []
        for i, p in enumerate(opt_set):
            nm = p["name"]
            if nm in over:
                vals.append(over[nm])
            elif nm.lower() in lower:
                vals.append(lower[nm.lower()])
            elif i < len(raw_list):
                vals.append(raw_list[i])
            else:
                raise RuntimeError("no snapshot value for option parameter %s" % nm)
        return net.call_rc(dt, L, "SetTableOutputOptionsForDisplay", *vals)

    combo_param = next((p for p in (opt_set or []) if "combo" in p["name"].lower()), None)
    route["combo_option_param"] = combo_param
    modes = [("default", None)]
    if combo_param and opt_raw is not None:
        modes += [("combo_%s" % k, v) for k, v in _option_values(combo_param)]
    elif combo_param is None:
        route["skipped"].append("no output-option parameter named like 'combo' found: only the default mode fetched")
    else:
        route["skipped"].append("output options snapshot failed: options not changed, only the default mode fetched")
    route["modes_tried"] = [m for m, _ in modes]

    sel_cases = [c for c in args.case if c in case_names]
    sel_combos = [c for c in args.case if c in combo_names]
    selection_ok = False
    try:
        # ---- select only the requested cases/combos for display (only with a complete snapshot)
        if not args.case:
            route["skipped"].append("no --case given: display selection not changed, no table fetched")
        elif not (sel_snap_ok.get("cases") and sel_snap_ok.get("combos")):
            route["skipped"].append("display-selection snapshot failed: selection not changed, no table fetched")
        else:
            a_cases = selection_args(setter_params.get("cases"), sel_cases)
            a_combos = selection_args(setter_params.get("combos"), sel_combos)
            if a_cases is None or a_combos is None:
                route["skipped"].append("selection setter parameters unknown: selection not changed, no table fetched")
            else:
                ok = True
                for kind, a in (("cases", a_cases), ("combos", a_combos)):
                    setter = getters[kind][1]
                    restored["attempted"].append(setter)
                    try:
                        net.call_rc(dt, L, setter, *a)
                        restored["changed"].append(setter)
                    except Exception as e:
                        ok = False
                        rec(setter, e)
                selection_ok = ok
                try:
                    route["selection_after_set"] = read_selection()
                except Exception as e:
                    rec("re-read selection", e)
                if not ok:
                    route["skipped"].append("display selection could not be set: no table fetched "
                                            "(never fetch an unfiltered table)")
        if save:
            save("route A setup")

        # ---- fetches
        if selection_ok:
            for tbl, key in targets.items():
                if key is None:
                    route["skipped"].append("%s table key not found" % tbl)
                    continue
                labels = set(args.frames if tbl == "frame" else args.joints)
                if args.group:
                    group = args.group
                elif labels:
                    group = "All"  # fetched for the selected case(s) only, then filtered client-side
                else:
                    route["skipped"].append("%s table: no --group and no --%s given" %
                                            (tbl, "frames" if tbl == "frame" else "joints"))
                    continue
                cap_reason = None
                for mode, val in modes:
                    f = {"table": tbl, "table_key": key, "mode": mode, "group": group, "rows": None,
                         "rows_total_unfiltered": None, "seconds": None, "step_types": [], "error": None}
                    if cap_reason:
                        f["error"] = "skipped (size guard): %s" % cap_reason
                        route["fetches"].append(f)
                        continue
                    say("Route A: fetching %s table (%s), mode %s, group %s ... this can take a few minutes"
                        % (tbl, key, mode, group))
                    try:
                        if val is not None:
                            if "SetTableOutputOptionsForDisplay" not in restored["attempted"]:
                                restored["attempted"].append("SetTableOutputOptionsForDisplay")
                            set_options({combo_param["name"]: val})
                            if "SetTableOutputOptionsForDisplay" not in restored["changed"]:
                                restored["changed"].append("SetTableOutputOptionsForDisplay")
                        t0 = time.perf_counter()
                        try:
                            try:
                                r = net.call_rc(dt, L, "GetTableForDisplayArray", key, [], group)
                            except Exception as e0:
                                if args.group:
                                    raise
                                f["group_all_error"] = _err(e0)
                                f["group"] = ""  # retry with a blank group name
                                r = net.call_rc(dt, L, "GetTableForDisplayArray", key, [], "")
                            f["call"] = "GetTableForDisplayArray"
                            fields = [str(x) for x in _list(r.get("FieldsKeysIncluded"))]
                            data = [_pyval(x) for x in _list(r.get("TableData"))]
                            f["number_records"] = _pyval(r.get("NumberRecords"))
                            f["table_version"] = _pyval(r.get("TableVersion"))
                            w = len(fields) or 1
                            rows = [data[i:i + w] for i in range(0, len(data), w)]
                        except Exception as e:
                            f["array_error"] = _err(e)
                            r = net.call_rc(dt, L, "GetTableForDisplayCSVString", key, [], group)
                            f["call"] = "GetTableForDisplayCSVString"
                            txt = [v for v in r.values() if isinstance(v, str) and "\n" in v]
                            lines = list(csv.reader((txt[0] if txt else "").splitlines()))
                            fields, rows = (lines[0], lines[1:]) if lines else ([], [])
                        f["seconds"] = round(time.perf_counter() - t0, 3)
                        f["fields"] = fields
                        f["rows_total_unfiltered"] = len(rows)
                        obj_col = "Frame" if tbl == "frame" else "Joint"
                        if labels and obj_col in fields:
                            ci = fields.index(obj_col)
                            rows = [rw for rw in rows if ci < len(rw) and str(rw[ci]) in labels]
                        elif labels:
                            f["filter_note"] = "object column not found; rows not filtered"
                        f["rows"] = len(rows)
                        if "StepType" in fields:
                            si = fields.index("StepType")
                            f["step_types"] = sorted({str(rw[si]) for rw in rows if si < len(rw)})
                        if "OutputCase" in fields:
                            ci = fields.index("OutputCase")
                            f["output_cases"] = sorted({str(rw[ci]) for rw in rows if ci < len(rw)})
                        fn = os.path.join(out_dir, "probe_rows_dbtables_%s_%s.csv" % (tbl, _safe(mode)))
                        rows_to_csv(fn, fields, rows[:CSV_ROWS])
                        f["csv"] = os.path.basename(fn)
                        cap_reason = over_cap(f["seconds"], f["rows_total_unfiltered"], f.get("number_records"))
                        if cap_reason:
                            f["size_guard"] = cap_reason
                            route["skipped"].append("%s table: remaining modes skipped (%s)" % (tbl, cap_reason))
                    except Exception as e:
                        f["error"] = _err(e)
                    route["fetches"].append(f)
                    say("  -> rows=%s seconds=%s %s" % (f["rows"], f["seconds"], f["error"] or ""))
                    if save:
                        save("route A fetch")
    finally:
        say("Route A: restoring display selection and output options ...")
        for kind, (getter, setter) in getters.items():
            if setter not in restored["attempted"]:
                continue
            try:
                net.call_rc(dt, L, setter, *selection_args(setter_params.get(kind), sel_raw.get(kind, [])))
                restored["restored"].append(setter)
            except Exception as e:
                if setter in restored["changed"]:
                    restored["errors"].append("%s: %s" % (setter, _err(e)))
                else:
                    restored.setdefault("notes", []).append("%s (never changed) restore failed: %s"
                                                            % (setter, _err(e)))
        if "SetTableOutputOptionsForDisplay" in restored["attempted"]:
            try:
                set_options({})
                restored["restored"].append("SetTableOutputOptionsForDisplay")
            except Exception as e:
                restored["errors"].append("SetTableOutputOptionsForDisplay: %s" % _err(e))
            try:
                r = net.call_rc(dt, L, "GetTableOutputOptionsForDisplay")
                after = {k: _pyval(v) for k, v in r.items() if k != "__ret__"}
                restored["options_after_restore_equal"] = (after == route.get("original_output_options"))
            except Exception as e:
                restored["errors"].append("verify options: %s" % _err(e))
        if any(s.endswith("SelectedForDisplay") for s in restored["attempted"]):
            try:
                after = read_selection()
                restored["selection_after_restore_equal"] = all(
                    sorted(after.get(k, [])) == sorted(sel_raw.get(k, [])) for k in getters)
            except Exception as e:
                restored["errors"].append("verify selection: %s" % _err(e))


# --------------------------------------------------------------------------------------------
# Route (b): direct result calls
# --------------------------------------------------------------------------------------------
def probe_direct(net, objs, args, case_names, combo_names, out_dir, result, save=None):
    route = result["routes"]["direct"] = {"fetches": [], "errors": [], "skipped": []}
    restored = _restore_rec(result, "direct")
    res, setup = objs.get("Results"), objs.get("Results.Setup")
    if res is None or setup is None:
        route["errors"].append("SapModel.Results / Results.Setup not available")
        return
    S = "Results.Setup"

    def rec(msg, e):
        route["errors"].append("%s: %s" % (msg, _err(e)))

    say("Route B (direct results): reading current output options and selection ...")
    opt_raw = {}
    t = net.iface_type(setup, S)
    getters = sorted({m.Name for m in t.GetMethods() if m.Name.startswith("GetOption")}) if t is not None else \
        ["GetOptionMultiValuedCombo", "GetOptionMultiStepStatic", "GetOptionNLStatic"]
    for g in getters:
        try:
            r = net.call_rc(setup, S, g)
            opt_raw[g] = [v for k, v in r.items() if k != "__ret__"]
        except Exception as e:
            rec(g, e)
    route["original_options"] = {k: [_pyval(x) for x in v] for k, v in opt_raw.items()}
    try:
        route["multivalued_combo_param"] = net.param_info(setup, S, "SetOptionMultiValuedCombo")
    except Exception as e:
        route["multivalued_combo_param"] = None
        rec("param_info SetOptionMultiValuedCombo", e)

    # Snapshot selected-for-output state of every case/combo (no early break)
    sel_snap, snap_errors = {"case": {}, "combo": {}}, 0
    for kind, names, getter in (("case", case_names, "GetCaseSelectedForOutput"),
                                ("combo", combo_names, "GetComboSelectedForOutput")):
        for n in sorted(names):
            try:
                r = net.call_rc(setup, S, getter, n)
                v = [x for k, x in r.items() if k != "__ret__"]
                sel_snap[kind][n] = bool(v[0]) if v else None
                if not v:
                    snap_errors += 1
            except Exception as e:
                snap_errors += 1
                if snap_errors <= 20:
                    rec("%s(%s)" % (getter, n), e)
    sel_complete = snap_errors == 0
    route["selection_snapshot_complete"] = sel_complete
    route["original_selected_for_output"] = {k: sorted(n for n, s in v.items() if s) for k, v in sel_snap.items()}

    orig_mv = opt_raw.get("GetOptionMultiValuedCombo")
    pinfo = (route["multivalued_combo_param"] or [None])[0]
    modes = [("default", None)]
    if orig_mv:
        modes += [("combo_%s" % k, v) for k, v in _option_values(pinfo)]
    else:
        route["skipped"].append("GetOptionMultiValuedCombo snapshot failed: option not changed, default mode only")
    route["modes_tried"] = [m for m, _ in modes]

    ftargets = ([("group", args.group, 2)] if args.group else []) + [("object", f, 0) for f in args.frames]
    jtargets = ([("group", args.group, 2)] if args.group else []) + [("object", j, 0) for j in args.joints]
    route["item_type_note"] = "eItemTypeElm candidates: 0=ObjectElm, 2=GroupElm (unverified)"

    try:
        if not args.case:
            route["skipped"].append("no --case given: output selection not changed, route B not run (nothing fetched)")
            return
        elif not sel_complete:
            route["skipped"].append("selected-for-output snapshot incomplete: selection not changed, route B not run")
            return
        else:
            restored["attempted"].append("selected for output")
            try:
                net.call_rc(setup, S, "DeselectAllCasesAndCombosForOutput")
                restored["changed"].append("selected for output")
            except Exception as e:
                rec("DeselectAllCasesAndCombosForOutput", e)
                route["skipped"].append("could not deselect cases for output: route B not run")
                return
            for c in args.case:
                try:
                    if c in combo_names:
                        net.call_rc(setup, S, "SetComboSelectedForOutput", c, True)
                    else:
                        net.call_rc(setup, S, "SetCaseSelectedForOutput", c, True)
                except Exception as e:
                    rec("select %s" % c, e)
        if save:
            save("route B setup")

        for tbl, method, tlist in (("frame", "FrameForce", ftargets), ("joint", "JointReact", jtargets)):
            if not tlist:
                route["skipped"].append("%s: no targets" % tbl)
                continue
            cap_reason = None
            for mode, val in modes:
                f = {"table": tbl, "mode": mode, "call": method, "rows": 0, "seconds": None, "step_types": [],
                     "error": None, "per_target": []}
                if cap_reason:
                    f["error"] = "skipped (size guard): %s" % cap_reason
                    route["fetches"].append(f)
                    continue
                if val is not None:
                    try:
                        if "SetOptionMultiValuedCombo" not in restored["attempted"]:
                            restored["attempted"].append("SetOptionMultiValuedCombo")
                        net.call_rc(setup, S, "SetOptionMultiValuedCombo", val)
                        if "SetOptionMultiValuedCombo" not in restored["changed"]:
                            restored["changed"].append("SetOptionMultiValuedCombo")
                    except Exception as e:
                        f["error"] = "SetOptionMultiValuedCombo(%r): %s" % (val, _err(e))
                        route["fetches"].append(f)
                        continue
                say("Route B: %s for %d target(s), mode %s ... this can take a few minutes"
                    % (method, len(tlist), mode))
                header, allrows = None, []
                t0 = time.perf_counter()
                for kind, name, item in tlist:
                    pt = {"target": name, "item_type": kind}
                    t1 = time.perf_counter()
                    try:
                        r = net.call_rc(res, "Results", method, name, item)
                        cols = [k for k, v in r.items()
                                if k not in ("__ret__", "NumberResults") and not isinstance(v, (str, int, float))]
                        arrs = [_list(r[k]) for k in cols]
                        rows = [[_pyval(a[i]) if i < len(a) else None for a in arrs]
                                for i in range(max((len(a) for a in arrs), default=0))]
                        header = header or cols
                        allrows += rows
                        pt.update(rows=len(rows), number_results=_pyval(r.get("NumberResults")))
                    except Exception as e:
                        pt["error"] = _err(e)
                        f["error"] = f["error"] or pt["error"]
                    pt["seconds"] = round(time.perf_counter() - t1, 3)
                    if len(f["per_target"]) < 200:
                        f["per_target"].append(pt)
                f["seconds"] = round(time.perf_counter() - t0, 3)
                f["rows"] = len(allrows)
                f["fields"] = header
                if header and "StepType" in header:
                    si = header.index("StepType")
                    f["step_types"] = sorted({str(rw[si]) for rw in allrows})
                if header and "LoadCase" in header:
                    ci = header.index("LoadCase")
                    f["output_cases"] = sorted({str(rw[ci]) for rw in allrows})
                if header:
                    fn = os.path.join(out_dir, "probe_rows_direct_%s_%s.csv" % (tbl, _safe(mode)))
                    rows_to_csv(fn, header, allrows[:CSV_ROWS])
                    f["csv"] = os.path.basename(fn)
                cap_reason = over_cap(f["seconds"], f["rows"], None)
                if cap_reason:
                    f["size_guard"] = cap_reason
                    route["skipped"].append("%s: remaining modes skipped (%s)" % (tbl, cap_reason))
                route["fetches"].append(f)
                say("  -> rows=%s seconds=%s %s" % (f["rows"], f["seconds"], f["error"] or ""))
                if save:
                    save("route B fetch")
    finally:
        say("Route B: restoring output options and selection ...")
        if "SetOptionMultiValuedCombo" in restored["attempted"]:
            try:
                net.call_rc(setup, S, "SetOptionMultiValuedCombo", orig_mv[0])
                restored["restored"].append("SetOptionMultiValuedCombo")
                r = net.call_rc(setup, S, "GetOptionMultiValuedCombo")
                after = [_pyval(v) for k, v in r.items() if k != "__ret__"]
                restored["options_after_restore_equal"] = (after == route["original_options"].get(
                    "GetOptionMultiValuedCombo"))
            except Exception as e:
                restored["errors"].append("SetOptionMultiValuedCombo restore/verify: %s" % _err(e))
        if "selected for output" in restored["changed"]:
            try:
                net.call_rc(setup, S, "DeselectAllCasesAndCombosForOutput")
                for kind, setter in (("case", "SetCaseSelectedForOutput"), ("combo", "SetComboSelectedForOutput")):
                    for n, s_ in sel_snap[kind].items():
                        if s_:
                            net.call_rc(setup, S, setter, n, True)
                restored["restored"].append("selected for output")
                ok = True
                for kind, getter in (("case", "GetCaseSelectedForOutput"), ("combo", "GetComboSelectedForOutput")):
                    for n, s_ in sel_snap[kind].items():
                        v = [x for k, x in net.call_rc(setup, S, getter, n).items() if k != "__ret__"]
                        if v and bool(v[0]) != s_:
                            ok = False
                restored["selection_after_restore_equal"] = ok
            except Exception as e:
                restored["errors"].append("restore selection: %s" % _err(e))


# --------------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------------
def _all_ok(restored):
    recs = [v for v in restored.values() if isinstance(v, dict)]
    if not recs:
        return None
    return all(not v.get("errors") and v.get("options_after_restore_equal") is not False
               and v.get("selection_after_restore_equal") is not False for v in recs)


def run(argv=None):
    import contextlib
    import io
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    argv = sys.argv[1:] if argv is None else list(argv)
    result = {"probe_version": 2, "started": stamp, "argv": argv, "python": sys.version,
              "attach": {}, "routes": {}, "restored": {"all_ok": None}, "warnings": []}
    args = None
    err_buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(err_buf):
            args = parse_args(argv)
        result["args"] = vars(args)
    except SystemExit as e:
        result["fatal"] = "argument error (exit %s): %s" % (e.code, err_buf.getvalue().strip())
    out_dir = os.path.abspath(args.out if args else "probe_out")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception as e:
        result["warnings"].append("cannot create %s (%s); writing to current folder" % (out_dir, _err(e)))
        out_dir = os.getcwd()
    result["output_dir"] = out_dir
    json_path = result["json_path"] = os.path.join(out_dir, "probe_result_%s.json" % stamp)
    old_out, old_err = sys.stdout, sys.stderr
    tee_out = tee_err = None
    try:
        tee_out = Tee(old_out, os.path.join(out_dir, "console.txt"))
        tee_err = Tee(old_err, os.path.join(out_dir, "console.txt"))
        sys.stdout, sys.stderr = tee_out, tee_err
    except Exception as e:
        result["warnings"].append("console copy not written: %s" % _err(e))
    t_start = time.perf_counter()

    def save(stage):
        result["last_stage"] = stage
        result["total_seconds"] = round(time.perf_counter() - t_start, 3)
        result["restored"]["all_ok"] = _all_ok(result["restored"])
        try:
            tmp = json_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(_jsonable(result), fh, indent=1, ensure_ascii=False)
            os.replace(tmp, json_path)
        except Exception as e:
            print("Could not write JSON %s: %s" % (json_path, _err(e)))

    try:
        if result.get("fatal"):
            say(result["fatal"])
        if args is not None:
            say("CSiBridge probe started %s. Output folder: %s" % (stamp, out_dir))
            say("Do not close this window. It may take several minutes. The model is never saved.")
            if not args.case:
                result["warnings"].append("no --case given: tables are not fetched and the output selection "
                                          "is not changed; give --case <combination>")
            if not args.group and not (args.frames or args.joints):
                result["warnings"].append("no --group and no --frames/--joints: nothing to fetch")
            save("start")
            say("Stage 1/4: attaching to CSiBridge ...")
            net, sap, model = attach(args, result)
            save("attach")
            if model is not None:
                say("Stage 2/4: reading model information (cases, combinations, groups) ...")
                objs = case_names = combo_names = None
                try:
                    objs, case_names, combo_names = probe_metadata(net, model, args, result)
                except Exception as e:
                    result["metadata_fatal"] = _err(e)
                    result["metadata_traceback"] = traceback.format_exc()
                save("metadata")
                if objs is not None:
                    for stage, fn, key in (("Stage 3/4: route A (database tables)", probe_database_tables,
                                            "database_tables"),
                                           ("Stage 4/4: route B (direct result calls)", probe_direct, "direct")):
                        say(stage + " ...")
                        try:
                            fn(net, objs, args, case_names, combo_names, out_dir, result, save)
                        except Exception as e:
                            r = result["routes"].setdefault(key, {})
                            r.setdefault("errors", []).append("fatal: %s" % _err(e))
                            r["traceback"] = traceback.format_exc()
                        save(key)
    except BaseException as e:  # noqa: BLE001 - must always write the JSON (also on Ctrl+C)
        result["fatal"] = _err(e)
        result["traceback"] = traceback.format_exc()
    finally:
        result["restored"]["note"] = "the probe never saves the model and never runs the analysis"
        save("final")
        try:
            print(summarise(result))
        except Exception as e:
            print("summary failed: %s; JSON at %s" % (_err(e), json_path))
        sys.stdout, sys.stderr = old_out, old_err
        for t_ in (tee_out, tee_err):
            if t_ is not None:
                t_.close()
    return result


if __name__ == "__main__":
    run()
