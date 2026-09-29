# Open Verification Items — REMIND THE USER AT THE START OF EVERY TASK

Last updated: 2026-09-29. Single source of truth for everything that is implemented but
**not yet verified against the printed AASHTO LRFD 10th Ed.** or **awaiting a user decision**.

- Every new task on this project starts by reminding the user of this list (count + critical items).
- When an item is resolved, move it to "Resolved" with the date and the evidence
  (AASHTO page / article / equation number, or the user's decision). Never delete it silently.
- **Source text:** `AASHTO 10 Ch 5 MD/Chapter 5 from AASHTO LRFD BDS-10 bookmarked.md` — full
  Chapter 5 (10th Ed., 2024) converted to Markdown. Article text, notation and commentary are
  legible; **most displayed equations were images and are NOT in the text** (only the
  surrounding words, variable lists and equation numbers). Items still open below are exactly
  those that depend on an illegible equation image, have no AASHTO rule, or need a decision.
- Citation rule still applies (CODE_PROTECTION.md): do not "upgrade" any item to a firm
  citation without seeing the printed text.

Status legend: **VERIFY** = check against AASHTO text · **DECIDE** = user decision needed · **FIX** = known defect, fix after verification/approval.

---

## A. Independent review by Fable 5 (REVIEW_FINDINGS_2026-06-11.md)

| ID | Status | Item |
|---|---|---|
| F5b | DECIDE (minor) | Row crack check is skipped entirely when the tension face has ≤ 1 bar (rest of F5 fixed 2026-09-28). |
| D-F2 | DECIDE (minor) | Table 5.6.3.3 gives γ3 for nonprestressed bars and "γ3 = 1.0 for prestressing steel", but no rule for a section with both. Engine now uses γ3 = 1.0 whenever tension-side prestress exists (conservative: higher Mcr); a force-weighted γ3 is the alternative. Override `gamma3_f` still wins. |
| M7 | DECIDE | Vp always |P·sinθ| and always favourable — UI caveat? |
| M10 | DECIDE (minor) | I-section P-M deep-compression region ignores far-flange overhangs until a ≥ h (conservative, small Pn discontinuity). |
| M11 | DECIDE (minor) | Mcr_serv for Branson Ieff ignores prestress and uses min S (conservative for deflection). |

## B. Circular section (added 2026-09-28) — still open after the Chapter 5 check

Engine list: `circ_engine.CIRC_UNVERIFIED` (also printed in the report, §1.4).

| ID | Status | Item |
|---|---|---|
| C4 | DECIDE (interpretation) | A<sub>v</sub> = 2·A<sub>hoop</sub> + n<sub>ties</sub>·A<sub>tie</sub>. §5.7.3.3 defines A<sub>v</sub> only as "area of transverse reinforcement within a distance s"; no circular-specific rule found in Chapter 5. |
| C9 | DECIDE (interpretation) | Crack-control s = arc spacing of the outer ring. §5.6.7: "spacing, s, of nonprestressed reinforcement in the layer closest to the tension face"; no circular rule. |
| C10 | DECIDE | §5.6.3.1.1 fps equation is stated "for rectangular or flanged sections"; §5.6.3.2.4 requires "an analysis based on the assumptions specified in Article 5.6.2" for other cross-sections, and C5.6.3.1.1 recommends strain compatibility when tendons are on the compression side. The circular P-M curve already uses strain compatibility for the tendon; `do_flexure_circ` still uses fps = fpu(1 − k·c/dp). Switch it to strain compatibility? |

Design choices awaiting a **DECIDE**:

| ID | Item |
|---|---|
| D-C1 | Row crack status (rect-consistent) does NOT compare actual bar spacing with s_crack; the arc-spacing comparison is information only in panels/report. Make it drive the status? (Default 36" / 12-#9 column: 7.76 in > 6.43 in.) |
| D-C3 | Circular cracked section transforms ALL bars (n·As below NA, (n−1)·As above); rect/I uses tension steel only. |
| D-C4 | Compression bars do not deduct displaced concrete in the stress block (mirrors rect/I). |
| D-C5 | Bars start at the top of the ring; odd bar counts give slightly different sag/hog capacity. |
| D-C6 | Circular crack-control s_max_ck = min(1.5·D, 18 in) copied from the §5.10.3.2 walls/slabs rule. |

## C. Other / housekeeping

| ID | Status | Item |
|---|---|---|
| H1 | DECIDE | Circular work + review fixes + 2026-09-29 Chapter-5 fixes are **uncommitted**. The pre-commit hook will flag `index.html` / `calc_engine.py` (lines modified in place — nothing removed); commit needs the user's go-ahead. |
| H3 | DECIDE | `tests/golden/rect_i_baseline.json` must be regenerated (reviewed) whenever fixes intentionally change rect/I results. Last regenerated 2026-09-29 for F1/F2/M4 (reviewed with an old-vs-new engine diff). |

---

## What would close the rest

| Need | Closes |
|---|---|
| User decision | D-F2, F5b, M7, M10, M11, C4, C9, C10, D-C1, D-C3–D-C6, H1, H3 |

Not implemented (optional): the C5.7.2.8-1 alternative for circular members (d<sub>v</sub> = M<sub>n</sub>/(A<sub>s</sub>f<sub>y</sub> + A<sub>ps</sub>f<sub>ps</sub>) with M<sub>n</sub> ignoring axial load and half-section steel); the engine uses the permitted 0.9d<sub>e</sub> alternative.

---

## Resolved

| Date | ID | Evidence / decision |
|---|---|---|
| 2026-09-29 | C2b | User confirmed the C5.7.2.8 circular equation d<sub>e</sub> = D/2 + D<sub>r</sub>/π (the image didn't come through in the Markdown). Engine already implemented it; labels updated, removed from `CIRC_UNVERIFIED`. |
| 2026-09-29 | C8b | User supplied the image of Eq. 5.6.4.6-1: ρ<sub>s</sub> = 4A<sub>sp</sub>/(d<sub>c</sub>s) ≥ 0.45(A<sub>g</sub>/A<sub>c</sub> − 1)f'<sub>c</sub>/f<sub>yh</sub> — one combined equation; there is **no Eq. 5.6.4.6-2** (the "-2" was only in this file, never in code). Engine matches (d<sub>c</sub> = D − 2·cover, cover = clear to the hoop → core to the outside of the transverse bar). Labels now cite Eq. 5.6.4.6-1; removed from `CIRC_UNVERIFIED`. |
| 2026-09-29 | **F1** | §5.7.3.4.2 (p. 5-74/5-75): one strain equation, Eq. 5.7.3.4.2-4, for sections with and without min A<sub>v</sub>; the εs<0 bullet reads "recalculated with the denominator of Eq. 5.7.3.4.2-4 replaced by (E<sub>s</sub>A<sub>s</sub> + E<sub>p</sub>A<sub>ps</sub> + E<sub>c</sub>A<sub>ct</sub>)" → base denominator is (E<sub>s</sub>A<sub>s</sub> + E<sub>p</sub>A<sub>ps</sub>). CB5.2 confirms the factor 2 belongs to Appendix B5 (ε<sub>x</sub> = ε<sub>t</sub>/2, Eq. B5.2-3). Factor 2 removed from `do_shear` and `compute_row_capacities`. Impact (180 golden cases): Vr2 lower in 85 active / 1023 row results where min A<sub>v</sub> is present (e.g. 162.3 → 127.4 kip), θ larger, Tr lower accordingly; long-steel demand slightly lower. Pinned `tests/test_aashto_ch5_verified.py`. Circular inherits via `do_shear`. |
| 2026-09-29 | M5 | Same §5.7.3.4.2 bullet: εs<0 denominator E<sub>s</sub>A<sub>s</sub> + E<sub>p</sub>A<sub>ps</sub> + E<sub>c</sub>A<sub>ct</sub> (no factor 2), εs ≥ −0.40×10<sup>−3</sup>. Pinned. |
| 2026-09-29 | R1 | Panel/report already showed the single denominator; now matches the engine. Report note for εs<0 lists the full denominator. |
| 2026-09-29 | F2 | Table 5.6.3.3 (p. 5-45): γ3 values for nonprestressed bars (0.67 A615 Gr 60 … 0.80 A706 Gr 80) and "For prestressing steel, γ3 shall be taken as 1.0." Engine: γ3 = 1.0 when tension-side prestress is present (rect/I, rows, circular); mixed-steel interpretation kept open as D-F2. Mcr changed in 60 PT golden cases, no status light changed. Pinned. γ1 = 1.2 segmental / 1.6 other, γ2 = 1.1 bonded / 1.0 unbonded also confirmed. |
| 2026-09-29 | M3 | §5.7.3.4.1 (p. 5-73): simplified procedure for footings, or nonprestressed sections not subjected to axial tension with ≥ min A<sub>v</sub> (5.7.2.5) or overall depth < 16.0 in. Engine returns `m1_applicable` / `m1_na_reason`; panel and report warn. Information only — does not change Method 1 numbers. Pinned. |
| 2026-09-29 | M4 | §5.7.3.4.2: "If the axial tension is large enough to crack the flexural compression face … the value calculated from Eq. 5.7.3.4.2-4 should be doubled"; §B5.2: "the resulting increase in ε<sub>x</sub> shall be taken into account … the value calculated from Eq. B5.2-4 should be doubled." Method 2 active already doubled; now also B5 ε<sub>x</sub> (both tables, conservative) and demand rows (`epsS`, `dblEps` row keys). Criterion unchanged: gross-section compression-face stress under N<sub>u</sub>, M<sub>u</sub> > f<sub>r</sub>. 3 golden rows changed (B5 becomes invalid). Pinned. |
| 2026-09-29 | M9 | §5.7.3.6.1 only requires transverse reinforcement ≥ sum for shear and concurrent torsion; no V+T stress-interaction equation exists in Chapter 5 (web crushing: Eq. 5.7.3.3-2). The `comb_stress` check (ACI-318 form) is kept, relabelled "supplementary — not an AASHTO LRFD equation", information only (it never drove status). |
| 2026-09-29 | R6b | V<sub>s</sub> cited as Eq. 5.7.3.3-4 (α = 90°) — C5.7.3.3: "Where α = 90 degrees, Eq. 5.7.3.3-4 reduces to"; v<sub>u</sub> cited §5.7.2.8 (B5.2-1 is V<sub>eff</sub> per CB5.2); B5 ε<sub>x</sub> cited Eq. B5.2-3 / B5.2-4. |
| 2026-09-29 | C1 | §5.7.2.8 notation: b<sub>v</sub> "for circular sections, the diameter of the section, modified for the presence of ducts"; C5.7.2.8: "the effective web width can be taken as the diameter of the section". |
| 2026-09-29 | C2 (part) | C5.7.2.8: "Alternatively, d<sub>v</sub> can be taken as 0.9d<sub>e</sub>"; §5.7.2.8: d<sub>v</sub> need not be less than max(0.9d<sub>e</sub>, 0.72h). d<sub>e</sub> equation → C2b (resolved). |
| 2026-09-29 | C3 | §5.7.3.4.2: "The flexural tension side of the member shall be taken as the half-depth containing the flexural tension zone"; A<sub>s</sub> = nonprestressed steel on the flexural tension side. C5.7.2.8 (circular d<sub>v</sub>): reinforcement "in one half of the section". |
| 2026-09-29 | C5 | §5.7.2.1 (A<sub>cp</sub>, p<sub>c</sub>, b<sub>e</sub> ≤ A<sub>cp</sub>/p<sub>c</sub>); §5.7.3.6.2: "For solid sections, A<sub>o</sub> may be taken as the area enclosed by the centerline of the effective width b<sub>e</sub> determined as A<sub>cp</sub>/p<sub>c</sub>" → π(D − b<sub>e</sub>)²/4; §5.7.3.6.3: p<sub>h</sub> = perimeter of the centerline of the closed transverse torsion reinforcement → πD<sub>h</sub>. |
| 2026-09-29 | C6 | §5.7.2.3: torsion transverse reinforcement "may consist of closed stirrups …, a closed cage of welded wire reinforcement …, or ties or hoops" — spirals not listed. Spiral T<sub>n</sub> = 0 retained. |
| 2026-09-29 | C7 | §5.6.4.4 + C5.6.4.4 ("values of 0.85 and 0.80 in Eqs. 5.6.4.4-2 and 5.6.4.4-3"): 0.85 for spirals or hoops closed by full-welded splice / full-mechanical coupler / hooks around longitudinal bars; 0.80 for ties or lap-spliced hoops. §5.2 defines a hoop by those closures. **New input** "Hoop closure" (default lap splice → 0.80, unchanged results; welded/mech./hooks → 0.85 and ρ<sub>s</sub> check). Pinned. |
| 2026-09-29 | C8 (part) | §5.6.4.6: ρ<sub>s</sub> applies to spirals and hoops with welded/mechanical/hooked closure (now checked for such hoops too); f<sub>yh</sub> ≤ 75.0 ksi (100 ksi only for Art. 5.4.3.3 elements) → capped. §5.10.4.2 / 5.10.4.4: clear spacing ≥ max(1.0 in, 1.33a<sub>g</sub>), c/c ≤ min(6d<sub>b</sub>, 6.0 in), spiral d ≥ 0.375 in; §5.10.4.3 ties: size (#3 / #4 for #11+ or bundles), spacing ≤ min(D, 12 in) or min(D/2, 6 in) for bundles of bars larger than #10 → new information-only "Compression-member detailing" block (panel + report §10.5). Coefficients → C8b (resolved). Pinned. |
| 2026-09-29 | C11 | §5.10.3.1.5: "a unit of bundled bars shall be treated as a single bar of a diameter derived from the equivalent total area" (d<sub>b</sub>√n ✓); ≤ 4 bars per bundle (UI max 3 ✓); bars larger than #11 ≤ 2 per bundle in flexural members → detailing check. |
| 2026-09-29 | C12 | §5.6.4.2: "minimum number of longitudinal reinforcing bars in the body of a column shall be six in a circular arrangement … minimum size of bar shall be #5" → detailing check; optimizer minimum of 6 bars confirmed. |
| 2026-09-29 | (confirms) | §5.6.7 d<sub>c</sub> "to center of the flexural reinforcement located closest thereto" (M1); §5.6.3.3 S<sub>c</sub> / f<sub>cpe</sub> "at extreme fiber … where tensile stress is caused by externally applied loads" (F3, F4). |
| 2026-09-28 | F3 | Mechanics: tendon below centroid decompresses the top fibre → hogging fcpe = P/A − P·e·y<sub>t</sub>/I (clamped ≥ 0). Fixed in `do_flexure`, row Mcr and `circ_engine`. Pinned `tests/test_review_fixes.py`. |
| 2026-09-28 | F4 | Mechanics: cracking is governed by the tension fibre → Sc = I/y<sub>tension fibre</sub> by Mu sign. Rect/circular unchanged (symmetric). Pinned. |
| 2026-09-28 | F5 | Rows now use the active-row Mcr assembly (γ1/γ2/γ3 incl. overrides, fcpe, sign-aware Sc), sign-dependent φ for the Nu term (audit D1), I-section T-shaped cracked section, and the correct compression-steel moment (+A's·fy·(ds − d's)) in the T-branch row Mn. No row status lights changed in the 180 golden cases; long-steel D/C slightly lower for axial-tension rows. |
| 2026-09-28 | F6 | Pure-tension key point uses bar positions from the top face without m_sign — now equals the plotted curve point for both faces. Pinned. |
| 2026-09-28 | R2 | B5 invalid message now shows the engine's `b5_invalid_reason` (panel + report). |
| 2026-09-28 | R3 | Federal header now "AASHTO LRFD 10th Edition (2024)" (engine and excerpt PDF are 10th Ed.). |
| 2026-09-28 | R4 | Report reads engine-unit inputs via `VE()`; checked with length units switched to ft. |
| 2026-09-28 | R5 | I-section report branches test the engine's compression-flange depth `fl.hf`. |
| 2026-09-28 | R6a | Labels: Nu term shown as 0.5Nu/φ<sub>N</sub> (φc compression / φf tension); γ3 annotated by the selected reinforcement spec. |
| 2026-09-28 | M1, D-C2 | dc = cover + stirrup diameter + db/2, consistent with the app's own bar depth (cover is clear to the stirrup). dc +0.5 in for #4 stirrups → s_crack ≈ 1.3 in tighter (conservative). Circular already used the bar-centre distance. Pinned. |
| 2026-09-28 | M2 | Cracked-section axial term uses b·hf + bw·(c_cr − hf) when the NA is in the web. Pinned. |
| 2026-09-28 | M12 | Dead `return profile` removed from `pt_engine.py`. |
| 2026-09-28 | M13 | Row εt uses dt = max(ds, dp) when PT is on the tension side. |
| 2026-09-28 | H2 | Unit labels written with `innerHTML` — "in&amp;sup2;" no longer shown literally. |
| 2026-09-28 | (cross-check) | Excerpt PDF pp. 5-127–5-132 checked against `_PT_LIMITS_DEFAULTS`: 0.65/0.70 f'ci; 0.24λ√f'ci, 0.0948λ√f'ci ≤ 0.2; 0.45 f'c, 0.60φw f'c; 0.19λ√f'c ≤ 0.6, 0.0948λ√f'c ≤ 0.3, unbonded no tension — all match. |
