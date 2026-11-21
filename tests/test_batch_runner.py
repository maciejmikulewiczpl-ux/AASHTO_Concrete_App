"""batch.runner: run loop, result columns, project output."""
import json

import pytest

import calc_engine
import mphi_engine
from batch import columns as C
from batch.form import FORM_DEFAULTS
from batch.inputs import inputs_from_form
from batch.runner import run_batch
from batch.sheet_io import read_tsv
from tests.test_batch_sheet_io import CIRC, HDR, RECT, row

LAB = {c.key: c.header for c in C.SETTINGS_ROWS}
RH = [c.header for c in C.RESULT_COLUMNS]


def write_job(tmp_path, data_rows, settings=None):
    inp, st = tmp_path / "_batch_inputs.tsv", tmp_path / "_batch_settings.tsv"
    inp.write_text("\n".join("\t".join(r) for r in [HDR] + data_rows), encoding="utf-8")
    srows = [["Setting", "Value"]] + [[LAB[k], v] for k, v in (settings or {}).items()]
    st.write_text("\n".join("\t".join(r) for r in srows), encoding="utf-8")
    return str(inp), str(st), str(tmp_path / "_batch_results.tsv")


def results(path):
    rows = read_tsv(path)
    assert rows[0] == RH and len(rows[1]) == len(RH)  # header line, units line, data lines
    return [dict(zip(RH, r)) for r in rows[2:]]


def test_units_line(tmp_path):
    inp, st, res = write_job(tmp_path, [row(**RECT)], {"unit_length": "ft"})
    run_batch(inp, st, res)
    units = dict(zip(RH, read_tsv(res)[1]))
    assert units[col("row.Mr")] == "kip-ft" and units[col("res.flexure.Icr")] == "in⁴"
    assert units[col("calc.dc_M")] == ""


def col(source):
    return next(c.header for c in C.RESULT_COLUMNS if c.source == source)


def num(cell):
    return float(cell)


TWO_SECTIONS = [row(**RECT), row(**CIRC), row(section_id="B1", Mu=-2000, Vu=40, Ps=-20, Ms=-900),
                row(section_id="C1", Pu=-900, Mu=5000, Vu=30, Ms=2500, Ps=-400)]


@pytest.fixture(scope="module")
def two_sections(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("job")
    inp, st, res = write_job(tmp, TWO_SECTIONS, {"project_path": str(tmp / "job.aashto.json")})
    summary = run_batch(inp, st, res, str(tmp / "_batch_progress.txt"))
    return tmp, summary, results(res)


def _direct(form_cells, demands, i, units={"force": "kip", "length": "in"}):
    from batch.sheet_io import default_base_form, group_rows
    secs, errs = group_rows([HDR] + form_cells, default_base_form({}), units)
    assert not errs
    sec = secs[0]
    inputs = inputs_from_form(sec.form, units)
    dr = [dict(d, Vp=0, x=None, dp=None, fpe=None, load_case="service_I_full") for d in sec.demands]
    res = calc_engine.calculate_all(inputs, dr, i)
    mp = mphi_engine.moment_curvature_section(inputs, Ms=dr[i]["Ms"], Ps=dr[i]["Ps"])
    return res, mp


def test_summary_and_status(two_sections):
    tmp, summary, out = two_sections
    assert summary["sections"] == 2 and summary["rows"] == 4 and summary["errors"] == 0
    assert [r[col("calc.section_id")] for r in out] == ["B1", "C1", "B1", "C1"]
    assert all(r[col("calc.status")] in ("OK", "NG") for r in out)


def test_results_equal_direct_engine_calls(two_sections):
    _, _, out = two_sections
    b1 = [row(**RECT), row(section_id="B1", Mu=-2000, Vu=40, Ps=-20, Ms=-900)]
    for i, out_row in ((0, out[0]), (1, out[2])):
        res, mp = _direct(b1, None, i)
        assert num(out_row[col("res.flexure.Mn")]) == pytest.approx(res["flexure"]["Mn"], rel=1e-9)
        assert num(out_row[col("res.shear.dv")]) == pytest.approx(res["shear"]["dv"], rel=1e-9)
        assert num(out_row[col("row.Mr")]) == pytest.approx(abs(res["row_results"][i]["Mr"]), rel=1e-9)
        assert num(out_row[col("res.torsion.Tcr")]) == pytest.approx(res["torsion"]["Tcr"], rel=1e-9)
        assert num(out_row[col("mphi.first_yield.M")]) == pytest.approx(mp["first_yield"]["M"], rel=1e-9)
        assert out_row[col("row.flexStatus")] == res["row_results"][i]["flexStatus"]


def test_row_and_active_blocks_agree(two_sections):
    b1 = [row(**RECT), row(section_id="B1", Mu=-2000, Vu=40, Ps=-20, Ms=-900)]
    for i in (0, 1):
        res, _ = _direct(b1, None, i)
        rr = res["row_results"][i]
        assert rr["Vr2"] == pytest.approx(res["shear"]["Vr2"], rel=1e-9)
        assert rr["Tr"] == pytest.approx(res["torsion"]["Tr"], rel=1e-9)


@pytest.mark.xfail(strict=True, reason="ENGINE FINDING (reported to the user, not fixed - engine change "
                   "needs approval): row_results[i].Mr (demand-table D/C) differs from flexure.Mr of the "
                   "same active row - 5434.8 vs 5437.0 sagging; 239 vs 0 hogging with no top bars")
def test_row_and_active_flexure_mr_agree():
    b1 = [row(**RECT), row(section_id="B1", Mu=-2000, Vu=40, Ps=-20, Ms=-900)]
    for i in (0, 1):
        res, _ = _direct(b1, None, i)
        assert abs(res["row_results"][i]["Mr"]) == pytest.approx(res["flexure"]["Mr"], rel=1e-9)


@pytest.mark.parametrize("method,k", [("simp", 1), ("gp", 2), ("b5", 3)])
def test_shear_method_selects_capacity(tmp_path, method, k):
    inp, st, res = write_job(tmp_path, [row(**RECT)], {"shear_method": method})
    run_batch(inp, st, res)
    r = results(res)[0]
    assert r[col("calc.Vr")] == r[col(f"row.Vr{k}")] and r[col("calc.shear_method")] == method
    vr = num(r[col("calc.Vr")])
    if vr == 0:  # e.g. B5 not applicable -> capacity 0 -> D/C shown as infinity (setDC)
        assert r[col("calc.dc_V")] == "inf" and r[col("calc.status")] == "NG"
    else:
        assert num(r[col("calc.dc_V")]) == pytest.approx(60 / vr, rel=1e-9)
    assert r[col("calc.beta")] != "" or method == "b5"


def test_failing_section_isolated(tmp_path, monkeypatch):
    real = calc_engine.calculate_all

    def boom(inputs, rows, i):
        if inputs["h"] == 31:
            raise RuntimeError("engine exploded")
        return real(inputs, rows, i)
    monkeypatch.setattr(calc_engine, "calculate_all", boom)
    inp, st, res = write_job(tmp_path, [row(**dict(RECT, section_id="BAD", h_total=31)), row(**RECT)])
    s = run_batch(inp, st, res)
    out = results(res)
    assert out[0][col("calc.status")] == "ERROR" and "engine exploded" in out[0][col("calc.message")]
    assert out[1][col("calc.status")] in ("OK", "NG") and s["errors"] == 1


def test_validation_error_rows_marked(tmp_path):
    inp, st, res = write_job(tmp_path, [row(**dict(RECT, fc="5,5")), row(**CIRC), row(section_id="B1", Mu=1)])
    s = run_batch(inp, st, res)
    out = results(res)
    assert out[0][col("calc.status")] == "ERROR" and "decimal separator" in out[0][col("calc.message")]
    assert out[2][col("calc.status")] == "ERROR"  # every row of the bad section
    assert out[1][col("calc.status")] in ("OK", "NG") and s["errors"] == 2


def test_mphi_unavailable_is_note_not_error(tmp_path):
    inp, st, res = write_job(tmp_path, [row(**dict(CIRC, Ps=-1e6, Ms=100))])
    run_batch(inp, st, res)
    r = results(res)[0]
    assert r[col("calc.status")] != "ERROR" and r[col("calc.mphi_note")] != ""
    assert r[col("mphi.first_yield.M")] == ""


def test_results_in_original_row_order_with_blank_rows(tmp_path):
    blank = [""] * len(HDR)
    inp, st, res = write_job(tmp_path, [row(**RECT), blank, row(**CIRC), row(section_id="B1", Mu=5)])
    run_batch(inp, st, res)
    out = results(res)
    assert len(out) == 4 and all(v == "" for v in out[1].values())
    assert [out[i][col("calc.section_id")] for i in (0, 2, 3)] == ["B1", "C1", "B1"]


def test_units_ft_results_converted(tmp_path):
    inp, st, res = write_job(tmp_path, [row(**dict(RECT, b_flange=16 / 12, h_total=2.5, cover=2 / 12,
                                                    shear_s=0.5, Mu=250, fc=720))],
                             {"unit_length": "ft"})
    run_batch(inp, st, res)
    r_ft = results(res)[0]
    inp2, st2, res2 = write_job(tmp_path, [row(**dict(RECT, h_total=30, Mu=3000))])
    run_batch(inp2, st2, res2)
    r_in = results(res2)[0]
    assert num(r_ft[col("row.Mr")]) == pytest.approx(num(r_in[col("row.Mr")]) / 12, rel=1e-6)
    assert num(r_ft[col("res.shear.dv")]) == pytest.approx(num(r_in[col("res.shear.dv")]) / 12, rel=1e-6)


def test_no_al_tors_columns():
    for c in C.RESULT_COLUMNS:
        for bad in ("Al_tors", "Al_min", "Al_gov"):
            assert bad not in c.header and bad not in c.source


def test_progress_and_project_written(two_sections):
    tmp, summary, _ = two_sections
    assert (tmp / "_batch_progress.txt").read_text(encoding="utf-8").startswith("2/2")
    proj = json.loads((tmp / "job.aashto.json").read_text(encoding="utf-8"))
    assert list(proj["sections"]) == ["B1", "C1"] and len(proj["sections"]["B1"]["demandRows"]) == 2
    assert proj["runOptions"]["shearCapacityMethod"] == "gp" and summary["project"].endswith("job.aashto.json")


def test_project_not_overwritten_reported(tmp_path):
    p = tmp_path / "keep.aashto.json"
    p.write_text("{}", encoding="utf-8")
    inp, st, res = write_job(tmp_path, [row(**RECT)], {"project_path": str(p), "overwrite_project": "FALSE"})
    s = run_batch(inp, st, res)
    assert s["project"] is None and "exists" in s["project_error"] and p.read_text(encoding="utf-8") == "{}"
