<#
  LiveWatch 一键可重复构建脚本（Windows / PowerShell 7+）。

  做什么：
    1. 每次从【空白 staging】重建，绝不手工复制。
    2. 用白名单把 douyin_worker_route 的【程序源码】拷进 staging\app（排除一切用户数据/缓存/样本）。
    3. 内置 node.exe、SenseVoice 模型、3D-Speaker 模型。
    4. PyInstaller 打包启动器（自带 Python、FFmpeg、各依赖）到 staging 根。
    5. 跑 check_release.ps1 安全扫描——发现 Cookie/库/音频/开发房间号立即失败。
    6. 调 Inno Setup(ISCC) 产出最终安装程序 .exe。

  用法：
    pwsh -File packaging\build\build_release.ps1
    可选参数见下方 param。
#>
[CmdletBinding()]
param(
    [string]$NodeExe = "",                 # 内置 node.exe 来源；留空则用系统 node
    [string]$Iscc = "",                    # ISCC.exe 路径；留空则自动探测
    [switch]$SkipInstaller,                # 只产 staging，不编译安装程序
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# ---------- 路径 ----------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$Route     = Join-Path $RepoRoot "_experiments\douyin_worker_route"
$AsrModel  = Join-Path $RepoRoot "_experiments\asr_bench\sensevoice_onnx"
$SpkModel  = Join-Path $RepoRoot "_experiments\speaker_change_analysis\models"
$Launcher  = Join-Path $ScriptDir "livewatch_launcher.py"
$Assets    = Join-Path $ScriptDir "assets"
$IssFile   = Join-Path $ScriptDir "livewatch.iss"
$Checker   = Join-Path $ScriptDir "check_release.ps1"
$PlaywrightCache = Join-Path $env:LOCALAPPDATA "ms-playwright"

$Staging   = Join-Path $RepoRoot "staging\LiveWatch"
$TmpDist   = Join-Path $RepoRoot "staging\_pyi_dist"
$TmpWork   = Join-Path $RepoRoot "staging\_pyi_work"
$ReleaseOut= Join-Path $RepoRoot "release"

function Write-Step($msg) { Write-Host "`n==== $msg ====" -ForegroundColor Cyan }

function Invoke-Robocopy {
    param([string]$Src, [string]$Dst, [string[]]$Extra)
    $args = @($Src, $Dst) + $Extra + @("/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1")
    robocopy @args | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy 失败 ($Src -> $Dst) exit=$LASTEXITCODE" }
    $global:LASTEXITCODE = 0
}

# ---------- 0. 前置检查 ----------
Write-Step "前置检查"
foreach ($p in @($Route, $AsrModel, $SpkModel, $Launcher)) {
    if (-not (Test-Path $p)) { throw "缺少构建输入: $p" }
}
# 不再内置 Chromium：铸 cookie 用目标机系统自带的 Edge（Win10/11 必装），故无需 Playwright 浏览器缓存。
if (-not (Test-Path (Join-Path $AsrModel "model.int8.onnx"))) { throw "缺少 SenseVoice 模型" }
if (-not (Test-Path (Join-Path $SpkModel "3dspeaker_eres2net_zh_16k.onnx"))) { throw "缺少 3D-Speaker 模型" }

if (-not $NodeExe) {
    $sys = Get-Command node -ErrorAction SilentlyContinue
    if (-not $sys) { throw "未找到 node。请安装 Node 或用 -NodeExe 指定 node.exe" }
    $NodeExe = $sys.Source
}
if (-not (Test-Path $NodeExe)) { throw "node.exe 不存在: $NodeExe" }
Write-Host "node.exe 来源: $NodeExe"

# ---------- 1. 空白 staging ----------
Write-Step "重建空白 staging"
foreach ($d in @($Staging, $TmpDist, $TmpWork)) {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}
New-Item -ItemType Directory -Force -Path $Staging | Out-Null
$AppDir = Join-Path $Staging "app"
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null

# ---------- 2. 程序源码（白名单拷贝，排除一切数据/缓存/样本） ----------
Write-Step "拷贝程序源码 (allowlist)"
# pipeline：只要 .py。legacy vendor/run_worker 不再进入安装包。
Invoke-Robocopy (Join-Path $Route "pipeline") (Join-Path $AppDir "pipeline") `
    @("/E", "/XD", "__pycache__", "/XF", "*.pyc")
Write-Host "安全模式：不打包旧 AGPL WSS 内核；桌面端默认使用 audio_only 后端。" -ForegroundColor Green

# ---------- 3. 内置 node + 模型 ----------
Write-Step "内置 node 与模型"
New-Item -ItemType Directory -Force -Path (Join-Path $AppDir "bin") | Out-Null
Copy-Item $NodeExe (Join-Path $AppDir "bin\node.exe") -Force

$ModelsDir = Join-Path $Staging "models"
Invoke-Robocopy $AsrModel (Join-Path $ModelsDir "sensevoice_onnx") @("/E")
Invoke-Robocopy $SpkModel (Join-Path $ModelsDir "speaker") @("/E")

# 不内置任何浏览器二进制（原来 Chromium + headless_shell 约 650MB）：
#   · 铸 cookie 用目标机系统自带的 Edge（browser_cookies 已优先 channel=msedge）。
#   · 待开播主页探测已下线，不再需要 headless_shell。
# 包体由此瘦约 650MB。

# ---------- 4. PyInstaller 打包桌面客户端 ----------
Write-Step "PyInstaller 打包桌面客户端"
python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name LiveWatchLauncher `
    --distpath $TmpDist --workpath $TmpWork --specpath $TmpWork `
    --collect-all sherpa_onnx `
    --collect-all playwright `
    --collect-all imageio_ffmpeg `
    --collect-all jieba `
    --collect-all reportlab `
    --collect-all webview `
    --collect-all pystray `
    $Launcher
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败 exit=$LASTEXITCODE" }

# 把 onedir 产物（exe + _internal）搬到 staging 根
$PyiOut = Join-Path $TmpDist "LiveWatchLauncher"
if (-not (Test-Path (Join-Path $PyiOut "LiveWatchLauncher.exe"))) { throw "未找到 PyInstaller 产物 exe" }
Invoke-Robocopy $PyiOut $Staging @("/E")

# ---------- 5. 文档 ----------
Write-Step "拷贝文档"
if (Test-Path (Join-Path $Assets "README_使用说明.md")) {
    Copy-Item (Join-Path $Assets "README_使用说明.md") (Join-Path $Staging "README_使用说明.md") -Force
}
$ThirdPartyNotices = Join-Path $Route "THIRD_PARTY_NOTICES.md"
if (Test-Path $ThirdPartyNotices) {
    Copy-Item $ThirdPartyNotices (Join-Path $Staging "THIRD_PARTY_NOTICES.md") -Force
}

# 清理 PyInstaller 临时
Remove-Item -Recurse -Force $TmpDist, $TmpWork -ErrorAction SilentlyContinue

# ---------- 6. 安全扫描 ----------
Write-Step "构建产物安全扫描"
& pwsh -NoProfile -File $Checker -Target $Staging
if ($LASTEXITCODE -ne 0) { throw "安全扫描未通过，构建中止。" }

# staging 体积
$size = (Get-ChildItem -Recurse $Staging | Measure-Object Length -Sum).Sum
Write-Host ("staging 未压缩体积: {0:N1} MB" -f ($size / 1MB))

# ---------- 7. Inno Setup 编译 ----------
if ($SkipInstaller) {
    Write-Step "跳过安装程序编译 (-SkipInstaller)"
    Write-Host "staging 就绪: $Staging"
    return
}

Write-Step "Inno Setup 编译安装程序"
if (-not $Iscc) {
    $cands = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    $Iscc = $cands | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Iscc) {
        $c = Get-Command iscc -ErrorAction SilentlyContinue
        if ($c) { $Iscc = $c.Source }
    }
}
if (-not $Iscc -or -not (Test-Path $Iscc)) { throw "未找到 ISCC.exe，请安装 Inno Setup 或用 -Iscc 指定" }

New-Item -ItemType Directory -Force -Path $ReleaseOut | Out-Null
& $Iscc "/DAppVersion=$Version" "/DStagingDir=$Staging" "/DOutputDir=$ReleaseOut" $IssFile
if ($LASTEXITCODE -ne 0) { throw "ISCC 编译失败 exit=$LASTEXITCODE" }

$setup = Get-ChildItem $ReleaseOut -Filter "LiveWatchSetup*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($setup) {
    Write-Step "完成"
    Write-Host ("安装程序: {0}" -f $setup.FullName)
    Write-Host ("大小:     {0:N1} MB" -f ($setup.Length / 1MB))
}
