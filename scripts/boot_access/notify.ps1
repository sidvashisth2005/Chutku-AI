# Chutku boot notice (owner 2026-11-07): when the laptop boots, before anyone signs in, tell the owner on Telegram
# that it is on, with the lock-screen link (ChutkuUnlock.exe) and Chutku's phone link (Chutku starts after sign-in).
# Runs at startup as NT AUTHORITY\LOCAL SERVICE from C:\ProgramData\ChutkuBoot (writable only by administrators).
# The bot token is in token.bin, encrypted by Windows (DPAPI, this machine); nothing here can act on the laptop.
$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Add-Type -AssemblyName System.Security
$cfg = Get-Content (Join-Path $dir "config.json") -Raw | ConvertFrom-Json
$sealed = [IO.File]::ReadAllBytes((Join-Path $dir "token.bin"))
$token = [Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect($sealed, $null, "LocalMachine"))
# this boot's key: ChutkuUnlock.exe (SYSTEM, same boot) writes it a few seconds after start-up
$booted = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$keyFile = Join-Path $dir "key.txt"
$unlock = $null
$wait = (Get-Date).AddMinutes(3)
while ($cfg.unlock_url -and (Get-Date) -lt $wait) {
    if ((Test-Path $keyFile) -and (Get-Item $keyFile).LastWriteTime -gt $booted) {
        $unlock = "$($cfg.unlock_url)#k=$((Get-Content $keyFile -Raw).Trim())"
        break
    }
    Start-Sleep -Seconds 5
}
$when = Get-Date -Format "dd MMM, HH:mm"
$text = "Laptop is ON ($when).`n`n"
if ($unlock) { $text += "Sign in from the phone (works on the lock screen until the next restart):`n$unlock`n`n" }
$text += "Chutku starts once you sign in, then sends the phone link here.`nPhone remote: $($cfg.phone_url)"
$body = [Text.Encoding]::UTF8.GetBytes((@{ chat_id = $cfg.chat_id; text = $text } | ConvertTo-Json -Compress))
$deadline = (Get-Date).AddMinutes(10)   # Wi-Fi and Tailscale can take a while after boot
while ($true) {
    try {
        Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$token/sendMessage" -Body $body `
            -ContentType "application/json; charset=utf-8" -TimeoutSec 20 | Out-Null
        break
    } catch {
        if ((Get-Date) -gt $deadline) { break }
        Start-Sleep -Seconds 15
    }
}
