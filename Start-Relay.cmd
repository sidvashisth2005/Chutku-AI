@echo off
rem The account relay for the phone app, on this laptop (home Wi-Fi). See docs\RELAY.md.
cd /d "%~dp0"
if not exist data mkdir data
".venv\Scripts\python.exe" -m chutku.relay --host 0.0.0.0 --home-network --port 8780 --db data\relay.sqlite3
