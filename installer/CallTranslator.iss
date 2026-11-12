; Build only from a staged directory created by tools.stage_installer.
; This is a technical pilot installer, not a publicly signed release.
#ifndef StageDir
  #error Specify /DStageDir with the staged files
#endif
[Setup]
AppId=CallTranslatorSaaS
AppName=Call Translator
AppVersion=0.1.10
DefaultDirName={localappdata}\Programs\CallTranslatorSaaS
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=no
RestartApplications=no
DefaultGroupName=Call Translator SaaS
DisableProgramGroupPage=yes
OutputBaseFilename=CallTranslatorSetup
OutputDir={#StageDir}\installer-output
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
UninstallDisplayName=Call Translator SaaS

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Messages]
russian.WelcomeLabel2=Установка добавит программу озвучки и расширение Call Translator.%n%nЕсли вы обновляете программу, сначала завершите перевод и закройте Google Chrome. После установки откроется подробная инструкция.

[Files]
Source: "{#StageDir}\CallTranslatorLocal.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\native-host.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\INSTALL.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\extension\*"; DestDir: "{app}\extension"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\org.call_translator.saas.local"; ValueType: string; ValueName: ""; ValueData: "{app}\native-host.json"; Flags: uninsdeletevalue uninsdeletekeyifempty

[Icons]
Name: "{group}\Инструкция Call Translator"; Filename: "{app}\INSTALL.html"

[Run]
Filename: "{app}\INSTALL.html"; Description: "Открыть инструкцию по загрузке расширения"; Flags: shellexec postinstall skipifsilent
