# CSiBridge probe: one-time check on the CSiBridge laptop

This script checks how CSiBridge v27.1 hands out its results to a program, so the extractor can be
built on calls that are known to work. It **only reads**. It changes a few display/output options
while it runs, puts them back at the end, and **never saves the model and never runs the analysis**.

## What you need

- The laptop with CSiBridge v27.1.
- The AASHTO concrete app folder on that laptop, with its `.venv` folder (it already has `pythonnet`).

## Steps

1. Open CSiBridge and open the bridge model.
2. Run the analysis (or check that it has been run and the results are available).
3. Pick a small test selection:
   - one column frame label (for example `1227`),
   - one support joint label (a joint that has a reaction),
   - one or two load combinations (for example `Str-I1`). Use a combination that includes the moving load, so
     envelope and correspondence give different rows.
   - optional: one small group name.
4. Leave CSiBridge open with the model. Open a Command Prompt (Start menu, type `cmd`, Enter) and go to the
   app folder, for example:

   ```
   cd C:\path\to\AASHTO_Concrete_App
   ```

5. Run (change the labels to your own; add `--case` once per combination; `--group` is optional):

   ```
   .venv\Scripts\python.exe csibridge_extractor\probe\probe_csibridge.py --frames 1227 --joints 15 --case Str-I1 --out probe_out
   ```

   With a group and two combinations:

   ```
   .venv\Scripts\python.exe csibridge_extractor\probe\probe_csibridge.py --frames 1227 --joints 15 --group Pier2 --case Str-I1 --case Serv-I --out probe_out
   ```

   If it says it cannot find `CSiAPIv1.dll`, add the full path to it, for example:
   `--dll "C:\Program Files\Computers and Structures\CSiBridge 27\CSiAPIv1.dll"`

6. Wait until it prints `=== CSiBridge probe summary ===` and the `NEXT:` line. It always writes its result
   file, even when something fails. A failure is still useful information.

## Also export the same tables from CSiBridge (for comparison)

For the **same frame, joint and combination(s)** (menu names below may differ slightly in v27.1; use the Show Tables viewer):

1. Display > Show Tables > Analysis Results > Element Output > Frame Output > **Element Forces - Frames**.
   In the table options set the load combinations to **Envelopes**, then export to Excel and save it into the
   `probe_out` folder as `csi_frame_envelope.xlsx`.
2. Same table, load combinations set to **Correspondence**: save as `csi_frame_correspondence.xlsx`.
3. Joint Output > Reactions > **Joint Reactions**: export with **Envelopes** (`csi_joint_envelope.xlsx`) and
   with **Correspondence** (`csi_joint_correspondence.xlsx`). If Correspondence is not offered for joint
   reactions, write that down.

Filter each table to just the test frame / joint if you can (smaller files are fine).

## What to send back

The whole `probe_out` folder (zip it):
- `probe_result_<date>_<time>.json`
- all `probe_rows_*.csv` files
- the four CSiBridge Excel exports above
- a copy of the text printed in the Command Prompt window (copy/paste into a `.txt` file), and any notes
  (e.g. "Correspondence not available for reactions").

## After running

The probe puts the table display options and the "selected for output" cases back as they were. Check the
`Restored:` line in the summary. If it says `False`, just close the model **without saving**.
