"""Generate tests/golden/seismic_port_golden.json from the upstream seismic package.

Run ONCE (and again whenever a later task adds a block) with the seismic app's venv:

    "<Seismic Column>/.venv/Scripts/python.exe" -I tools/make_seismic_golden.py \
        "<Seismic Column>" tests/golden/seismic_port_golden.json

Blocks: source_commit, sections (parameters + materials/section values + M-phi),
detailing, provisions, pile (p-y soil profiles + beam-column pile solver),
seismic (Task 7: capacity-design primitives for the column/shaft pair, built from
upstream PRIMITIVES only -- never evaluate_column / _build_checks).
"""
import json
import subprocess
import sys

SECTIONS = {
    "col_D48_12-#9_#5@4_hoop": dict(
        D=48.0, fc=4.0, cover=2.0, n_bars=12, long_bar_no=9,
        spiral_bar_no=5, spiral_spacing=4.0, hoops=True),
    "col_D72_24-#11_#6@5_spiral": dict(
        D=72.0, fc=4.0, cover=2.0, n_bars=24, long_bar_no=11,
        spiral_bar_no=6, spiral_spacing=5.0, hoops=False),
    "col_D84_20x2-#11_#6@4_spiral": dict(
        D=84.0, fc=4.0, cover=2.0, n_bars=20, long_bar_no=11, long_bundle=2,
        spiral_bar_no=6, spiral_spacing=4.0, hoops=False),
    "shaft_D96_30-#11_#8@6_spiral": dict(
        D=96.0, fc=4.0, cover=3.0, n_bars=30, long_bar_no=11,
        spiral_bar_no=8, spiral_spacing=6.0, hoops=False),
}
CONF_STRAINS = [0.001, 0.002, 0.004]      # plus eps_cu
STEEL_STRAINS = [0.001, 0.01, 0.05]
AXIALS = [0.0, 500.0, 1500.0]             # kip, compression positive (upstream)
SHEAR_AXIALS = [0.0, 800.0, -200.0]       # kip, compression positive; -200 = tension
SHEAR_MU = [1.0, 3.0, 5.0]
PROV_KEYS = ["SDC 2.1", "AASHTO SGS 3rd Ed."]
# --- pile block (Task 3A) ---------------------------------------------------
PILE_COL, PILE_SHAFT = "col_D72_24-#11_#6@5_spiral", "shaft_D96_30-#11_#8@6_spiral"
PILE_AXIAL = 800.0                        # kip, compression positive
PILE_HCOL = [240.0, 480.0]
PILE_EMBED = 720.0
PILE_BOUNDS = [2.0, 0.5]                  # upstream inground_demand default bounds
# layers as SoilLayer.from_engineering(thickness_ft, py_model, gamma_pcf, **kw)
PILE_PROFILES = {
    "soft_clay": [
        [80.0, "matlock_soft_clay", 115.0,
         dict(su_top_ksf=1.0, su_bot_ksf=2.0, eps50=0.02, submerged=True)]],
    "stiff_clay_over_sand": [
        [20.0, "welch_stiff_clay", 125.0,
         dict(su_top_ksf=2.5, su_bot_ksf=3.0, eps50=0.005)],
        [60.0, "api_sand", 125.0,
         dict(phi_deg=36.0, k_pci=90.0, submerged=True)]],
    "sand_water_table": [
        [10.0, "api_sand", 120.0, dict(phi_deg=34.0, k_pci=225.0)],
        [70.0, "api_sand", 125.0, dict(phi_deg=34.0, k_pci=60.0, submerged=True)]],
}
PILE_UNSTABLE = dict(
    profile=[[80.0, "matlock_soft_clay", 110.0,
              dict(su_top_ksf=0.15, eps50=0.02, submerged=True)]],
    Hcol=240.0, L_embed=120.0, bound=0.5)
PILE_SAMPLE = 8                           # store every 8th node of the diagrams
# --- seismic capacity-design block (Task 7) ---------------------------------
SEIS_P_DEAD = 800.0                       # kip, compression positive
SEIS_H = 240.0                            # column clear height, in
SEIS_L_EMBED = 720.0
SEIS_PROFILE = "soft_clay"
SEIS_COL_TRANS = [[5, 6.0], [6, 5.0], [6, 3.0], [8, 3.0]]   # (spiral bar, pitch) probes
BALANCE = ("balance_k_ratio_adjacent", "balance_k_ratio_any", "balance_T_ratio",
           "ref_balanced_stiffness", "ref_balanced_stiffness_any",
           "ref_balanced_geometry", "ref_balance_tuning")


def main(upstream, out):
    sys.path.insert(0, upstream)
    from seismic_column.section import CircularSection
    from seismic_column.moment_curvature import moment_curvature
    from seismic_column import sdc_capacity as sc
    from seismic_column.provisions import get_provisions
    from seismic_column.materials import bar_diameter
    import dataclasses

    commit = subprocess.check_output(
        ["git", "-C", upstream, "rev-parse", "HEAD"], text=True).strip()
    golden = {"source_commit": commit, "axial_sign": "compression positive",
              "sections": {}}
    for name, p in SECTIONS.items():
        s = CircularSection(**p)
        ecu = float(s.confined.eps_cu)
        conf = {repr(e): float(s.confined.stress(e)) for e in CONF_STRAINS}
        conf["eps_cu"] = ecu
        conf["stress_at_eps_cu"] = float(s.confined.stress(ecu))
        steel = {repr(e): float(s.steel.stress(e)) for e in STEEL_STRAINS}
        mphi = {}
        for P in AXIALS:
            r = moment_curvature(s, P)
            mphi[repr(P)] = dict(
                phi_y=float(r.phi_y), Mp=float(r.Mp), phi_u=float(r.phi_u),
                Mu=float(r.Mu), phi_yield_first=float(r.phi_yield_first),
                M_yield_first=float(r.M_yield_first),
                failure_mode=r.failure_mode)
        shear = {}
        for pk in PROV_KEYS:
            prov = get_provisions(pk)
            for P in SHEAR_AXIALS:
                for mu in SHEAR_MU:
                    for hinge in (True, False):
                        phi_vn, vc, vs = sc.shear_capacity(s, P, mu, hinge, prov)
                        b = sc.shear_breakdown(s, P, mu, hinge, prov)
                        shear[f"{pk}|{P!r}|{mu!r}|{hinge}"] = dict(
                            phiVn=float(phi_vn), Vc=float(vc), Vs=float(vs),
                            breakdown={k: (float(v) if isinstance(v, (int, float)) else v)
                                       for k, v in dataclasses.asdict(b).items()})
        golden["sections"][name] = dict(shear=shear, 
            params=p, Ag=float(s.Ag), Acore=float(s.Acore),
            rho_l=float(s.rho_l), rho_s=float(s.rho_s),
            confined=conf, steel=steel, moment_curvature=mphi)
    sec = golden["sections"]
    mt = {}
    for name, g in sec.items():
        p = SECTIONS[name]
        s = CircularSection(**p)
        dbl, dsp = bar_diameter(p["long_bar_no"]), bar_diameter(p["spiral_bar_no"])
        mt[name] = dict(
            lng_spacing=sc.longitudinal_bar_spacing(
                p["D"], p["cover"], dsp, dbl, p["n_bars"]),
            max_trans=list(sc.max_transverse_spacing(p["D"], dbl, False)),
            max_trans_bundled=list(sc.max_transverse_spacing(p["D"], dbl, True)),
            max_trans_caltrans=list(sc.max_transverse_spacing_caltrans(dbl)),
            max_long_caltrans=list(sc.max_longitudinal_spacing_caltrans(p["D"])),
            min_bar_no=sc.min_transverse_bar_no(p["long_bar_no"], p.get("long_bundle", 1) > 1),
            max_bar_diameter=sc.max_bar_diameter(p["fc"], 300.0, p["D"], 68.0),
            anchorage=[sc.anchorage_length(dbl, 68.0, p["fc"], b) for b in (1, 2, 3)],
            eff_bar_d=[sc.effective_bar_diameter(dbl, b) for b in (1, 2, 3)],
            min_ratio_aashto=sc.min_transverse_ratio(
                p["fc"], 68.0, s.Ag, s.Acore, 0.0, 0.0, 0.005),
            min_ratio_aci=sc.min_transverse_ratio(p["fc"], 68.0, s.Ag, s.Acore),
            axial_ratio=sc.axial_load_ratio(400.0, p["fc"], s.Ag),
            caltrans_min=[
                list(sc.caltrans_min_transverse_ratio(
                    p["D"], H, s.rho_l, Pd, p["fc"], s.Ag))
                for H, Pd in ((p["D"] * 4, 0.0), (p["D"] * 4, 0.12 * p["fc"] * s.Ag),
                              (p["D"] * 4, 0.05 * p["fc"] * s.Ag), (p["D"] * 9, 0.0))],
            caltrans_min_args=[[p["D"] * 4, 0.0], [p["D"] * 4, 0.12 * p["fc"] * s.Ag],
                               [p["D"] * 4, 0.05 * p["fc"] * s.Ag], [p["D"] * 9, 0.0]])
    golden["detailing"] = mt
    golden["provisions"] = {
        pk: {k: v for k, v in dataclasses.asdict(get_provisions(pk)).items()
             if k not in BALANCE} for pk in PROV_KEYS}
    golden["pile"] = _pile_block(CircularSection, moment_curvature, get_provisions)
    golden["seismic"] = _seismic_block(CircularSection, moment_curvature, get_provisions)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(golden, f, indent=2)
    print("wrote", out, commit)


def _pile_block(CircularSection, moment_curvature, get_provisions):
    from dataclasses import replace
    from seismic_column.soil import SoilLayer, SoilProfile
    from seismic_column.pile_solver import solve_lateral
    from seismic_column.sdc_capacity import inground_demand

    def prof(layers):
        return SoilProfile(tuple(SoilLayer.from_engineering(t, m, g, **kw)
                                 for t, m, g, kw in layers))

    def sol_dict(s):
        idx = sorted(set(range(0, len(s.x), PILE_SAMPLE)) | {s.ground_index,
                                                              len(s.x) - 1})
        out = {k: float(getattr(s, k)) for k in (
            "head_deflection", "head_stiffness", "head_flexibility", "Df_eq",
            "max_inground_moment", "max_moment_depth", "max_inground_shear")}
        out.update(stable=bool(s.stable), converged=bool(s.converged),
                   iterations=int(s.iterations), ground_index=int(s.ground_index),
                   n_nodes=int(len(s.x)),
                   M_ground=float(s.moment[s.ground_index]),
                   sample_index=idx,
                   x=[float(s.x[i]) for i in idx], y=[float(s.y[i]) for i in idx],
                   moment=[float(s.moment[i]) for i in idx],
                   shear=[float(s.shear[i]) for i in idx])
        return out

    rc = moment_curvature(CircularSection(**SECTIONS[PILE_COL]), PILE_AXIAL)
    rs = moment_curvature(CircularSection(**SECTIONS[PILE_SHAFT]), PILE_AXIAL)
    EI_col, EI_shaft = float(rc.Mp / rc.phi_y), float(rs.Mp / rs.phi_y)
    Mo = float(get_provisions("SDC 2.1").overstrength_factor * rc.Mp)
    D_shaft = float(SECTIONS[PILE_SHAFT]["D"])
    cases, demand = [], []
    for pname, layers in PILE_PROFILES.items():
        base = prof(layers)
        for H in PILE_HCOL:
            for end, V, Mh in (("free", Mo / H, 0.0), ("fixed", 2.0 * Mo / H, Mo)):
                for b in PILE_BOUNDS:
                    p = replace(base, stiffness_factor=base.stiffness_factor * b)
                    s = solve_lateral(H, PILE_EMBED, EI_col, EI_shaft, D_shaft,
                                      PILE_AXIAL, p, V, M_head=Mh)
                    cases.append(dict(profile=pname, Hcol=H, L_embed=PILE_EMBED,
                                      end=end, bound=b, V_head=V, M_head=Mh,
                                      result=sol_dict(s)))
                M, Vd, gov = inground_demand(H, PILE_EMBED, EI_col, EI_shaft,
                                             D_shaft, PILE_AXIAL, base, V,
                                             soil_bounds=tuple(PILE_BOUNDS),
                                             M_head=Mh)
                demand.append(dict(profile=pname, Hcol=H, end=end, V_head=V,
                                   M_head=Mh, M=float(M), V=float(Vd),
                                   gov_none=gov is None))
    u = PILE_UNSTABLE
    Vu = Mo / u["Hcol"]
    pu = prof(u["profile"])
    pu = replace(pu, stiffness_factor=u["bound"])
    su = solve_lateral(u["Hcol"], u["L_embed"], EI_col, EI_shaft, D_shaft,
                       PILE_AXIAL, pu, Vu)
    unstable = dict(u, V_head=Vu, result=sol_dict(su))
    return dict(column=PILE_COL, shaft=PILE_SHAFT, axial=PILE_AXIAL,
                EI_col=EI_col, EI_shaft=EI_shaft, Mp_col=float(rc.Mp), Mo=Mo,
                D_shaft=D_shaft, profiles=PILE_PROFILES, bounds=PILE_BOUNDS,
                cases=cases, inground_demand=demand, unstable=unstable)


def _seismic_block(CircularSection, moment_curvature, get_provisions):
    """Column/shaft capacity-design values from upstream primitives (Ruling P4).

    Sections use the provisions' expected-strength factors (fce_factor,
    fce_floor) and upstream default fye/fue/fyh.  Axial is compression positive.
    """
    from seismic_column import sdc_capacity as sc
    from seismic_column.soil import SoilLayer, SoilProfile
    from seismic_column.materials import bar_diameter
    profile = SoilProfile(tuple(SoilLayer.from_engineering(t, m, g, **kw)
                                for t, m, g, kw in PILE_PROFILES[SEIS_PROFILE]))
    P = SEIS_P_DEAD
    out = dict(column=PILE_COL, shaft=PILE_SHAFT, P_dead=P, H=SEIS_H,
               L_embed=SEIS_L_EMBED, profile=SEIS_PROFILE, bounds=PILE_BOUNDS,
               by_code={})
    for pk in PROV_KEYS:
        prov = get_provisions(pk)
        mat = dict(fce_factor=prov.fce_factor, fce_floor=prov.fce_floor)
        col = CircularSection(**dict(SECTIONS[PILE_COL], **mat))
        sh = CircularSection(**dict(SECTIONS[PILE_SHAFT], **mat))
        mc, ms = moment_curvature(col, P), moment_curvature(sh, P)
        Mo = prov.overstrength_factor * mc.Mp
        mu = prov.mu_d_limit_single
        Vo = {"fixed-free": Mo / SEIS_H, "fixed-fixed": 2.0 * Mo / SEIS_H}
        col_v = list(sc.shear_capacity(col, P, mu, True, prov))
        sh_v = list(sc.shear_capacity(sh, P, 1.0, False, prov))
        dbl = bar_diameter(col.long_bar_no)
        if prov.max_tie_spacing_model == "caltrans_8.4.1":
            s_max = sc.max_transverse_spacing_caltrans(dbl)[0]
        else:
            s_max = sc.max_transverse_spacing(col.D, dbl, False)[0]
        if prov.transverse_min_model == "caltrans_table":
            rmin = list(sc.caltrans_min_transverse_ratio(
                col.D, SEIS_H, col.rho_l, P, col.fc, col.Ag))
        else:
            rmin = [sc.min_transverse_ratio(col.fc, col.fyh, col.Ag, col.Acore,
                                            prov.conf_c1, prov.conf_c2,
                                            prov.rho_s_min_floor), True, ""]
        probes = []
        for bar, pitch in SEIS_COL_TRANS:
            c2 = CircularSection(**dict(SECTIONS[PILE_COL], spiral_bar_no=bar,
                                        spiral_spacing=pitch, **mat))
            probes.append(dict(bar=bar, s=pitch, rho_s=float(c2.rho_s),
                               phiVn=float(sc.shear_capacity(c2, P, mu, True, prov)[0])))
        EI_col, EI_sh = float(mc.Mp / mc.phi_y), float(ms.Mp / ms.phi_y)
        soil = {}
        for end, Vh, Mh in (("fixed-free", Vo["fixed-free"], 0.0),
                            ("fixed-fixed", Vo["fixed-fixed"], Mo)):
            M_ig, V_ig, gov = sc.inground_demand(
                SEIS_H, SEIS_L_EMBED, EI_col, EI_sh, sh.D, P, profile, Vh,
                tuple(PILE_BOUNDS), M_head=Mh)
            soil[end] = dict(M=float(M_ig), V=float(V_ig),
                             gov_none=gov is None,
                             gov_Df_eq=None if gov is None else float(gov.Df_eq),
                             gov_depth=None if gov is None else float(gov.max_moment_depth))
        if pk == PROV_KEYS[0]:
            out["stability"] = _stability(sc, SoilLayer, SoilProfile, mc, ms, sh.D, P)
        out["by_code"][pk] = dict(
            Mp_col=float(mc.Mp), phi_y_col=float(mc.phi_y), Mo=float(Mo), Vo=Vo,
            mu_d=mu, col_shear=col_v, col_rho_s=float(col.rho_s),
            shaft_shear=sh_v, Mp_shaft=float(ms.Mp), phi_y_shaft=float(ms.phi_y),
            shaft_rho_s=float(sh.rho_s),
            shaft_demand_interface=float(prov.shaft_demand_factor * Mo),
            shaft_demand_factor=prov.shaft_demand_factor,
            rho_s_min=rmin, s_max=float(s_max), trans_probes=probes, soil=soil)
    return out


def _stability(sc, SoilLayer, SoilProfile, mc, ms, D_shaft, P):
    """Upstream evaluate_column check 13 inputs: per-bound p-y stability at the
    YIELD-level head force F_y = Mp/H (x2 and head_fixed=True for fixed-fixed),
    as in sdc_capacity._specs_for, for every golden profile."""
    from dataclasses import replace
    EI_col, EI_sh = mc.EI_eff, ms.EI_eff
    F_y = mc.Mp / SEIS_H
    out = {}
    for pname, layers in PILE_PROFILES.items():
        base = SoilProfile(tuple(SoilLayer.from_engineering(t, m, g, **kw)
                                 for t, m, g, kw in layers))
        for fixed in (False, True):
            V = (2.0 if fixed else 1.0) * F_y
            rows = []
            for b in PILE_BOUNDS:
                prof = replace(base, stiffness_factor=base.stiffness_factor * b)
                sol = sc._cached_pile_solve(SEIS_H, SEIS_L_EMBED, EI_col, EI_sh,
                                            D_shaft, P, prof, V, head_fixed=fixed)
                rows.append(dict(bound=b, stable=bool(sol.stable),
                                 Df_eq=float(sol.Df_eq)))
            out[f"{pname}|{'fixed' if fixed else 'free'}"] = dict(V_head=V, bounds=rows)
    return out


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
