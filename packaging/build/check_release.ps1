<#
  构建产物安全扫描。发现以下任一即【构建失败】(exit 1)：
    - 开发者 Cookie 文件 / 任意 cookie 令牌（ttwid/odin_tt）落进 json
    - 任意数据库 *.db
    - 任意音频 *.mp3 / *.wav
    - 日志 *.log、备份 *.bak、scratch/sample 临时件
    - AI 配置 / API Key
    - rooms.json（含开发房间清单）
    - audio/ 或 exports/ 里有遗留文件
    - 任意文本（除模型词表外）出现已知开发房间号

  用法: pwsh -File check_release.ps1 -Target <staging目录>
#>
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Target)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path $Target)) { Write-Error "扫描目标不存在: $Target"; exit 2 }
$root = (Resolve-Path $Target).Path
$violations = New-Object System.Collections.Generic.List[string]
function Add-V($m) { $violations.Add($m) }

# 已知开发房间号（出现在任何源码/配置/文本里都算泄漏）
$devRooms = @(
    "511237932901","58308379389","746953090945","741047106961","811505107233","567554942527","251928164584",
    "499025011911","51519965700","594109199563","615851362646","645268872452",
    "819606404524","831196721401","864764673788","886973330041"
)

# 禁止的文件名/扩展（任意层级）
$banName = @("browser_cookies.json","rooms.json","ai_config.json")
$banExt  = @(".db",".mp3",".wav",".log",".bak")
$banGlob = @("_scratch*","sample_*","*.db-wal","*.db-shm")

$allFiles = Get-ChildItem -Recurse -File -Force $root

foreach ($f in $allFiles) {
    $name = $f.Name
    $ext  = $f.Extension.ToLower()
    $rel  = $f.FullName.Substring($root.Length).TrimStart('\')

    if ($banName -contains $name) { Add-V "禁止文件: $rel" ; continue }
    if ($banExt  -contains $ext)  { Add-V "禁止扩展($ext): $rel" ; continue }
    foreach ($g in $banGlob) { if ($name -like $g) { Add-V "禁止临时件: $rel" ; break } }
}

# audio/ exports/ 不应有任何遗留文件（这俩是用户数据目录，安装包里绝不能带）
foreach ($d in @("app\audio","audio","app\exports","exports")) {
    $p = Join-Path $root $d
    if (Test-Path $p) {
        $n = (Get-ChildItem -Recurse -File -Force $p | Measure-Object).Count
        if ($n -gt 0) { Add-V "用户数据目录非空: $d ($n 个文件)" }
    }
}

# 文本内容扫描（跳过 models 词表/二进制；只看会带文本的源码与配置）
$textExt = @(".py",".js",".cjs",".json",".txt",".md",".csv",".cfg",".ini")
$modelsPrefix = (Join-Path $root "models").ToLower()
foreach ($f in $allFiles) {
    if ($textExt -notcontains $f.Extension.ToLower()) { continue }
    if ($f.FullName.ToLower().StartsWith($modelsPrefix)) { continue }  # 模型词表 tokens.txt 跳过
    $rel = $f.FullName.Substring($root.Length).TrimStart('\')
    $content = [System.IO.File]::ReadAllText($f.FullName)

    foreach ($rid in $devRooms) {
        if ($content -match [regex]::Escape($rid)) { Add-V "文本含开发房间号 $rid : $rel" }
    }
    if ($content -match "sk-[A-Za-z0-9_-]{12,}") {
        Add-V "文本疑似包含 AI API Key: $rel"
    }
    if ($content -match '"api_key"\s*:\s*"[^"]{6,}"') {
        Add-V "文本包含已填写 api_key: $rel"
    }
    # cookie 令牌只在 json 里查（.py 源码里出现 'ttwid' 是合法代码）
    if ($f.Extension.ToLower() -eq ".json") {
        foreach ($tok in @("ttwid","odin_tt","s_v_web_id")) {
            if ($content -match $tok) { Add-V "json 含 cookie 令牌 '$tok': $rel" }
        }
    }
}

Write-Host "扫描完成: $root  共 $($allFiles.Count) 个文件"
if ($violations.Count -gt 0) {
    Write-Host "`n安全扫描未通过，发现 $($violations.Count) 处问题：" -ForegroundColor Red
    $violations | ForEach-Object { Write-Host "  ✗ $_" -ForegroundColor Red }
    exit 1
}
Write-Host "安全扫描通过：未发现 Cookie / 数据库 / 音频 / 日志 / 开发房间号。" -ForegroundColor Green
exit 0
