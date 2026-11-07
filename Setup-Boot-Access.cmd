@echo off
rem One-time: keep Tailscale connected from boot, install the lock-screen helper (sign in from the phone) and send a
rem Telegram "Laptop is ON" message with its link at every boot. Windows asks for admin permission once.
rem See scripts\setup_boot_access.ps1.
powershell -NoProfile -Command "Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0scripts\setup_boot_access.ps1'"
