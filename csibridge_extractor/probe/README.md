# CSiBridge probe: one-time check on the CSiBridge laptop

This script checks how CSiBridge v27.1 hands out its results to a program, so the extractor can be
built on calls that are known to work. It **only reads**. It changes a few table display / output options
while it runs and puts them back at the end. It **never saves the model and never runs the analysis**.

## What you need

- The laptop with CSiBridge v27.1.
- The `AASHTO_Concrete_App` folder on that laptop, with its `.venv` folder (it already has `pythonnet`).

## 1. Get the probe onto the laptop

Open a Command Prompt (Start menu, type `cmd`, Enter) and run, one line at a time
(change the first line to where your `AASHTO_Concrete_App` folder is):

```
cd C:\path\to\AASHTO_Concrete_App
git fetch origin
git checkout feature/csibridge-extractor
```

You can switch back later with `git checkout main`.

## 2. Prepare CSiBridge

1. Open CSiBridge and open the bridge model.
2. Run the analysis (or check that results are available).
3. **Create a small group first (required).** In CSiBridge select **1 or 2 column frames** and
   **1 or 2 support joints** (joints that have reactions), and assign them to a new group named, for example,
   `PROBE`. Keep it small: the probe asks CSiBridge for every result of this group, and a big group can take a
   very long time. The probe does not create groups itself.
4. Note the labels of those frames and joints and the name of one or two load combinations to test, for example
   `Str-I1`. Use a combination that includes the moving load, so envelope and correspondence give different rows.
5. Leave CSiBridge open with the model.

**Same "administrator" level:** start the Command Prompt the same way CSiBridge was started. If both were
opened normally, that's fine. If CSiBridge was started with "Run as administrator", start the Command Prompt
with "Run as administrator" too (right-click Command Prompt, then "Run as administrator"). Otherwise the probe
cannot see CSiBridge.

## 3. Run the probe

In the Command Prompt, in the `AASHTO_Concrete_App` folder, run (one line; change the labels, group and
combination to yours; add `--case` once per combination):

```
.venv\Scripts\python.exe csibridge_extractor\probe\probe_csibridge.py --group PROBE --frames 1227 --joints 15 --case Str-I1 --out probe_out
```

With two combinations:

```
.venv\Scripts\python.exe csibridge_extractor\probe\probe_csibridge.py --group PROBE --frames 1227 --joints 15 --case Str-I1 --case Serv-I --out probe_out
```

If it says it cannot find `CSiAPIv1.dll`, add the full path to it at the end, for example:
`--dll "C:\Program Files\Computers and Structures\CSiBridge 27\CSiAPIv1.dll"`

While it runs:
- **Do not close the window.** It prints a line before each step ("fetching ... this can take a few minutes").
  The whole run may take several minutes.
- If it really seems stuck for a long time, press **Ctrl+C once only**, then wait: it puts the CSiBridge
  settings back and writes its result file before it stops.
- It finishes with `=== CSiBridge probe summary ===` and a `NEXT:` line. Everything printed in the window is
  also saved in `probe_out\console.txt`.

It always writes its result file, even when something fails. A failure is still useful information.

## 4. Also export the same tables from CSiBridge (for comparison)

For the **same frames, joints and combination(s)** (the menu names below may differ slightly in v27.1; use the
Show Tables viewer):

1. Display > Show Tables > Analysis Results > Element Output > Frame Output > **Element Forces - Frames**.
   In the table options set the load combinations to **Envelopes**, then export to Excel and save it into the
   `probe_out` folder as `csi_frame_envelope.xlsx`.
2. Same table, load combinations set to **Correspondence**: save as `csi_frame_correspondence.xlsx`.
3. Joint Output > Reactions > **Joint Reactions**: export with **Envelopes** (`csi_joint_envelope.xlsx`) and
   with **Correspondence** (`csi_joint_correspondence.xlsx`). If Correspondence is not offered for joint
   reactions, write that down.

Filter each table to just the test frames / joints if you can (smaller files are fine).

## 5. What to send back

Zip the whole `probe_out` folder and send it. It should contain:
- `probe_result_<date>_<time>.json`
- `console.txt`
- all `probe_rows_*.csv` files
- the four CSiBridge Excel exports from step 4
- a short note with anything you noticed (for example "Correspondence not available for reactions", or an
  error message shown by CSiBridge).

## 6. Afterwards

The probe puts the table display options and the "selected for output" cases back as they were; the summary
shows `Restored: True`. Either way, **when you close CSiBridge, answer No to saving the model** (you can delete
the `PROBE` group first if you like; it doesn't matter as long as you don't save).
