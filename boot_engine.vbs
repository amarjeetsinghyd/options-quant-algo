Set WshShell = CreateObject("WScript.Shell")
' WindowStyle 0 = Completely hidden in background. No console window will appear.
WshShell.Run "cmd.exe /c boot_engine.bat", 0, False
