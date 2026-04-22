"""Quick test for multi-row PM curve support."""
from calc_engine import derive_constants, build_pm_curve, get_pm_equilibrium_at_pu

BASE = {
    'fc':4, 'fy':60, 'Es':29000, 'Ec':3644, 'fpu':270, 'fpy':243, 'Ept':28500,
    'ecl':0.002, 'etl':0.005, 'ecl_override':False, 'etl_override':False,
    'ag':0.75, 'lam':1.0, 'phi_v':0.9, 'gamma_e':0.75,
    'codeEdition':'AASHTO', 'sectionClass':'NP',
    'secType':'RECTANGULAR', 'b':16, 'h':26, 'bw_input':16,
    'hf_top':0, 'hf_bot':0, 'cover':2,
    'barN_top':4, 'nBars_top':0, 'd_top':2.44,
    'barN_bot':7, 'nBars_bot':5, 'd_bot':24.5625,
    'nStrands':0, 'strand_area':0.217, 'dp':0, 'fpe':0, 'ductDia':0,
    'shN':4, 'shear_legs':2, 's_shear':12, 'tN':4, 's_torsion':12,
}

# Test 1: Single layer (backward compat)
I = dict(BASE)
derive_constants(I)
pm = build_pm_curve(I, 'top')
print("=== SINGLE LAYER ===")
print(f"Points: {len(pm)}")
p = pm[20]
print(f"Point 20: c={p['c']:.3f} Pn={p['Pn']:.1f} Mn={p['Mn']:.1f}")
print(f"  rows_tens: {len(p.get('rows_tens', []))} rows")
for r in p.get('rows_tens', []):
    print(f"    d_cf={r['d_cf']:.3f} As={r['As']:.2f} es={r['es']:.6f} fs={r['fs']:.1f} F={r['F']:.1f}")
print(f"  es_tens={p['es_tens']:.6f} fs_tens={p['fs_tens']:.1f} F_tens={p['F_tens']:.1f}")
assert len(p.get('rows_tens', [])) == 1, "Single-layer should have 1 tension row"
assert 'rows_comp' in p, "Should have rows_comp key"

# Test 2: Multi-row
I2 = dict(BASE)
I2['mr_rows_bot'] = [{'d': 24.5625, 'As': 3.0}, {'d': 20.0, 'As': 3.0}]
I2['As_bot_ovr'] = 6.0
derive_constants(I2)
pm2 = build_pm_curve(I2, 'top')
print("\n=== MULTI-ROW (2 bot layers) ===")
print(f"Points: {len(pm2)}")
p2 = pm2[20]
print(f"Point 20: c={p2['c']:.3f} Pn={p2['Pn']:.1f} Mn={p2['Mn']:.1f}")
print(f"  rows_tens: {len(p2.get('rows_tens', []))} rows")
for r in p2['rows_tens']:
    print(f"    d_cf={r['d_cf']:.3f} As={r['As']:.2f} es={r['es']:.6f} fs={r['fs']:.1f} F={r['F']:.1f}")
assert len(p2['rows_tens']) == 2, "Multi-row should have 2 tension rows"
# The two rows should have different strains
assert abs(p2['rows_tens'][0]['es'] - p2['rows_tens'][1]['es']) > 1e-6, "Different depths should give different strains"

# es_tens should match the extreme (deepest) row's strain
extreme = max(p2['rows_tens'], key=lambda r: r['d_cf'])
assert abs(p2['es_tens'] - extreme['es']) < 1e-10, "es_tens should match extreme row"

# F_tens should be sum of all row forces
total_F = sum(r['F'] for r in p2['rows_tens'])
assert abs(p2['F_tens'] - total_F) < 1e-6, f"F_tens={p2['F_tens']} should equal sum={total_F}"

# Test 3: PM equilibrium interpolation preserves rows
eq = get_pm_equilibrium_at_pu(pm2, 0)
print("\n=== PM Equilibrium at Pu=0 (multi-row) ===")
assert eq is not None, "Should find equilibrium at Pu=0"
print(f"c={eq['c']:.3f} Mr={eq['Mr']:.1f}")
assert 'rows_tens' in eq, "Equilibrium should contain rows_tens"
assert len(eq['rows_tens']) == 2, "Equilibrium rows_tens should have 2 rows"
for r in eq['rows_tens']:
    print(f"  d_cf={r['d_cf']:.3f} es={r['es']:.6f} fs={r['fs']:.1f} F={r['F']:.1f}")

# Test 4: Hogging (bottom face compression)
pm_hog = build_pm_curve(I2, 'bottom')
ph = pm_hog[20]
print("\n=== HOGGING (multi-row) ===")
print(f"Point 20: c={ph['c']:.3f} Pn={ph['Pn']:.1f}")
# In hogging, top = tension, but we have no top steel rows. 
# Bottom rows become compression side.
print(f"  rows_comp: {len(ph.get('rows_comp', []))} rows (bottom bars as compression)")
assert len(ph.get('rows_comp', [])) == 2, "Hogging should have 2 compression rows (from bot)"

print("\n\nALL MULTI-ROW PM TESTS PASSED")
