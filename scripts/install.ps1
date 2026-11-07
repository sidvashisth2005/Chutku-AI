<#
.SYNOPSIS
    One-click Chutku install for a new PC: Python check, private virtual environment, pinned packages,
    model check (optional download), health check, and (optional) start at sign-in.

.EXAMPLE
    Install-Chutku.cmd                       # packages + health check; models are only checked
    Install-Chutku.cmd -Models               # also download the pinned local models (several GB, hash-checked)
    Install-Chutku.cmd -Models -Autostart    # ...and start Chutku when you sign in to Windows

Nothing outside this folder is changed, except the optional sign-in task (-Autostart). Run it as a normal user,
not as Administrator.
#>
param(
    [switch]$Models,
    [switch]$Autostart,
    [string]$PythonExe = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nInstall stopped: $text" -ForegroundColor Red; exit 1 }

# 1. A supported Python (3.11 or newer). The Windows "py" launcher is tried first, then python on PATH.
Step "Looking for Python 3.11+"
$candidates = @()
if ($PythonExe) { $candidates += ,@($PythonExe) }
else {
    foreach ($v in "3.13", "3.12", "3.11") { $candidates += ,@("py", "-$v") }
    $candidates += ,@("python")
}
$python = $null
foreach ($c in $candidates) {
    try {
        $exe = $c[0]; $rest = @($c | Select-Object -Skip 1)
        $version = & $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $version -match '^(\d+)\.(\d+)$' -and
            ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11))) {
            $python = $c; Write-Host "Using Python $version ($($c -join ' '))"; break
        }
        if ($version) { Write-Host "Skipping Python $version ($($c -join ' ')): Chutku needs 3.11 or newer" }
    } catch { }
}
if (-not $python) { Fail "Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again." }

# 2. Chutku's own virtual environment, so nothing else on the PC is affected.
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Step "Creating the virtual environment (.venv)"
    $exe = $python[0]; $rest = @($python | Select-Object -Skip 1)
    & $exe @rest -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "could not create .venv" }
}

# 3. Exactly the pinned packages.
Step "Installing pinned packages (requirements.lock)"
& $venvPython -m pip install --disable-pip-version-check --no-cache-dir --require-hashes -r requirements.lock
if ($LASTEXITCODE -ne 0) { Fail "a package failed to install (see the lines above)" }

# 3b. The pinned helper CLIs (tools/package-lock.json, integrity-checked by npm): agent-desktop for background app
#     control, agent-browser for the signed-in browser. Optional: without Node.js those two features say so.
Step "Installing helper tools (tools/package-lock.json)"
if (Get-Command npm -ErrorAction SilentlyContinue) {
    & npm ci --prefix tools --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { Fail "the helper tools failed to install (see the lines above)" }
} else {
    Write-Host "Node.js (npm) not found: background app control and the signed-in browser stay off. Install Node.js LTS and run this again to add them." -ForegroundColor Yellow
}

# 4. Local models: checked always, downloaded only with -Models (each file must match its pinned SHA-256).
Step "Checking local models (models/manifest.json)"
if ($Models) { & $venvPython scripts\setup_all.py --download } else { & $venvPython scripts\setup_all.py }
$modelsOk = ($LASTEXITCODE -eq 0)
if (-not $modelsOk -and $Models) { Fail "a model download failed or did not match its pinned hash" }

# 5. Health check (no microphone, no model start).
Step "Health check"
& $venvPython -m chutku.cli doctor | Out-Null
if ($LASTEXITCODE -ne 0) { & $venvPython -m chutku.cli doctor; Fail "the health check found a problem (see above)" }
Write-Host "Health check passed."

if ($Autostart) {
    Step "Starting Chutku when you sign in"
    & $venvPython -m chutku.cli autostart on
}

Write-Host "`nChutku is installed." -ForegroundColor Green
if (-not $modelsOk) {
    Write-Host "Local models are not all present: Chutku will use free cloud brains when online."
    Write-Host "For offline use run: Install-Chutku.cmd -Models"
}
if (-not [Console]::IsInputRedirected) {   # only when someone is at the keyboard
    Write-Host "Next: answer 4 quick setup questions (name, free brain key, mic, autonomy):"
    & $venvPython -m chutku.cli setup
}
Write-Host "Start it with Start-Chutku.cmd. Run setup again any time: .venv\Scripts\python.exe -m chutku.cli setup"
exit 0
