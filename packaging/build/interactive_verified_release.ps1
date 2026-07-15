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

$versionGuardPath = Join-Path $PSScriptRoot 'version_guard.ps1'
if (-not (Test-Path -LiteralPath $versionGuardPath)) {
    throw "Version guard was not found: $versionGuardPath"
}
$version = (& pwsh -NoProfile -File $versionGuardPath -NextVersion).Trim()
if ([string]::IsNullOrWhiteSpace($version)) { throw 'Unable to derive the next online version.' }
Write-Host "Online release detected. Building next version automatically: $version" -ForegroundColor Green

$env:LIVEWATCH_BUILD_VERSION = $version
$runnerPath = Join-Path $PSScriptRoot 'run_verified_release.ps1'
if (-not (Test-Path -LiteralPath $runnerPath)) {
    throw "Build runner was not found: $runnerPath"
}

& $runnerPath
