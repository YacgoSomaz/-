$ErrorActionPreference = "Stop"

$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$installDir = Join-Path $env:LOCALAPPDATA "LiveWatch"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "直播复盘侠.lnk"

Write-Host ""
Write-Host "直播复盘侠本地安装"
Write-Host "----------------------------------------"
Write-Host "Source: $source"
Write-Host "Install dir: $installDir"

if (!(Test-Path $installDir)) {
  New-Item -ItemType Directory -Path $installDir | Out-Null
}

# Copy/upgrade program files, but keep user data from previous installs.
robocopy $source $installDir /E /XD "__pycache__" "audio" "exports" /XF "*.bak_*" "rooms.json" "transcripts.db" "multi_events.db" "cookies.json" "_diag.log" | Out-Null
if ($LASTEXITCODE -gt 7) {
  throw "Copy failed, robocopy exit code: $LASTEXITCODE"
}

$exe = Join-Path $installDir "LiveWatchLauncher.exe"
if (!(Test-Path $exe)) {
  throw "Launcher not found: $exe"
}

$appDir = Join-Path $installDir "app"
New-Item -ItemType Directory -Path (Join-Path $appDir "audio") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $appDir "exports") -Force | Out-Null
$roomsPath = Join-Path $appDir "rooms.json"
if (!(Test-Path $roomsPath)) {
  Set-Content -LiteralPath $roomsPath -Value "[]" -Encoding UTF8
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = $installDir
$shortcut.WindowStyle = 1
$shortcut.Description = "启动直播复盘侠"
$shortcut.Save()

Write-Host ""
Write-Host "Install completed. Desktop shortcut:"
Write-Host $shortcutPath
Write-Host ""
Write-Host "Double click the shortcut to start. Browser will open http://127.0.0.1:8848"
Write-Host ""
Read-Host "Press Enter to exit"


