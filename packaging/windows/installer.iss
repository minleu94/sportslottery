; Inno Setup Script for Taiwan Sports Lottery System
; Requires Inno Setup 6.x (freely available at https://jrsoftware.org/isdl.php)

#define MyAppName "台灣運彩瘋狗流決策系統"
#ifndef MyAppVersion
#define MyAppVersion "2.2.0"
#endif
#define MyAppPublisher "SportsLottery Research Team"
#define MyAppExeName "Sportslottery.exe"
#define MyAppIcon "..\..\app_icon.ico"
#define SourceDir "..\..\dist\Sportslottery"

[Setup]
AppId={{8B452798-F02A-4B26-A1D8-92138BC6E74B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Sportslottery
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=Sportslottery_Win11_Setup_v{#MyAppVersion}
SetupIconFile={#MyAppIcon}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#MyAppIcon}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
