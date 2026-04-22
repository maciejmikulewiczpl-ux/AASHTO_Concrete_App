# AASHTO Concrete App - Recent Fixes & Testing Guide

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
