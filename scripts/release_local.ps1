# Owner 2026-11-09: every release is built on this PC. Build -> setup -> install/uninstall test -> publish -> delete old.
param([Parameter(Mandatory = $true)][string]$Version, [string]$Old)
$ErrorActionPreference = "Stop"
Set-Location D:\Project\Chutku
& .\.venv\Scripts\python.exe scripts\build_release.py --out dist --version $Version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "build failed" }
& .\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, '.'); from chutku.icon import icon_bytes; open('installer/chutku.ico', 'wb').write(icon_bytes())"
$zip = "D:\Project\Chutku\dist\Chutku-$Version-win64.zip"
$hash = (Get-Content "$zip.sha256").Split(' ')[0]
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /Qp "/DAppVersion=$Version" "/DPackageZip=$zip" "/DPackageSha256=$hash" installer\chutku.iss | Out-Null
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }
$dir = "$env:TEMP\ctest-$Version\Chutku"
$p = Start-Process dist\Chutku-Setup-for-Windows.exe -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /TASKS="""" /DIR=""$dir""" -Wait -PassThru
$v = (Get-Content "$dir\version.json" -Raw | ConvertFrom-Json).version
if ($p.ExitCode -ne 0 -or $v -ne $Version) { throw "install test failed ($($p.ExitCode), $v)" }
$un = Get-ChildItem $dir -Filter "unins*.exe" | Select-Object -First 1
Start-Process $un.FullName -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" -Wait | Out-Null
Start-Sleep 3
if (Test-Path "$dir\Chutku.exe") { throw "uninstall test failed" }
"install/uninstall test ok ($v)"
gh release create "v$Version" -R sidvashisth2005/Chutku-releases --title "Chutku v$Version for Windows" --notes-file installer\release_notes.md dist\Chutku-Setup-for-Windows.exe
if ($LASTEXITCODE -ne 0) { throw "publish failed" }
if ($Old) { gh release delete "v$Old" -R sidvashisth2005/Chutku-releases --yes --cleanup-tag }
gh release list -R sidvashisth2005/Chutku-releases
