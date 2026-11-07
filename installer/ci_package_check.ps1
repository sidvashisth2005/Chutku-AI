# W3: prove a built package on a clean Windows runner (also usable by hand on a test PC).
#   powershell -File installer/ci_package_check.ps1 -Zip dist\Chutku-<version>-win64.zip
# Unzips the package, starts Chutku.exe, waits for the dashboard on 127.0.0.1:8765, runs doctor, stops Chutku and
# checks that no file was created or changed under the app folder (all state must go to CHUTKU_HOME).
param([Parameter(Mandatory = $true)][string]$Zip, [string]$App = "", [string]$HomeDir = "")
$ErrorActionPreference = "Stop"
$temp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
if (-not $App) { $App = Join-Path $temp "ChutkuApp" }
if (-not $HomeDir) { $HomeDir = Join-Path $temp "ChutkuHome" }
Remove-Item $App, $HomeDir -Recurse -Force -ErrorAction SilentlyContinue

$clock = [Diagnostics.Stopwatch]::StartNew()
Expand-Archive -Path $Zip -DestinationPath $App -Force
$unzip = $clock.Elapsed.TotalSeconds
function Snapshot { Get-ChildItem $App -Recurse -File | ForEach-Object { "$($_.FullName)|$($_.Length)|$($_.LastWriteTimeUtc.Ticks)" } | Sort-Object }
$before = Snapshot

$env:CHUTKU_HOME = $HomeDir
$clock.Restart()
Start-Process -FilePath (Join-Path $App "Chutku.exe") -ArgumentList "--background"
$answered = $false
for ($i = 0; $i -lt 120; $i++) {
    try {
        $page = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8765/" -TimeoutSec 2
        if ($page.StatusCode -eq 200) { $answered = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
$firstLaunch = $clock.Elapsed.TotalSeconds
if (-not $answered) {
    Get-ChildItem $HomeDir -Recurse -ErrorAction SilentlyContinue | Select-Object FullName | Format-Table -AutoSize
    Get-ChildItem (Join-Path $HomeDir "data\logs") -File -ErrorAction SilentlyContinue | ForEach-Object { Get-Content $_.FullName -Tail 60 }
    throw "The dashboard did not answer on 127.0.0.1:8765 within 120 s."
}
Write-Host "Dashboard answered after $([math]::Round($firstLaunch, 1)) s"

# doctor from the installed app (the runner is Administrator: only that check may fail)
$python = Join-Path $App "python\python.exe"
Push-Location $App
$doctor = & $python -m chutku.cli doctor | Out-String
Pop-Location
$report = $doctor | ConvertFrom-Json
$failed = @($report.checks | Where-Object { $_.required -and -not $_.ready } | ForEach-Object { $_.name })
$unexpected = @($failed | Where-Object { $_ -ne "Not elevated" })
Write-Host "doctor: required checks not ready: $($failed -join ', ')"
if ($unexpected.Count -gt 0) { throw "doctor failed: $($unexpected -join ', ')" }

& (Join-Path $App "Chutku.exe") --stop | Out-Null
for ($i = 0; $i -lt 60; $i++) {
    $left = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($App, [StringComparison]::OrdinalIgnoreCase) })
    if ($left.Count -eq 0) { break }
    Start-Sleep -Seconds 1
}
if ($left.Count -gt 0) { $left | Stop-Process -Force; throw "Chutku did not stop within 60 s." }

$after = Snapshot
$changed = Compare-Object $before $after | ForEach-Object { $_.InputObject }
if ($changed) { $changed | Select-Object -First 20 | ForEach-Object { Write-Host "CHANGED: $_" }; throw "Files under the app folder were created or changed." }
if (-not (Test-Path (Join-Path $HomeDir "data"))) { throw "Nothing was written to CHUTKU_HOME." }

$size = (Get-Item $Zip).Length
$installed = (Get-ChildItem $App -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("PACKAGE-TABLE zip_mb={0:N1} installed_mb={1:N1} unzip_s={2:N1} first_launch_s={3:N1}" -f ($size / 1MB), ($installed / 1MB), $unzip, $firstLaunch)
Write-Host "Package check passed: started, answered, doctor ok, stopped, app folder untouched."
