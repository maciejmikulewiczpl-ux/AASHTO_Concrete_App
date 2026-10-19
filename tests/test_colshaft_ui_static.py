"""Column on Shaft tab (Task 10): static / headless checks (ruling 10-5, P5).

No GUI is available unattended, so this pins:
  (a) index.html carries the new tab button, panel and script tag exactly once;
  (b) the 11 original tab buttons are unchanged (labels, data-tab, order);
  (c) the Node unit tests of colshaft.js pass;
  (d) `node --check colshaft.js` passes;
  (e) app.get_html() inlines colshaft.js (ruling 10-1) and leaves the tag alone
      when the file is missing;
  (f) the payload built by colshaft.js from a sample 2-bent state runs through
      Api().run_colshaft without error and gives the same bents as the engine
      test's equivalent payload.
"""
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")
JS = os.path.join(ROOT, "colshaft.js")
NODE_TEST = os.path.join(ROOT, "tests", "js", "test_colshaft_js.js")
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not found")

BUTTON = '<button class="tab-btn" data-tab="colshaft">Column on Shaft</button>'
PANEL = '<div class="tab-panel" id="tab-colshaft" data-title="Column on Shaft"></div>'
TAG = '<script src="colshaft.js"></script>'

ORIGINAL_TABS = [
    ("inputs", "Inputs"),
    ("section", "Section Definition"),
    ("pt", "PT Design"),
    ("demands", "Demands &amp; Results"),
    ("flexure", "Flexure"),
    ("shear", "Shear"),
    ("torsion", "Torsion"),
    ("service", "Service Flexure Stress"),
    ("report", "Report"),
    ("summary", "Project Summary"),
    ("limitations", "Limitations"),
]


def _html():
    with open(INDEX, encoding="utf-8") as f:
        return f.read()


def _tab_bar(html):
    m = re.search(r'<div class="tab-bar" id="tabBar">(.*?)</div>', html, re.S)
    assert m, "tabBar not found"
    return re.findall(r'<button class="tab-btn[^"]*" data-tab="([^"]+)">([^<]*)</button>', m.group(1))


# ── (a) / (b) index.html ───────────────────────────────────────────

def test_new_tab_button_panel_and_script_once():
    html = _html()
    assert html.count(BUTTON) == 1
    assert html.count(PANEL) == 1
    assert html.count(TAG) == 1
    assert html.count('id="tab-colshaft"') == 1
    # the button is the LAST one in #tabBar; the script comes after the main script block
    assert _tab_bar(html)[-1] == ("colshaft", "Column on Shaft")
    assert html.index(TAG) > html.rindex("updateFileDisplay(null);")
    assert html.index(PANEL) > html.index('id="tab-limitations"')
    # persistence hooks
    assert html.count("window.ColShaft.getState()") == 2
    assert html.count("window.ColShaft.setState(data.columnShaft||null)") == 1


def test_original_tab_buttons_unchanged():
    tabs = _tab_bar(_html())
    assert tabs[:len(ORIGINAL_TABS)] == ORIGINAL_TABS
    assert len(tabs) == len(ORIGINAL_TABS) + 1
    assert '<button class="tab-btn active" data-tab="inputs">Inputs</button>' in _html()


def test_colshaft_js_uses_only_cs_ids():
    with open(JS, encoding="utf-8") as f:
        js = f.read()
    ids = set(re.findall(r'(?:id=\\?"|getElementById\(\')([A-Za-z0-9_-]+)', js))
    assert ids, "no ids found"
    bad = sorted(i for i in ids if not i.startswith("cs-") and i != "tab-colshaft")
    assert bad == []
    assert "</script" not in js.lower()        # safe to inline (ruling 10-1)


# ── (c) / (d) Node ──────────────────────────────────────────────────

@needs_node
def test_node_check_colshaft_js():
    r = subprocess.run([NODE, "--check", JS], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@needs_node
def test_node_unit_tests_pass():
    r = subprocess.run([NODE, NODE_TEST], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "TESTS PASSED" in r.stdout


# ── (e) app.get_html inlining ───────────────────────────────────────

@pytest.fixture
def app_module(monkeypatch):
    try:
        import webview  # noqa: F401
    except ImportError:
        monkeypatch.setitem(sys.modules, "webview", types.ModuleType("webview"))
    monkeypatch.delitem(sys.modules, "app", raising=False)
    monkeypatch.syspath_prepend(ROOT)
    mod = importlib.import_module("app")
    yield mod
    sys.modules.pop("app", None)


def test_get_html_inlines_colshaft_js(app_module):
    html = app_module.get_html()
    with open(JS, encoding="utf-8") as f:
        js = f.read()
    assert TAG not in html
    assert html.count("<script>\n" + js + "\n</script>") == 1
    assert "window.ColShaft = {" in html
    # everything else unchanged
    assert html.replace("<script>\n" + js + "\n</script>", TAG) == _html()


def test_get_html_without_colshaft_js_leaves_tag(app_module, monkeypatch, tmp_path):
    shutil.copy(INDEX, tmp_path / "index.html")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert app_module.get_html() == _html()
    shutil.copy(JS, tmp_path / "colshaft.js")
    html = app_module.get_html()
    assert TAG not in html and "window.ColShaft = {" in html


def test_spec_bundles_colshaft_js():
    with open(os.path.join(ROOT, "AASHTO_Concrete_App.spec"), encoding="utf-8") as f:
        spec = f.read()
    assert re.search(r"\(\s*'colshaft\.js'\s*,\s*'\.'\s*\)", spec)


# ── (f) Node payload -> Api().run_colshaft ──────────────────────────

@needs_node
def test_node_payload_runs_through_api(tmp_path, monkeypatch):
    out = tmp_path / "payload.json"
    r = subprocess.run([NODE, NODE_TEST, "--dump", str(out)], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    with open(out, encoding="utf-8") as f:
        payload = json.load(f)
    assert set(payload) == {"paste", "units", "categories", "code", "params", "settings", "bents"}
    try:
        import webview  # noqa: F401
    except ImportError:
        monkeypatch.setitem(sys.modules, "webview", types.ModuleType("webview"))
    from api import Api
    res = json.loads(Api().run_colshaft(json.dumps(payload)))
    assert "error" not in res, res.get("error")
    assert [b["name"] for b in res["bents"]] == ["B1", "B2"]
    # same design as the engine test's hand-written equivalent payload ("2b")
    from tests import test_colshaft_engine as te
    ref = te.run("2b")
    for got, exp in zip(res["bents"], ref["bents"]):
        assert got["status"] == exp["status"]
        assert got["final"] == exp["final"]
        assert got["final_source"] == exp["final_source"]
    assert res["bents"][1]["shaft_basis"] == "soil"
    assert res["bents"][0]["shaft_basis"] == "cantilever"


# ── constants mirrored from Python (fix round 1) ────────────────────

@needs_node
def test_js_constants_mirror_python():
    import calc_engine as ce
    import colshaft_slender as csl
    code = ("const c=require(process.argv[1]);console.log(JSON.stringify("
            "{st:c.SLENDER_STATUS,rank:c.SLENDER_RANK,bars:c.BAR_SIZES,colors:c.STATUS_COLORS,"
            "srank:c.STATUS_RANK}))")
    r = subprocess.run([NODE, "-e", code, JS], capture_output=True, text=True, cwd=ROOT,
                       encoding="utf-8")       # the pending status carries an en dash
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["st"] == {"NEGLECT": csl.ST_NEGLECT, "PENDING": csl.ST_PENDING, "REFINED": csl.ST_REFINED}
    assert js["rank"] == csl._RANK
    assert js["bars"] == sorted(ce.BARS)
    import colshaft_engine as ee
    assert js["srank"] == ee.STATUS_RANK
    assert set(js["colors"]) == set(ee.STATUS_RANK)


@needs_node
def test_js_k_and_long_check_constants_mirror_python():
    """Follow-ups 2026-10-19: K sources / end conditions / Euler K / warning texts and the
    'n/a' long-check text are one value in Python and JS."""
    import colshaft_lrfd as cl
    import colshaft_slender as csl
    code = ("const c=require(process.argv[1]);console.log(JSON.stringify("
            "{src:c.K_SOURCES,end:c.END_CONDITIONS,euler:c.EULER_K,dw:c.DEFAULT_K_WARNING,"
            "uw:c.UNBRACED_K_LT1_WARNING,bn:c.BRACED_K_LT1_NOTE,na:c.LONG_NA}))")
    r = subprocess.run([NODE, "-e", code, JS], capture_output=True, text=True, cwd=ROOT,
                       encoding="utf-8")
    assert r.returncode == 0, r.stderr
    js = json.loads(r.stdout)
    assert js["src"] == list(csl.K_SOURCES) and js["end"] == list(csl.END_CONDITIONS)
    assert js["euler"] == csl.EULER_K
    assert js["dw"] == csl.DEFAULT_K_WARNING and js["uw"] == csl.UNBRACED_K_LT1_WARNING
    assert js["bn"] == csl.BRACED_K_LT1_NOTE and js["na"] == cl.LONG_NA


# ── Task 11: printable report ───────────────────────────────────────

def _js_eval(expr_code, *args):
    r = subprocess.run([NODE, "-e", expr_code, JS, *args], capture_output=True, text=True,
                       cwd=ROOT, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout


@needs_node
def test_open_decide_e_mirrors_open_items():
    """The report's DECIDE list equals the open E-section DECIDE rows of
    OPEN_VERIFICATION_ITEMS.md (update both together)."""
    with open(os.path.join(ROOT, "OPEN_VERIFICATION_ITEMS.md"), encoding="utf-8") as f:
        text = f.read().split("## Resolved")[0]
    open_e = re.findall(r"^\|\s*(E\d+)\s*\|\s*DECIDE\s*\|", text, re.M)
    js = json.loads(_js_eval("const c=require(process.argv[1]);"
                             "console.log(JSON.stringify(c.OPEN_DECIDE_E.map(e=>e[0])))"))
    assert open_e and js == open_e


@needs_node
def test_report_from_real_run(tmp_path):
    """reportHtml on the engine's real 2-bent result: every section in order per bent,
    the ported refs suffixed, the real M-phi curve and per-bound shaft profiles drawn,
    no 'undefined' / 'NaN' leaking into the page."""
    from tests import test_colshaft_engine as te
    res = te.run("2b")
    pl = te.PAYLOADS["2b"]()
    (tmp_path / "r.json").write_text(json.dumps(res), encoding="utf-8")
    (tmp_path / "p.json").write_text(json.dumps(pl), encoding="utf-8")
    code = ("const c=require(process.argv[1]),fs=require('fs');"
            "const r=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
            "const p=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));"
            "process.stdout.write(JSON.stringify({h:c.reportHtml(r,p,{project:'P',date:'2026-10-19'}),"
            "s:c.REPORT_SECTIONS.map(x=>x[0]),suf:c.UNVERIFIED_SUFFIX}))")
    out = json.loads(_js_eval(code, str(tmp_path / "r.json"), str(tmp_path / "p.json")))
    h, keys, suf = out["h"], out["s"], out["suf"]
    assert re.findall(r'<h3 data-sec="([a-z]+)">', h) == keys * 2
    for bad in ("undefined", "NaN", "[object Object]"):
        assert bad not in h, bad
    b1, b2 = h.split("Bent B2 —")
    for b, S in zip((b1, b2), (res["bents"][0]["seismic"], res["bents"][1]["seismic"])):
        assert "Column M-φ at P = %.0f kip" % S["mphi"]["P"] in b
        assert "Shaft M-φ at P = %.0f kip" % S["mphi_shaft"]["P"] in b
        for k in ("overstrength", "shear", "flexure", "shaft_capacity", "transverse"):
            esc = S["refs"][k].replace("&", "&amp;")
            assert esc + " " + suf in b, k
    # B2 is the soil basis: both bounds drawn, the governing one labelled
    assert "×2 " in b2 or "×2<" in b2
    assert "(governing)" in b2 and "(governing)" not in b1
    assert "Vo = Mo / H" in b1 and "envelope-bounded (conservative)" in h


def test_limitations_tab_lists_column_on_shaft_non_goals():
    html = _html()
    lim = html[html.index('id="tab-limitations"'):html.index(PANEL)]
    assert ">Column on Shaft</div>" in lim
    for text in ("displacement demand", "ductility demand", "column silos", "screen only",
                 "S6", "No service-limit crack control", "Circular members only",
                 "envelope-bounded (conservative)", "No direct CSiBridge read"):
        assert text in lim, text


# ── final-review fix wave ───────────────────────────────────────────

def test_panel_stops_keydown_and_keyup_propagation():
    """Ruling F-2: index.html's document-level keydown handler clears a multi-cell
    demand selection on Delete / Backspace; the Column on Shaft panel must stop
    keydown / keyup from bubbling to it (index.html's handler is not touched)."""
    with open(JS, encoding="utf-8") as f:
        js = f.read()
    for ev in ("keydown", "keyup", "change", "input"):
        m = re.search(r"panel\.addEventListener\('" + ev + r"', function \(ev\) \{(.*?)\n  \}\);|"
                      r"panel\.addEventListener\('" + ev + r"', function \(ev\) \{(.*?)\}\);", js, re.S)
        assert m, ev
        body = m.group(1) or m.group(2)
        assert "ev.stopPropagation()" in body, ev
    # the main-tab handler is still there, unchanged in shape
    assert "document.addEventListener('keydown',(e)=>{" in _html()


@needs_node
def test_js_pending_status_and_gr60_mirror_python():
    import colshaft_engine as ee
    import colshaft_seismic as cs
    out = json.loads(_js_eval("const c=require(process.argv[1]);console.log(JSON.stringify("
                              "{p:c.ST_OK_PENDING,g:c.GR60_EXPECTED}))"))
    assert out["p"] == ee.ST_OK_PENDING
    assert out["g"] == {"fye": cs.FYE, "fue": cs.FUE, "fyh": cs.FYH}


def test_stale_banner_and_print_guard_wiring():
    """Minors 7b / 7h (DOM only, so pinned statically): edits after a run mark the
    results stale until the next Design; window.print() is guarded and a print not
    started by this tab drops a stale cs-printing class."""
    with open(JS, encoding="utf-8") as f:
        js = f.read()
    assert "markStale(path);" in js and js.count("markStale()") >= 3
    done = js[js.index("lastResult = r;"):js.index("renderResults();", js.index("lastResult = r;"))]
    assert "stale = false;" in done and "showStale();" in done
    pr = js[js.index("function printReportCs()"):js.index("function renderAll()")]
    assert "try {" in pr and "window.print();" in pr and "catch (e)" in pr and "off();" in pr
    assert "printFlag = true;" in pr
    bp = js[js.index("window.addEventListener('beforeprint'"):]
    assert "if (printFlag) { printFlag = false; return; }" in bp[:300]
    assert "classList.remove('cs-printing')" in bp[:400]
