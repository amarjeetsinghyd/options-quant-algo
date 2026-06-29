Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Amarjeet Singh\quant_algo_test"
WshShell.Run ".\node_modules\.bin\electron.cmd .", 0, False
