[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Version,
    [string]$PublishedVersion = '',
    [string]$Endpoint = 'https://anyq.site/api/v1/releases/latest?product_id=replay_shrimp'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function ConvertTo-VersionParts {
    param([Parameter(Mandatory)][string]$Value)
    $core = ($Value -split '[-+]', 2)[0]
    if ($core -notmatch '^\d+(?:\.\d+){1,3}$') {
        throw "版本号格式无效: $Value"
    }
    $parts = [System.Collections.Generic.List[int64]]::new()
    foreach ($part in $core.Split('.')) { $parts.Add([int64]$part) }
    while ($parts.Count -lt 4) { $parts.Add(0) }
    return $parts.ToArray()
}

function Compare-ReleaseVersion {
    param(
        [Parameter(Mandatory)][string]$Left,
        [Parameter(Mandatory)][string]$Right
    )
    $leftParts = ConvertTo-VersionParts $Left
    $rightParts = ConvertTo-VersionParts $Right
    for ($index = 0; $index -lt 4; $index++) {
        if ($leftParts[$index] -gt $rightParts[$index]) { return 1 }
        if ($leftParts[$index] -lt $rightParts[$index]) { return -1 }
    }
    return 0
}

function Get-PublishedReleaseVersion {
    param([Parameter(Mandatory)][string]$Uri)
    try {
        $response = Invoke-RestMethod -Method Get -Uri $Uri -TimeoutSec 15
        $envelope = $response.update_release
        if (-not $envelope -or -not $envelope.payload) { throw '线上尚无已发布版本' }
        $encoded = [string]$envelope.payload
        $base64 = $encoded.Replace('-', '+').Replace('_', '/')
        switch ($base64.Length % 4) {
            2 { $base64 += '==' }
            3 { $base64 += '=' }
            1 { throw '线上版本载荷格式无效' }
        }
        $json = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($base64))
        $release = $json | ConvertFrom-Json
        if ($release.product_id -ne 'replay_shrimp' -or $release.aud -ne 'replay_shrimp') {
            throw '线上版本产品标识无效'
        }
        return [string]$release.version
    }
    catch {
        throw "无法读取线上复盘虾版本，已在耗时编译前停止：$($_.Exception.Message)"
    }
}

if ([string]::IsNullOrWhiteSpace($PublishedVersion)) {
    $PublishedVersion = Get-PublishedReleaseVersion -Uri $Endpoint
}

if ((Compare-ReleaseVersion -Left $Version -Right $PublishedVersion) -le 0) {
    throw "构建版本 $Version 必须高于线上已发布版本 $PublishedVersion。版本按主版本.次版本.修订号逐段比较，例如 1.0.17 低于 1.1.14。"
}

Write-Host "版本预检通过：线上 $PublishedVersion -> 本次 $Version" -ForegroundColor Green
