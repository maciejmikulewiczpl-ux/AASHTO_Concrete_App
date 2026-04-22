import calc_engine

# Test 1: Rectangular section with torsion
rect_inputs = {
    'fc':5,'fy':60,'Es':29000,'Ec':4074,'fpu':270,'fpy':243,'Ept':28500,
    'ecl':0.002,'ag':0.75,'lam':1,'phi_v':0.9,'gamma_e':0.75,
    'codeEdition':'AASHTO','sectionClass':'NP',
    'secType':'RECTANGULAR',
    'b':24,'h':36,'bw_input':24,'hf_top':0,'hf_bot':0,
    'cover':2,'barN':7,'nBars':4,'ds':33.57,'As_comp':0,
    'nStrands':0,'strand_area':0.217,'dp':30,'ductDia':0,
    'shN':4,'shear_legs':2,'s_shear':12,
    'tN':4,'s_torsion':12,
}
demands = [{'Pu':0,'Mu':2000,'Vu':80,'Tu':800,'Vp':0,'Ms':1200,'Ps':0}]
res = calc_engine.calculate_all(rect_inputs, demands, 0)
sh = res['shear']
tor = res['torsion']
print('=== Rect Section (Tu=800) ===')
print('Veff=%.2f, torsion_consider=%s' % (sh['Veff'], sh['torsion_consider']))
print('Tn(torsion)=%.1f, Tr=%.1f' % (tor['Tn'], tor['Tr']))
print('Av_s_prov=%.5f, Av_s_shear=%.5f' % (tor['Av_s_prov'], tor['Av_s_shear']))
print('At_s_avail=%.5f (per leg after shear)' % tor['At_s_avail'])
shear_util = tor['Av_s_shear'] / tor['Av_s_prov'] * 100 if tor['Av_s_prov'] > 0 else 0
print('Shear utilization: %.1f%%' % shear_util)
print('Tu=%.1f, Tr >= Tu? %s' % (800, tor['Tr'] >= 800))

# Test 2: T-section with torsion
t_inputs = dict(rect_inputs)
t_inputs['secType'] = 'T_SECTION'
t_inputs['bw_input'] = 12
t_inputs['hf_top'] = 6
t_inputs['hf_bot'] = 6
t_inputs['b'] = 48
res2 = calc_engine.calculate_all(t_inputs, demands, 0)
sh2 = res2['shear']
tor2 = res2['torsion']
print('=== T-Section (Tu=800) ===')
print('Veff=%.2f, torsion_consider=%s' % (sh2['Veff'], sh2['torsion_consider']))
print('Tn(torsion)=%.1f, Tr=%.1f' % (tor2['Tn'], tor2['Tr']))
print('Av_s_prov=%.5f, Av_s_shear=%.5f' % (tor2['Av_s_prov'], tor2['Av_s_shear']))
print('At_s_avail=%.5f' % tor2['At_s_avail'])

# Test row results
for i, r in enumerate(res['row_results']):
    print('Row %d: Vr2=%.2f, Tr=%.2f, torsConsider=%s' % (i, r['Vr2'], r['Tr'], r['torsionConsider']))
for i, r in enumerate(res2['row_results']):
    print('T-Row %d: Vr2=%.2f, Tr=%.2f, torsConsider=%s' % (i, r['Vr2'], r['Tr'], r['torsionConsider']))

# Test 3: No torsion case (should not affect existing calcs)
demands_no_tors = [{'Pu':0,'Mu':2000,'Vu':80,'Tu':0,'Vp':0,'Ms':1200,'Ps':0}]
res3 = calc_engine.calculate_all(rect_inputs, demands_no_tors, 0)
sh3 = res3['shear']
print('=== No Torsion ===')
print('Veff=%.2f (should equal |Vu|=80)' % sh3['Veff'])
print('torsion_consider=%s (should be False)' % sh3['torsion_consider'])
print('ld_T_tors=%.2f (should be 0)' % sh3['ld_T_tors'])
assert abs(sh3['Veff'] - 80) < 0.01, 'Veff should equal |Vu| when no torsion'
assert sh3['torsion_consider'] == False, 'Should not consider torsion when Tu=0'
assert sh3['ld_T_tors'] == 0, 'ld_T_tors should be 0 when no torsion'

print('\nALL TESTS PASSED')
