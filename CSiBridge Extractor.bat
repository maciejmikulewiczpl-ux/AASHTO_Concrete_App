@echo off
REM Double-click launcher for the CSiBridge Results Extractor window.
REM Must be python.exe, not pythonw.exe: under pythonw the CSiBridge API attach finds no instance.
REM The app hides its own console window once it starts.

start "" /min "%~dp0.venv\Scripts\python.exe" "%~dp0csibridge_extractor\app.py" %*
