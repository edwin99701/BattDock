; BattDock 标准 Windows 安装程序脚本（Inno Setup 6）
; 特点：管理员安装 + 安装目录 users-modify 权限 + runasoriginaluser，支持任意盘符安装、软件内免 UAC 一键自动更新、防重复安装、自动停进程覆盖与标准卸载

#ifndef MyAppVersion
  #define MyAppVersion "2.7.5"
#endif

#define MyAppName "BattDock"
#define MyAppPublisher "BattDock"
#define MyAppURL "https://github.com/edwin99701/BattDock"
#define MyAppExeName "BattDock.exe"
#define MyAppDesc "轻量化 Windows 无线外设电量管理工具"

[Setup]
; 固定 AppId：重复运行安装程序时自动识别原安装路径并原地覆盖升级，绝不重复安装两份
AppId={{B477D0C1-9A2E-4F18-B7E6-3C9E2A8F1D04}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
; 默认安装到 Program Files\BattDock，支持任意盘符/路径（如 E:\BattDock），并对程序目录授予用户修改权限以保障软件内一键自动更新
DefaultDirName={autopf}\{#MyAppName}
UsePreviousAppDir=yes
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release\assets_v{#MyAppVersion}
OutputBaseFilename=BattDock-v{#MyAppVersion}-Setup
SetupIconFile=..\assets\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern dynamic
WizardSizePercent=105
ShowLanguageDialog=no
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll
RestartApplications=no
; Windows 文件属性元数据
VersionInfoVersion={#MyAppVersion}.0
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} 安装程序（{#MyAppDesc}）
VersionInfoCopyright=Copyright (C) 2026 {#MyAppPublisher}

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "{cm:AutoStartTask}"; GroupDescription: "{cm:AutoStartGroup}"; Flags: unchecked

[Dirs]
; 授予普通用户对 BattDock 安装目录的修改权限，确保安装在 E:\BattDock 或 Program Files 后软件内自动更新无需提权即可覆盖
Name: "{app}"; Permissions: users-modify

[Files]
; 打包已编译的 release\BattDock 全部运行文件（排除仅给便携 ZIP 用的两个 bat 脚本）
Source: "..\release\BattDock\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "卸载BattDock.bat,创建桌面与开始菜单快捷方式.bat"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; Comment: "{#MyAppDesc}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#MyAppExeName}"; Comment: "{#MyAppDesc}"; Tasks: desktopicon

[Registry]
; 可选开机静默自启（与 BattDock 软件内设置页共用完全相同的注册表键）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "BattDock"; ValueData: """{app}\{#MyAppExeName}"" --background"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallDelete]
; 清理软件运行/在线更新过程中可能产生的残留临时回滚目录
Type: filesandordirs; Name: "{app}\._battdock_rollback_*"
Type: files; Name: "{app}\VGNMouseBattery.exe"

[Code]
procedure StopRunningBattDock();
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM BattDock.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM VGNMouseBattery.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(450);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningBattDock();
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  LegacyExe: String;
  LegacyDesktopLnk: String;
  LegacyStartMenuLnk: String;
  OldRunVal: String;
begin
  if CurStep = ssPostInstall then
  begin
    // 若覆盖安装在旧版目录，自动清理遗留的 VGNMouseBattery.exe、旧快捷方式与旧自启项
    LegacyExe := ExpandConstant('{app}\VGNMouseBattery.exe');
    if FileExists(LegacyExe) then
      DeleteFile(LegacyExe);

    LegacyDesktopLnk := ExpandConstant('{userdesktop}\VGNMouseBattery.lnk');
    if FileExists(LegacyDesktopLnk) then
      DeleteFile(LegacyDesktopLnk);

    LegacyStartMenuLnk := ExpandConstant('{userprograms}\VGNMouseBattery.lnk');
    if FileExists(LegacyStartMenuLnk) then
      DeleteFile(LegacyStartMenuLnk);

    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'VGNMouseBattery', OldRunVal) then
    begin
      if not RegValueExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'BattDock') then
      begin
        if Pos('--background', Lowercase(OldRunVal)) > 0 then
          RegWriteStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'BattDock', '"' + ExpandConstant('{app}\{#MyAppExeName}') + '" --background')
        else
          RegWriteStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'BattDock', '"' + ExpandConstant('{app}\{#MyAppExeName}') + '"');
      end;
      RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'VGNMouseBattery');
    end;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  StopRunningBattDock();
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  CfgDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // 彻底清理新旧版开机自启注册表项
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'BattDock');
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'VGNMouseBattery');

    // 交互式卸载时询问是否删除个人配置文件（静默卸载默认保留）
    CfgDir := ExpandConstant('{localappdata}\BattDock');
    if (not UninstallSilent) and DirExists(CfgDir) then
    begin
      if MsgBox(CustomMessage('RemoveUserConfigPrompt'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(CfgDir, True, True, True);
    end;
  end;
end;
