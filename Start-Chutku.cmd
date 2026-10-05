@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m chutku.guard --open
) else (
  py -3 -m chutku.guard --open
)
if errorlevel 1 pause
