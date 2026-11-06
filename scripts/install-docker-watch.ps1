$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$pythonw = Join-Path $root '.ven\Scripts\pythonw.exe'
$action = New-ScheduledTaskAction -Execute $pythonw -Argument ('"' + (Join-Path $PSScriptRoot 'watch-docker.py') + '"') -WorkingDirectory $root
$login = New-ScheduledTaskTrigger -AtLogOn -User $user
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'RugScene-Docker-Watch' -Action $action -Trigger @($login, $repeat) -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'RugScene-Docker-Watch'
Write-Output 'Installed RugScene-Docker-Watch (every minute while user is logged in).'
