# -*- mode: python ; coding: utf-8 -*-
# ============================================================
#  PyInstaller spec — AASHTO Concrete App  (ONE-FILE BUILD)
#
#  Produces a single self-contained AASHTO_Concrete_App.exe.
#  At runtime, the bootloader extracts everything to a temp
#  folder, runs the app, and cleans up on exit.
#
#  Designed to be built with a CLEAN, standard CPython
#  (downloaded from python-build-standalone by build_exe.bat).
#  Conda-specific DLLs are NOT bundled — they aren't needed.
# ============================================================
from PyInstaller.utils.hooks import collect_all, collect_submodules

# --- pywebview (the import name is `webview`) ---
_d, _b, _h = collect_all('webview')
datas, binaries, hiddenimports = _d, _b, _h

# --- clr_loader (Python <-> .NET native bridge, includes ClrLoader.dll) ---
_d, _b, _h = collect_all('clr_loader')
datas += _d
binaries += _b
hiddenimports += _h

# --- pythonnet (includes Python.Runtime.dll, the .NET assembly) ---
_d, _b, _h = collect_all('pythonnet')
datas += _d
binaries += _b
hiddenimports += _h

# --- Application source files ---
datas += [
    ('index.html',           '.'),
    ('api.py',               '.'),
    ('calc_engine.py',       '.'),
    ('pt_engine.py',         '.'),
    ('deep_audit.py',        '.'),
    ('full_verification.py', '.'),
]

# --- Hidden imports for pywebview's Windows backend ---
hiddenimports += collect_submodules('clr_loader')
hiddenimports += collect_submodules('pythonnet')
hiddenimports += [
    'clr',
    'webview.platforms.winforms',
]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,           # bundled into the single exe
    a.datas,              # bundled into the single exe
    [],
    name='AASHTO_Concrete_App',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # never compress — UPX flags antivirus + bloats startup
    upx_exclude=[],
    runtime_tmpdir=None,  # use system temp (cleaned up on exit)
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
# No COLLECT step — one-file build packs everything into the EXE.
