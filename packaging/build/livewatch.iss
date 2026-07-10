; 直播复盘侠安装程序 (Inno Setup 6)
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
AppName=直播复盘侠
AppVersion={#AppVersion}
AppPublisher=直播复盘侠（个人版）
DefaultDirName={autopf}\LiveWatch
DefaultGroupName=直播复盘侠
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir={#OutputDir}
OutputBaseFilename=LiveWatchSetup_{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\livewatch.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=直播复盘侠
UninstallDisplayIcon={app}\LiveWatchLauncher.exe
CloseApplications=force
CloseApplicationsFilter=LiveWatchLauncher.exe

[Languages]
Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式:"

[Files]
; 整个 staging 原样装进安装目录（exe + _internal + app\ + models\ + README）。
Source: "{#StagingDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\直播复盘侠"; Filename: "{app}\LiveWatchLauncher.exe"; WorkingDir: "{app}"; IconFilename: "{app}\LiveWatchLauncher.exe"
Name: "{group}\卸载直播复盘侠"; Filename: "{uninstallexe}"
Name: "{autodesktop}\直播复盘侠"; Filename: "{app}\LiveWatchLauncher.exe"; WorkingDir: "{app}"; IconFilename: "{app}\LiveWatchLauncher.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LiveWatchLauncher.exe"; Description: "立即启动直播复盘侠"; Flags: nowait postinstall skipifsilent

[Code]
function DataDir(): String;
begin
  Result := ExpandConstant('{localappdata}\LiveWatch\data');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  // 先优雅关闭旧版进程树（LiveWatchLauncher 及其子进程 python/node/ffmpeg）
  Exec('taskkill.exe', '/F /IM LiveWatchLauncher.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  // 等 1 秒让文件锁释放
  Sleep(1000);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  dir: String;
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    Exec('taskkill.exe', '/F /IM LiveWatchLauncher.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(1000);
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

