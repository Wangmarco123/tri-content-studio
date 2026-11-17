#ifndef PackageDir
  #error PackageDir required
#endif
#ifndef InstallerOut
  #error InstallerOut required
#endif
[Setup]
AppId={{4A253F0D-BC23-4EB5-86E9-C77F2A2D54B2}
AppName=三平台内容发布助手
AppVersion=1.4.0
AppPublisher=漫爱设计工作室
DefaultDirName={localappdata}\Programs\TriContentStudio
DefaultGroupName=三平台内容发布助手
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#InstallerOut}
OutputBaseFilename=TriContentStudio-1.4.0-R05-Setup
SetupIconFile=..\assets\studio.ico
UninstallDisplayIcon={app}\TriContentStudio.exe
Compression=lzma2/fast
SolidCompression=yes
DiskSpanning=yes
DiskSliceSize=1566000000
SlicesPerDisk=1
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
MinVersion=10.0
[Tasks]
Name: desktopicon; Description: "创建桌面快捷方式"; Flags: unchecked
[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "state,workspace.json,*.log"
[Icons]
Name: "{group}\三平台内容发布助手"; Filename: "{app}\TriContentStudio.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\三平台内容发布助手"; Filename: "{app}\TriContentStudio.exe"; WorkingDir: "{app}"; Tasks: desktopicon
[Run]
Filename: "{app}\TriContentStudio.exe"; Description: "启动三平台内容发布助手"; Flags: nowait postinstall skipifsilent
