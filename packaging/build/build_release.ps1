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
    [string]$Version = "1.0.0",
    [switch]$Commercial,                    # 账号版商业加固：Nuitka 编译业务代码 + 账号权益验签
    [string]$AccountApiUrl = "https://anyq.site", # 手机号账号服务（仅 HTTPS）
    [string]$AccountPublicKey = "",         # account-v1 Ed25519 SPKI 公钥（不是私钥）
    [string]$UpdatePublicKey = "",          # update-v1 Ed25519 SPKI 公钥（不是私钥）
    [string]$AccountProductCode = "replay_shrimp",
    [string]$IntegrityPrivateKey = "",      # 可选：base64url Ed25519 私钥；留空则本次构建临时生成
    [string]$IntegrityPublicKey = "",       # 可选：base64url Ed25519 公钥；留空则随私钥推导/生成
    [string]$CodeSignThumbprint = "",       # 可选：Windows 证书存储中的代码签名证书指纹
    [string]$SignTool = ""                   # 可选：signtool.exe 路径；留空自动探测
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
$Guard     = Join-Path $ScriptDir "livewatch_guard.py"
$Assets    = Join-Path $ScriptDir "assets"
$SidecarVendorDir = Join-Path $ScriptDir "vendor\douyinlive"
$SidecarExe = Join-Path $SidecarVendorDir "douyinLive.exe"
$SidecarLicense = Join-Path $SidecarVendorDir "LICENSE"
$SidecarArchiveName = "douyinLive-v2.0.24-79453ece4a44-windows-amd64.zip"
$SidecarExeSha256 = "59cd585998393b16c0cbb8f2e4d7caa382a98c7ba7c2c67b40d57ddd60205062"
$IconFile  = Join-Path $Assets "icon-options\replay-shrimp.ico"
$IssFile   = Join-Path $ScriptDir "livewatch.iss"
$Checker   = Join-Path $ScriptDir "check_release.ps1"
$PythonChecker = Join-Path $ScriptDir "check_release.py"
$PlaywrightCache = Join-Path $env:LOCALAPPDATA "ms-playwright"

$Staging   = Join-Path $RepoRoot "staging\LiveWatch"
$TmpDist   = Join-Path $RepoRoot "staging\_pyi_dist"
$TmpWork   = Join-Path $RepoRoot "staging\_pyi_work"
$TmpNuitkaSource = Join-Path $RepoRoot "staging\_nuitka_source"
$TmpNuitkaOutput = Join-Path $RepoRoot "staging\_nuitka_output"
$TmpLauncherDir = Join-Path $RepoRoot "staging\_launcher_source"
$TmpLauncher = Join-Path $TmpLauncherDir "livewatch_launcher.py"
$TmpGuardDir = Join-Path $RepoRoot "staging\_guard_source"
$TmpGuardOutput = Join-Path $RepoRoot "staging\_guard_output"
$TmpGuard = Join-Path $TmpGuardDir "livewatch_guard.py"
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
foreach ($p in @($Route, $AsrModel, $SpkModel, $Launcher, $Guard, $Checker, $PythonChecker, $SidecarExe, $SidecarLicense)) {
    if (-not (Test-Path $p)) { throw "缺少构建输入: $p" }
}
$actualSidecarHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SidecarExe).Hash.ToLowerInvariant()
if ($actualSidecarHash -ne $SidecarExeSha256) {
    throw "互动 sidecar 校验失败：$SidecarArchiveName 的 douyinLive.exe SHA-256 不匹配"
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

if ($Commercial) {
    if ($AccountApiUrl -notmatch '^https://[^/\s]+(?:/[^\s]*)?$') {
        throw "商业构建必须提供 HTTPS 账号服务地址：-AccountApiUrl https://anyq.site"
    }
    if ($AccountPublicKey -notmatch '^[A-Za-z0-9_-]{40,128}$') {
        throw "商业构建必须提供 account-v1 base64url Ed25519 公钥：-AccountPublicKey <public-key>"
    }
    if ($UpdatePublicKey -notmatch '^[A-Za-z0-9_-]{40,128}$') {
        throw "商业构建必须提供 update-v1 base64url Ed25519 公钥：-UpdatePublicKey <public-key>"
    }
    if ($UpdatePublicKey -eq $AccountPublicKey) {
        throw "update-v1 必须使用独立于 account-v1 的 Ed25519 公钥"
    }
    if ($AccountProductCode -ne 'replay_shrimp') {
        throw "复盘虾商业包的账号产品码必须是 replay_shrimp"
    }
    & python -m nuitka --version
    if ($LASTEXITCODE -ne 0) {
        throw "商业构建需要 Nuitka。请执行：python -m pip install Nuitka"
    }
}

function Resolve-SignTool {
    if ($SignTool) {
        if (-not (Test-Path $SignTool)) { throw "SignTool 不存在: $SignTool" }
        return (Resolve-Path $SignTool).Path
    }
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    $sdkRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (Test-Path $sdkRoot) {
        $candidate = Get-ChildItem -Path $sdkRoot -Filter "signtool.exe" -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($candidate) { return $candidate.FullName }
    }
    throw "未找到 signtool.exe。请安装 Windows SDK，或用 -SignTool 指定路径。"
}

function Sign-ReleaseBinary {
    param([string]$FilePath)
    if (-not $CodeSignThumbprint) { return }
    if (-not $script:ResolvedSignTool) { $script:ResolvedSignTool = Resolve-SignTool }

    Write-Host "签名: $FilePath"
    & $script:ResolvedSignTool sign /sha1 $CodeSignThumbprint /fd SHA256 `
        /tr "http://timestamp.digicert.com" /td SHA256 /v $FilePath
    if ($LASTEXITCODE -ne 0) { throw "代码签名失败: $FilePath (exit=$LASTEXITCODE)" }

    $signature = Get-AuthenticodeSignature -FilePath $FilePath
    if ($signature.Status -ne "Valid") {
        throw "签名校验失败: $FilePath ($($signature.Status))"
    }
}

function Initialize-IntegritySigning {
    if ($IntegrityPrivateKey -and $IntegrityPublicKey) {
        if ($IntegrityPrivateKey -notmatch '^[A-Za-z0-9_-]{40,128}$' -or $IntegrityPublicKey -notmatch '^[A-Za-z0-9_-]{40,128}$') {
            throw "完整性签名密钥格式无效；请传入 base64url Ed25519 密钥，构建已中止。"
        }
        return @{ Private = $IntegrityPrivateKey; Public = $IntegrityPublicKey }
    }
    if ($env:LIVEWATCH_INTEGRITY_PRIVATE_KEY -and $env:LIVEWATCH_INTEGRITY_PUBLIC_KEY) {
        if ($env:LIVEWATCH_INTEGRITY_PRIVATE_KEY -notmatch '^[A-Za-z0-9_-]{40,128}$' -or $env:LIVEWATCH_INTEGRITY_PUBLIC_KEY -notmatch '^[A-Za-z0-9_-]{40,128}$') {
            throw "环境变量中的完整性签名密钥格式无效，构建已中止。"
        }
        return @{
            Private = $env:LIVEWATCH_INTEGRITY_PRIVATE_KEY
            Public = $env:LIVEWATCH_INTEGRITY_PUBLIC_KEY
        }
    }

    $oldPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = $Route
    try {
        $json = & python -c "from pipeline.integrity_manifest import generate_keypair; import json; private, public = generate_keypair(); print(json.dumps({'private': private, 'public': public}))"
        if ($LASTEXITCODE -ne 0) { throw "完整性签名密钥生成失败" }
        $pair = $json | ConvertFrom-Json
        if ([string]$pair.private -notmatch '^[A-Za-z0-9_-]{40,128}$' -or [string]$pair.public -notmatch '^[A-Za-z0-9_-]{40,128}$') {
            throw "生成的完整性签名密钥格式无效"
        }
        return @{ Private = [string]$pair.private; Public = [string]$pair.public }
    } finally {
        $env:PYTHONPATH = $oldPythonPath
    }
}

# ---------- 1. 空白 staging ----------
Write-Step "重建空白 staging"
foreach ($d in @($Staging, $TmpDist, $TmpWork, $TmpNuitkaSource, $TmpNuitkaOutput, $TmpLauncherDir, $TmpGuardDir, $TmpGuardOutput)) {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}
New-Item -ItemType Directory -Force -Path $Staging | Out-Null
$IntegrityKeys = Initialize-IntegritySigning
Write-Host "完整性签名：已为本次构建准备 Ed25519 公钥（私钥不写入安装包）。" -ForegroundColor Green
$AppDir = Join-Path $Staging "app"
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null

# ---------- 2. 程序源码（白名单拷贝，排除一切数据/缓存/样本） ----------
Write-Step "拷贝程序源码 (allowlist)"
# 不打包旧 AGPL WSS 内核。互动事件改由固定版本、MIT 许可的本地 sidecar 提供。
# 商业包把整个 pipeline 编译为单个 .pyd，只留下 HTML/CSS/JS 等公开前端资产。
if ($Commercial) {
    New-Item -ItemType Directory -Force -Path $TmpNuitkaSource, $TmpNuitkaOutput | Out-Null
    $NuitkaPipeline = Join-Path $TmpNuitkaSource "pipeline"
    Invoke-Robocopy (Join-Path $Route "pipeline") $NuitkaPipeline `
        @("/E", "/XD", "__pycache__", "/XF", "*.pyc")

    # 公钥可公开，私钥与卡密库仅存在授权服务器。运行配置必须在编译前写入临时副本。
    $RuntimeFile = Join-Path $NuitkaPipeline "license_runtime.py"
    $RuntimeCode = @"
"""Commercial account build settings. Generated during packaging."""
LICENSE_ENFORCE = False
LICENSE_SERVER_URL = ""
LICENSE_PUBLIC_KEY = ""
LICENSE_APP_VERSION = "$Version"
ACCOUNT_API_URL = "$AccountApiUrl"
ACCOUNT_PUBLIC_KEY = "$AccountPublicKey"
ACCOUNT_PRODUCT_CODE = "$AccountProductCode"
UPDATE_PUBLIC_KEY = "$UpdatePublicKey"
"@
    [System.IO.File]::WriteAllText($RuntimeFile, $RuntimeCode, [System.Text.UTF8Encoding]::new($false))

    Write-Host "Nuitka 编译商业业务模块（首次下载 Zig 编译器后会更快）"
    Push-Location $TmpNuitkaSource
    try {
        # 打包机通常还会运行其他产品的构建；限制为单编译任务，避免 Zig/Scons 耗尽分页文件。
        & python -m nuitka --mode=package --include-package=pipeline --assume-yes-for-downloads --zig `
            --low-memory --jobs=1 --lto=no --no-pyi-file --output-dir=$TmpNuitkaOutput $NuitkaPipeline
        if ($LASTEXITCODE -ne 0) { throw "Nuitka 编译 pipeline 失败 exit=$LASTEXITCODE" }
    } finally {
        Pop-Location
    }
    $CompiledPipeline = Get-ChildItem $TmpNuitkaOutput -Filter "pipeline*.pyd" | Select-Object -First 1
    if (-not $CompiledPipeline) { throw "Nuitka 未产出 pipeline 二进制模块" }
    Copy-Item $CompiledPipeline.FullName (Join-Path $AppDir $CompiledPipeline.Name) -Force

    $PipelineData = Join-Path $AppDir "pipeline_data"
    New-Item -ItemType Directory -Force -Path $PipelineData | Out-Null
    Copy-Item (Join-Path $NuitkaPipeline "frontend.html") (Join-Path $PipelineData "frontend.html") -Force
    Invoke-Robocopy (Join-Path $NuitkaPipeline "static") (Join-Path $PipelineData "static") @("/E")
    $LexiconData = Join-Path $PipelineData "lexicons"
    New-Item -ItemType Directory -Force -Path $LexiconData | Out-Null
    Copy-Item (Join-Path $NuitkaPipeline "lexicons\sensitive_regex_seed.json") (Join-Path $LexiconData "sensitive_regex_seed.json") -Force
    Copy-Item (Join-Path $NuitkaPipeline "lexicons\yunyingxia_forbidden_words.v1.json") (Join-Path $LexiconData "yunyingxia_forbidden_words.v1.json") -Force
    Write-Host "商业账号与更新验签已启用：业务代码已编译为二进制模块，安装包仅含 account-v1 / update-v1 公钥。" -ForegroundColor Green
} else {
    Invoke-Robocopy (Join-Path $Route "pipeline") (Join-Path $AppDir "pipeline") `
        @("/E", "/XD", "__pycache__", "/XF", "*.pyc")
}
Write-Host "互动事件：内置 MIT douyinLive sidecar；桌面端默认使用 sidecar 后端。" -ForegroundColor Green

# ---------- 3. 内置 node、互动 sidecar 与模型 ----------
Write-Step "内置 node、互动 sidecar 与模型"
New-Item -ItemType Directory -Force -Path (Join-Path $AppDir "bin") | Out-Null
Copy-Item $NodeExe (Join-Path $AppDir "bin\node.exe") -Force
$SidecarDir = Join-Path $AppDir "sidecar"
New-Item -ItemType Directory -Force -Path $SidecarDir | Out-Null
Copy-Item $SidecarExe (Join-Path $SidecarDir "douyinLive.exe") -Force
Sign-ReleaseBinary (Join-Path $SidecarDir "douyinLive.exe")

$ModelsDir = Join-Path $Staging "models"
Invoke-Robocopy $AsrModel (Join-Path $ModelsDir "sensevoice_onnx") @("/E")
Invoke-Robocopy $SpkModel (Join-Path $ModelsDir "speaker") @("/E")

# 不内置任何浏览器二进制（原来 Chromium + headless_shell 约 650MB）：
#   · 铸 cookie 用目标机系统自带的 Edge（browser_cookies 已优先 channel=msedge）。
#   · 待开播主页探测已下线，不再需要 headless_shell。
# 包体由此瘦约 650MB。

# ---------- 4. PyInstaller 打包桌面客户端 ----------
Write-Step "PyInstaller 打包桌面客户端"
New-Item -ItemType Directory -Force -Path $TmpLauncherDir | Out-Null
$LauncherCode = [System.IO.File]::ReadAllText($Launcher, [System.Text.Encoding]::UTF8)
$LauncherCode = $LauncherCode.Replace("__LIVEWATCH_INTEGRITY_PUBLIC_KEY__", $IntegrityKeys.Public)
[System.IO.File]::WriteAllText($TmpLauncher, $LauncherCode, [System.Text.UTF8Encoding]::new($false))
python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name LiveWatchLauncher `
    --icon $IconFile `
    --distpath $TmpDist --workpath $TmpWork --specpath $TmpWork `
    --collect-all sherpa_onnx `
    --collect-all playwright `
    --collect-all imageio_ffmpeg `
    --collect-all jieba `
    --collect-all reportlab `
    --collect-all webview `
    --collect-all pystray `
    --hidden-import cryptography.hazmat.primitives.asymmetric.ed25519 `
    --hidden-import cryptography.hazmat.primitives.ciphers.aead `
    $TmpLauncher
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败 exit=$LASTEXITCODE" }

# 把 onedir 产物（exe + _internal）搬到 staging 根
$PyiOut = Join-Path $TmpDist "LiveWatchLauncher"
if (-not (Test-Path (Join-Path $PyiOut "LiveWatchLauncher.exe"))) { throw "未找到 PyInstaller 产物 exe" }
Invoke-Robocopy $PyiOut $Staging @("/E")
Sign-ReleaseBinary (Join-Path $Staging "LiveWatchLauncher.exe")

# ---------- 4.5 编译独立完整性 Guard ----------
# Guard 与主启动器分离：先验证 Ed25519 签名清单及核心文件哈希，再启动 Launcher。
# 用户数据、导出目录、Cookie、数据库均不在 Guard 校验范围内。
Write-Step "Nuitka 编译完整性 Guard"
New-Item -ItemType Directory -Force -Path $TmpGuardDir, $TmpGuardOutput | Out-Null
$GuardCode = [System.IO.File]::ReadAllText($Guard, [System.Text.Encoding]::UTF8)
$GuardCode = $GuardCode.Replace("__LIVEWATCH_INTEGRITY_PUBLIC_KEY__", $IntegrityKeys.Public)
[System.IO.File]::WriteAllText($TmpGuard, $GuardCode, [System.Text.UTF8Encoding]::new($false))
& python -m nuitka --onefile --assume-yes-for-downloads --windows-console-mode=disable `
    --output-dir=$TmpGuardOutput --output-filename=LiveWatchGuard.exe $TmpGuard
if ($LASTEXITCODE -ne 0) { throw "Nuitka 编译完整性 Guard 失败 exit=$LASTEXITCODE" }
$CompiledGuard = Get-ChildItem $TmpGuardOutput -Recurse -Filter "LiveWatchGuard.exe" | Select-Object -First 1
if (-not $CompiledGuard) { throw "Nuitka 未产出 LiveWatchGuard.exe" }
Copy-Item $CompiledGuard.FullName (Join-Path $Staging "LiveWatchGuard.exe") -Force
Sign-ReleaseBinary (Join-Path $Staging "LiveWatchGuard.exe")

# ---------- 5. 文档 ----------
Write-Step "拷贝文档"
if (Test-Path (Join-Path $Assets "README_使用说明.md")) {
    Copy-Item (Join-Path $Assets "README_使用说明.md") (Join-Path $Staging "README_使用说明.md") -Force
}
if (Test-Path (Join-Path $Assets "COMMERCIAL_NOTICE.txt")) {
    Copy-Item (Join-Path $Assets "COMMERCIAL_NOTICE.txt") (Join-Path $Staging "COMMERCIAL_NOTICE.txt") -Force
}
$ThirdPartyNotices = Join-Path $Route "THIRD_PARTY_NOTICES.md"
if (Test-Path $ThirdPartyNotices) {
    Copy-Item $ThirdPartyNotices (Join-Path $Staging "THIRD_PARTY_NOTICES.md") -Force
}
Copy-Item $SidecarLicense (Join-Path $Staging "LICENSE.douyinLive.txt") -Force

# ---------- 5.5 完整性清单 ----------
Write-Step "生成完整性清单"
$env:PYTHONPATH = $Route
$env:LIVEWATCH_INTEGRITY_PRIVATE_KEY = $IntegrityKeys.Private
$env:LIVEWATCH_INTEGRITY_PUBLIC_KEY = $IntegrityKeys.Public
& python -c "from pathlib import Path; from pipeline import integrity_manifest; integrity_manifest.write_and_verify(Path(r'$Staging'))"
if ($LASTEXITCODE -ne 0) { throw "完整性清单生成失败，构建中止。" }
$env:LIVEWATCH_INTEGRITY_PRIVATE_KEY = $null

# 清理 PyInstaller 临时
Remove-Item -Recurse -Force $TmpDist, $TmpWork, $TmpNuitkaSource, $TmpNuitkaOutput, $TmpLauncherDir, $TmpGuardDir, $TmpGuardOutput -ErrorAction SilentlyContinue

# ---------- 6. 安全扫描 ----------
Write-Step "构建产物安全扫描"
& pwsh -NoProfile -File $Checker -Target $Staging
if ($LASTEXITCODE -ne 0) { throw "安全扫描未通过，构建中止。" }
if ($Commercial) {
    & python $PythonChecker $Staging --commercial
} else {
    & python $PythonChecker $Staging
}
if ($LASTEXITCODE -ne 0) { throw "Python 安全扫描未通过，构建中止。" }

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
$isccArgs = @(
    "/DAppVersion=$Version",
    "/DStagingDir=$Staging",
    "/DOutputDir=$ReleaseOut"
)
if ($CodeSignThumbprint) {
    # Inno must sign while compiling so the embedded uninstaller is signed too.
    # $q and $f are Inno SignTool placeholders, deliberately left literal here.
    if (-not $script:ResolvedSignTool) { $script:ResolvedSignTool = Resolve-SignTool }
    $innoSignCommand = '$q' + $script:ResolvedSignTool + '$q sign /sha1 ' + $CodeSignThumbprint +
        ' /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /v $f'
    $isccArgs += "/DInnoSignTool=1"
    $isccArgs += "/Slivewatch=$innoSignCommand"
}
& $Iscc @isccArgs $IssFile
if ($LASTEXITCODE -ne 0) { throw "ISCC 编译失败 exit=$LASTEXITCODE" }

$setup = Get-ChildItem $ReleaseOut -Filter "LiveWatchSetup*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($setup) {
    if ($CodeSignThumbprint) {
        # 安装器已由 ISCC 签名；这里只验签，避免二次签名破坏内嵌卸载器签名流程。
        $signature = Get-AuthenticodeSignature -FilePath $setup.FullName
        if ($signature.Status -ne "Valid") {
            throw "安装程序签名校验失败: $($setup.FullName) ($($signature.Status))"
        }
    }
    Write-Step "完成"
    Write-Host ("安装程序: {0}" -f $setup.FullName)
    Write-Host ("大小:     {0:N1} MB" -f ($setup.Length / 1MB))
}
