# W4: the clean-machine install test (release workflow and the package job; also usable by hand on a test PC).
#   powershell -File installer/ci_install_check.ps1 -Setup dist\ChutkuSetup.exe -Zip dist\Chutku-<v>-win64.zip
# 1. A tampered copy of the package is refused (nothing installed).
# 2. A silent install from the local, hash-checked package.
# 3. doctor from the installed app (only "Not elevated" may fail: CI runners are Administrator).
# 4. One text command through the installed, running app (/api/chat with the session token, then its answer).
# 5. Silent uninstall: the app folder is gone; the user's data is deleted only because /DELETEDATA=yes is given.
param([Parameter(Mandatory = $true)][string]$Setup, [Parameter(Mandatory = $true)][string]$Zip)
$ErrorActionPreference = "Stop"
$app = Join-Path $env:LOCALAPPDATA "Programs\Chutku"
$data = Join-Path $env:LOCALAPPDATA "Chutku"
$temp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
function Run-Setup([string]$Arguments) {
    $process = Start-Process -FilePath $Setup -ArgumentList $Arguments -Wait -PassThru
    return $process.ExitCode
}

# 1. tampered package: one byte appended, the original .sha256 kept
$tampered = Join-Path $temp "Chutku-tampered.zip"
Copy-Item $Zip $tampered -Force
Copy-Item "$Zip.sha256" "$tampered.sha256" -Force
[IO.File]::AppendAllText($tampered, "x")
$code = Run-Setup "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /PACKAGE=`"$tampered`""
if ($code -eq 0 -or (Test-Path (Join-Path $app "Chutku.exe"))) { throw "A tampered package was installed (exit $code)." }
Write-Host "Tampered package refused (exit $code)."

# 2. install
$clock = [Diagnostics.Stopwatch]::StartNew()
$code = Run-Setup "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /PACKAGE=`"$Zip`""
$installSeconds = $clock.Elapsed.TotalSeconds
if ($code -ne 0 -or -not (Test-Path (Join-Path $app "Chutku.exe"))) { throw "The install failed (exit $code)." }
Write-Host ("Installed in {0:N1} s" -f $installSeconds)

# 3. doctor
Push-Location $app
$env:CHUTKU_HOME = $data
$report = (& (Join-Path $app "python\python.exe") -m chutku.cli doctor | Out-String) | ConvertFrom-Json
Pop-Location
$unexpected = @($report.checks | Where-Object { $_.required -and -not $_.ready -and $_.name -ne "Not elevated" } | ForEach-Object { $_.name })
if ($unexpected.Count -gt 0) { throw "doctor failed: $($unexpected -join ', ')" }
Write-Host "Installed doctor: ok"

# 4. one text command through the installed app
Start-Process -FilePath (Join-Path $app "Chutku.exe") -ArgumentList "--background"
$link = Join-Path $data "data\dashboard-session.json"
for ($i = 0; $i -lt 120 -and -not (Test-Path $link); $i++) { Start-Sleep -Seconds 1 }
if (-not (Test-Path $link)) { throw "The installed Chutku did not start (no session link after 120 s)." }
Start-Sleep -Seconds 2
$url = (Get-Content $link -Raw | ConvertFrom-Json).url
$token = ($url -split '#token=')[1]
$base = "http://127.0.0.1:8765"
$headers = @{ "X-Chutku-Token" = $token; "Origin" = $base; "X-Chutku-Synthetic" = "1" }
$answer = Invoke-RestMethod -Method Post -Uri "$base/api/chat" -Headers $headers -ContentType "application/json" -Body '{"message": "what time is it"}'
if ($answer.kind -eq "agent") {
    $id = $answer.session.id
    for ($i = 0; $i -lt 60; $i++) {
        $session = (Invoke-RestMethod -Uri "$base/api/agent/session?id=$id" -Headers @{ "X-Chutku-Token" = $token }).session
        if ($session.status -notin @("planning", "running", "queued")) { break }
        Start-Sleep -Seconds 1
    }
    $reply = $session.reply
    $status = $session.status
} else {
    $reply = $answer.message
    $status = "direct"
}
Write-Host "Text command answered ($status): $reply"
if (-not $reply) { throw "The text command got no answer." }
& (Join-Path $app "Chutku.exe") --stop | Out-Null
Start-Sleep -Seconds 5

# 5. uninstall
$uninstaller = Get-ChildItem $app -Filter "unins*.exe" | Select-Object -First 1
$process = Start-Process -FilePath $uninstaller.FullName -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DELETEDATA=yes" -Wait -PassThru
for ($i = 0; $i -lt 30 -and (Test-Path (Join-Path $app "Chutku.exe")); $i++) { Start-Sleep -Seconds 1 }
if (Test-Path (Join-Path $app "Chutku.exe")) { throw "The uninstaller left the app behind." }
if (Test-Path $data) { throw "The data folder was not deleted although /DELETEDATA=yes was given." }
$setupMb = (Get-Item $Setup).Length / 1MB
Write-Host ("INSTALL-TABLE setup_mb={0:N2} install_s={1:N1}" -f $setupMb, $installSeconds)
Write-Host "Install check passed: tampered refused, installed, doctor ok, text command answered, uninstalled."
