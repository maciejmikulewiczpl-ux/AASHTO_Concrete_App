# GSA Force Extractor — Development Summary

*Last updated: 2026-05-15*

## What it is

A standalone tool (fully decoupled from the AASHTO concrete app) that extracts
enveloped element forces from an Oasys GSA model and emits a paste-friendly
demand table compatible with the concrete app.

## Files

| File | Purpose |
|---|---|
| `gsa_force_extractor.py` | Extraction engine — config parsing, unit/sign conversion, envelope logic, two GSA backends (`GsaAdapter` for gsapy COM, `GsaApiAdapter` for GsaAPI .NET) |
| `gsa_extractor_gui.py` | Tkinter GUI — 3 tabs (Setup, Jobs, Run & Results), Canvas-based BatchDialog for results, BatchProgressDialog with per-permutation progress + ETA |
| `tests/test_gsa_force_extractor.py` | 46 tests using `MockGsaModel` (no GSA installation needed) |
| `gsa_extractor_config.example.json` | Example config file |
| `GSA Force Extractor.bat` | Launcher (uses `pythonw.exe`) |

## Architecture

### Two GSA backends

1. **`GsaAdapter`** (gsapy / COM) — the original backend. Makes one COM
   round-trip per (element, permutation) via `get_1D_elem_resultants`. Slow
   (~50–100 ms per call). Returns values in the model's **display units**.

2. **`GsaApiAdapter`** (GsaAPI / .NET via pythonnet) — added 2026-05-15.
   Uses `CombinationCaseResult.Element1dForce()` to batch-fetch ALL elements ×
   ALL permutations in a **single API call**. Dramatically faster.
   Returns values in **SI base units (N, N·m)** regardless of display settings.

The factory function `open_gsa_model(path)` tries GsaApiAdapter first and
falls back to GsaAdapter automatically.

### Critical unit difference between backends

| Backend | Forces returned in | Moments returned in |
|---|---|---|
| gsapy (COM) | Model display units (e.g. kip) | Model display units (e.g. kip·in) |
| GsaAPI (.NET) | **Always N** | **Always N·m** |

`GsaAdapter.discover_units()` reads the model's display units.
`GsaApiAdapter.discover_units()` always returns `("N", "N.m")`.
The conversion pipeline in `gsa_perm_to_app_row()` then correctly converts
from source units to the user's chosen output units.

### GsaApiAdapter batch flow

```
run_job()
  └─ adapter.prefetch(combo, elements)     ← ONE GsaAPI call
       └─ ccr.Element1dForce("9071 9075 9083", 5, None)
            → Dict[elem_id → list[perm → list[position → Double6]]]
            → cached in _combo_cache
  └─ _candidates_for_target()
       └─ adapter.list_permutations()      ← from cache
       └─ adapter.elem_forces_all_positions() ← from cache (zero latency)
```

### GsaAPI .NET details (GSA 10.2)

- DLL: `C:\Program Files\Oasys\GSA 10.2\GsaAPI.dll`
- Loaded via `pythonnet` (`import clr; clr.AddReference(...)`)
- `Model(path)` constructor opens the file
- `Double6` fields: `X`=Fx, `Y`=Fy, `Z`=Fz, `XX`=Mxx, `YY`=Myy, `ZZ`=Mzz
- `Element1dForce(elem_list_str, n_positions_int, axis_nullable_int)`:
  - `n_positions` = total number of equally-spaced sample points (not addl_pts)
  - `axis=None` = local element axes (same as `axis=-1`)
  - `axis=0` → errors with "not available in the specified axis"
- Permutations: outer `ReadOnlyCollection` in the result; indexed 0-based
- Perm naming convention: `C1p1`, `C1p2`, … (1-based, matching gsapy)

### GUI highlights

- **BatchProgressDialog**: per-permutation progress bar, elapsed time + ETA,
  cancel button. Updates every 5 perms to avoid Tk overhead.
- **BatchDialog** (results table): Canvas-based (not Label widgets — hundreds
  of Labels was too slow). Click-drag rectangular cell selection, Ctrl+C copy,
  "Copy all" button. Column widths auto-sized via `tkfont.measure()`.

## Dependencies

- **gsapy** (COM): `pip install https://packages.arup.com/gsapy.tar.gz`
  — fallback backend, works without GSA 10.x
- **pythonnet** 3.0.5: `pip install pythonnet` — required for GsaApiAdapter
- **Oasys GSA 10.x**: must be installed for the GsaAPI DLL
- No dependency on the AASHTO concrete app (`calc_engine`, `api`, `app`)

## What's NOT done / known limitations

- `debug_gsaapi.py` is a diagnostic script used during development; can be
  deleted or kept for future debugging.
- The GsaApiAdapter has only been verified on one model. If a model returns
  results in units other than SI base, the hardcoded `("N", "N.m")` in
  `discover_units()` would need revisiting. (All evidence so far confirms
  GsaAPI 10.x always returns SI.)
- `elements_in_group()` on GsaApiAdapter searches `model.Lists()` by name;
  if no list matches, it raises an error. The gsapy adapter's `get_elements(name)`
  may handle more flexible name resolution.
- No automated test covers the GsaApiAdapter against a real GSA model (the
  test suite uses MockGsaModel which only exercises GsaAdapter's interface).
  Adding a test that compares both backends on a sample `.gwb` would be ideal.
- The `.vscode/settings.json` sets the Python interpreter to the local venv.

## Test commands

```bash
# Fast test suite (no GSA needed)
pytest tests/test_gsa_force_extractor.py -v

# Full app test suite (unrelated to GSA extractor)
python run_test_suite.py --full
```
