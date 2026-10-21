# CSiBridge Results Extractor — Design

Date: 2026-10-21 · Status: draft for review · Author: Claude, from a brainstorm with the user

## 1. Intent

Exporting large result tables from CSiBridge to Excel through its table viewer is slow and unreliable, especially with
**correspondence** output (concurrent forces), which multiplies the row count. This standalone desktop tool connects
to CSiBridge running on the same PC, reads the selected results directly through CSiBridge's API (OAPI), and writes
them to an Excel workbook quickly and reproducibly. The extraction can be saved as a job and re-run with one click after
each re-analysis.

The workbook tabs use CSiBridge's own table layout, so a tab can be copied straight into the AASHTO concrete app's
"Column on Shaft" paste box (its parser already reads that format).

## 2. Goals / non-goals / anti-goals

**Goals (v1)**
- Extract **Frame Forces** (CSiBridge table "Element Forces – Frames") and **Joint Reactions** for the user's selection.
- For each table: **Envelope** (StepType Max/Min), **Correspondence** (concurrent rows, StepType e.g. "Max P", "Min P"),
  or both.
- Targets: any mix of **frame labels, joint labels, and group names**.
- Load cases and combinations: picked from the list the model reports.
- Save / load / re-run an extraction **job**.
- One Excel workbook per run.
- v1 runs from source on the user's laptop (like the concrete app's `run.bat`). A double-click **.exe** for colleagues is wanted
  later but **deferred** (user, 2026-10-21: "don't worry about exe right now"); keep the code PyInstaller-friendly.

**Non-goals (v1)** — user decision 2026-10-21: "extract the data as it comes from CSI; filtering or changing later".
- No filtering of stations, no re-sorting, no reduction, no unit conversion beyond what CSiBridge returns.
- No direct import into the concrete app (copy-paste is enough for now); no other result tables (displacements, section
  cuts, etc.); not running the analysis; no separate GitHub repository yet.

**Anti-goals (it fails even if it "works" if…)**
- …it silently drops or truncates data: Excel's row limit, labels not found in the model, cases not run, or API errors must
  all be reported, never hidden.
- …a workbook can't be traced to its model and analysis (the Run-info tab is mandatory).
- …the numbers differ from CSiBridge's own tables for the same selection (the acceptance test compares against them).
- …it modifies the model (results selection/output options may be changed during extraction but must be restored).

## 3. Constraints
- Runs on the **same Windows PC as CSiBridge**, with the model open and analysed. Target version: **CSiBridge v27.1**
  (user, 2026-10-21) — bind to that version's API; other versions are out of scope for v1 (detect and warn if a different version is found).
- Lives in a self-contained folder **`csibridge_extractor/`** in the AASHTO_Concrete_App repo (user decision: "start as a folder, move to
  a repo later"). It imports nothing from the concrete app, has its own tests and its own `build_exe.bat`, and is not part
  of the concrete app's `run_test_suite.py`.
- One-file Windows .exe (user decision), the same approach as the concrete app's build (Python + pywebview window + PyInstaller).
- Rows are written exactly as returned by CSiBridge, in the model's **present units**, which are written into the units row.

## 4. How it works (decided)

### 4.1 Connection
"Connect" attaches to the running CSiBridge instance through the OAPI (.NET; `pythonnet`, the same library the concrete
app's window already ships) and reads: model file path, present units, the list of load cases / combinations and whether each
has results, frame/joint/group names. If the model isn't analysed or a selected case has no results, the tool says so.

### 4.2 Targets
Three inputs, any mix:
- **Frames:** labels typed or pasted (comma/space/newline separated; ranges like `1301-1310` expanded only where those labels exist).
- **Joints:** same.
- **Groups:** picked from the model's group list. A group contributes its frames to the frame table and its joints to the
  reaction table.
The UI shows how many frames/joints the selection resolves to. Labels or groups not in the model are listed as warnings.

### 4.3 Tables and modes
- Frame forces columns (as CSiBridge's table): `Frame | Station | OutputCase | CaseType | StepType | P | V2 | V3 | T | M2 | M3 | FrameElem | ElemStation`.
- Joint reactions columns: `Joint | OutputCase | CaseType | StepType | F1 | F2 | F3 | M1 | M2 | M3`.
- Row 1 = column names, row 2 = units (as CSiBridge prints them, e.g. `ft`, `Kip`, `Kip-ft`), then data. No title row.
- **The table is extracted exactly as CSiBridge produces it** (user, 2026-10-21): the mode the user picks (Envelope /
  Correspondence) is passed to CSiBridge as its own output option for that table, and whatever rows CSiBridge then returns are
  written unchanged; the StepType column shows the user what each row is (`Max`/`Min` for envelopes; `Max P`, `Min P`, … for
  correspondence per the user's sample; blank for single-valued cases). If CSiBridge does not provide correspondence for a
  case or for a table (e.g. possibly joint reactions), the tool writes what CSiBridge gives and notes it in the log/Run info —
  **the tool never computes concurrent rows itself**.
- Case kinds (Claude's call, following "as it comes from CSI"): single-valued cases (linear static, linear-add combos) appear with
  blank StepType in whichever tab is extracted; moving-load and envelope combinations follow the chosen mode; multi-step cases
  (staged construction, nonlinear, time history) use CSiBridge's default multi-step output setting, recorded in Run info.

### 4.4 Workbook
`<model name>_results_<YYYY-MM-DD_HHMM>.xlsx` (default beside the model file; path editable), with tabs:
- `Run info`: model file path, model file date, analysis time if available, present units, CSiBridge version, the job's full
  settings, tool version, rows per tab, warnings.
- `Frame Forces – Envelope`, `Frame Forces – Corresp.`, `Joint Reactions – Envelope`, `Joint Reactions – Corresp.`: only the
  ones selected.
- When a tab would exceed 1,048,576 rows, continuation tabs `… (2)`, `… (3)` repeat the two header rows.
Option "Open when done".

### 4.5 Jobs
A job is a small JSON file: targets (frame labels, joint labels, groups), cases/combos, tables + modes, output folder/name
pattern. Save / Load / Run. On re-run, missing labels/cases are reported, never silently dropped.

### 4.6 Window (text sketch)
1. Connection bar (Connect, model, units, analysed status).
2. Targets (frames, joints, groups + resolved counts).
3. Cases (tick-list with text filter).
4. Tables (Frame forces / Joint reactions, each Envelope / Correspondence / Both).
5. Output (path, open when done).
6. Jobs (Save / Load / Run).
7. Progress + log (rows per table, elapsed time, Cancel).

### 4.7 Performance target
Hundreds of frames × dozens of combinations with correspondence output in seconds to a few minutes, with steady memory
(stream rows into the workbook rather than holding them all).

## 5. Left to the builder
Internal module split, the Excel writing library (it must stream large sheets; it's a new dependency, which is fine for this separate
app), how API calls are batched (per object vs per group), UI styling, log format.

## 6. Verification approach (decided)
- **First build step = a probe script** run once on the user's laptop (CSiBridge v27.1). It confirms: attaching to the running
  instance; the model metadata calls; and, for two candidate routes, which one reproduces CSiBridge's own table exactly,
  envelope and correspondence:
  (a) the **database-tables API** (the same "Element Forces – Frames" / "Joint Reactions" tables the viewer shows, with their
  output options), preferred because it is "the table as it comes from CSI";
  (b) the direct result calls (frame forces / joint reactions with the results-setup output options).
  The probe also records how fast each route is on a realistic selection. The probe output is saved and drives the
  implementation (the route choice is the builder's, based on the probe evidence).
- Acceptance: for a small selection, the extractor's rows equal CSiBridge's own table export (same rows, same values to
  printed precision) for both envelope and correspondence; the frame tab pastes into the concrete app's Column on Shaft
  parser without error.
- Unit tests run without CSiBridge, against a fake API that replays recorded probe data.

## 7. Decisions from the builder check (2026-10-21)
- Correspondence not available → write what CSiBridge gives; the user reads StepType (user).
- Target CSiBridge v27.1 only for v1 (user).
- .exe deferred, so the one-time API registration / admin question is deferred with it (user).
- Non-envelope case kinds follow CSiBridge's own output (Claude's call; see §4.3).

## 8. Later (not v1)
Separate repository; .exe for colleagues (and its API-registration first-run check); direct import into the concrete app; filtering /
sorting / station selection; other result tables.
