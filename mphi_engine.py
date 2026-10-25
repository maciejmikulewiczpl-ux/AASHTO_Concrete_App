"""Moment-curvature (M-phi) secant stiffness for RECTANGULAR, T-SECTION (I) and CIRCULAR sections.

Fibre section: horizontal concrete strips (cover / confined core areas) plus one fibre per bar row,
with the concrete displaced by each bar removed. Units kip, in, ksi. App sign convention on input:
Ms > 0 sagging, Ps > 0 tension.

This is a "more comprehensive analysis" alternative to the table/formula I_e (BDS-10 Art. 5.6.3.5.2a
wording); no AASHTO equation is implemented here. Concrete model:
  service  - Hognestad parabola in compression (eps_cu 0.003) with the app's Ec; linear tension up to
             fr = 0.24*lam*sqrt(f'c) (Art. 5.4.2.6), zero after cracking; steel elastic-perfectly plastic.
  confined - Mander confined core + unconfined cover, no concrete tension, Caltrans SDC steel curve with
             strain hardening (same models as the column-on-shaft seismic module, seismic_port.materials).
             Rectangular/I confinement uses ke = 0.75 and the mean of the two lateral pressures
             (approximation, OPEN_VERIFICATION_ITEMS MP1).
Strengths are nominal by default; expected_concrete -> f'ce = 1.3 f'c, expected_steel -> A706 fye = 68/60 fy,
fue = 95/60 fy (nominal fu = 1.5 fy).
Prestressed sections are not supported.
"""
from __future__ import annotations

import math

import calc_engine as ce
from seismic_port.materials import ConfinedConcrete, ReinforcingSteel, UnconfinedConcrete, concrete_modulus
from seismic_port.moment_curvature import _brentq, _idealise

N_STRIPS = 160
N_KAPPA = 140
CURVE_POINTS = 150
FCE_FACTOR = 1.3
FYE_RATIO, FUE_RATIO = 68.0 / 60.0, 95.0 / 60.0  # A706 Gr 60 expected 68 / 95 ksi, scaled for other fy
FU_NOMINAL_RATIO = 1.5  # nominal fu/fy (A615 Gr 60: 90/60) for the strain-hardening curve
NOMINAL_EPS_CU = 0.003
NOMINAL_EPS_SU = 0.05  # curve end for elastic-perfectly plastic steel
KE_RECT = 0.75


class NominalConcrete:
    """Compression-positive stress; Hognestad parabola (or linear) + tension to fr, zero after cracking."""

    def __init__(self, fc, Ec, fr, tension=True, linear=False):
        self.fc, self.Ec, self.fr = fc, Ec, fr
        self.tension, self.linear = tension, linear
        self.eps_cr = fr / Ec if Ec > 0 else 0.0
        self.eps0 = min(2.0 * fc / Ec, 0.0025) if Ec > 0 else 0.002
        self.eps_cu = NOMINAL_EPS_CU

    def stress(self, e):
        if e < 0.0:
            return -self.Ec * (-e) if (self.tension and -e <= self.eps_cr) else 0.0
        if self.linear:
            return self.Ec * e
        if e <= self.eps0:
            x = e / self.eps0
            return self.fc * (2.0 * x - x * x)
        return max(self.fc * (1.0 - 0.15 * (e - self.eps0) / (self.eps_cu - self.eps0)), 0.0)


class NominalSteel:
    def __init__(self, fy, Es):
        self.fy, self.Es = fy, Es
        self.eps_y = fy / Es if Es > 0 else 0.0
        self.eps_limit = NOMINAL_EPS_SU

    def stress(self, e):  # tension-positive strain
        return math.copysign(min(self.Es * abs(e), self.fy), e)


class _NoTension:
    """Wrap a compression-only Mander model."""

    def __init__(self, m):
        self.m = m
        self.eps_cu = getattr(m, "eps_cu", None)

    def stress(self, e):
        return self.m.stress(e) if e > 0.0 else 0.0


class RectConfined:
    """Mander confined concrete for a rectangular core (ke = 0.75, mean lateral pressure)."""

    def __init__(self, fc, rho_x, rho_y, fyh, eps_su_h=0.09, eps_c0=0.002):
        fl = KE_RECT * 0.5 * (rho_x + rho_y) * fyh
        ratio = fl / fc
        self.fcc = fc * (-1.254 + 2.254 * math.sqrt(1.0 + 7.94 * ratio) - 2.0 * ratio)
        self.eps_cc = eps_c0 * (1.0 + 5.0 * (self.fcc / fc - 1.0))
        self.eps_cu = 0.004 + 1.4 * (rho_x + rho_y) * fyh * eps_su_h / self.fcc
        self.Ec = concrete_modulus(fc)
        self.r = self.Ec / (self.Ec - self.fcc / self.eps_cc)

    def stress(self, e):
        if e <= 0.0:
            return 0.0
        x = e / self.eps_cc
        return self.fcc * x * self.r / (self.r - 1.0 + x ** self.r)


# ── Section ──────────────────────────────────────────────────────────────────────

def _prepare(raw):
    I = dict(raw)
    if I.get("secType") == "CIRCULAR":
        import circ_engine
        circ_engine.derive_circular(I)
    else:
        ce.derive_constants(I)
    return I


def _bars(I):
    """[(y_from_top, As, bar_no)]"""
    if I.get("isCirc"):
        return [(b["d_top"], b["As"], int(b["barN"])) for b in I["circ_bars"]]
    out = []
    for side, n_key in (("bot", "barN_bot"), ("top", "barN_top")):
        barN = int(I.get(n_key) or 0) or int(I.get("barN_bot") or 8)
        rows = I.get(f"mr_rows_{side}")
        if rows:
            out += [(r["d"], r["As"], barN) for r in rows if r.get("As", 0) > 0]
        else:
            As = I["As_bot"] if side == "bot" else I["As_top"]
            d = I["d_bot"] if side == "bot" else I["d_top"]
            if As > 0:
                out.append((d, As, barN))
    return out


def _cum_area_fns(I, confined):
    """(A_total(y), A_core(y)): cumulative areas from the top face down to depth y."""
    h = I["h"]
    cover = I["cover"]
    dt = I.get("circ_trans_d", I.get("shBar_d", 0.0)) if confined else 0.0
    if I.get("isCirc"):
        import circ_engine
        R = I["D"] / 2.0
        Rc = (I["D"] - 2.0 * cover - dt) / 2.0 if confined else 0.0
        off = R - Rc

        def a_tot(y):
            return circ_engine.circle_segment(R, y)[0]

        def a_core(y):
            return circ_engine.circle_segment(Rc, y - off)[0] if Rc > 0 else 0.0
        return a_tot, a_core
    b, bw = I["b"], I["bw"]
    hf_t = 0.0 if I["isRect"] else I["hf_top"]
    hf_b = 0.0 if I["isRect"] else I.get("hf_bot", 0.0)
    hw = h - hf_t - hf_b

    def clamp(v, lo, hi):
        return max(lo, min(v, hi))

    def a_tot(y):
        if I["isRect"]:
            return b * clamp(y, 0.0, h)
        return (b * clamp(y, 0.0, hf_t) + bw * clamp(y - hf_t, 0.0, hw)
                + b * clamp(y - hf_t - hw, 0.0, hf_b))

    y0, y1 = cover + dt / 2.0, h - cover - dt / 2.0
    wc = (b if I["isRect"] else bw) - 2.0 * cover - dt

    def a_core(y):
        if not confined or wc <= 0 or y1 <= y0:
            return 0.0
        return wc * clamp(y - y0, 0.0, y1 - y0)
    return a_tot, a_core


def build_fibres(I, confined, n_strips=N_STRIPS):
    """Concrete strips [(y, A_cover, A_core)] and bars [(y, As, bar_no, in_core)]; y from the top."""
    h = I["h"]
    a_tot, a_core = _cum_area_fns(I, confined)
    dy = h / n_strips
    strips = []
    for i in range(n_strips):
        y_a, y_b = i * dy, (i + 1) * dy
        at = a_tot(y_b) - a_tot(y_a)
        ac = a_core(y_b) - a_core(y_a)
        strips.append(((y_a + y_b) / 2.0, max(at - ac, 0.0), ac))
    bars = [(y, As, n, confined) for y, As, n in _bars(I)]
    return strips, bars


# ── Solver ───────────────────────────────────────────────────────────────────────

class _Model:
    def __init__(self, strips, bars, yref, cover_m, core_m, steel):
        self.strips, self.bars, self.yref = strips, bars, yref
        self.cover_m, self.core_m, self.steel = cover_m, core_m, steel
        self.y_top = min(y for y, _, _ in strips)
        self.y_bot = max(y for y, _, _ in strips)
        cores = [y for y, _, ac in strips if ac > 0]
        self.y_core_top = min(cores) if cores else self.y_top
        self.y_bar_bot = max((b[0] for b in bars), default=self.y_bot)

    def forces(self, ea, k):
        """(N compression-positive, M sagging-positive about yref)."""
        N = M = 0.0
        yr = self.yref
        for y, a_cov, a_core in self.strips:
            e = ea + k * (yr - y)
            f = self.cover_m.stress(e) * a_cov + (self.core_m.stress(e) * a_core if a_core else 0.0)
            N += f
            M += f * (yr - y)
        for y, As, _n, in_core in self.bars:
            e = ea + k * (yr - y)
            conc = (self.core_m if in_core else self.cover_m).stress(e)
            f = (-self.steel(_n).stress(-e) - conc) * As
            N += f
            M += f * (yr - y)
        return N, M

    def solve_ea(self, k, P):
        def g(ea):
            return self.forces(ea, k)[0] - P
        lo, hi = -0.01, 0.005
        for _ in range(40):
            if g(lo) <= 0.0 <= g(hi):
                break
            if g(lo) > 0.0:
                lo *= 2.0
            if g(hi) < 0.0:
                hi = hi * 2.0 + 0.001
        else:
            raise RuntimeError("axial equilibrium not bracketed")
        return _brentq(g, lo, hi, xtol=1e-14, maxiter=200)

    def state(self, k, P):
        ea = self.solve_ea(k, P)
        _N, M = self.forces(ea, k)
        return ea, M


def _materials(I, model, exp_c, exp_s, tension, linear):
    fc, Es = I["fc"], I["Es"]
    fc_u = FCE_FACTOR * fc if exp_c else fc
    fy_u = FYE_RATIO * I["fy_long"] if exp_s else I["fy_long"]
    fu_u = (FUE_RATIO if exp_s else FU_NOMINAL_RATIO) * I["fy_long"]
    fyh = FYE_RATIO * I["fy_trans"] if exp_s else I["fy_trans"]
    base = {"fc_used": fc_u, "fy_used": fy_u, "expected_concrete": exp_c, "expected_steel": exp_s}
    if model == "confined":
        fce, fye, fue = fc_u, fy_u, fu_u
        cover_m = _NoTension(UnconfinedConcrete(fc=fce))
        s, tr_bar = I.get("s_shear", 0), int(I.get("shN") or 4)
        core_m = cover_m
        if s and s > 0:
            if I.get("isCirc"):
                Acore = math.pi * (I["D"] - 2 * I["cover"] - I["circ_trans_d"]) ** 2 / 4.0
                core_m = _NoTension(ConfinedConcrete(
                    fc=fce, D=I["D"], cover=I["cover"], spiral_bar_no=tr_bar, spacing=s, fyh=fyh,
                    rho_long=I["circ_Ast"] / Acore if Acore > 0 else 0.0,
                    hoops=I.get("circ_trans_type") != "spiral"))
            else:
                dt = I["shBar_d"]
                wc = (I["b"] if I["isRect"] else I["bw"]) - 2 * I["cover"] - dt
                hc = I["h"] - 2 * I["cover"] - dt
                if wc > 0 and hc > 0:
                    a = I["shBar_a"]
                    rho_y = I.get("shear_legs", 2) * a / (s * wc)  # vertical legs
                    rho_x = 2.0 * a / (s * hc)                     # horizontal legs of the closed tie
                    core_m = _NoTension(RectConfined(fce, rho_x, rho_y, fyh))
        cache = {}

        def steel(n):
            if n not in cache:
                cache[n] = ReinforcingSteel(bar_no=n if n in (3, 4, 5, 6, 7, 8, 9, 10, 11, 14, 18) else 10,
                                            fye=fye, fue=fue, Es=Es)
            return cache[n]
        Ec = concrete_modulus(fce)
        info = dict(base, fu_used=fue, Ec_used=Ec, confined=core_m is not cover_m,
                    fcc=getattr(getattr(core_m, "m", None), "fcc", None),
                    eps_cu=getattr(core_m, "eps_cu", None))
        return cover_m, core_m, steel, Ec, info
    lam = I.get("lam", 1.0)
    fr = 0.24 * lam * math.sqrt(fc_u)
    Ec = I["Ec"] * math.sqrt(fc_u / fc)  # app Ec, scaled with sqrt(f'c) when expected
    conc = NominalConcrete(fc_u, Ec, fr, tension=tension, linear=linear)
    st = NominalSteel(fy_u, Es)
    info = dict(base, Ec_used=Ec, fr=fr, confined=False, eps_cu=NOMINAL_EPS_CU)
    return conc, conc, (lambda n: st), Ec, info


def _mirror(strips, bars, h):
    return ([(h - y, a, c) for y, a, c in strips], [(h - y, As, n, ic) for y, As, n, ic in bars])


def _downsample(phi, M, n):
    if len(phi) <= n:
        return list(phi), list(M)
    idx = sorted({round(i * (len(phi) - 1) / (n - 1)) for i in range(n)})
    return [phi[i] for i in idx], [M[i] for i in idx]


def moment_curvature_section(raw_inputs, Ms=0.0, Ps=0.0, model="service", expected_concrete=False,
                             expected_steel=False, tension=True, linear=False, n_strips=N_STRIPS,
                             n_kappa=N_KAPPA, materials=None):
    """M-phi curve and secant stiffnesses. Returns a JSON-ready dict.

    model: 'service' (unconfined, tension to fr) or 'confined' (Mander core, no tension).
    materials: legacy alias - 'nominal' = service/nominal, 'expected' = confined with expected concrete+steel.
    """
    if materials is not None:
        if materials not in ("nominal", "expected"):
            raise ValueError(f"materials must be 'nominal' or 'expected', not {materials!r}")
        if materials == "expected":
            model, expected_concrete, expected_steel = "confined", True, True
    if model not in ("service", "confined"):
        raise ValueError(f"model must be 'service' or 'confined', not {model!r}")
    I = _prepare(raw_inputs)
    if I.get("hasPT"):
        return {"available": False,
                "reason": "Moment-curvature stiffness is not available for prestressed sections."}
    h = I["h"]
    confined = model == "confined"
    strips, bars = build_fibres(I, confined, n_strips)
    if not bars:
        return {"available": False, "reason": "No longitudinal reinforcement."}
    hog = Ms < 0
    yref = I["yb_centroid"]
    if hog:
        strips, bars = _mirror(strips, bars, h)
        yref = h - yref
    cover_m, core_m, steel_fn, Ec, info = _materials(I, model, expected_concrete, expected_steel, tension, linear)
    mdl = _Model(strips, bars, yref, cover_m, core_m, steel_fn)
    P = -Ps  # compression positive
    notes = []

    st0 = steel_fn(bars[0][2])
    eps_y = getattr(st0, "eps_y", None) or getattr(st0, "eps_ye")
    eps_su = getattr(st0, "eps_limit", None) or getattr(st0, "eps_su_r")
    eps_cu = core_m.eps_cu if confined and info["confined"] else (
        getattr(cover_m, "eps_cu", None) or NOMINAL_EPS_CU)
    if confined and not info["confined"]:
        eps_cu = 0.005  # unconfined spalling strain (no transverse steel)
        notes.append("No transverse reinforcement: core treated as unconfined.")
    y_comp = mdl.y_core_top if confined and info["confined"] else mdl.y_top
    d_t = mdl.y_bar_bot - mdl.y_top
    k_ref = eps_y / max(0.6 * d_t, 1e-6)

    ks = [k_ref * 10 ** (-3.0 + 4.8 * i / (n_kappa - 1)) for i in range(n_kappa)]
    phi, M = [0.0], [0.0]
    failure = "curve end"
    try:
        _, m0 = mdl.state(0.0, P)
        M[0] = m0
    except RuntimeError:
        return {"available": False, "reason": "Axial load exceeds the section's axial capacity."}

    def limits(ea, k):
        e_c = ea + k * (yref - y_comp)
        e_s = -(ea + k * (yref - mdl.y_bar_bot))
        return e_c, e_s

    def limit_ratio(k):
        e_c, e_s = limits(mdl.solve_ea(k, P), k)
        return max(e_c / eps_cu, e_s / eps_su)

    for k in ks:
        try:
            ea, m = mdl.state(k, P)
        except RuntimeError:
            failure = "equilibrium lost"
            break
        e_c, e_s = limits(ea, k)
        if e_c >= eps_cu or e_s >= eps_su:
            failure = "concrete crushing" if e_c / eps_cu >= e_s / eps_su else "steel strain limit"
            try:
                k_u = _brentq(lambda kk: limit_ratio(kk) - 1.0, phi[-1], k, xtol=1e-15)
                phi.append(k_u)
                M.append(mdl.state(k_u, P)[1])
            except RuntimeError:
                pass
            break
        phi.append(k)
        M.append(m)
    phi_u, M_u = phi[-1], M[-1]

    def m_at(k):
        return mdl.state(k, P)[1]

    def secant(k, m):
        EI = m / k if k > 0 else None
        return {"M": m, "phi": k, "EI": EI, "Ieff": EI / Ec if EI else None}

    out = {"available": True, "model": model, "expected_concrete": bool(expected_concrete),
           "expected_steel": bool(expected_steel), "direction": "hogging" if hog else "sagging",
           "Ms": Ms, "Ps": Ps, "Ec_used": Ec, "Ig": I["Ig"], "M0": M[0], "info": info, "notes": notes,
           "ultimate": {"M": M_u, "phi": phi_u, "failure": failure}}

    # Cracking (nominal with tension): extreme tension concrete fibre reaches eps_cr
    if not confined and tension and info.get("fr"):
        eps_cr = info["fr"] / Ec

        def crack_margin(k):
            ea = mdl.solve_ea(k, P)
            return -(ea + k * (yref - mdl.y_bot)) - eps_cr
        try:
            if crack_margin(phi_u) > 0:
                k_cr = _brentq(crack_margin, 1e-12, phi_u, xtol=1e-14)
                out["cracking"] = secant(k_cr, m_at(k_cr))
        except RuntimeError:
            pass

    # First yield: extreme tension steel at eps_y or extreme compression concrete at 0.002
    def fy_margin(k):
        e_c, e_s = limits(mdl.solve_ea(k, P), k)
        return max(e_s - eps_y, e_c - 0.002)
    k_fy = None
    try:
        if fy_margin(phi_u) >= 0:
            k_fy = _brentq(fy_margin, 1e-12, phi_u, xtol=1e-14)
            out["first_yield"] = secant(k_fy, m_at(k_fy))
        else:
            notes.append("First yield not reached before the curve end.")
    except RuntimeError:
        notes.append("First yield could not be located.")

    if k_fy and phi_u > k_fy:
        Mp, phi_y = _idealise(phi, M, k_fy, out["first_yield"]["M"], phi_u)
        # Equal-area bilinear through first yield: Mp/phi_y = My/phi_y' (same EI as first yield).
        out["idealised"] = {"Mp": Mp, "phi_y": phi_y, "EI": Mp / phi_y if phi_y > 0 else None,
                            "Ieff": Mp / phi_y / Ec if phi_y > 0 else None}

    # Secant at the service moment (first crossing; after cracking the curve dips below Mcr)
    Ma = abs(Ms)
    if Ma <= 0:
        notes.append("Service moment Ms = 0: no secant stiffness at the demand.")
    elif Ma > max(M):
        out["service_error"] = "Ms exceeds the moment capacity of the M-phi curve."
    else:
        i = next(j for j in range(1, len(M)) if M[j] >= Ma)
        k_lo, k_hi = phi[i - 1], phi[i]
        if M[i - 1] >= Ma:
            k_s = k_lo
        else:
            k_s = _brentq(lambda k: m_at(k) - Ma, k_lo, k_hi, xtol=1e-15)
        out["service"] = secant(k_s, Ma)
        if k_fy and k_s > k_fy:
            notes.append("Service moment is beyond first yield.")

    if abs(M[0]) > 1e-6 * max(abs(m) for m in M):
        notes.append("Axial load about the gross centroid gives M ≠ 0 at zero curvature "
                     "(asymmetric reinforcement / section).")
    out["curve"] = dict(zip(("phi", "M"), _downsample(phi, M, CURVE_POINTS)))
    return out
