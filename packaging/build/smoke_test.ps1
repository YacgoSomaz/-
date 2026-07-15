<#
  全新目录安装冒烟测试。把 staging 当作安装产物，复制到一个全新目录里（模拟"装到干净路径"），
  指定一个全新外部数据目录启动真正的 LiveWatchLauncher.exe，验证：
    1. 后端起得来（端口监听、控制台首页 200）
    2. 模型从安装目录\models 解析、数据落到外部数据目录（程序/数据分离）
    3. 数据目录确实被创建并写了 logs / audio / exports
    4. 覆盖升级（重灌安装目录）后外部数据原样保留

  用法: pwsh -File smoke_test.ps1
#>
[CmdletBinding()]
param(
    [int]$Port = 8853,
    [string]$Staging = ""
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
if (-not $Staging) { $Staging = Join-Path $RepoRoot "staging\LiveWatch" }
if (-not (Test-Path (Join-Path $Staging "LiveWatchLauncher.exe"))) { throw "未找到 staging 产物，请先构建: $Staging" }

$work    = Join-Path ([System.IO.Path]::GetTempPath()) ("lw_smoke_" + [guid]::NewGuid().ToString("N").Substring(0,8))
$install = Join-Path $work "install"
$data    = Join-Path $work "data"
$fail = 0
$proc = $null
$proc2 = $null
function Check($name, $cond) {
    if ($cond) { Write-Host "  [PASS] $name" -ForegroundColor Green }
    else { Write-Host "  [FAIL] $name" -ForegroundColor Red; $script:fail++ }
}

function Wait-Port($p, $timeoutSec) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $timeoutSec) {
        $c = Test-NetConnection -ComputerName 127.0.0.1 -Port $p -WarningAction SilentlyContinue
        if ($c.TcpTestSucceeded) { return $true }
        Start-Sleep -Milliseconds 800
    }
    return $false
}

function Start-App() {
    $env:LIVEWATCH_DATA_DIR = $data
    $env:LIVEWATCH_PORT = "$Port"
    Remove-Item Env:LIVEWATCH_RESOURCE_DIR -ErrorAction SilentlyContinue  # 用安装目录\models 默认解析
    return Start-Process -FilePath (Join-Path $install "LiveWatchLauncher.exe") `
        -WorkingDirectory $install -PassThru -WindowStyle Hidden
}

function Stop-App($proc) {
    if ($proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}

try {
    Write-Host "`n==== 准备全新安装目录 ====" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $install | Out-Null
    robocopy $Staging $install /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "复制 staging 到安装目录失败" }
    $global:LASTEXITCODE = 0
    Check "全新安装目录含 LiveWatchLauncher.exe" (Test-Path (Join-Path $install "LiveWatchLauncher.exe"))
    Check "安装目录含 models\sensevoice_onnx\model.int8.onnx" (Test-Path (Join-Path $install "models\sensevoice_onnx\model.int8.onnx"))
    Check "安装目录含 models\speaker\3dspeaker_eres2net_zh_16k.onnx" (Test-Path (Join-Path $install "models\speaker\3dspeaker_eres2net_zh_16k.onnx"))
    Check "安装目录含 app\bin\node.exe" (Test-Path (Join-Path $install "app\bin\node.exe"))
    $compiledPipeline = @(Get-ChildItem (Join-Path $install "app") -Filter "pipeline*.pyd" -ErrorAction SilentlyContinue).Count -gt 0
    $sourcePipeline = (Test-Path (Join-Path $install "app\pipeline\diagnostics.py")) -and `
        (Test-Path (Join-Path $install "app\pipeline\runtime_health.py")) -and `
        (Test-Path (Join-Path $install "app\pipeline\speaker_worker.py"))
    Check "安装目录含已编译或源码业务模块" ($compiledPipeline -or $sourcePipeline)
    Check "外部数据目录此刻尚不存在(干净起步)" (-not (Test-Path $data))

    Write-Host "`n==== 首次启动 ====" -ForegroundColor Cyan
    $proc = Start-App
    $up = Wait-Port $Port 60
    Check "后端端口 $Port 监听成功" $up
    if ($up) {
        try { $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -TimeoutSec 10 -UseBasicParsing; $code = $resp.StatusCode } catch { $code = 0 }
        Check "控制台首页返回 200" ($code -eq 200)
        try {
            $diag = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/diagnostics" -TimeoutSec 10
            $diagOk = ($null -ne $diag.cookie.state) -and $diag.models.ready -and ($null -ne $diag.recent_errors)
        } catch { $diagOk = $false }
        Check "诊断接口可用且模型就绪" $diagOk
    }
    Start-Sleep -Seconds 2
    Check "外部数据目录已创建" (Test-Path $data)
    Check "数据目录\logs 已建" (Test-Path (Join-Path $data "logs"))
    Check "数据目录\audio 已建" (Test-Path (Join-Path $data "audio"))
    Check "数据目录\exports 已建" (Test-Path (Join-Path $data "exports"))
    Check "控制台日志已落盘" ((Get-ChildItem (Join-Path $data "logs") -Filter *.log -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0)
    Check "安装目录内未生成任何数据库(数据未污染程序目录)" ((Get-ChildItem $install -Recurse -Filter *.db -ErrorAction SilentlyContinue | Measure-Object).Count -eq 0)

    # 写一个标记进数据目录，验证升级保留
    $marker = Join-Path $data "rooms.json"
    Set-Content -Path $marker -Value '["000000000001"]' -Encoding UTF8
    Stop-App $proc
    Start-Sleep -Seconds 2

    Write-Host "`n==== 覆盖升级（重灌安装目录，数据目录不动） ====" -ForegroundColor Cyan
    robocopy $Staging $install /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "覆盖安装失败" }
    $global:LASTEXITCODE = 0
    Check "升级后外部数据(rooms.json)仍在" (Test-Path $marker)
    Check "升级后数据库等用户文件未被安装覆盖删除" (Test-Path (Join-Path $data "logs"))

    $proc2 = Start-App
    $up2 = Wait-Port $Port 60
    Check "升级后再次启动成功" $up2
    Check "升级后 rooms.json 内容保留" ((Get-Content $marker -Raw).Contains("000000000001"))
    Stop-App $proc2
}
finally {
    Stop-App $proc
    Stop-App $proc2
    Start-Sleep -Seconds 1
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
    Remove-Item Env:LIVEWATCH_DATA_DIR, Env:LIVEWATCH_PORT -ErrorAction SilentlyContinue
}

Write-Host ""
if ($fail -eq 0) { Write-Host "冒烟测试全部通过 ✅" -ForegroundColor Green; exit 0 }
else { Write-Host "冒烟测试有 $fail 项失败 ❌" -ForegroundColor Red; exit 1 }
