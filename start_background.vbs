Set WshShell = CreateObject("WScript.Shell")
' WindowStyle 0 = Hidden. The user will NOT see any command prompt.
' It will run entirely in the background as a headless service.
Dim fso
Set fso = CreateObject("Scripting.FileSystemObject")
Dim scriptPath, scriptFolder
scriptPath = WScript.ScriptFullName
scriptFolder = fso.GetParentFolderName(scriptPath)

WshShell.CurrentDirectory = scriptFolder
WshShell.Run "cmd.exe /c start_headless.bat", 0, False
