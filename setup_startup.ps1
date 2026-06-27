$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbsPath = Join-Path -Path $scriptDir -ChildPath "start_background.vbs"

# Define the path to the current user's Startup folder
$startupFolder = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path -Path $startupFolder -ChildPath "QuantAlgoBackground.lnk"

# Create the COM object for Windows Script Host Shell
$wshShell = New-Object -ComObject WScript.Shell

# Create the shortcut
$shortcut = $wshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $vbsPath
$shortcut.WorkingDirectory = $scriptDir
$shortcut.Description = "Starts the Quant Algo Backend in Headless Mode"
$shortcut.Save()

Write-Host "Startup shortcut created successfully at: $shortcutPath"
Write-Host "The system will now run automatically on boot!"
