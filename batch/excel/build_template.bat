@echo off
setlocal
cd /d "%~dp0..\.."

:: Builds AASHTO_Batch_Template.xlsm from batch\columns.py (needs Excel).
:: Uses the build venv made by build_batch_exe.bat; installs pywin32 into it (dev-only).
:: Excel must allow "Trust access to the VBA project object model" (this script never changes it).
:: Extra arguments are passed on, e.g.  build_template.bat --layout-only --out C:\temp\check.xlsx

set "VENV_PY=%CD%\.build_venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo Build venv not found. Run build_batch_exe.bat once first.
    exit /b 1
)
"%VENV_PY%" -m pip install --quiet pywin32==308
if errorlevel 1 ( echo ERROR: pip install pywin32 failed. & exit /b 1 )
"%VENV_PY%" batch\excel\build_template.py %*
exit /b %errorlevel%
