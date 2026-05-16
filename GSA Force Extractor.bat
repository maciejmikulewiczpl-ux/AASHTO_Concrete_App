@echo off
REM Double-click launcher for gsa_extractor_gui.py.
REM Uses the project's venv Python (pythonw.exe = no console window).
REM
REM If the GUI does NOT appear when you double-click, swap `pythonw.exe`
REM for `python.exe` and add a `pause` line at the end so you can see the
REM error message in the console window before it closes.

start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0gsa_extractor_gui.py" %*
