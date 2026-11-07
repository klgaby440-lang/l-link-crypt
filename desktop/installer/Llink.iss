#define AppName "Llink"
#define AppVersion "1.0.0"
#define AppExe "llink.exe"

[Setup]
AppId={{C6A8E6D4-BB4C-4B54-A36A-11A0C0FF0001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=CRYPT
DefaultDirName={localappdata}\Programs\Llink
DefaultGroupName=Llink
OutputDir=..\..\artifacts
OutputBaseFilename=Llink-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#AppExe}

[Files]
Source: "..\src-tauri\target\release\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Llink"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\Llink"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Lancer Llink"; Flags: postinstall nowait skipifsilent
