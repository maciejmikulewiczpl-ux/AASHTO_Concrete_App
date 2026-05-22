@echo off
setlocal
cd /d "%~dp0"

set "TASKLIST=%SystemRoot%\System32\tasklist.exe"
set "FIND=%SystemRoot%\System32\find.exe"

echo ============================================================
echo  GSA Force Extractor  ^|  EXE Builder
echo ============================================================
echo.
echo  Builds a standalone .exe (single file, no console).
echo  Uses the project's existing .venv.
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv\Scripts\python.exe not found.
    echo Create the venv first (see project setup), then re-run.
    pause & exit /b 1
)

:: If the venv's parent Python is a conda install, its native DLLs
:: (tcl86t.dll, tk86t.dll, sqlite3.dll, etc.) live in <base>\Library\bin
:: rather than next to python.exe. PyInstaller can't find them via PATH
:: by default, so we prepend that folder here. Harmless if not conda.
for /f "delims=" %%P in ('".venv\Scripts\python.exe" -c "import sys;print(sys.base_prefix)"') do set "PY_BASE=%%P"
if exist "%PY_BASE%\Library\bin" (
    echo Using conda native DLL dir: %PY_BASE%\Library\bin
    set "PATH=%PY_BASE%\Library\bin;%PATH%"
)

:: Refuse to overwrite a running exe.
"%TASKLIST%" /FI "IMAGENAME eq GSA_Force_Extractor.exe" 2>nul | "%FIND%" /I "GSA_Force_Extractor.exe" >nul
if not errorlevel 1 (
    echo ERROR: GSA_Force_Extractor.exe is currently running.
    echo Close it, then re-run this script.
    pause & exit /b 1
)

echo [1/2] Cleaning previous build...
if exist "dist\GSA_Force_Extractor"     rmdir /s /q "dist\GSA_Force_Extractor"
if exist "dist\GSA_Force_Extractor.exe" del /f /q  "dist\GSA_Force_Extractor.exe"
if exist "build\GSA_Force_Extractor"    rmdir /s /q "build\GSA_Force_Extractor"

echo [2/2] Building single-file executable...
".venv\Scripts\python.exe" -m PyInstaller gsa_extractor.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed. See output above.
    pause & exit /b 1
)

if not exist "dist\GSA_Force_Extractor.exe" (
    echo ERROR: Build finished but dist\GSA_Force_Extractor.exe was not produced.
    pause & exit /b 1
)

echo.
echo ============================================================
echo  Build complete.
echo.
echo  Output : dist\GSA_Force_Extractor.exe
echo.
echo  Users need Oasys GSA 10.x installed for the .NET backend
echo  (GsaAPI.dll is loaded from their GSA install at runtime).
echo  The gsapy COM backend also requires GSA installed locally.
echo ============================================================
echo.
pause
