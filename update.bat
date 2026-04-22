@echo off
setlocal

set REPO_URL=https://github.com/LukaszTetiorka/Maciej_Cocnrete_App.git

:: Move to the folder where this script lives
cd /d "%~dp0"

echo ============================================
echo  Concrete App - Update from GitHub
echo ============================================
echo.

:: Check if git is installed
git --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git is not installed or not in PATH.
    echo Download Git from: https://git-scm.com/download/win
    echo.
    pause
    exit /b 1
)

:: If .git folder exists -> pull, otherwise clone into current folder
if exist ".git" (
    echo [INFO] Repository found. Pulling latest changes...
    git pull
    if errorlevel 1 (
        echo [ERROR] git pull failed.
        pause
        exit /b 1
    )
) else (
    echo [INFO] No repository found. Cloning into current folder...
    git clone %REPO_URL% .
    if errorlevel 1 (
        echo [ERROR] git clone failed.
        pause
        exit /b 1
    )
)

echo.
echo [INFO] Updating Python environment...

:: Create venv if it doesn't exist
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create virtual environment.
        echo Make sure Python 3 is installed: https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

:: Install / update requirements
if exist "requirements.txt" (
    echo [INFO] Installing requirements...
    .venv\Scripts\pip install -r requirements.txt --quiet
)

echo.
echo ============================================
echo  Done! App is up to date.
echo  Run app.py to start the application.
echo ============================================
echo.
pause
