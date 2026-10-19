"""PORT of the shear / detailing functions of seismic_column/sdc_capacity.py @ 9265d67.

Copied line for line: ShearBreakdown, _alpha_prime, concrete_shear_stress,
_concrete_shear, shear_breakdown, shear_capacity, max_transverse_spacing,
max_transverse_spacing_caltrans, max_longitudinal_spacing_caltrans,
longitudinal_bar_spacing, min_transverse_bar_no, max_bar_diameter,
anchorage_length, effective_bar_diameter, min_transverse_ratio,
axial_load_ratio, caltrans_min_transverse_ratio.

Units: kip, in, ksi.  SIGN CONVENTION (upstream, kept): axial load P is
COMPRESSION-POSITIVE, as in moment_curvature.  P <= 0 is net tension and gives
vc = 0 in both shear models.  (The app convention Pu<0 = compression must be
flipped by the caller.)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .provisions import SDC_2_0, CodeProvisions
from .section import CircularSection

PHI_SHEAR = 0.90            # shear resistance factor


@dataclass
class ShearBreakdown:
    """Every intermediate quantity behind ``phiVn``, for reporting.

    Stresses are ksi, areas in^2, forces kip.  ``alpha`` is the concrete shear
    stress adjustment factor — Caltrans calls it F1, AASHTO calls it alpha'.
    """
    model: str
    alpha: float            # F1 / alpha', after clamping to [0.3, 3.0]
    alpha_raw: float        # before clamping
    fs: float               # rho_s*fyh used in alpha (ksi; AASHTO caps at 0.35)
    fs_raw: float           # rho_s*fyh before the cap
    axial_factor: float     # F2 / (1 + Pc/(2Ag)), after any cap
    axial_factor_raw: float
    vc_uncapped: float      # ksi, before the code's vc cap
    vc_cap: float           # ksi, governing cap on vc
    cap_label: str          # which cap governs, for the report
    vc: float               # ksi
    Ae: float
    Vc: float
    Vs_uncapped: float
    Vs_cap: float
    Vs: float
    Vn: float
    phiVn: float


def _alpha_prime(rho_s: float, fyh: float, mu_d: float, inside_hinge: bool,
                 fs_limit: float | None) -> tuple[float, float, float, float]:
    """Return (alpha, alpha_raw, fs, fs_raw) for the shear stress adjustment.

    ``fs_limit`` caps rho_s*fyh (0.35 ksi in both codes: SDC 5.3.7.2-5 /
    SGS 8.6.2-6); pass ``None`` to leave it uncapped.  Outside the plastic hinge
    alpha' = 3 (SDC 5.3.7.2-4 / SGS 8.6.1).
    """
    fs_raw = rho_s * fyh
    fs = min(fs_raw, fs_limit) if fs_limit is not None else fs_raw
    if not inside_hinge:
        return 3.0, 3.0, fs, fs_raw
    alpha_raw = fs / 0.15 + 3.67 - mu_d
    return min(max(alpha_raw, 0.3), 3.0), alpha_raw, fs, fs_raw


def concrete_shear_stress(fc: float, rho_s: float, fyh: float, P: float,
                          Ag: float, mu_d: float, inside_hinge: bool,
                          model: str = "caltrans") -> float:
    """Concrete shear stress vc (ksi); see :func:`shear_breakdown`."""
    return _concrete_shear(fc, rho_s, fyh, P, Ag, mu_d, inside_hinge, model)[0]


def _concrete_shear(fc: float, rho_s: float, fyh: float, P: float, Ag: float,
                    mu_d: float, inside_hinge: bool, model: str) -> tuple:
    """Return (vc, alpha, alpha_raw, fs, fs_raw, f2, f2_raw, vc_unc, cap, label).

    All stresses ksi.  ``model`` is ``"caltrans"`` (SDC 2.1 §5.3.7.2) or
    ``"aashto"`` (SGS §8.6.2).

    Both models share the ``fs = ρs·fyh ≤ 0.35 ksi`` limit and the net-tension
    rule ``vc = 0`` — SDC 2.1 §5.3.7.2-5 states both explicitly, matching
    SGS §8.6.2-6 and §8.6.2-4.  They differ only in units and the vc cap.
    """
    if model not in ("aashto", "caltrans"):
        raise ValueError(f"unknown shear model {model!r}")

    # fs = ρs·fyh capped at 0.35 ksi in BOTH codes (SDC 5.3.7.2-5 / SGS 8.6.2-6).
    alpha, alpha_raw, fs, fs_raw = _alpha_prime(rho_s, fyh, mu_d, inside_hinge,
                                                0.35)

    if model == "aashto":
        # SGS 8.6.2-4: no concrete contribution unless Pc is compressive.
        if P <= 0.0:
            return (0.0, alpha, alpha_raw, fs, fs_raw, 0.0, 0.0, 0.0, 0.0,
                    "Pc not compressive → vc = 0 (8.6.2-4)")
        root = math.sqrt(fc)                        # f'c in ksi
        f2 = 1.0 + P / (2.0 * Ag)                   # 8.6.2-3, P kip / Ag in^2
        # 0.032, NOT the 0.0032 printed in the 3rd Ed.  The September 2024
        # errata (LRFDSEIS-3-Errata, p. 8-10) corrects "0.0032" to "0.032";
        # 0.0032 under-predicts vc by 10x and would make the 0.047*alpha' cap
        # unreachable.  0.032 ~ sqrt(1000)/1000, the psi->ksi conversion of the
        # equivalent Caltrans SDC §5.3.7.2 expression.
        vc_unc = 0.032 * alpha * f2 * root
        cap_abs = 0.11 * root
        cap_alpha = 0.047 * alpha * root
        cap = min(cap_abs, cap_alpha)
        label = "0.11√f'c" if cap_abs <= cap_alpha else "0.047α'√f'c"
        return (min(vc_unc, cap), alpha, alpha_raw, fs, fs_raw, f2, f2,
                vc_unc, cap, label)

    # Caltrans SDC 2.1 §5.3.7.2, evaluated in psi.
    # 5.3.7.2: "For members with net axial load in tension, vc = 0."
    if P <= 0.0:
        return (0.0, alpha, alpha_raw, fs, fs_raw, 0.0, 0.0, 0.0, 0.0,
                "net axial tension → vc = 0 (5.3.7.2)")
    root_psi = math.sqrt(fc * 1000.0)
    f2_raw = 1.0 + P * 1000.0 / (2000.0 * Ag)       # Pc lb / Ag in^2
    f2 = min(f2_raw, 1.5)
    vc_unc = alpha * f2 * root_psi / 1000.0
    cap = 4.0 * root_psi / 1000.0
    return (min(vc_unc, cap), alpha, alpha_raw, fs, fs_raw, f2, f2_raw,
            vc_unc, cap, "4√f'c")


def shear_breakdown(section: CircularSection, P: float, mu_d: float,
                    inside_hinge: bool,
                    provisions: CodeProvisions = SDC_2_0) -> ShearBreakdown:
    """Full shear derivation for a circular section (SDC 3.6 / SGS 8.6).

    Vs follows SGS 8.6.3-1 for circular hoops/spirals (n = 1 core section) and
    is capped at ``vs_max_coeff*sqrt(f'c)*Ae`` (max shear reinforcement,
    SGS 8.6.4 with coeff = 0.25, f'c in ksi).
    """
    Ag = section.Ag
    Ae = 0.8 * Ag
    (vc, alpha, alpha_raw, fs, fs_raw, f2, f2_raw, vc_unc, vc_cap,
     cap_label) = _concrete_shear(section.fc, section.rho_s, section.fyh, P, Ag,
                                  mu_d, inside_hinge, provisions.shear_model)
    Vc = vc * Ae
    # transverse (spiral) shear: Vs = (pi/2) * Asp * fyh * D' / s
    Asp = section.transverse_area()
    Vs_unc = (math.pi / 2.0) * Asp * section.fyh * section.ds / section.spiral_spacing
    Vs_cap = provisions.vs_max_coeff * math.sqrt(section.fc) * Ae
    Vs = min(Vs_unc, Vs_cap)
    Vn = Vc + Vs
    return ShearBreakdown(
        model=provisions.shear_model, alpha=alpha, alpha_raw=alpha_raw, fs=fs,
        fs_raw=fs_raw, axial_factor=f2, axial_factor_raw=f2_raw,
        vc_uncapped=vc_unc, vc_cap=vc_cap, cap_label=cap_label, vc=vc, Ae=Ae,
        Vc=Vc, Vs_uncapped=Vs_unc, Vs_cap=Vs_cap, Vs=Vs, Vn=Vn,
        phiVn=PHI_SHEAR * Vn,
    )


def shear_capacity(section: CircularSection, P: float, mu_d: float,
                   inside_hinge: bool,
                   provisions: CodeProvisions = SDC_2_0,
                   ) -> tuple[float, float, float]:
    """Return (phi*Vn, Vc, Vs) in kip for a circular section."""
    b = shear_breakdown(section, P, mu_d, inside_hinge, provisions)
    return b.phiVn, b.Vc, b.Vs


def max_transverse_spacing(D: float, dbl: float,
                           bundled: bool) -> tuple[float, str]:
    """Max transverse spacing in the plastic hinge region (SGS 8.8.9), in.

    Smallest of D/5 (columns), 6*dbl, and 6 in. (single hoop/spiral) or 8 in.
    (bundled hoops).  Returns (spacing, governing-term label).
    """
    limit_abs = (8.0, "8 in. (bundled hoops)") if bundled else (6.0, "6 in.")
    candidates = [(D / 5.0, "D/5"), (6.0 * dbl, "6·dbl"), limit_abs]
    return min(candidates, key=lambda c: c[0])


def max_transverse_spacing_caltrans(dbl: float) -> tuple[float, str]:
    """Max transverse spacing inside the plastic hinge (SDC 2.1 §8.4.1.1), in.

    Smallest of 6*dbl and 8 in.  (SDC 2.1 drops the D/5 term that AASHTO uses.)
    """
    candidates = [(6.0 * dbl, "6·dbl"), (8.0, "8 in.")]
    return min(candidates, key=lambda c: c[0])


def max_longitudinal_spacing_caltrans(D: float) -> tuple[float, str]:
    """Max c/c lateral spacing of longitudinal bars (SDC 2.1 §8.4.2), in.

    10 in. for Dc <= 5 ft, 12 in. for Dc > 5 ft.
    """
    if D <= 60.0:
        return 10.0, "10 in. (Dc ≤ 5 ft)"
    return 12.0, "12 in. (Dc > 5 ft)"


def longitudinal_bar_spacing(D: float, cover: float, dsp: float, dbl: float,
                             n_bars: int) -> float:
    """Centre-to-centre spacing of longitudinal bars around the cage, in."""
    r_bars = D / 2.0 - cover - dsp - dbl / 2.0
    return 2.0 * math.pi * r_bars / n_bars


def min_transverse_bar_no(long_bar_no: int, long_bundled: bool) -> int:
    """Minimum transverse bar size (SGS 8.8.9): #4, or #5 for #10+/bundled."""
    if long_bundled or long_bar_no >= 10:
        return 5
    return 4


def max_bar_diameter(fc: float, L: float, Dc: float, fye: float) -> float:
    """Max longitudinal bar diameter for bond (SGS 8.8.6-1), in.

    dbl <= 0.79*sqrt(f'c)*(L - 0.5*Dc)/fye, with f'c and fye in ksi, L and Dc
    in in.  ``L`` is contraflexure-to-max-moment length.
    """
    return 0.79 * math.sqrt(fc) * (L - 0.5 * Dc) / fye


def anchorage_length(dbl: float, fye: float, fc: float, bundle: int = 1) -> float:
    """Required anchorage length into a cap beam or footing (SGS 8.8.4-1), in.

    l_ac >= 0.79*dbl*fye/sqrt(f'c), increased 20% for two-bar and 50% for
    three-bar bundles per SGS 8.8.5.  Note this is the cap-beam/footing rule;
    a column embedded in an *oversized* shaft is governed instead by SGS 8.8.10
    (Dc,max + ld staggered), which needs ld from AASHTO LRFD 5.10.8.2.1 and is
    therefore not evaluated here.
    """
    base = 0.79 * dbl * fye / math.sqrt(fc)
    return base * {1: 1.0, 2: 1.2, 3: 1.5}.get(bundle, 1.0)


def effective_bar_diameter(dbl: float, bundle: int) -> float:
    """Effective bar diameter for the SGS 8.8.6 bond check (1.2x / 1.5x)."""
    return dbl * {1: 1.0, 2: 1.2, 3: 1.5}.get(bundle, 1.0)


def min_transverse_ratio(fc: float, fyh: float, Ag: float, Acore: float,
                         c1: float = 0.45, c2: float = 0.12,
                         floor: float = 0.0) -> float:
    """Minimum volumetric transverse steel ratio (ACI/legacy form + floor).

    max of the ACI confinement terms and a constant floor.  Used for AASHTO SGS
    (c1 = c2 = 0, floor = 0.005 per §8.6.5).  **Not** used for Caltrans SDC 2.1,
    whose minimum comes from :func:`caltrans_min_transverse_ratio` (Table
    5.3.8.2-1) — the ACI equations were removed in SDC 2.0.
    """
    return max(c1 * (Ag / Acore - 1.0) * fc / fyh, c2 * fc / fyh, floor)


def axial_load_ratio(P_dead: float, fc: float, Ag: float) -> float:
    """Axial load ratio due to dead load ρdl = Pdl/(f'c·Ag) (SDC 2.1 §5.3.3-1).

    f'c is capped at 5.0 ksi per §5.3.3.  ``P_dead`` kip, ``fc`` ksi (nominal),
    ``Ag`` in^2.  Dimensionless (multiply by 100 for the percentage used in
    Table 5.3.8.2-1).
    """
    return P_dead / (min(fc, 5.0) * Ag)


def caltrans_min_transverse_ratio(
    D: float, Hcol: float, rho_l: float, P_dead: float, fc: float, Ag: float,
) -> tuple[float, bool, str]:
    """Minimum transverse volumetric ratio from SDC 2.1 Table 5.3.8.2-1.

    Ordinary Standard bridges, inside the plastic hinge region.  The table is
    keyed on aspect ratio ``L/Dc``, column diameter ``Dc`` (ft), longitudinal
    ratio ``ρl`` (%), and dead-load axial ratio ``ρdl`` (%).

    Returns ``(rho_s_min, in_table, note)``.  When the section falls outside the
    tabulated parameter ranges (``in_table`` False) the table cannot supply a
    value — SDC 2.1 directs the designer to the PSDC procedure to establish a
    ρs,min giving μc ≥ 3.0 — so the check must be flagged for manual review
    rather than silently passed.

    Recovery Standard bridges (ρs,min = 0.01) are out of this tool's scope.
    """
    Dc_ft = D / 12.0
    L_over_Dc = Hcol / D
    rho_l_pct = rho_l * 100.0
    rho_dl_pct = axial_load_ratio(P_dead, fc, Ag) * 100.0

    def outside(why: str) -> tuple[float, bool, str]:
        return (0.0, False,
                f"outside Table 5.3.8.2-1 ({why}) → establish ρs,min via PSDC "
                f"procedure for μc ≥ 3.0")

    if L_over_Dc > 8.0:
        return outside(f"L/Dc = {L_over_Dc:.1f} > 8.0")
    if rho_dl_pct > 15.0:
        return outside(f"ρdl = {rho_dl_pct:.1f}% > 15%")

    if 3.0 <= Dc_ft <= 6.0:
        if rho_l_pct > 2.3:
            return outside(f"ρl = {rho_l_pct:.2f}% > 2.3% for Dc ≤ 6 ft")
        rho_s_min = 0.006 if rho_dl_pct <= 10.0 else 0.007
    elif 6.0 < Dc_ft <= 11.0:
        if rho_l_pct > 2.15:
            return outside(f"ρl = {rho_l_pct:.2f}% > 2.15% for Dc > 6 ft")
        rho_s_min = 0.007 if rho_dl_pct <= 10.0 else 0.008
    else:
        return outside(f"Dc = {Dc_ft:.1f} ft outside 3–11 ft")

    band = "≤10%" if rho_dl_pct <= 10.0 else "10–15%"
    return (rho_s_min, True,
            f"Table 5.3.8.2-1: Dc={Dc_ft:.1f}ft, L/Dc={L_over_Dc:.1f}, "
            f"ρl={rho_l_pct:.2f}%, ρdl={rho_dl_pct:.1f}% ({band}) → "
            f"ρs,min={rho_s_min:.3f}")
