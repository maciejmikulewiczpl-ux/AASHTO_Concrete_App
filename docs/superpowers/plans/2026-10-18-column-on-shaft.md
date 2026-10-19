# Column on Oversized CIDH Shaft — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new "Column on Shaft" tab. It takes pasted CSiBridge frame forces, designs the column and
shaft reinforcement with the existing circular LRFD engine, and adds seismic capacity design
(Mp → Mo → Vo → shaft). The shaft's in-ground moment and shear come from a p-y beam-column analysis on layered soil.
It also adds an optional AASHTO slenderness / moment-magnification check and per-bent reinforcement overrides.

**Architecture:** The new pure-Python modules form a pipeline:
`csi_import` (parse) → `colshaft_demands` (group + resultants) → `colshaft_lrfd` (search over
`circ_engine`) and `colshaft_seismic` (built on `seismic_port/`, a numpy-free port of the seismic app)
→ `colshaft_engine` (governing cage + overrides). `api.py` exposes two new methods. The UI is a new
tab whose JS lives in its own file `colshaft.js`. Existing engine files are imported, never edited.

**Tech Stack:** Python 3.12 stdlib only, pywebview 4.0 bridge, vanilla JS/HTML, pytest.

**Spec:** `docs/superpowers/specs/2026-10-18-column-on-shaft-design.md`

## Global Constraints

- Units inside the engine: **kip, in, ksi**. Moments in kip-in.
- App sign convention: `Pu < 0` compression, `Pu > 0` tension (CSiBridge P matches; no flip).
- No new third-party dependency. `requirements.txt` and the PyInstaller pins are unchanged.
- `calc_engine.py`, `circ_engine.py` and `pt_engine.py` are **not modified**. Existing tabs, inputs and the project
  `version` are unchanged.
- CLAUDE.md: notify the user before each app-code edit (`api.py`, `index.html`, any new engine module,
  `.spec`/`.bat`). Never delete more than 5 lines from `index.html`/`api.py`. No unverified code citations: ported
  seismic references are copied verbatim from the seismic app and listed in `OPEN_VERIFICATION_ITEMS.md`.
- Port source pinned: `C:\Users\macie\VSC\Seismic Column` @ `9265d67`; port tolerance ±0.5 % vs golden.
- Done = `python run_test_suite.py --full` all stages PASS (existing 21 + new ones).

## Review Focus

1. **Envelope-only (Max/Min) output, which is the user's real case.** The user expects conservative bounded rows, labelled
   as such, never Max-row values combined as if concurrent → `test_screenshot_fixture_parses` (Task 4) and
   `test_envelope_bounding_rows` (Task 5).
2. **Units row absent, or in kN / kN-m.** The user expects correct kip/kip-in numbers or a clear error,
   never silent kip-ft assumptions → `test_units_row_kn_m` and `test_no_units_row_uses_defaults` (Task 4).
3. **No cage in the search range satisfies the demand** (axial beyond P-M, bars don't fit). The user
   expects "NO SOLUTION" with the best D/C reached, not a crash or a false pass →
   `test_lrfd_no_solution_reported` (Task 6).
4. **Override is weaker than required.** The user expects it kept as entered and shown failing, never
   replaced → `test_override_kept_and_fails` (Task 8).
5. **p-y solve that does not converge or goes unstable on one bound only.** The user expects the stable bound to govern
   and the unstable one to be listed, never silently dropped and never shown as zero demand →
   `test_unstable_flagged` (Task 3A) and `test_unstable_soil_is_NG_not_pass` (Task 7).
6. **Old project file without `columnShaft`.** The user expects it to load exactly as before →
   `test_project_without_colshaft_roundtrips` (Task 9), plus a manual check in Task 10.

---

### Task 1: Pure-Python seismic materials and circular fibre section

**Files:**
- Create: `seismic_port/__init__.py`, `seismic_port/materials.py`, `seismic_port/section.py`
- Create: `tools/make_seismic_golden.py` (run once with the **seismic app's** venv)
- Create: `tests/golden/seismic_port_golden.json`, `tests/test_seismic_port.py`

**Interfaces:**
- Produces: `bar_area(n:int)->float`, `bar_diameter(n:int)->float`,
  `ReinforcingSteel(fye, fue, bar_no, ...)`, `UnconfinedConcrete(fc)`, `ConfinedConcrete(...)` with
  `.stress(eps:float)->float`. `CircularSection` keeps the **same constructor fields as the original**
  (`D, fc, fce_factor, cover, n_bars, long_bar_no, spiral_bar_no, spiral_spacing, fye, fue, fyh, hoops,
  n_strips`, plus `bundle` if present upstream). `concrete_fibres()` returns
  `(list[float] y, list[float] A_conf, list[float] A_unc)`, `steel_fibres()` returns
  `(list[float] y, list[float] A)`, and the properties `rho_l, rho_s, Ag, Acore` match upstream.

- [ ] **Step 1: Write `tools/make_seismic_golden.py`.** It imports `seismic_column` from
  `sys.argv[1]`. For 4 sections (column D=48/12-#9/#5@4 hoop; D=72/24-#11/#6@5 spiral;
  D=84/2-bundled 20-#11/#6@4; shaft Ds=96/30-#11/#8@6) it dumps confined-concrete stress at
  ε = 0.001, 0.002, 0.004, εcu, the steel stress at 0.001, 0.01, 0.05, Ag, Acore, rho_l, rho_s, and (for Task 2)
  the M-φ results at axial 0, 500, 1500 kip: φy, Mp, φu, Mu, φ_first-yield, M_first-yield, failure_mode.
  It also writes the upstream git hash into the JSON.
- [ ] **Step 2: Generate the golden.**
  Run: `"../Seismic Column/.venv/Scripts/python.exe" -I tools/make_seismic_golden.py "../Seismic Column" tests/golden/seismic_port_golden.json`
  Expected: the file is written and contains `"source_commit": "9265d67…"`.
- [ ] **Step 3: Write the failing tests** `test_materials_match_golden` and
  `test_section_props_match_golden`, parametrised over the golden sections, each value
  `pytest.approx(rel=5e-3)`.
- [ ] **Step 4: Run** `pytest tests/test_seismic_port.py -q`. Expected: FAIL (ImportError).
- [ ] **Step 5: Port** `materials.py` and `section.py` line-for-line, replacing numpy arrays with lists and
  `np.sum` with `math.fsum`. The module docstring records the upstream path and commit.
- [ ] **Step 6: Run** the tests. Expected: PASS.
- [ ] **Step 7: Commit** `feat(seismic_port): numpy-free Mander materials and circular section`.

### Task 2: Pure-Python moment-curvature with bilinear idealisation

**Files:** Create `seismic_port/moment_curvature.py`. Modify `tests/test_seismic_port.py`.

**Interfaces:**
- Consumes: `CircularSection` (Task 1).
- Produces: `moment_curvature(section, axial: float, n_points:int=60, kappa_max_factor:float=1.2) -> MomentCurvature`.
  The dataclass fields are identical to upstream (`phi, M, phi_y, Mp, phi_u, Mu, phi_yield_first,
  M_yield_first, failure_mode, EI_eff, axial`; `phi`/`M` are lists). **Axial is compression-positive here
  (upstream convention).** Callers convert from the app's `Pu`.

- [ ] **Step 1: Write the failing test** `test_mphi_matches_golden[section-axial]`: φy, Mp, φu and Mu within rel 5e-3,
  failure_mode equal.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Port.** Replace `scipy.optimize.brentq` with a local `_brentq(f, a, b, xtol=1e-12, maxiter=200)`
  (bisection plus secant, same bracketing contract, raises `ValueError` without a sign change).
- [ ] **Step 4: Run.** Expected: PASS. Also assert that a 48 in section's M-φ runs in under 0.5 s (`time.perf_counter`).
- [ ] **Step 5: Commit** `feat(seismic_port): moment-curvature port pinned to seismic-column@9265d67`.

### Task 3: Ported seismic provisions and column/shaft seismic shear

**Files:** Create `seismic_port/provisions.py` and `seismic_port/shear.py`. Modify `tests/test_seismic_port.py` and
`tools/make_seismic_golden.py` (add a shear block), then regenerate the golden.

**Interfaces:**
- Produces: `CodeProvisions` (fields as upstream, **minus** the balance/frame fields),
  `get_provisions(key: str) -> CodeProvisions` with keys `"SDC_2_0"` and `"AASHTO_SGS"`;
  `shear_breakdown(section, P: float, mu_d: float, inside_hinge: bool, provisions) -> ShearBreakdown`;
  `shear_capacity(...) -> tuple[phiVn, Vc, Vs]`; `min_transverse_ratio(...)`,
  `caltrans_min_transverse_ratio(...)`, `max_transverse_spacing(...)`,
  `max_transverse_spacing_caltrans(...)`, `max_longitudinal_spacing_caltrans(...)`,
  `longitudinal_bar_spacing(...)` — signatures copied from upstream `sdc_capacity.py`. Every `ref_*`
  string is copied verbatim.

- [ ] **Step 1: Extend the golden** with φVn, Vc and Vs for the 4 sections × P ∈ {0, 800 kip, −200 kip (tension)} ×
  μd ∈ {1, 3, 5} × both codes, plus the minimum-transverse results. Regenerate it as in Task 1, Step 2.
- [ ] **Step 2: Write the failing tests** `test_shear_matches_golden` and `test_min_transverse_matches_golden`, plus
  `test_refs_copied_verbatim`, which compares each `ref_*` string to the golden.
- [ ] **Step 3: Run.** Expected: FAIL.
- [ ] **Step 4: Port** the listed functions only.
- [ ] **Step 5: Run.** Expected: PASS.
- [ ] **Step 6: Add the open items** to `OPEN_VERIFICATION_ITEMS.md` under a new section **"E. Column-on-shaft
  (seismic provisions ported 2026-10)"**: one VERIFY row per `ref_*` used by this feature (overstrength,
  shear model, min ρs, shaft demand factor 1.25, shaft confinement fraction, min oversize, detailing
  spacing). Evidence source: `Seismic Column/AASHTO Seismic 3rd Edn.pdf`.
- [ ] **Step 7: Commit.**

### Task 3A: Soil strata, p-y curves and the beam-column pile solver (port)

**Files:** Create `seismic_port/soil.py` and `seismic_port/pile_solver.py`. Modify `tools/make_seismic_golden.py` (add a
pile block) and `tests/test_seismic_port.py`.

**Interfaces:**
- Produces (signatures and fields copied from upstream `soil.py` / `pile_solver.py`):
  `SoilLayer` (+ `from_engineering(thickness_ft, py_model, gamma_pcf, *, su_top_ksf, su_bot_ksf, eps50, phi_deg,
  k_pci, submerged, gamma_water_pcf)`), `SoilProfile(layers, J=0.5, cyclic=True, stiffness_factor=1.0)` (with **no**
  silo `below()`/`surface_offset` logic: YAGNI, there are no silos here), `PY_MODELS`;
  `solve_lateral(Hcol, L_embed, EI_col, EI_shaft, D_shaft, axial, soil, V_head, *, M_head=0.0, head_fixed=False,
  target_h=None, max_nodes=241, max_iter=100, tol=1e-6, relax=1.0) -> PileSolution` (fields as upstream, arrays → lists);
  `inground_demand(Hcol, L_embed, EI_col, EI_shaft, D_shaft, axial, soil_profile, V_head, soil_bounds=(2.0, 0.5),
  M_head=0.0) -> (M, V, PileSolution|None)`; `equivalent_fixity_depth(...)` as upstream.
- Replace `scipy.linalg.solve_banded` with a local `_solve_banded(ab, b, bw=3)`: banded Gaussian elimination without
  pivoting (the matrix is symmetric positive-definite after the boundary conditions).

- [ ] **Step 1: Extend the golden.** For 3 soil profiles (soft clay; stiff clay over sand; sand with a water table), the
  golden column/shaft pair, Hcol ∈ {240, 480 in}, L_embed = 720 in, axial 800 kip, both `(V_head, M_head)` cases
  (fixed-free Mo/H, 0 and fixed-fixed 2Mo/H, −Mo) × both bounds, store `head_deflection`, `Df_eq`,
  `max_inground_moment`, `max_moment_depth`, `max_inground_shear`, `stable`, and M at the ground node. Add one
  deliberately unstable case (very soft clay, L_embed = 120 in).
- [ ] **Step 2: Write the failing tests:** `test_pile_matches_golden` (rel 5e-3), `test_unstable_flagged`,
  `test_interface_moment_equals_Mo` (|M(ground node)| = Mo within 0.5 % for both end conditions),
  `test_elastic_closed_form` (an `elastic_subgrade` layer vs the Hetényi long-beam closed form, < 1 %, same as upstream's
  validation), and `test_pile_solve_under_2s`.
- [ ] **Step 3–5: Run → port → run.** Expected: FAIL, then PASS.
- [ ] **Step 6: Commit** `feat(seismic_port): p-y soil models and pile beam-column solver`.

### Task 4: CSiBridge paste parser

**Files:** Create `csi_import.py` and `tests/test_csi_import.py`, plus `tests/fixtures_csi/`. The fixtures are
`frame1227_strI1.txt` (the user's screenshot of 2026-10-18 transcribed exactly: 8 rows, tab-separated, header + units row,
Max/Min, FrameElem 1227-1/1227-2), `kn_m_no_title.txt`, `no_units_row.txt`, and `step_by_step.txt` (concurrent `Step 1..3`
rows). Replace `frame1227_strI1.txt` with a real clipboard paste when the user provides one (S1).

**Interfaces:**
- Produces:
  - `parse_csi_frame_forces(text: str, default_units: dict | None = None) -> ParseResult`
  - `ParseResult` (dataclass): `rows: list[ForceRow]`, `cases: list[str]` (in first-seen order),
    `frames: list[str]`, `units: dict` (`{"force","moment","length"}` as detected), `warnings: list[str]`,
    `n_envelope: int`
  - `ForceRow` (dataclass): `frame: str, station_in: float, case: str, case_type: str, step_type: str,
    P, V2, V3, T, M2, M3: float` (kip, kip-in), `envelope: bool`, `src_line: int`
  - The default units `{"force":"kip","moment":"kip-ft","length":"ft"}`.

- [ ] **Step 1: Write the failing tests:**
  - `test_screenshot_fixture_parses`: after de-duplication there are 6 rows (the station-8.4167 duplicates from 1227-1/1227-2
    are merged), `n_envelope == 6`. Row (station 0, Max): P = −2948.932 kip, M2 = 4720.0867×12 kip-in, T = 4523.3045×12 kip-in.
    Station 16.8333 ft → 202.0 in (rel 1e-4). `units == {"force":"kip","moment":"kip-ft","length":"ft"}`.
  - `test_dedupe_requires_identical_values`: if two duplicate keys carry different numbers, keep both and add a warning.
  - `test_units_row_kn_m`: P 100 kN → 22.481 kip (rel 1e-4). M 100 kN-m → 885.07 kip-in (rel 1e-4).
  - `test_no_units_row_uses_defaults`: `units == default` and `"No units row"` appears in the warnings.
  - `test_step_rows_are_concurrent`: `Step 1` etc. → `envelope=False`.
  - `test_unit_in_header_cell`: the header `Station ft` / `M3 Kip-ft` without a units row parses the same as the fixture.
  - `test_header_case_and_whitespace_tolerant`: tab- **or** multi-space-separated, mixed case headers.
  - `test_missing_required_column_raises`: no `M3` column → `ValueError` whose message lists the missing columns.
  - `test_comma_thousands_and_blank_lines` are tolerated.
- [ ] **Step 2: Run** `pytest tests/test_csi_import.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Find the header as the first line containing both `Frame` and `OutputCase`. The units row is the next
  line when its `P` cell does not parse as a float. De-duplicate on (frame, station rounded to 1e-4 ft, case, step_type). Unknown unit → `ValueError("Unknown unit 'X' in column P")`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit.**

### Task 5: Grouping, resultants and case categories

**Files:** Create `colshaft_demands.py` and `tests/test_colshaft_demands.py`.

**Interfaces:**
- Consumes: `ParseResult`, `ForceRow` (Task 4).
- Produces:
  - `default_case_category(case: str) -> str` ∈ `{"Strength","Extreme","Dead","Ignore"}`. Rules
    (case-insensitive, first match): `DEAD|^DC` → Dead; `EQ|EXT|SEIS` → Extreme; `SERV` → Ignore;
    otherwise Strength.
  - `demand_rows(rows: list[ForceRow], frames: list[str], categories: dict[str,str], category: str) -> list[dict]`.
    Each dict has `{"Pu","Mu","Vu","Tu","Vp":0,"Ms":0,"Ps":0,"_frame","_station","_case","_bound"}`.
    Concurrent rows: `Mu=hypot(M2,M3)`, `Vu=hypot(V2,V3)`, `Tu=abs(T)`, `Pu=P`, `_bound="concurrent"`.
    Envelope rows (spec §4.1a): per (frame, station, case), **one** row with `Pu = P_max` (CSiBridge algebraic max = least
    compression), `Mu=hypot(max|M2|, max|M3|)`, `Vu=hypot(max|V2|, max|V3|)`, `Tu=max|T|`, plus `_Pmin = P_min`,
    `_Pmax = P_max` and `_bound="envelope"`. Each absolute maximum is taken over both the Max and Min rows. A case with a Max
    and no Min (or the reverse) → use the one present for both and add a warning.
  - `prune_dominated(rows) -> list[dict]`: removes row a when another row b of the same frame has `Pu_b ≥ Pu_a`,
    `Mu_b ≥ Mu_a`, `Vu_b ≥ Vu_a`, `Tu_b ≥ Tu_a` and `[_Pmin_a, _Pmax_a] ⊆ [_Pmin_b, _Pmax_b]`.
  - `collapse_member(rows) -> list[dict]`: one row per frame (member mode) with Pu = max P_max, M/V/T = their maxima,
    and `_Pmin` = min P_min.
  - `detect_base_end(rows, frames) -> "min"|"max"`: the end whose mean P over all rows is more compressive (self
    weight grows downward). In the screenshot, station 0 is more compressive (−2948.9 vs −2768.5), so frame 1227 has
    its base at station 0, `"min"`. `bent.base_end` ∈ {"auto","min","max"}, default "auto".
  - `base_axial(rows, frames, categories, category, base_end) -> list[float]`: P at the base station.
  - `column_height_in(rows, frames) -> float` = Σ(max station − min station) over the frames.
  - `end_moments(rows, frames, case, step) -> dict` = `{"M2": (M_top, M_bot), "M3": (M_top, M_bot)}` (signed, kip-in)
    for one concurrent (case, step). Slenderness uses it (Task 6A).

- [ ] **Step 1: Write the failing tests:** `test_resultants_hypot` (M2=3, M3=4 → Mu=5; V likewise; T=−7 → Tu=7),
  `test_category_defaults` (a table of 8 case names; `Str-I1` → Strength), `test_envelope_bounding_rows` (screenshot fixture
  station 0 → one row, Pu = −2948.932, `_Pmin` = −4347.776, Mu = hypot(4720.0867, 14559.3567)×12, Vu = hypot(647.416,
  473.349), Tu = 4523.3045×12), `test_prune_dominated` (on the screenshot, station 8.4167 is not dominated by station 0,
  because its M is larger), `test_collapse_member_screenshot` (Pu = −2768.491, `_Pmin` = −4347.776, Mu = hypot(5712.5384,
  22053.4899)×12, Vu = hypot(647.416, 473.349), Tu = 4523.3045×12), `test_detect_base_end_screenshot_is_min`, `test_base_axial_picks_base_station`,
  `test_height_from_stations` (16.8333 ft → 202.0 in), `test_end_moments_signed`, and
  `test_end_moments_envelope_returns_none` (envelope-only → None, so Task 6A uses M1/M2 = +1).
- [ ] **Step 2–4: Run → implement → run.** Expected: FAIL, then PASS.
- [ ] **Step 5: Commit.**

### Task 6: LRFD strength design search over `circ_engine`

**Files:** Create `colshaft_lrfd.py` and `tests/test_colshaft_lrfd.py`.

**Interfaces:**
- Consumes: `demand_rows(...)` (Task 5); `circ_engine.derive_circular`, `build_pm_curve_circ`,
  `compute_row_capacities_circ`; `calc_engine.get_mr_at_pu`, `calc_engine.BARS`.
- Produces:
  - `base_circ_inputs(member: dict) -> dict`. It maps the bent-table member fields (`D, fc, fy, fyt, cover, ag,
    trans_type, hoop_closure`) to the raw-input dict `circ_engine` expects. It gets its defaults by calling
    `circ_engine.calculate_all_circ` on a template, so no key list is duplicated by hand.
  - `design_longitudinal(member: dict, rows: list[dict], params: dict) -> LongResult` with
    `LongResult(ok: bool, bar: int, n: int, bundle: int, Ast: float, rho_l: float, dc_max: float,
    governing_row: int | None, note: str)`.
  - `design_transverse(member: dict, long: LongResult, rows: list[dict], params: dict) -> TransResult`
    with `TransResult(ok, bar, s, ties, Av, rho_s, dc_v, dc_t, governing_row, note)`.
  - `check_cage(member, cage: dict, rows) -> list[dict]` returns the row results of
    `compute_row_capacities_circ`. Task 8 uses it to re-check overrides.
  - Both search functions take an optional `transform: Callable[[dict cage, list[dict] rows], list[dict]] | None`.
    The search calls it on each candidate's rows before checking (the slenderness hook from Task 6A; `None` = identity).
  - `flexure_axial_star(pm_curve: list[dict], Pmin: float, Pmax: float) -> float`: the P in [Pmin, Pmax] with the lowest
    `get_mr_at_pu`, checked at both ends and at every curve vertex inside the range (exact for the piecewise-linear curve).
  - Envelope rows (`_bound == "envelope"`): the shear-side pass (shearStatus, Tr, long_ok) is judged on the row as given (Pu =
    P_max). The flexure pass is judged on a copy with `Pu = flexure_axial_star(curve, _Pmin, _Pmax)` for **that candidate's**
    curve. The governing row reports which P governed flexure.
  - Defaults in `params`: `minBar 8, maxBar 14, minSpacing 1.5 in (clear), rho_min/rho_max` from
    provisions, `stirMin 5, stirMax 8, sMax 6.0, sMin 3.0, sStep 0.25, maxLegs 2`.
- Algorithm: the same order and tie-breaks as `optimizeFlexureCirc` / `optimizeShearCirc` (`index.html:3682-3762`).
  Flexure pass = `flexStatus != "NG"` on every row. Shear pass = `shearStatus in {"OK","NR"}` and
  (`not torsionConsider` or `Tr >= Tu`) on every row. **Speed rule:** the P-M curves are built once per
  candidate, and the flexure check uses `get_mr_at_pu` on the curve before any per-row shear run.

- [ ] **Step 1: Write the failing tests:**
  - `test_single_row_matches_existing_tab`: D=48, f'c=4, one row Pu=−800, Mu=12000. The cage found equals
    the one the app's JS optimiser returns for the same input (record it by running the app once and paste it in
    as a literal, with a comment saying how it was obtained).
  - `test_minimum_six_bars` and `test_rho_min_enforced` (a tiny demand still gives ≥ 6 bars and ρl ≥ ρmin).
  - `test_more_demand_never_less_steel` (monotonic over 3 demand levels).
  - `test_torsion_drives_transverse`: the same V with Tu large → smaller s or a larger bar than with Tu = 0.
  - `test_lrfd_no_solution_reported`: Pu beyond Pn,max of the largest cage → `ok False`, a `note`
    containing "NO SOLUTION", `dc_max` finite.
  - `test_500_rows_under_20s`.
  - `test_envelope_flexure_uses_worst_P`: a cage whose balance point lies inside [Pmin, Pmax] → P* is the end with
    lower Mr; and a high-compression envelope → P* = Pmin. Assert it equals a brute-force scan of 200 P values (rel 1e-6).
  - `test_envelope_shear_uses_Pmax`: the same row with Pu = Pmin gives Vr2 ≥ the Pmax result, and the search uses the Pmax
    value.
- [ ] **Step 2–4: Run → implement → run.** Expected: FAIL, then PASS.
- [ ] **Step 5: Commit.**

### Task 6A: Slenderness screen and moment magnification (optional toggle)

**Files:** Create `colshaft_slender.py` and `tests/test_colshaft_slender.py`.

**Gate:** Steps 1–5 (the screen) can be done now. Steps 6–9 (magnification) are **blocked until the user supplies
Art. 4.5.3.2.2b and the §5.6.4.3 EI equations (spec S6)**. Put the user's text, or an image transcription confirmed by
the user, in `AASHTO 10 Ch 5 MD/Art_4.5.3.2.2b_user_supplied.md` and cite only that.

**Interfaces:**
- Consumes: `end_moments` (Task 5), `circ_engine.derive_circular` (for Ec, Ig and the bar layout → Is).
- Produces:
  - `slenderness_screen(D: float, K: float, lu: float, braced: bool, M1: float, M2: float) -> dict`. It returns
    `{"r": 0.25*D, "klr": K*lu/r, "limit": 22.0 if not braced else 34 - 12*(M1/M2), "neglect": bool,
    "approx_ok": klr < 100, "ref": "AASHTO LRFD 10th §5.6.4.3; r per C5.6.4.3; <100 per §5.6.4.1"}`.
    `M1/M2` is signed by curvature, with |M1| ≤ |M2|. **Single curvature = end moments of opposite sign in the CSiBridge frame
    sign convention.** Confirm this against the sample paste (S1) and pin it in a test with a hand sketch in the docstring.
  - `make_magnifier(bent: dict, rows_by_case: dict, settings: dict) -> Callable[[cage, rows], rows]`. This is the
    `transform` hook for Task 6. It returns rows with `Mu` replaced by the resultant of the per-axis magnified moments and adds
    `_delta2`, `_delta3`, `_klr2`, `_klr3`. With the toggle off it returns the identity. For envelope rows, δ is computed with
    `Pu = _Pmin` (most compression) and M1/M2 = +1.
  - `Is_circular(cage_inputs: dict) -> float` = Σ As_i·y_i² over the `circ_layout` bars about the centroid.
- Rules: an axis with `neglect=True` gets δ = 1. `approx_ok=False` → the bent status is "REFINED ANALYSIS REQUIRED" and
  the design is not reported as passing. Pe ≤ the required ΣPu term (or δ ≤ 0) → status "UNSTABLE", never a negative δ.

- [ ] **Step 1: Write the failing screen tests:** `test_r_is_quarter_D`, `test_unbraced_limit_22`,
  `test_braced_limit_double_curvature` (M1/M2 = −0.5 → 40), `test_braced_limit_single_curvature` (M1/M2 = +0.5 →
  28), `test_klr_100_requires_refined`, and `test_toggle_off_is_identity` (rows are byte-identical with the toggle off).
- [ ] **Step 2–4: Run → implement the screen and `Is_circular` → run.** Expected: FAIL, then PASS.
- [ ] **Step 5: Commit** `feat(colshaft): slenderness screen per AASHTO 5.6.4.3`.
- [ ] **Step 6 (blocked by S6):** Write the failing magnification tests from a **hand calculation** done with the
  supplied equations (one braced and one unbraced worked example, numbers in the test docstring). Add
  `test_magnified_rows_drive_more_steel` (Task 6 search with the transform gives Ast ≥ without it) and
  `test_negative_delta_reported_unstable`.
- [ ] **Step 7: Implement** δb/δs, Cm, Pe and EI exactly as supplied. Every function's docstring cites the supplied file and
  the equation number.
- [ ] **Step 8: Run.** Expected: PASS. Move S6 to "Resolved" in `OPEN_VERIFICATION_ITEMS.md` with the evidence.
- [ ] **Step 9: Commit.**

### Task 7: Seismic capacity design

**Files:** Create `colshaft_seismic.py` and `tests/test_colshaft_seismic.py`.

**Interfaces:**
- Consumes: `seismic_port.*` (Tasks 1–3); `base_axial` (Task 5).
- Produces:
  - `to_section(member: dict, cage: dict, provisions) -> CircularSection` (expected properties from the provisions).
  - `seismic_design(column: dict, shaft: dict, col_cage: dict, shaft_cage: dict, axial: dict, bent: dict,
    provisions) -> SeismicResult`. `axial = {"P_dead": float, "P_ext_min": float, "P_ext_max": float}` in the app's
    sign convention. Convert with `P_comp = -Pu`.
  - `SeismicResult`: `Mp_by_P: list[(P, Mp)]`, `Mp, Mo, Vo, lambda_mo, end_condition, H`,
    `col_shear: (phiVn, Vc, Vs)`, `rho_s_min, s_max_detailing`,
    `shaft_profile: list[(z, M, V)]`, `shaft_Mdemand, shaft_Mp, shaft_phiVn`,
    `checks: list[Check(name, demand, capacity, ok, detail, ref)]`,
    `required_transverse: dict(bar, s)`. This is the lightest hoop or spiral that meets shear, ρs,min and detailing, found by
    the same search order as Task 6.
  - Bent inputs used: `lambda_mo` (default 1.2), `end_condition_long`/`_trans` ∈ `{"fixed-free","fixed-fixed"}`,
    `H_in`, `mu_d` (default = `provisions.mu_d_limit_single`; conservative for Vc), `shaft_basis` ∈
    `{"soil","cantilever","interface"}` (default `"soil"` if `bent["soil"]` is set, else `"cantilever"`), `L_eq_in`
    (the pile's equivalent cantilever length below the top of shaft; **required** when basis = `"cantilever"`, so a missing value →
    `ValueError("Enter the pile equivalent cantilever length or a soil profile")`),
    `soil` (`{"layers": [eng-unit dicts as upstream io_schema], "J", "cyclic"}` or None), `L_embed_in`,
    `soil_bounds` (default `(2.0, 0.5)`).
  - `SeismicResult` also carries `pile: {"bounds": [{factor, stable, Df_eq, Mmax, z_Mmax, Vmax}], "profile_gov":
    [(z, M, V, y)], "Df_eq_gov"}` (or None).
- Rules: `Mo = lambda_mo · max(Mp over P_dead and 5 points evenly across [P_ext_min, P_ext_max])`, with the governing
  P stored; column and shaft seismic Vc use `P_ext_max` (least compression); `Vo = max over directions of (1 or 2)·Mo/H`.
  Shaft profile by basis:
  - `soil`: the governing direction's end condition → `(V_head, M_head) = (Mo/H, 0)` or `(2Mo/H, −Mo)`. Call
    `inground_demand(H, L_embed, EI_col=Mp_col/φy_col, EI_shaft=Mp_sh/φy_sh, Ds, P_dead_comp, profile, V_head,
    soil_bounds, M_head)`. Every bound unstable → check "Shaft p-y solve" NG with "soil too soft or shaft too short".
  - `cantilever`: `M(z) = Mo + Vo·z`, `V(z) = Vo`, `z ∈ [0, L_eq_in]`, 11 points. `Df = L_eq_in`.
  - `interface`: `z = 0` only.
  Shaft flexure demand = `provisions.shaft_demand_factor · max M(z)` vs shaft Mp at P_dead; shaft shear `max V(z)` vs
  `shear_capacity(shaft, P_dead, 1.0, inside_hinge=False)`; confinement `rho_s,shaft ≥ fraction · rho_s,col`;
  oversize `Ds − D ≥ provisions.min_shaft_oversize`.

- [ ] **Step 1: Write the failing tests:**
  - `test_mo_is_lambda_times_max_mp`, `test_mp_sampled_inside_axial_range` (a range spanning balance → the governing P is
    interior), `test_seismic_vc_uses_least_compression`, and `test_vo_fixed_fixed_doubles`.
  - `test_matches_seismic_app_checks`: for the golden column/shaft pair, the column shear, shaft flexure and shaft shear
    D/C equal the upstream `_build_checks` values (add these to the golden generator, upstream's
    `shaft_moment_basis="interface"`).
  - `test_cantilever_basis_amplifies`: `shaft_Mdemand(cantilever) = shaft_Mdemand(interface)·(1 + Vo·L_eq/Mo)`.
  - `test_missing_L_eq_without_soil_raises`.
  - `test_required_transverse_meets_shear`.
  - `test_soil_basis_matches_upstream_inground`: shaft demand equals upstream `evaluate_column` with
    `fixity_source="soil"` for the golden pair (add it to the golden).
  - `test_soil_moment_exceeds_interface` (soft clay: in-ground Mmax > Mo, depth > 0).
  - `test_unstable_soil_is_NG_not_pass`.
- [ ] **Step 2–4: Run → implement → run.** Expected: FAIL, then PASS.
- [ ] **Step 5: Commit.**

### Task 8: Orchestrator — governing cage, overrides, whole-project run

**Files:** Create `colshaft_engine.py` and `tests/test_colshaft_engine.py`.

**Interfaces:**
- Consumes: Tasks 4–7.
- Produces `run_colshaft(payload: dict) -> dict`. Payload =
  `{"paste": str, "units": dict, "categories": {case: cat},
  "code": "SDC_2_0"|"AASHTO_SGS", "bents": [bent], "params": {...}}`, where `bent = {"name", "col_frames": [...],
  "shaft_frames": [...], "column": member, "shaft": member, "lambda_mo", "end_condition_long",
  "end_condition_trans", "H_in"|None, "mu_d", "shaft_basis", "L_eq_in", "base_end",
  "override": {"col_long"?, "col_trans"?, "shaft_long"?, "shaft_trans"?}}`.
  It returns `{"parse": {...summary, warnings}, "bents": [{"name", "lrfd": {col, shaft},
  "seismic": SeismicResult as dict, "final": {col_long, col_trans, shaft_long, shaft_trans},
  "final_source": {...: "LRFD"|"Seismic"|"Override"}, "final_checks": [...], "status": "OK"|"NG"|"NO SOLUTION"}]}`.
  Everything is JSON-serialisable.
- Rules: final longitudinal = override, else the LRFD result with the larger Ast, but no less than the seismic ρl,min. Final
  transverse = override, else the larger ρs of LRFD and seismic (where pitches are equal, take the larger bar). Then
  **re-run** `check_cage` (LRFD rows) and `seismic_design` on the final cages. Mo comes from the **final** column
  cage. A bent without shaft frames still gets the shaft seismic checks; its shaft LRFD part is `None`.

- [ ] **Step 1: Write the failing tests:** `test_end_to_end_fixture` (the kip-ft fixture, 2 bents, JSON round-trips with
  `json.dumps`), `test_override_kept_and_fails` (the override is 6-#5 → `final_source` "Override", status NG, cage
  unchanged), `test_seismic_governs_transverse`, `test_mo_uses_final_cage` (increasing the override bars raises Mo
  and the shaft demand), `test_bent_without_shaft_frames`,
  `test_strength_rows_through_pile` (spec §4.4a: strata + no shaft frames → shaft LRFD rows come from the p-y solve on the top-5-M +
  top-5-V base rows, and the interface M and V of each solve equal the base M and V within 0.5 %), and
  `test_slenderness_toggle_changes_only_when_on` (`settings.slenderness_on`, default False).
- Payload additions: `bent.soil`, `bent.L_embed_in`, `bent.soil_bounds`, `bent.slender = {"2": {braced, K, lu|None},
  "3": {...}, "beta_d"|None, "gamma_p"}`, `settings.slenderness_on`. `lu=None` → `H + Df_eq_gov` if a soil solve exists, else `H + L_eq_in` (user decision
  2026-10-18). The orchestrator passes
  `make_magnifier(...)` as `transform` to the column searches. `settings.envelope_mode ∈ {"station","member"}` (default
  "station"). Station mode applies `prune_dominated`; member mode applies `collapse_member`. Add the test
  `test_member_mode_never_less_steel_than_station_mode`.
- [ ] **Step 2–4: Run → implement → run.** Expected: FAIL, then PASS.
- [ ] **Step 5: Commit.**

### Task 9: API bridge, test-suite stage, build inclusion

**Notify the user first (app code: `api.py`, `.spec`).**

**Files:** Modify `api.py` (append 2 methods, no deletions), `run_test_suite.py` (append stages),
`AASHTO_Concrete_App.spec` (add `hiddenimports` for the new modules and the `seismic_port` package).
Create `tests/test_colshaft_api.py`.

**Interfaces:**
- Produces: `Api.parse_csi(payload_json: str) -> str` (it returns the ParseResult summary: cases with default
  categories, frames with height, units, warnings, n_envelope) and `Api.run_colshaft(payload_json: str) -> str`.
  Both follow the existing `{"error": str}` pattern.

- [ ] **Step 1: Write the failing tests:** `test_api_parse_csi_summary`, `test_api_run_colshaft_roundtrip`,
  `test_api_error_is_json` (bad paste → `{"error": ...}`), and `test_project_without_colshaft_roundtrips` (it loads an
  existing `*.aashto.json`-shaped dict without `columnShaft` through `save_project_to_path`/`json.loads` unchanged).
  Instantiate `Api()` without a window.
- [ ] **Step 2–4: Run → implement → run.** Expected: FAIL, then PASS.
- [ ] **Step 5: Register stages** `("Pytest:  seismic port", [tests/test_seismic_port.py])` and
  `("Pytest:  column on shaft", [tests/test_csi_import.py, tests/test_colshaft_demands.py, tests/test_colshaft_lrfd.py,
  tests/test_colshaft_slender.py, tests/test_colshaft_seismic.py, tests/test_colshaft_engine.py,
  tests/test_colshaft_api.py])`. Update
  `TEST_PROCEDURE.md` and the stage count in `CLAUDE.md` and `.github/copilot-instructions.md`.
- [ ] **Step 6: Run** `python run_test_suite.py --full`. Expected: all stages PASS, including
  `test_rect_i_unchanged.py` (golden unchanged).
- [ ] **Step 7: Commit.**

### Task 10: The tab (UI, persistence)

**Notify the user first (app code: `index.html`).**

**Files:** Create `colshaft.js`. Modify `index.html` with **additions only**: one `<button class="tab-btn"
data-tab="colshaft">Column on Shaft</button>` appended to `#tabBar`, one `<div class="tab-panel" id="tab-colshaft">`
skeleton, one `<script src="colshaft.js">`, a project-save hook that adds `columnShaft: window.ColShaft?.getState()`
in `saveProject`/`saveProjectQuick`, and a load hook that calls `ColShaft.setState(data.columnShaft || null)`.
Add `('colshaft.js','.')` to the spec `datas`. Check how `app.py` serves `index.html` (file vs inlined); if it is inlined,
inline the script in the same way.

**Interfaces:**
- Consumes: `pywebview.api.parse_csi`, `pywebview.api.run_colshaft` (Task 9).
- Produces: `window.ColShaft = { getState(): object, setState(obj|null): void }`. All DOM ids start with `cs-`.

UI contents (in order): paste textarea + unit dropdowns + **Parse** → summary chip row (frames, cases,
rows, an amber "envelope output: bounded conservatively" notice when Max/Min rows are present) → load-case table (case | count | category dropdown) → bent table (name, column frames
multi-select, shaft frames, D, Ds, f'c, fy, cover, end conditions, H (auto, editable), base end (auto/min/max), λmo, μD, basis, **pile equivalent cantilever length L_eq (ft;
required when no soil profile)**, soil profile, L_embed) + **Add bent** → soil profiles (named strata tables: thickness ft, model dropdown, γ pcf, su top/bot ksf, ε50,
φ′, k pci, submerged; bounds ×2.0/×0.5) → slenderness panel (toggle **off by default**; per bent and axis: braced, K, ℓu
auto/override, βd auto/override, γp)
→ code select + search params → **Design** → results grid (bent | LRFD col | seismic col | override | final |
Mp | Mo | Vo | Kℓu/r & δ max | shaft Mmax(depth)/Mn | shaft V/φVn | status light) → drill-down per bent (governing
rows table with Mu and Mc side by side, M-φ curve, shaft M(z)/V(z)/y(z) diagrams per soil bound with Df_eq marked, every
check with its reference string) → override editors per bent.

- [ ] **Step 1: Manual check against the baseline.** Before editing, open the app (`run.bat`), load one existing project, and note the
  Project Summary numbers.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Manual check.** Paste `tests/fixtures_csi/kipft.txt`, assign 2 bents, Design. The results match
  `test_end_to_end_fixture`. Apply an override → the bent turns NG with the override shown. Save, reload, and the state is restored.
  Reload the old project → the Project Summary numbers are identical to Step 1, and the other tabs are unchanged.
- [ ] **Step 4: Run** `python run_test_suite.py --full`. Expected: all PASS.
- [ ] **Step 5: Commit.**

### Task 11: Printable report and documentation

**Files:** Modify `colshaft.js` (report view and print button, reusing the existing report CSS classes). Modify
`index.html` Limitations tab (append a "Column on Shaft" section listing the non-goals of spec §2). Modify `CODE_PROTECTION.md`
(new section: the port is pinned to upstream and must not be changed without regenerating the golden from upstream;
existing engines are not to be edited for this feature). Modify `FIXES_SUMMARY.md` (feature entry).

- [ ] **Step 1: Write the report.** Per bent it covers inputs, parse summary, LRFD governing rows (Pu, Mu, Vu, Tu, Mr, Vr, Tr, D/C), the M-φ
  table (P, φy, Mp, φu), Mo/Vo derivation, column seismic shear breakdown, shaft profile and checks, and the final cage
  with its source. Every seismic line shows the ported `ref_*` text followed by "(unverified — see OPEN_VERIFICATION_ITEMS E)".
- [ ] **Step 2: Manual check.** Print-preview the fixture report and check that nothing is clipped.
- [ ] **Step 3: Run** `python run_test_suite.py --full`. Expected: all PASS.
- [ ] **Step 4: Commit.**

---

## Self-review notes
- Every spec section has a task: §4.1 → T4; §4.2 → T5/T10; §4.3 → T6; §4.4 → T1–3, T3A, T7; §4.4a → T8;
  §4.4b → T6A (+ T8 wiring); §4.5 → T8; §4.6 → T9–10.
- Task 6A Steps 6–9 are the only blocked work (S6). Everything else, including the soil and pile work, can run in order.
  The anti-goals are pinned by the rect/I golden (T9), the envelope-bounding tests (T4/T5), the override test (T8) and the OPEN items (T3).
- Open decisions S2–S4 change T5 categories, T7 shaft capacity and T6 rows. Settle them before Task 5.
