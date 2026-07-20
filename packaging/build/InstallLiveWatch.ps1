<# 
  复盘虾在线安装器

  作用：
    1. 从官方 HTTPS 地址下载安装包。
    2. 校验 SHA256，避免半包、损坏文件或非官方文件。
    3. 校验通过后启动 Inno Setup 安装程序。

  说明：
    - 这个脚本不包含卡密、后台令牌、AI Key 或任何私钥。
    - Windows SmartScreen 对未签名 EXE 的信誉提示，最终仍需要受信任代码签名证书解决。
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "",
    [switch]$Silent,
    [switch]$KeepInstaller,
    [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

$Version = "1.0.2"
$InstallerUrl = "https://license.runmo.art/downloads/LiveWatchSetup_1.0.2.exe"
$ExpectedSha256 = "53D6E00CF285E1DE31E14FD57E4155B16B9D23A1482D14974DCA8A6503DF1F72"
$ExpectedBytes = 329330062

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==== $Message ====" -ForegroundColor Cyan
}

function Get-FileSha256([string]$Path) {
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Download-WithRetry([string]$Url, [string]$OutFile) {
    $attempts = 3
    for ($i = 1; $i -le $attempts; $i++) {
        try {
            if (Test-Path -LiteralPath $OutFile) {
                Remove-Item -LiteralPath $OutFile -Force
            }
            Write-Host "正在下载安装包（第 $i/$attempts 次）..."
            Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -TimeoutSec 1800
            return
        } catch {
            Write-Warning "下载失败：$($_.Exception.Message)"
            if ($i -eq $attempts) { throw }
            Start-Sleep -Seconds (3 * $i)
        }
    }
}

Write-Step "准备下载"
$downloadDir = Join-Path $env:TEMP "LiveWatchInstaller"
New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
$installer = Join-Path $downloadDir "LiveWatchSetup_$Version.exe"

Write-Host "版本: $Version"
Write-Host "来源: $InstallerUrl"
Write-Host "保存: $installer"

Write-Step "下载并校验"
Download-WithRetry -Url $InstallerUrl -OutFile $installer

$actualBytes = (Get-Item -LiteralPath $installer).Length
if ($actualBytes -ne $ExpectedBytes) {
    throw "安装包大小不正确：实际 $actualBytes 字节，期望 $ExpectedBytes 字节。请重新运行脚本。"
}

$actualSha = Get-FileSha256 -Path $installer
if ($actualSha -ne $ExpectedSha256) {
    throw "安装包校验失败：实际 $actualSha，期望 $ExpectedSha256。请不要运行该文件。"
}

Write-Host "安装包完整性校验通过。" -ForegroundColor Green

try {
    Unblock-File -Path $installer -ErrorAction SilentlyContinue
} catch {
    # Unblock-File 不影响安装完整性；某些系统策略下可能不可用。
}

if ($VerifyOnly) {
    Write-Host "VerifyOnly 已开启，仅完成下载校验，不启动安装。"
    exit 0
}

Write-Step "启动安装"
$args = @("/NORESTART")
if ($Silent) {
    $args += "/VERYSILENT"
}
if ($InstallDir.Trim()) {
    $args += "/DIR=`"$InstallDir`""
}

$proc = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    throw "安装程序退出码异常：$($proc.ExitCode)"
}

Write-Host "复盘虾安装完成。" -ForegroundColor Green

if (-not $KeepInstaller) {
    Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
}
