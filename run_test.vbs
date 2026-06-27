Set WshShell = CreateObject("WScript.Shell")
' WindowStyle 7 = Minimized, inactive. The user can see the command prompt in the taskbar and close it to stop the bot.
WshShell.Run "cmd.exe /c start_full.bat", 7, False
