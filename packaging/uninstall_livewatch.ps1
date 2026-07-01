$ErrorActionPreference = "SilentlyContinue"
$installDir = Join-Path $env:LOCALAPPDATA "LiveWatch"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "直播复盘侠.lnk"

Remove-Item -LiteralPath $shortcutPath -Force
Write-Host "Desktop shortcut removed."
Write-Host "Install dir is kept: $installDir"
Write-Host "To fully remove 直播复盘侠, manually delete that folder; it may contain audio, exports, and databases."
Read-Host "Press Enter to exit"


