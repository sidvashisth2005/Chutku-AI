@echo off
rem One-time: keep Tailscale connected from boot and send a Telegram "Laptop is ON" notice (Chutku only; it also
rem removes RustDesk if an older setup installed it). Windows asks for admin permission once. See scripts\setup_boot_access.ps1.
powershell -NoProfile -Command "Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0scripts\setup_boot_access.ps1'"
