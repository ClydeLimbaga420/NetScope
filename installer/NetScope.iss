; NetScope per-user installer. Built by scripts\build_installer.ps1.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8E6F1C2A-4B7D-4E3A-9C5F-2D1B7A6E8F04}
AppName=NetScope
AppVersion={#AppVersion}
AppPublisher=NetScope
DefaultDirName={localappdata}\Programs\NetScope
DefaultGroupName=NetScope
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename=NetScope-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes
CloseApplications=yes
UninstallDisplayIcon={app}\NetScope.exe
UninstallDisplayName=NetScope
SetupIconFile=..\assets\netscope.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\NetScope.exe"; DestDir: "{app}"; Flags: ignoreversion
; CLI shim: cmd.exe waits for GUI programs launched from a batch file, so
; `netscope --version` prints before the next prompt instead of after it.
Source: "..\scripts\netscope.cmd"; DestDir: "{app}\bin"; DestName: "netscope.cmd"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\NetScope"; Filename: "{app}\NetScope.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\NetScope"; Filename: "{app}\NetScope.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\App Paths\NetScope.exe"; ValueType: string; ValueName: ""; ValueData: "{app}\NetScope.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}\bin"; Flags: preservestringtype; Check: NeedsAddPath('{app}\bin')

[Run]
Filename: "{app}\NetScope.exe"; Description: "{cm:LaunchProgram,NetScope}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop every NetScope process before Windows tries to delete the running exe.
Filename: "{app}\NetScope.exe"; Parameters: "__stop_all__"; RunOnceId: "NetScopeStopAll"; Flags: runhidden waituntilterminated skipifdoesntexist

[Code]
function GetUserPath: string;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Result) then
    Result := '';
end;

function PathContains(const Path, Dir: string): Boolean;
var
  Rest, Entry: string;
begin
  Result := False;
  Rest := Path;
  while Rest <> '' do
  begin
    if Pos(';', Rest) > 0 then
    begin
      Entry := Copy(Rest, 1, Pos(';', Rest) - 1);
      Rest := Copy(Rest, Pos(';', Rest) + 1, Length(Rest));
    end
    else
    begin
      Entry := Rest;
      Rest := '';
    end;
    Entry := Trim(Entry);
    if (Entry <> '') and (CompareText(Entry, Dir) = 0) then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function NeedsAddPath(Param: string): Boolean;
begin
  Result := not PathContains(GetUserPath, ExpandConstant(Param));
end;

procedure RemoveFromUserPath(const Dir: string);
var
  Path, Rest, Entry, NewPath: string;
begin
  Path := GetUserPath;
  Rest := Path;
  NewPath := '';
  while Rest <> '' do
  begin
    if Pos(';', Rest) > 0 then
    begin
      Entry := Copy(Rest, 1, Pos(';', Rest) - 1);
      Rest := Copy(Rest, Pos(';', Rest) + 1, Length(Rest));
    end
    else
    begin
      Entry := Rest;
      Rest := '';
    end;
    if (Trim(Entry) <> '') and (CompareText(Trim(Entry), Dir) <> 0) then
    begin
      if NewPath <> '' then
        NewPath := NewPath + ';';
      NewPath := NewPath + Entry;
    end;
  end;
  if NewPath <> Path then
    RegWriteExpandStringValue(HKCU, 'Environment', 'Path', NewPath);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    SaveStringToFile(
      ExpandConstant('{app}\.netscope-inno'),
      'Managed by NetScope Setup',
      False
    );
    // Upgrade from a build that put the GUI exe directory itself on PATH:
    // that entry would win over the new CLI shim (PATHEXT prefers .exe).
    RemoveFromUserPath(ExpandConstant('{app}'));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    RemoveFromUserPath(ExpandConstant('{app}\bin'));
    RemoveFromUserPath(ExpandConstant('{app}'));
  end;
  if CurUninstallStep = usPostUninstall then
    if UninstallSilent or (MsgBox(
      'Also remove NetScope logs, reports, and fix backups?',
      mbConfirmation,
      MB_YESNO or MB_DEFBUTTON1
    ) = IDYES) then
      DelTree(ExpandConstant('{localappdata}\NetScope'), True, True, True);
end;
