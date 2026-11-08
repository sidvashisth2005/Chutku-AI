<#
.SYNOPSIS
    Undo setup_boot_access.ps1 (run as administrator; the Phone tab's "Turn off" runs it with one Windows prompt):
    removes the lock-screen helper and the "Laptop is ON" startup tasks, the C:\ProgramData\ChutkuBoot folder (the
    sealed bot token with it) and the tailnet-only 8443 address. Tailscale itself, its unattended mode and the phone
    remote are left as they are. Fast Startup stays off; the end of this script says how to turn it back on.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\remove_boot_access.ps1
#>
param([switch]$Quiet)
$ErrorActionPreference = "Stop"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Write-Host "Run this as administrator." -ForegroundColor Red; Read-Host "Press Enter to close"; exit 1 }

foreach ($name in "ChutkuUnlock", "ChutkuBootNotice") {
    try { Stop-ScheduledTask -TaskName $name -ErrorAction Stop } catch { }
    try { Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction Stop; Write-Host "Removed task $name" }
    catch { Write-Host "Task $name was not there" }
}
Get-Process ChutkuUnlock -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
$tailscale = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"
if (Test-Path $tailscale) {   # try: Windows PowerShell 5.1 turns a native command's stderr into a stopping error
    try { & $tailscale serve --https=8443 off 2>$null } catch { }
    Write-Host "Tailnet address :8443 turned off"
}
$boot = Join-Path $env:ProgramData "ChutkuBoot"
if (Test-Path -LiteralPath $boot) {   # rmdir /s deletes junctions without following them (review 2026-11-08)
    cmd /c "rmdir /s /q `"$boot`""
    Write-Host "Removed $boot"
}
Write-Host "`nDone: the laptop no longer sends 'Laptop is ON' and the lock screen is not reachable from the phone." -ForegroundColor Green
Write-Host "Fast Startup is still off. To turn it back on: Control Panel > Power Options > 'Choose what the power buttons do'."
if ($Quiet) { Start-Sleep -Seconds 6 } else { Read-Host "Press Enter to close" }
