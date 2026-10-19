import os
import pytest
from csi_import import parse_csi_frame_forces

FIX = os.path.join(os.path.dirname(__file__), "fixtures_csi")
DEFAULT = {"force": "kip", "moment": "kip-ft", "length": "ft"}


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def test_screenshot_fixture_parses():
    r = parse_csi_frame_forces(load("frame1227_strI1.txt"))
    assert len(r.rows) == 6
    assert r.n_envelope == 6
    assert r.units == DEFAULT
    assert r.cases == ["Str-I1"]
    assert r.frames == ["1227"]
    row = r.rows[0]
    assert row.station_in == 0 and row.step_type == "Max"
    assert row.P == pytest.approx(-2948.932)
    assert row.M2 == pytest.approx(4720.0867 * 12)
    assert row.T == pytest.approx(4523.3045 * 12)
    assert row.src_line == 3
    assert max(x.station_in for x in r.rows) == pytest.approx(202.0, rel=1e-4)


def test_dedupe_requires_identical_values():
    txt = load("frame1227_strI1.txt").splitlines()
    parts = txt[4].split("\t")
    parts[10] = "-5000.0"
    txt[4] = "\t".join(parts)  # corrupt first duplicate (1227-1 at 8.4167 Max)
    r = parse_csi_frame_forces("\n".join(txt))
    assert len(r.rows) == 7
    assert any("duplicate" in w.lower() for w in r.warnings)


def test_units_row_kn_m():
    r = parse_csi_frame_forces(load("kn_m_no_title.txt"))
    assert r.units == {"force": "kN", "moment": "kN-m", "length": "m"} or \
        r.units["force"].lower() == "kn"
    assert r.rows[0].P == pytest.approx(22.481, rel=1e-4)
    assert r.rows[0].M2 == pytest.approx(885.07, rel=1e-4)
    assert r.rows[1].P == pytest.approx(-1200.5 / 4.4482216152605, rel=1e-9)
    assert r.rows[1].station_in == pytest.approx(1000.5 / 0.0254, rel=1e-9)


def test_no_units_row_uses_defaults():
    r = parse_csi_frame_forces(load("no_units_row.txt"))
    assert r.units == DEFAULT
    assert any("No units row" in w for w in r.warnings)
    assert len(r.rows) == 2
    assert r.rows[1].station_in == 120.0
    assert r.rows[0].M3 == 60.0
    assert r.rows[0].envelope is False


def test_step_rows_are_concurrent():
    r = parse_csi_frame_forces(load("step_by_step.txt"))
    assert len(r.rows) == 3
    assert [x.envelope for x in r.rows] == [False] * 3
    assert r.n_envelope == 0


def test_unit_in_header_cell():
    ref = parse_csi_frame_forces(load("frame1227_strI1.txt"))
    hdr = ("Frame\tStation ft\tOutputCase\tCaseType\tStepType\tP Kip\tV2 Kip\tV3 Kip\t"
           "T Kip-ft\tM2 Kip-ft\tM3 Kip-ft\tFrameElem\tElemStation")
    lines = load("frame1227_strI1.txt").splitlines()
    r = parse_csi_frame_forces("\n".join([hdr] + lines[2:]))
    assert r.units == DEFAULT
    assert r.rows == [type(x)(**{**x.__dict__, "src_line": x.src_line - 1}) for x in ref.rows]


def test_header_case_and_whitespace_tolerant():
    txt = ("frame   STATION   outputcase   p   v2   v3   t   m2   M3\n"
           "ft_placeholder\n")
    txt = ("frame   STATION   outputcase   p   v2   v3   t   m2   M3\n"
           "Text   ft   Text   kip   kip   kip   kip-ft   kip-ft   kip-ft\n"
           "A   2   C1   -1   2   3   4   5   6\n")
    r = parse_csi_frame_forces(txt)
    assert len(r.rows) == 1
    assert r.rows[0].M3 == 72.0 and r.rows[0].station_in == 24.0


def test_missing_required_column_raises():
    txt = "Frame\tStation\tOutputCase\tP\tV2\tV3\tT\tM2\n1\t0\tA\t1\t1\t1\t1\t1\n"
    with pytest.raises(ValueError) as e:
        parse_csi_frame_forces(txt)
    assert "M3" in str(e.value)


def test_comma_thousands_and_blank_lines():
    r = parse_csi_frame_forces(load("kn_m_no_title.txt") + "\n\n")
    assert r.rows[1].P < -269


def test_unknown_unit_raises():
    txt = load("no_units_row.txt").replace("Frame\tStation\tOutputCase\tP", "Frame\tStation\tOutputCase\tP") \
        .replace("\tP\t", "\tP furlong\t")
    with pytest.raises(ValueError, match="Unknown unit 'furlong' in column P"):
        parse_csi_frame_forces(txt)


def test_units_row_missing_unit_falls_back():
    txt = ("Frame\tStation\tOutputCase\tP\tV2\tV3\tT\tM2\tM3\n"
           "Text\tft\t\t\tKip\tKip\tKip-ft\tKip-ft\tKip-ft\n"
           "A\t0\tC\t-5\t1\t1\t1\t1\t1\n")
    r = parse_csi_frame_forces(txt)
    assert r.rows[0].P == -5
    assert any("column P" in w for w in r.warnings)
