$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$PSScriptRoot\boot_engine.vbs`"" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00am

# Failsafe: Run task as soon as possible after a scheduled start is missed
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings

Register-ScheduledTask -TaskName "Quant_Autonomous_Engine" -InputObject $task -User $env:USERNAME -Force

Write-Host "Success! The Quant Autonomous Engine will now start automatically at 9:00 AM every day."
Write-Host "Success! The Quant Autonomous Engine will now start automatically at 9:00 AM every day."
Write-Host "If the computer is off at 9:00 AM, it will start immediately when you turn it on."
