# AASHTO Citation Audit — COMPLETED 2026-05-14

> **STATUS: COMPLETE.** All 20 decisions (D1–D20) implemented and tested.
> Full test suite (17 stages, 233 pytest cases + 6 verification scripts) PASSES.
> See `FIXES_SUMMARY.md` § "AASHTO Citation Audit — completed 2026-05-14"
> for the consolidated change log.
> This file is preserved as the historical record of the Q&A walkthrough.

---

## How this audit started

This session began with a finding that `Al_tors`, `Al_min`, `Al_gov` (AASHTO Eq. 5.7.3.6.3-2 implementation) had been incorrectly re-added to the engine in a previous session and cited a non-existent "Eq. 5.7.3.6.3-3". After fixing that specific regression and locking it in with anti-regression docs (see `CODE_PROTECTION.md` § "Removed checks — DO NOT re-add" and `FIXES_SUMMARY.md` § "CRITICAL REGRESSION GUARD"), the user asked for a systematic audit of all AASHTO citations in the codebase to find similar fabricated or wrong citations.

The audit started with an inventory of every AASHTO/ACI reference in `calc_engine.py`, `pt_engine.py`, and `index.html`, plus git-history checks for other removed-then-re-added equations. **No other Al-style "wrong-section-type" or "fabricated equation" issue was found in git history.** The Al case appears to have been the only such regression.

The audit then moved into a Q&A walkthrough of the items where I (Claude) couldn't verify the equation form or coefficient from memory. Each question was answered against the user's actual AASHTO PDF (10th Ed + Caltrans amendments).

---

## Q&A walkthrough — completed (Q1 through Q10)

### Q1 — `0.45` coefficient in AASHTO Eq. 5.7.3.6.3-1

**Where**: `calc_engine.py:2264, 2958`, `calc_engine.py:2294`, `index.html:5847`
**Formula**: `ld_T = 0.45 · ph · |Tu| / (2 · Ao · φv)` inside the √ of the combined longitudinal demand.
**User answer**: Confirmed `0.45` is correct. **No engine change.**

### Q2 — φ-per-component in 5.7.3.6.3-1 longitudinal check

**Where**: `calc_engine.py:2252-2271` (and Method 1/3 mirrors at 2273-2300)
**Current state**:
- `ld_M = |Mu| / (dv · phi_f)` — strain-region-dependent flexure φ ✅
- `ld_V = |Vu|/phi_v − Vp − 0.5·Vs` — shear φ ✅
- `ld_T = 0.45·ph·|Tu|/(2·Ao·phi_v)` — treated as part of shear/torsion group ✅
- `ld_N = 0.5 · Pu / phi_c` — **always uses compression φ regardless of Pu sign** ✗

**User answer**: The φ factor for Nu should be sign-dependent.
**Decisions**:
- **D1**: `phi_for_N = phi_c` if Pu<0 (compression), else `phi_f` (use strain-region phi for tension)
- **D2**: Update `breakdown_long_comb` to display the actual φ value used per term (so engineers can see φ_f/φ_v/φ_c/φ_f spelled out, not just symbols)

### Q3 — `fr` modulus of rupture, lightweight concrete

**Where**: `calc_engine.py:1682, 2020, 2901`
**Current**: `fr = 0.24 * math.sqrt(fc)` — **no λ multiplier**.
**Impact**: Engine over-predicts `fr` for any case with `lam < 1.0`. Feeds into Mcr (5.6.3.3-1), εs strain (5.7.3.4.2-4), service stress.

**Decisions**:
- **D3**: `fr = 0.24 · λ · √fc` (apply existing `lam` factor the engine already uses for Vc/Tcr/Av_min)
- **D4**: Fix at the source so Mcr, ε_s, service stress all pick up the corrected value automatically

### Q4 — Pn,max formula + `kc` factor

**Where**: `calc_engine.py:397-399, 905-906`
**Current**: explicit citation `AASHTO LRFD 10th Ed Eq. 5.6.4.4-3`, with `kc = alpha1` simplification.
**User edition**: Mixed / project-by-project, including Caltrans amendments.

**Screenshot received** showing AASHTO 10th Ed §5.6.4.4 definition of kc:
- kc = 0.85 for fc' ≤ 10 ksi
- Reduce by 0.02 per 1 ksi above 10 ksi
- Floor at 0.75

This is **identical to the α1 formula** (AASHTO 10th Ed §5.6.2.2). The engine's `kc = alpha1` simplification is **verified correct**.

**Decisions**:
- **D5**: Edition is mixed / Caltrans-amended — need explicit edition tagging in the codebase
- **D6**: kc screenshot received; engine matches
- **D7**: `kc = alpha1` simplification verified correct in AASHTO 10th Ed; strengthen comment to make the edition assumption explicit

### Q5 — `Veff` formula applicability to I-sections

**Where**: `calc_engine.py:1985, 2719`
**Current**: `Veff = √(Vu² + (0.9·ph·Tu/(2·Ao))²)` cited as 5.7.3.4.2-5 "solid sections" — but applied to BOTH `RECTANGULAR` and `T-SECTION` (I-section).

**User answer**: For "real" I-sections, using the solid formula is acceptable. But if the user is modeling part of a hollow / box section as an I-beam, the equation should change.

**Decision**:
- **D8**: Keep formula. **Expand the I-section warning** (originally added for the Al case) to also note that the engine treats I-sections as solid (for Veff, Ao, etc.); users must NOT model halves of box/hollow sections as I-sections without supplementary manual checks.

### Q6 — `get_phi_flex` resistance-factor transitions

**Where**: `calc_engine.py:143-170`
**Section_class taxonomy** (verified from UI at `index.html:397-399`):
- `NP` = Non-Prestressed
- `PP` = Precast Prestressed
- `CIP_PT` = CIP Post-Tensioned / PT Spliced Precast

**Screenshots received**:
1. AASHTO LRFD 10th Ed §5.5.4.2 (Resistance Factors) — full bullet list and transition figure
2. AASHTO LRFD 10th Ed §C5.5.4.2 — transition figure (Fig. C5.5.4.2-1) with prestressed and nonprestressed curves
3. Caltrans amendments to §5.5.4.2 — replaces bullet 2, adds new bullet, updates figure to include CIP-PT curve

**Cross-check result**:
| code_edition | section_class | Engine | AASHTO source | Match? |
|---|---|---|---|---|
| AASHTO | NP | slope 0.15, ceiling 0.90 | Eq. 5.5.4.2-2 nonprestressed | ✅ |
| AASHTO | PP | slope 0.25, ceiling 1.00 | Eq. 5.5.4.2-1 prestressed (bonded assumed) | ✅ (under D9 bonded assumption) |
| AASHTO | CIP_PT | slope 0.25, ceiling 1.00 | Eq. 5.5.4.2-1 prestressed (bonded assumed) | ✅ (under D9) |
| CA | NP | slope 0.15, ceiling 0.90 | Caltrans Fig. C5.5.4.2-1 Non-Prestressed | ✅ |
| CA | PP | slope 0.25, ceiling 1.00 | Caltrans Fig. C5.5.4.2-1 Precast Prestressed | ✅ |
| CA | CIP_PT | slope 0.20, ceiling 0.95 | Caltrans Fig. C5.5.4.2-1 CIP-PT or PT Spliced Precast | ✅ |

**Key gap surfaced**: AASHTO 10th Ed has a bonded/unbonded distinction (1.00 for bonded PT, 0.90 for unbonded PT) and similar for shear/torsion φ (0.90 bonded, 0.85 unbonded). The engine currently doesn't have a "bond type" UI input.

**Decisions**:
- **D9**: Assume all CIP_PT is bonded (current behavior — the typical bridge case of grouted-duct PT). Document the assumption. No new UI control. User must manually override φ_f and φ_v if they have unbonded PT.
- **D10**: AASHTO base `get_phi_flex` verified correct under bonded assumption. No formula change.
- **D11**: Caltrans `get_phi_flex` verified exactly correct against amendments figure. No formula change.
- **D12**: Caltrans default in UI (`codeEdition: 'CA'`) appropriate for this user's bridge-design context. Keep.

### Q7 — γ1 / γ2 defaults for Mcr (AASHTO Table 5.6.3.3-1)

**Where**: `calc_engine.py:1670-1671`
**Current defaults**: γ1 = 1.6, γ2 = 1.1

**Screenshot received** confirming AASHTO Table 5.6.3.3-1:
- γ1 = 1.2 for precast segmental / **1.6 for all other concrete structures** ← engine default matches
- γ2 = **1.1 for bonded tendons** / 1.0 for unbonded tendons ← engine default matches

**Note**: my initial audit text had γ1 segmental as 1.5 — it's actually 1.2. My error, not the engine's.

**Decisions**:
- **D13**: γ1 default 1.6 verified correct. No engine change. Add comment noting segmental override = 1.2.
- **D14**: γ2 default 1.1 verified correct (consistent with D9 bonded assumption). No engine change. Add comment noting unbonded override = 1.0.

### Q8 — `min_trans` and `Av_min` (missing λ + Av+2At gap)

**Where**: `calc_engine.py:2040, 2572, 2737`
**Current**:
```python
Av_min   = 0.0316 * math.sqrt(fc) * bv * s_shear / fy_trans   # line 2040 (shear)
min_trans = 0.0316 * math.sqrt(fc) * bv * s_shear / fy_trans   # line 2572 (combined shear+torsion)
Av_min   = 0.0316 * math.sqrt(fc) * bv * s_shear / fy_trans   # line 2737 (row-level)
```
**Issue 1**: Same λ omission as fr. Per AASHTO 5.7.2.5-1, formula should include λ.
**Issue 2**: Label says "(Av+2At) required" but the HTML check (`index.html:4203-4206`) only compares against `Av` (shear stirrups), ignoring the additional torsion stirrup input that the engine accepts.

**Verified by user**: The additional torsion stirrup input (`at_add_bar_a`, `s_at_add`) IS used for Tn capacity but NOT for the min_trans check. The user confirmed this is a bug.

**Decisions**:
- **D15**: Apply `λ` multiplier to `Av_min` and `min_trans` in all 3 locations (lines 2040, 2572, 2737)
- **D16**: Update the HTML min_trans check (inline `index.html:4203-4206` and PDF report ~`index.html:5938-5948`) so the provided side is `Av_t + 2·at_add_bar_area`, matching the label and AASHTO 5.7.3.6.2

### Q9 — Tcr and Ao geometry approximation for I-section [**RESOLVED 2026-05-14**]

**Where**: `calc_engine.py:2432-2484`

**Resolution**: For I-section torsion, treat the FULL cross-section as solid
when computing Tcr (cracking torque), but use a WEB-ONLY sub-section when
computing Tn (post-cracking torsional capacity).

**For Tcr** (no change — engine already correct):
- `Acp_full = b·hf_top + bw·hw + b·hf_bot` (full gross area)
- `pc_full` = stepped outside perimeter of I-section
- `Tcr = 0.126·K·λ·√fc·Acp_full² / pc_full`

**For Tn** (CHANGE — drop the `max(...)` heuristic):
- `Acp_web = bw · h`           (web treated as own rectangular sub-section)
- `pc_web  = 2·(bw + h)`
- `be_web  = Acp_web / pc_web`
- `Ao = (bw − be_web)·(h − be_web)`
- `ph` (stirrup centerline) — already web-based, unchanged

**Rationale**: open I-sections have negligible St-Venant torsion stiffness.
Web-only Ao is the conservative interpretation consistent with treating the
web as the only meaningful closed-cell carrier. UI note required so engineers
understand the dual treatment.

→ Becomes **D17** (calculation) + **D18** (UI note).

### Q10 — AASHTO Appendix B5 tables [**RESOLVED 2026-05-14**]

**Where**: `calc_engine.py:53-100`

**Resolution**: All 320 cells (160 θ + 160 β across both tables) cross-checked
against user-provided AASHTO LRFD 10th Ed PDF screenshots of Tables B5.2-1
and B5.2-2. **PERFECT MATCH** — no transcription corrections needed.

**Two follow-ups identified and locked in**:

1. **D19 — Invalidate + reason on out-of-bounds inputs.** Currently `lookup_b5`
   only flags εx > max_ex (1.00 for T1, 2.00 for T2) and silently clamps every
   other out-of-bounds case. Per user direction, ANY out-of-bounds input now
   invalidates Method 3 and surfaces a specific reason in the report:

   | Bound | Trigger |
   |---|---|
   | εx·1000 < −0.20 | invalidate |
   | T1: vu/fc < 0.075 or > 0.250 | invalidate |
   | T1: εx·1000 > +1.00 | invalidate (already done) |
   | T2: sxe < 5 or > 80 | invalidate |
   | T2: εx·1000 > +2.00 | invalidate (already done) |

2. **D20 — Edition tag.** Add comment header to the B5 table block confirming
   AASHTO LRFD 10th Ed Tables B5.2-1 / B5.2-2 verified against PDF on 2026-05-14.

→ Becomes **D19** (logic + UI) + **D20** (doc-only).

---

## Consolidated decision sheet (20 decisions across 3 files)

### `calc_engine.py` changes

| # | Lines | Type | Change |
|---|---|---|---|
| **D1** | 2252-2271 + Method 1/3 mirrors at 2273-2300 | **Calculation** | `ld_N = 0.5 · Pu / phi_for_N` where `phi_for_N = phi_c if Pu<0 else phi_f` |
| **D2** | Inside `breakdown_long_comb` block | **Display** | Show actual φ value per term in the breakdown (φ_f for Mu, φ_v for V/T, sign-dependent φ for N) |
| **D3, D4** | 1682, 2020, 2901 | **Calculation** | `fr = 0.24 · lam · math.sqrt(fc)` (apply λ multiplier) |
| **D7** | 399, 906 | Doc-only | Strengthen kc comment with edition reference |
| **D9** | 143 (get_phi_flex docstring) | Doc-only | Document the "all CIP_PT treated as bonded" assumption |
| **D13** | 1670 | Doc-only | Strengthen γ1 comment (segmental = 1.2; non-segmental = 1.6 per Table 5.6.3.3-1) |
| **D14** | 1671 | Doc-only | Strengthen γ2 comment (bonded = 1.1; unbonded = 1.0) |
| **D15** | 2040, 2572, 2737 | **Calculation** | Add `* lam` multiplier to Av_min and min_trans |
| **D17** | 2473-2479 (and parallel 2719) | **Calculation** | I-section: keep `Acp_full`/`pc_full` for Tcr. For Ao, use `Acp_web=bw·h`, `pc_web=2(bw+h)`, `be_web=Acp_web/pc_web`, `Ao=(bw−be_web)·(h−be_web)`. Drop `max(...)` heuristic. |
| **D19** | 130-140 (`lookup_b5`) + call sites 2126-2129 / 2800-2803 | **Logic + UI** | Return `{valid, reason, theta, beta}` from `lookup_b5`. Invalidate for ALL out-of-bounds inputs (vu/fc, sxe, εx<−0.20). Surface reason string in Method 3 breakdown. |
| **D20** | 53 (above B5 tables) | Doc-only | Add comment: `# AASHTO LRFD 10th Ed Appendix B5, Tables B5.2-1 and B5.2-2 — full transcription verified against PDF on 2026-05-14.` |

### `index.html` changes

| # | Location | Type | Change |
|---|---|---|---|
| **D16** | 4203-4206 (inline torsion report) | **UI logic** | Provided side: `Av_t + 2 * at_add_bar_area` |
| **D16** | ~5938-5948 (PDF torsion report) | **UI logic** | Same fix |
| **D8** | ~4200 (inline) and ~5970 (PDF) I-section warning | Doc/text | Expand warning to cover not just Al but also Veff, Ao, and the "I-section as solid" assumption generally |
| **D18** | ~4200 (inline) and ~5970 (PDF), paired with D8 | Doc/text | Add note: *"For I-sections, Tcr uses full cross-section geometry, but Tn (post-cracking) uses an Ao based on the web rectangle only. Engineers should verify this matches the detailing intent."* |

### `tests/test_invariants.py` additions

- New regression test: `fr` scales with `lam` (NW gives unchanged result, LW reduces)
- New regression test: `Av_min` scales with `lam`
- New regression test: 5.7.3.6.3-1 Nu term uses `phi_c` when Pu<0 and `phi_f` when Pu>0

### Files NOT touched

- `pt_engine.py` — no findings
- `api.py`, `app.py` — no findings
- Any of the existing tests — only additions, no edits

---

## Calculation impact of the decision set

| User scenario | Numerical change? |
|---|---|
| Normal-weight concrete (`lam = 1.0`), Pu = 0 (or Pu < 0 compression) | **None.** Output identical to current. |
| Normal-weight concrete, Pu > 0 (axial tension) | Small shift in 5.7.3.6.3-1 longitudinal check (`ld_N`) — typically more favorable (φ_f ≥ φ_c, so ld_N magnitude smaller for tension). |
| Lightweight concrete (`lam < 1.0`) | `fr`, `Av_min`, `min_trans` reduced by λ. Mcr lower; ε_s slightly different; min transverse threshold easier to meet. All in the safer direction per AASHTO. |
| I-section with torsion considered | Same numerical results. New warning text rendered in the report. |
| Any section with additional torsion stirrups (`at_add_bar` input populated) | Min-transverse check now correctly includes them — currently they're silently dropped from the check. |

---

## Resume instructions for next session

When the user returns:

1. **Read this file in full** before making any changes.
2. **Check `MEMORY.md`** in the Claude project memory folder — there's a pointer there.
3. **Reopen the parked questions**:
   - **Q9**: Tcr / Ao for I-section. User was thinking about Ao approximation and looking up Tcr for I-section in AASHTO.
   - **Q10**: B5 Appendix tables spot-check.
4. **After Q9 and Q10 are resolved**, ask the user one final time before implementing the consolidated decision set. The user explicitly requested no edits until they review.
5. **When implementing**: follow the order in the decision sheet table above. Each calc_engine.py change should be checked with the full test suite (`python run_test_suite.py --full`) before moving on. NW-concrete tests should give zero numerical change; LW tests should shift in the documented direction.
6. **Mandatory anti-regression compliance**: the `Al_tors`/`Al_min`/`Al_gov` keys remain forbidden. See `CODE_PROTECTION.md` § "Removed checks — DO NOT re-add" and the inline notice at the top of `do_torsion`. The decision set above does NOT reintroduce them.

---

## Files saved this session (for context)

This session has already completed several rounds of work:

1. **Initial test-suite + runbook** — `tests/` folder, `run_test_suite.py`, `TEST_PROCEDURE.md` — all green, all stages pass.
2. **Bug-fix round** — `test_compliance.py`, `test_none_shear.py`, `full_verification.py`, `deep_audit.py` — all repaired and back in active rotation.
3. **Al regression fix** — removed Al_tors/Al_min/Al_gov from `do_torsion`, added Eq. 5.7.3.6.3-1 breakdown to `do_shear`, added I-section warning, expanded report keys contract.
4. **Anti-regression documentation** — `CLAUDE.md`, `.github/copilot-instructions.md`, `CODE_PROTECTION.md` § "Removed checks", `FIXES_SUMMARY.md` § "CRITICAL REGRESSION GUARD", `tests/test_invariants.py::test_al_keys_removed_from_torsion`, plus my memory files.
5. **Verifiable-citations rule** — added in CODE_PROTECTION.md / CLAUDE.md / Copilot instructions after Claude fabricated the Eq. 5.7.3.6.3-3 citation. This rule was prompted by the user's pointed question.
6. **AASHTO citation audit (this document)** — IN PROGRESS, paused.

All of (1)–(5) above have **completed runs of `python run_test_suite.py --full`** — all 17 stages PASS at the point of pause. Test counts: pytest 230, full_verification.py 20,436, deep_audit.py 30,923.

---

**Last touched**: 2026-05-13 by Claude (current session).
**Next action when user resumes**: pick up Q9 (Tcr/Ao for I-section) and Q10 (B5 tables).
**Estimated remaining work after Q&A completes**: 1–2 hours of implementation + testing for the 16 decisions.
