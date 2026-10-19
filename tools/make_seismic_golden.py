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


def main(upstream, out):
    sys.path.insert(0, upstream)
    from seismic_column.section import CircularSection
    from seismic_column.moment_curvature import moment_curvature

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
        golden["sections"][name] = dict(
            params=p, Ag=float(s.Ag), Acore=float(s.Acore),
            rho_l=float(s.rho_l), rho_s=float(s.rho_s),
            confined=conf, steel=steel, moment_curvature=mphi)
    with open(out, "w") as f:
        json.dump(golden, f, indent=2)
    print("wrote", out, commit)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
