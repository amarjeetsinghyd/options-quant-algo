Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Quant"
WshShell.Run "cmd.exe /c start_headless.bat", 0, False
