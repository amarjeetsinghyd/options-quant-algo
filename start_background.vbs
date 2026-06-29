Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Amarjeet Singh\quant_algo_test"
WshShell.Run "cmd.exe /c start_headless.bat", 0, False
