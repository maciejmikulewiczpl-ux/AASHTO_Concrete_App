import math, sys
sys.path.insert(0, ".")
from calc_engine import build_pm_curve, derive_constants, BARS

def MI(h, b, **kw):
    fc=kw.get('fc',4); fy=kw.get('fy',60); Es=29000; Ec=2500*fc**0.33; fpu=270; fpy=0.9*fpu; Ept=28500
    secType=kw.get('secType','RECTANGULAR'); bw_input=kw.get('bw_input',b)
    hf_top=kw.get('hf_top',0); hf_bot=kw.get('hf_bot',0); cover=2.0
    barN_bot=kw.get('barN_bot',8); nBars_bot=kw.get('nBars_bot',4)
    barN_top=kw.get('barN_top',0); nBars_top=kw.get('nBars_top',0)
    bar_bot=BARS.get(barN_bot,BARS[8]); bar_top=BARS.get(barN_top,None)
    sh_bar=BARS[4]; db_stir=sh_bar['d']
    d_bot=h-cover-db_stir-bar_bot['d']/2
    d_top=cover+db_stir+(bar_top['d']/2 if bar_top else 0)
    return dict(fc=fc,fy=fy,Ec=Ec,Es=Es,fpu=fpu,fpy=fpy,Ept=Ept,ecl=0,etl=0,ecl_override=False,etl_override=False,
        ag=0.75,lam=1.0,phi_v=0.9,gamma_e=0.75,codeEdition='AASHTO',sectionClass='RC',
        secType=secType,b=b,h=h,bw_input=bw_input,hf_top=hf_top,hf_bot=hf_bot,cover=cover,
        barN_bot=barN_bot,nBars_bot=nBars_bot,d_bot=d_bot,
        barN_top=barN_top,nBars_top=nBars_top,d_top=d_top,
        nStrands=0,strand_area=0,dp=0,ductDia=0,shN=4,shear_legs=2,s_shear=12,tN=4,s_torsion=12)

raw = MI(h=36, b=36, secType='T-SECTION', bw_input=12, hf_top=8, hf_bot=8,
         barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4)
I = dict(raw)
derive_constants(I)
h = I["h"]
print(f"As_bot={I['As_bot']:.3f} As_top={I['As_top']:.3f}")
print(f"d_bot={I['d_bot']:.4f} d_top={I['d_top']:.4f} h-d_top={h - I['d_top']:.4f}")
print(f"d_bot == h-d_top ? {abs(I['d_bot'] - (h - I['d_top'])) < 0.001}")

pm_sag = build_pm_curve(I, 'top')
pm_hog = build_pm_curve(I, 'bottom')

mid = len(pm_sag)//2
print(f"\nSag mid[{mid}]: c={pm_sag[mid]['c']:.3f} a={pm_sag[mid]['a']:.3f} Pn={pm_sag[mid]['Pn']:.0f} Mn={pm_sag[mid]['Mn']:.0f} Mr={pm_sag[mid]['Mr']:.1f}")
print(f"Hog mid[{mid}]: c={pm_hog[mid]['c']:.3f} a={pm_hog[mid]['a']:.3f} Pn={pm_hog[mid]['Pn']:.0f} Mn={pm_hog[mid]['Mn']:.0f} Mr={pm_hog[mid]['Mr']:.1f}")

# Detailed comparison at mid
s = pm_sag[mid]
hg = pm_hog[mid]
print(f"\nSag: d_tens={I['d_bot']:.4f} d_comp={I['d_top']:.4f}")
print(f"Hog: d_tens={h-I['d_top']:.4f} d_comp={h-I['d_bot']:.4f}")

# Check if dt_bc differs
dt_sag = I['d_bot']
dt_hog = h - I['d_top']
print(f"\ndt_sag (max of d_tens)={dt_sag:.4f}")
print(f"dt_hog (max of d_tens)={dt_hog:.4f}")
print(f"These should be equal for symmetric: {abs(dt_sag - dt_hog) < 0.001}")

# Check Ag
b_val = I['b']
bw_val = I['bw']
hf_top = I['hf_top']
hf_bot = I['hf_bot']
Ag = b_val * hf_top + bw_val * (h - hf_top - hf_bot) + b_val * hf_bot
print(f"\nAg = {Ag:.1f}")
print(f"Sag Pn_max row: Pr={pm_sag[0]['Pr']:.0f}")
print(f"Hog Pn_max row: Pr={pm_hog[0]['Pr']:.0f}")

# Compare a few points
for i in [5, 10, 15, 20, 30, 35, 40]:
    if i < len(pm_sag):
        ps = pm_sag[i]
        ph = pm_hog[i]
        print(f"  pt{i}: sag(c={ps.get('c',0):.3f},a={ps.get('a',0):.3f},Pn={ps['Pn']:.0f},Mn={ps['Mn']:.0f},phi={ps.get('phi',0):.4f}) hog(c={ph.get('c',0):.3f},a={ph.get('a',0):.3f},Pn={ph['Pn']:.0f},Mn={ph['Mn']:.0f},phi={ph.get('phi',0):.4f})")
