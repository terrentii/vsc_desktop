; Inno Setup — установщик МЫС Desktop для Windows.
; Ожидает собранную PyInstaller onedir-папку в dist\mys-desktop\.
; Компиляция:  iscc packaging\windows\installer.iss
; Результат:   dist\mys-desktop-setup-<версия>.exe

#define MyAppName "МЫС Desktop"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "soufos.ru"
#define MyAppExeName "mys-desktop.exe"

[Setup]
; Стабильный AppId — не менять между версиями (по нему работает обновление/удаление).
AppId={{8F3C2A1E-6B4D-4E2A-9C1F-7A0D5E9B2C44}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\MYS Desktop
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=mys-desktop-setup-{#MyAppVersion}
SetupIconFile=..\..\src\mys_ui\vsc.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; По умолчанию ставим для текущего пользователя (без прав администратора).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Вся onedir-сборка PyInstaller.
Source: "..\..\dist\mys-desktop\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
