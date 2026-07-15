[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host ''
Write-Host '========================================' -ForegroundColor Cyan
Write-Host '       LiveWatch Official Build' -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan
Write-Host 'This process performs the commercial build and release checks.'
Write-Host ''

$version = Read-Host 'Enter version (next build: 1.1.15)'
if ([string]::IsNullOrWhiteSpace($version)) {
    Write-Host 'No version entered. Build cancelled.' -ForegroundColor Yellow
    return
}

$env:LIVEWATCH_BUILD_VERSION = $version
$runnerPath = Join-Path $PSScriptRoot 'run_verified_release.ps1'
if (-not (Test-Path -LiteralPath $runnerPath)) {
    throw "Build runner was not found: $runnerPath"
}

& $runnerPath
