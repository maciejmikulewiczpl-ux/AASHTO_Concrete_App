@echo off
setlocal
cd /d "%~dp0"

:: Builds dist\AASHTO_Batch.exe — the engine behind the Excel batch template.
:: Uses the same clean CPython + build venv as build_exe.bat (created on first run).
:: Optional argument "nopause" skips the final pause (for scripted builds).

set "TAR=%SystemRoot%\System32\tar.exe"
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

echo ============================================================
echo  AASHTO Batch runner  ^|  EXE Builder
echo ============================================================
echo.

set "PY_VERSION=3.12.7"
set "PY_BUILD=20241016"
set "PY_FILE=cpython-%PY_VERSION%+%PY_BUILD%-x86_64-pc-windows-msvc-install_only.tar.gz"
set "PY_URL=https://github.com/astral-sh/python-build-standalone/releases/download/%PY_BUILD%/%PY_FILE%"
set "BUILD_PY_DIR=%~dp0.build_python"
set "BUILD_PY=%BUILD_PY_DIR%\python\python.exe"
set "BUILD_VENV=%~dp0.build_venv"
set "PY_TGZ=%~dp0_py_dl.tar.gz"

:: ── 1. Standalone CPython ──────────────────────────────────
if exist "%BUILD_PY%" goto :py_done
echo [1/4] Downloading clean CPython %PY_VERSION% ^(~40 MB^)...
"%POWERSHELL%" -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_TGZ%' -UseBasicParsing" >nul
if errorlevel 1 ( echo ERROR: Download failed. & goto :fail )
if not exist "%BUILD_PY_DIR%" mkdir "%BUILD_PY_DIR%"
"%TAR%" -xzf "%PY_TGZ%" -C "%BUILD_PY_DIR%"
if errorlevel 1 ( echo ERROR: Could not extract Python archive. & goto :fail )
del "%PY_TGZ%"
:py_done
echo [1/4] Build Python OK

:: ── 2. Build venv ──────────────────────────────────────────
if not exist "%BUILD_VENV%\Scripts\python.exe" (
    "%BUILD_PY%" -m venv "%BUILD_VENV%"
    if errorlevel 1 ( echo ERROR: venv creation failed. & goto :fail )
)
echo [2/4] Build venv OK

:: ── 3. PyInstaller (pinned, as requirements.txt) ───────────
"%BUILD_VENV%\Scripts\python.exe" -m pip install --quiet pyinstaller==6.20.0
if errorlevel 1 ( echo ERROR: pip install failed. & goto :fail )
echo [3/4] PyInstaller OK

:: ── 4. Build ───────────────────────────────────────────────
if exist "dist\AASHTO_Batch.exe" del /f /q "dist\AASHTO_Batch.exe"
if exist "build\batch_runner"   rmdir /s /q "build\batch_runner"
"%BUILD_VENV%\Scripts\python.exe" -m PyInstaller batch_runner.spec --clean --noconfirm
if errorlevel 1 ( echo ERROR: PyInstaller build failed. & goto :fail )
if not exist "dist\AASHTO_Batch.exe" ( echo ERROR: dist\AASHTO_Batch.exe was not produced. & goto :fail )

echo.
echo ============================================================
echo  Build complete: dist\AASHTO_Batch.exe
echo  Put it next to the batch workbook (AASHTO_Batch_Template.xlsm).
echo ============================================================
if /i not "%~1"=="nopause" pause
exit /b 0

:fail
if /i not "%~1"=="nopause" pause
exit /b 1
