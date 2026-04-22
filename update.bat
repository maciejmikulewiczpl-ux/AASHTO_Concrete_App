@echo off
setlocal enabledelayedexpansion

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

:: ── Clone or fetch ───────────────────────────────────────────────────────────
if exist ".git" (
    echo [INFO] Repository found. Fetching all branches...
    git fetch --all --prune
    if errorlevel 1 (
        echo [ERROR] git fetch failed.
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
    goto :install_python
)

:: ── Switch to main ────────────────────────────────────────────────────────────
git checkout main
if errorlevel 1 (
    echo [ERROR] Could not switch to branch main.
    pause
    exit /b 1
)

:: Pull latest main first
git pull origin main
if errorlevel 1 (
    echo [ERROR] git pull main failed.
    pause
    exit /b 1
)

:: ── Merge all remote branches into main ──────────────────────────────────────
echo.
echo [INFO] Merging all remote branches into main...

set MERGE_ERRORS=0

for /f "tokens=*" %%b in ('git branch -r --format "%%(refname:short)"') do (
    set BRANCH=%%b

    :: Skip origin/main and origin/HEAD
    if /i "!BRANCH!" neq "origin/main" (
        echo !BRANCH! | findstr /i "HEAD" >nul
        if errorlevel 1 (
            set LOCAL=!BRANCH:origin/=!
            echo.
            echo [INFO] Merging !BRANCH! into main...
            git merge !BRANCH! --no-edit --no-ff -m "Merge !LOCAL! into main [auto]"
            if errorlevel 1 (
                echo [WARN] Merge conflict on !BRANCH! — aborting this merge and skipping.
                git merge --abort >nul 2>&1
                set /a MERGE_ERRORS+=1
            ) else (
                echo [OK]   !BRANCH! merged successfully.
            )
        )
    )
)

:: ── Push merged main to GitHub ────────────────────────────────────────────────
echo.
echo [INFO] Pushing updated main to GitHub...
git push origin main
if errorlevel 1 (
    echo [ERROR] git push failed.
    pause
    exit /b 1
)

if !MERGE_ERRORS! gtr 0 (
    echo.
    echo [WARN] !MERGE_ERRORS! branch(es) had conflicts and were skipped.
)

:install_python
:: ── Python environment ────────────────────────────────────────────────────────
echo.
echo [INFO] Updating Python environment...

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

if exist "requirements.txt" (
    echo [INFO] Installing requirements...
    .venv\Scripts\pip install -r requirements.txt --quiet
)

echo.
echo ============================================
echo  Done! App is up to date.
echo  Double-click run.bat to start the application.
echo ============================================
echo.
pause
