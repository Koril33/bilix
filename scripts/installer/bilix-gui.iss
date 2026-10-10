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
SetupIconFile=..\..\src\djhx_bilix\assets\bilix.ico
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
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
SetupLogging=yes
LicenseFile={#StageDir}\LICENSE

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项:"; Flags: unchecked

[Files]
Source: "{#StageDir}\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifdef ValidationFailure
; A real missing external-file I/O error after runtime writes. An exception in
; BeforeInstall can be suppressed and ignored, so it is not a rollback fixture.
Source: "{tmp}\bilix-validation-missing-source.bin"; DestDir: "{app}"; Flags: external ignoreversion; ExternalSize: 1
#endif
Source: "{#StageDir}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\LICENSES\*"; DestDir: "{app}\LICENSES"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\SOURCES\*"; DestDir: "{app}\SOURCES"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#DisplayName}"; Filename: "{app}\runtime\BiliX-GUI.exe"
Name: "{autodesktop}\{#DisplayName}"; Filename: "{app}\runtime\BiliX-GUI.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\BiliX-GUI.exe"; Description: "启动 {#DisplayName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  RuntimeBackedUp, InstallComplete: Boolean;

function UninstallKey: String;
begin
  Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' +
    ExpandConstant('{#StableAppId}') + '_is1';
end;

{ Compare numeric components, then dev/alpha/beta/rc/final. Unknown installed
  formats fail closed rather than guessing lexical ordering. }
function ParseVersion(Value: String; var Numbers: TArrayOfInteger): Boolean;
var I, Dot, N, Suffix, SuffixNumber: Integer; Token, Tail: String;
begin
  Result := False;
  SetArrayLength(Numbers, 5);
  Tail := Lowercase(Value);
  for I := 0 to 2 do begin
    Dot := Pos('.', Tail);
    if (I < 2) and (Dot = 0) then Exit;
    if I < 2 then begin
      Token := Copy(Tail, 1, Dot - 1);
      Delete(Tail, 1, Dot);
    end else begin
      N := 1;
      while (N <= Length(Tail)) and (Tail[N] >= '0') and (Tail[N] <= '9') do N := N + 1;
      Token := Copy(Tail, 1, N - 1);
      Delete(Tail, 1, N - 1);
    end;
    Numbers[I] := StrToIntDef(Token, -1);
    if Numbers[I] < 0 then Exit;
  end;
  Suffix := 4; SuffixNumber := 0;
  if Tail <> '' then begin
    if Copy(Tail, 1, 4) = '.dev' then begin Suffix := 0; Delete(Tail, 1, 4); end
    else if Copy(Tail, 1, 1) = 'a' then begin Suffix := 1; Delete(Tail, 1, 1); end
    else if Copy(Tail, 1, 1) = 'b' then begin Suffix := 2; Delete(Tail, 1, 1); end
    else if Copy(Tail, 1, 2) = 'rc' then begin Suffix := 3; Delete(Tail, 1, 2); end
    else Exit;
    SuffixNumber := StrToIntDef(Tail, -1);
    if SuffixNumber < 0 then Exit;
  end;
  Numbers[3] := Suffix; Numbers[4] := SuffixNumber;
  Result := True;
end;

function VersionCheck: String;
var Installed: String; OldNumbers, NewNumbers: TArrayOfInteger; I: Integer;
begin
  Result := '';
  if not RegQueryStringValue(HKCU64, UninstallKey, 'DisplayVersion', Installed) then Exit;
  if not ParseVersion(Installed, OldNumbers) or not ParseVersion('{#AppVersion}', NewNumbers) then begin
    Result := '无法识别已安装版本。请先核对同渠道安装记录。'; Exit;
  end;
  for I := 0 to 4 do begin
    if OldNumbers[I] > NewNumbers[I] then begin
      Result := '已安装更新的 BiliX ' + Installed + '，已阻止降级。'; Exit;
    end;
    if OldNumbers[I] < NewNumbers[I] then Exit;
  end;
end;

function InitializeSetup: Boolean;
var Error: String;
begin
  Error := VersionCheck;
  Result := Error = '';
  if not Result then begin
    Log(Error);
    SuppressibleMsgBox(Error, mbError, MB_OK, IDOK);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := VersionCheck;
  if Result <> '' then Exit;
  if DirExists(ExpandConstant('{app}\runtime.previous')) then
    Result := '发现未恢复的 runtime.previous。请保留该目录并核对旧版本后重试。';
end;

procedure RegisterExtraCloseApplicationsResources;
begin
  RegisterExtraCloseApplicationsResource(ExpandConstant('{app}\runtime\BiliX-GUI.exe'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then begin
    if DirExists(ExpandConstant('{app}\runtime')) then begin
      if not RenameFile(ExpandConstant('{app}\runtime'), ExpandConstant('{app}\runtime.previous')) then
        RaiseException('无法保护旧运行目录，请退出应用并检查权限。');
      RuntimeBackedUp := True;
    end;
  end;
  if CurStep = ssDone then begin
    InstallComplete := True;
    if RuntimeBackedUp then
      DelTree(ExpandConstant('{app}\runtime.previous'), True, True, True);
  end;
end;

procedure DeinitializeSetup;
begin
  if RuntimeBackedUp and not InstallComplete then begin
    if (not DirExists(ExpandConstant('{app}\runtime')) or
        DelTree(ExpandConstant('{app}\runtime'), True, True, True)) and
       RenameFile(ExpandConstant('{app}\runtime.previous'), ExpandConstant('{app}\runtime')) then
      Log('Previous runtime restored')
    else begin
      Log('Previous runtime retained; automatic restoration failed');
      SuppressibleMsgBox('旧版本保留在 runtime.previous；自动恢复失败，请勿删除该目录。', mbError, MB_OK, IDOK);
    end;
  end;
end;
