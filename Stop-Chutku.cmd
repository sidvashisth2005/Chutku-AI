@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m chutku.cli control stop
) else (
  py -3 -m chutku.cli control stop
)
