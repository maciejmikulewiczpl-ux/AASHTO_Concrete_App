# Independent Deep Review — Findings Report

**Date:** 2026-06-11 (overnight session)
**Reviewer:** Claude (Fable 5) — independent review requested by owner; no app code was modified.
**Scope:** Every calculation in `calc_engine.py`, `pt_engine.py`, `api.py`; report-tool consistency in `index.html`; JS↔engine data flow; test suite.

---

## How this review was done

1. **Full code read** of `calc_engine.py` (3,607 lines), `pt_engine.py`, `api.py`, `app.py`, and the
   input-gathering / rendering / report-generation layers of `index.html`.
2. **Independent re-implementation** of the calculations (separate scratch scripts, written from
   first principles, own interpolation code, own iteration loops) compared value-by-value against
   engine output. Coverage:
   - Flexure: rectangular & T-section (block in flange AND genuinely into web), sagging/hogging,
     asymmetric flanges, compression-steel yield logic, PT (k, fps, c with PT denominator),
     PT-in-compression-zone exclusion.
   - P-M: pure-compression cap (Eq. 5.6.4.4-3 incl. PT term), key points (zero tension, balanced,
     TC limit, pure flexure, pure tension), display curve, equilibrium interpolation, multi-row.
   - Shear: **all 3 methods, every intermediate value, across a 24-case matrix** — sag/hog ×
     axial tension/compression × {min stirrups, sub-minimum, none} × {RC, PT (fpo, Vp)} ×
     {rect, I-section} × {with/without torsion (Veff)} + forced edge regimes (εs<0 recalc,
     εs=0.006 cap, Vnmax cap, dbl_eps). Zero mismatches vs the engine's stated formulation.
   - Method 3 (B5): independent bilinear interpolation (exact match at table corners and interior
     points), independent fixed-point iteration, validity gating both directions.
   - Torsion: Tcr, threshold, Ao/be/ph (rect + I-section web-only), Veff, stirrup apportioning
     (2 external legs, multi-leg pro-rating), At required, combined checks, additional torsion bars.
   - Service: cracked-section NA & Icr (rect + T with NA in web), fss incl. axial term, crack
     control (dc, βs, s limits both modes), Branson Ieff, Mcr/fcpe, spacing checks.
   - Materials/derived: α1, β1, εcl/εtl interpolation, k, Ec (5.4.2.4-1), φ curves for all
     edition × class combinations (AASHTO/CA × RC/PP/CIP_PT), I-section Ag/Ig/centroid.
   - pt_engine: parabola geometry & slopes, friction at multiple points, anchor-set
     **energy-balance integral closes to 0.01%**, reflection property, ES iteration residual ≈ 0,
     ΔfpLT exact, Vp/dp clamp/dual-end envelope, interpolation helpers.
   - Physics invariants: εs/Vc monotonic with axial load, PT raises Vc, symmetric-section
     sag↔hog Vr identical, Pu beyond pure-tension capacity → Mr=0 → NG.
3. **Report-tool audit**: automated key-coverage scan (~225 distinct keys accessed by the UI/PDF
   renderers — **all exist in engine output, none missing**) plus a line-by-line read of
   `generateReport()` for recomputation drift, branch errors, and unit handling.
4. **Test suite**: 346 pytest cases + 1 skip pass; all 9 verification scripts pass
   (~51,000 assertions).

**Bottom line:** the engine implements its stated formulation *exactly* — no coding slips were
found anywhere in flexure, P-M, shear, torsion, service, or PT losses. All findings below are
either (a) specification-level questions to verify against the printed AASHTO text, or
(b) internal inconsistencies between parallel code paths / between engine and report.

---

## CRITICAL — verify against the printed AASHTO LRFD 10th Ed. before relying on Method 2 shear

### F1. Method-2 (General Procedure) εs denominator is doubled when minimum stirrups are present

`calc_engine.py:2476` (`eps_denom = 2 * denom if has_min_av else denom`) and duplicate at
`calc_engine.py:3189`; related εs<0 recalc at `calc_engine.py:2482` / `calc_engine.py:3199`.

- As the reviewer recalls AASHTO §5.7.3.4.2 (8th/9th Ed., Eq. 5.7.3.4.2-4), the strain is
  εs = (|Mu|/dv + 0.5Nu + |Vu−Vp| − Aps·fpo) / (Es·As + Ep·Aps) — **a single denominator, no
  factor-2 variant**. The factor 2 belongs to **Appendix B5's εx** (mid-depth strain, with-min-Av
  table) — which Method 3 in this app already implements correctly. The β = 4.8/(1+750εs) and
  θ = 29+3500εs closed forms are calibrated to εs at the tension steel (they are the CSA εx
  equations with constants pre-converted: 750 = 1500/2, 3500 = 7000/2). Halving εs again
  double-counts the conversion.
- **Evidence inside the app itself:** the PDF report (index.html:6709, :6715) and the inline tab
  (index.html:4852) both display the Method-2 equation and denominator **without** the factor 2
  (`sh.denom`), so the report's printed numbers do not reproduce the printed εs. Meanwhile the B5
  panel correctly labels its denominator "2(EsAs+EpAps)" (index.html:4887). The factor-2 branch
  dates to the initial commit and was not covered by the D1–D20 audit. The two internal code
  comments contradict each other ("-5" is cited both as the no-min-Av strain equation at
  calc_engine.py:2474 and as the Veff equation at calc_engine.py:2414).
- **Quantified effect** (engine Vr2 vs single-denominator calculation, 24-case matrix):

  | Condition | Vr2 deviation |
  |---|---|
  | No stirrups / sub-minimum stirrups | 0.0 % (identical) |
  | εs < 0 (heavy compression, strong PT) | 0 to −1 % (slightly conservative) |
  | εs at 0.006 cap or Vnmax cap governing | 0.0 % |
  | Sag/hog, min stirrups, moderate moment | **+21 to +25 % (unconservative)** |
  | + axial tension | **+34 %** |
  | I-section hogging (small As,top) | **+48 %** |

- The suspect regime (min stirrups present, εs > 0) is the **common design case**, and Method 2
  drives the row shear status, sh_reqd, the torsion θ, and the longitudinal-reinforcement check.
- **Action:** check §5.7.3.4.2 in the 10th Ed. PDF. If it shows a single denominator, fix the two
  εs sites (+ the εs<0 variants) and update the pinned tests. Per the project's verifiable-citation
  rule, this report does NOT assert the 10th-Ed. text — it flags the discrepancy and its size.

---

## HIGH — engine findings (verify / fix after review)

### F2. γ3 in Mcr taken from the mild-steel ASTM map even for prestressed sections
`calc_engine.py:1735` (and row-level duplicate at `calc_engine.py:3378`). γ3 defaults to 0.67
(A615 Gr 60) regardless of `sectionClass`. Reviewer's recollection of Table 5.6.3.3-1 is
**γ3 = 1.00 for prestressed structures**; 0.67 lowers Mcr by a third and weakens the
minimum-reinforcement check for PP/CIP_PT sections (unconservative). Verify against the printed
table. Overridable today via `gamma3_f`, but the default matters.

### F3. fcpe for hogging uses the wrong sign on the eccentricity term  *(found in overnight pass)*
`calc_engine.py:1766-1771`: fcpe = P/Ag **+** P·e·yt/Ig for both faces; only the fiber distance
is swapped by Mu sign. At the **top** fiber (hogging tension face) the eccentricity term should
**subtract** (tendon below centroid decompresses the bottom, not the top). Example (16×28 rect,
10×0.217 in² at dp=22, fpe=160): engine fcpe = 2.10 ksi for hogging where the correct top-fiber
value is 0 (net tension → clamp). Effect: hogging Mcr overstated → min-flex check too strict
(conservative direction, but wrong, and the displayed Mcr/fcpe are misleading). The PDF report
echoes the same "+" formula (index.html:6534).

### F4. Sc for Mcr is not selected by bending direction  *(found in overnight pass)*
`calc_engine.py:1739-1751`: Sc = I/max(yb, h−yb) — the **minimum** section modulus — used for both
sagging and hogging. For asymmetric I-sections the hogging tension face can have the larger S
(verified example: S_top = 10,428 in³ vs engine Sc = 6,940 in³). Understates hogging Mcr →
unconservative for the min-reinforcement check (partially offset by F3 overstating fcpe — the two
errors interact). Rectangular sections unaffected. The fcpe yt selection (F3 line) IS sign-aware,
so the Mcr assembly currently mixes a sign-aware fcpe distance with a sign-blind Sc.

### F5. Per-row status lights diverge from the active-row analysis
`compute_row_capacities` re-implements checks with simplifications that disagree with
`do_flexure`/`do_shear` for identical demands:
- **Row Mcr omits the γ2·fcpe prestress term** (`calc_engine.py:3394`): for the PT test case,
  row Mcr = 1,076 kip-in vs 5,085 kip-in in the full check → row "MIN" flag can disagree with the
  active-row report in either direction.
- **Row ld_N always uses φc = 0.75** (`calc_engine.py:3432`) while audit D1 made `do_shear` use
  φf for tension (`calc_engine.py:2692`). Conservative, but D1 landed in only one of two sites.
- **Row crack check uses the rectangular cracked-section quadratic for I-sections too**
  (`calc_engine.py:3324`), and skips entirely when nBars ≤ 1.
- **Row Mn for dv**: compression steel omitted in the rect branch but *subtracted* with arm
  (ds − cover) in the T-branch (`calc_engine.py:3145`) — the sign of that term looks wrong;
  affects only dv (conservatively), not capacity.

### F6. Hogging "Pure Tension" P-M key point has flipped moment sign
`calc_engine.py:1177`: bar positions converted to from-top coordinates AND multiplied by m_sign —
a double conversion. For an asymmetric section the hogging curve's pure-tension point is
Mn = +1366 while the key-point table shows −1366 (verified numerically). Display-level only; the
key-point table contradicts the plotted curve.

---

## REPORT-TOOL CONSISTENCY (generateReport / inline tabs)

Verified clean: all ~225 engine keys accessed by renderers exist; PDF report values are faithful
echoes of engine values (no silent recomputation of capacities); the D16 "provided Av+2At"
recompute from DOM inputs is unit-safe; PT loss report (§14) matches the verified pt_engine
values; per-row service stress breakdown uses the engine's curvature consistently.

Issues found:

- **R1. Method-2 strain display contradicts the value** — PDF report (index.html:6709/6715) and
  inline tab (index.html:4852) print the εs equation/denominator WITHOUT the factor 2 next to an
  εs computed WITH it (when min Av present). A reader re-doing the printed math gets 2× the
  printed εs. (Same root cause as F1; whichever way F1 resolves, display and engine must agree.)
- **R2. B5 "not valid" message always blames the εx limit** — index.html:6740 (PDF) and :4894
  (inline badge) hardcode "εx exceeds the table range limit", but `sh.b5_invalid_reason` can be a
  vu/f'c or sxe bound (post-D19). The engine string exists and should be displayed instead.
  Related: `full_verification.py` prints misleading "B5 should converge, n_iter=1" warnings for
  what are actually deliberate validity exits.
- **R3. Report header says "AASHTO LRFD 9th Edition"** (index.html:6280) while the engine and
  audit documentation are 10th-Ed. based.
- **R4. Report input-echo uses display-unit values with engine-unit labels** —
  `generateReport` reads inputs via `V()` (display units) but RR labels them 'ksi'/'in'
  (engine units), and the report div is later re-walked by `convertRenderedOutputs`. Correct at
  default kip/in units; wrong values whenever the user switches the unit toggle to lbf or ft.
  Should use `VE()` like `gatherInputs` does.
- **R5. T-section report branches test `fl.a <= hf_top` regardless of compression face**
  (index.html:6379, :6457) — for hogging I-sections with unequal flanges the displayed equation
  branch can be wrong (values shown remain correct; engine used `fl.hf`, which is available).
- **R6. Minor label issues**: "0.5Nu/φc" label at index.html:6831 (engine value is sign-dependent
  per D1 — value right, label stale); γ3 annotated by fy grade (index.html:6529) though it is
  selected by ASTM spec; Vs cited as "C5.7.3.3-1" and vu as "B5.2-1" in places — citation labels
  worth a pass against the PDF (project citation rule).

---

## MINOR / DOCUMENTATION-LEVEL NOTES

1. **dc omits the stirrup diameter** (`calc_engine.py:1782`): dc = cover + db/2, while the UI's
   auto bar depth is cover + db_stir + db/2. Slightly understates dc → slightly long allowed
   crack spacing. Same in the row check.
2. **Cracked-section axial term** uses transformed area `nAs + nAps + c_cr·b`
   (`calc_engine.py:1860`) — full flange width even when c_cr is in the web of an I-section.
3. **Method 1 offered without applicability limits**: β=2/θ=45° is blind to axial tension/PT.
   In the heavy-tension test case Vr1 = 84.5 vs Vr2 = 54.0 kip (+56%). Consider a UI warning or
   suppressing M1 when Aps > 0 or Pu > 0 (§5.7.3.4.1 scope).
4. **B5 εx is never doubled** for the cracked-compression-face axial-tension case (Method 2 does
   double εs). If B5 carries the equivalent provision, M3 is unconservative in that corner —
   in practice the εx limit usually invalidates M3 there anyway. Verify against B5 text.
5. **εs<0 recalc denominator (min-Av branch)** uses 2(EsAs+EpAps)+EcAct — more conservative than
   the commentary form (EsAs+EpAps+EcAct); part of the F1 family.
6. **Mu_c and strain numerators use Veff** (torsion-inflated) where the code text uses Vu —
   deliberate, conservative.
7. **Vp always taken as |P·sinθ|** and always favorable (pt_engine.py:570) — true for typical
   drapes; could be unconservative where shear sign reverses relative to the drape. Worth a UI
   caveat.
8. **Torsion Tcr uses K=1** (ignores prestress enhancement) — conservative.
9. **Combined V+T stress check** `Vu/(bv·dv) + Tu·ph/(1.7Aoh²) ≤ 0.25f'c`
   (`calc_engine.py:3005`): linear sum of factored demands with no φ — conservative, but the
   reviewer could not tie it to a specific AASHTO equation; per the project citation rule it
   should carry an "unverified" flag where labeled (report cites §5.7.3.6.1).
10. **I-section P-M deep-compression region** ignores far-flange overhangs until a ≥ h
    (Cw = bw·a) then jumps to full Ag — conservative in between, small Pn discontinuity near
    full compression.
11. **Mcr_serv for Branson Ieff** ignores prestress and uses min-S — conservative for deflection.
12. **Dead code**: unreachable `return profile` after `return parabolas` (pt_engine.py:208).
13. **Row eps_t uses ds (mild steel) not dt = max(ds, dp)** (`calc_engine.py:3427`) — affects
    only the row-level φf for ld_M; minor.

---

## VERIFIED-CORRECT HIGHLIGHTS (no action needed)

- Whitney-block flexure (rect, T-in-flange, T-into-web, hogging incl. asymmetric flanges) — exact.
- PT flexure: k = 2(1.04−fpy/fpu), c with k·Aps·fpu/dp denominator, fps = fpu(1−k·c/dp) — exact.
- P-M curves: equilibrium at every point checked (incl. I-section with block across the flange),
  Pn_max per Eq. 5.6.4.4-3 incl. PT (fpe − Ep·εcu) term, key points (zero-tension εt=0, balanced
  φ=0.75, TC limit φ=0.9/1.0, pure flexure Pn≈0), Mr@Pu interpolation, out-of-range Pu → 0/NG.
- Shear: all three methods reproduce exactly across the full loading matrix; B5 interpolation,
  iteration, and gating verified independently; εs floor/cap, dbl_eps, Av_min, sxe, Vnmax caps,
  sh_reqd, longitudinal check (5.7.3.5-1 / 5.7.3.6.3-1) structure all correct.
- Torsion: Tcr/threshold, Ao=(b−be)(h−be) (web-only for I — conservative D17 policy), Veff,
  external-leg stirrup apportioning with multi-leg pro-rating, At required, min transverse,
  s_max = min(ph/8, 12), additional dedicated torsion-bar channel — exact.
- Service: cracked NA/Icr (rect + T web), fss, crack control both modes, Branson, spacing — exact.
- pt_engine: geometry, friction, anchor-set energy balance (0.01% closure), ES (=0 for N=1 PT,
  iterative for N>1), ΔfpLT = 10·fpi·(Aps/Ag)·γh·γst + 12·γh·γst + 2.4 — exact.
- φ curves: AASHTO + Caltrans, RC/PP/CIP_PT, all boundary and interpolated values — exact.
- Materials: α1 (incl. >10 ksi), β1 bounds, εcl/εtl interpolation, Ec 5.4.2.4-1 — exact.
- Anti-regression guardrails (no Al for non-box sections) intact and well-defended.
- UI↔engine: gatherInputs uses engine units (VE) correctly; d auto-calc includes stirrup db;
  slab pro-rating, spacing→count, multi-row overrides consistent; renderer key coverage 100%.

---

## HOUSEKEEPING

- **Python environment**: `C:\Python314` reports "Could not find platform independent libraries"
  and resolves its prefix to the CWD — pip installed pytest into **`Lib/` and `Scripts/` inside
  this repo** during the review (now git-ignored; safe to delete once the Python install is
  repaired). `python` resolves to the MS Store stub on this machine; `py -3.14` works.
  `run_test_suite.py` invokes `python` and should be run via `py -3.14 run_test_suite.py --full`.
- `.gitignore` updated (this commit) to exclude `Lib/` and `Scripts/`.
- Review scratch scripts were kept OUT of the repo (in the session temp directory).

## SUGGESTED ORDER OF WORK (for tomorrow's session)

1. Verify F1 against the printed 10th Ed. §5.7.3.4.2 → if confirmed, fix both εs sites + εs<0
   variants + pinned tests (touches `calc_engine.py` in 4 places; report displays then already
   match). **Safety-critical if confirmed.**
2. F3 + F4 together (hogging fcpe sign + sign-selected Sc) — one Mcr block, plus report echo.
3. F2 (γ3 for prestressed) after checking Table 5.6.3.3-1.
4. F5 row/active-row alignment (decide: reuse full functions per-row vs document the deltas).
5. F6 pure-tension key-point sign; R1–R5 report fixes (cheap, display-only).
