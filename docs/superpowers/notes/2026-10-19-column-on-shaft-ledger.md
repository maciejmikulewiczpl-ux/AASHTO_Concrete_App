# SDD ledger — plan: docs/superpowers/plans/2026-10-18-column-on-shaft.md

Spec: docs/superpowers/specs/2026-10-18-column-on-shaft-design.md
Branch: feature/column-on-shaft (from main @ 863f716; docs commit 58745a1)
Baseline: `py -m pytest tests -q` → 400 passed, 1 skipped.
Interpreter: `py` (Python 3.14 locally; the exe build uses 3.12, so the code must stay 3.12-compatible). Upstream seismic venv:
`C:\Users\macie\VSC\Seismic Column\.venv\Scripts\python.exe` (3.14).
Reference fixture (user screenshot, transcribed): .superpowers/sdd/2026-10-18-column-on-shaft/ref/frame1227_strI1.txt
User authorised overnight coding on 2026-10-18 ("start coding … burn as much usage as you need"). This counts as the
CLAUDE.md notice for app-code edits on this branch. No push or merge.

Task order: 1, 2, 3, 3A, 4, 5, 6, 6A (screen only), 7, 8, 9, 10, 11.

## Pre-flight scan

| Pair / task | Produces → consumes | Finding |
|---|---|---|
| T1→T2,T3,T3A,T7 | CircularSection fields, golden JSON, test_seismic_port.py | Sequential additions to the same golden generator and test file. OK. |
| T2→T3A,T7 | moment_curvature (axial compression +) → EI_eff, Mp | Sign convention stated in both. OK. |
| T3→T7 | shear_capacity, provisions | OK. |
| T3A→T7,T8 | inground_demand, solve_lateral | OK. T8 strength rows use solve_lateral with M_head. OK. |
| T4→T5 | ParseResult/ForceRow | OK. |
| T5→T6,T6A,T7,T8 | demand_rows (+_Pmin/_Pmax), base_axial(…, base_end), end_moments, prune/collapse | T7 Interfaces said `base_axial` without base_end. T5 is authoritative (base_end param). OK. |
| T6→T6A,T7,T8 | transform hook, flexure_axial_star, check_cage, search | T7 `required_transverse` "same search order as Task 6" → see Ruling P7. |
| T6A→T8 | make_magnifier | Screen only (S6 blocks magnification). See Ruling P1. |
| T7→T8 | SeismicResult | OK. |
| T8→T9→T10→T11 | run_colshaft payload/result → api → UI → report | OK. |
| T1 self | golden made by an upstream run | OK. |
| T6 self | test_single_row_matches_existing_tab needs the JS optimiser run in the GUI | Not runnable headless. Ruling P3. |
| T7 self | test_matches_seismic_app_checks via upstream `_build_checks` (needs a full evaluate_column setup) | Ruling P4. |
| T10 self | manual GUI checks | Not possible unattended. Ruling P5. |
| T6A self | Steps 6–9 blocked (S6) | Ruling P1. |

## Rulings
- Ruling P1: Task 6A implements the slenderness screen, `Is_circular` and `make_magnifier`. With magnification unavailable, make_magnifier returns rows unchanged but tags `_klr2/_klr3`, `_slender_status` ("neglect" | "magnification pending verification (S6)" | "refined analysis required"). Steps 6–9 are skipped until the user supplies Art. 4.5.3.2.2b. — The citation rule forbids coding the equations from memory. — If wrong: nothing; the user supplies the text and a later task adds the equations.
- Ruling P2 (open decisions, defaults): S2 = Extreme rows set only the axial range for M-φ / seismic Vc (no LRFD check of the Extreme rows). S3 = shaft flexural capacity uses M-φ expected Mp (seismic-app convention); the shaft LRFD strength design (pasted shaft frames or p-y strength rows) runs in addition. S4 = no service crack control in v1. S5 = pure-Python port. — These are the spec defaults. — If wrong: S2/S3 change only the check lists in T7/T8 (small rework).
- Ruling P3: Task 6's `test_single_row_matches_existing_tab` is replaced by `test_single_row_minimal_cage`: the returned cage passes, n−1 bars of the same size and bundle fail, and the result is pinned as a literal regression value. The algorithm order is checked against index.html:3682-3762 by reading. — The JS optimiser cannot run headless. — If wrong: the cage could differ from the GUI optimiser's on tie-breaks; the user can compare in the app.
- Ruling P4: Task 7's upstream cross-check uses upstream primitives directly (`moment_curvature`, `shear_capacity`, `inground_demand`, `provisions.shaft_demand_factor`) in the golden generator instead of `_build_checks`/`evaluate_column`. — Same numbers, far less fixture setup. — If wrong: a difference in upstream orchestration (e.g. the Vo definition) would not be caught. Mitigation: replicate upstream's Vo rule (2·Mo/H fixed-fixed, M_head = −Mo).
- Ruling P5: Task 10/11 manual GUI checks are replaced by (a) `node --check colshaft.js`, (b) a pytest that index.html contains the new tab button/panel/script tag and that the existing tab buttons are unchanged (count and order), and (c) the user's manual check tomorrow (listed in the hand-over). — No GUI is available unattended. — If wrong: UI bugs are found tomorrow.
- Ruling P6: The workspace dir `.superpowers/` is excluded through .git/info/exclude (local), not .gitignore. — Avoids touching repo files. — If wrong: nothing.
- Ruling P7: Task 7's required-transverse search reuses Task 6's candidate generator (exported helper in colshaft_lrfd) instead of re-coding the loop order. — Follows the DRY / "two sources for one number" trap in the seismic HANDOVER. — If wrong: only a refactor.
- Ruling P8: The CLAUDE.md "notify the user before app-code edits" requirement is satisfied by the user's overnight authorisation. All edits to existing app files (api.py, index.html, run_test_suite.py, .spec) are additive only (pre-commit hook: ≤5 deleted lines).

## Progress
Task 1: complete (commits 58745a1..6024b7f, review clean; ⚠️ golden provenance verified by controller: regenerated from upstream → identical)
Task 1: minor (deferred): test_seismic_port.py eps_cu loop dead code; json open without encoding=utf-8; golden lacks trailing newline / fce_factor param not recorded
Task 2: complete (commits 6024b7f..3f11b14, review clean)
Task 2: minor (deferred → carried into Task 3 dispatch): _brentq returns silently on maxiter exhaustion; scipy raises RuntimeError (upstream callers catch RuntimeError) — fidelity fix
Task 2: minor (deferred): speed test single-case; _brentq contract test thin
Task 3: complete (commits 3f11b14..8895153, review clean; ⚠️ REL tolerance verified by controller)
Task 3: minor (deferred → carried to Task 8): unknown provisions key silently falls back to SDC 2.1 — validate code key in feature layer (run_colshaft)
Task 3: minor (deferred): maxiter test doesn't assert solve_eps_a swallows; OPEN items E4/E6 duplicate text, E10 lumped; golden generator cosmetic
Ruling 3A-1: Fixed-fixed pile head moment is M_head = +Mo (solver DOF sign), not −Mo as the spec and Ruling P4 said — verified upstream sdc_capacity.py:794 passes +Mo and tests/test_two_direction.py:140 labels −Mp "wrong"; the upstream docstring is stale. Spec/plan text corrected (uncommitted doc edit, committed with the next task). — Cost if wrong: the shaft demand for fixed-fixed bents is off by ~2·Mo; pinned by a test either way.
Ruling 3A-2: test_interface_moment_equals_Mo runs at axial 0 (P-Δ adds 3–11 % at 800 kip, which is physics, not an error). — Cost if wrong: none.
Task 3A: complete (commits 8895153..15ac179, review clean)
Task 3A: carry to T7/T8: (a) inground_demand/solve_lateral axial is compression-positive → pass −Pu; (b) Df_eq is only meaningful from a fixed-free solve (M_head=0) → for ℓu/Df use a fixed-free solve; (c) never mutate cached PileSolution lists (copy first)
Task 3A: minor (deferred): dense matrix inside _solve_banded (perf ok); check_finite dropped; thin interface test
Task 4: review 1 → Needs fixes (decimal comma silent misread; nan/inf; silently dropped bad lines; blank unit cell ignores header unit)
Ruling 4-1: Unparseable data lines raise ValueError (listing all bad lines) instead of being skipped with a warning — losing one Max/Min row silently corrupts the envelope bound. — Cost if wrong: users must clean pastes with stray junk rows; error message tells them where.
Ruling 4-2: "Tonf" = metric tonne-force (CSI metric unit). — Cost if wrong: Tonf-unit pastes off by 1.1×; documented in docstring and hand-over.
Ruling 4-3: The "No units row" warning must be shown prominently in the UI (Task 10 carries it); there is no hard block.
Task 4: fix round 1/5 (6 addressed, 1 partial — test hygiene leftovers; commits 5c19c12..654a75f)
Task 4: fix round 2/5 (3 addressed, 0 open; commits 654a75f..1f3db44)
Task 4: complete (commits c3863be..1f3db44, review clean after 2 fix rounds)
Task 4: minor (deferred): non-numeric P in first data row misread as units row → "Unknown unit" message (still raises)
Task 5: review 1 → Needs fixes (multi-frame column stacks: end_moments uses frames[0], one global base end, base_axial at every frame's base)
Ruling 5-1: Multi-frame columns are stack-aware. CSiBridge frame stations are local per frame. Each frame gets its own base end (its own vote). Stack order: the bottom frame is the one whose base-end mean P is most compressive (self-weight accumulates downward), and frames are ordered by that mean. base_axial = P at the bottom frame's base only. end_moments = (top frame's top end, bottom frame's base end). A warning is issued when two frames' base means are within 0.5 % (ambiguous order). — Cost if wrong: an unusual model (e.g. net-tension columns) misorders the stack; the user can override base_end and the order shows in the report.
Ruling 5-2: The base-end vote uses Dead + Strength rows when present, else all rows. — Lateral/seismic envelopes would otherwise dominate the mean.
Ruling 5-3: The Extreme regex is prefix-anchored, `(?<![A-Z])(EQ|EXT|SEIS)`, case-insensitive, so "FREQ"/"SEQUENCE" aren't caught (EXTRA still matches; acceptable).
Ruling 5-4 (supersedes part of 5-3): Dead = plain load-case name only: ^(DEAD|DC|DL|SW|SELF)\b[\w-]*$ with no '+'; combinations containing DC are Strength/Extreme. My earlier '1.0DC+EQ → Dead' example was wrong (it would put strength combos into P_dead). — Cost if wrong: unusual dead-case names default to Strength; the user can recategorise in the case table.
Task 5: fix round 1-2/5 (all addressed; commits 6e963d5..730542b)
Task 5: complete (commits 1f3db44..730542b, review clean)
Task 5: carry to T8/T10: colshaft_demands functions take an optional warnings list — the orchestrator must pass one and surface it in results/UI
Ruling 6-1: The AASHTO longitudinal-reinforcement check for V(+T) (long_ok_2, Eq. 5.7.3.5-1/5.7.3.6.3-1) drives the design. It is part of the transverse pass criterion, and when only it fails, the longitudinal cage is stepped up (design_member orchestrates). The JS optimiser in the existing tab doesn't do this; the new tool is a designer. — Cost if wrong: heavier longitudinal steel in shear/torsion-dominated columns, but it is code-required.
Ruling 6-2: Envelope flexure checks both P-M faces and takes the lower Mr (conservative for odd bar counts; D-C5). Longitudinal is designed with a nominal #5@6 hoop before the transverse search. — Cost if wrong: slight over-design for odd bar counts.
Task 6: review 1 → Needs fixes (false NO SOLUTION: stepping gated on long_ok_2-only and break on first V/T failure; reviewer reproduced 11-#14 passing)
Ruling 6-3 (widens 6-1): when the transverse search fails for ANY shear-side reason while flexure passes, step through heavier longitudinal candidates (continue, not break) until design_transverse passes; NO SOLUTION only after exhausting the list. — Method 2 Vr depends non-monotonically on As. — Cost if wrong: runtime only.
Task 6: fix round 1/5 (6 addressed, 0 open; commits 2c099b3..a11b3aa)
Task 6: complete (commits 730542b..a11b3aa, review clean)
Task 6: parked — step screening uses the strongest transverse candidate only — Ruling: real but rare (web-crushing / dv-limited edge); conservative (over-reinforced, never unsafe); deferred.
Ruling 6A-1 (supersedes my P1 sign statement): single curvature = SAME sign of the CSiBridge station (internal) moments at both ends; opposite sign = double curvature (inflection). My original "opposite = single" was wrong (unconservative). The constant SINGLE_CURVATURE_OPPOSITE_SIGN=False is a one-line flip. — Cost if wrong: the braced limit 34−12(M1/M2) is off. Confirm with the user's concurrent sample (S1).
Task 6A: complete (commits a11b3aa..900ba35, review clean; steps 6-9 blocked by S6)
Task 6A: minor (deferred): sign comment still says "pending"; test mutates a module global (use monkeypatch); Is_circular multi-ring untested
Task 6A: carry to T8: make_magnifier expects rows_by_case = {"rows": ForceRows, "frames": [...], "categories": ...}; bent["lu_default_in"] must be set by T8 (H + Df)
Task 7: review 1 → Needs fixes (partial soil instability passed with warning; duplicate OPEN id E12)
Ruling 7-1: Port upstream check 13 "Soil-pile stability (p-y)" — NG if ANY soil bound is unstable at F_y = Mp/H (fixed-fixed: head_fixed at 2F_y as upstream); the overstrength demand envelope still drops unstable bounds (upstream inground_demand). Matches spec §4.4 "never as credit". — Cost if wrong: soft-soil designs flagged NG that the user might accept with a different bound bracket; user can change soil_bounds.
Ruling 7-2: Shaft seismic Vc at P_ext_max (least compression) per spec §4.1a — conservative; supersedes brief's P_dead.
Task 7: fix round 1/5 (7 addressed, 0 open; commits 9850144..aafdde3)
Task 7: complete (commits 900ba35..aafdde3, review clean)
Task 7: carry to T8: Check.ratio can be inf (stability check capacity=0) → JSON output must not emit Infinity/NaN (JS JSON.parse rejects); sanitize. Soil basis requires L_embed_in.
Task 7: minor (deferred): upstream detailing checks not ported: "Longitudinal bar spacing (max)" (SDC), "Longitudinal bar diameter (bond)" (SGS)
Ruling 8-1: strength rows through the pile use M_head = V·H − M_base (solver convention: interface M = V·H − M_head); the plan's "M − V·H" had the wrong sign. EI from the seismic M-φ at P_dead; axial = most compression. — Cost if wrong: shaft strength demand mis-scaled; pinned by an interface-equality test.
Ruling 8-2: the orchestrator sizes the shaft for the seismic checks (step longitudinal for capacity-protection flexure, then transverse for shear/confinement); final shaft = heavier of LRFD and seismic. — The plan only checked the shaft; the spec says "required reinforcement = envelope". — Cost if wrong: extra code; the user can override.
Ruling 8-3..8-11: see task-8-dispatch.md (final cage = larger Av/s; code key validation; JSON sanitising; warnings plumbing; lu_default = H+Df; envelope mode; status precedence; P_dead = most compressive base Dead axial; H from stations unless given).
Task 8: review 1 → Needs fixes (E15 replacement guard accepts P-Δ-reversed/post-buckled solves — unsafe; skipped strength rows warning-only)
Ruling 8-12: strength rows through the pile load the SHAFT ALONE at its top (Hcol=0, V_head=V_b, M_head giving interface M_b in V's sense); the solver's own stability guard is restored; column P-Δ is already in the CSI forces. Supersedes 8-1's column+shaft model and the E15 guard. — Cost if wrong: in-ground strength demand ~3–12 % different from the column+shaft model; safer.
Ruling 8-13: final check "Shaft p-y strength solve" NG when a governing strength row is skipped (unstable). — Supersedes the warning-only part of 8-1.
Ruling 8-14: P_dead = sum over the Dead-category cases of each case's base axial (spec §4.4). My 8-10 "most compressive single" was wrong (under-counts DC+DW → unconservative Mo). — Cost if wrong: none (matches spec).
Ruling 8-15: final transverse = larger Av/s with ties = max(LRFD, seismic); if the merged cage fails the final LRFD check, walk transverse_candidates for the first passing both. The same for the shaft after seismic upsizing.
Task 8: fix round 1/5 (9 addressed, 1 open — post-buckled p-y solves accepted by solver's stable flag; commits f2359b9..253e6ba)
Ruling 8-16: strength-row p-y solves need an axial-ramp guard (stable at P·k/4, k=0..4; |y_top| non-decreasing; interface M keeps sign and ≥ 0.995|M_b|); the seismic path stays upstream-faithful with a new DECIDE item for the user. — Cost if wrong: more "skipped → NG" rows in soft soils at high axial (conservative).
Task 8: fix round 2/5 (6 addressed, 0 open; commits 253e6ba..6d421cc)
Task 8: complete (commits aafdde3..6d421cc, review clean after 2 fix rounds)
Task 8: parked — shaft longitudinal sizing bisects assuming Mp monotone in As — Ruling: the result always passes, possibly not the lightest; deferred.
Task 8: minor (deferred): slenderness Df warnings not re-evaluated after the walk recompute; engine tests 18-23 s near the 25 s target
Task 9: complete (commits 6d421cc..aa89ed9, review clean)
Task 9: minor (deferred): webview stub not scoped (use monkeypatch); project roundtrip test weak (load path not exercised); error passthrough not pinned verbatim
Ruling 10-1: app.py passes html= as a string, so a relative <script src> never loads; get_html() inlines <script src="colshaft.js"></script> from the file (additive app.py change; colshaft.js added to spec datas). — Keeps the separate file per spec; the plan's assumption was wrong. — Cost if wrong: none.
Ruling 10-2..10-5: see task-10-dispatch.md (index.html additions only; pure JS functions Node-testable; static/Node tests replace manual GUI checks).
Task 10: review 1 → Needs fixes (grid slenderness status uses invented strings; P_dead labelled override but is a fallback)
Ruling 10-6: P_dead stays a fallback (engine sums Dead cases per 8-14); the UI relabels it accordingly. — Cost if wrong: the user can't force P_dead when Dead cases exist; they can recategorise the Dead cases to Ignore.
Task 10: deferred to Task 11: M-φ curve data and per-bound pile profiles in the engine result + chart updates
Task 10: note for user: pre-existing index.html:8635 Excel-table keydown handler swallows Backspace/Delete when a demand multi-cell selection is active (affects all tabs)
Task 10: fix round 1/5 (7 addressed, 0 open; commits 2a84f8b..d8a2988)
Task 10: complete (commits aa89ed9..d8a2988, review clean)
Task 11: complete (commits d8a2988..8feb8bc, review clean)
Task 11: minor (deferred): report text "least compression of the Extreme rows" should add "else P_dead"; print hardening (try/catch around window.print, stale cs-printing); CODE_PROTECTION wording "rows that fail" → per-bound; slenderAxes duplicates Python status logic; "bundled by the spec" wording; :has() needs Chromium 105+
Final review (863f716..8feb8bc): With fixes — 1 Critical (expected steel hard-coded Gr60), 5 Important (Backspace wipes main demands; slender OK while magnification pending; no shaft strength check w/o frames for cantilever/interface; auto H vs clear height; merge false NG)
Ruling F-1: expected steel fye/fue/fyh become inputs; blank only allowed for fy=60 (A706 Gr60 68/95/68); other fy → ValueError; no invented Gr80 values. — Cost if wrong: Gr80 users must type expected strengths.
Ruling F-2: colshaft panel stops keydown/keyup propagation (fixes the pre-existing global handler wiping hidden demand cells). — Cost if wrong: none.
Ruling F-3: new status "OK – MAGNIFICATION PENDING (S6)", ranked between NG and OK. — Cost if wrong: none (more honest).
Ruling F-4: no shaft frames + cantilever/interface basis → shaft strength rows from the cantilever profile (M_b + V_b·L_eq) / interface. — Cost if wrong: a conservative shaft strength check.
Ruling F-5: auto-H warning for clear height. Ruling F-6: the transverse walk also triggers on a seismic-screen failure of the merged cage.
Final fix wave: commits 8feb8bc..d7309ff; re-review: all 20 items addressed; full suite 23/23 PASS, Node 22/22 (controller-verified)
Final: parked — Ctrl+S quick-save doesn't fire while focus is inside the Column-on-Shaft tab (ruling F-2 stops all keydown propagation) — Ruling: surfaced to user (no second fix wave); one-line fix: stop propagation only for Delete/Backspace.

## Follow-ups 2026-10-19 (user decisions)
Ruling U-1 (supersedes 6-1 / 6-3 in part): the longitudinal-reinforcement check for V(+T) (`long_ok_2`) is ENFORCED on a row only when the member's new flag `bars_terminated` is True (payload `bent.column.bars_terminated` / `bent.shaft.bars_terminated`, default False; UI "Longitudinal bars terminated/discontinuous within the member (apply Eq. 5.7.3.5-1)") or the row requires torsion consideration (`torsionConsider`; Eq. 5.7.3.6.3-1 always applies to solid sections). Verified text: §5.7.3.5 "Eq. 5.7.3.5-1 shall be evaluated where simply-supported girders are made continuous for live loads and where longitudinal reinforcement is discontinuous."; §5.7.3.6.3 "The longitudinal reinforcement in solid sections shall be proportioned to satisfy Eq. 5.7.3.6.3-1". Otherwise it is reported "n/a: bars continuous (§5.7.3.5)" and does not affect the pass criterion, the stepping in `design_member`, the final checks, the D/C ratio or the status. Single source: `colshaft_lrfd.long_check_enforced` / `long_check_ok`; per-member report entry `lrfd[col|shaft]["long_check"]` (`long_check_summary`).
Ruling U-2: slenderness K per axis: `K_source` "default" | "analysis" (default "default") and `end_condition` "fixed-free" | "fixed-fixed" (default "fixed-free"). Default K: braced 1.0 (C5.6.4.3); unbraced = Euler ideal value (fixed-free 2.0, fixed-fixed 1.0), labelled "not the AASHTO Table C4.6.2.5-1 design value", with a bent warning. Analysis K: any K > 0; unbraced K < 1.0 accepted as entered with a warning (the old ValueError in `slenderness_screen`, `make_magnifier` and the JS validation is removed); K ≤ 0 / missing → ValueError. Legacy payload/state with a numeric K and no K_source → "analysis" (Python `resolve_K`, JS `normalizeState`/`kInfo`). Report/drill-down show per axis: K used, source, end condition, Kℓu/r, limit, status (engine result `bent.slender_K`). Art. 4.6.2.5 / Table C4.6.2.5-1 are not available: open item E19 (VERIFY).

## Moment magnification 2026-10-19 (rulings M1-M14, dispatch .superpowers/sdd/2026-10-19-magnification)
Source: `AASHTO 10 Ch 5 MD/Art_4.5.3.2.2b_user_supplied.md` (user page images; S6 and E19 resolved). Implemented in `colshaft_slender` (resolve_K_unbraced / resolve_K_braced, beta_d, EI_circular, euler_Pe, delta_b, delta_s, cm_factor, make_magnifier), `colshaft_lrfd` (`_unstable` rows fail with D/C inf; UNSTABLE_NOTE in NO SOLUTION notes), `colshaft_demands` (`_M2`/`_M3` row components), `colshaft_engine` (status UNSTABLE, magnification summary, sway_pass2), `colshaft.js` (K_braced, sway group, magnification tables, status mirror), index.html Limitations line (1 line changed).
Implementation choices inside the rulings (flag to the user if wrong):
- M2: a legacy BRACED axis whose K was a buckling-analysis K (K_source "analysis", or numeric K without K_source) and no K_braced keeps that K as the braced K (Python resolve_K_braced, JS kbInfo/normalizeState); otherwise legacy -> 1.0. On a braced axis the screen uses the braced K.
- M7 (superseded by MF-4): M_dead at a station = the SUM OF THE ABSOLUTE per-case Dead resultants (per case the resultant of the per-component |max|), max over stations; Strength max |Mu| = max demand-row resultant of the column frames. No Strength moment -> beta_d = 1.0.
- M8/M5: a neglected axis (K lu/r < limit) gets delta = 1.0 (the computed db/ds are still tagged); "refined analysis required" axes are still magnified (status REFINED anyway). Instability is only flagged on non-neglected axes with Pu compressive.
- M9: pass 2 uses Sum Pe = own CANDIDATE Pe_s + other members' pass-1 final-cage Pe_s (so a heavier own cage still stabilises); others' Pu = their most compressive Pu over stations for the same (case, step) (envelope: same case, step None); a key missing on any other member -> Pu x n_members + warning. A member without a final cage (NO SOLUTION) -> group pass 2 skipped with a warning (pass-1 results kept). Braced-axis members contribute their unbraced-K Pe_s anyway.
- M10: STATUS_RANK = OK 0, NG 1, REFINED 2, UNSTABLE 3, NO SOLUTION 4 (renumbered).
- Rows without `_M2`/`_M3` (none from colshaft_demands now) are magnified as Mu x max(delta2, delta3).
Tests: tests/test_colshaft_slender.py (hand calcs braced/unbraced to rel 1e-6, tension, unstable, drive-more-steel, beta_d, K_braced/legacy, sway sums), tests/test_colshaft_engine.py (toggle, precedence, UNSTABLE final cage, sway two-pass), tests/js (27), tests/test_colshaft_ui_static.py mirrors. Full suite 23/23 PASS.
Magnification review fix round 1 (rulings MF-1..MF-5, minors 6/7): EI cache keyed on every raw input (transverse bar sets the ring radius); sway pass-2 consistency loop (max 3, then check-only run with min Pe_s); member-mode ΣPu = own + others' max compression over all cases (MEMBER_KEY); βd = max over stations of Σ|Dead resultants|; one column redesign with the final ℓu when only magnified column rows fail (the transverse-walk NO SOLUTION counts as such; Df can deepen with the heavier column, so one redesign may not suffice; superseded by MF-5b/5c: iteration (max 4, 1 % ℓu) + a final redesign for max(ℓu) × 1.02 — bent 2 at K 2.3 converges in 2, K 2.4 passes via the margin run); `_neglect_note` for neglected axes with an unstable δ; report line on envelope component maxima.
Fix rounds 2-4: MF-5b (ℓu iteration, `lu_iterations`), MF-5c (margin run ×1.02, `lu_margin`; open item E23), MF-2 label "LRFD (sway check-only)" only for the cages the check-only run adds (a real user override stays "Override", O1); O2 `lu_not_settled` compares the per-axis ℓu actually used (explicit ℓu on both axes -> no loop / no margin run); O3 margin warnings ("resolved by the margin run" / "margin redesign at ℓu × 1.02 tried; did not pass"); neglect note shown whenever the axis summary carries it (summary prefers rows with the note).
Ruling C-1 (2026-10-19, user's real concurrent CSiBridge output tests/fixtures_csi/frame1227_strI1_concurrent.txt): correspondence StepTypes `^(max|min)\s+\S+` ("Max P", "Min M3", ...) are concurrent design rows, but `colshaft_demands.end_moments` returns None for them (`is_correspondence_step`; the ends may be different load states) -> M1/M2 = +1 (Cm 1.0, braced limit 22). Sway ΣPu matching by (case, step) unchanged. Regression: D 96 / Ds 120 cantilever run -> column 33-#14 (Ast 74.25) + #7 @ 3.75 vs 19-3x#14 (Ast 128.25) from the envelope sample.
