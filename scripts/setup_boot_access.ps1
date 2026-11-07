<#
.SYNOPSIS
    One-time setup (run as administrator, owner 2026-11-07): reach the laptop from the phone right after it boots.
      1. Tailscale unattended: the laptop joins your tailnet at boot, before anyone signs in.
      2. RustDesk 1.5.1 (official MSI, SHA-256 checked): its service shows the Windows login screen, so you can type
         your password from the phone. It accepts only Tailscale addresses (100.64.0.0/10); you set its password here.
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
$python = Join-Path $root ".venv\Scripts\python.exe"
$info = & $python -c "import json; from chutku.app import PROJECT_ROOT; from chutku.gateway import telegram as tg; print(json.dumps({'token': tg.token() or '', 'chat': tg.paired(PROJECT_ROOT)}))" | ConvertFrom-Json
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

# --- 2. RustDesk for the login screen ---------------------------------------------------------------------------
Step "RustDesk: unlock the laptop from the phone"
$rustdesk = Join-Path $env:ProgramFiles "RustDesk\rustdesk.exe"
if (-not (Test-Path $rustdesk)) {
    $msi = Join-Path $env:TEMP "rustdesk-1.5.1-x86_64.msi"
    Invoke-WebRequest "https://github.com/rustdesk/rustdesk/releases/download/1.5.1/rustdesk-1.5.1-x86_64.msi" -OutFile $msi
    $hash = (Get-FileHash $msi -Algorithm SHA256).Hash.ToLower()
    if ($hash -ne "71069183cbc6124273138684ab4032d2211e83efa035886f9c774fe1d3eba3f0") { Remove-Item $msi; Fail "the RustDesk download did not match its published SHA-256." }
    Start-Process msiexec.exe -ArgumentList "/i", "`"$msi`"", "/qn", "/norestart" -Wait
    Remove-Item $msi
    Start-Sleep -Seconds 5
}
if (-not (Test-Path $rustdesk)) { Fail "RustDesk did not install." }
& $rustdesk --option direct-server Y | Out-Null            # connect by the laptop's Tailscale address
& $rustdesk --option whitelist "100.64.0.0/10" | Out-Null   # only devices on your Tailscale network
Write-Host "Choose RustDesk's permanent password (you will type it in the RustDesk app on the phone)."
$first = Read-Host "RustDesk password (8+ characters)" -AsSecureString
$again = Read-Host "Again" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($first))
$check = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($again))
if ($plain -ne $check -or $plain.Length -lt 8) { Fail "the passwords differ or are shorter than 8 characters." }
& $rustdesk --password $plain | Out-Null
$plain = $null; $check = $null

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
Write-Host "On the phone: install RustDesk (Play Store), connect to $ip with the password you just set."
Read-Host "Press Enter to close"
