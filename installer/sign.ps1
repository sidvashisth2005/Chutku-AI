# W4: sign Chutku's executables when a code-signing certificate is available; skipped (exit 0) otherwise.
#   powershell -File installer/sign.ps1 -Files dist\ChutkuSetup.exe, <app>\Chutku.exe
# The certificate comes from the environment, never from a file in the repository:
#   CHUTKU_SIGN_PFX_BASE64  the .pfx, base64-encoded (a GitHub secret)
#   CHUTKU_SIGN_PASSWORD    its password (a GitHub secret)
#   CHUTKU_SIGN_TIMESTAMP   optional RFC 3161 timestamp server (default: DigiCert)
param([Parameter(Mandatory = $true)][string[]]$Files)
$ErrorActionPreference = "Stop"
if (-not $env:CHUTKU_SIGN_PFX_BASE64 -or -not $env:CHUTKU_SIGN_PASSWORD) {
    Write-Host "Signing skipped: no certificate configured (the setup is unsigned; SmartScreen shows 'More info -> Run anyway')."
    exit 0
}
$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -like "*\x64\*" } | Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) { throw "signtool.exe was not found (install the Windows SDK)." }
$pfx = Join-Path ([IO.Path]::GetTempPath()) ("chutku-" + [Guid]::NewGuid() + ".pfx")
try {
    [IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:CHUTKU_SIGN_PFX_BASE64))
    $timestamp = if ($env:CHUTKU_SIGN_TIMESTAMP) { $env:CHUTKU_SIGN_TIMESTAMP } else { "http://timestamp.digicert.com" }
    foreach ($file in $Files) {
        & $signtool.FullName sign /f $pfx /p $env:CHUTKU_SIGN_PASSWORD /fd sha256 /tr $timestamp /td sha256 $file
        if ($LASTEXITCODE -ne 0) { throw "signtool failed for $file" }
        & $signtool.FullName verify /pa $file
        if ($LASTEXITCODE -ne 0) { throw "The signature of $file does not verify" }
    }
} finally {
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
}
