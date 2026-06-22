@echo off
echo ========================================================
echo CREATING LIGHTWEIGHT BACKUP FOR GOOGLE DRIVE
echo ========================================================
echo.
echo This will create a clean ZIP file on your Desktop.
echo It will automatically ignore heavy/useless folders like 'venv' and 'node_modules'
echo to make your upload to Google Drive 100x faster!
echo.

powershell -Command "$source = '%~dp0'; $destination = [Environment]::GetFolderPath('Desktop') + '\Quant_Algo_Backup.zip'; if (Test-Path $destination) { Remove-Item $destination }; Get-ChildItem -Path $source -Exclude 'venv', 'node_modules', '__pycache__', 'logs', '.env' | Compress-Archive -DestinationPath $destination -Force; Write-Host 'Backup successfully created at: ' $destination"

echo.
pause
