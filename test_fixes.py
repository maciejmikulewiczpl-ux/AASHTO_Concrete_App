"""Quick test for all fixes."""
from calc_engine import calculate_all

inp = {
    'fc':5,'fy':60,'Es':29000,'Ec':4074,'fpu':270,'fpy':243,'Ept':28500,
    'ecl':0.002,'etl':0.005,'ecl_override':False,'etl_override':False,
    'ag':0.75,'lam':1,'phi_v':0.9,'gamma_e':0.75,
    'codeEdition':'CA','sectionClass':'NP','secType':'RECTANGULAR',
    'b':16.38,'h':27.5,'bw_input':16.38,'hf_top':0,'hf_bot':0,'cover':2,
    'barN_top':7,'nBars_top':5,'barN_bot':7,'nBars_bot':5,
    'd_top':2.4375,'d_bot':24.5625,
    'nStrands':5,'strand_area':0.217,'dp':20,'ductDia':6,
    'shN':4,'shear_legs':0,'s_shear':0,'tN':4,'s_torsion':0,
    'As_top_ovr':None,'As_bot_ovr':None
}
dem = [{'Pu':0,'Mu':6953,'Vu':108,'Tu':0,'Vp':0,'Ms':2500,'Ps':-100}]

print("=== Test 1: User's section (comp steel does NOT yield) ===")
r = calculate_all(inp, dem, 0)
fl = r['flexure']
sh = r['shear']

# c_trial should be about 4.899 (with A's)
print(f"  c_trial: {fl['c_trial']:.4f} in (with A's·fy)")
print(f"  3·d's:   {3*fl['d_s_comp']:.4f} in")
print(f"  c_trial >= 3·d's? {fl['c_trial'] >= 3*fl['d_s_comp']}")
print(f"  comp_steel_yields: {fl['comp_steel_yields']}")

# Final c should be ~7.91 (without A's)
print(f"  c (final): {fl['c']:.4f} in (without A's)")
print(f"  a (final): {fl['a']:.4f} in")

# eps_comp and fs_comp at final c (for reference)
print(f"  eps_comp (at final c): {fl['eps_comp']:.6f}")
print(f"  fs_comp (at final c): {fl['fs_comp']:.2f} ksi")
print(f"  Mn: {fl['Mn']:.1f} kip-in")
print(f"  Mr: {fl['Mr']:.1f} kip-in")

# Manually verify Mn = As·fy·(ds−a/2) + Aps·fps·(dp−a/2) [no A's term]
As=3.0; fy=60; ds=24.5625; Aps=1.085; dp=20
c=fl['c']; a=fl['a']
fps=270*(1-0.28*c/dp)
Mn_check = As*fy*(ds-a/2) + Aps*fps*(dp-a/2)
print(f"  Mn (manual check): {Mn_check:.1f} kip-in")
assert abs(fl['Mn'] - Mn_check) < 1, f"Mn mismatch: {fl['Mn']} vs {Mn_check}"

print()
print("=== Test 2: Comp steel DOES yield (big section, small d's) ===")
inp2 = dict(inp)
inp2['nStrands'] = 0
inp2['h'] = 48; inp2['d_bot'] = 45; inp2['d_top'] = 1.5
inp2['barN_top'] = 4; inp2['nBars_top'] = 2  # small comp steel
inp2['barN_bot'] = 9; inp2['nBars_bot'] = 5  # big tension steel
r2 = calculate_all(inp2, dem, 0)
fl2 = r2['flexure']
print(f"  c_trial: {fl2['c_trial']:.4f} in")
print(f"  3·d's: {3*fl2['d_s_comp']:.4f} in")
print(f"  comp_steel_yields: {fl2['comp_steel_yields']}")
print(f"  c (final): {fl2['c']:.4f} in")
print(f"  Mn: {fl2['Mn']:.1f} kip-in")

print()
print("=== Test 3: Av=0 handling ===")
rr = r['row_results'][0]
print(f"  has_min_av: {sh['has_min_av']}")
print(f"  Vs1={sh['Vs1']:.1f} Vs2={sh['Vs2']:.1f} Vs3={sh['Vs3']:.1f}")
print(f"  shReqd: {rr['shReqd']}  hasMinAv: {rr['hasMinAv']}")

print()
print("=== Test 4: P-M bar strains present ===")
pm = fl['pm_data']
pt = pm[2]
print(f"  Point: c={pt['c']:.3f}  es_tens={pt.get('es_tens','MISSING')}  fs_tens={pt.get('fs_tens','MISSING')}")
assert 'es_tens' in pt, "P-M missing es_tens"
assert 'fs_comp' in pt, "P-M missing fs_comp"

print()
print("ALL TESTS PASSED")
