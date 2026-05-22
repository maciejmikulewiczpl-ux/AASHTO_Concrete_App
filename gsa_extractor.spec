# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — GSA Force Extractor (single-file build).
#
# Entry point: gsa_extractor_gui.py (Tkinter)
# Engine:      gsa_force_extractor.py
#
# Runtime backends loaded lazily by the engine:
#   - gsapy (COM)         — bundled
#   - clr / pythonnet     — bundled (for GsaAPI .NET adapter)
#   - GsaAPI.dll          — NOT bundled; loaded from the user's installed
#                            Oasys GSA at runtime via clr.AddReference.

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

for pkg in ('gsapy', 'clr_loader', 'pythonnet'):
    _d, _b, _h = collect_all(pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

hiddenimports += collect_submodules('clr_loader')
hiddenimports += collect_submodules('pythonnet')
hiddenimports += [
    'clr',
    'gsa_force_extractor',
]

a = Analysis(
    ['gsa_extractor_gui.py'],
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
    a.binaries,
    a.datas,
    [],
    name='GSA_Force_Extractor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
