@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m chutku.cli open
if errorlevel 1 pause
