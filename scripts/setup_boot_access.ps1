<#
.SYNOPSIS
    One-time setup (run as administrator, owner 2026-11-07): reach the laptop from the phone right after it boots.
    The Phone tab's "Reach this laptop after a restart" runs it (one Windows prompt); so does Setup-Boot-Access.cmd.
    It works in the owner's checkout (scripts\) and in an installed app (boot_access\). Your Windows account must be an
    administrator: the setup reads your own Chutku's Telegram settings. remove_boot_access.ps1 undoes it.
      1. Tailscale unattended: the laptop joins your tailnet at boot, before anyone signs in.
      2. The lock-screen helper (boot_access\ChutkuUnlock.cs, owner 2026-11-07): a SYSTEM startup task shows the
         Windows sign-in screen on your phone (https://<laptop>:8443, tailnet only) so you can tap, type the password
         and press Enter. It works only while the sign-in/lock screen is up; never on your desktop or a UAC prompt.
         Fast Startup is turned off so that switching the laptop on is a real boot (startup tasks run).
      3. A startup task (LOCAL SERVICE) sends "Laptop is ON" with that link to your paired Telegram chat.
    Chutku itself never runs elevated: after you sign in it starts as before.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup_boot_access.ps1
#>
param([switch]$Quiet)   # -Quiet: started from the dashboard; a success closes by itself (a failure still waits)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
# the helper's files: scripts\boot_access\ in a checkout, next to this script in an installed app's boot_access\
$helpers = if (Test-Path (Join-Path $PSScriptRoot "boot_access")) { Join-Path $PSScriptRoot "boot_access" } else { $PSScriptRoot }
function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nStopped: $text" -ForegroundColor Red; Read-Host "Press Enter to close"; exit 1 }
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Fail "run this as administrator (it asks Windows once)." }

# --- 0. what the boot notice needs from Chutku (the paired chat, the token) --------------------------------------
# An elevated window starts in C:\Windows\System32: run Chutku's Python from its own folder (PC check 2026-11-07).
Set-Location $root
$env:PYTHONPATH = $root
$python = Join-Path $root ".venv\Scripts\python.exe"                     # a checkout
if (-not (Test-Path $python)) { $python = Join-Path $root "python\python.exe" }   # an installed app
$raw = & $python -c "import json; from chutku.app import PROJECT_ROOT; from chutku.gateway import telegram as tg; print(json.dumps({'token': tg.token() or '', 'chat': tg.paired(PROJECT_ROOT)}))"
if ($LASTEXITCODE -ne 0 -or -not $raw) { Fail "could not read Chutku's Telegram settings (see the error above)." }
$info = $raw | ConvertFrom-Json
if (-not $info.token) { Fail "no Telegram bot yet: connect it in Chutku's Phone tab (Telegram card) first. (If the prompt signed in as a different administrator, run this from that account.)" }
if (-not $info.chat) { Fail "the bot is not paired yet: press 'Pair my phone' in Chutku's Phone tab (Telegram card) first." }

# --- 1. Tailscale unattended ------------------------------------------------------------------------------------
Step "Tailscale: stay connected at boot (unattended)"
$tailscale = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"
if (-not (Test-Path $tailscale)) { Fail "Tailscale is not installed." }
& $tailscale set --unattended=true
$ip = (& $tailscale ip -4 | Select-Object -First 1).Trim()
$ts = & $tailscale status --json | ConvertFrom-Json
$dns = $ts.Self.DNSName.TrimEnd(".")
$login = $ts.User."$($ts.Self.UserID)".LoginName
if (-not $login) { Fail "Tailscale is not signed in." }
Write-Host "Laptop on Tailscale: $ip ($dns), owner $login"

# --- 2. the lock-screen helper and the boot notice -------------------------------------------------------------
Step "Lock-screen helper and Telegram 'Laptop is ON' at every boot"
$boot = Join-Path $env:ProgramData "ChutkuBoot"
New-Item -ItemType Directory -Force $boot | Out-Null
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)   # only these: administrators and SYSTEM change it, LOCAL SERVICE reads
foreach ($who in "BUILTIN\Administrators", "NT AUTHORITY\SYSTEM") {
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($who, "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")))
}
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule("NT AUTHORITY\LOCAL SERVICE", "ReadAndExecute", "ContainerInherit,ObjectInherit", "None", "Allow")))
Set-Acl $boot $acl
# status\: the boot notice's log (no token, no key), so "no message came" can be explained by anyone on the laptop.
# LOCAL SERVICE writes it; only the notice writes there (SYSTEM's ChutkuUnlock never does: no link tricks into SYSTEM).
$status = Join-Path $boot "status"
New-Item -ItemType Directory -Force $status | Out-Null
$sacl = New-Object Security.AccessControl.DirectorySecurity
$sacl.SetAccessRuleProtection($true, $false)
foreach ($who in "BUILTIN\Administrators", "NT AUTHORITY\SYSTEM") {
    $sacl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($who, "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")))
}
$sacl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule("NT AUTHORITY\LOCAL SERVICE", "Modify", "ContainerInherit,ObjectInherit", "None", "Allow")))
$sacl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule("BUILTIN\Users", "ReadAndExecute", "ContainerInherit,ObjectInherit", "None", "Allow")))
Set-Acl $status $sacl
Copy-Item (Join-Path $helpers "notify.ps1") (Join-Path $boot "notify.ps1") -Force
try { Stop-ScheduledTask -TaskName "ChutkuUnlock" -ErrorAction Stop } catch { }   # a re-run replaces the helper
Get-Process ChutkuUnlock -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
$csc = Join-Path $env:SystemRoot "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
& $csc -nologo -optimize "-out:$boot\ChutkuUnlock.exe" -r:System.Drawing.dll -r:System.Web.Extensions.dll `
    (Join-Path $helpers "ChutkuUnlock.cs")
if ($LASTEXITCODE -ne 0) { Fail "the lock-screen helper did not compile (see above)." }
Add-Type -AssemblyName System.Security
$sealed = [Security.Cryptography.ProtectedData]::Protect([Text.Encoding]::UTF8.GetBytes($info.token), $null, "LocalMachine")
[IO.File]::WriteAllBytes((Join-Path $boot "token.bin"), $sealed)
@{ chat_id = $info.chat; ip = $ip; phone_url = "https://$dns/"; host = $dns; login = $login; unlock_port = 8767
   unlock_https_port = 8443; unlock_url = "https://${dns}:8443/" } | ConvertTo-Json | Set-Content (Join-Path $boot "config.json") -Encoding UTF8
& $tailscale serve --bg --https=8443 http://127.0.0.1:8767   # tailnet only, like the phone remote on 443
if ($LASTEXITCODE -ne 0) { Fail "tailscale serve on 8443 failed." }
# Fast Startup makes "shut down" a hibernation: startup tasks would not run when the laptop is switched on.
Set-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power" -Name HiberbootEnabled -Value 0
Write-Host "Fast Startup is off (Control Panel > Power Options > 'Choose what the power buttons do' turns it back on)."
$always = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "ChutkuUnlock" -Action (New-ScheduledTaskAction -Execute "$boot\ChutkuUnlock.exe" -Argument "watch") `
    -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $always -Force `
    -Principal (New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" -LogonType ServiceAccount -RunLevel Highest) | Out-Null
Start-ScheduledTask -TaskName "ChutkuUnlock"
$action = New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe") `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$boot\notify.ps1`""
$principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\LOCAL SERVICE" -LogonType ServiceAccount
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "ChutkuBootNotice" -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) `
    -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "ChutkuBootNotice"
Write-Host "`nDone. A test 'Laptop is ON' message with the sign-in link is on its way to your Telegram." -ForegroundColor Green
Write-Host "Try it: lock the laptop (Win+L), open the link on your phone, tap the picture, type your password, Sign in."
if ($Quiet) { Start-Sleep -Seconds 8 } else { Read-Host "Press Enter to close" }
