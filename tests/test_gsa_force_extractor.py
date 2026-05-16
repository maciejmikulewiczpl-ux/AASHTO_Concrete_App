"""Tests for the standalone gsa_force_extractor tool.

Uses a duck-typed MockGsaModel; gsapy is NOT required to run these tests.

These tests exercise the pure-Python parts of the tool (envelope, unit
and sign conversion, column selection, CSV / table output, element
selector resolution via the adapter) without ever touching the AASHTO
concrete app.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys

import pytest

# Make the project root importable from inside tests/ (mirrors fixtures.py).
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import gsa_force_extractor as gfe  # noqa: E402


# ---------------------------------------------------------------------------
# A duck-typed mock GSA model — implements only what GsaAdapter needs.
# ---------------------------------------------------------------------------

class _MockElement:
    def __init__(self, prop):
        self.prop = prop


class MockGsaModel:
    """Duck-typed model matching the real gsapy.GSA surface that GsaAdapter
    actually calls.

    Internal data shape (test-author convenience):
      combos    : {combo_name: {(elem, position, perm): {axis: float}}}
      groups    : {group_name: [elem_id, ...]}      (saved-list lookups)
      properties: {prop_num:   [elem_id, ...]}      (mock-only convenience;
                  surfaced via the .prop attribute on _MockElement)
    """

    POSITION_RESOLUTION = 100  # must match GsaAdapter.POSITION_RESOLUTION

    def __init__(self, combos, groups=None, properties=None):
        self._combos = combos
        self._groups = groups or {}
        self._properties = properties or {}

    # --- gsapy-style API ----------------------------------------------

    def get_elements(self, indices=None):
        """Mirror gsapy.GSA.get_elements: returns {id: Element}.
        - indices=None  -> all elements (collected from properties + combos)
        - indices=str   -> saved-list name
        """
        if indices is None:
            ids: set = set()
            for ids_list in self._properties.values():
                ids.update(ids_list)
            for combo_data in self._combos.values():
                for (e, _, _) in combo_data.keys():
                    ids.add(e)
            return {i: self._element_for(i) for i in ids}
        if isinstance(indices, str):
            return {i: self._element_for(i) for i in self._groups.get(indices, [])}
        if isinstance(indices, int):
            return {indices: self._element_for(indices)}
        return {int(i): self._element_for(int(i)) for i in indices}

    def _element_for(self, eid):
        for prop, ids in self._properties.items():
            if eid in ids:
                return _MockElement(prop)
        return _MockElement(0)

    def case_num_perm(self, case_type="A", case_ref=1):
        combo = f"{case_type}{case_ref}"
        if combo not in self._combos:
            return 0
        perms = {p for (_, _, p) in self._combos[combo].keys()}
        return len(perms)

    def case_perm_string(self, case_type="L", case_ref=1, perm_num=0):
        # Build the same form gsapy returns: e.g. "C1p3"
        return f"{case_type}{case_ref}p{perm_num}"

    def get_unit_names(self):
        # Tests default to (kN, m); override per-test by setting model._unit_names.
        return getattr(self, "_unit_names", {"FORCE": "kN", "LENGTH": "m"})

    def get_1D_elem_resultants(self, index, case, axis="default", addl_pts=0,
                               interesting_pts=False):
        """Return a list of [Fx, Fy, Fz, Mxx, Myy, Mzz] over (addl_pts + 2)
        equally-spaced points. Each (elem, position, perm) cell in the test
        fixture writes its forces into the corresponding index; positions
        with no fixture entry remain zero. Supports multi-position fixtures
        for position="max" tests.
        """
        if "p" in case:
            combo, _, _ = case.rpartition("p")
        else:
            combo = case
        combo_data = self._combos.get(combo)
        if combo_data is None:
            raise KeyError(f"Mock has no combo {combo!r} for case {case!r}")
        n_pts = addl_pts + 2
        results = [[0.0] * 6 for _ in range(n_pts)]
        found_any = False
        for (e, pos, p), forces in combo_data.items():
            if e == index and p == case:
                idx = round(pos * (n_pts - 1))
                idx = max(0, min(n_pts - 1, idx))
                results[idx] = [
                    float(forces["Fx"]), float(forces["Fy"]), float(forces["Fz"]),
                    float(forces["Mxx"]), float(forces["Myy"]), float(forces["Mzz"]),
                ]
                found_any = True
        if not found_any:
            raise KeyError(f"No forces for elem={index} case={case!r}")
        return results


# ---------------------------------------------------------------------------
# Envelope correctness (the key engineering invariant)
# ---------------------------------------------------------------------------

def _perm_rows():
    """Six hand-built rows already in app units; Mu in kip-in, Pu/Vu in kip."""
    return [
        {"perm_id": "Cp1", "Pu": -100.0, "Mu":  100.0, "Vu":  10.0, "Tu":   1.0},
        {"perm_id": "Cp2", "Pu": -120.0, "Mu":  500.0, "Vu":  50.0, "Tu":   5.0},
        {"perm_id": "Cp3", "Pu":  -80.0, "Mu":  900.0, "Vu":  20.0, "Tu":   8.0},
        {"perm_id": "Cp4", "Pu": -200.0, "Mu":  -50.0, "Vu":  90.0, "Tu":  -3.0},
        {"perm_id": "Cp5", "Pu":   30.0, "Mu": -400.0, "Vu": -75.0, "Tu":  12.0},
        {"perm_id": "Cp6", "Pu":  -60.0, "Mu":  700.0, "Vu":  40.0, "Tu":  -7.0},
    ]


def test_envelope_max_top3_picks_largest_three_in_order():
    rows = _perm_rows()
    out = gfe.envelope(rows, action="max", on="Mu", top_n=3)
    assert [r["perm_id"] for r in out] == ["Cp3", "Cp6", "Cp2"]
    # Coexistent forces preserved verbatim from the source permutation.
    assert out[0]["Pu"] == -80.0
    assert out[0]["Vu"] == 20.0
    assert out[0]["Tu"] == 8.0


def test_envelope_min_top1_picks_most_negative():
    rows = _perm_rows()
    out = gfe.envelope(rows, action="min", on="Mu", top_n=1)
    assert out[0]["perm_id"] == "Cp5"
    assert out[0]["Mu"] == -400.0
    # And the coexistent Pu (tension!) tags along.
    assert out[0]["Pu"] == 30.0


def test_envelope_max_abs_distinguishes_from_max():
    rows = _perm_rows()
    out_max = gfe.envelope(rows, action="max", on="Vu", top_n=1)
    out_abs = gfe.envelope(rows, action="max_abs", on="Vu", top_n=1)
    # Max +Vu is Cp4 (90); max |Vu| is also Cp4 (|90| > |-75|). Pick a force
    # where the two diverge to make the distinction sharp:
    out_max_p = gfe.envelope(rows, action="max", on="Pu", top_n=1)
    out_abs_p = gfe.envelope(rows, action="max_abs", on="Pu", top_n=1)
    assert out_max_p[0]["perm_id"] == "Cp5"   # algebraically largest = +30
    assert out_abs_p[0]["perm_id"] == "Cp4"   # largest magnitude = -200
    # And the |Vu| sanity check:
    assert out_max[0]["perm_id"] == "Cp4"
    assert out_abs[0]["perm_id"] == "Cp4"


def test_envelope_top_n_clamps_to_available():
    rows = _perm_rows()[:2]
    out = gfe.envelope(rows, action="max", on="Mu", top_n=10)
    assert len(out) == 2


# ---------------------------------------------------------------------------
# Unit and sign conversion
# ---------------------------------------------------------------------------

def test_force_factor_kn_to_kip():
    # 1 kN = 0.224809 kip (within rounding)
    f = gfe.force_factor("kN")
    assert pytest.approx(f, rel=1e-4) == 0.224809


def test_moment_factor_knm_to_kip_in():
    # 1 kN.m = 0.224809 kip * 39.3701 in = 8.85075 kip-in
    m = gfe.moment_factor("kN.m")
    assert pytest.approx(m, rel=1e-4) == 8.85075


def test_moment_unit_separators_all_supported():
    for s in ("kN.m", "kN-m", "kN*m", "kN m"):
        assert pytest.approx(gfe.moment_factor(s), rel=1e-4) == 8.85075


def test_gsa_perm_to_app_row_default_signs_match_typical_gsa():
    """Defaults: GSA Fx tension-positive (matches app -> no axial flip);
    GSA Myy/Mzz hogging-positive (differs from app -> moment flip)."""
    perm = {"perm_id": "C1p1", "Fx": -100.0, "Fy": 50.0, "Fz": 30.0,
            "Mxx": 5.0, "Myy": 200.0, "Mzz": 0.0}
    output_units = gfe.UnitsCfg()  # kip / kip-in defaults
    signs = gfe.SignsCfg()  # all defaults
    axes = {"Pu": "Fx", "Mu": "Myy", "Vu": "Fz", "Tu": "Mxx"}
    row = gfe.gsa_perm_to_app_row(
        perm, axes, ["Pu", "Mu", "Vu", "Tu"],
        "kN", "kN.m", output_units, signs,
    )
    # Pu: GSA Fx = -100 kN (compression in GSA) -> app Pu = -100 kip*conv
    # (compression in app, no flip).
    assert row["Pu"] == pytest.approx(-100.0 * 0.224809, rel=1e-4)
    # Mu: GSA Myy = +200 kN.m (hogging in GSA) -> app Mu negative (hogging
    # in app), flip applied.
    assert row["Mu"] == pytest.approx(-200.0 * 8.85075, rel=1e-4)
    # Vu: not affected by either flip.
    assert row["Vu"] == pytest.approx(30.0 * 0.224809, rel=1e-4)
    # Tu: torsion is NOT a bending moment, so no flip.
    assert row["Tu"] == pytest.approx(5.0 * 8.85075, rel=1e-4)


def test_gsa_perm_to_app_row_axial_flip_when_compression_positive():
    """If GSA reports compression as +Fx, flag flips to give app -Pu."""
    perm = {"perm_id": "C1p1", "Fx": 100.0, "Fy": 0.0, "Fz": 0.0,
            "Mxx": 0.0, "Myy": 0.0, "Mzz": 0.0}
    output_units = gfe.UnitsCfg(output_force="kip", output_moment="kip-in")
    signs = gfe.SignsCfg(axial_compression_positive_in_gsa=True,
                        moment_hogging_positive_in_gsa=False)
    row = gfe.gsa_perm_to_app_row(perm, {"Pu": "Fx"}, ["Pu"],
                                   "kip", "kip-in", output_units, signs)
    # Fx = +100 means compression in GSA per the flag -> app Pu = -100.
    assert row["Pu"] == -100.0


def test_gsa_perm_to_app_row_no_moment_flip_when_disabled():
    """If GSA hog-positive flag is off, moments pass through un-flipped."""
    perm = {"perm_id": "C1p1", "Fx": 0.0, "Fy": 0.0, "Fz": 0.0,
            "Mxx": 0.0, "Myy": 200.0, "Mzz": 0.0}
    output_units = gfe.UnitsCfg(output_force="kip", output_moment="kip-in")
    signs = gfe.SignsCfg(axial_compression_positive_in_gsa=False,
                        moment_hogging_positive_in_gsa=False)
    row = gfe.gsa_perm_to_app_row(perm, {"Mu": "Myy"}, ["Mu"],
                                   "kip", "kip-in", output_units, signs)
    assert row["Mu"] == 200.0


def test_gsa_perm_to_app_row_torsion_never_flipped_by_moment_flag():
    """The moment flag affects bending (Mu, Ms) only; torsion (Tu) stays."""
    perm = {"perm_id": "C1p1", "Fx": 0.0, "Fy": 0.0, "Fz": 0.0,
            "Mxx": 50.0, "Myy": 0.0, "Mzz": 0.0}
    output_units = gfe.UnitsCfg(output_force="kip", output_moment="kip-in")
    signs = gfe.SignsCfg(moment_hogging_positive_in_gsa=True)  # default
    row = gfe.gsa_perm_to_app_row(perm, {"Tu": "Mxx"}, ["Tu"],
                                   "kip", "kip-in", output_units, signs)
    assert row["Tu"] == 50.0  # NOT -50; torsion isn't a bending moment.


# ---------------------------------------------------------------------------
# Note formatting
# ---------------------------------------------------------------------------

def test_envelope_note_strings():
    assert gfe.envelope_note("max", "Mu", 1, 3) == "max Mu (rank 1/3)"
    assert gfe.envelope_note("min", "Pu", 2, 5) == "min Pu (rank 2/5)"
    assert gfe.envelope_note("max_abs", "Vu", 1, 1) == "max |Vu| (rank 1/1)"


# ---------------------------------------------------------------------------
# Element selector resolution (group, property, explicit)
# ---------------------------------------------------------------------------

def _adapter_with_groups():
    model = MockGsaModel(
        combos={},
        groups={"PierCap": [10, 11, 12]},
        properties={5: [101, 102]},
    )
    return gfe.GsaAdapter(model)


def test_resolve_explicit_element():
    adapter = _adapter_with_groups()
    assert gfe.resolve_target_elements(adapter, {"element": 7, "position": 0.5}) == [7]


def test_resolve_explicit_elements_list():
    adapter = _adapter_with_groups()
    assert gfe.resolve_target_elements(adapter, {"elements": [1, 2, 3], "position": 0.5}) == [1, 2, 3]


def test_resolve_group():
    adapter = _adapter_with_groups()
    assert gfe.resolve_target_elements(adapter, {"group": "PierCap", "position": 0.5}) == [10, 11, 12]


def test_resolve_property():
    adapter = _adapter_with_groups()
    assert gfe.resolve_target_elements(adapter, {"property": 5, "position": 0.5}) == [101, 102]


# ---------------------------------------------------------------------------
# End-to-end run_job: integrates envelope + units + element resolution.
# ---------------------------------------------------------------------------

def _build_combo_with_known_extremes():
    """Build a combo where it's hand-verifiable which permutation wins."""
    # All values in kN / kN.m. Fx is tension-positive; we'll flip on read.
    # C1p1: small forces. C1p2: max +Mzz. C1p3: max |Vy|. C1p4: max compression.
    return {
        "C1": {
            (124, 0.5, "C1p1"): {"Fx":  10.0, "Fy":   5.0, "Fz": 0.0, "Mxx":  1.0, "Myy": 0.0, "Mzz":  100.0},
            (124, 0.5, "C1p2"): {"Fx": -50.0, "Fy":  20.0, "Fz": 0.0, "Mxx":  3.0, "Myy": 0.0, "Mzz": 1000.0},
            (124, 0.5, "C1p3"): {"Fx": -30.0, "Fy": -75.0, "Fz": 0.0, "Mxx": -2.0, "Myy": 0.0, "Mzz":  300.0},
            (124, 0.5, "C1p4"): {"Fx": 800.0, "Fy":  10.0, "Fz": 0.0, "Mxx":  0.0, "Myy": 0.0, "Mzz":  500.0},
        }
    }


def _job_strength():
    return gfe.JobCfg(
        name="Test job",
        location={"element": 124, "position": 0.5},
        combo="C1",
        axes={"Pu": "Fx", "Mu": "Mzz", "Vu": "Fy", "Tu": "Mxx"},
        forces_to_output=["Pu", "Mu", "Vu", "Tu"],
        envelopes=[
            gfe.EnvelopeRule(action="max", on="Mu", top_n=2),
            gfe.EnvelopeRule(action="max_abs", on="Vu", top_n=1),
            gfe.EnvelopeRule(action="min", on="Pu", top_n=1),
        ],
    )


def test_run_job_end_to_end_with_units_signs_and_envelopes():
    model = MockGsaModel(combos=_build_combo_with_known_extremes())
    adapter = gfe.GsaAdapter(model)
    output_units = gfe.UnitsCfg()  # kip / kip-in
    # Disable both flips so the test focuses on ranking + unit conversion.
    signs = gfe.SignsCfg(axial_compression_positive_in_gsa=False,
                        moment_hogging_positive_in_gsa=False)
    rows = gfe.run_job(adapter, _job_strength(), "kN", "kN.m", output_units, signs)

    # 2 (max Mu) + 1 (max |Vu|) + 1 (min Pu) = 4 rows
    assert len(rows) == 4

    # Max Mu rank 1 = C1p2; rank 2 = C1p4.
    max_mu_rows = [r for r in rows if r["Note"].startswith("max Mu")]
    assert [r["Permutation"] for r in max_mu_rows] == ["C1p2", "C1p4"]
    # No flips: app Pu == GSA Fx after unit conversion.
    f_kn_to_kip = gfe.force_factor("kN")
    assert max_mu_rows[0]["Pu"] == pytest.approx(-50.0 * f_kn_to_kip, rel=1e-4)
    assert max_mu_rows[1]["Pu"] == pytest.approx(800.0 * f_kn_to_kip, rel=1e-4)

    # Max |Vu| = C1p3 (|-75| largest)
    max_vu = [r for r in rows if r["Note"].startswith("max |Vu|")][0]
    assert max_vu["Permutation"] == "C1p3"

    # Min Pu (most negative app Pu) = C1p2 (Fx=-50, smallest non-flipped).
    # With no flip and Fx values [10, -50, -30, +800], the min is -50 = C1p2.
    min_pu = [r for r in rows if r["Note"].startswith("min Pu")][0]
    assert min_pu["Permutation"] == "C1p2"

    # Meta columns populated.
    for r in rows:
        assert r["Job"] == "Test job"
        assert r["Element"] == 124
        assert r["Position"] == 0.5
        assert r["Combo"] == "C1"


def _f(Fx=0.0, Fy=0.0, Fz=0.0, Mxx=0.0, Myy=0.0, Mzz=0.0):
    return {"Fx": Fx, "Fy": Fy, "Fz": Fz, "Mxx": Mxx, "Myy": Myy, "Mzz": Mzz}


def _combo_multi_position():
    """Two perms with forces sampled at several positions along the element.

    Designed so the global max Mzz across (perm, position) is at perm C1p2,
    position 0.75 — so a position='max' job should pick that cell and
    report its coexistent Fx (-50) and the position 0.75.
    """
    return {
        "C1": {
            (1, 0.0,  "C1p1"): _f(Mzz=100, Fx=10),
            (1, 0.5,  "C1p1"): _f(Mzz=300, Fx=12),
            (1, 1.0,  "C1p1"): _f(Mzz=200, Fx=15),
            (1, 0.0,  "C1p2"): _f(Mzz=400, Fx=-10),
            (1, 0.5,  "C1p2"): _f(Mzz=600, Fx=-30),
            (1, 0.75, "C1p2"): _f(Mzz=900, Fx=-50),
            (1, 1.0,  "C1p2"): _f(Mzz=200, Fx=-20),
        }
    }


def test_run_job_position_max_picks_global_extreme_across_positions():
    model = MockGsaModel(combos=_combo_multi_position())
    adapter = gfe.GsaAdapter(model)
    output_units = gfe.UnitsCfg()  # kip / kip-in
    signs = gfe.SignsCfg(axial_compression_positive_in_gsa=False,
                        moment_hogging_positive_in_gsa=False)
    job = gfe.JobCfg(
        name="max-pos test",
        location={"element": 1, "position": "max"},
        combo="C1",
        axes={"Pu": "Fx", "Mu": "Mzz"},
        forces_to_output=["Pu", "Mu"],
        envelopes=[gfe.EnvelopeRule("max", "Mu", 1)],
    )
    rows = gfe.run_job(adapter, job, "kN", "kN.m", output_units, signs)
    assert len(rows) == 1
    r = rows[0]
    # The global max Mu is at C1p2 / position 0.75.
    assert r["Permutation"] == "C1p2"
    assert r["Position"] == pytest.approx(0.75, abs=0.011)
    # Note annotates the position so the user knows where it came from.
    assert "x/L=0.75" in r["Note"]
    # Coexistent Pu is the same cell's Fx (-50 kN, no flip).
    assert r["Pu"] == pytest.approx(-50.0 * gfe.force_factor("kN"), rel=1e-4)


def test_run_job_position_max_per_envelope_uses_independent_extremes():
    """Different envelopes get different best positions."""
    model = MockGsaModel(combos=_combo_multi_position())
    adapter = gfe.GsaAdapter(model)
    output_units = gfe.UnitsCfg()  # kip / kip-in
    signs = gfe.SignsCfg(axial_compression_positive_in_gsa=False,
                        moment_hogging_positive_in_gsa=False)
    job = gfe.JobCfg(
        name="multi-envelope",
        location={"element": 1, "position": "max"},
        combo="C1",
        axes={"Pu": "Fx", "Mu": "Mzz"},
        forces_to_output=["Pu", "Mu"],
        envelopes=[
            gfe.EnvelopeRule("max", "Mu", 1),
            gfe.EnvelopeRule("min", "Pu", 1),
        ],
    )
    rows = gfe.run_job(adapter, job, "kN", "kN.m", output_units, signs)
    assert len(rows) == 2
    by_note = {r["Note"].split(" @")[0]: r for r in rows}
    # Max Mu -> C1p2 / pos 0.75 / Mzz=900
    mu_row = by_note["max Mu (rank 1/1)"]
    assert mu_row["Permutation"] == "C1p2"
    assert mu_row["Position"] == pytest.approx(0.75, abs=0.011)
    # Min Pu -> most negative Fx anywhere = -50 at C1p2 / pos 0.75
    pu_row = by_note["min Pu (rank 1/1)"]
    assert pu_row["Permutation"] == "C1p2"
    assert pu_row["Position"] == pytest.approx(0.75, abs=0.011)


def test_run_job_position_max_case_insensitive():
    """Accept 'MAX', 'Max', 'max' equivalently."""
    model = MockGsaModel(combos=_combo_multi_position())
    adapter = gfe.GsaAdapter(model)
    output_units = gfe.UnitsCfg()  # kip / kip-in
    signs = gfe.SignsCfg(axial_compression_positive_in_gsa=False,
                        moment_hogging_positive_in_gsa=False)
    job = gfe.JobCfg(
        name="case test",
        location={"element": 1, "position": "MAX"},
        combo="C1",
        axes={"Mu": "Mzz"},
        forces_to_output=["Mu"],
        envelopes=[gfe.EnvelopeRule("max", "Mu", 1)],
    )
    rows = gfe.run_job(adapter, job, "kN", "kN.m", output_units, signs)
    assert len(rows) == 1
    assert rows[0]["Permutation"] == "C1p2"


def _combo_two_elements_same_perms():
    """Two elements with separable forces, two perms, fixed position 0.5.
    Element 10's Fx + Element 11's Fx is the summed Pu.
    """
    return {
        "C1": {
            (10, 0.5, "C1p1"): _f(Fx=-50, Myy=100),
            (11, 0.5, "C1p1"): _f(Fx=-30, Myy=200),
            (10, 0.5, "C1p2"): _f(Fx=-80, Myy=400),
            (11, 0.5, "C1p2"): _f(Fx=-60, Myy=300),
        }
    }


def test_run_job_sum_across_elements_at_fixed_position():
    model = MockGsaModel(combos=_combo_two_elements_same_perms())
    adapter = gfe.GsaAdapter(model)
    output_units = gfe.UnitsCfg()  # kip / kip-in
    signs = gfe.SignsCfg(axial_compression_positive_in_gsa=False,
                        moment_hogging_positive_in_gsa=False)
    job = gfe.JobCfg(
        name="pile group",
        location={"elements": [10, 11], "position": 0.5,
                  "sum_across_elements": True},
        combo="C1",
        axes={"Pu": "Fx", "Mu": "Myy"},
        forces_to_output=["Pu", "Mu"],
        envelopes=[
            gfe.EnvelopeRule("min", "Pu", 1),
            gfe.EnvelopeRule("max", "Mu", 1),
        ],
    )
    rows = gfe.run_job(adapter, job, "kN", "kN.m", output_units, signs)
    assert len(rows) == 2  # one per envelope rule, ONE summed target
    f_kn_to_kip = gfe.force_factor("kN")
    m_knm_to_kipin = gfe.moment_factor("kN.m")
    # Both rows should reference the summed group, not individual elements.
    for r in rows:
        assert r["Element"] == "sum(10,11)"

    # Min Pu: sum Fx per perm.
    #   C1p1: -50 + -30 = -80
    #   C1p2: -80 + -60 = -140  <- min (most negative)
    min_pu = next(r for r in rows if r["Note"].startswith("min Pu"))
    assert min_pu["Permutation"] == "C1p2"
    assert min_pu["Pu"] == pytest.approx(-140.0 * f_kn_to_kip, rel=1e-4)
    # Coexistent Mu in the same perm: sum Myy = 400 + 300 = 700
    assert min_pu["Mu"] == pytest.approx(700.0 * m_knm_to_kipin, rel=1e-4)

    # Max Mu: sum Myy per perm.
    #   C1p1: 100 + 200 = 300
    #   C1p2: 400 + 300 = 700  <- max
    max_mu = next(r for r in rows if r["Note"].startswith("max Mu"))
    assert max_mu["Permutation"] == "C1p2"
    assert max_mu["Mu"] == pytest.approx(700.0 * m_knm_to_kipin, rel=1e-4)


def test_run_job_sum_across_group_label_uses_group_name():
    model = MockGsaModel(
        combos=_combo_two_elements_same_perms(),
        groups={"PileGroupA": [10, 11]},
    )
    adapter = gfe.GsaAdapter(model)
    output_units = gfe.UnitsCfg()  # kip / kip-in
    signs = gfe.SignsCfg(axial_compression_positive_in_gsa=False,
                        moment_hogging_positive_in_gsa=False)
    job = gfe.JobCfg(
        name="group sum",
        location={"group": "PileGroupA", "position": 0.5,
                  "sum_across_elements": True},
        combo="C1",
        axes={"Pu": "Fx"},
        forces_to_output=["Pu"],
        envelopes=[gfe.EnvelopeRule("min", "Pu", 1)],
    )
    rows = gfe.run_job(adapter, job, "kN", "kN.m", output_units, signs)
    assert len(rows) == 1
    assert rows[0]["Element"] == "sum(PileGroupA)"


def test_run_job_sum_with_max_position_scans_summed_forces():
    """Position='max' + sum: scan summed forces over the whole element span."""
    # Build a fixture where element 10 has max Myy at x/L=0.5 and element 11
    # has max Myy at x/L=0.75. The SUM is largest at... let's compute:
    #   x/L=0.5:  300 + 100 = 400
    #   x/L=0.75: 200 + 500 = 700  <- max sum
    combos = {
        "C1": {
            (10, 0.0,  "C1p1"): _f(Myy=10),
            (10, 0.5,  "C1p1"): _f(Myy=300),
            (10, 0.75, "C1p1"): _f(Myy=200),
            (10, 1.0,  "C1p1"): _f(Myy=20),
            (11, 0.0,  "C1p1"): _f(Myy=10),
            (11, 0.5,  "C1p1"): _f(Myy=100),
            (11, 0.75, "C1p1"): _f(Myy=500),
            (11, 1.0,  "C1p1"): _f(Myy=20),
        }
    }
    model = MockGsaModel(combos=combos)
    adapter = gfe.GsaAdapter(model)
    output_units = gfe.UnitsCfg()  # kip / kip-in
    signs = gfe.SignsCfg(axial_compression_positive_in_gsa=False,
                        moment_hogging_positive_in_gsa=False)
    job = gfe.JobCfg(
        name="sum max-pos",
        location={"elements": [10, 11], "position": "max",
                  "sum_across_elements": True},
        combo="C1",
        axes={"Mu": "Myy"},
        forces_to_output=["Mu"],
        envelopes=[gfe.EnvelopeRule("max", "Mu", 1)],
    )
    rows = gfe.run_job(adapter, job, "kN", "kN.m", output_units, signs)
    assert len(rows) == 1
    r = rows[0]
    assert r["Position"] == pytest.approx(0.75, abs=0.01)
    assert "x/L=0.75" in r["Note"]
    assert r["Mu"] == pytest.approx(700.0 * gfe.moment_factor("kN.m"), rel=1e-4)


def test_load_config_accepts_max_position(tmp_path):
    cfg = _minimal_cfg()
    cfg["jobs"][0]["location"]["position"] = "max"
    parsed = gfe.load_config(_write_json(tmp_path, cfg))
    assert parsed.jobs[0].location["position"] == "max"


def test_load_config_rejects_bad_position(tmp_path):
    cfg = _minimal_cfg()
    cfg["jobs"][0]["location"]["position"] = "middle"
    with pytest.raises(ValueError, match="position"):
        gfe.load_config(_write_json(tmp_path, cfg))


def test_run_job_group_selector_emits_one_block_per_element():
    # Same forces dict reused for elements 10 and 11.
    base = _build_combo_with_known_extremes()["C1"]
    combos = {"C1": {}}
    for elem in (10, 11):
        for (_, pos, perm), force in base.items():
            combos["C1"][(elem, pos, perm)] = force
    model = MockGsaModel(combos=combos, groups={"PierCap": [10, 11]})
    adapter = gfe.GsaAdapter(model)
    output_units = gfe.UnitsCfg()  # kip / kip-in
    signs = gfe.SignsCfg(axial_compression_positive_in_gsa=False,
                        moment_hogging_positive_in_gsa=False)

    job = gfe.JobCfg(
        name="Group sweep",
        location={"group": "PierCap", "position": 0.5},
        combo="C1",
        axes={"Pu": "Fx", "Mu": "Mzz", "Vu": "Fy", "Tu": "Mxx"},
        forces_to_output=["Pu", "Mu", "Vu", "Tu"],
        envelopes=[gfe.EnvelopeRule(action="max", on="Mu", top_n=1)],
    )
    rows = gfe.run_job(adapter, job, "kN", "kN.m", output_units, signs)
    # One row per element.
    assert sorted(r["Element"] for r in rows) == [10, 11]


# ---------------------------------------------------------------------------
# Column selection and unified CSV header
# ---------------------------------------------------------------------------

def test_unified_columns_only_includes_used_forces():
    j_strength = _job_strength()
    j_service = gfe.JobCfg(
        name="svc",
        location={"element": 124, "position": 0.5},
        combo="C2",
        axes={"Ps": "Fx", "Ms": "Mzz"},
        forces_to_output=["Ps", "Ms"],
        envelopes=[gfe.EnvelopeRule("max", "Ms", 1)],
    )
    cols = gfe.unified_columns([j_strength, j_service])
    # Meta block first, then forces in APP_FORCE_ORDER.
    assert cols[:6] == gfe.META_COLUMNS
    assert cols[6:] == ["Pu", "Mu", "Vu", "Tu", "Ps", "Ms"]
    # Vp was deliberately removed from APP_FORCE_ORDER (GSA doesn't model it).
    assert "Vp" not in gfe.APP_FORCE_ORDER


def test_csv_blanks_columns_not_produced_by_a_job(tmp_path):
    rows = [
        {"Job": "A", "Note": "max Mu (rank 1/1)", "Element": 1, "Position": 0.5,
         "Combo": "C1", "Permutation": "Cp1", "Pu": -10.0, "Mu": 500.0,
         "Vu": 20.0, "Tu": 1.0, "Ps": "", "Ms": ""},
        {"Job": "B", "Note": "max Ms (rank 1/1)", "Element": 1, "Position": 0.5,
         "Combo": "C2", "Permutation": "Cp1", "Pu": "", "Mu": "",
         "Vu": "", "Tu": "", "Ps": -8.0, "Ms": 200.0},
    ]
    cols = gfe.META_COLUMNS + ["Pu", "Mu", "Vu", "Tu", "Ps", "Ms"]
    path = tmp_path / "out.csv"
    gfe.write_csv(rows, cols, str(path))
    with open(path, "r", encoding="utf-8") as f:
        content = list(csv.reader(f))
    assert content[0] == cols
    # Strength row: Ps and Ms cells empty.
    assert content[1][cols.index("Ps")] == ""
    assert content[1][cols.index("Ms")] == ""
    # Service row: Pu/Mu/Vu/Tu cells empty.
    assert content[2][cols.index("Pu")] == ""
    assert content[2][cols.index("Mu")] == ""
    assert content[2][cols.index("Vu")] == ""
    assert content[2][cols.index("Tu")] == ""


def test_format_table_smoke():
    rows = [{"Job": "j", "Note": "max Mu (rank 1/1)", "Element": 1,
             "Position": 0.5, "Combo": "C1", "Permutation": "Cp1",
             "Pu": -10.5, "Mu": 500.0, "Vu": 20.1, "Tu": 1.0}]
    cols = gfe.META_COLUMNS + ["Pu", "Mu", "Vu", "Tu"]
    out = gfe.format_table(rows, cols)
    # Includes header line and one data line.
    assert "max Mu (rank 1/1)" in out
    assert "Cp1" in out
    assert "-10.50" in out
    assert "500.00" in out


# ---------------------------------------------------------------------------
# Config loading and validation
# ---------------------------------------------------------------------------

def _write_json(tmp_path, data):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def _minimal_cfg(**overrides):
    cfg = {
        "gsa_file": "fake.gwb",
        "units": {"output_force": "kip", "output_moment": "kip-in"},
        "signs": {
            "axial_compression_positive_in_gsa": False,
            "moment_hogging_positive_in_gsa": True,
        },
        "jobs": [
            {
                "name": "j1",
                "location": {"element": 1, "position": 0.5},
                "combo": "C1",
                "axes": {"Pu": "Fx", "Mu": "Mzz"},
                "forces_to_output": ["Pu", "Mu"],
                "envelopes": [{"action": "max", "on": "Mu", "top_n": 2}],
            }
        ],
    }
    cfg.update(overrides)
    return cfg


def test_load_config_minimal(tmp_path):
    cfg = gfe.load_config(_write_json(tmp_path, _minimal_cfg()))
    assert cfg.gsa_file == "fake.gwb"
    assert cfg.jobs[0].envelopes[0].top_n == 2


def test_load_config_rejects_unknown_force(tmp_path):
    bad = _minimal_cfg()
    bad["jobs"][0]["forces_to_output"] = ["Pu", "Bogus"]
    with pytest.raises(ValueError, match="Bogus"):
        gfe.load_config(_write_json(tmp_path, bad))


def test_load_config_rejects_envelope_on_unselected_force(tmp_path):
    bad = _minimal_cfg()
    bad["jobs"][0]["envelopes"] = [{"action": "max", "on": "Vu", "top_n": 1}]
    with pytest.raises(ValueError, match="Vu"):
        gfe.load_config(_write_json(tmp_path, bad))


def test_load_config_rejects_multiple_location_selectors(tmp_path):
    bad = _minimal_cfg()
    bad["jobs"][0]["location"] = {"element": 1, "group": "G", "position": 0.5}
    with pytest.raises(ValueError, match="exactly one"):
        gfe.load_config(_write_json(tmp_path, bad))


def test_load_config_rejects_bad_action(tmp_path):
    bad = _minimal_cfg()
    bad["jobs"][0]["envelopes"][0]["action"] = "median"
    with pytest.raises(ValueError, match="median"):
        gfe.load_config(_write_json(tmp_path, bad))


def test_load_config_requires_axis_for_each_output_force(tmp_path):
    bad = _minimal_cfg()
    bad["jobs"][0]["forces_to_output"] = ["Pu", "Mu", "Vu"]
    # axes only has Pu, Mu — missing Vu.
    with pytest.raises(ValueError, match="Vu"):
        gfe.load_config(_write_json(tmp_path, bad))


# ---------------------------------------------------------------------------
# CLI entry point: --dry-run-config validates without touching gsapy.
# ---------------------------------------------------------------------------

def test_save_load_config_round_trip(tmp_path):
    cfg = gfe.load_config(_write_json(tmp_path, _minimal_cfg()))
    out = tmp_path / "out.json"
    gfe.save_config(cfg, str(out))
    cfg2 = gfe.load_config(str(out))
    # Compare via dict form so nested dataclasses compare by value.
    assert gfe.config_to_dict(cfg) == gfe.config_to_dict(cfg2)


def test_load_config_strips_underscore_comment_keys(tmp_path):
    cfg = _minimal_cfg()
    cfg["_comment_top"] = "ignore me"
    cfg["units"]["_comment"] = "also ignore"
    cfg["jobs"][0]["_note"] = "and me"
    # Should not raise.
    parsed = gfe.load_config(_write_json(tmp_path, cfg))
    assert parsed.units.output_force == "kip"
    assert parsed.jobs[0].name == "j1"


def test_discover_units_reads_model_unit_names():
    model = MockGsaModel(combos={})
    model._unit_names = {"FORCE": "kN", "LENGTH": "m"}
    adapter = gfe.GsaAdapter(model)
    detected = adapter.discover_units()
    assert detected is not None
    assert detected == ("kN", "kN.m")


def test_discover_units_returns_none_for_unknown_unit():
    model = MockGsaModel(combos={})
    model._unit_names = {"FORCE": "tonnes", "LENGTH": "m"}  # we don't know tonnes
    adapter = gfe.GsaAdapter(model)
    assert adapter.discover_units() is None


def test_discover_units_returns_none_when_missing_keys():
    model = MockGsaModel(combos={})
    model._unit_names = {}  # discovery should fail cleanly
    adapter = gfe.GsaAdapter(model)
    assert adapter.discover_units() is None


def test_real_gsapy_provides_methods_adapter_calls():
    """Pin the real gsapy.GSA surface that GsaAdapter depends on.

    Catches a future gsapy upgrade that renames or removes any of the
    methods we hit. Skips cleanly if gsapy isn't installed (CI without it).
    """
    gsapy = pytest.importorskip("gsapy")
    G = gsapy.GSA
    required = (
        "open", "close",
        "get_elements",
        "get_unit_names",
        "case_num_perm", "case_perm_string",
        "get_1D_elem_resultants",
    )
    for name in required:
        assert hasattr(G, name), (
            f"gsapy.GSA is missing required method {name!r} -- GsaAdapter will "
            f"fail at runtime. Inspect the installed gsapy and update the "
            f"adapter accordingly."
        )


def test_parse_case_id():
    assert gfe._parse_case_id("C1") == ("C", 1)
    assert gfe._parse_case_id("A12") == ("A", 12)
    assert gfe._parse_case_id("l3") == ("L", 3)
    with pytest.raises(ValueError):
        gfe._parse_case_id("123")
    with pytest.raises(ValueError):
        gfe._parse_case_id("Cabc")


def test_main_dry_run(tmp_path, capsys):
    path = _write_json(tmp_path, _minimal_cfg())
    rc = gfe.main([path, "--dry-run-config"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Config OK" in out


# ---------------------------------------------------------------------------
# Backward-compatible config loading & output-unit conversion
# ---------------------------------------------------------------------------

def test_load_config_backward_compat_old_style_units(tmp_path):
    """Old configs that used gsa_force/gsa_moment should still load."""
    cfg = _minimal_cfg()
    cfg["units"] = {"gsa_force": "kN", "gsa_moment": "kN.m"}
    parsed = gfe.load_config(_write_json(tmp_path, cfg))
    # Legacy keys are interpreted as output units for backward compat.
    assert parsed.units.output_force == "kN"
    assert parsed.units.output_moment == "kN.m"


def test_output_unit_conversion_kn_to_lbf():
    """Verify the two-stage conversion: GSA kN -> output lbf."""
    perm = {"perm_id": "C1p1", "Fx": 1.0, "Fy": 0.0, "Fz": 0.0,
            "Mxx": 0.0, "Myy": 0.0, "Mzz": 0.0}
    output_units = gfe.UnitsCfg(output_force="lbf", output_moment="lbf-ft")
    signs = gfe.SignsCfg(axial_compression_positive_in_gsa=False,
                        moment_hogging_positive_in_gsa=False)
    row = gfe.gsa_perm_to_app_row(perm, {"Pu": "Fx"}, ["Pu"],
                                   "kN", "kN.m", output_units, signs)
    # 1 kN = 224.809 lbf
    assert row["Pu"] == pytest.approx(224.809, rel=1e-3)


def test_output_unit_identity_kip_to_kip():
    """GSA in kip, output in kip — factor should be 1.0."""
    perm = {"perm_id": "C1p1", "Fx": 42.0, "Fy": 0.0, "Fz": 0.0,
            "Mxx": 0.0, "Myy": 0.0, "Mzz": 0.0}
    output_units = gfe.UnitsCfg(output_force="kip", output_moment="kip-in")
    signs = gfe.SignsCfg(axial_compression_positive_in_gsa=False,
                        moment_hogging_positive_in_gsa=False)
    row = gfe.gsa_perm_to_app_row(perm, {"Pu": "Fx"}, ["Pu"],
                                   "kip", "kip-in", output_units, signs)
    assert row["Pu"] == 42.0
