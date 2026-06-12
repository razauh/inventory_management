#define MyAppName "Al Husnain"
#define MyAppExeName "AlHusnain.exe"
#ifndef MyAppVersion
#define MyAppVersion "0.1.0"
#endif

[Setup]
AppId={{9B04F844-06E0-4E6B-9B3F-6D5E1D39B0E5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppMutex=AlHusnainMutex
DefaultDirName={localappdata}\Programs\Al Husnain
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=AlHusnain-Setup-v{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\..\dist\AlHusnain\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
