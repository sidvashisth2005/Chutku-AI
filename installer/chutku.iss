; W4: ChutkuSetup.exe (Inno Setup 6.2+). Build:  ISCC /DAppVersion=1.0.0 installer\chutku.iss
; A small setup: it downloads the app package named in latest.json from the public releases repository, checks its
; SHA-256 (a mismatch is refused), and unzips it into the user's own Programs folder. No administrator rights.
; Upgrades replace the app folder and keep the user's data (%LOCALAPPDATA%\Chutku). The uninstaller asks before
; deleting that data.
;
; Switches (besides Inno's own /VERYSILENT /SUPPRESSMSGBOXES):
;   /PACKAGE=<zip>        install this local package instead of downloading; it must match <zip>.sha256 (or
;                         /PACKAGESHA256=<hex>). Used by the release workflow's clean-machine test.
;   /DELETEDATA=yes       (uninstall) delete the user's data without asking.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define LatestJson "https://github.com/sidvashisth2005/Chutku-releases/releases/latest/download/latest.json"

[Setup]
AppId={{6B1C3E57-0C7A-4F33-9A54-6E8D2F1B7C21}
AppName=Chutku
AppVersion={#AppVersion}
AppVerName=Chutku {#AppVersion}
AppPublisher=Chutku
AppPublisherURL=https://github.com/sidvashisth2005/Chutku-releases
DefaultDirName={localappdata}\Programs\Chutku
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
SetupIconFile=chutku.ico
UninstallDisplayIcon={app}\Chutku.exe
UninstallDisplayName=Chutku
OutputDir=..\dist
OutputBaseFilename=ChutkuSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Chutku

[Tasks]
Name: "autostart"; Description: "Start Chutku when I sign in"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce

[Icons]
Name: "{userprograms}\Chutku"; Filename: "{app}\Chutku.exe"
Name: "{userdesktop}\Chutku"; Filename: "{app}\Chutku.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Chutku"; \
  ValueData: """{app}\Chutku.exe"" --background"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Chutku.exe"; Description: "Launch Chutku"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\Chutku.exe"; Parameters: "--stop"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "StopChutku"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
var
  PackageZip: String;

function JsonValue(const Text, Key: String): String;
{ The string or number after "Key": in a small flat JSON object (latest.json). }
var
  P, Q: Integer;
  Rest: String;
begin
  Result := '';
  P := Pos('"' + Key + '"', Text);
  if P = 0 then Exit;
  Rest := Copy(Text, P + Length(Key) + 2, MaxInt);
  P := Pos(':', Rest);
  if P = 0 then Exit;
  Rest := Trim(Copy(Rest, P + 1, MaxInt));
  if (Length(Rest) > 0) and (Rest[1] = '"') then
  begin
    Rest := Copy(Rest, 2, MaxInt);
    Q := Pos('"', Rest);
    if Q > 0 then Result := Copy(Rest, 1, Q - 1);
  end else begin
    Q := 1;
    while (Q <= Length(Rest)) and (Pos(Rest[Q], '0123456789') > 0) do Q := Q + 1;
    Result := Copy(Rest, 1, Q - 1);
  end;
end;

function ExpectedLocalHash(const Zip: String): String;
var
  Line: AnsiString;
begin
  Result := Lowercase(Trim(ExpandConstant('{param:PACKAGESHA256|}')));
  if (Result = '') and LoadStringFromFile(Zip + '.sha256', Line) then
    Result := Lowercase(Trim(Copy(String(Line), 1, 64)));
end;

function IsHex64(const Value: String): Boolean;
var
  I: Integer;
begin
  Result := Length(Value) = 64;
  for I := 1 to Length(Value) do
    if Pos(Value[I], '0123456789abcdef') = 0 then Result := False;
end;

function FetchPackage(): String;
(* The verified package zip in the temporary folder, or raise with a message the user understands. *)
var
  Info: AnsiString;
  Url, Hash: String;
  DownloadPage: TDownloadWizardPage;
begin
  Result := ExpandConstant('{param:PACKAGE|}');
  if Result <> '' then
  begin
    Hash := ExpectedLocalHash(Result);
    if not IsHex64(Hash) then
      RaiseException('The package ' + Result + ' has no SHA-256 to check (' + Result + '.sha256).');
    if Lowercase(GetSHA256OfFile(Result)) <> Hash then
      RaiseException('The package does not match its SHA-256: it was changed or damaged. Nothing was installed.');
    Exit;
  end;
  try
    DownloadTemporaryFile('{#LatestJson}', 'latest.json', '', nil);
  except
    RaiseException('Chutku could not reach the internet to download the app. Check your connection and run the ' +
                   'setup again.');
  end;
  if not LoadStringFromFile(ExpandConstant('{tmp}\latest.json'), Info) then
    RaiseException('The release information could not be read.');
  Url := JsonValue(String(Info), 'url');
  Hash := Lowercase(JsonValue(String(Info), 'sha256'));
  if (Pos('https://github.com/sidvashisth2005/Chutku-releases/', Url) <> 1) or not IsHex64(Hash) then
    RaiseException('The release information is not valid (unexpected address or hash). Nothing was installed.');
  DownloadPage := CreateDownloadPage('Downloading Chutku', 'Chutku is downloading the app (about ' +
                                     JsonValue(String(Info), 'size') + ' bytes).', nil);
  DownloadPage.Clear;
  DownloadPage.Add(Url, 'Chutku.zip', Hash);   { Inno refuses the file if its SHA-256 differs }
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
    except
      RaiseException('The download failed or did not match its SHA-256: ' + GetExceptionMessage +
                     ' Nothing was installed.');
    end;
  finally
    DownloadPage.Hide;
  end;
  Result := ExpandConstant('{tmp}\Chutku.zip');
end;

function SafeAppFolder(const Folder: String): Boolean;
{ DelTree only a folder that is Chutku's own app folder: named Chutku, not the data folder, and either empty or
  holding Chutku.exe. A /DIR= pointing anywhere else (e.g. the user's profile) is refused. }
var
  Probe: TFindRec;
  Empty: Boolean;
begin
  Result := (Lowercase(ExtractFileName(RemoveBackslash(Folder))) = 'chutku') and
            (CompareText(RemoveBackslash(Folder), ExpandConstant('{localappdata}\Chutku')) <> 0);
  if not Result or not DirExists(Folder) then Exit;
  Empty := not FindFirst(AddBackslash(Folder) + '*', Probe);
  if not Empty then
  begin
    Empty := True;
    repeat
      if (Probe.Name <> '.') and (Probe.Name <> '..') then Empty := False;
    until not FindNext(Probe);
    FindClose(Probe);
  end;
  Result := Empty or FileExists(AddBackslash(Folder) + 'Chutku.exe');
end;

procedure StopRunningChutku();
var
  Code: Integer;
begin
  if FileExists(ExpandConstant('{app}\Chutku.exe')) then
    Exec(ExpandConstant('{app}\Chutku.exe'), '--stop', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  try
    PackageZip := FetchPackage();
  except
    Result := GetExceptionMessage;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  Command: String;
begin
  if CurStep <> ssInstall then Exit;
  StopRunningChutku();
  if not SafeAppFolder(ExpandConstant('{app}')) then
    RaiseException('Chutku installs only into its own folder named Chutku; ' + ExpandConstant('{app}') +
                   ' is not one. Nothing was changed.');
  { An upgrade replaces the whole app folder; the user's data is in LOCALAPPDATA\Chutku and is not touched. }
  DelTree(ExpandConstant('{app}'), True, True, True);
  ForceDirectories(ExpandConstant('{app}'));
  Command := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath ''' +
             PackageZip + ''' -DestinationPath ''' + ExpandConstant('{app}') + ''' -Force"';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Command, '', SW_HIDE,
              ewWaitUntilTerminated, Code) or (Code <> 0) or not FileExists(ExpandConstant('{app}\Chutku.exe')) then
    RaiseException('The app could not be unpacked (code ' + IntToStr(Code) + ').');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep <> usPostUninstall then Exit;
  Data := ExpandConstant('{localappdata}\Chutku');
  if not DirExists(Data) then Exit;
  if (Lowercase(ExpandConstant('{param:DELETEDATA|no}')) = 'yes') or
     (SuppressibleMsgBox('Also delete your Chutku data (memory, settings, history) in ' + Data + '?' + #13#10 +
                         'Choose No to keep it for a later reinstall.', mbConfirmation, MB_YESNO, IDNO) = IDYES) then
    DelTree(Data, True, True, True);
end;
