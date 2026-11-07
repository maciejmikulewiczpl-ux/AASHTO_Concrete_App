# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — CSiBridge Results Extractor (single-file build).
#
# Entry point: csibridge_extractor/app.py (pywebview window)
# CSiAPIv1.dll is NOT bundled; it is loaded from the user's CSiBridge install at runtime.
#
# console=True on purpose: under a windowless interpreter (pythonw) the CSiBridge API attach
# finds no instance. app.hide_own_console() hides the console on a double-click launch.

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [('csibridge_extractor/ui/index.html', 'ui')]
binaries, hiddenimports = [], []

for pkg in ('webview', 'clr_loader', 'pythonnet'):
    _d, _b, _h = collect_all(pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

hiddenimports += collect_submodules('csibridge_extractor')
hiddenimports += ['clr', 'xlsxwriter', 'webview.platforms.winforms', 'bottle', 'proxy_tools']

a = Analysis(
    ['csibridge_extractor/app.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'tkinter', 'numpy', 'pandas', 'matplotlib'],
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
    name='CSiBridge_Results_Extractor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
