<#
.SYNOPSIS
    One-time setup (run as administrator, owner 2026-11-07): reach the laptop from the phone right after it boots.
      1. Tailscale unattended: the laptop joins your tailnet at boot, before anyone signs in.
      2. RustDesk is removed if an earlier version of this setup installed it (owner 2026-11-07: Chutku only).
      3. A startup task (LOCAL SERVICE) sends "Laptop is on" with the unlock steps to your paired Telegram chat.
    Chutku itself never runs elevated: after you sign in it starts as before.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup_boot_access.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nStopped: $text" -ForegroundColor Red; Read-Host "Press Enter to close"; exit 1 }
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Fail "run this as administrator (it asks Windows once)." }

# --- 0. what the boot notice needs from Chutku (the paired chat, the token) --------------------------------------
# An elevated window starts in C:\Windows\System32: run Chutku's Python from its own folder (PC check 2026-11-07).
Set-Location $root
$env:PYTHONPATH = $root
$python = Join-Path $root ".venv\Scripts\python.exe"
$raw = & $python -c "import json; from chutku.app import PROJECT_ROOT; from chutku.gateway import telegram as tg; print(json.dumps({'token': tg.token() or '', 'chat': tg.paired(PROJECT_ROOT)}))"
if ($LASTEXITCODE -ne 0 -or -not $raw) { Fail "could not read Chutku's Telegram settings (see the error above)." }
$info = $raw | ConvertFrom-Json
if (-not $info.token) { Fail "no Telegram bot token yet: run chutku.cli telegram set-token first." }
if (-not $info.chat) { Fail "the bot is not paired yet: send /pair CODE to your bot (chutku.cli telegram pair) first." }

# --- 1. Tailscale unattended ------------------------------------------------------------------------------------
Step "Tailscale: stay connected at boot (unattended)"
$tailscale = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"
if (-not (Test-Path $tailscale)) { Fail "Tailscale is not installed." }
& $tailscale set --unattended=true
$ip = (& $tailscale ip -4 | Select-Object -First 1).Trim()
$dns = ((& $tailscale status --json | ConvertFrom-Json).Self.DNSName).TrimEnd(".")
Write-Host "Laptop on Tailscale: $ip ($dns)"

# --- 2. RustDesk removed (owner 2026-11-07: no other remote-desktop software; Chutku only) -----------------------
Step "Removing RustDesk (no longer used)"
$entries = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*", `
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like "RustDesk*" }
foreach ($entry in $entries) {
    if ($entry.PSChildName -match "^\{[0-9A-Fa-f-]+\}$") {
        Start-Process msiexec.exe -ArgumentList "/x", $entry.PSChildName, "/qn", "/norestart" -Wait
    } elseif ($entry.UninstallString) {
        Start-Process cmd.exe -ArgumentList "/c", "`"$($entry.UninstallString)`" --silent-uninstall" -Wait
    }
}
Stop-Service RustDesk -ErrorAction SilentlyContinue
if (Get-Service RustDesk -ErrorAction SilentlyContinue) { Write-Host "RustDesk's service is still there: remove it in Settings > Apps." -ForegroundColor Yellow }
else { Write-Host "RustDesk is not installed." }

# --- 3. the boot notice -----------------------------------------------------------------------------------------
Step "Telegram: 'Laptop is on' at every boot"
$boot = Join-Path $env:ProgramData "ChutkuBoot"
New-Item -ItemType Directory -Force $boot | Out-Null
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)   # only these: administrators and SYSTEM change it, LOCAL SERVICE reads
foreach ($who in "BUILTIN\Administrators", "NT AUTHORITY\SYSTEM") {
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($who, "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")))
}
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule("NT AUTHORITY\LOCAL SERVICE", "ReadAndExecute", "ContainerInherit,ObjectInherit", "None", "Allow")))
Set-Acl $boot $acl
Copy-Item (Join-Path $PSScriptRoot "boot_access\notify.ps1") (Join-Path $boot "notify.ps1") -Force
Add-Type -AssemblyName System.Security
$sealed = [Security.Cryptography.ProtectedData]::Protect([Text.Encoding]::UTF8.GetBytes($info.token), $null, "LocalMachine")
[IO.File]::WriteAllBytes((Join-Path $boot "token.bin"), $sealed)
@{ chat_id = $info.chat; ip = $ip; phone_url = "https://$dns/" } | ConvertTo-Json | Set-Content (Join-Path $boot "config.json") -Encoding UTF8
$action = New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe") `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$boot\notify.ps1`""
$principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\LOCAL SERVICE" -LogonType ServiceAccount
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "ChutkuBootNotice" -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) `
    -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "ChutkuBootNotice"
Write-Host "`nDone. A test 'Laptop is ON' message is on its way to your Telegram." -ForegroundColor Green
Write-Host "After a restart, sign in at the laptop once; Chutku then sends the phone link on Telegram."
Read-Host "Press Enter to close"
