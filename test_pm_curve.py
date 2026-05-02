"""Verify PM curve fixes: eccentricity, smooth transition, I-section."""
from calc_engine import calculate_all

# Base symmetric rectangular section
inp_base = {
    'fc':5,'fy':60,'Es':29000,'Ec':4074,'fpu':270,'fpy':243,'Ept':28500,
    'ecl':0.002,'etl':0.005,'ecl_override':False,'etl_override':False,
    'ag':0.75,'lam':1,'phi_v':0.9,'gamma_e':0.75,
    'codeEdition':'CA','sectionClass':'NP','secType':'RECTANGULAR',
    'b':16,'h':28,'bw_input':16,'hf_top':0,'hf_bot':0,'cover':2,
    'barN_top':7,'nBars_top':5,'barN_bot':7,'nBars_bot':5,
    'd_top':2.4375,'d_bot':25.5625,
    'nStrands':0,'strand_area':0.217,'dp':20,'ductDia':6,
    'shN':4,'shear_legs':2,'s_shear':6,'tN':4,'s_torsion':6,
    'As_top_ovr':None,'As_bot_ovr':None
}
dem = [{'Pu':0,'Mu':3000,'Vu':50,'Tu':0,'Vp':0,'Ms':2000,'Ps':0}]

# Test 1: Symmetric rectangular - run full calc
print('=== Test 1: SYMMETRIC SECTION (5#7 top, 5#7 bot, rect 16x28) ===')
r = calculate_all(inp_base, dem, 0)
fl = r['flexure']
assert 'pm_curve_sag' in fl, "pm_curve_sag missing from flexure result"
assert 'pm_curve_hog' in fl, "pm_curve_hog missing from flexure result"
pm_sag = fl['pm_curve_sag']
pm_hog = fl['pm_curve_hog']

print(f'  Pure comp Mn (sag): {pm_sag[0]["Mn"]:.1f} kip-in')
print(f'  Pure comp Mn (hog): {pm_hog[0]["Mn"]:.1f} kip-in')
print(f'  Pure tens Mn (sag): {pm_sag[-1]["Mn"]:.1f} kip-in')
print(f'  Pure tens Mn (hog): {pm_hog[-1]["Mn"]:.1f} kip-in')
print(f'  Num points (sag): {len(pm_sag)}')
# For symmetric rect: pure comp and pure tens should have Mn ~ 0
assert abs(pm_sag[0]["Mn"]) < 1.0, f"Symmetric: pure comp Mn should be ~0, got {pm_sag[0]['Mn']}"
assert abs(pm_sag[-1]["Mn"]) < 1.0, f"Symmetric: pure tens Mn should be ~0, got {pm_sag[-1]['Mn']}"
print('  PASS: endpoints near M=0 for symmetric section\n')

# Test 2: Asymmetric section - 5#7 bot, 3#5 top
print('=== Test 2: ASYMMETRIC SECTION (3#5 top, 5#7 bot, rect 16x28) ===')
inp2 = dict(inp_base)
inp2['barN_top'] = 5
inp2['nBars_top'] = 3
r2 = calculate_all(inp2, dem, 0)
pm_sag2 = r2['flexure']['pm_curve_sag']
pm_hog2 = r2['flexure']['pm_curve_hog']

print(f'  Pure comp Mn (sag): {pm_sag2[0]["Mn"]:.1f} kip-in')
print(f'  Pure comp Mn (hog): {pm_hog2[0]["Mn"]:.1f} kip-in')
print(f'  Pure tens Mn (sag): {pm_sag2[-1]["Mn"]:.1f} kip-in')
print(f'  Pure tens Mn (hog): {pm_hog2[-1]["Mn"]:.1f} kip-in')
assert abs(pm_sag2[-1]["Mn"]) > 5.0, f"Asymmetric: pure tens Mn should be non-zero, got {pm_sag2[-1]['Mn']}"
assert abs(pm_sag2[0]["Mn"]) > 5.0, f"Asymmetric: pure comp Mn should be non-zero, got {pm_sag2[0]['Mn']}"
print('  PASS: endpoints shifted for asymmetric section\n')

# Test 3: Smooth transition - no flat portion
print('=== Test 3: TENSION TRANSITION (sag, asymmetric) - last 12 points ===')
last12 = pm_sag2[-12:]
for pt in last12:
    print(f'  c={pt["c"]:8.3f}  Pn={pt["Pn"]:8.1f}  Mn={pt["Mn"]:8.1f}')
mn_vals = [pt["Mn"] for pt in last12]
diffs = [abs(mn_vals[i+1] - mn_vals[i]) for i in range(len(mn_vals)-1)]
flat_count = sum(1 for d in diffs if d < 0.01)
assert flat_count <= 1, f"Too many flat segments: {flat_count}"
print('  PASS: smooth transition, no flat portion\n')

# Test 4: I-section (asymmetric flanges)
print('=== Test 4: I-SECTION (36w x 36h, tf=8, bf=12, bw=12, 4#5 top, 6#9 bot) ===')
inp3 = dict(inp_base)
inp3['secType'] = 'I_BEAM'
inp3['b'] = 36
inp3['bw_input'] = 12
inp3['hf_top'] = 8
inp3['hf_bot'] = 12
inp3['h'] = 36
inp3['d_bot'] = 33.5
inp3['d_top'] = 2.5
inp3['barN_top'] = 5
inp3['nBars_top'] = 4
inp3['barN_bot'] = 9
inp3['nBars_bot'] = 6
r3 = calculate_all(inp3, dem, 0)
pm_sag3 = r3['flexure']['pm_curve_sag']
pm_hog3 = r3['flexure']['pm_curve_hog']

print(f'  Pure comp Mn (sag): {pm_sag3[0]["Mn"]:.1f} kip-in')
print(f'  Pure comp Mn (hog): {pm_hog3[0]["Mn"]:.1f} kip-in')
print(f'  Pure tens Mn (sag): {pm_sag3[-1]["Mn"]:.1f} kip-in')
print(f'  Pure tens Mn (hog): {pm_hog3[-1]["Mn"]:.1f} kip-in')
print(f'  Max Mn (sag): {max(d["Mn"] for d in pm_sag3):.0f} kip-in')
print(f'  Num points (sag): {len(pm_sag3)}')
# I-section with asym flanges + asym bars: comp endpoint should be non-zero
assert abs(pm_sag3[0]["Mn"]) > 1.0, f"I-section: pure comp Mn should be non-zero due to flange asymmetry"
print('  PASS: I-section endpoints shifted correctly\n')

print('ALL PM CURVE TESTS PASSED')
