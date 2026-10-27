# CSiBridge Results Extractor

Pulls frame forces, joint reactions and joint displacements out of an analysed CSiBridge v27.1 model into an Excel workbook,
for chosen frames / joints / groups and load cases / combinations, as envelope, correspondence, or both.
Self-contained: it shares no code with the concrete-section app. Units are whatever the model is in (written to the
sheet's units row and to Run info).

## Run

```
cd csibridge_extractor
run.bat
```

`run.bat` creates `.venv` on first use, installs `requirements.txt`, then starts `app.py`. Extra arguments are passed on; relative paths in them are relative to the
`csibridge_extractor` folder (the script changes to it). It prefers `py -3` and falls back to `python`.

Demo without CSiBridge (replays a recorded fixture):

```
run.bat --fake tests\fixtures\fake_model.json
```

In the window: Connect, enter frames / joints (labels or ranges like `1201-1210`) and/or pick groups, tick cases,
choose Envelope / Correspondence / Both per table, set the output folder (empty = next to the model file) and the
name pattern (`{model}`, `{stamp}`), then Run. Cases without results are greyed out and cannot be ticked.
Cancel stops the run; the workbook is kept but marked INCOMPLETE.

With CSiBridge:
- **Close every dialog in CSiBridge** before Connect / Run: while a dialog is open CSiBridge answers no API call and
  the tool just waits.
- Several CSiBridge windows open: it connects to the first one started (the note after Connect names the model).
  To pick another, start with its process id: `run.bat --pid 36740` (Task Manager > Details > PID).
- Speed: the results are filtered by the smallest existing CSiBridge group that contains all requested objects
  (~0.5 s). If only a whole-model group covers them, the whole table is read (seconds to minutes on big models):
  put the objects you extract often into a group in CSiBridge. The tool never edits the model.
- Joint reactions and joint displacements (U1-U3, R1-R3): correspondence is requested from CSiBridge like frame
  forces; if CSiBridge returns only Max/Min rows for a case, the Run info tab says so.
  Joints can come from typed labels or from groups (a group's joints feed both joint tables).

## CSV output (big extractions, Power Query)

Output format "CSV folder" writes `<name>\` with one CSV per table/mode plus `Run info.csv`: UTF-8, one header row
with units in the names (`P [Kip]`), numbers with a `.` decimal point. Much faster than .xlsx on large tables.
Power Query: Data > Get Data > From File > From Folder (or From Text/CSV for one file). If Windows uses a comma
decimal separator, set the column types with Change Type > Using Locale > English (United States).

For linked spreadsheets tick **Overwrite** (Output section; the job's `overwrite: true`): every run replaces the same
file / folder (name without `{stamp}`), so Power Query keeps the same source path; just re-run the saved job and
Refresh. In CSV mode only the extractor's own files (table CSVs, `Run info.csv`) are replaced; stale table files from
a previous run are removed and other files in the folder are left alone. If one of them is open, the run stops before
anything is deleted.

## Jobs

Save job / Load job store the whole selection as JSON (see `extractor/jobs.py`). A job also runs headless:

```
py -m csibridge_extractor.extractor.cli run JOB.json [--out PATH] [--fake FIXTURE] [--pid PID]
```

Exit code 0 = complete, 2 = complete with warnings, 1 = failed or incomplete.

## Workbook layout

One tab per table and mode: `Frame Forces – Envelope`, `Frame Forces – Corresp.`, `Joint Reactions – Envelope`,
`Joint Reactions – Corresp.`, `Joint Displacements – Envelope` (long tables continue on numbered tabs), each with a header row and a units row, then
data rows. The last tab, `Run info`, records status (COMPLETE / INCOMPLETE), model file and version, units, the job,
resolved counts, cases extracted, rows per tab, timing, every warning and note. Check Run info before using the data.
The frame tab can be copy-pasted into the concrete app's Column on Shaft paste box.

## Status

- Done: targets resolution, job files, streaming writer, runner, CLI, this window, and the real CSiBridge adapter
  (`extractor/csi_source.py`, DatabaseTables route; checked 2026-10-23 on a v27.1 model against the probe rows).

## Tests

`py -m pytest csibridge_extractor/tests -q` (pywebview and CSiBridge are not needed).
