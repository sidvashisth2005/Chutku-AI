# Move the Chutku project folder and re-point everything that records its absolute path.
# Run from OUTSIDE the folder, with VS Code closed on it:
#   powershell -ExecutionPolicy Bypass -File "D:\Project\CHUTKU COPY\Chutku\scripts\relocate.ps1" [-DryRun]
param(
    [string]$Source = (Split-Path -Parent $PSScriptRoot),
    [string]$Target = 'D:\Project\Chutku',
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
Set-Location $env:TEMP   # never hold the folder being moved
$Source = (Resolve-Path -LiteralPath $Source).Path.TrimEnd('\')
function Step($msg) { Write-Host ("[{0}] {1}" -f ($(if ($DryRun) { 'dry-run' } else { 'run' }), $msg)) }
# Run Chutku's python inside a folder (so `-m chutku...` resolves) without PS 5.1 turning stderr into a terminating error.
function RunPy($dir, [string[]]$pyArgs) {
    Push-Location -LiteralPath $dir
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $out = & (Join-Path $dir '.venv\Scripts\python.exe') @pyArgs 2>&1; $script:PyExit = $LASTEXITCODE; $out | ForEach-Object { "$_" } }
    finally { $ErrorActionPreference = $old; Pop-Location }
}
function ProjectKey($p) { ($p.Substring(0, 1).ToLower() + $p.Substring(1)) -replace '[^A-Za-z0-9]', '-' }   # D:\X Y\Z -> d--X-Y-Z

if ($Source -ieq $Target) { throw "Already at $Target." }
if (Test-Path -LiteralPath $Target) { throw "Target already exists: $Target (refusing to overwrite)." }
if (-not (Test-Path -LiteralPath (Join-Path $Source 'chutku\__init__.py'))) { throw "$Source is not a Chutku project." }
$python = Join-Path $Source '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw "Missing venv interpreter: $python" }

# 1. Stop Chutku (guard, dashboard) so no file inside is locked.
$procs = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($Source) -and $_.ProcessId -ne $PID })
Step "stop $($procs.Count) Chutku process(es)"
if (-not $DryRun) {
    RunPy $Source @('-m', 'chutku.cli', 'control', 'stop') | Out-Null
    Start-Sleep -Seconds 3
    foreach ($p in $procs) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {} }
    Start-Sleep -Seconds 1
}

# 2. Move the folder (fails cleanly if VS Code or a terminal still has it open).
Step "move '$Source' -> '$Target'"
if (-not $DryRun) {
    try { Move-Item -LiteralPath $Source -Destination $Target -ErrorAction Stop }
    catch {
        # leave Chutku running as it was (the logon task only: starting a Reminder-* task would fire that reminder)
        Get-ScheduledTask -TaskPath '\Chutku\' -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -notlike 'Reminder-*' } |
            Select-Object -First 1 | Start-ScheduledTask
        throw "Move failed, nothing changed (close VS Code / terminals using the folder, then re-run): $($_.Exception.Message)"
    }
    $python = Join-Path $Target '.venv\Scripts\python.exe'
}

# 3. Re-point the runtime sandbox grant and user grants (resource_grants.py refuses a retargeted sandbox).
Step "rewrite grant roots in data\resource_grants.db"
if (-not $DryRun) {
    $code = @'
import sqlite3, sys
src, dst, db = sys.argv[1], sys.argv[2], sys.argv[3]
c = sqlite3.connect(db)
with c:
    for gid, key, disp in list(c.execute("SELECT grant_id, canonical_root, display_root FROM resource_grants")):
        if disp.lower() == src.lower() or disp.lower().startswith(src.lower() + "\\"):
            nd = dst + disp[len(src):]
            c.execute("UPDATE resource_grants SET canonical_root=?, display_root=? WHERE grant_id=?", (nd.lower(), nd, gid))
            print("  grant", gid, "->", nd)
'@
    $tmp = Join-Path $env:TEMP 'chutku-relocate-grants.py'
    Set-Content -LiteralPath $tmp -Value $code -Encoding utf8
    RunPy $Target @($tmp, $Source, $Target, (Join-Path $Target 'data\resource_grants.db'))
    if ($script:PyExit) { throw "Grant rewrite failed." }
}

# 4. Every task in \Chutku\: the logon task AND each reminder (their arguments hold the project path too).
foreach ($task in @(Get-ScheduledTask -TaskPath '\Chutku\' -ErrorAction SilentlyContinue)) {
    Step "re-point scheduled task \Chutku\$($task.TaskName)"
    if (-not $DryRun) {
        $actions = foreach ($a in $task.Actions) {
            $arguments = if ($a.Arguments) { $a.Arguments.Replace($Source, $Target) } else { $null }
            $directory = if ($a.WorkingDirectory) { $a.WorkingDirectory.Replace($Source, $Target) } else { $null }
            if ($arguments -and $directory) {
                New-ScheduledTaskAction -Execute ($a.Execute.Replace($Source, $Target)) -Argument $arguments -WorkingDirectory $directory
            } elseif ($arguments) {
                New-ScheduledTaskAction -Execute ($a.Execute.Replace($Source, $Target)) -Argument $arguments
            } else {
                New-ScheduledTaskAction -Execute ($a.Execute.Replace($Source, $Target))
            }
        }
        Set-ScheduledTask -TaskPath '\Chutku\' -TaskName $task.TaskName -Action $actions | Out-Null
    }
}

# 5. Claude Code: project-scoped plugin registrations and memory folder.
$plugins = Join-Path $env:USERPROFILE '.claude\plugins\installed_plugins.json'
if (Test-Path -LiteralPath $plugins) {
    Step "re-point project plugin paths in installed_plugins.json (backup kept)"
    if (-not $DryRun) {
        Copy-Item -LiteralPath $plugins "$plugins.bak-relocate" -Force
        $json = [IO.File]::ReadAllText($plugins)
        [IO.File]::WriteAllText($plugins, $json.Replace($Source.Replace('\', '\\'), $Target.Replace('\', '\\')))
    }
}
$projects = Join-Path $env:USERPROFILE '.claude\projects'
$oldMem = Join-Path $projects ((ProjectKey $Source) + '\memory')
$newMem = Join-Path $projects ((ProjectKey $Target) + '\memory')
if ((Test-Path -LiteralPath $oldMem) -and -not (Test-Path -LiteralPath $newMem)) {
    Step "copy Claude memory '$oldMem' -> '$newMem'"
    if (-not $DryRun) { New-Item -ItemType Directory -Force (Split-Path $newMem) | Out-Null; Copy-Item -LiteralPath $oldMem -Destination $newMem -Recurse }
}

# 6. Remove the now-empty parent (e.g. "CHUTKU COPY").
$parent = Split-Path -Parent $Source
Step "remove empty parent '$parent' if empty"
if (-not $DryRun -and (Test-Path -LiteralPath $parent) -and -not (Get-ChildItem -LiteralPath $parent -Force)) { Remove-Item -LiteralPath $parent }

# 7. Verify and restart.
if (-not $DryRun) {
    RunPy $Target @('-m', 'chutku.cli', 'doctor')
    if ($task) { Start-ScheduledTask -TaskPath '\Chutku\' -TaskName $task.TaskName }
    Step "done: open VS Code at $Target"
}
