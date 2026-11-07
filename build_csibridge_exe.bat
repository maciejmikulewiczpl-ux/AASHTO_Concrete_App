@echo off
setlocal
cd /d "%~dp0"

set "TASKLIST=%SystemRoot%\System32\tasklist.exe"
set "FIND=%SystemRoot%\System32\find.exe"
set "EXE_NAME=CSiBridge_Results_Extractor.exe"

echo ============================================================
echo  CSiBridge Results Extractor  ^|  EXE Builder
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv\Scripts\python.exe not found.
    pause & exit /b 1
)

:: Conda-based venvs keep native DLLs in <base>\Library\bin; let PyInstaller find them.
for /f "delims=" %%P in ('".venv\Scripts\python.exe" -c "import sys;print(sys.base_prefix)"') do set "PY_BASE=%%P"
if exist "%PY_BASE%\Library\bin" set "PATH=%PY_BASE%\Library\bin;%PATH%"

".venv\Scripts\python.exe" -m pip install -q -r csibridge_extractor\requirements.txt pyinstaller
if errorlevel 1 (
    echo ERROR: installing requirements failed.
    pause & exit /b 1
)

"%TASKLIST%" /FI "IMAGENAME eq %EXE_NAME%" 2>nul | "%FIND%" /I "%EXE_NAME%" >nul
if not errorlevel 1 (
    echo ERROR: %EXE_NAME% is currently running. Close it, then re-run.
    pause & exit /b 1
)

echo [1/2] Cleaning previous build...
if exist "dist\%EXE_NAME%" del /f /q "dist\%EXE_NAME%"
if exist "build\csibridge_extractor" rmdir /s /q "build\csibridge_extractor"

echo [2/2] Building single-file executable...
".venv\Scripts\python.exe" -m PyInstaller csibridge_extractor.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed. See output above.
    pause & exit /b 1
)
if not exist "dist\%EXE_NAME%" (
    echo ERROR: dist\%EXE_NAME% was not produced.
    pause & exit /b 1
)

echo.
echo  Build complete: dist\%EXE_NAME%
echo  Users need CSiBridge 27 installed (CSiAPIv1.dll is loaded from it at runtime)
echo  and the Microsoft Edge WebView2 runtime (standard on Windows 10/11).
echo.
pause
