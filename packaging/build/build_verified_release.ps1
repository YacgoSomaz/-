<#
  本机正式发包入口（复盘虾）。

  只使用公开的账号 / 更新验签公钥；不读取、保存或生成服务器私钥、OSS 密钥、Cookie。
  每次从干净 staging 重建，商业编译与发布扫描失败会直接停止。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Version,
    [string]$AccountApiUrl = 'https://anyq.site',
    [string]$AccountPublicKey = '',
    [string]$UpdatePublicKey = '',
    [string]$NodeExe = '',
    [string]$Iscc = '',
    [string]$CodeSignThumbprint = '',
    [string]$SignTool = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir '..\..')).Path
$BuildScript = Join-Path $ScriptDir 'build_release.ps1'
$ReleaseScanner = Join-Path $ScriptDir 'check_release.ps1'
$VersionGuard = Join-Path $ScriptDir 'version_guard.ps1'
$Staging = Join-Path $RepoRoot 'staging\LiveWatch'
$ReleaseDir = Join-Path $RepoRoot 'release'

if ($Version -notmatch '^\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?$') {
    throw 'Version 必须是例如 1.0.13 的版本号。'
}
& pwsh -NoProfile -File $VersionGuard -Version $Version
if ($LASTEXITCODE -ne 0) { throw '版本预检失败，已在耗时编译前停止。' }
if ($AccountApiUrl -notmatch '^https://[^/\s]+(?:/[^\s]*)?$') {
    throw 'AccountApiUrl 必须是 HTTPS 地址。'
}

# 这是公开验签材料，写入客户端是预期行为；私钥只在 anyq.site 服务器环境变量中。
if (-not $AccountPublicKey) { $AccountPublicKey = $env:LIVEWATCH_ACCOUNT_PUBLIC_KEY }
if (-not $AccountPublicKey) { $AccountPublicKey = 'MCowBQYDK2VwAyEACqLAEE2KnduTFtw1gVQIExS1qLRa-XI3TaWpbchMbKc' }
if (-not $UpdatePublicKey) { $UpdatePublicKey = $env:LIVEWATCH_UPDATE_PUBLIC_KEY }
if (-not $UpdatePublicKey) { $UpdatePublicKey = 'MCowBQYDK2VwAyEAlYg7Ws_9MxeQYmSVP6SNJ8ZgRh1isI8mv_SwIrP7eZ4' }

foreach ($key in @($AccountPublicKey, $UpdatePublicKey)) {
    if ($key -notmatch '^[A-Za-z0-9_-]{40,128}$') { throw '账号或更新验签公钥格式无效。' }
}
if ($AccountPublicKey -eq $UpdatePublicKey) { throw '账号公钥与更新公钥必须独立。' }

function Resolve-LocalNodeExe {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        if (-not (Test-Path -LiteralPath $RequestedPath)) {
            throw "node.exe 不存在: $RequestedPath"
        }
        return (Resolve-Path -LiteralPath $RequestedPath).Path
    }

    $candidates = [System.Collections.Generic.List[string]]::new()
    $command = Get-Command node -ErrorAction SilentlyContinue
    if ($command -and $command.Source) { $candidates.Add($command.Source) }

    foreach ($path in @(
        (Join-Path $env:ProgramFiles 'nodejs\node.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'nodejs\node.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\nodejs\node.exe'),
        (Join-Path $env:LOCALAPPDATA 'Volta\bin\node.exe')
    )) {
        if ($path) { $candidates.Add($path) }
    }
    foreach ($drive in Get-PSDrive -PSProvider FileSystem) {
        $candidates.Add((Join-Path $drive.Root 'node.exe'))
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw '未找到 node.exe。请安装 Node 或用 -NodeExe 指定 node.exe。'
}

$NodeExe = Resolve-LocalNodeExe -RequestedPath $NodeExe
Write-Host "node.exe 来源: $NodeExe"

Write-Host "`n==== 构建复盘虾 $Version ====" -ForegroundColor Cyan
$buildArgs = @{
    Commercial = $true
    Version = $Version
    AccountApiUrl = $AccountApiUrl
    AccountPublicKey = $AccountPublicKey
    UpdatePublicKey = $UpdatePublicKey
    AccountProductCode = 'replay_shrimp'
    NodeExe = $NodeExe
}
if ($Iscc) { $buildArgs.Iscc = $Iscc }
if ($CodeSignThumbprint) { $buildArgs.CodeSignThumbprint = $CodeSignThumbprint }
if ($SignTool) { $buildArgs.SignTool = $SignTool }

& $BuildScript @buildArgs
if ($LASTEXITCODE -ne 0) { throw "构建失败，退出码: $LASTEXITCODE" }

Write-Host "`n==== 复跑发布扫描 ====" -ForegroundColor Cyan
& $ReleaseScanner -Target $Staging
if ($LASTEXITCODE -ne 0) { throw "发布扫描失败，退出码: $LASTEXITCODE" }

$installer = Join-Path $ReleaseDir "LiveWatchSetup_$Version.exe"
if (-not (Test-Path $installer)) { throw "未找到安装包: $installer" }
$item = Get-Item $installer
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash.ToLowerInvariant()
$signature = Get-AuthenticodeSignature -LiteralPath $installer
if ($CodeSignThumbprint -and $signature.Status -ne 'Valid') {
    throw "代码签名校验失败: $($signature.Status)"
}
if (-not $CodeSignThumbprint) {
    Write-Warning "安装包尚未进行 Windows 代码签名（当前状态：$($signature.Status)）。"
}

$objectKey = "replay-shrimp/$Version/LiveWatchSetup_$Version.exe"
$manifest = [ordered]@{
    product_id = 'replay_shrimp'
    version = $Version
    installer_path = $installer
    installer_url = "https://download.anyq.site/$objectKey"
    object_key = $objectKey
    sha256 = $hash
    size_bytes = [int64]$item.Length
    authenticode_status = [string]$signature.Status
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
}
$manifestPath = Join-Path $ReleaseDir "LiveWatchSetup_$Version.release.json"
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8

Write-Host "`n==== 可发布产物 ====" -ForegroundColor Green
Write-Host "安装包 : $installer"
Write-Host "SHA-256 : $hash"
Write-Host "大小    : $($item.Length) bytes"
Write-Host "清单    : $manifestPath"
Write-Host '下一步：登录 https://anyq.site/admin/releases，上传该安装包并在后台签名发布。'
