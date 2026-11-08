# Chutku boot notice (owner 2026-11-07): when the laptop boots, before anyone signs in, tell the owner on Telegram
# that it is on, with the lock-screen link (ChutkuUnlock.exe) and Chutku's phone link (Chutku starts after sign-in).
# Runs at startup as NT AUTHORITY\LOCAL SERVICE from C:\ProgramData\ChutkuBoot (writable only by administrators).
# The bot token is in token.bin, encrypted by Windows (DPAPI, this machine); nothing here can act on the laptop.
# Owner 2026-11-08, "no Telegram message came": the laptop's internet was a phone hotspot whose DNS was broken for a
# while, so every try failed. It now tries for 20 minutes, falls back to public DNS (1.1.1.1, 8.8.8.8) with curl.exe,
# and writes what happened to status\notify.log, which anyone on the laptop can read (no token, no key in it).
$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$log = Join-Path $dir "status\notify.log"
function Note($text) {
    try { Add-Content -Path $log -Value ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $text) -Encoding UTF8 } catch { }
}
Add-Type -AssemblyName System.Security
$cfg = Get-Content (Join-Path $dir "config.json") -Raw | ConvertFrom-Json
$sealed = [IO.File]::ReadAllBytes((Join-Path $dir "token.bin"))
$token = [Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect($sealed, $null, "LocalMachine"))
$booted = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
Note "boot at $($booted.ToString('HH:mm:ss')): sending 'Laptop is ON'"
# this boot's key: ChutkuUnlock.exe (SYSTEM, same boot) writes it a few seconds after start-up
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
Note ("lock-screen link: " + $(if ($unlock) { "included" } else { "not ready (ChutkuUnlock gave no key)" }))
$when = Get-Date -Format "dd MMM, HH:mm"
$text = "Laptop is ON ($when).`n`n"
if ($unlock) { $text += "Sign in from the phone (works on the lock screen until the next restart):`n$unlock`n`n" }
$text += "Chutku starts once you sign in, then sends the phone link here.`nPhone remote: $($cfg.phone_url)"
$json = @{ chat_id = $cfg.chat_id; text = $text } | ConvertTo-Json -Compress
$body = [Text.Encoding]::UTF8.GetBytes($json)
$url = "https://api.telegram.org/bot$token/sendMessage"

function Send-Direct {
    Invoke-RestMethod -Method Post -Uri $url -Body $body -ContentType "application/json; charset=utf-8" -TimeoutSec 20 | Out-Null
}

function Send-PublicDns {
    # the network's own DNS can fail (a phone hotspot); look Telegram up at a public resolver and connect to that
    # address with curl --resolve (same certificate checks). The token goes in a private config file, never on a
    # command line other processes could see.
    $curl = Join-Path $env:SystemRoot "System32\curl.exe"
    foreach ($server in "1.1.1.1", "8.8.8.8") {
        try {
            $ip = (Resolve-DnsName api.telegram.org -Server $server -Type A -DnsOnly -QuickTimeout -ErrorAction Stop |
                Where-Object IPAddress | Select-Object -First 1).IPAddress
        } catch { continue }
        if (-not $ip) { continue }
        $config, $payload = [IO.Path]::GetTempFileName(), [IO.Path]::GetTempFileName()   # LOCAL SERVICE's own temp
        try {
            [IO.File]::WriteAllBytes($payload, $body)
            [IO.File]::WriteAllText($config, "url = `"$url`"`nresolve = `"api.telegram.org:443:$ip`"`n" +
                "header = `"Content-Type: application/json; charset=utf-8`"`ndata-binary = `"@$($payload.Replace('\', '/'))`"`n")   # \ escapes in curl's config
            $answer = & $curl -s -S --max-time 20 -K $config 2>&1
            if ($LASTEXITCODE -eq 0 -and "$answer" -match '"ok":\s*true') { return "public DNS $server" }
        } finally {
            Remove-Item $config, $payload -Force -ErrorAction SilentlyContinue
        }
    }
    return $null
}

$deadline, $tries = (Get-Date).AddMinutes(20), 0   # Wi-Fi, a hotspot or its DNS can take a while after boot
while ($true) {
    $tries++
    try {
        Send-Direct
        Note "sent on try $tries"
        break
    } catch {
        $why = $_.Exception.GetType().Name
        $via = Send-PublicDns
        if ($via) { Note "sent on try $tries through $via (the network's DNS failed: $why)"; break }
        if ($tries -eq 1 -or $tries % 8 -eq 0) { Note "try $tries failed ($why); trying again every 15 s" }
    }
    if ((Get-Date) -gt $deadline) { Note "gave up after 20 minutes ($tries tries): no internet reached Telegram"; break }
    Start-Sleep -Seconds 15
}
