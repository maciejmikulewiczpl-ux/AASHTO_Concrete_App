"""Show the effect of the eps_s denominator fix on shear with axial tension."""
import sys
sys.path.insert(0, ".")
from calc_engine import calculate_all, BARS

def make_inputs(**kw):
    bar_bot = BARS[kw.get("barN_bot", 8)]
    sh_bar = BARS[kw.get("shN", 4)]
    h, b, cover = kw.get("h", 36), kw.get("b", 36), kw.get("cover", 2.0)
    db_stir = sh_bar["d"]
    d_bot = h - cover - db_stir - bar_bot["d"] / 2
    bar_top = BARS.get(kw.get("barN_top", 0), None)
    d_top = cover + db_stir + (bar_top["d"] / 2 if bar_top else 0)
    fc = kw.get("fc", 4)
    return dict(
        fc=fc, fy=60, Ec=2500 * fc ** 0.33, Es=29000, fpu=270, fpy=243, Ept=28500,
        ecl=0, etl=0, ecl_override=False, etl_override=False,
        ag=0.75, lam=1.0, phi_v=0.9, gamma_e=0.75,
        codeEdition="AASHTO", sectionClass="RC",
        secType="RECTANGULAR", b=b, h=h, bw_input=b,
        hf_top=0, hf_bot=0, cover=cover,
        barN_bot=kw.get("barN_bot", 8), nBars_bot=kw.get("nBars_bot", 4), d_bot=d_bot,
        barN_top=kw.get("barN_top", 0), nBars_top=kw.get("nBars_top", 0), d_top=d_top,
        nStrands=0, strand_area=0, dp=0, ductDia=0,
        shN=kw.get("shN", 4), shear_legs=2, s_shear=12,
        tN=4, s_torsion=12,
    )

raw = make_inputs()
cases = [
    ("Pu=0 (no axial)", 0),
    ("Pu=+100 (tension)", 100),
    ("Pu=+200 (tension)", 200),
    ("Pu=-200 (compression)", -200),
]

print("Rect 36x36, 4#8 bot, Mu=2000 kip-in, Vu=150 kip, #4 stirrups @ 12in")
print("=" * 90)
print(f"{'Case':<25} {'eps_s':>10} {'beta2':>8} {'theta2':>8} {'Vc2':>8} {'Vs2':>8} {'Vr2':>8} {'Vr3':>8}")
print("-" * 90)

for label, Pu in cases:
    dem = [{"Pu": Pu, "Mu": 2000, "Vu": 150, "Tu": 0, "Vp": 0, "Ms": 0, "Ps": 0}]
    res = calculate_all(raw, dem, 0)
    sh = res["shear"]
    print(f"{label:<25} {sh['eps_s']:>10.6f} {sh['bt2']:>8.3f} {sh['th2']:>8.1f} {sh['Vc2']:>8.1f} {sh['Vs2']:>8.1f} {sh['Vr2']:>8.1f} {sh.get('Vr3',0):>8.1f}")

print("\nhas_min_av:", res["shear"].get("has_min_av"))
print("Av_min:", f"{res['shear'].get('Av_min', 0):.4f}")
print("Av_prov:", f"{res['shear'].get('Av', 0) if 'Av' in res['shear'] else 'N/A'}")
