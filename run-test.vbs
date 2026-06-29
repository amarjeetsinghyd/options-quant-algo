Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Amarjeet Singh\quant_algo_test"
WshShell.Run """C:\Users\Amarjeet Singh\quant_algo_test\node_modules\electron\dist\electron.exe"" .", 1, False
