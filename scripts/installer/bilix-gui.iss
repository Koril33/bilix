; Built by scripts/package_gui_windows.py from the verified Nuitka standalone output.
; AppId and runtime directory are stable across upgrades within one channel.

#ifndef AppVersion
  #error AppVersion must be supplied by the release script
#endif
#ifndef NumericVersion
  #error NumericVersion must be supplied by the release script
#endif
#ifndef StageDir
  #error StageDir must be supplied by the release script
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by the release script
#endif
#ifndef Channel
  #error Channel must be supplied by the release script
#endif

#if Channel == "preview"
  #define DisplayName "BiliX Preview"
  #define StableAppId "{{C32C73E4-B820-46EC-BD14-05A02A426AA8}"
  #define InstallName "BiliX Preview"
#else
  #define DisplayName "BiliX"
  #define StableAppId "{{3C888838-39AF-40C1-839B-A89F07E908AD}"
  #define InstallName "BiliX"
#endif

[Setup]
AppId={#StableAppId}
AppName={#DisplayName}
AppVersion={#AppVersion}
AppVerName={#DisplayName} {#AppVersion}
AppPublisher=djhx
AppPublisherURL=https://github.com/Koril33/bilix
AppSupportURL=https://github.com/Koril33/bilix/issues
AppUpdatesURL=https://github.com/Koril33/bilix/releases
DefaultDirName={localappdata}\Programs\{#InstallName}
DefaultGroupName={#DisplayName}
UninstallDisplayIcon={app}\runtime\BiliX-GUI.exe
OutputDir={#OutputDir}
OutputBaseFilename=BiliX-GUI-Setup-{#AppVersion}-windows-x64
VersionInfoVersion={#NumericVersion}
VersionInfoDescription={#DisplayName} installer
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
LicenseFile={#StageDir}\LICENSE

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项:"; Flags: unchecked

[InstallDelete]
; This directory only contains application files. Settings, tokens and downloads
; live in platformdirs user locations and are never touched by the installer.
Type: filesandordirs; Name: "{app}\runtime"

[Files]
Source: "{#StageDir}\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\LICENSES\*"; DestDir: "{app}\LICENSES"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\SOURCES\*"; DestDir: "{app}\SOURCES"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#DisplayName}"; Filename: "{app}\runtime\BiliX-GUI.exe"
Name: "{autodesktop}\{#DisplayName}"; Filename: "{app}\runtime\BiliX-GUI.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\BiliX-GUI.exe"; Description: "启动 {#DisplayName}"; Flags: nowait postinstall skipifsilent
