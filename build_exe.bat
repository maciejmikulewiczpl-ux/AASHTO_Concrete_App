@echo off
setlocal
cd /d "%~dp0"

:: Use absolute paths for Windows tools so the script works even when
:: invoked from environments with a non-standard PATH (e.g. Git Bash).
set "TASKLIST=%SystemRoot%\System32\tasklist.exe"
set "FIND=%SystemRoot%\System32\find.exe"
set "TAR=%SystemRoot%\System32\tar.exe"
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

echo ============================================================
echo  AASHTO Concrete App  ^|  EXE Builder
echo ============================================================
echo.
echo  Builds a standalone .exe that runs on any Windows 10/11 PC
echo  with NO Python or conda required by the user.
echo.

:: ── 0. Make sure the app is not currently running ────────────
"%TASKLIST%" /FI "IMAGENAME eq AASHTO_Concrete_App.exe" 2>nul | "%FIND%" /I "AASHTO_Concrete_App.exe" >nul
if not errorlevel 1 (
    echo ERROR: AASHTO_Concrete_App.exe is currently running.
    echo Close the app, then run this script again.
    echo.
    pause & exit /b 1
)

:: ============================================================
::  Configurable: CPython version (must match a published
::  python-build-standalone release).
:: ============================================================
set "PY_VERSION=3.12.7"
set "PY_BUILD=20241016"
set "PY_FILE=cpython-%PY_VERSION%+%PY_BUILD%-x86_64-pc-windows-msvc-install_only.tar.gz"
set "PY_URL=https://github.com/astral-sh/python-build-standalone/releases/download/%PY_BUILD%/%PY_FILE%"

set "BUILD_PY_DIR=%~dp0.build_python"
set "BUILD_PY=%BUILD_PY_DIR%\python\python.exe"
set "BUILD_VENV=%~dp0.build_venv"
set "PY_TGZ=%~dp0_py_dl.tar.gz"

:: ── 1. Download standalone CPython if missing ────────────────
if exist "%BUILD_PY%" (
    echo [1/5] Build Python OK  ^(.build_python\python\python.exe^)
    goto :py_done
)

echo [1/5] First-run setup: downloading clean CPython %PY_VERSION% ^(~40 MB^)...
"%POWERSHELL%" -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_TGZ%' -UseBasicParsing" >nul
if errorlevel 1 (
    echo ERROR: Download failed. Check internet/proxy and try again.
    pause & exit /b 1
)
if not exist "%PY_TGZ%" (
    echo ERROR: Download did not produce %PY_TGZ%
    pause & exit /b 1
)
echo Extracting...
if not exist "%BUILD_PY_DIR%" mkdir "%BUILD_PY_DIR%"
"%TAR%" -xzf "%PY_TGZ%" -C "%BUILD_PY_DIR%"
if errorlevel 1 (
    echo ERROR: Could not extract Python archive.
    pause & exit /b 1
)
del "%PY_TGZ%"
if not exist "%BUILD_PY%" (
    echo ERROR: Python extraction left no python.exe at expected path.
    pause & exit /b 1
)
:py_done

:: ── 2. Create the build venv if missing ──────────────────────
if not exist "%BUILD_VENV%\Scripts\python.exe" (
    echo [2/5] Creating clean build venv...
    "%BUILD_PY%" -m venv "%BUILD_VENV%"
    if errorlevel 1 (
        echo ERROR: venv creation failed.
        pause & exit /b 1
    )
) else (
    echo [2/5] Build venv OK  ^(.build_venv\^)
)

:: ── 3. Install pinned dependencies ──────────────────────────
echo [3/5] Installing pinned dependencies...
"%BUILD_VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%BUILD_VENV%\Scripts\python.exe" -m pip install pywebview==4.0 pythonnet==3.0.5 pyinstaller==6.20.0
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause & exit /b 1
)

:: ── 4. Build with PyInstaller (one-file mode) ────────────────
echo [4/4] Building single-file executable...
if exist "dist\AASHTO_Concrete_App"     rmdir /s /q "dist\AASHTO_Concrete_App"
if exist "dist\AASHTO_Concrete_App.exe" del /f /q  "dist\AASHTO_Concrete_App.exe"
if exist "build\AASHTO_Concrete_App"    rmdir /s /q "build\AASHTO_Concrete_App"

"%BUILD_VENV%\Scripts\python.exe" -m PyInstaller AASHTO_Concrete_App.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed. See output above.
    pause & exit /b 1
)

if not exist "dist\AASHTO_Concrete_App.exe" (
    echo ERROR: Build finished but dist\AASHTO_Concrete_App.exe was not produced.
    pause & exit /b 1
)

echo.
echo ============================================================
echo  Build complete.
echo.
echo  Output : dist\AASHTO_Concrete_App.exe   (single file)
echo.
echo  Send this single .exe to users. They double-click it.
echo  No Python, no folder, no install — just one file.
echo  Only Edge WebView2 is needed (pre-installed on Win10/11).
echo ============================================================
echo.
pause
