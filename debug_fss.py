"""Debug fss mismatch with axial load."""
import math, sys
sys.path.insert(0, ".")
from calc_engine import calculate_all, BARS

sh_bar = BARS[4]
db_stir = sh_bar["d"]
bar_bot = BARS[8]
h, b, cover = 36, 36, 2.0
d_bot = h - cover - db_stir - bar_bot["d"]/2
d_top = cover + db_stir

raw = dict(
    fc=4, fy=60, Ec=2500*4**0.33, Es=29000, fpu=270, fpy=243, Ept=28500,
    ecl=0, etl=0, ecl_override=False, etl_override=False,
    ag=0.75, lam=1.0, phi_v=0.9, gamma_e=0.75,
    codeEdition="AASHTO", sectionClass="RC",
    secType="RECTANGULAR", b=b, h=h, bw_input=b,
    hf_top=0, hf_bot=0, cover=cover,
    barN_bot=8, nBars_bot=4, d_bot=d_bot,
    barN_top=0, nBars_top=0, d_top=d_top,
    nStrands=0, strand_area=0, dp=0, ductDia=0,
    shN=4, shear_legs=2, s_shear=12,
    tN=4, s_torsion=12,
)

# Test 1: Ps=10 (tension), Ms=1000
dem = [{"Pu":50, "Mu":2000, "Vu":80, "Tu":30, "Vp":0, "Ms":1000, "Ps":10}]
res = calculate_all(raw, dem, 0)
fl = res["flexure"]

print("=== Test: Pu=50, Ms=1000, Ps=10 ===")
print(f"M_serv = {fl['M_serv']:.2f}")
print(f"addlBM = {fl['addlBM']:.2f}")
M_total = fl["M_serv"] + fl["addlBM"]
print(f"M_total= {M_total:.2f}")
print(f"ds     = {fl['ds']:.4f}")
print(f"c_cr   = {fl['c_cr']:.4f}")
print(f"Icr    = {fl['Icr']:.1f}")
print(f"n_mod  = {fl['n_mod']:.4f}")
print(f"fss_eng= {fl['fss']:.4f}")
print(f"eps_rb = {fl['eps_rb']:.8f}")
print(f"curv   = {fl['curv']:.10f}")
n = fl["n_mod"]
fss_hand = M_total * (fl["ds"] - fl["c_cr"]) / fl["Icr"] * n
print(f"fss_hnd= {fss_hand:.4f}")
diff_pct = abs(fl["fss"] - fss_hand) / max(abs(fss_hand), 1e-9) * 100
print(f"diff   = {diff_pct:.2f}%")

# Test 2: Ps=0 (no axial), Ms=1000 — should match perfectly
dem2 = [{"Pu":0, "Mu":2000, "Vu":80, "Tu":30, "Vp":0, "Ms":1000, "Ps":0}]
res2 = calculate_all(raw, dem2, 0)
fl2 = res2["flexure"]

print("\n=== Test: Pu=0, Ms=1000, Ps=0 ===")
print(f"M_serv = {fl2['M_serv']:.2f}")
print(f"addlBM = {fl2['addlBM']:.2f}")
M_total2 = fl2["M_serv"] + fl2["addlBM"]
print(f"M_total= {M_total2:.2f}")
print(f"fss_eng= {fl2['fss']:.4f}")
fss_hand2 = M_total2 * (fl2["ds"] - fl2["c_cr"]) / fl2["Icr"] * fl2["n_mod"]
print(f"fss_hnd= {fss_hand2:.4f}")
diff_pct2 = abs(fl2["fss"] - fss_hand2) / max(abs(fss_hand2), 1e-9) * 100
print(f"diff   = {diff_pct2:.2f}%")

# Test 3: Pu=-200, Ms=1000 — compression
dem3 = [{"Pu":-200, "Mu":2000, "Vu":80, "Tu":30, "Vp":0, "Ms":1000, "Ps":-50}]
res3 = calculate_all(raw, dem3, 0)
fl3 = res3["flexure"]

print("\n=== Test: Pu=-200, Ms=1000, Ps=-50 ===")
print(f"M_serv = {fl3['M_serv']:.2f}")
print(f"addlBM = {fl3['addlBM']:.2f}")
M_total3 = fl3["M_serv"] + fl3["addlBM"]
print(f"M_total= {M_total3:.2f}")
print(f"fss_eng= {fl3['fss']:.4f}")
fss_hand3 = M_total3 * (fl3["ds"] - fl3["c_cr"]) / fl3["Icr"] * fl3["n_mod"]
print(f"fss_hnd= {fss_hand3:.4f}")
diff_pct3 = abs(fl3["fss"] - fss_hand3) / max(abs(fss_hand3), 1e-9) * 100
print(f"diff   = {diff_pct3:.2f}%")
