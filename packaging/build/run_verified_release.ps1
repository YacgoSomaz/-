[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$logPath = Join-Path $PSScriptRoot 'build-last.log'
$exitCode = 0
Start-Transcript -LiteralPath $logPath -Force | Out-Null
try {
    $version = $env:LIVEWATCH_BUILD_VERSION
    if ([string]::IsNullOrWhiteSpace($version)) {
        throw 'Version was not provided.'
    }

    $scriptPath = Join-Path $PSScriptRoot 'build_verified_release.ps1'
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        throw "Build script was not found: $scriptPath"
    }

    & $scriptPath -Version $version
    if ($LASTEXITCODE -ne 0) {
        $exitCode = $LASTEXITCODE
    }
}
catch {
    Write-Error $_
    $exitCode = 1
}
finally {
    Stop-Transcript | Out-Null
}

if ($exitCode -eq 0) {
    Write-Host 'Build complete. The installer and release manifest are in the release folder.' -ForegroundColor Green
}
else {
    Write-Host "Build failed (exit code $exitCode). Review the output above or build-last.log." -ForegroundColor Red
}

$global:LASTEXITCODE = $exitCode
