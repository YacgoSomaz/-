; 复盘虾安装程序 (Inno Setup 6)
; 由 build_release.ps1 调用，命令行注入：
;   /DAppVersion=...  /DStagingDir=...  /DOutputDir=...
; 设计要点：
;   * 程序与模型装到安装目录；用户数据全部在 %LOCALAPPDATA%\LiveWatch\data，安装/卸载都不碰 → 升级天然保数据。
;   * 默认装到 C:\Program Files\LiveWatch，需要管理员权限；用户数据仍保存在本机用户目录。
;   * 卸载默认保留用户数据；并提供「同时删除全部用户数据」的明确选项。

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef StagingDir
  #define StagingDir "..\..\staging\LiveWatch"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\release"
#endif

[Setup]
AppId={{8F2A1C7E-4B3D-49A6-9E21-7C5D0A1B2E34}
AppName=复盘虾
AppVersion={#AppVersion}
AppPublisher=复盘虾（个人版）
; 旧版更新器没有传 /DIR 时，也要回到用户原来选择的安装目录。
; 否则升级包会落到默认目录，桌面快捷方式仍然启动旧版本。
DefaultDirName={code:GetDefaultInstallDir}
DefaultGroupName=复盘虾
DisableProgramGroupPage=yes
PrivilegesRequired=admin
; 保留 Inno 的正式升级识别：手动下载的更高版本应自动复用同一 AppId 的安装目录，
; 而不是把已有复盘虾目录当成普通非空文件夹。更新器传入的 /DIR 仍优先。
UsePreviousAppDir=yes
OutputDir={#OutputDir}
OutputBaseFilename=LiveWatchSetup_{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets/icon-options/replay-shrimp.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=复盘虾
UninstallDisplayIcon={app}\LiveWatchGuard.exe
CloseApplications=force
CloseApplicationsFilter=LiveWatchLauncher.exe
RestartApplications=no
#ifdef InnoSignTool
; 由 build_release.ps1 通过 ISCC /Slivewatch 注入签名命令。
; 这会在编译期同时签名安装器和嵌入的卸载程序，避免卸载时仍显示未知发布者。
SignTool=livewatch
SignedUninstaller=yes
#endif

[Languages]
Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式:"

[Files]
; 整个 staging 原样装进安装目录（exe + _internal + app\ + models\ + README）。
Source: "{#StagingDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\复盘虾"; Filename: "{app}\LiveWatchGuard.exe"; WorkingDir: "{app}"; IconFilename: "{app}\LiveWatchGuard.exe"
Name: "{group}\卸载复盘虾"; Filename: "{uninstallexe}"
Name: "{autodesktop}\复盘虾"; Filename: "{app}\LiveWatchGuard.exe"; WorkingDir: "{app}"; IconFilename: "{app}\LiveWatchGuard.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LiveWatchGuard.exe"; Description: "立即启动复盘虾"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; 覆盖升级时，先清理安装目录中受控的旧程序树，再写入新版本。
; 绝不删除 {app} 整目录，也绝不触碰 {localappdata}\LiveWatch\data，避免误删用户文件。
; 这样旧版的 PyInstaller _internal、模型和已编译 pipeline 不会与新包混用。
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\browsers"
Type: filesandordirs; Name: "{app}\asr_bench"
Type: files; Name: "{app}\LiveWatchLauncher.exe"
Type: files; Name: "{app}\LiveWatchGuard.exe"
Type: files; Name: "{app}\integrity_manifest.json"
; 清理早期本地安装包遗留的程序源码与运行资源。用户数据统一保留在
; {localappdata}\LiveWatch\data，不在这里删除。
Type: filesandordirs; Name: "{localappdata}\LiveWatch\app"
Type: filesandordirs; Name: "{localappdata}\LiveWatch\_internal"
Type: filesandordirs; Name: "{localappdata}\LiveWatch\models"
Type: filesandordirs; Name: "{localappdata}\LiveWatch\asr_bench"
Type: files; Name: "{localappdata}\LiveWatch\LiveWatchLauncher.exe"
Type: files; Name: "{localappdata}\LiveWatch\install.bat"
Type: files; Name: "{localappdata}\LiveWatch\install_to_desktop.ps1"
Type: files; Name: "{localappdata}\LiveWatch\uninstall_livewatch.ps1"
Type: files; Name: "{localappdata}\LiveWatch\uninstall_shortcut.bat"
Type: files; Name: "{localappdata}\LiveWatch\安装到桌面.bat"
Type: files; Name: "{localappdata}\LiveWatch\卸载快捷方式.bat"
Type: files; Name: "{localappdata}\LiveWatch\README_使用说明.md"

[UninstallDelete]
; Inno 会自动删除当前安装日志记录的文件；以下补充删除旧版本遗留的受控程序目录。
; 用户数据仅由下方的明确确认逻辑删除。
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\browsers"
Type: filesandordirs; Name: "{app}\asr_bench"
Type: files; Name: "{app}\LiveWatchLauncher.exe"
Type: files; Name: "{app}\LiveWatchGuard.exe"
Type: files; Name: "{app}\integrity_manifest.json"
; 清理早期“安装到本机用户目录”的程序残留；不包含 data，用户资料仍保留。
Type: filesandordirs; Name: "{localappdata}\LiveWatch\app"
Type: filesandordirs; Name: "{localappdata}\LiveWatch\_internal"
Type: filesandordirs; Name: "{localappdata}\LiveWatch\models"
Type: filesandordirs; Name: "{localappdata}\LiveWatch\asr_bench"
Type: files; Name: "{localappdata}\LiveWatch\LiveWatchLauncher.exe"
Type: files; Name: "{localappdata}\LiveWatch\install.bat"
Type: files; Name: "{localappdata}\LiveWatch\install_to_desktop.ps1"
Type: files; Name: "{localappdata}\LiveWatch\uninstall_livewatch.ps1"
Type: files; Name: "{localappdata}\LiveWatch\uninstall_shortcut.bat"
Type: files; Name: "{localappdata}\LiveWatch\安装到桌面.bat"
Type: files; Name: "{localappdata}\LiveWatch\卸载快捷方式.bat"
Type: files; Name: "{localappdata}\LiveWatch\README_使用说明.md"

[Code]
const
  LiveWatchUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{8F2A1C7E-4B3D-49A6-9E21-7C5D0A1B2E34}_is1';

var
  InstalledLauncher: String;
  PreviousInstallPathInvalid: Boolean;

function DataDir(): String;
begin
  Result := ExpandConstant('{localappdata}\LiveWatch\data');
end;

function ReadInstalledValue(const ValueName: String; var Value: String): Boolean;
begin
  Result := RegQueryStringValue(HKLM64, LiveWatchUninstallKey, ValueName, Value);
  if not Result then
    Result := RegQueryStringValue(HKLM, LiveWatchUninstallKey, ValueName, Value);
end;

function IsExistingInstallDir(const Candidate: String): Boolean;
begin
  // A valid previous install must contain the launcher.  C:\\Program is a
  // known truncation produced by the old unquoted /DIR handoff and is never
  // accepted as an upgrade target.
  Result := (Candidate <> '') and
    (CompareText(ExtractFileName(RemoveBackslashUnlessRoot(Candidate)), 'Program') <> 0) and
    FileExists(AddBackslash(Candidate) + 'LiveWatchLauncher.exe');
end;

function HasExplicitInstallDir(): Boolean;
begin
  // A packaged client passes its actual launcher directory with /DIR.  It is
  // more authoritative than a potentially stale registry value left by an
  // earlier install on another drive.
  // Inno Setup exposes named setup parameters through {param:...}; unlike
  // command-line ParamStr this also works for /DIR= paths containing spaces.
  Result := ExpandConstant('{param:DIR|}') <> '';
end;

function GetDefaultInstallDir(Param: String): String;
var
  InstalledDir: String;
begin
  PreviousInstallPathInvalid := False;
  if HasExplicitInstallDir() then
  begin
    Result := ExpandConstant('{param:DIR|}');
    Exit;
  end;
  // Inno evaluates this before showing the directory page.  Prefer the
  // registered path from the existing installation, even when an old client
  // launched this installer without an explicit /DIR switch.
  if ReadInstalledValue('Inno Setup: App Path', InstalledDir) and
     IsExistingInstallDir(InstalledDir) then
    Result := InstalledDir
  else
  begin
    if InstalledDir <> '' then
      PreviousInstallPathInvalid := True;
    Result := ExpandConstant('{autopf}\LiveWatch');
  end;
end;

procedure InitializeWizard();
var
  InstalledDir: String;
begin
  // A valid explicit /DIR comes from the running launcher and must win over a
  // registry value: users commonly install to D:/E:, while old registry data
  // may still reference C: or a previously abandoned copy.
  if PreviousInstallPathInvalid then
    MsgBox('检测到旧安装记录，但原目录无效。请在安装目录页面选择原复盘虾目录，避免生成第二份安装。', mbInformation, MB_OK)
  else if (not HasExplicitInstallDir()) and
          ReadInstalledValue('Inno Setup: App Path', InstalledDir) and
          IsExistingInstallDir(InstalledDir) then
    WizardForm.DirEdit.Text := InstalledDir;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and PreviousInstallPathInvalid and
     (not IsExistingInstallDir(WizardForm.DirEdit.Text)) then
  begin
    MsgBox('请在安装目录页面选择原复盘虾目录，否则更新会安装成第二份程序。', mbError, MB_OK);
    Result := False;
  end;
end;

function ShouldLaunchInstalledApp(): Boolean;
var
  InstalledDir: String;
  InstalledVersionText: String;
  InstalledVersion: Int64;
  PackageVersion: Int64;
begin
  Result := False;
  InstalledLauncher := '';
  if not ReadInstalledValue('Inno Setup: App Path', InstalledDir) then
    Exit;
  InstalledLauncher := AddBackslash(InstalledDir) + 'LiveWatchLauncher.exe';
  if not FileExists(InstalledLauncher) then
  begin
    InstalledLauncher := '';
    Exit;
  end;
  if not ReadInstalledValue('DisplayVersion', InstalledVersionText) then
    Exit;
  if not StrToVersion(InstalledVersionText, InstalledVersion) then
    Exit;
  if not StrToVersion('{#AppVersion}', PackageVersion) then
    Exit;
  // 同版或旧安装包不再显示空白安装向导；真正更高版本仍正常升级。
  Result := ComparePackedVersion(InstalledVersion, PackageVersion) >= 0;
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if not ShouldLaunchInstalledApp() then
    Exit;
  Log('检测到已安装的同版或更新版，直接启动：' + InstalledLauncher);
  if not Exec(InstalledLauncher, '', ExtractFileDir(InstalledLauncher), SW_SHOWNORMAL,
              ewNoWait, ResultCode) then
    MsgBox('已检测到复盘虾，但启动失败。请从开始菜单或桌面快捷方式重新打开。', mbError, MB_OK);
  Result := False;
end;

function IsLauncherRunning(): Boolean;
var
  ResultCode: Integer;
  Output: TExecOutput;
  Index: Integer;
begin
  Result := False;
  try
    if ExecAndCaptureOutput(ExpandConstant('{cmd}'),
         '/c tasklist /FI "IMAGENAME eq LiveWatchLauncher.exe" /NH', '',
         SW_HIDE, ewWaitUntilTerminated, ResultCode, Output) then
    begin
      for Index := 0 to GetArrayLength(Output.StdOut) - 1 do
      begin
        if Pos('LiveWatchLauncher.exe', Output.StdOut[Index]) > 0 then
        begin
          Result := True;
          Exit;
        end;
      end;
    end;
  except
    Log('检查 LiveWatchLauncher.exe 进程状态失败：' + GetExceptionMessage);
  end;
end;

procedure StopLauncherTree();
var
  ResultCode: Integer;
begin
  if not IsLauncherRunning() then
    Exit;
  Log('正在关闭旧版 LiveWatchLauncher.exe 进程树');
  Exec('taskkill.exe', '/F /IM LiveWatchLauncher.exe /T', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
end;

function WaitForLauncherExit(MaxSeconds: Integer): Boolean;
var
  Index: Integer;
begin
  for Index := 1 to MaxSeconds do
  begin
    if not IsLauncherRunning() then
    begin
      Result := True;
      Exit;
    end;
    Sleep(1000);
  end;
  Result := not IsLauncherRunning();
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  // 先关闭旧版进程树并确认锁文件已释放；再让 Restart Manager 处理极少数异常锁。
  StopLauncherTree();
  if not WaitForLauncherExit(12) then
    Result := '无法自动关闭正在运行的复盘虾。请在系统托盘图标中选择“彻底退出”后，再重新安装。';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  dir: String;
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    StopLauncherTree();
    if not WaitForLauncherExit(12) then
      MsgBox('复盘虾仍在运行。请在系统托盘图标中选择“彻底退出”后重新执行卸载。', mbError, MB_OK);
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    dir := DataDir();
    if DirExists(dir) then
    begin
      // 默认保留（点"否"）；只有用户明确选"是"才连数据一起删。
      if MsgBox('是否同时删除全部用户数据？' + #13#10 +
                '（Cookie、房间清单、数据库、录音、导出、日志，位于:' + #13#10 +
                dir + ' ）' + #13#10#13#10 +
                '默认【否 = 保留数据】，便于以后重装继续使用。',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        DelTree(dir, True, True, True);
      end;
    end;
  end;
end;

