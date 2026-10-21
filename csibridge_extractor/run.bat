@echo off
rem Start the CSiBridge Results Extractor. Extra arguments go to app.py, e.g.
rem   run.bat --fake tests\fixtures\fake_model.json
cd /d "%~dp0"
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo Could not create .venv. Is Python 3.12 installed and on PATH?
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo Installing requirements failed.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" app.py %*
if errorlevel 1 pause
