$ErrorActionPreference = 'Stop'
$researchTaskName = 'SportsLottery-Research-Pipeline'
$researchAuditRoot = 'C:\Projects\PythonProjects\sportslottery\artifacts\research_completion_20261014'
$researchTask = Get-ScheduledTask -TaskName $researchTaskName
$researchInfo = Get-ScheduledTaskInfo -TaskName $researchTaskName
[ordered]@{
    observed_at_utc = [DateTime]::UtcNow.ToString('o')
    task_name = $researchTask.TaskName
    state = $researchTask.State.ToString()
    enabled = $researchTask.Settings.Enabled
    last_run_time_utc = $researchInfo.LastRunTime.ToUniversalTime().ToString('o')
    last_task_result = $researchInfo.LastTaskResult
    next_run_time_utc = $researchInfo.NextRunTime.ToUniversalTime().ToString('o')
    logon_type = $researchTask.Principal.LogonType.ToString()
    run_level = $researchTask.Principal.RunLevel.ToString()
    actions = @($researchTask.Actions | Select-Object Execute,Arguments,WorkingDirectory)
    triggers = @($researchTask.Triggers | Select-Object StartBoundary,@{Name='RepetitionInterval';Expression={$_.Repetition.Interval}})
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $researchAuditRoot 'scheduled-task-last-run.json') -Encoding utf8
Export-ScheduledTask -TaskName $researchTaskName | Set-Content -LiteralPath (Join-Path $researchAuditRoot 'scheduled-task.xml') -Encoding utf8
Get-Content -LiteralPath (Join-Path $researchAuditRoot 'scheduled-task-last-run.json')
