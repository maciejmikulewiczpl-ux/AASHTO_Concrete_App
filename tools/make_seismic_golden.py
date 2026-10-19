"""Generate tests/golden/seismic_port_golden.json from the upstream seismic package.

Run ONCE (and again whenever a later task adds a block) with the seismic app's venv:

    "<Seismic Column>/.venv/Scripts/python.exe" -I tools/make_seismic_golden.py \
        "<Seismic Column>" tests/golden/seismic_port_golden.json

Blocks: source_commit, sections (parameters + materials/section values + M-phi).
Later tasks add further top-level keys (shear, provisions, pile solver, ...).
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
    with open(out, "w", encoding="utf-8") as f:
        json.dump(golden, f, indent=2)
    print("wrote", out, commit)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
