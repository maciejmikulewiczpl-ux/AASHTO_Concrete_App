# Excel batch runner — design

Date: 2026-11-21 · Status: draft for user review (builder check done; decisions folded in)

## Intent

Let an engineer design many concrete sections from one Excel workbook: fill in one row per
(section, load case), press a button in Excel, and get the app's full results written back into the
workbook, plus a normal `.aashto.json` project file that opens in the app for a detailed look at any
section. It must work on PCs **without Python installed** (colleagues), the same way the app itself
ships as an .exe.

Why: typing many sections into the UI one at a time is slow; a spreadsheet is where section lists and
load tables already live. A later step (out of scope here) will feed this workbook from another
spreadsheet that pulls raw forces from analysis software, so the input layout must be easy to fill by
formula / paste.

## Goals

1. A template macro-enabled workbook (`.xlsm`) with an input sheet, a Settings sheet and a Results sheet.
2. A "Run" button in Excel that runs every row through the existing engine and writes results back.
3. Works without Python on the user's machine (bundled engine executable).
4. Any number of sections; each row can be RECTANGULAR, T-SECTION (I) or CIRCULAR.
5. Several rows with the same Section ID = several demand rows of one section (as in the app).
6. Full numbers in the results (not just pass/fail): flexure, shear, torsion, crack control, service,
   moment–curvature / effective stiffness, with a status per check.
7. One project file containing all sections, openable in the app, named by section ID.
8. User-selectable units (kip-in or kip-ft, matching the app's display-unit choice).

## Non-goals (v1)

- Prestressed sections / PT layout and losses.
- Multi-row rebar layers (`mrData`), per-section overrides of d, Ec, fy, fpy, εcl, εtl.
- Column-on-shaft, CSiBridge/GSA extraction, the optimiser.
- Linking to an analysis-software spreadsheet (next step).
- macOS Excel / Excel Online / Google Sheets.

## Anti-goals (failure even if it "works")

- **Different numbers from the app.** A section run through the batch must give the same results as
  the same section typed into the UI. This is the single most important requirement.
- Engine changes that alter rect/I results (`tests/test_rect_i_unchanged.py` golden baseline must stay
  green without regeneration) or that touch the protected torsion/longitudinal code (CLAUDE.md,
  CODE_PROTECTION.md).
- New AASHTO citations in labels/headers that are not already in the app (citation rule).
- Silent failure: a bad row must be reported by Section ID and row, never skipped quietly; one bad
  section must not stop the others.
- Requiring users to install Python, xlwings or any add-in.

## How it runs (decided)

- User opens the `.xlsm`, fills rows, presses **Run** (a button on the input sheet).
- A VBA macro hands the data to a bundled command-line engine executable, waits, and writes the results
  into the Results sheet. The executable is built like the existing app exe (`build_exe.bat`:
  python-build-standalone, no Python needed by the user).
- Excel keeps the workbook open and locked, so the engine must not write into the `.xlsm` itself.
  **Builder's call** on the exchange format (e.g. macro exports Inputs + Settings to a temp CSV/JSON
  next to the workbook → exe writes a results CSV/JSON → macro imports it); keep VBA small and
  dependency-free.
- Path to the engine exe and the output folder/name of the project file: on the Settings sheet
  (defaults: exe next to the workbook; project file next to the workbook, `<workbook name>.aashto.json`).

## Workbook layout

### Inputs sheet — one row per (section, load case)

- Column groups, with headers and a units row that follows the Settings unit choice:
  - **ID / type:** Section ID (= section name in the app), Section type (dropdown RECTANGULAR / T-SECTION /
    CIRCULAR), Member type (BEAM / SLAB, as in the app's `memberType` select).
  - **Materials:** f′c, fy, fy_trans (Es, λ etc. are on Settings).
  - **Rect / I geometry:** b (flange width), h, bw, hf_top, hf_bot, cover.
  - **Rect / I longitudinal steel:** top / bottom bar size, mode (count / spacing, as the app's
    `bar_mode_top/bot`), and the count or spacing. Spacing mode is included because SLAB members
    pro-rate As only in spacing mode (`gatherInputs`, ~lines 4561-4566). *(My call.)*
  - **Circular geometry / steel:** D, ring 1 bar / count / bundle, ring 2 on/off + bar / count / bundle /
    ring diameter, transverse type (hoop / spiral), hoop closure, tie legs / tie bar.
  - **Transverse (rect/I):** stirrup bar, legs, spacing; additional torsion bar + spacing.
  - **Demands:** Pu, Mu, Vu, Tu, Ps, Ms, service load case (same choices as the app's row dropdown).
  - Optional per-row M–φ axial override is **not** needed: M–φ runs at the row's Ps (app behaviour).
- Cells that do not apply to the row's section type are greyed (conditional formatting) and ignored.
- Geometry / materials / rebar are taken from the **first row** of each Section ID; later rows may leave
  them blank. If a later row fills them with different values → that section is reported as an error
  (my call, not discussed in detail with the user).
- Data validation dropdowns for type, bar sizes, load case, hoop type.

### Settings sheet

- Units: force kip / lbf and length in / ft (same four combinations as the app's display units).
- Every other calculation input the app has (user: "all other factors used in the calcs … in the
  separate tab"), **including** the factor overrides (`.factor-ovr-cb`), crack-control mode
  (`crack_mode`), wc / K1 overrides and the fy / fy_trans overrides as global values. Pre-filled with
  the values a **new section actually gets in the UI** (the HTML element defaults after
  `getDefaultSectionState()` is applied), not `getDefaultSectionState()` alone — these differ
  (e.g. `circ_hoop_closure` 'hooked' in the state vs the welded/hooked UI default from c9d52e0).
  *(My call; the mismatch itself is reported to the user as a possible app bug.)* Code edition, section class, reinforcement spec
  (astm_spec), concrete type / unit weight, K1, Es, aggregate size, λ, φ_v, γe, shear method and any
  other global options the app exposes, plus the M–φ options (concrete model service / confined / sgs,
  expected concrete, expected steel). Applies to every section.
- Engine exe path, project-file path, "overwrite project file" yes/no.

### Results sheet

- One row per input row, same order, keyed by Section ID + input row number, plus a run timestamp and
  a status column (OK / NG / ERROR + message).
- Full numbers per row, grouped: flexure (Mr, φ, c, εt, As, Mcr / 1.33Mu min-steel check, D/C),
  axial/P-M (Pr at the row's Mu or Mr at the row's Pu, whichever the app reports), shear (method,
  β, θ, εs, Vc, Vs, Vr, dv, bv, D/C, min Av, max spacing), torsion (Tcr threshold, Tr, required
  At/s, combined longitudinal check Eq. 5.7.3.6.3-1 as the app reports it — **no** Al_tors / Al_min),
  crack control (fss, s_max, actual s), service (Icr, Ieff, stresses), moment–curvature (My, φy,
  Mp, φy,ideal, φu, μφ, failure mode, Ieff/Ig at Ms, first yield and idealised).
- **Builder's call:** the exact column list — derive it from what the app's panels/report show per row
  (`row_results` and the active-row blocks), but every value written must come from the engine result
  dict, not be recomputed in the batch layer.
- Results are cleared and rewritten on each run; inputs are never modified.

## The engine side

- New CLI module (e.g. `batch_runner.py`) + its exe spec/build script modelled on
  `AASHTO_Concrete_App.spec` / `build_exe.bat`.
- Per section: build the app section state from the rows → convert to engine inputs → call
  `calc_engine.calculate_all(raw_inputs, demand_rows, active_row_idx)` (it dispatches circular)
  **once per demand row, with that row as the active row** — the detailed flexure / shear / torsion
  blocks (β, θ, εs, Vc, Vs, dv, Tcr, At/s, crack, service) exist only for the active row
  (calc_engine.py ~3587-3617); this equals what the app shows when the user clicks each row. Values
  come from the active-row blocks; `row_results` is used only where the active-row blocks have no
  equivalent; the parity test checks both agree where they overlap. *(My call.)* Plus
  `mphi_engine.moment_curvature_section` per demand row.
- Runs are sequential; the macro shows progress in the status bar ("section k of n") and the exe
  writes a progress file the macro can poll; no cancel in v1. *(My call.)*
- **Critical constraint:** the UI→engine conversion lives in JavaScript, `gatherInputs()` in
  `index.html` (~180 lines from line 4436: derived d from cover / stirrup / bar, Ec, defaults,
  circular fields, units). There is no Python equivalent. The batch needs one that produces the
  **identical** raw-input dict. Builder's call how (port to Python, or extract a shared definition),
  but it must be pinned by a parity test: for a set of section states (rect, I, circular, several
  bar/cover/unit combinations) the Python conversion must equal what `gatherInputs()` produces (e.g.
  run the extracted JS in node with a stub DOM, as done for the M–φ chart smoke test), and the final
  engine results must match.
- Units: convert sheet values (display units) → engine kip/in/ksi with the same factors as the app
  (`unitFactor` / `toEngine` in `index.html`), and back for results.
- Project file: `{version:1, activeSection, sections:{<ID>: state}, optParams, displayUnits}` exactly as
  `index.html` saves it (`saveCurrentSectionState()` ~line 1250 for the state shape; values stored in
  display units with `state.units`). Must open in the app with no warnings; pin with a round-trip test.
- **App change (user decision 2026-11-21):** the project file today does not store the shear-capacity
  method (`shearCapacityMethod`, global, index.html ~2702) or the M–φ options (concrete model,
  expected concrete, expected steel). Extend the app's save/load so it does, so a batch project
  reopens in the app with the same statuses and curvature results as the Results sheet. Backward
  compatible: older files without these keys load with today's defaults; older app builds must still
  open new files (extra keys ignored). Additive change only — notify the user before editing
  `index.html` (CLAUDE.md).
- Error handling: validate every row first (missing required cell, unknown type/bar, negative sizes,
  conflicting geometry within an ID); run each section in isolation; errors go to the Results status
  column; the exe exits non-zero only if it could not run at all.

## Constraints

- Project rules in CLAUDE.md apply: notify the user before app-code edits; no deletion of > 5 lines from
  `calc_engine.py` / `index.html` / `api.py`; new tests under `tests/`; `python run_test_suite.py --full`
  all stages pass; update OPEN_VERIFICATION_ITEMS.md.
- The batch layer must not change engine behaviour. If parity needs an engine change, stop and ask.
  (The project-file save/load extension above is the one approved app change.)
- Windows + desktop Excel only. Macros must be enabled by the user (document this in the template's
  instructions sheet).
- Creating an `.xlsm` with VBA programmatically needs desktop Excel (COM, with "Trust access to the VBA
  project object model") or an existing `vbaProject.bin`; keep the VBA source in the repo as `.bas`
  text so it can be reviewed and re-imported. Builder's call on the generation route.

## Open items to carry into OPEN_VERIFICATION_ITEMS.md

- MP1 / MP2 / MP3 apply to the curvature and stiffness columns (unverified materials, SGS preset,
  AdSec definition) — show a note on the Results sheet.

## Left to the builder

Exchange format between VBA and exe; exact Results column list (from engine keys); Python port vs
shared definition of `gatherInputs`; workbook generation route; sheet styling; exe name.
