# Chutku boot notice (owner 2026-11-07): when the laptop boots, before anyone signs in, tell the owner on Telegram
# that it is on and how to unlock it from the phone (RustDesk over Tailscale), then Chutku's own phone link.
# Runs at startup as NT AUTHORITY\LOCAL SERVICE from C:\ProgramData\ChutkuBoot (writable only by administrators).
# The bot token is in token.bin, encrypted by Windows (DPAPI, this machine); nothing here can act on the laptop.
$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Add-Type -AssemblyName System.Security
$cfg = Get-Content (Join-Path $dir "config.json") -Raw | ConvertFrom-Json
$sealed = [IO.File]::ReadAllBytes((Join-Path $dir "token.bin"))
$token = [Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect($sealed, $null, "LocalMachine"))
$when = Get-Date -Format "dd MMM, HH:mm"
$text = "Laptop is ON ($when).`n`n" +
        "1) Unlock it: open RustDesk on your phone, connect to $($cfg.ip), enter your Windows password on the login screen.`n" +
        "2) Then Chutku on your phone: $($cfg.phone_url)`n`n" +
        "(Chutku starts by itself once you are signed in.)"
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
