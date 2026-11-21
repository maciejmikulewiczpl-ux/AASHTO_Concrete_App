"""Section state and .aashto.json project file, in the shape index.html saves them.

state_from_form mirrors saveCurrentSectionState() (index.html ~1250-1366) as it runs right after a
Calculate: auto-calculated fields (wc, Ec, fpy, eps_cl, eps_tl, d_top, d_bot) hold their computed
values, exactly as the page would store them. Field values are in display units (state.units).
"""
from __future__ import annotations

import copy
import json
import os

from batch.form import BARS, from_engine
from batch.inputs import _Form, bars_from_spacing, inputs_from_form, js_parse_float, js_parse_int

# getDefaultSectionState().ptDesign (index.html ~1232) and the optParams defaults (~1186).
DEFAULT_PT_DESIGN = {
    "parabolas": [
        {"xL": 0, "yL": 8, "xM": 50.4, "yM": 24, "xR": 113.4, "yR": 4},
        {"xL": 113.4, "yL": 4, "xM": 126, "yM": 3, "xR": 142.8, "yR": 4.5},
        {"xL": 142.8, "yL": 4.5, "xM": 210, "yM": 24, "xR": 277.2, "yR": 4.5},
        {"xL": 277.2, "yL": 4.5, "xM": 294, "yM": 3, "xR": 305.8, "yR": 4},
        {"xL": 305.8, "yL": 4, "xM": 364.8, "yM": 24, "xR": 412, "yR": 8},
    ],
    "lossParams": {"fpj": 202.5, "jack_end": "both", "mu": 0.20, "kappa": 0.0002,
                   "delta_set": 0.375, "N_tendons": 1, "Msw": 0, "H": 70, "fci": 4.0},
}
DEFAULT_OPT_PARAMS = {
    "tgt": {"mpos": 0.9, "mneg": 0.9, "v": 0.9, "t": 0.9},
    "flex": {"minSpacing": 1.5, "rowSpacing": 1.5, "minBar": 4, "maxBar": 11, "maxRows": 3},
    "stir": {"minBar": 3, "maxBar": 6, "sMin": 3, "sMax": 18, "sStep": 1, "maxLegs": 4},
}
# Demand-row field kinds (DEMAND_ROW_KINDS, index.html ~4255) for engine -> display conversion.
DEMAND_KINDS = {"Pu": "force", "Vu": "force", "Vp": "force", "Ps": "force",
                "Mu": "moment", "Tu": "moment", "Ms": "moment"}


def _fixed(v: float, n: int) -> str:
    return f"{v:.{n}f}"


def _d_for_width_lookup(F: _Form, side: str) -> float:
    """dForWidthLookup (index.html ~8560): note `parseInt(shear_bar)||4` (None -> #4 here)."""
    cover = F.VE("cover")
    shN = js_parse_int(F.raw("shear_bar")) or 4
    db_stir = BARS.get(shN, BARS[4])["d"]
    if side == "top":
        if F.checked("d_top_ovr"):
            v = F.VE("d_top_override")
            if v > 0:
                return v
        bar = BARS.get(js_parse_int(F.raw("top_bar")) or 0)
        return cover + db_stir + bar["d"] / 2 if bar else cover
    if F.checked("d_bot_ovr"):
        v = F.VE("d_bot_override")
        if v > 0:
            return v
    bar = BARS.get(js_parse_int(F.raw("bot_bar")) or 7, BARS[7])
    return F.VE("h_total") - cover - db_stir - bar["d"] / 2


def _after_calculate(form: dict, units: dict) -> dict:
    """The form as the page shows it after gatherInputs() wrote its auto-calculated fields back."""
    f = dict(form)
    inp = inputs_from_form(form, units)
    F = _Form(form, units)
    if not F.checked("wc_ovr"):
        f["wc"] = _fixed(from_engine(inp["wc"], "unit_weight", units), 3)
    if not F.checked("Ec_ovr"):
        f["Ec"] = _fixed(from_engine(inp["Ec"], "stress", units), 1)
    if not F.checked("fpy_ovr"):
        f["fpy"] = _fixed(from_engine(inp["fpy"], "stress", units), 1)
    if not F.checked("ecl_ovr"):
        f["ecl"] = _fixed(inp["ecl"], 4)
    if not F.checked("etl_ovr"):
        f["etl"] = _fixed(inp["etl"], 4)
    if not F.checked("d_top_ovr"):
        f["d_top_override"] = _fixed(from_engine(inp["d_top"], "length", units), 4)
    if not F.checked("d_bot_ovr"):
        f["d_bot_override"] = _fixed(from_engine(inp["d_bot"], "length", units), 4)
    return f


def state_from_form(form: dict, demand_rows: list[dict], units: dict) -> dict:
    """Section state for one section. demand_rows are in ENGINE units (kip, kip-in); the state
    stores them in display units, as the page does."""
    f = _after_calculate(form, units)
    F = _Form(f, units)
    V, raw, chk = F.V, F.raw, F.checked

    def bars(side):
        if raw(f"bar_mode_{side}") == "spacing":
            return bars_from_spacing(V(f"n_bars_{side}"), _d_for_width_lookup(F, side), f, units)
        return V(f"n_bars_{side}")

    inputs = {
        "fc": V("fc"), "fy": V("fy"), "fy_trans": V("fy_trans"), "Es": V("Es"), "fpu": V("fpu"),
        "Ept": V("Ept"), "ag": V("ag"), "lam": V("lambda"), "phi_v": V("phi_v"),
        "gamma_e": js_parse_float(raw("gamma_e")),
        "codeEdition": raw("codeEdition"), "sectionClass": raw("sectionClass"),
        "astm_spec": raw("astm_spec"), "concType": raw("concType"),
        "wc_ovr": chk("wc_ovr"), "wc_val": raw("wc"), "K1_val": raw("K1"),
        "secType": raw("sectionType"), "memberType": raw("memberType") or "BEAM",
        "b": V("b_flange"), "h": V("h_total"), "bw_input": V("b_web"), "hf_top": V("hf_top"),
        "hf_bot": V("hf_bot"), "cover": V("cover"),
        "barN_top": js_parse_int(raw("top_bar")), "nBars_top": bars("top"),
        "mode_top": raw("bar_mode_top") or "count",
        "spacing_top": V("n_bars_top") if raw("bar_mode_top") == "spacing" else None,
        "barN_bot": js_parse_int(raw("bot_bar")), "nBars_bot": bars("bot"),
        "mode_bot": raw("bar_mode_bot") or "count",
        "spacing_bot": V("n_bars_bot") if raw("bar_mode_bot") == "spacing" else None,
        "d_top_ovr": chk("d_top_ovr"), "d_bot_ovr": chk("d_bot_ovr"), "Ec_ovr": chk("Ec_ovr"),
        "fpy_ovr": chk("fpy_ovr"), "ecl_ovr": chk("ecl_ovr"), "etl_ovr": chk("etl_ovr"),
        "fy_ovr": chk("fy_ovr"), "fy_trans_ovr": chk("fy_trans_ovr"),
        "fy_val": raw("fy"), "fy_trans_val": raw("fy_trans"), "Ec_val": raw("Ec"),
        "fpy_val": raw("fpy"), "ecl_val": raw("ecl"), "etl_val": raw("etl"),
        "d_top_val": raw("d_top_override"), "d_bot_val": raw("d_bot_override"),
        "nStrands": V("n_strands"), "strand_area": V("strand_area"), "dp_mode": raw("dp_mode"),
        "dp_input": V("dp_input"), "fpe_mode": raw("fpe_mode"), "fpe_input": V("fpe_input"),
        "duct_dia": V("duct_dia"),
        "shN": js_parse_int(raw("shear_bar")), "shear_legs": V("shear_legs"), "shear_s": V("shear_s"),
        "at_add_bar_N": js_parse_int(raw("at_add_bar")), "at_add_s": V("at_add_s"),
        "circ_D": V("circ_D"), "circ_bar1": js_parse_int(raw("circ_bar1")), "circ_n1": V("circ_n1"),
        "circ_bundle1": js_parse_int(raw("circ_bundle1")), "circ_ring2": chk("circ_ring2"),
        "circ_bar2": js_parse_int(raw("circ_bar2")), "circ_n2": V("circ_n2"),
        "circ_bundle2": js_parse_int(raw("circ_bundle2")), "circ_Dr2": V("circ_Dr2"),
        "circ_trans_type": raw("circ_trans_type"), "circ_hoop_closure": raw("circ_hoop_closure"),
        "circ_tie_legs": V("circ_tie_legs"), "circ_tie_bar": js_parse_int(raw("circ_tie_bar")),
    }
    rows = []
    for d in demand_rows:
        row = {k: from_engine(float(d.get(k) or 0), kind, units) for k, kind in DEMAND_KINDS.items()}
        row.update({"x": None, "dp": None, "fpe": None, "ptMode": "layout", "loadCase": "service_I_full"})
        rows.append(row)
    return {"units": dict(units), "inputs": inputs, "demandRows": rows,
            "ptDesign": copy.deepcopy(DEFAULT_PT_DESIGN), "mrData": {"top": None, "bot": None}}


def build_project(states: dict[str, dict], units: dict, run_options: dict) -> dict:
    """Project dict as saveProject() writes it, plus runOptions (shear method, M-phi options)."""
    return {"version": 1, "activeSection": next(iter(states), None), "sections": states,
            "optParams": copy.deepcopy(DEFAULT_OPT_PARAMS), "displayUnits": dict(units),
            "runOptions": run_options}


def write_project(path: str, project: dict, overwrite: bool) -> str:
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(f"Project file already exists: {path}")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(project, fh, indent=2)
    return path
