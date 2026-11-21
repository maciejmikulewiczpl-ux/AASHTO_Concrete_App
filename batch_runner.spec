# -*- mode: python ; coding: utf-8 -*-
# ============================================================
#  PyInstaller spec — AASHTO Batch runner (ONE-FILE BUILD)
#
#  Produces dist\AASHTO_Batch.exe, the engine the Excel batch
#  template's Run button calls. No GUI, no pywebview: only the
#  calculation engine + the batch package.
#  Built by build_batch_exe.bat with the same clean CPython as
#  the app (python-build-standalone).
# ============================================================
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = [
    'calc_engine',
    'circ_engine',
    'mphi_engine',
    'pt_engine',
]
hiddenimports += collect_submodules('batch')
hiddenimports += collect_submodules('seismic_port')

a = Analysis(
    ['batch_runner.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['webview', 'clr', 'pythonnet', 'tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AASHTO_Batch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # never compress — UPX flags antivirus + bloats startup
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,        # called hidden by the Excel macro; results go to files
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
