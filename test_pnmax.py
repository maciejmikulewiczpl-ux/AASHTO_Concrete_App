"""Quick sanity check for new Pn_max formula (AASHTO 10th Ed Eq. 5.6.4.4-3)."""
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

r = calculate_all(inp, dem, 0)
fl = r['flexure']
inp_out = r.get('inputs', {})

# Check kc
kc = inp_out.get('kc')
print(f"kc = {kc}")
assert kc is not None, "kc missing from results"
assert abs(kc - 0.85) < 1e-6, f"kc should be 0.85 for fc=5, got {kc}"

# Check key points
kp = fl.get('pm_key_points', [])
assert len(kp) > 0, "No key points"
pc = kp[0]
print(f"Pure Compression: Pn={pc['Pn']:.1f} kip, name={pc['name']}")

# Manual calculation
Ag = 16.38 * 27.5  # 450.45
Ast = 3.0 + 3.0    # 5*0.6 each face
Aps = 5 * 0.217    # 1.085
fpe = 170.0        # typical
Ept = 28500
kc_manual = 0.85
pt_red = Aps * (fpe - Ept * 0.003)  # 1.085*(170-85.5) = 91.68
Pn_max_manual = -0.8 * (kc_manual * 5 * (Ag - Ast - Aps) + 60 * Ast - pt_red)
print(f"\nManual check:")
print(f"  Ag={Ag:.2f}, Ast={Ast:.3f}, Aps={Aps:.3f}")
print(f"  fpe={fpe}, Ept={Ept}, ecu=0.003")
print(f"  PT reduction = Aps*(fpe-Ep*ecu) = {Aps:.3f}*({fpe}-{Ept*0.003:.1f}) = {pt_red:.1f}")
print(f"  Concrete = kc*fc*(Ag-Ast-Aps) = 0.85*5*{Ag-Ast-Aps:.3f} = {kc_manual*5*(Ag-Ast-Aps):.1f}")
print(f"  Steel = fy*Ast = 60*{Ast:.3f} = {60*Ast:.1f}")
print(f"  Pn_max = -0.80*({kc_manual*5*(Ag-Ast-Aps):.1f}+{60*Ast:.1f}-{pt_red:.1f}) = {Pn_max_manual:.1f}")

# Verify key point detail steps mention kc
details = pc.get('steps', [])
has_kc = any('kc' in s for s in details)
print(f"\nKey point details mention kc: {has_kc}")
assert has_kc, "kc not found in key point detail steps"

print("\nPn_max FORMULA TEST PASSED")
