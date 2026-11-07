@echo off
rem One-time: reach the laptop from the phone right after boot (Tailscale unattended, RustDesk for the login
rem screen, a Telegram "Laptop is ON" notice). Windows asks for admin permission once. See scripts\setup_boot_access.ps1.
powershell -NoProfile -Command "Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0scripts\setup_boot_access.ps1'"
