"""Column-on-Shaft: seismic capacity design (Task 7, spec sections 4.1a / 4.4 / 4.5).

Steps: Mp from moment-curvature -> Mo = lambda_mo * Mp -> Vo -> column seismic
shear -> shaft M(z), V(z) along its depth (soil p-y, equivalent cantilever, or
interface only) -> shaft capacity-protection checks -> lightest transverse cage
meeting the seismic shear, rho_s,min and detailing spacing.

Everything seismic comes from the numpy-free port in `seismic_port/` (pinned to
the upstream Seismic Column app by golden tests).  Pure Python, stdlib only.

Units kip, in, ksi; moments kip-in.

SIGN CONVENTION.  The `axial` dict is in the APP convention (Pu < 0 =
compression).  seismic_port (M-phi, shear, pile solver) is COMPRESSION-POSITIVE,
so every call into it uses ``P_comp = -Pu``.  Mp_by_P, Mp_P and P_vc are reported
in the app convention.

References.  Every `Check.ref` is a ported provisions ``ref_*`` string, copied
verbatim (unverified, OPEN_VERIFICATION_ITEMS section E).  The shaft confinement
and oversize checks carry ``ref_shaft_capacity`` (no dedicated ref_* field exists
upstream; see E5 / E6).  No new citations are added here.

Df_eq.  The equivalent depth to fixity is only meaningful for a free head
(M_head = 0).  ``pile["Df_eq_gov"]`` (used later for the slenderness length lu) is
therefore taken from a FIXED-FREE solve (V_head = Mo/H, M_head = 0) at the same
EI / axial / profile, on the softest STABLE soil bound, even when the governing
end condition is fixed-fixed.  Each entry of ``pile["bounds"]`` likewise reports
the fixed-free Df_eq of that bound, while its Mmax / z_Mmax / Vmax come from the
governing end condition's solve.

Cached PileSolution objects returned by the port are shared; this module only
reads them and builds new lists/tuples.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import List, Optional

import colshaft_lrfd as cl
from seismic_port.materials import bar_diameter
from seismic_port.moment_curvature import moment_curvature
from seismic_port.pile_solver import _cached_pile_solve, inground_demand
from seismic_port.provisions import CodeProvisions
from seismic_port.section import CircularSection
from seismic_port.shear import (
    caltrans_min_transverse_ratio,
    max_transverse_spacing,
    max_transverse_spacing_caltrans,
    min_transverse_bar_no,
    min_transverse_ratio,
    shear_capacity,
)
from seismic_port.soil import SoilLayer, SoilProfile

# Upstream CircularSection defaults for expected steel properties, ksi.
FYE, FUE, FYH = 68.0, 95.0, 68.0
END_FACTOR = {"fixed-free": 1.0, "fixed-fixed": 2.0}
BASES = ("soil", "cantilever", "interface")
N_EXT = 5                       # evenly spaced samples across [P_ext_min, P_ext_max]
N_CANT = 11                     # points of the cantilever M(z) profile
L_EQ_MSG = "Enter the pile equivalent cantilever length or a soil profile"
UNSTABLE_MSG = "soil too soft or shaft too short"


@dataclass
class Check:
    name: str
    demand: float
    capacity: float
    ok: bool
    detail: str = ""
    ref: str = ""

    @property
    def ratio(self) -> float:
        if self.capacity == 0:
            return float("inf") if self.demand else 0.0
        return self.demand / self.capacity


@dataclass
class SeismicResult:
    Mp_by_P: List[tuple]            # [(P app convention, Mp kip-in)]
    Mp: float                       # max Mp over the samples
    Mp_P: float                     # governing P (app convention)
    Mo: float
    Vo: float
    lambda_mo: float
    end_condition: str              # governing ("fixed-fixed" if any direction is)
    H: float
    P_vc: float                     # P used for the seismic Vc (app convention)
    mu_d: float
    col_shear: tuple                # (phiVn, Vc, Vs) kip, inside the hinge
    rho_s_col: float
    rho_s_min: float
    s_max_detailing: Optional[float]
    min_trans_bar: int
    shaft_basis: str
    shaft_profile: List[tuple]      # [(z below top of shaft, M, V)]
    shaft_Mdemand: float            # shaft_demand_factor * max M(z)
    shaft_Mp: float
    shaft_phiVn: float
    EI_col: float
    EI_shaft: float
    Df: Optional[float]             # fixity depth for lu: Df_eq_gov (soil) / L_eq (cantilever)
    checks: List[Check]
    required_transverse: dict
    pile: Optional[dict] = None
    warnings: List[str] = field(default_factory=list)


# ─── Sections / soil ────────────────────────────────────────────────

def to_section(member: dict, cage: dict, provisions: CodeProvisions) -> CircularSection:
    """CircularSection from bent-table member + cage {bar, n, bundle, trans_bar, s, ties}
    (colshaft_lrfd keys), with expected material properties from the provisions."""
    return CircularSection(
        D=float(member["D"]), fc=float(member["fc"]),
        fce_factor=provisions.fce_factor, fce_floor=provisions.fce_floor,
        cover=float(member["cover"]),
        n_bars=int(cage["n"]), long_bar_no=int(cage["bar"]),
        long_bundle=int(cage.get("bundle", 1)),
        spiral_bar_no=int(cage["trans_bar"]), spiral_spacing=float(cage["s"]),
        fye=float(member.get("fye", FYE)), fue=float(member.get("fue", FUE)),
        fyh=float(member.get("fyh", FYH)),
        hoops=member.get("trans_type", "hoop") != "spiral",
    )


def soil_profile(soil: dict) -> SoilProfile:
    """SoilProfile from {"layers": [SoilLayer.from_engineering kwargs], "J", "cyclic"}."""
    layers = []
    for d in soil["layers"]:
        d = dict(d)
        t, m, g = d.pop("thickness_ft"), d.pop("py_model"), d.pop("gamma_pcf")
        layers.append(SoilLayer.from_engineering(float(t), m, float(g), **d))
    return SoilProfile(tuple(layers), J=float(soil.get("J", 0.5)),
                       cyclic=bool(soil.get("cyclic", True)))


# ─── Helpers ────────────────────────────────────────────────────────

def _num(v):
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)


def _axial_samples(axial: dict) -> List[float]:
    """P_dead + 5 evenly spaced across [P_ext_min, P_ext_max] (app convention).
    Missing range -> P_dead only; a zero-width range adds its single value."""
    P_dead = float(axial["P_dead"])
    lo, hi = axial.get("P_ext_min"), axial.get("P_ext_max")
    out = [P_dead]
    if _num(lo) and _num(hi):
        lo, hi = sorted((float(lo), float(hi)))
        if hi - lo <= 1e-9:
            pts = [lo]
        else:
            step = (hi - lo) / (N_EXT - 1)
            pts = [lo + i * step for i in range(N_EXT - 1)] + [hi]
        for p in pts:
            if not any(abs(p - q) <= 1e-9 for q in out):
                out.append(p)
    return out


def _end_condition(bent: dict):
    ends = [bent.get("end_condition_long", "fixed-free"),
            bent.get("end_condition_trans", "fixed-free")]
    for e in ends:
        if e not in END_FACTOR:
            raise ValueError(f"end condition must be 'fixed-free' or 'fixed-fixed', got {e!r}")
    return max(ends, key=lambda e: END_FACTOR[e])


def _rho_s_min(prov, col: CircularSection, H: float, P_dead_comp: float):
    """(rho_s_min, applicable, note) per the ported minimum-transverse model."""
    if prov.transverse_min_model == "caltrans_table":
        return caltrans_min_transverse_ratio(col.D, H, col.rho_l, P_dead_comp, col.fc, col.Ag)
    r = min_transverse_ratio(col.fc, col.fyh, col.Ag, col.Acore,
                             prov.conf_c1, prov.conf_c2, prov.rho_s_min_floor)
    return r, True, ""


def _s_max(prov, col: CircularSection):
    """(s_max, governing label) or (None, "") when detailing checks are off."""
    if not prov.detailing_checks:
        return None, ""
    dbl = bar_diameter(col.long_bar_no)
    if prov.max_tie_spacing_model == "caltrans_8.4.1":
        return max_transverse_spacing_caltrans(dbl)
    return max_transverse_spacing(col.D, dbl, col.spiral_bundle > 1)


def _min_bar(prov, col: CircularSection) -> int:
    """Min transverse bar size (ported SGS 8.8.9 rule; AASHTO detailing model only)."""
    if prov.detailing_checks and prov.max_tie_spacing_model != "caltrans_8.4.1":
        return min_transverse_bar_no(col.long_bar_no, col.long_bundle > 1)
    return 0


# ─── Main ───────────────────────────────────────────────────────────

def seismic_design(column: dict, shaft: dict, col_cage: dict, shaft_cage: dict,
                   axial: dict, bent: dict, provisions: CodeProvisions,
                   *, params: dict = None) -> SeismicResult:
    prov = provisions
    warnings: List[str] = []
    H = float(bent["H_in"])
    if not H > 0:
        raise ValueError("column clear height H_in must be > 0")
    lam = float(bent.get("lambda_mo", 1.2))
    mu_d = float(bent.get("mu_d", prov.mu_d_limit_single))
    P_dead = float(axial["P_dead"])
    P_dead_c = -P_dead
    soil = bent.get("soil")
    basis = bent.get("shaft_basis") or ("soil" if soil else "cantilever")
    if basis not in BASES:
        raise ValueError(f"shaft_basis must be one of {BASES}, got {basis!r}")
    L_eq = bent.get("L_eq_in")
    if basis == "cantilever" and not (_num(L_eq) and L_eq >= 0):
        raise ValueError(L_EQ_MSG)
    if basis == "soil" and not soil:
        raise ValueError(L_EQ_MSG)

    col = to_section(column, col_cage, prov)
    sh = to_section(shaft, shaft_cage, prov)

    # --- Mp sampling -> Mo (spec 4.1a) ---
    mp_by_p, mc_dead, mc_gov = [], None, None
    for P in _axial_samples(axial):
        try:
            mc = moment_curvature(col, -P)
        except (ValueError, RuntimeError, ArithmeticError) as e:
            warnings.append(f"moment-curvature failed at P = {P:.0f} kip ({e}); point skipped")
            continue
        if not (math.isfinite(mc.Mp) and math.isfinite(mc.phi_y) and mc.phi_y > 0):
            warnings.append(f"moment-curvature gave no valid Mp at P = {P:.0f} kip; point skipped")
            continue
        mp_by_p.append((P, mc.Mp))
        if P == P_dead:
            mc_dead = mc
        if mc_gov is None or mc.Mp > mc_gov.Mp:
            mc_gov = mc
    if not mp_by_p:
        raise ValueError("moment-curvature failed at every axial load sampled for Mp")
    Mp = mc_gov.Mp
    Mp_P = -mc_gov.axial
    Mo = lam * Mp
    end = _end_condition(bent)
    Vo = END_FACTOR[end] * Mo / H

    # --- seismic Vc axial: least compression of Extreme, else P_dead ---
    ext = [float(axial[k]) for k in ("P_ext_min", "P_ext_max") if _num(axial.get(k))]
    P_vc = max(ext) if ext else P_dead          # app convention: max = least compression
    P_vc_c = -P_vc

    col_v = shear_capacity(col, P_vc_c, mu_d, True, prov)
    rho_min, rho_min_applies, rho_note = _rho_s_min(prov, col, H, P_dead_c)
    s_max, s_gov = _s_max(prov, col)
    bar_min = _min_bar(prov, col)

    # --- shaft capacities ---
    try:
        mc_sh = moment_curvature(sh, P_dead_c)
    except (ValueError, RuntimeError, ArithmeticError) as e:
        raise ValueError(f"shaft moment-curvature failed at P_dead = {P_dead:.0f} kip ({e})")
    sh_v = shear_capacity(sh, P_vc_c, 1.0, False, prov)
    if mc_dead is None:
        mc_dead = mc_gov
        warnings.append("column EI taken at the governing P (M-phi failed at P_dead)")
    EI_col = mc_dead.Mp / mc_dead.phi_y
    EI_sh = mc_sh.Mp / mc_sh.phi_y

    checks: List[Check] = []
    pile = None
    Df = None
    M_env = V_env = 0.0
    # --- shaft demand profile ---
    if basis == "interface":
        profile = [(0.0, Mo, Vo)]
    elif basis == "cantilever":
        L = float(L_eq)
        profile = [(L * i / (N_CANT - 1), Mo + Vo * L * i / (N_CANT - 1), Vo)
                   for i in range(N_CANT)]
        Df = L
    else:
        profile, pile, py_check, M_env, V_env = _soil_basis(bent, soil, H, EI_col, EI_sh, sh.D,
                                              P_dead_c, Mo, Vo, end)
        Df = pile["Df_eq_gov"]
        checks.append(py_check)
        if py_check.ok and py_check.demand:
            warnings.append("Shaft p-y solve: " + py_check.detail)

    M_max = max(max(abs(m) for _, m, _ in profile), M_env)
    V_max = max(max(abs(v) for _, _, v in profile), V_env, Vo)
    shaft_Md = prov.shaft_demand_factor * M_max

    # --- checks (ported refs verbatim) ---
    checks.insert(0, Check(
        "Column shear", Vo, col_v[0], col_v[0] >= Vo,
        f"Vo={Vo:.1f} kip ({end}), phiVn={col_v[0]:.1f} kip (Vc={col_v[1]:.1f}, "
        f"Vs={col_v[2]:.1f}) at P={P_vc:.0f} kip, mu_d={mu_d:g}", prov.ref_shear))
    checks.insert(1, Check(
        "Transverse steel ratio (min)", rho_min, col.rho_s,
        rho_min_applies and col.rho_s >= rho_min,
        f"rho_s={col.rho_s:.4f} >= {rho_min:.4f}" + (f"; {rho_note}" if rho_note else ""),
        prov.ref_transverse))
    pos = 2
    if s_max is not None:
        checks.insert(pos, Check(
            "Transverse spacing (max)", col.spiral_spacing, s_max,
            col.spiral_spacing <= s_max + 1e-9,
            f"s={col.spiral_spacing:g} in <= {s_max:.2f} in ({s_gov} governs)", prov.ref_detailing))
        pos += 1
    if bar_min:
        checks.insert(pos, Check(
            "Transverse bar size (min)", bar_min, col.spiral_bar_no, col.spiral_bar_no >= bar_min,
            f"#{col.spiral_bar_no} >= #{bar_min} for #{col.long_bar_no} longitudinal bars",
            prov.ref_detailing))
    checks.append(Check(
        "Shaft flexure (capacity protection)", shaft_Md, mc_sh.Mp, mc_sh.Mp >= shaft_Md,
        f"{prov.shaft_demand_factor:g}*max M(z)={shaft_Md:.0f} ({basis}), "
        f"Mp_shaft={mc_sh.Mp:.0f} kip-in at P_dead", prov.ref_shaft_capacity))
    checks.append(Check(
        "Shaft shear (capacity protection)", V_max, sh_v[0], sh_v[0] >= V_max,
        f"max V(z)={V_max:.1f} kip (>= Vo={Vo:.1f}), phiVn_shaft={sh_v[0]:.1f} kip",
        prov.ref_shaft_capacity))
    if prov.shaft_confinement_fraction is not None:
        req = prov.shaft_confinement_fraction * col.rho_s
        checks.append(Check(
            "Shaft confinement (oversized)", req, sh.rho_s, sh.rho_s >= req,
            f"rho_s,shaft={sh.rho_s:.4f} >= {prov.shaft_confinement_fraction:g}*rho_s,col={req:.4f}",
            prov.ref_shaft_capacity))
    gap = sh.D - col.D
    need = prov.min_shaft_oversize
    ok_gap = gap > 0.0 if need <= 0 else gap >= need - 1e-9
    checks.append(Check(
        "Shaft oversize", need, gap, ok_gap,
        f"Ds - D = {gap:g} in " + (f">= {need:g} in" if need > 0 else "> 0 (shaft larger than column)"),
        prov.ref_shaft_capacity))

    req_t = required_transverse(column, col_cage, prov, Vo, P_vc_c, mu_d, rho_min, s_max,
                                bar_min, params)

    return SeismicResult(
        Mp_by_P=mp_by_p, Mp=Mp, Mp_P=Mp_P, Mo=Mo, Vo=Vo, lambda_mo=lam,
        end_condition=end, H=H, P_vc=P_vc, mu_d=mu_d, col_shear=tuple(col_v),
        rho_s_col=col.rho_s, rho_s_min=rho_min, s_max_detailing=s_max, min_trans_bar=bar_min,
        shaft_basis=basis, shaft_profile=profile, shaft_Mdemand=shaft_Md,
        shaft_Mp=mc_sh.Mp, shaft_phiVn=sh_v[0], EI_col=EI_col, EI_shaft=EI_sh, Df=Df,
        checks=checks, required_transverse=req_t, pile=pile, warnings=warnings)


def _soil_basis(bent, soil, H, EI_col, EI_sh, Ds, P_comp, Mo, Vo, end):
    """p-y shaft demand (upstream inground_demand semantics) + per-bound results."""
    prof = soil_profile(soil)
    L_embed = float(bent.get("L_embed_in") or prof.depth)
    bounds = tuple(float(b) for b in bent.get("soil_bounds", (2.0, 0.5)))
    M_head = Mo if end == "fixed-fixed" else 0.0
    V_ff = Mo / H

    M_ig, V_ig, gov = inground_demand(H, L_embed, EI_col, EI_sh, Ds, P_comp, prof, Vo,
                                      bounds, M_head)
    rows, n_unstable = [], 0
    df_soft = None
    for f in bounds:
        p = replace(prof, stiffness_factor=prof.stiffness_factor * f)
        s = _cached_pile_solve(H, L_embed, EI_col, EI_sh, Ds, P_comp, p, Vo, M_head)
        s_ff = s if M_head == 0.0 else _cached_pile_solve(H, L_embed, EI_col, EI_sh, Ds,
                                                          P_comp, p, V_ff, 0.0)
        df = s_ff.Df_eq if s_ff.stable else None
        if df is not None and (df_soft is None or f < df_soft[0]):
            df_soft = (f, df)
        if not s.stable:
            n_unstable += 1
        rows.append(dict(factor=f, stable=bool(s.stable), Df_eq=df,
                         Mmax=s.max_inground_moment if s.stable else None,
                         z_Mmax=s.max_moment_depth if s.stable else None,
                         Vmax=s.max_inground_shear if s.stable else None))

    if gov is None:
        profile = [(0.0, Mo, Vo)]           # interface only: never zero demand
        prof_gov = []
    else:
        g0 = gov.ground_index
        prof_gov = [(gov.x[i] - H, gov.moment[i], gov.shear[i], gov.y[i])
                    for i in range(g0, len(gov.x))]
        profile = [(z, m, v) for z, m, v, _ in prof_gov]
    n = len(bounds)
    # Controller ruling (upstream inground_demand semantics): unstable bounds are
    # skipped from the envelope; the check is NG only when NO bound is stable.
    # A partially unstable envelope is reported in the detail and as a warning.
    ok = gov is not None
    detail = f"{n - n_unstable}/{n} soil bounds stable at the overstrength head force"
    if not ok:
        detail += f"; UNSTABLE on every bound: {UNSTABLE_MSG} (increase embedment or shaft size, or refine the soil)"
    elif n_unstable:
        bad = ", ".join(f"x{r['factor']:g}" for r in rows if not r["stable"])
        detail += (f"; bound(s) {bad} unstable ({UNSTABLE_MSG}) and excluded from the "
                   "envelope, as upstream inground_demand does")
    check = Check("Shaft p-y solve", n_unstable, 0, ok, detail, "")
    pile = dict(bounds=rows, profile_gov=prof_gov,
                Df_eq_gov=None if df_soft is None else df_soft[1],
                M_inground=M_ig, V_inground=V_ig, L_embed=L_embed, end_condition=end,
                M_head=M_head, V_head=Vo)
    # upstream envelope over the stable bounds: M_ig / V_ig (the max V may sit on
    # a bound other than the governing-moment one, so it is carried separately)
    return profile, pile, check, M_ig, V_ig


def required_transverse(column, col_cage, prov, Vo, P_vc_comp, mu_d, rho_min, s_max,
                        bar_min, params=None) -> dict:
    """FIRST (lightest) hoop/spiral in colshaft_lrfd.transverse_candidates order with
    seismic phiVn >= Vo, rho_s >= rho_s,min and s <= the detailing max spacing.
    The longitudinal cage is kept fixed (Mp feedback ignored; Task 8 re-checks)."""
    for bar, ties, s in cl.transverse_candidates(params):
        if bar < bar_min:
            continue
        if s_max is not None and s > s_max + 1e-9:
            continue
        sec = to_section(column, dict(col_cage, trans_bar=bar, s=s, ties=ties), prov)
        if sec.rho_s < rho_min:
            continue
        phi_vn = shear_capacity(sec, P_vc_comp, mu_d, True, prov)[0]
        if phi_vn >= Vo:
            return dict(ok=True, bar=bar, s=s, ties=ties, rho_s=sec.rho_s, phiVn=phi_vn)
    return dict(ok=False, bar=None, s=None, ties=None, rho_s=None, phiVn=None)
