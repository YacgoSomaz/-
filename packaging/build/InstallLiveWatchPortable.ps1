param(
  [string]$InstallDir = "$env:LOCALAPPDATA\Programs\LiveWatch",
  [switch]$NoShortcut,
  [switch]$NoLaunch,
  [switch]$KeepArchive,
  [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"

$Version = "1.0.2"
$DownloadUrl = "https://license.runmo.art/downloads/LiveWatchPortable_1.0.2.zip"
$ExpectedSha256 = "34D0AFC96CDB4AC0B0F51F6E01DBF6E9E96FD9C22606C11F3FF6BED051740BE6"
$ExpectedBytes = 391625121

function Write-Step([string]$Message) {
  Write-Host "[直播复盘侠] $Message" -ForegroundColor Cyan
}

function Assert-SafeInstallDir([string]$Path) {
  $resolved = [System.IO.Path]::GetFullPath($Path)
  if ($resolved.Length -lt 6) {
    throw "安装目录异常：$resolved"
  }
  $root = [System.IO.Path]::GetPathRoot($resolved)
  if ($resolved.TrimEnd('\') -eq $root.TrimEnd('\')) {
    throw "不能安装到磁盘根目录：$resolved"
  }
  return $resolved
}

function Verify-Archive([string]$Archive) {
  if (-not (Test-Path -LiteralPath $Archive)) {
    throw "下载文件不存在：$Archive"
  }
  $actualBytes = (Get-Item -LiteralPath $Archive).Length
  if ($actualBytes -ne $ExpectedBytes) {
    throw "安装包大小不一致。期望 $ExpectedBytes，实际 $actualBytes。请重新下载。"
  }
  $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash.ToUpperInvariant()
  if ($actualHash -ne $ExpectedSha256) {
    throw "安装包 SHA256 校验失败。请删除后重新下载。"
  }
}

$InstallDir = Assert-SafeInstallDir $InstallDir
$tempRoot = Join-Path $env:TEMP ("LiveWatchPortableInstall_" + [Guid]::NewGuid().ToString("N"))
$archive = Join-Path $tempRoot "LiveWatchPortable_$Version.zip"
$extractRoot = Join-Path $tempRoot "extract"

try {
  New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

  Write-Step "下载安装文件..."
  Invoke-WebRequest -Uri $DownloadUrl -OutFile $archive -UseBasicParsing
  Unblock-File -LiteralPath $archive -ErrorAction SilentlyContinue

  Write-Step "校验文件完整性..."
  Verify-Archive $archive
  if ($VerifyOnly) {
    Write-Step "校验通过，未执行安装。"
    return
  }

  Write-Step "解压程序文件..."
  New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null
  Expand-Archive -Path $archive -DestinationPath $extractRoot -Force
  $sourceDir = Join-Path $extractRoot "LiveWatch"
  $launcher = Join-Path $sourceDir "LiveWatchLauncher.exe"
  if (-not (Test-Path -LiteralPath $launcher)) {
    throw "压缩包结构异常，未找到 LiveWatchLauncher.exe。"
  }
  Get-ChildItem -LiteralPath $sourceDir -Recurse -Force | ForEach-Object {
    Unblock-File -LiteralPath $_.FullName -ErrorAction SilentlyContinue
  }

  if (Test-Path -LiteralPath $InstallDir) {
    $oldLauncher = Join-Path $InstallDir "LiveWatchLauncher.exe"
    $oldManifest = Join-Path $InstallDir "integrity_manifest.json"
    if (-not ((Test-Path -LiteralPath $oldLauncher) -or (Test-Path -LiteralPath $oldManifest))) {
      throw "目标目录已存在且不像直播复盘侠安装目录：$InstallDir。请换一个目录。"
    }
    $backup = "$InstallDir.bak_$(Get-Date -Format yyyyMMdd_HHmmss)"
    Write-Step "备份旧版本..."
    Move-Item -LiteralPath $InstallDir -Destination $backup
  }

  Write-Step "安装到 $InstallDir ..."
  New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName($InstallDir)) | Out-Null
  Move-Item -LiteralPath $sourceDir -Destination $InstallDir

  if (-not $NoShortcut) {
    Write-Step "创建桌面快捷方式..."
    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "直播复盘侠.lnk"
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $InstallDir "LiveWatchLauncher.exe"
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.IconLocation = Join-Path $InstallDir "LiveWatchLauncher.exe"
    $shortcut.Save()
  }

  Write-Step "安装完成。"
  if (-not $NoLaunch) {
    Start-Process -FilePath (Join-Path $InstallDir "LiveWatchLauncher.exe") -WorkingDirectory $InstallDir
  }
}
finally {
  if ($KeepArchive) {
    Write-Step "保留下载文件：$archive"
  } else {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
  }
}
