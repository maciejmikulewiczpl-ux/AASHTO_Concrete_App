"""Single source of the batch workbook layout: Inputs columns, Settings rows, Results columns.

The Excel template builder (batch/excel/build_template.ps1) reads `python -m batch.columns --json`,
so the sheet order here is the sheet order there.
"""
from __future__ import annotations

import json
import sys
from typing import NamedTuple


class Col(NamedTuple):
    header: str          # text in the sheet's header row (the exchange key)
    key: str             # form element id, or a demand / meta key
    kind: str            # unit kind (length, stress, force, moment, dimensionless) or text / bool / choice
    applies: frozenset   # section types the cell is used for
    required: bool
    choices: tuple | None = None
    default: object = None
    group: str = ""
    note: str = ""


ALL = frozenset({"RECTANGULAR", "T-SECTION", "CIRCULAR"})
RI = frozenset({"RECTANGULAR", "T-SECTION"})
TS = frozenset({"T-SECTION"})
CI = frozenset({"CIRCULAR"})

BAR_TOP = ("0", "3", "4", "5", "6", "7", "8", "9", "10", "11", "14", "18")
BAR_BOT = BAR_TOP[1:]
BAR_TR = ("0", "3", "4", "5", "6", "7", "8", "9", "10", "11")
BAR_CIRC = ("5", "6", "7", "8", "9", "10", "11", "14", "18")

# ASTM grade -> fy (ksi) (ASTM_FY_MAP, index.html ~4139). Blank fy cells use this.
ASTM_FY = {"A615_60": 60.0, "A615_75": 75.0, "A615_80": 80.0, "A706_60": 60.0, "A706_80": 80.0,
           "A1035_100": 100.0}

INPUT_HEADER_ROW = 2      # group row 1, headers row 2, units row 3
INPUT_FIRST_DATA_ROW = 4
SETTINGS_FIRST_ROW = 2    # header row 1: Setting | Value | Units | Note
RESULTS_HEADER_ROW = 2
RESULTS_FIRST_DATA_ROW = 4

DEMAND_KEYS = ("Pu", "Mu", "Vu", "Tu", "Ps", "Ms")


def _c(header, key, kind, applies, required, choices=None, default=None, group="", note=""):
    return Col(header, key, kind, applies, required, choices, default, group, note)


INPUT_COLUMNS: list[Col] = [
    _c("Section ID", "section_id", "text", ALL, True, group="Section",
       note="Same ID on several rows = several load cases of one section"),
    _c("Section type", "sectionType", "choice", ALL, True, ("RECTANGULAR", "T-SECTION", "CIRCULAR"), group="Section"),
    _c("Member type", "memberType", "choice", RI, False, ("BEAM", "SLAB"), "BEAM", group="Section"),
    _c("f'c", "fc", "stress", ALL, True, group="Materials"),
    _c("fy", "fy", "stress", ALL, False, group="Materials", note="Blank = from ASTM spec (Settings)"),
    _c("fy,trans", "fy_trans", "stress", ALL, False, group="Materials", note="Blank = from ASTM spec (Settings)"),
    _c("b", "b_flange", "length", RI, True, group="Rect / I geometry", note="Width (rectangular) or top flange width (I)"),
    _c("h", "h_total", "length", RI, True, group="Rect / I geometry"),
    _c("bw", "b_web", "length", TS, True, group="Rect / I geometry"),
    _c("hf top", "hf_top", "length", TS, True, group="Rect / I geometry"),
    _c("hf bot", "hf_bot", "length", TS, True, group="Rect / I geometry"),
    _c("Cover", "cover", "length", ALL, True, group="Rect / I geometry", note="Clear cover to the stirrup / hoop"),
    _c("Top bar", "top_bar", "choice", RI, False, BAR_TOP, "0", group="Longitudinal (rect / I)", note="0 = none"),
    _c("Top mode", "bar_mode_top", "choice", RI, False, ("count", "spacing"), "count", group="Longitudinal (rect / I)"),
    _c("Top count / spacing", "n_bars_top", "dimensionless", RI, False, default="0", group="Longitudinal (rect / I)",
       note="Number of bars, or spacing in inches (always inches) in spacing mode"),
    _c("Bottom bar", "bot_bar", "choice", RI, True, BAR_BOT, group="Longitudinal (rect / I)"),
    _c("Bottom mode", "bar_mode_bot", "choice", RI, False, ("count", "spacing"), "count", group="Longitudinal (rect / I)"),
    _c("Bottom count / spacing", "n_bars_bot", "dimensionless", RI, True, group="Longitudinal (rect / I)",
       note="Number of bars, or spacing in inches (always inches) in spacing mode"),
    _c("D", "circ_D", "length", CI, True, group="Circular"),
    _c("Ring 1 bar", "circ_bar1", "choice", CI, True, BAR_CIRC, group="Circular"),
    _c("Ring 1 count", "circ_n1", "dimensionless", CI, True, group="Circular"),
    _c("Ring 1 bundle", "circ_bundle1", "choice", CI, False, ("1", "2", "3"), "1", group="Circular"),
    _c("Ring 2", "circ_ring2", "bool", CI, False, default=False, group="Circular"),
    _c("Ring 2 bar", "circ_bar2", "choice", CI, False, BAR_CIRC, "8", group="Circular"),
    _c("Ring 2 count", "circ_n2", "dimensionless", CI, False, default="0", group="Circular"),
    _c("Ring 2 bundle", "circ_bundle2", "choice", CI, False, ("1", "2", "3"), "1", group="Circular"),
    _c("Ring 2 diameter", "circ_Dr2", "length", CI, False, default="0", group="Circular",
       note="Bar-centre ring diameter of ring 2"),
    _c("Transverse type", "circ_trans_type", "choice", CI, False, ("hoop", "spiral"), "hoop", group="Circular"),
    _c("Hoop closure", "circ_hoop_closure", "choice", CI, False, ("lap", "hooked"), "hooked", group="Circular",
       note="hooked = welded / mechanical / hooks around bars"),
    _c("Cross-tie legs", "circ_tie_legs", "dimensionless", CI, False, default="0", group="Circular"),
    _c("Cross-tie bar", "circ_tie_bar", "choice", CI, False, ("3", "4", "5", "6", "7", "8"), "4", group="Circular"),
    _c("Stirrup / hoop bar", "shear_bar", "choice", ALL, True, BAR_TR, group="Transverse", note="0 = none"),
    _c("Stirrup legs", "shear_legs", "dimensionless", RI, False, default="2", group="Transverse"),
    _c("Spacing s", "shear_s", "length", ALL, True, group="Transverse"),
    _c("Add. torsion bar", "at_add_bar", "choice", RI, False, BAR_TR, "0", group="Transverse", note="0 = none"),
    _c("Add. torsion spacing", "at_add_s", "length", RI, False, default="12", group="Transverse"),
    _c("Pu", "Pu", "force", ALL, False, default="0", group="Demands", note="Compression negative (app convention)"),
    _c("Mu", "Mu", "moment", ALL, False, default="0", group="Demands", note="Sagging positive"),
    _c("Vu", "Vu", "force", ALL, False, default="0", group="Demands"),
    _c("Tu", "Tu", "moment", ALL, False, default="0", group="Demands"),
    _c("Ps", "Ps", "force", ALL, False, default="0", group="Demands", note="Service axial, tension positive"),
    _c("Ms", "Ms", "moment", ALL, False, default="0", group="Demands", note="Service moment"),
]

SETTINGS_ROWS: list[Col] = [
    _c("Force unit", "unit_force", "choice", ALL, False, ("kip", "lbf"), "kip", group="Units"),
    _c("Length unit", "unit_length", "choice", ALL, False, ("in", "ft"), "in", group="Units"),
    _c("Code edition", "codeEdition", "choice", ALL, False, ("CA", "FED"), "CA", group="Code"),
    _c("Longitudinal reinforcement ASTM", "astm_spec", "choice", ALL, False,
       ("A615_60", "A615_75", "A615_80", "A706_60", "A706_80", "A1035_100"), "A615_60", group="Materials",
       note="Sets fy / fy,trans where the Inputs cells are blank"),
    _c("Concrete type", "concType", "choice", ALL, False, ("NORMAL",), "NORMAL", group="Materials"),
    _c("Es", "Es", "stress", ALL, False, default="29000", group="Materials"),
    _c("Aggregate size ag", "ag", "length", ALL, False, default="0.75", group="Materials"),
    _c("Concrete density modification λ", "lambda", "dimensionless", ALL, False, default="1", group="Materials"),
    _c("Correction factor K1", "K1", "dimensionless", ALL, False, default="1.0", group="Materials"),
    _c("Override unit weight wc", "wc_ovr", "bool", ALL, False, default=False, group="Materials"),
    _c("Unit weight wc", "wc", "unit_weight", ALL, False, default="0.145", group="Materials",
       note="Used only when the override is TRUE"),
    _c("φ for shear (φv)", "phi_v", "dimensionless", ALL, False, default="0.9", group="Factors"),
    _c("Exposure factor γe", "gamma_e", "choice", ALL, False, ("1.00", "0.75"), "0.75", group="Factors"),
    _c("Crack-control mode", "crack_mode", "choice", ALL, False, ("capped", "actual"), "capped", group="Service"),
]
_FACTOR_LABELS = {"phi_v_f": "φv", "phi_f_f": "φf", "phi_c_f": "φc", "gamma_e_f": "γe", "lambda_f": "λ",
                  "lambda_duct_f": "λduct", "gamma1_f": "γ1", "gamma2_f": "γ2", "gamma3_f": "γ3",
                  "alpha1_f": "α1", "beta1_f": "β1"}
_FACTOR_DEFAULTS = {"phi_c_f": "0.75", "gamma1_f": "1.6", "gamma2_f": "1.1"}
for _k, _lab in _FACTOR_LABELS.items():
    SETTINGS_ROWS.append(_c(f"Override {_lab}", _k + "_ovr", "bool", ALL, False, default=False, group="Factor overrides"))
    SETTINGS_ROWS.append(_c(f"{_lab} value", _k + "_ovr_val", "dimensionless", ALL, False,
                            default=_FACTOR_DEFAULTS.get(_k, ""), group="Factor overrides"))
SETTINGS_ROWS += [
    _c("Shear capacity for D/C", "shear_method", "choice", ALL, False, ("gp", "simp", "b5"), "gp", group="Run",
       note="gp = General Procedure, simp = Simplified, b5 = Appendix B5 (as the app's D/C selector)"),
    _c("M-φ concrete model", "mphi_model", "choice", ALL, False, ("service", "confined", "sgs"), "service",
       group="Run", note="sgs = AASHTO Seismic preset (values unverified, OPEN_VERIFICATION_ITEMS MP2)"),
    _c("M-φ expected concrete", "mphi_exp_c", "bool", ALL, False, default=False, group="Run"),
    _c("M-φ expected steel", "mphi_exp_s", "bool", ALL, False, default=False, group="Run"),
    _c("Project file", "project_path", "text", ALL, False, default="", group="Run",
       note="Blank = <workbook name>.aashto.json next to the workbook"),
    _c("Overwrite project file", "overwrite_project", "bool", ALL, False, default=True, group="Run"),
    _c("Engine exe", "engine_exe", "text", ALL, False, default="", group="Run",
       note="Blank = AASHTO_Batch.exe next to the workbook (read by the macro only)"),
]

RUN_KEYS = ("shear_method", "mphi_model", "mphi_exp_c", "mphi_exp_s", "project_path", "overwrite_project",
            "engine_exe", "unit_force", "unit_length")

class RCol(NamedTuple):
    header: str
    source: str   # dotted path into {"res", "row", "mphi", "calc"} (see batch.runner)
    kind: str     # unit kind for display conversion, "fixed:<label>" (no conversion), or "text"
    group: str = ""


def _r(group, *cols):
    return [RCol(h, s, k, group) for h, s, k in cols]


RESULT_COLUMNS: list[RCol] = (
    _r("Row", ("Section ID", "calc.section_id", "text"), ("Input row", "calc.input_row", "text"),
       ("Status", "calc.status", "text"), ("Message", "calc.message", "text"))
    + _r("Flexure",
         ("Mr", "row.Mr", "moment"), ("Mn", "res.flexure.Mn", "moment"), ("φf", "res.flexure.phi_f", "dimensionless"),
         ("c", "res.flexure.c", "length"), ("a", "res.flexure.a", "length"), ("ds", "res.flexure.ds", "length"),
         ("dt", "res.flexure.dt", "length"), ("εt", "res.flexure.eps_t", "dimensionless"),
         ("As (tension)", "res.flexure.As", "area"), ("Mcr", "res.flexure.Mcr", "moment"),
         ("Min. flexural steel OK", "res.flexure.min_flex_ok", "text"),
         ("Mr at Pu", "res.flexure.Mr_atPu", "moment"), ("D/C flexure", "calc.dc_M", "dimensionless"),
         ("Flexure status", "row.flexStatus", "text"))
    + _r("Shear",
         ("Shear method", "calc.shear_method", "text"), ("Vr (selected)", "calc.Vr", "force"),
         ("Vr simplified", "row.Vr1", "force"), ("Vr general", "row.Vr2", "force"), ("Vr B5", "row.Vr3", "force"),
         ("dv", "res.shear.dv", "length"), ("bv", "res.shear.bv", "length"),
         ("β", "calc.beta", "dimensionless"), ("θ", "calc.theta", "fixed:deg"),
         ("Vc", "calc.Vc", "force"), ("Vs", "calc.Vs", "force"), ("εs", "res.shear.eps_s", "dimensionless"),
         ("Vn,max", "res.shear.Vnmax", "force"), ("Av,min", "res.shear.Av_min", "area"),
         ("Has min. Av", "res.shear.has_min_av", "text"), ("s,max", "res.shear.s_max_sh", "length"),
         ("D/C shear", "calc.dc_V", "dimensionless"),
         ("Long. steel D/C (V)", "calc.long_dc", "dimensionless"), ("Long. steel OK (V)", "calc.long_ok", "text"),
         ("Shear status (engine, GP)", "row.shearStatus", "text"))
    + _r("Torsion",
         ("Torsion considered", "res.torsion.consider", "text"), ("Tcr", "res.torsion.Tcr", "moment"),
         ("Torsion threshold", "res.torsion.thresh", "moment"), ("Tr", "res.torsion.Tr", "moment"),
         ("At/s design", "res.torsion.At_s_design", "area_per_length"),
         ("Long. V+T demand","res.torsion.long_dem_comb", "force"),
         ("Long. V+T capacity", "res.torsion.long_cap_val", "force"),
         ("Long. V+T OK", "res.torsion.long_comb_ok", "text"), ("D/C torsion", "calc.dc_T", "dimensionless"))
    + _r("Crack control / service",
         ("fss", "res.flexure.fss_used", "stress"), ("s,max crack", "res.flexure.s_crack", "length"),
         ("s actual", "res.flexure.s_crack_actual", "length"), ("Crack status", "row.crackStatus", "text"),
         ("Icr", "res.flexure.Icr", "fixed:in⁴"), ("Ieff", "res.flexure.Ieff", "fixed:in⁴"),
         ("Ig", "res.flexure.Ig", "fixed:in⁴"))
    + _r("Moment-curvature",
         ("M-φ model", "mphi.model", "text"),
         ("Ieff (M-φ, at Ms)", "mphi.service.Ieff", "fixed:in⁴"),
         ("Ieff/Ig (M-φ, at Ms)", "calc.mphi_Ieff_Ig_service", "dimensionless"),
         ("EI at Ms", "mphi.service.EI", "fixed:kip-in²"),
         ("My (first yield)", "mphi.first_yield.M", "moment"), ("φy (first yield)", "mphi.first_yield.phi", "fixed:1/in"),
         ("Mp (idealised)", "mphi.idealised.Mp", "moment"), ("φy (idealised)", "mphi.idealised.phi_y", "fixed:1/in"),
         ("EI idealised", "mphi.idealised.EI", "fixed:kip-in²"),
         ("φu", "mphi.ultimate.phi", "fixed:1/in"), ("Ultimate limit", "mphi.ultimate.failure", "text"),
         ("μφ", "mphi.idealised.mu_phi", "dimensionless"), ("Mcr (M-φ)", "mphi.cracking.M", "moment"),
         ("M-φ note", "calc.mphi_note", "text"))
)

UNIT_LABELS = {  # unitLabel (index.html ~4186), keyed by force|length
    "force": {"kip|in": "kip", "kip|ft": "kip", "lbf|in": "lbf", "lbf|ft": "lbf"},
    "length": {"kip|in": "in", "kip|ft": "ft", "lbf|in": "in", "lbf|ft": "ft"},
    "stress": {"kip|in": "ksi", "kip|ft": "ksf", "lbf|in": "psi", "lbf|ft": "psf"},
    "moment": {"kip|in": "kip-in", "kip|ft": "kip-ft", "lbf|in": "lbf-in", "lbf|ft": "lbf-ft"},
    "area": {"kip|in": "in²", "kip|ft": "ft²", "lbf|in": "in²", "lbf|ft": "ft²"},
    "area_per_length": {"kip|in": "in²/in", "kip|ft": "ft²/ft", "lbf|in": "in²/in", "lbf|ft": "ft²/ft"},
    "unit_weight": {"kip|in": "kcf", "kip|ft": "kcf", "lbf|in": "pcf", "lbf|ft": "pcf"},
}


def unit_label(kind: str, units: dict) -> str:
    if kind.startswith("fixed:"):
        return kind[6:]
    return UNIT_LABELS.get(kind, {}).get(f"{units['force']}|{units['length']}", "")


def _col_dict(c) -> dict:
    d = c._asdict()
    if "applies" in d:
        d["applies"] = sorted(d["applies"])
    return d


def columns_json() -> str:
    return json.dumps({
        "input": [_col_dict(c) for c in INPUT_COLUMNS],
        "settings": [_col_dict(c) for c in SETTINGS_ROWS],
        "results": [_col_dict(c) for c in RESULT_COLUMNS],
        "unit_labels": UNIT_LABELS,
        "layout": {"input_header_row": INPUT_HEADER_ROW, "input_first_data_row": INPUT_FIRST_DATA_ROW,
                   "settings_first_row": SETTINGS_FIRST_ROW, "results_header_row": RESULTS_HEADER_ROW,
                   "results_first_data_row": RESULTS_FIRST_DATA_ROW},
    }, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    if "--json" in sys.argv:
        sys.stdout.reconfigure(encoding="utf-8")
        print(columns_json())
