# CSiBridge Results Extractor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone tool in `csibridge_extractor/` that attaches to a running CSiBridge v27.1, extracts Frame Forces and Joint
Reactions (envelope and/or correspondence) for selected frames/joints/groups and cases, and writes them exactly as CSiBridge
produces them into one Excel workbook, with saved, re-runnable jobs.

**Architecture:** Everything except the CSiBridge adapter is built and tested against a `ResultSource` interface and a
`FakeSource` that replays recorded data. Task 1 is a **probe script the user runs on the CSiBridge laptop**; its JSON output
decides which API route the real adapter (Task 7) uses and becomes the fake's fixture. Rows stream from the source into an
XlsxWriter workbook (constant-memory mode) with continuation tabs at Excel's row limit. A small pywebview window drives it.

**Tech Stack:** Python 3.12, pythonnet 3.0.5 (CSiBridge .NET API, already pinned by the concrete app), XlsxWriter (new, writing),
openpyxl (tests only, reading), pywebview 4.0 (UI), pytest.

**Spec:** `docs/superpowers/specs/2026-10-21-csibridge-extractor-design.md`

## Global Constraints

- Self-contained folder `csibridge_extractor/`; imports nothing from the concrete app; not added to `run_test_suite.py`. Its tests
  run with `py -m pytest csibridge_extractor/tests -q`.
- Target CSiBridge **v27.1** only; a different version → a warning (not a crash).
- Rows are written **exactly as CSiBridge returns them** (no filtering, sorting, unit conversion or computed rows), in the model's
  present units, which are written into row 2 of each tab.
- **Never silently drop data:** missing labels/groups/cases, cases without results, API errors and row-limit continuation are all reported in
  the log and the Run-info tab.
- The model must be left as found: any results-selection / table-output option changed during extraction is restored afterwards
  (also on error/cancel).
- Frame tab columns: `Frame, Station, OutputCase, CaseType, StepType, P, V2, V3, T, M2, M3, FrameElem, ElemStation`.
  Joint tab columns: `Joint, OutputCase, CaseType, StepType, F1, F2, F3, M1, M2, M3`. Row 1 = names, row 2 = units, data from row 3.
- Tab names: `Run info`, `Frame Forces – Envelope`, `Frame Forces – Corresp.`, `Joint Reactions – Envelope`,
  `Joint Reactions – Corresp.`; continuation tabs append ` (2)`, ` (3)`…; Excel max 1,048,576 rows per tab (2 header rows
  repeated on each continuation tab).
- Workbook default name `<model name>_results_<YYYY-MM-DD_HHMM>.xlsx` beside the model file.
- Code stays PyInstaller-friendly (no dynamic imports by string, data files via a resource helper); no exe build in this plan.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A saved job references labels/groups/cases that no longer exist** after the model changed: the user expects the run to proceed with
   the rest and list exactly what was skipped → `test_rerun_reports_missing_targets_and_cases` (Task 6).
2. **The output workbook is open in Excel** (file locked): the user expects a clear error before any extraction starts, not after minutes
   → `test_locked_output_fails_fast` (Task 6).
3. **Cancel mid-run:** the user expects a valid, readable partial workbook clearly marked INCOMPLETE in Run info, and the model's output
   options restored → `test_cancel_writes_incomplete_workbook` (Task 6) + the restore assertion in Task 7's adapter test.
4. **More rows than one Excel tab holds:** the user expects continuation tabs, with no row lost or duplicated →
   `test_continuation_tabs_preserve_every_row` (Task 5).
5. **CSiBridge not running / no model open / not analysed / wrong version:** the user expects a plain message saying which →
   `test_connect_messages` (Task 7, with the adapter's attach path mocked).

---

### Task 1: Probe script (run by the user on the CSiBridge laptop)

**Files:** Create `csibridge_extractor/__init__.py` (empty), `csibridge_extractor/probe/probe_csibridge.py`,
`csibridge_extractor/probe/README.md`, `csibridge_extractor/requirements.txt` (`pythonnet==3.0.5`, `XlsxWriter`, `pywebview==4.0`),
`csibridge_extractor/requirements-dev.txt` (`pytest`, `openpyxl`), `csibridge_extractor/tests/test_probe_helpers.py`.

**Interfaces:**
- Produces: `probe_result_<YYYYmmdd_HHMMSS>.json` + `probe_rows_<route>_<table>_<mode>.csv` files in an output folder. JSON keys:
  `attach` (method used, ProgID, DLL path, success, errors), `version`, `model_file`, `present_units`, `cases` / `combos` (name, type, has
  results), `groups`, `n_frames`, `n_joints`, `routes.database_tables` (available table keys containing "Frame"/"Reaction", the field
  lists, the table output-option values found and tried, per (table, mode) the StepType values returned, row counts, seconds, errors),
  `routes.direct` (the same for the Results.Setup + FrameForce / JointReact calls with each multi-valued option value tried), `restored`
  (true/false + what was changed and put back).
- Pure helpers (unit-tested, no CSiBridge): `parse_args(argv) -> Namespace` (`--frames`, `--joints`, `--group`, `--case` (repeatable),
  `--out DIR`, `--dll PATH`), `unpack_out(ret) -> tuple` (normalises pythonnet out-parameter tuples: return code first; non-zero → raises
  `ProbeCallError(name, code)`), `rows_to_csv(path, header, rows)`, `summarise(result: dict) -> str`.

Approach (for the implementer; every API name below is a **candidate to be tried and recorded**, not a fact: the probe exists because
these are unverified for v27.1):
- Attach: locate `CSiAPIv1.dll` (search `C:\Program Files\Computers and Structures\CSiBridge*\`, or `--dll`), `clr.AddReference`,
  `cHelper(Helper()).GetObject("CSI.CSiBridge.API.SapObject")`; fallback `comtypes.client.GetActiveObject` if comtypes is installed.
  Record every attempt.
- Metadata: model filename, version, present units, case and combo name lists, analysis status per case, group list, frame/point
  counts, group assignments for `--group`.
- Route (a) **DatabaseTables**: list available tables; find the frame-forces and joint-reactions table keys; read their fields; read the
  current table output options; for each candidate multi-valued option value (envelope / step-by-step / last step / correspondence, as
  the enum/values exposed by the API), set it, select only `--case` for display, fetch the table (filtered by `--group` if given, else
  all and filtered client-side to `--frames`/`--joints`), record row count, distinct StepType values, seconds, the first 50 rows to CSV;
  restore the original options and display selections.
- Route (b) **direct**: Results.Setup deselect-all / select case or combo / multi-valued combo option values; FrameForce and JointReact for
  the targets (object or group item type); record the same; restore.
- Never save the model; wrap everything in try/finally restore; print `summarise(...)` at the end with "NEXT: send me the JSON +
  CSV folder".
- README: exact commands for the user (with the concrete app's `.venv`), e.g.
  `.venv\Scripts\python.exe csibridge_extractor\probe\probe_csibridge.py --frames 1227 --joints <a support joint> --case Str-I1 --out probe_out`,
  plus "also export the same table from CSiBridge (Display → Show Tables → Element Forces – Frames, envelope and
  correspondence) to Excel and put it in probe_out for comparison".

- [ ] **Step 1: Write the failing tests** `test_parse_args_defaults_and_repeatable_case`, `test_unpack_out_return_code_first`
  (`(0, 3, ['a'])` → `(3, ['a'])`; `(1, ...)` → raises `ProbeCallError`), `test_rows_to_csv_roundtrip` (tmp_path),
  `test_summarise_lists_routes_and_errors`.
- [ ] **Step 2: Run** `py -m pytest csibridge_extractor/tests/test_probe_helpers.py -q`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** the helpers and the probe body as above (the CSiBridge part is untestable here; keep it in functions
  `attach`, `probe_metadata`, `probe_database_tables`, `probe_direct`, each returning dicts and catching/recording exceptions).
- [ ] **Step 4: Run** the tests. Expected: PASS. Also `py -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" csibridge_extractor/probe/probe_csibridge.py`.
- [ ] **Step 5: Commit** `feat(extractor): CSiBridge API probe script`. **Then the controller pushes and hands the README commands to the
  user; Task 7 waits for the probe output. Tasks 2-6 and 8 continue meanwhile.**

### Task 2: Targets — label parsing and resolution

**Files:** Create `csibridge_extractor/extractor/__init__.py`, `csibridge_extractor/extractor/targets.py`,
`csibridge_extractor/tests/test_targets.py`.

**Interfaces:**
- `parse_labels(text: str) -> list[str]`: splits on commas, whitespace and newlines; keeps order and drops duplicates; a token `A-B` where A and B are both
  integers is a range candidate `RangeToken(a, b)`; anything else is a literal label (CSI labels may contain letters/dashes, e.g. `1227-1`
  is a literal, not a range, when it isn't two integers… rule: `^\d+-\d+$` is a range, otherwise literal).
- `resolve(frames_text, joints_text, groups: list[str], model: ModelLists) -> Resolution` where
  `ModelLists(frames: set[str], joints: set[str], groups: dict[str, tuple[set[str], set[str]]])` (group → (frames, joints)) and
  `Resolution(frames: list[str], joints: list[str], missing_frames: list[str], missing_joints: list[str], missing_groups: list[str],
  empty_ranges: list[str])`. Ranges expand to the integers in [a, b] that exist as labels in the model (others ignored; a range with none →
  `empty_ranges`). Group members are added (frames → frames, joints → joints). Output keeps first-seen order, de-duplicated.

- [ ] **Step 1: Failing tests:** `test_parse_mixed_separators`, `test_range_vs_literal` (`1301-1310` range; `1227-1` literal),
  `test_resolve_ranges_only_existing`, `test_resolve_groups_and_missing`, `test_dedupe_keeps_order`.
- [ ] **Step 2–4: Run → implement → run.** Expected: FAIL, then PASS.
- [ ] **Step 5: Commit.**

### Task 3: Jobs — save / load / validate

**Files:** Create `csibridge_extractor/extractor/jobs.py`, `csibridge_extractor/tests/test_jobs.py`.

**Interfaces:**
- `Job` dataclass: `version: int = 1`, `frames: str = ""`, `joints: str = ""`, `groups: list[str]`, `cases: list[str]`,
  `tables: dict` = `{"frame": {"enabled": bool, "modes": list[str]}, "joint": {...}}` with modes ⊆ {"envelope","correspondence"},
  `output_dir: str | None` (None = beside the model), `name_pattern: str = "{model}_results_{stamp}.xlsx"`, `open_when_done: bool = True`.
- `save_job(job, path)`, `load_job(path) -> Job` (UTF-8 JSON; unknown keys ignored with a warning list; a missing version → 1;
  invalid mode → ValueError naming the field), `validate(job) -> list[str]` (errors: nothing to extract, no cases, a table enabled with no mode).

- [ ] **Step 1: Failing tests:** `test_roundtrip`, `test_unknown_keys_warn`, `test_invalid_mode_raises`, `test_validate_messages`.
- [ ] **Step 2–4: Run → implement → run.**
- [ ] **Step 5: Commit.**

### Task 4: ResultSource interface and FakeSource

**Files:** Create `csibridge_extractor/extractor/source.py`, `csibridge_extractor/tests/fixtures/fake_model.json`,
`csibridge_extractor/tests/test_source.py`.

**Interfaces:**
- `TABLE_COLUMNS = {"frame": [...13 names...], "joint": [...10 names...]}` (Global Constraints).
- `ModelInfo(file: str, version: str, units: dict, analysed: bool)`; `CaseInfo(name: str, kind: "case"|"combo", type: str, has_results: bool)`.
- `class ResultSource(Protocol)`: `model_info() -> ModelInfo`; `list_cases() -> list[CaseInfo]`; `model_lists() -> targets.ModelLists`;
  `units_row(table: str) -> list[str]` (same length as TABLE_COLUMNS[table]); `iter_rows(table: str, mode: str, cases: list[str],
  objects: list[str]) -> Iterator[tuple]` (rows in TABLE_COLUMNS order, exactly as CSiBridge gives them; may raise `SourceError`);
  `notes() -> list[str]` (e.g. "correspondence not provided for joint reactions"); `close()` (restores the model's options; idempotent).
- `FakeSource(fixture_path)` replays `fake_model.json`. Build the fixture from the user's two real tables (the concrete app's
  `tests/fixtures_csi/frame1227_strI1.txt` (envelope) and `frame1227_strI1_concurrent.txt` (correspondence)), two small synthetic joint
  reaction sets, two groups, one case without results, and present units kip/ft. Task 7 replaces/extends the fixture with real probe rows.

- [ ] **Step 1: Failing tests:** `test_fake_rows_match_concrete_fixtures` (the rows equal the parsed concrete-app fixture rows, in kip-ft),
  `test_units_row_lengths`, `test_case_without_results_flagged`, `test_close_idempotent`.
- [ ] **Step 2–4: Run → implement → run.**
- [ ] **Step 5: Commit.**

### Task 5: Workbook writer (streaming, continuation tabs, Run info)

**Files:** Create `csibridge_extractor/extractor/writer.py`, `csibridge_extractor/tests/test_writer.py`.

**Interfaces:**
- `WorkbookWriter(path, row_limit: int = 1_048_576)`: context manager; `open_table(tab_base: str, header: list[str], units: list[str])
  -> TableHandle`; `TableHandle.write(row: tuple)` (numbers as numbers, text as text; switches to `tab_base + " (n)"` with both header rows
  repeated when the limit is reached); `TableHandle.rows_written: int`, `TableHandle.tabs: list[str]`; `write_run_info(items:
  list[tuple[str, str]])` (Run info tab FIRST in tab order); `close()`. XlsxWriter `constant_memory=True`.
- `check_writable(path) -> None`: raises `OutputLockedError(path)` if the file exists and can't be opened for writing (e.g. open in Excel),
  or the folder isn't writable.

- [ ] **Step 1: Failing tests:** `test_two_header_rows_and_types` (read back with openpyxl), `test_continuation_tabs_preserve_every_row`
  (row_limit=10, 25 rows → tabs "X", "X (2)", "X (3)", each with 2 header rows, all 25 data rows in order, none duplicated),
  `test_run_info_first_tab`, `test_check_writable_locked` (simulate a lock by holding the file open exclusively on Windows; skip
  elsewhere), `test_tab_names_within_31_chars`.
- [ ] **Step 2–4: Run → implement → run.**
- [ ] **Step 5: Commit.**

### Task 6: Runner + CLI

**Files:** Create `csibridge_extractor/extractor/runner.py`, `csibridge_extractor/extractor/cli.py`, `csibridge_extractor/tests/test_runner.py`.

**Interfaces:**
- `run_job(job: Job, source: ResultSource, out_path: str | None = None, progress: Callable[[dict], None] | None = None,
  cancel: threading.Event | None = None) -> RunResult` where `RunResult(path, rows: dict[str, int], tabs: list[str], warnings:
  list[str], seconds: float, complete: bool)`.
- Steps: validate job → `check_writable` (fail fast) → resolve targets against `source.model_lists()` → check cases exist and have results
  (warn and skip the others) → for each enabled table × mode: `open_table`, stream `iter_rows` (per object batches as the source prefers),
  progress callback every 1,000 rows `{table, mode, rows, seconds}`, honour `cancel` between rows/batches → Run info (model file, version,
  units, job JSON, resolved counts, rows per tab, warnings, `complete`, tool version, timestamps) → `source.close()` in finally.
  A `SourceError` on one object is recorded as a warning with the object name and the run continues.
- `cli.py`: `python -m csibridge_extractor.extractor.cli run JOB.json [--out PATH] [--fake FIXTURE]` (`--fake` uses FakeSource, for tests and
  demos); prints the progress and the summary; exit code 0 complete, 2 complete with warnings, 1 failed/cancelled.

- [ ] **Step 1: Failing tests:** `test_end_to_end_fake` (frame envelope + correspondence + joint envelope → tabs and row counts equal the
  fixture), `test_rerun_reports_missing_targets_and_cases`, `test_locked_output_fails_fast` (no source calls made — assert via a spy),
  `test_cancel_writes_incomplete_workbook` (cancel after the first batch → workbook readable, Run info `complete = False`, `close()` called),
  `test_source_error_on_one_object_continues`, `test_cli_exit_codes`.
- [ ] **Step 2–4: Run → implement → run.**
- [ ] **Step 5: Commit.**

### Task 7: Real CSiBridge adapter (BLOCKED until the user's probe output is available)

**Files:** Create `csibridge_extractor/extractor/csi_source.py`, `csibridge_extractor/tests/fixtures/probe_<date>/` (the user's probe JSON +
CSVs + their CSiBridge table exports), `csibridge_extractor/tests/test_csi_source.py`, `csibridge_extractor/probe/acceptance.py`.

**Interfaces:**
- `CsiSource(dll_path: str | None = None) -> ResultSource`: implements Task 4's protocol with the route the probe proved reproduces
  CSiBridge's own table (prefer DatabaseTables if both do; choose by the probe's equality + speed evidence, and record the choice in the
  module docstring with the probe file name). Version check: v27.1 → OK, else a warning in `notes()`. Records every option it changes
  and restores it in `close()`.
- `connect_message(exc) -> str`: plain messages for: CSiBridge not running; no model open; model not analysed; DLL not found;
  version mismatch.
- `acceptance.py`: run on the laptop: extracts the probe's selection with `CsiSource` and compares, row by row, with the user's
  CSiBridge export (same rows, values equal to the export's printed precision), for envelope and correspondence; prints PASS/FAIL per
  table/mode.

- [ ] **Step 1:** Read the probe output; write the route decision (2–5 lines) into the module docstring.
- [ ] **Step 2: Failing tests** (no CSiBridge: a fake .NET object built from the probe's recorded responses):
  `test_rows_equal_probe_rows` per table/mode, `test_options_restored_on_close_and_on_error`, `test_connect_messages`,
  `test_version_mismatch_warns`.
- [ ] **Step 3–4: Implement → run.** Expected: PASS.
- [ ] **Step 5:** The user runs `acceptance.py` on the laptop. Expected: PASS for every table/mode that CSiBridge provides; any mode
  CSiBridge doesn't provide is reported in `notes()` (not a failure).
- [ ] **Step 6: Commit.**

### Task 8: Window (pywebview) + run.bat

**Files:** Create `csibridge_extractor/app.py`, `csibridge_extractor/api.py`, `csibridge_extractor/ui/index.html`,
`csibridge_extractor/run.bat`, `csibridge_extractor/README.md`, `csibridge_extractor/tests/test_api.py`.

**Interfaces:**
- `Api` (JSON-string methods like the concrete app): `connect() -> {model_info, cases, groups, n_frames, n_joints, notes} | {error}`
  (uses `CsiSource`, or `FakeSource` when started with `--fake FIXTURE`); `resolve(job_json) -> {counts, missing...}`;
  `run(job_json) -> {started}` (runs in a background thread) + `poll() -> {progress, log, done, result}` + `cancel()`;
  `save_job(job_json)` / `load_job()` (file dialogs); `open_file(path)`.
- UI sections in the spec's order (§4.6): connection bar; targets (frames / joints text areas, group multi-select from the model, resolved
  counts); cases (tick-list with a text filter, the ones without results greyed with a note); tables (Frame forces / Joint reactions, each
  Envelope / Correspondence / Both); output (folder + name pattern preview, open when done); Save / Load / Run / Cancel; progress + log.
- `run.bat`: creates `.venv` in `csibridge_extractor/` if missing, installs `requirements.txt`, starts `app.py`.

- [ ] **Step 1: Failing tests** for `Api` with FakeSource: `test_connect_fake`, `test_resolve_counts_and_missing`,
  `test_run_poll_until_done` (writes a workbook in tmp_path), `test_cancel_via_api`, `test_errors_are_json`.
- [ ] **Step 2–4: Run → implement → run.**
- [ ] **Step 5: Manual check** with `run.bat --fake tests\fixtures\fake_model.json`: the window opens, Connect lists the fake cases/groups,
  Run writes the workbook, and the frame tab copy-pastes into the concrete app's Column on Shaft paste box and parses.
- [ ] **Step 6: Commit.**

---

## Self-review notes
- Spec coverage: §4.1 → T7/T8; §4.2 → T2; §4.3 → T4/T7; §4.4 → T5/T6; §4.5 → T3/T6; §4.6 → T8; §4.7 → T5 streaming + T1/T7 timing;
  §6 → T1/T7 (probe, acceptance) and the fake-based unit tests.
- Task 7 is the only blocked task; Tasks 2–6 and 8 proceed in order on FakeSource.
