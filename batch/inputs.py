"""Python port of the app's gatherInputs() (index.html ~4436) and its helpers.

inputs_from_form(form, units) returns exactly the raw-input dict the app sends to
calc_engine.calculate_all for the same form, with no multi-row rebar (mrData empty) and no
PT layout result (window._ptResult unset). Pinned line by line against the real JavaScript by
tests/test_batch_inputs_parity.py — keep the JS quirks; do not "fix" them here.
"""
from __future__ import annotations

import math
import re

from batch.form import BARS, FACTOR_KEYS, FIELD_KINDS, to_engine

_FLOAT = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")
_INT = re.compile(r"^\s*([+-]?\d+)")
NAN = float("nan")


def js_parse_float(v) -> float:
    """parseFloat: leading number of the string, NaN if none."""
    if isinstance(v, bool):
        return NAN
    if isinstance(v, (int, float)):
        return float(v)
    m = _FLOAT.match(str(v))
    return float(m.group(1)) if m else NAN


def js_parse_int(v):
    """parseInt: leading integer, None for NaN."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) if math.isfinite(v) else None
    m = _INT.match(str(v))
    return int(m.group(1)) if m else None


def js_round(x: float) -> int:
    """Math.round: half up (towards +infinity)."""
    return math.floor(x + 0.5)


def _or(v, dflt):
    """JS `v || dflt` for numbers (0, NaN, None are falsy)."""
    return dflt if (v is None or v == 0 or (isinstance(v, float) and math.isnan(v))) else v


class _Form:
    def __init__(self, form: dict, units: dict):
        self.f, self.u = form, units

    def raw(self, k):
        return self.f.get(k, "")

    def checked(self, k) -> bool:
        return self.f.get(k) is True

    def V(self, k) -> float:
        v = js_parse_float(self.raw(k))
        return 0.0 if math.isnan(v) else v

    def VE(self, k) -> float:
        v, kind = self.V(k), FIELD_KINDS.get(k)
        return to_engine(v, kind, self.u) if kind and kind != "dimensionless" else v

    def pickF(self, k, dflt):
        if k not in self.f:
            return dflt
        v = js_parse_float(self.raw(k))
        return dflt if math.isnan(v) else v


def compute_wc(fc: float) -> float:
    return 0.145 if fc <= 5 else 0.140 + 0.001 * fc


def compute_ec_aashto(fc: float, K1: float, wc: float) -> float:
    return 120000 * K1 * wc * wc * math.pow(fc, 0.33)


def _width_at_depth(F: _Form, d: float) -> float:
    b = F.VE("b_flange")
    if F.raw("sectionType") != "T-SECTION":
        return b
    bw = _or(F.VE("b_web"), b)
    hf_top, hf_bot, h = F.VE("hf_top"), F.VE("hf_bot"), F.VE("h_total")
    if d < hf_top or d > h - hf_bot:
        return b
    return bw


def bars_from_spacing(spacing: float, d: float, form: dict, units: dict) -> int:
    """barsFromSpacing / clearWidthAt (index.html ~8543). Spacing is always inches."""
    F = _Form(form, units)
    shN = _or(js_parse_int(F.raw("shear_bar")), 4)
    db_stir = BARS.get(shN, BARS[4])["d"]
    clear_w = max(_width_at_depth(F, d) - 2 * F.VE("cover") - 2 * db_stir, 0)
    return max(math.floor(clear_w / spacing) + 1, 1) if spacing > 0 else 1


def circ_params(form: dict, units: dict) -> dict:
    """circParamsFromDOM (index.html ~8226)."""
    F = _Form(form, units)
    shN = js_parse_int(F.raw("shear_bar"))
    tr = None if shN == 0 else BARS.get(shN, BARS[4])
    return {"D": F.VE("circ_D"), "cover": F.VE("cover"), "d_tr": tr["d"] if tr else 0,
            "bar1": _or(js_parse_int(F.raw("circ_bar1")), 9), "n1": F.V("circ_n1"),
            "bundle1": _or(js_parse_int(F.raw("circ_bundle1")), 1),
            "ring2": F.checked("circ_ring2"),
            "bar2": _or(js_parse_int(F.raw("circ_bar2")), 8), "n2": F.V("circ_n2"),
            "bundle2": _or(js_parse_int(F.raw("circ_bundle2")), 1), "Dr2": F.VE("circ_Dr2"),
            "trans": F.raw("circ_trans_type"), "closure": F.raw("circ_hoop_closure"), "shN": shN,
            "s": F.VE("shear_s"),
            "tie_legs": max(0, js_round(_or(F.V("circ_tie_legs"), 0))),
            "tie_bar": _or(js_parse_int(F.raw("circ_tie_bar")), 4)}


def circ_payload(p: dict) -> dict:
    """circPayload (index.html ~8251): circular keys merged over the rect-style payload."""
    return {"secType": "CIRCULAR", "memberType": "BEAM", "D": p["D"], "b": p["D"], "h": p["D"],
            "bw_input": p["D"], "hf_top": 0, "hf_bot": 0,
            "circ_bar1": p["bar1"], "circ_n1": js_round(_or(p["n1"], 0)), "circ_bundle1": p["bundle1"],
            "circ_ring2": bool(p["ring2"]), "circ_bar2": p["bar2"], "circ_n2": js_round(_or(p["n2"], 0)),
            "circ_bundle2": p["bundle2"], "circ_Dr2": p["Dr2"],
            "circ_trans_type": p["trans"], "circ_hoop_closure": p["closure"] or "lap",
            "circ_tie_legs": p["tie_legs"], "circ_tie_bar": p["tie_bar"],
            "shear_legs": 0 if p["shN"] == 0 else 2, "at_add_bar_N": 0, "s_at_add": 0,
            "As_top_ovr": None, "As_bot_ovr": None, "mr_rows_top": None, "mr_rows_bot": None}


def _strain_limits(F: _Form, fy: float, Es: float):
    if F.checked("ecl_ovr"):
        ecl = F.V("ecl")
    elif fy <= 60:
        ecl = min(fy / Es, 0.002)
    elif fy >= 100:
        ecl = 0.004
    else:
        ecl = 0.002 + (0.004 - 0.002) * (fy - 60) / (100 - 60)
    if F.checked("etl_ovr"):
        etl = F.V("etl")
    elif fy <= 75:
        etl = 0.005
    elif fy >= 100:
        etl = 0.008
    else:
        etl = 0.005 + (0.008 - 0.005) * (fy - 75) / (100 - 75)
    return ecl, etl


def inputs_from_form(form: dict, units: dict) -> dict:
    """gatherInputs() for a full form dict (element id -> display value)."""
    F = _Form(form, units)
    fc, fy, fy_trans, Es = F.VE("fc"), F.VE("fy"), F.VE("fy_trans"), F.VE("Es")
    fpu, Ept, ag = F.VE("fpu"), F.VE("Ept"), F.VE("ag")
    lam, phi_v = F.V("lambda"), F.V("phi_v")
    gamma_e = js_parse_float(F.raw("gamma_e"))
    wc = F.VE("wc") if F.checked("wc_ovr") else compute_wc(fc)
    K1 = _or(F.V("K1"), 1.0)
    Ec = F.VE("Ec") if F.checked("Ec_ovr") else compute_ec_aashto(fc, K1, wc)
    fpy = F.VE("fpy") if F.checked("fpy_ovr") else 0.9 * fpu
    ecl, etl = _strain_limits(F, fy, Es)
    sec_type = F.raw("sectionType")
    b, h, bw_input = F.VE("b_flange"), F.VE("h_total"), F.VE("b_web")
    hf_top, hf_bot, cover = F.VE("hf_top"), F.VE("hf_bot"), F.VE("cover")

    shN = js_parse_int(F.raw("shear_bar"))
    sh_bar = None if shN == 0 else BARS.get(shN, BARS[4])
    shear_legs, s_shear = F.V("shear_legs"), F.VE("shear_s")
    if shN == 0:
        shear_legs, s_shear = 0, 0
    db_stir = sh_bar["d"] if sh_bar else 0
    at_add_bar_N = _or(js_parse_int(F.raw("at_add_bar")), 0)
    s_at_add = F.VE("at_add_s") if at_add_bar_N > 0 else 0

    barN_top = js_parse_int(F.raw("top_bar"))
    bar_top = BARS.get(barN_top)
    if F.checked("d_top_ovr"):
        d_top = F.VE("d_top_override")
    else:
        d_top = cover + db_stir + bar_top["d"] / 2 if bar_top else cover
    mode_top = F.raw("bar_mode_top") or "count"
    nBars_top = (bars_from_spacing(F.V("n_bars_top"), d_top, form, units)
                 if mode_top == "spacing" else F.V("n_bars_top"))
    barN_bot = js_parse_int(F.raw("bot_bar"))
    bar_bot = BARS.get(barN_bot, BARS[7])
    d_bot = F.VE("d_bot_override") if F.checked("d_bot_ovr") else h - cover - db_stir - bar_bot["d"] / 2
    mode_bot = F.raw("bar_mode_bot") or "count"
    nBars_bot = (bars_from_spacing(F.V("n_bars_bot"), d_bot, form, units)
                 if mode_bot == "spacing" else F.V("n_bars_bot"))

    nStrands, strand_area, duct_dia = F.V("n_strands"), F.VE("strand_area"), F.VE("duct_dia")
    dp, fpe = F.VE("dp_input"), _or(F.V("fpe_input"), 0)
    tN = 4 if shN == 0 else shN
    member_type = F.raw("memberType") or "BEAM"
    is_slab = member_type == "SLAB"
    As_top_ovr = As_bot_ovr = None
    if is_slab and mode_top == "spacing" and bar_top and F.V("n_bars_top") > 0:
        As_top_ovr = (b / F.V("n_bars_top")) * bar_top["a"]
    if is_slab and mode_bot == "spacing" and F.V("n_bars_bot") > 0:
        As_bot_ovr = (b / F.V("n_bars_bot")) * bar_bot["a"]

    factor_overrides = {}
    for key in FACTOR_KEYS:
        if F.checked(key + "_ovr"):
            factor_overrides[key] = _or(js_parse_float(F.raw(key + "_ovr_val")), 0)
    bonded = (F.raw("pt_bonded") or "true") == "true"
    srv3 = F.raw("pt_srv3_tens_case") or "moderate"
    if not bonded:
        srv3 = "none"
    pt_flags = {"bonded": bonded, "temp_comp_case": F.raw("pt_temp_comp_case") or "general",
                "temp_tens_case": F.raw("pt_temp_tens_case") or "bonded", "srv3_tens_case": srv3,
                "phi_w": F.pickF("pt_phi_w", 1.0)}
    fci = F.pickF("pt_fci_chk", None)
    if fci is None:
        fci = F.pickF("pt_fci", fc)

    out = {"fc": fc, "fci": fci, "fy": fy, "fy_trans": fy_trans, "Ec": Ec, "wc": wc, "K1": K1,
           "concType": F.raw("concType"), "Es": Es, "fpu": fpu, "fpy": fpy, "Ept": Ept,
           "ecl": ecl, "etl": etl, "ecl_override": F.checked("ecl_ovr"),
           "etl_override": F.checked("etl_ovr"), "ag": ag, "lam": lam, "phi_v": phi_v,
           "gamma_e": gamma_e, "codeEdition": F.raw("codeEdition"),
           "sectionClass": F.raw("sectionClass"), "secType": sec_type, "memberType": member_type,
           "astm_spec": F.raw("astm_spec"), "factor_overrides": factor_overrides,
           "b": b, "h": h, "bw_input": bw_input, "hf_top": hf_top, "hf_bot": hf_bot, "cover": cover,
           "barN_top": barN_top, "nBars_top": nBars_top, "d_top": d_top,
           "barN_bot": barN_bot, "nBars_bot": nBars_bot, "d_bot": d_bot,
           "nStrands": nStrands, "strand_area": strand_area, "dp": dp, "fpe": fpe, "ductDia": duct_dia,
           "shN": 4 if shN == 0 else shN, "shear_legs": shear_legs, "s_shear": s_shear, "tN": tN,
           "s_torsion": s_shear, "at_add_bar_N": at_add_bar_N, "s_at_add": s_at_add,
           "As_top_ovr": As_top_ovr, "As_bot_ovr": As_bot_ovr, "mr_rows_bot": None, "mr_rows_top": None,
           "crack_mode": F.raw("crack_mode") or "capped", "pt_flags": pt_flags,
           "pt_profile": None, "pt_loss_summary": None}
    if sec_type == "CIRCULAR":
        out.update(circ_payload(circ_params(form, units)))
    return out
