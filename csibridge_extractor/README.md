# CSiBridge Results Extractor

Pulls frame forces and joint reactions out of an analysed CSiBridge v27.1 model into an Excel workbook,
for chosen frames / joints / groups and load cases / combinations, as envelope, correspondence, or both.
Self-contained: it shares no code with the concrete-section app. Units are whatever the model is in (written to the
sheet's units row and to Run info).

## Run

```
cd csibridge_extractor
run.bat
```

`run.bat` creates `.venv` on first use, installs `requirements.txt`, then starts `app.py`. Extra arguments are passed on.

Demo without CSiBridge (replays a recorded fixture):

```
run.bat --fake tests\fixtures\fake_model.json
```

In the window: Connect, enter frames / joints (labels or ranges like `1201-1210`) and/or pick groups, tick cases,
choose Envelope / Correspondence / Both per table, set the output folder (empty = next to the model file) and the
name pattern (`{model}`, `{stamp}`), then Run. Cases without results are greyed out and cannot be ticked.
Cancel stops the run; the workbook is kept but marked INCOMPLETE.

## Jobs

Save job / Load job store the whole selection as JSON (see `extractor/jobs.py`). A job also runs headless:

```
py -m csibridge_extractor.extractor.cli run JOB.json [--out PATH] [--fake FIXTURE]
```

Exit code 0 = complete, 2 = complete with warnings, 1 = failed or incomplete.

## Workbook layout

One tab per table and mode: `Frame Forces – Envelope`, `Frame Forces – Corresp.`, `Joint Reactions – Envelope`,
`Joint Reactions – Corresp.` (long tables continue on numbered tabs), each with a header row and a units row, then
data rows. The last tab, `Run info`, records status (COMPLETE / INCOMPLETE), model file and version, units, the job,
resolved counts, cases extracted, rows per tab, timing, every warning and note. Check Run info before using the data.
The frame tab can be copy-pasted into the concrete app's Column on Shaft paste box.

## Status

- Done: targets resolution, job files, streaming writer, runner, CLI, this window (tested on the fake source).
- Pending: **Task 7**, the real CSiBridge adapter (`extractor/csi_source.py`), which waits for the probe
  (`probe/README.md`) to be run on the CSiBridge laptop. Until it exists, Connect without `--fake` reports
  "real CSiBridge adapter not available yet (Task 7)".

## Tests

`py -m pytest csibridge_extractor/tests -q` (pywebview and CSiBridge are not needed).
