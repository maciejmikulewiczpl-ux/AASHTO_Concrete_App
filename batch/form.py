"""Field model of the app's input form, mirrored from index.html.

A "form" is a dict keyed by the DOM element ids that gatherInputs() reads, holding the values the
user would see in the page (display units; strings for inputs / selects, bool for checkboxes).
Every literal here is guarded by tests/test_batch_form.py against drift from index.html.
"""
from __future__ import annotations

# Default value of each element as a new page shows it (index.html element defaults).
FORM_DEFAULTS: dict[str, str | bool] = {
    # Materials
    "fc": "5", "fy": "60", "fy_trans": "60", "Es": "29000", "fpu": "270", "Ept": "28500",
    "ag": "0.75", "lambda": "1", "phi_v": "0.9", "gamma_e": "0.75", "K1": "1.0",
    "wc": "0.145", "wc_ovr": False, "Ec": "0", "Ec_ovr": False, "fpy": "243", "fpy_ovr": False,
    "ecl": "0.002", "ecl_ovr": False, "etl": "0.005", "etl_ovr": False,
    "fy_ovr": False, "fy_trans_ovr": False,
    "codeEdition": "CA", "sectionClass": "NP", "astm_spec": "A615_60", "concType": "NORMAL",
    # Section
    "sectionType": "RECTANGULAR", "memberType": "BEAM",
    "b_flange": "16.38", "h_total": "27.5", "b_web": "12", "hf_top": "8", "hf_bot": "12", "cover": "2",
    # Longitudinal (rect / I)
    "top_bar": "7", "bar_mode_top": "count", "n_bars_top": "5",
    "bot_bar": "7", "bar_mode_bot": "count", "n_bars_bot": "5",
    "d_top_ovr": False, "d_top_override": "", "d_bot_ovr": False, "d_bot_override": "",
    # Transverse
    "shear_bar": "4", "shear_legs": "2", "shear_s": "4", "at_add_bar": "0", "at_add_s": "12",
    # Circular
    "circ_D": "36", "circ_bar1": "9", "circ_n1": "12", "circ_bundle1": "1",
    "circ_ring2": False, "circ_bar2": "8", "circ_n2": "8", "circ_bundle2": "1", "circ_Dr2": "20",
    "circ_trans_type": "hoop", "circ_hoop_closure": "hooked", "circ_tie_legs": "0", "circ_tie_bar": "4",
    # Prestressing (read by gatherInputs; not used by the batch, kept at defaults)
    "n_strands": "10", "strand_area": "0.217", "dp_input": "15.5", "fpe_input": "0", "duct_dia": "6",
    "pt_bonded": "true", "pt_temp_comp_case": "general", "pt_temp_tens_case": "bonded",
    "pt_srv3_tens_case": "moderate", "pt_phi_w": "1.00", "pt_fci_chk": "4.0", "pt_fci": "4.0",
    # Service
    "crack_mode": "capped",
}

# data-factor names of the .factor-ovr-cb checkboxes, in page order (index.html ~510-540).
FACTOR_KEYS: list[str] = ["phi_v_f", "phi_f_f", "phi_c_f", "gamma_e_f", "lambda_f", "lambda_duct_f",
                          "gamma1_f", "gamma2_f", "gamma3_f", "alpha1_f", "beta1_f"]
_FACTOR_VALS = {"phi_c_f": "0.75", "gamma1_f": "1.6", "gamma2_f": "1.1"}
for _f in FACTOR_KEYS:
    FORM_DEFAULTS[_f + "_ovr"] = False
    FORM_DEFAULTS[_f + "_ovr_val"] = _FACTOR_VALS.get(_f, "")

# INPUT_FIELD_KINDS (index.html ~4228): which numeric fields carry units.
FIELD_KINDS: dict[str, str] = {
    "b_flange": "length", "h_total": "length", "b_web": "length",
    "hf_top": "length", "hf_bot": "length", "cover": "length",
    "circ_D": "length", "circ_Dr2": "length",
    "ag": "length",
    "fc": "stress", "fy": "stress", "fy_trans": "stress",
    "Ec": "stress", "Es": "stress", "fpu": "stress", "fpy": "stress",
    "Ept": "stress", "fpe": "stress", "fci": "stress",
    "wc": "unit_weight",
    "shear_s": "length", "s_torsion": "length", "at_add_s": "length", "duct_dia": "length",
    "pt_fpj": "stress", "pt_fpe": "stress",
    "delta_set": "length", "pt_H": "length",
    "pt_M_sw": "moment",
    "strand_area": "area",
    "dp_input": "length",
    "d_top_override": "length", "d_bot_override": "length",
}

# Bar table (index.html ~1156): diameter d (in), area a (in^2).
BARS: dict[int, dict[str, float]] = {
    2: {"d": 0.250, "a": 0.05}, 3: {"d": 0.375, "a": 0.11}, 4: {"d": 0.500, "a": 0.20},
    5: {"d": 0.625, "a": 0.31}, 6: {"d": 0.750, "a": 0.44}, 7: {"d": 0.875, "a": 0.60},
    8: {"d": 1.000, "a": 0.79}, 9: {"d": 1.128, "a": 1.00}, 10: {"d": 1.270, "a": 1.27},
    11: {"d": 1.410, "a": 1.56}, 14: {"d": 1.693, "a": 2.25}, 18: {"d": 2.257, "a": 4.00},
}

DEFAULT_UNITS = {"force": "kip", "length": "in"}


def unit_factor(kind: str, units: dict) -> float:
    """Engine value x factor = display value (unitFactor, index.html ~4178)."""
    f = 1000.0 if units.get("force") == "lbf" else 1.0
    l = 1.0 / 12.0 if units.get("length") == "ft" else 1.0
    return {"force": f, "length": l, "stress": f / (l * l), "moment": f * l, "area": l * l,
            "force_per_length": f / l, "area_per_length": l, "unit_weight": f,
            "dimensionless": 1.0}.get(kind, 1.0)


def from_engine(v: float, kind: str, units: dict) -> float:
    return v * unit_factor(kind, units)


def to_engine(v: float, kind: str, units: dict) -> float:
    return v / unit_factor(kind, units)
