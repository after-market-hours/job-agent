# Registers a daily 8:00am Windows scheduled task that emails the job digest.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
$action = New-ScheduledTaskAction -Execute $py -Argument "-m jobagent digest" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 8:00am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable
Register-ScheduledTask -TaskName "JobAgentDigest" -Action $action -Trigger $trigger -Settings $settings -Force

# Weekly refresh (Sundays 6am) of the YC/accelerator company list so new hiring startups get picked up.
$weekly = New-ScheduledTaskAction -Execute $py -Argument "-m jobagent harvest" -WorkingDirectory $root
$wtrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 6:00am
Register-ScheduledTask -TaskName "JobAgentHarvest" -Action $weekly -Trigger $wtrigger -Settings $settings -Force
