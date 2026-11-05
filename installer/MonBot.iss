; =====================================================================
; MonBot.iss : script Inno Setup qui fabrique Setup.exe
; - installe MonBot dans le dossier des programmes de l'utilisateur
; - crée un raccourci Bureau et Menu Démarrer
; - permet une désinstallation propre (Paramètres > Applications)
;
; Compilé automatiquement par GitHub Actions. Pour le compiler à la main :
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\MonBot.iss
; (après avoir lancé PyInstaller, qui crée le dossier dist\MonBot)
; =====================================================================

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppName "MonBot"
#define MyAppExeName "MonBot.exe"
#define MyAppPublisher "MonBot (usage personnel)"

[Setup]
; Identifiant unique de l'application : NE PAS le changer entre deux versions
; (sinon Windows croit que c'est un autre logiciel).
AppId={{6F2B8C41-9D3E-4A7B-B1C2-5E8F0A7D3C19}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppVerName={#MyAppName} {#MyAppVersion}
; Installation SANS droits administrateur (dans %LOCALAPPDATA%\Programs).
; Ainsi MonBot tourne avec des droits normaux, comme MT5 lancé normalement.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
; Case "Créer une icône sur le Bureau" cochée par défaut
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Tout le dossier produit par PyInstaller
Source: "..\dist\MonBot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Messages]
french.WelcomeLabel2=Ce programme va installer [name/ver].%n%nAVERTISSEMENT : le trading comporte un risque de perte en capital. Aucun gain n'est garanti. MonBot démarre en mode démo.%n%nMetaTrader 5 doit être installé sur cet ordinateur.

; Remarque : vos réglages et journaux (%APPDATA%\MonBot) ne sont PAS supprimés
; à la désinstallation, pour ne pas perdre votre historique. Supprimez ce
; dossier à la main si vous le souhaitez. Le mot de passe éventuellement
; mémorisé se retire avec le bouton « Oublier les identifiants ».
