; 3D Linker for PotPlayer - registers pot3d:// URL protocol and launches PotPlayer with M3U URL
#define MyAppName "3D Linker for PotPlayer"
#define MyAppVersion "1.0"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\3DLinker
DefaultGroupName=
OutputDir=dist
OutputBaseFilename=3d_setup
PrivilegesRequired=admin
Compression=lzma2
SolidCompression=yes
; No Start Menu shortcut, no desktop icon - we only register the protocol
DisableProgramGroupPage=yes
DisableWelcomePage=yes
DisableDirPage=yes

[Registry]
; Register pot3d:// URL protocol
Root: HKCR; Subkey: "pot3d"; ValueType: string; ValueName: ""; ValueData: "URL:PotPlayer 3D Protocol"; Flags: uninsdeletekey
Root: HKCR; Subkey: "pot3d"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Flags: uninsdeletekey
; Command: PowerShell strips pot3d:// -> https:// and launches PotPlayer
Root: HKCR; Subkey: "pot3d\shell\open\command"; ValueType: string; ValueName: ""; ValueData: "{code:GetPotCommand}"; Flags: uninsdeletekey

[Code]
function GetPotCommand(Param: String): String;
begin
  Result := 'powershell.exe -WindowStyle Hidden -Command "' +
    '$u=''%1'' -replace ''^pot3d://'',''https://''; ' +
    '$p=(Get-ItemProperty ''HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\PotPlayerMini64.exe'' -EA 0).''(default)''; ' +
    'if(-not $p){$p=(Get-ItemProperty ''HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\PotPlayerMini.exe'' -EA 0).''(default)''}; ' +
    'if(-not $p){$p=''C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe''}; ' +
    'Start-Process -FilePath $p -ArgumentList $u,''/3dmode'',''anaglyph_red_cyan_dubois''"';
end;
