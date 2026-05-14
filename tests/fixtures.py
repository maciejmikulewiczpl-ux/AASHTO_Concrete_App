"""
Shared input builders for the test suite.

The `make_inputs()` helper produces a dict that `calc_engine.calculate_all`
will accept. All defaults are picked to be safe / non-trivial so that a
single keyword change exercises a meaningful variation.

Units: kip, inch, ksi.
"""
import math
import os
import sys

# Make the project root importable from inside tests/.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from calc_engine import BARS  # noqa: E402


def make_inputs(
    # Section
    h=36, b=36, secType="RECTANGULAR",
    bw_input=None, hf_top=0, hf_bot=0, cover=2.0,
    # Materials
    fc=4, fy=60, Es=29000, Ec=None,
    fpu=270, fpy=None, Ept=28500,
    ag=0.75, lam=1.0,
    # Reinforcement (flexure)
    barN_bot=8, nBars_bot=4, d_bot=None,
    barN_top=0, nBars_top=0, d_top=None,
    As_top_ovr=None, As_bot_ovr=None,
    # Prestressing
    nStrands=0, strand_area=0.217, dp=0, fpe=0, ductDia=0,
    # Transverse steel
    shN=4, shear_legs=2, s_shear=12,
    tN=4, s_torsion=12,
    # Code factors
    phi_v=0.9, gamma_e=0.75,
    ecl=0, etl=0, ecl_override=False, etl_override=False,
    codeEdition="AASHTO", sectionClass="RC",
    # Optional extras passed through to engine
    **extra,
):
    """Build a minimal input dict compatible with calc_engine.calculate_all."""
    if Ec is None:
        Ec = 2500 * fc ** 0.33
    if fpy is None:
        fpy = 0.9 * fpu
    if bw_input is None:
        bw_input = b
    bar_bot = BARS.get(barN_bot, BARS[8])
    bar_top = BARS.get(barN_top, None)
    sh_bar = BARS.get(shN, BARS[4])
    db_stir = sh_bar["d"]
    if d_bot is None:
        d_bot = h - cover - db_stir - bar_bot["d"] / 2
    if d_top is None:
        d_top = cover + db_stir + (bar_top["d"] / 2 if bar_top else 0)

    inp = dict(
        # Section
        secType=secType, b=b, h=h, bw_input=bw_input,
        hf_top=hf_top, hf_bot=hf_bot, cover=cover,
        # Materials
        fc=fc, fy=fy, Es=Es, Ec=Ec,
        fpu=fpu, fpy=fpy, Ept=Ept,
        ag=ag, lam=lam,
        # Reinforcement
        barN_bot=barN_bot, nBars_bot=nBars_bot, d_bot=d_bot,
        barN_top=barN_top, nBars_top=nBars_top, d_top=d_top,
        As_top_ovr=As_top_ovr, As_bot_ovr=As_bot_ovr,
        # Prestressing
        nStrands=nStrands, strand_area=strand_area, dp=dp, fpe=fpe, ductDia=ductDia,
        # Shear / torsion
        shN=shN, shear_legs=shear_legs, s_shear=s_shear,
        tN=tN, s_torsion=s_torsion,
        # Factors / code
        phi_v=phi_v, gamma_e=gamma_e,
        ecl=ecl, etl=etl,
        ecl_override=ecl_override, etl_override=etl_override,
        codeEdition=codeEdition, sectionClass=sectionClass,
    )
    inp.update(extra)
    return inp


def demand(Pu=0, Mu=0, Vu=0, Tu=0, Vp=0, Ms=0, Ps=0, **extra):
    """Build a single demand row dict.

    Sign convention (matches calc_engine):
      Pu > 0 = compression (per app convention used in test fixtures);
      Pu < 0 = tension.  NOTE: full_verification.py uses Pu<0 for compression
      in some calls — the engine itself does not enforce sign; whichever
      convention you adopt, be consistent.
      Mu > 0 = sagging (compression on top fiber).
      Mu < 0 = hogging.
    """
    d = dict(Pu=Pu, Mu=Mu, Vu=Vu, Tu=Tu, Vp=Vp, Ms=Ms, Ps=Ps)
    d.update(extra)
    return d


# ─── Canonical section catalogue ──────────────────────────────────────
#
# Used by parametrized tests so the same descriptive name shows up
# everywhere ("Rect_TopBot_PT" etc.).

PT_STRAND_AREA = math.pi / 4 * 0.5 ** 2  # 0.5" diameter strand, ~0.196 in^2

SECTION_CATALOGUE = {
    # ── Rectangular ──
    "Rect_BotOnly": dict(
        desc="Rectangular 36x36, 4#8 bot only, no PT",
        h=36, b=36, secType="RECTANGULAR",
        barN_bot=8, nBars_bot=4, barN_top=0, nBars_top=0,
    ),
    "Rect_TopBot_Sym": dict(
        desc="Rectangular 36x36, 4#8 top + 4#8 bot (symmetric)",
        h=36, b=36, secType="RECTANGULAR",
        barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4,
    ),
    "Rect_TopBot_Asym": dict(
        desc="Rectangular 36x36, 3#5 top + 5#7 bot (asymmetric)",
        h=36, b=36, secType="RECTANGULAR",
        barN_bot=7, nBars_bot=5, barN_top=5, nBars_top=3,
    ),
    "Rect_Slim_Deep": dict(
        desc="Rectangular 16x36 (slim/deep)",
        h=36, b=16, secType="RECTANGULAR",
        barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=2,
    ),
    "Rect_Wide_Shallow": dict(
        desc="Rectangular 36x12 (wide/shallow slab strip)",
        h=12, b=36, secType="RECTANGULAR",
        barN_bot=6, nBars_bot=6, barN_top=0, nBars_top=0,
    ),
    "Rect_TopBot_PT": dict(
        desc="Rectangular 36x36, 4#8 top + 4#8 bot + 2-strand PT",
        h=36, b=36, secType="RECTANGULAR",
        barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4,
        nStrands=2, strand_area=PT_STRAND_AREA, dp=28, fpe=170, ductDia=2.0,
        sectionClass="CIP_PT",
    ),
    "Rect_BotOnly_PT": dict(
        desc="Rectangular 36x36, 4#8 bot + 2-strand PT, no top bars",
        h=36, b=36, secType="RECTANGULAR",
        barN_bot=8, nBars_bot=4, barN_top=0, nBars_top=0,
        nStrands=2, strand_area=PT_STRAND_AREA, dp=28, fpe=170, ductDia=2.0,
        sectionClass="CIP_PT",
    ),
    # ── I-sections ──
    "I_Sym_TopBot": dict(
        desc="I-section 36w x 36h, bw=12, hf_top=hf_bot=8, 4#8 top + 4#8 bot",
        h=36, b=36, secType="T-SECTION",
        bw_input=12, hf_top=8, hf_bot=8,
        barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4,
    ),
    "I_Sym_BotOnly": dict(
        desc="I-section 36w x 36h, bw=12, symmetric flanges, 4#8 bot only",
        h=36, b=36, secType="T-SECTION",
        bw_input=12, hf_top=8, hf_bot=8,
        barN_bot=8, nBars_bot=4, barN_top=0, nBars_top=0,
    ),
    "I_Asym_Flanges": dict(
        desc="I-section 36w x 36h, bw=12, hf_top=8, hf_bot=12 (asym flanges)",
        h=36, b=36, secType="T-SECTION",
        bw_input=12, hf_top=8, hf_bot=12,
        barN_bot=9, nBars_bot=6, barN_top=5, nBars_top=4,
    ),
    "I_Sym_TopBot_PT": dict(
        desc="I-section symmetric + 4#8 top + 4#8 bot + 2-strand PT",
        h=36, b=36, secType="T-SECTION",
        bw_input=12, hf_top=8, hf_bot=8,
        barN_bot=8, nBars_bot=4, barN_top=8, nBars_top=4,
        nStrands=2, strand_area=PT_STRAND_AREA, dp=28, fpe=170, ductDia=2.0,
        sectionClass="CIP_PT",
    ),
    "I_Asym_PT": dict(
        desc="I-section asym + 4#8 bot + 2-strand PT (typical PT girder)",
        h=36, b=36, secType="T-SECTION",
        bw_input=12, hf_top=8, hf_bot=12,
        barN_bot=8, nBars_bot=4, barN_top=0, nBars_top=0,
        nStrands=2, strand_area=PT_STRAND_AREA, dp=28, fpe=170, ductDia=2.0,
        sectionClass="CIP_PT",
    ),
}


# ─── Canonical demand catalogue ───────────────────────────────────────
#
# Each entry is a *single-row* demand list, suitable to drop into
# calculate_all().  Multi-row cases are constructed in tests as needed.
#
# Sign convention here follows full_verification.py: Pu>0 means
# axial tension, Pu<0 means axial compression (it's whatever the user
# inputs into a row).  Engine does not enforce a sign.

DEMAND_CATALOGUE = {
    "Pure_Sag":           dict(Pu=0,   Mu=3000,  Vu=100, Tu=0,   Vp=0, Ms=1500, Ps=0),
    "Pure_Hog":           dict(Pu=0,   Mu=-3000, Vu=100, Tu=0,   Vp=0, Ms=1500, Ps=0),
    "Comp_Sag":           dict(Pu=-200, Mu=2000,  Vu=80,  Tu=0,   Vp=0, Ms=1000, Ps=-50),
    "Comp_Hog":           dict(Pu=-200, Mu=-2000, Vu=80,  Tu=0,   Vp=0, Ms=1000, Ps=-50),
    "Tens_Sag":           dict(Pu=50,  Mu=2000,  Vu=80,  Tu=0,   Vp=0, Ms=1000, Ps=10),
    "Tens_Hog":           dict(Pu=50,  Mu=-2000, Vu=80,  Tu=0,   Vp=0, Ms=1000, Ps=10),
    "High_Shear_No_Tor":  dict(Pu=0,   Mu=2000,  Vu=300, Tu=0,   Vp=0, Ms=1000, Ps=0),
    "Small_Tor_Below":    dict(Pu=0,   Mu=2000,  Vu=100, Tu=10,  Vp=0, Ms=1000, Ps=0),
    "High_Shear_Tor":     dict(Pu=0,   Mu=2000,  Vu=300, Tu=200, Vp=0, Ms=1000, Ps=0),
    "Full_Combo":         dict(Pu=-100, Mu=2500, Vu=250, Tu=150, Vp=0, Ms=1200, Ps=-20),
    "Pure_Comp":          dict(Pu=-400, Mu=0,    Vu=0,   Tu=0,   Vp=0, Ms=0,    Ps=-200),
    "Pure_Tens":          dict(Pu=200, Mu=0,    Vu=0,   Tu=0,   Vp=0, Ms=0,    Ps=100),
}


def calc(section_kwargs, dem_row, active=0):
    """Convenience: run one section × one demand row through the engine."""
    from calc_engine import calculate_all
    desc = section_kwargs.pop("desc", "")
    raw = make_inputs(**section_kwargs)
    res = calculate_all(raw, [dem_row], active)
    # restore desc for repeated reuse of the dict
    if desc:
        section_kwargs["desc"] = desc
    return raw, res
