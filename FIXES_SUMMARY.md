# AASHTO Concrete App - Recent Fixes & Testing Guide

---

## AASHTO Citation Audit — completed 2026-05-14 (D1–D20)

A 20-decision audit started on 2026-05-13 and finalized on 2026-05-14, covering
every AASHTO citation in `calc_engine.py`, `pt_engine.py`, and `index.html`.
All decisions implemented; full test suite (17 stages, 233 pytest cases + 6
verification scripts) PASSES.

**Calculation changes (numerical impact):**

| # | Change | Impact |
|---|---|---|
| D1 | Eq. 5.7.3.6.3-1 Nu term: `ld_N = 0.5·Pu/φ_for_N` where φ = φ_c when Pu<0 (compression), φ_f when Pu>0 (tension). | Tension cases shift slightly (favorable, since φ_f ≥ φ_c); compression unchanged. |
| D3/D4 | `fr = 0.24·λ·√fc'` (per AASHTO 5.4.2.6). λ multiplier was missing. | Lightweight concrete: lower Mcr, lower service stress threshold, slightly different εs. NW unchanged. |
| D15 | `Av_min` and `min_trans = 0.0316·λ·√fc'·bv·s/fy` (per 5.7.2.5-1). λ missing. 3 sites. | Lightweight: easier to satisfy min transverse. NW unchanged. |
| D17 | I-section torsion: `Tcr` uses full Acp/pc; `Ao` uses web-only sub-section (Acp_web=bw·h, pc_web=2(bw+h), be_web=Acp_web/pc_web, Ao=(bw−be_web)·(h−be_web)). 3 sites. Drops the previous `max(...)` heuristic. | I-section with torsion considered: lower Ao → lower Tn → higher torsion utilization (more conservative). Rectangular unchanged. |
| D19 | `lookup_b5` invalidates Method 3 for ANY out-of-bounds input (vu/fc, sxe, εx<−0.20) instead of silently clamping; reason string surfaces in the report. | Method 3 may now be flagged "not applicable" in cases that previously got an extrapolated edge-value answer. Methods 1 and 2 unchanged. |

**Display/UI changes:**

- D2 — Eq. 5.7.3.6.3-1 breakdown now shows the actual φ value used per term (φ_f, φ_v, sign-dependent φ for N).
- D8 — Expanded I-section warning in the torsion report (covers Veff, Ao, Eq. 5.7.3.6.3-2 box-only, plus the I-section-as-solid assumption).
- D16 — HTML "min transverse" check (inline + PDF report) now compares against `Av + 2·At` (additional torsion stirrups normalized to s_shear), not just Av. Label was already "Av+2At required" but the prior check ignored At.
- D18 — Torsion report explicitly states the Tcr-full / Tn-web split for I-sections.

**Doc-only:**

- D5/D6/D7 — kc per AASHTO 10th Ed §5.6.4.4 confirmed identical to α₁ per §5.6.2.2; comment strengthened.
- D9 — `get_phi_flex` docstring documents the bonded-PT assumption (engine has no bond-type input; users with unbonded PT must override φ_f).
- D10/D11/D12 — AASHTO + Caltrans `get_phi_flex` curves verified correct under the bonded assumption. No formula change.
- D13/D14 — γ1 (1.6 default) and γ2 (1.1 default) comments strengthened with override notes (segmental → 1.2; unbonded → 1.0).
- D20 — B5 tables block tagged as AASHTO LRFD 10th Ed Tables B5.2-1 / B5.2-2; full transcription verified cell-by-cell against PDF (all 320 values match).

**New pinning tests (in `tests/test_invariants.py`):**

- `test_fr_scales_with_lambda` — verifies D3/D4
- `test_av_min_scales_with_lambda` — verifies D15
- `test_long_comb_Nu_phi_sign_dependent` — verifies D1

**Modified test (boundary-case adjustment):**

- `test_lightweight_concrete_reduces_Vc` — now uses #5 stirrups so both NW and LW cases stay on the same side of the has_min_av boundary. With D15 making Av_min itself λ-dependent, the prior fixture (default #4 stirrups) inadvertently straddled the boundary, causing β to invert via the General Procedure. Behavior change is real and correct.

**Files NOT touched in this audit:** `pt_engine.py`, `api.py`, `app.py`, the verification scripts at project root.

---

## CRITICAL REGRESSION GUARD — Al box-section checks (2026-05-13)

> **DO NOT re-add `Al_tors`, `Al_min`, `Al_gov` or any AASHTO Eq. 5.7.3.6.3-2 implementation to `do_torsion` in `calc_engine.py`.** This has now been removed **TWICE**. See full details in `CODE_PROTECTION.md` § "Removed checks — DO NOT re-add".

**Why they keep getting added back**

AASHTO LRFD 5.7.3.6 talks about both transverse (At) and longitudinal (Al) torsion reinforcement. When an AI assistant or engineer reads §5.7.3.6 with a checklist mindset, the Al equations look "missing" and there's a temptation to add them. They are NOT missing — they are intentionally absent because this app does not model box sections.

**The cycle so far**

1. **Initial commit `0bd99ec`**: app shipped with `Al_tors`/`Al_min`/`Al_gov` implementing Eq. 5.7.3.6.3-2.
2. **Commit `7939745`** ("Add longitudinal reinforcement ASTM grade options with gamma3 factors"): the Al block was REMOVED — Eq. 5.7.3.6.3-2 is box-only.
3. **A prior AI-assisted session**: re-added `Al_tors`/`Al_min`/`Al_gov` while "fixing missing HTML report keys", citing a non-existent "Eq. 5.7.3.6.3-3" for the minimum.
4. **2026-05-13 (this session)**: removed AGAIN, replaced with an I-section warning + full Eq. 5.7.3.6.3-1 breakdown.

**What is allowed**

- `long_dem_comb`, `long_cap_val`, `long_comb_ok` — the AASHTO **Eq. 5.7.3.6.3-1** combined longitudinal check. **This stays.** It is the AASHTO requirement applicable to solid and I sections.
- `breakdown_long_comb` — the symbolic+numeric equation breakdown for Eq. 5.7.3.6.3-1.
- An I-section warning rendered in the torsion report when `secType !== 'RECTANGULAR'` AND `tor.consider === true`.

**What is NOT allowed without explicit user approval**

- Re-introducing `Al_tors`, `Al_min`, `Al_gov` in any form.
- Implementing AASHTO Eq. 5.7.3.6.3-2 (box-section longitudinal A_l).
- Inventing a "5.7.3.6.3-3" minimum-Al formula — **no such equation exists** in current AASHTO LRFD.
- Removing or weakening `tests/test_invariants.py::test_al_keys_removed_from_torsion`.

**Regression test pinning this**

`tests/test_invariants.py::test_al_keys_removed_from_torsion` will FAIL if any of these keys come back. Do not skip or modify this test without owner approval.

---

## 1. Problem: "None" Shear Reinforcement Breaking Calculations

**Root Cause**: When user selects "None" for shear bar size, the JavaScript sends `shN=0` to Python. However, `calc_engine.py` expects `shN` to be a valid BARS key {2,3,4,5,6,7,8,9,10,11,14,18}. The `.get()` method with default fallback wasn't being reached because the value 0 was invalid.

**Impact**: All calculations (flexure, shear, torsion, service) failed silently with no results displayed.

---

## 2. Solution Implemented

### Fix #1: Frontend Remapping (index.html, line 1493)
```javascript
const tN=(shN===0)?4:shN; // Default to #4 if None selected, for Python processing
```
When torsion bar number is 0 (None), remap to #4 (valid BARS key).

### Fix #2: Frontend Return Value Remapping (index.html, line 1515)
```javascript
return {
  ...,
  shN:(shN===0)?4:shN,  // Remap shN before sending to Python
  shear_legs,s_shear,tN,s_torsion,
  ...
};
```
Ensures the input object sent to Python contains valid bar designations.

**Implementation Details**:
- When user selects "None" (UI displays empty/null), dropdown value is 0
- JavaScript converts shN=0 → 4 before sending JSON to Python
- Python receives shN=4, looks up BARS[4] successfully
- UI still shows "None" to user—only internal communication is remapped
- When no shear reinforcement: `shear_legs=0` or `s_shear=0` makes `Av=0` in calc_engine

---

## 3. Auto-Calculate Feature Implementation

### Feature: Calculations Run Automatically on Input Change

**Implementation** (index.html, lines 526-537):

```javascript
let _calcDebounceTimer=null;
const _debounceDelay=400; // milliseconds

function debouncedCalculate(){
  if(_calcDebounceTimer) clearTimeout(_calcDebounceTimer);
  _calcDebounceTimer=setTimeout(()=>{ 
    runAllCalculations(); 
    _calcDebounceTimer=null; 
  }, _debounceDelay);
}

function setupAutoCalculate(){
  // Event delegation: attach listeners to document for input/select changes
  document.addEventListener('change', (e)=>{
    if(e.target.matches('input[type="number"], input[type="text"], select, input[type="checkbox"]')){
      debouncedCalculate();
    }
  });
  document.addEventListener('input', (e)=>{
    if(e.target.matches('input[type="number"], input[type="text"]')){
      debouncedCalculate();
    }
  });
}
```

**Benefits**:
- Changes trigger calculation after 400ms delay (prevents excessive calculations while typing)
- Works with any input: numbers, text, select dropdowns, checkboxes
- Event delegation means dynamically added elements are automatically handled
- Debouncing prevents performance issues

**Activation** (index.html, line 3089):
```javascript
window.addEventListener('load',()=>{
  updateSectionFields();
  updatePTFields();
  addDemandRow(0,6953,108,0,0,2500,-100);
  setupAutoCalculate();  // ← Activated here
  runAllCalculations();
});
```

---

## 4. Testing Checklist

### Test 1: "None" Shear Reinforcement Selection
- [x] Code fixes applied to index.html
- [ ] App restarted with new code
- [ ] Select "None" from shear bar dropdown
- [ ] Verify:
  - ✓ d_top/d_bot display correctly (should be cover + bar_diameter/2)
  - ✓ No stirrups appear in cross-section diagram
  - ✓ All calculations display (flexure, shear M1/M2/M3, torsion, service)
  - ✓ Capacity checks work correctly

### Test 2: Auto-Calculate Feature
- [ ] App running with new code
- [ ] Change a concrete strength input (fc) → verify calculation runs ~400ms later
- [ ] Change bar selection → verify calculation runs immediately after selection
- [ ] Type slowly in a number field → verify calculation doesn't run with each keystroke (only after 400ms pause)
- [ ] Change multiple inputs rapidly → verify debounce prevents excessive calculations

### Test 3: Equation Breakdowns
- [ ] Enable "Show Detailed Equation Breakdowns" checkbox
- [ ] Verify flexure breakdown displays step-by-step calculations
- [ ] Verify shear breakdowns display (M1, M2, M3 methods)
- [ ] Verify torsion breakdown displays
- [ ] Verify service stress breakdowns display

### Test 4: Edge Cases
- [ ] Select "None" + zero flexure bars → verify no crashes
- [ ] Select "None" + no PT strands → verify works correctly
- [ ] Auto-calculate with various section types (Rectangular, T-section, Box)
- [ ] Demand row operations (add/remove rows) → verify calculations respond

---

## 5. Code Locations

| Feature | File | Lines | Details |
|---------|------|-------|---------|
| shN remapping | index.html | 1493, 1515 | Remap shN=0→4 in gatherInputs() |
| Auto-calc debounce | index.html | 526-530 | debouncedCalculate() function |
| Auto-calc setup | index.html | 533-544 | setupAutoCalculate() function with event delegation |
| Auto-calc activation | index.html | 3089 | Called during window load |
| Backend handling | calc_engine.py | 242 | `BARS.get(I["shN"], BARS[4])` has fallback |
| d_top/d_bot when None | index.html | 1455, 1460 | Auto-calc ignores db_stir when shBar null |
| Cross-section rendering | index.html | 568-570 | Conditional: `if(db_stir>0){ /*draw stirrup*/ }` |

---

## 6. Key Design Decisions

1. **Frontend Remapping vs Backend Fallback**: 
   - Decision: Remap in frontend for clarity and control
   - Reason: Backend already has fallback; frontend is more transparent to developers

2. **Event Delegation vs Direct Listeners**:
   - Decision: Use event delegation
   - Reason: Works with dynamically added elements; doesn't require re-attachment

3. **400ms Debounce Delay**:
   - Decision: 400ms chosen
   - Rationale: Allows natural typing speed without lag; prevents excessive calc_engine calls

4. **"None" Option Strategy**:
   - When shear_legs=0 or s_shear=0 in Python, Av automatically becomes 0
   - No special "no shear reinforcement" logic needed in Python
   - shN=4 (default bar) is placeholder when user selects "None"

---

## 7. Verification Script (test_none_shear.py)

A test script has been created to verify the backend handles the remapped values correctly:
```bash
cd 'c:\Users\maciej.mikulewicz\Test\Concrete app'
python test_none_shear.py
```

*Note: Script requires complete input dictionary matching gatherInputs() output structure*

---

## 8. Next Steps

1. ✓ Code changes completed
2. ✓ App restarted (terminal running)
3. [ ] Manual testing via app UI (required)
4. [ ] Verify all calculations display with None selected
5. [ ] Test auto-calculate responsiveness
6. [ ] Edge case testing

**Status**: Ready for user testing. App (app.py) is running in background terminal.
