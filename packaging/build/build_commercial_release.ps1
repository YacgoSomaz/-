<#
  LiveWatch commercial one-click build wrapper.

  This wrapper is intentionally thin: it resolves the licensing public key, then
  delegates the real packaging work to build_release.ps1 with -Commercial.

  Secrets policy:
    - Do not hardcode admin tokens, AI keys, or private keys here.
    - Use LIVEWATCH_LICENSE_PUBLIC_KEY for offline builds, or
      LIVEWATCH_LICENSE_ADMIN_TOKEN to fetch /admin/public-key at build time.
#>
[CmdletBinding()]
param(
    [string]$Version = "1.0.0",
    [string]$LicenseServerUrl = "https://license.runmo.art",
    [string]$LicensePublicKey = "",
    [string]$AdminToken = "",
    [string]$NodeExe = "",
    [string]$Iscc = "",
    [switch]$SkipInstaller,
    [string]$CodeSignThumbprint = "",
    [string]$SignTool = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildScript = Join-Path $ScriptDir "build_release.ps1"
if (-not (Test-Path $BuildScript)) {
    throw "Missing build script: $BuildScript"
}

function Write-Step($Message) {
    Write-Host "`n==== $Message ====" -ForegroundColor Cyan
}

function Resolve-LicensePublicKey {
    param(
        [string]$ExplicitPublicKey,
        [string]$ExplicitAdminToken,
        [string]$ServerUrl
    )

    $publicKey = $ExplicitPublicKey.Trim()
    if (-not $publicKey -and $env:LIVEWATCH_LICENSE_PUBLIC_KEY) {
        $publicKey = $env:LIVEWATCH_LICENSE_PUBLIC_KEY.Trim()
    }
    if ($publicKey) {
        return $publicKey
    }

    $token = $ExplicitAdminToken.Trim()
    if (-not $token -and $env:LIVEWATCH_LICENSE_ADMIN_TOKEN) {
        $token = $env:LIVEWATCH_LICENSE_ADMIN_TOKEN.Trim()
    }
    if (-not $token) {
        throw @"
Missing licensing public key.

Choose one:
  1. Set LIVEWATCH_LICENSE_PUBLIC_KEY to the Ed25519 public key, then rerun.
  2. Set LIVEWATCH_LICENSE_ADMIN_TOKEN to the license admin token so this script can fetch:
     $ServerUrl/admin/public-key

No admin token or private key will be written into the installer.
"@
    }

    if ($ServerUrl -notmatch '^https://[^/\s]+(?:/[^\s]*)?$') {
        throw "LicenseServerUrl must be HTTPS, for example: https://license.runmo.art"
    }

    $endpoint = $ServerUrl.TrimEnd("/") + "/admin/public-key"
    Write-Host "Fetching license public key from: $endpoint"
    $headers = @{ Authorization = "Bearer $token" }
    $response = Invoke-RestMethod -Method Get -Uri $endpoint -Headers $headers -TimeoutSec 20
    if (-not $response.public_key) {
        throw "License server response did not contain public_key."
    }
    return [string]$response.public_key
}

Write-Step "Commercial build settings"
if ($LicenseServerUrl -notmatch '^https://[^/\s]+(?:/[^\s]*)?$') {
    throw "LicenseServerUrl must be HTTPS, for example: https://license.runmo.art"
}

$ResolvedPublicKey = Resolve-LicensePublicKey `
    -ExplicitPublicKey $LicensePublicKey `
    -ExplicitAdminToken $AdminToken `
    -ServerUrl $LicenseServerUrl

if ($ResolvedPublicKey -notmatch '^[A-Za-z0-9_-]{40,96}$') {
    throw "Resolved license public key is not a valid base64url Ed25519 public key."
}

Write-Host "License server : $LicenseServerUrl"
Write-Host "Version        : $Version"
Write-Host "Installer      : $(-not $SkipInstaller)"
Write-Host "Code signing   : $([bool]$CodeSignThumbprint)"
Write-Host "Hardening      : Nuitka pipeline compile + signed integrity manifest + release scanner"

$buildArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $BuildScript,
    "-Commercial",
    "-LicenseServerUrl", $LicenseServerUrl,
    "-LicensePublicKey", $ResolvedPublicKey,
    "-Version", $Version
)

if ($NodeExe) { $buildArgs += @("-NodeExe", $NodeExe) }
if ($Iscc) { $buildArgs += @("-Iscc", $Iscc) }
if ($SkipInstaller) { $buildArgs += "-SkipInstaller" }
if ($CodeSignThumbprint) { $buildArgs += @("-CodeSignThumbprint", $CodeSignThumbprint) }
if ($SignTool) { $buildArgs += @("-SignTool", $SignTool) }

Write-Step "Run commercial package build"
& pwsh @buildArgs
if ($LASTEXITCODE -ne 0) {
    throw "Commercial package build failed with exit code $LASTEXITCODE"
}

Write-Step "Commercial package build completed"
Write-Host "Next checks:"
Write-Host "  - Install on a clean machine or VM."
Write-Host "  - Activate with a real card key."
Write-Host "  - Confirm tampering with app files fails at startup."
