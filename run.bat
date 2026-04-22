@echo off
setlocal

:: Move to the folder where this script lives
cd /d "%~dp0"

echo ============================================
echo  Concrete App - Launcher
echo ============================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Download Python 3 from: https://www.python.org/downloads/
    echo Make sure to tick "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

:: Create venv if it doesn't exist
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Virtual environment not found. Creating .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create virtual environment.
        pause
        exit /b 1
    )
)

:: Install / update requirements (errors still shown; normal output suppressed)
if exist "requirements.txt" (
    echo [INFO] Ensuring Python packages are installed...
    .venv\Scripts\pip install -r requirements.txt -qq
    if errorlevel 1 (
        echo [ERROR] Failed to install requirements.
        pause
        exit /b 1
    )
)

:: Verify the app entry point exists before launching
if not exist "app.py" (
    echo [ERROR] app.py was not found in this folder:
    echo   %CD%
    echo Make sure run.bat is located inside the repository folder
    echo (run update.bat first if you have not cloned the repo yet).
    pause
    exit /b 1
)

:: Launch the app using the venv's Python (which has pywebview installed)
echo [INFO] Starting AASHTO LRFD - Concrete Section Design...
echo.
.venv\Scripts\python.exe app.py
if errorlevel 1 (
    echo.
    echo [ERROR] The app exited with an error. See the message above.
    pause
    exit /b 1
)

endlocal
