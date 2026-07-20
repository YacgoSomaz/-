param(
  [string]$InstallDir = "$env:LOCALAPPDATA\Programs\LiveWatch",
  [string]$ArchivePath = "",
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
  Write-Host "[复盘虾] $Message" -ForegroundColor Cyan
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

function Download-FileWithProgress([string]$Url, [string]$Destination, [int64]$ExpectedLength) {
  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
  if ($curl) {
    Write-Step "使用系统下载器下载，窗口会显示实时进度..."
    & $curl.Source --fail --location --retry 3 --connect-timeout 20 --progress-bar --output $Destination $Url
    if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $Destination)) {
      return
    }
    Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
    Write-Step "系统下载器失败，切换到备用下载方式..."
  }

  $request = [System.Net.HttpWebRequest]::Create($Url)
  $request.UserAgent = "LiveWatchInstaller/$Version"
  $request.AllowAutoRedirect = $true
  $request.Timeout = 30000
  $request.ReadWriteTimeout = 120000

  $response = $request.GetResponse()
  try {
    $total = [int64]$response.ContentLength
    if ($total -le 0) {
      $total = $ExpectedLength
    }

    $inputStream = $response.GetResponseStream()
    $outputStream = [System.IO.File]::Open($Destination, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
      $buffer = New-Object byte[] (1024 * 1024)
      $downloaded = [int64]0
      $lastReport = Get-Date
      $started = Get-Date

      while ($true) {
        $read = $inputStream.Read($buffer, 0, $buffer.Length)
        if ($read -le 0) {
          break
        }
        $outputStream.Write($buffer, 0, $read)
        $downloaded += $read

        $now = Get-Date
        if (($now - $lastReport).TotalMilliseconds -ge 700 -or $downloaded -eq $total) {
          $percent = 0
          if ($total -gt 0) {
            $percent = [Math]::Min(100, [Math]::Round(($downloaded * 100.0) / $total, 1))
          }
          $elapsed = [Math]::Max(0.1, ($now - $started).TotalSeconds)
          $speed = ($downloaded / 1MB) / $elapsed
        Write-Progress -Activity "正在下载复盘虾" -Status ("{0:N1} MB / {1:N1} MB，{2:N1} MB/s" -f ($downloaded / 1MB), ($total / 1MB), $speed) -PercentComplete $percent
          Write-Host ("  下载进度 {0}%  {1:N1}/{2:N1} MB  {3:N1} MB/s" -f $percent, ($downloaded / 1MB), ($total / 1MB), $speed)
          $lastReport = $now
        }
      }
    }
    finally {
      if ($outputStream) { $outputStream.Dispose() }
      if ($inputStream) { $inputStream.Dispose() }
      Write-Progress -Activity "正在下载复盘虾" -Completed
    }
  }
  finally {
    if ($response) { $response.Dispose() }
  }
}

$InstallDir = Assert-SafeInstallDir $InstallDir
$tempRoot = Join-Path $env:TEMP ("LiveWatchPortableInstall_" + [Guid]::NewGuid().ToString("N"))
$usingLocalArchive = -not [string]::IsNullOrWhiteSpace($ArchivePath)
$archive = if ($usingLocalArchive) { [System.IO.Path]::GetFullPath($ArchivePath) } else { Join-Path $tempRoot "LiveWatchPortable_$Version.zip" }
$extractRoot = Join-Path $tempRoot "extract"

try {
  New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

  if ($usingLocalArchive) {
    Write-Step "使用本地安装文件：$archive"
  } else {
    Write-Step "下载安装文件..."
    Download-FileWithProgress -Url $DownloadUrl -Destination $archive -ExpectedLength $ExpectedBytes
  }
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
      throw "目标目录已存在且不像复盘虾安装目录：$InstallDir。请换一个目录。"
    }
    $backup = "$InstallDir.bak_$(Get-Date -Format yyyyMMdd_HHmmss)"
    Write-Step "备份旧版本..."
    Move-Item -LiteralPath $InstallDir -Destination $backup
  }

  Write-Step "安装到 $InstallDir ..."
  $parentDir = Split-Path -Path $InstallDir -Parent
  if ($parentDir -and -not (Test-Path -LiteralPath $parentDir)) {
    New-Item -ItemType Directory -Force -Path $parentDir | Out-Null
  }
  Move-Item -LiteralPath $sourceDir -Destination $InstallDir

  if (-not $NoShortcut) {
    Write-Step "创建桌面快捷方式..."
    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "复盘虾.lnk"
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
  if ($KeepArchive -and -not $usingLocalArchive) {
    Write-Step "保留下载文件：$archive"
  } elseif (-not $usingLocalArchive) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
  } else {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
  }
}
