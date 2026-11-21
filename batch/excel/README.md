# Excel batch template

`AASHTO_Batch_Template.xlsm` runs many sections through the app's calculation engine from Excel.
One row on the **Inputs** sheet is one load case; rows that share a **Section ID** are the load cases
of one section, and that section's geometry and bars come from its first row.

## Using it

1. Put `AASHTO_Batch.exe` in the same folder as the workbook. Python is **not** needed.
2. Open the workbook and **enable macros** when Excel asks. If the file came from email or the web, you may
   first need to right-click it, choose Properties, and tick *Unblock*.
3. **Settings** sheet: pick the force unit (kip / lbf) and the length unit (in / ft) first. Every input and
   result uses them, and the units rows on Inputs and Results follow. The other rows are the app's AASHTO
   defaults. Unit-bearing defaults (Es, ag, wc) are left blank on purpose: blank means the app default,
   converted to your units.
4. **Inputs** sheet: fill one row per load case. Dropdowns list the allowed values. Greyed cells do not
   apply to that row's section type and are ignored. Hover over a header to see its default and notes.
5. Press **Run** on the Inputs sheet. The engine writes the **Results** sheet:
   - one row per input row, with full-precision numbers
   - Status OK, NG or ERROR, with the reason in Message
   - a project file (`<workbook name>.aashto.json` unless set in Settings), which you can open in the app
     to review any section

The workbook must be saved in a local folder, or in a OneDrive folder that is synced to disk. Exchange
files (`_batch_inputs.tsv`, `_batch_settings.tsv`, `_batch_results.tsv`, `_batch_progress.txt`,
`_batch_summary.txt`) are written next to it on each run. Numbers are exchanged in a locale-independent
form, so any Windows decimal separator works.

Notes:
- Flexure Mr and its D/C are the row values from the app's demand table, the same as the app shows.
- Moment-curvature values (the SGS preset, and the AdSec-style secant EI) are still pending verification.
  See `OPEN_VERIFICATION_ITEMS.md` items MP1–MP3.

## Building (developers)

1. `build_batch_exe.bat` builds `dist\AASHTO_Batch.exe`. On first run it creates the build Python and venv.
2. `batch\excel\build_template.bat` builds `AASHTO_Batch_Template.xlsm` from `batch/columns.py`. It needs:
   - Excel installed
   - Excel > File > Options > Trust Center > Trust Center Settings > Macro Settings >
     **Trust access to the VBA project object model**, so that `BatchRunner.bas` can be imported.
     The script only checks this setting and never changes it.
   - `--layout-only --out <path>.xlsx` builds the sheets without the macro, which needs no VBA access.

The builder drives Excel through late binding (pywin32 dynamic dispatch, installed into `.build_venv`).
The Office interop-assembly binding that PowerShell uses fails with "Interface not registered" on some
Office installs.

`BatchRunner.bas` finds columns by their header text, so the column order can change. The layout constants
must match `batch/columns.py`; `tests/test_batch_vba_static.py` pins that.
