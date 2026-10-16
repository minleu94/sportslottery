param(
    [switch]$DryRun,
    [switch]$Uninstall,
    [string]$TaskName = "SportsLottery-Research-Pipeline",
    [string]$DataRoot = "",
    [string]$WorkingDirectory = "",
    [string]$PythonPath = "",
    [switch]$RunAsSystem
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WorkingDirectoryWasExplicit = -not [string]::IsNullOrWhiteSpace($WorkingDirectory)
if ($WorkingDirectory) {
    if (-not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) {
        throw "Working directory does not exist: $WorkingDirectory"
    }
    $ProjectRoot = (Resolve-Path -LiteralPath $WorkingDirectory).Path
}
$MainPath = (Resolve-Path (Join-Path $ProjectRoot "main.py")).Path
$ConfigPath = (Resolve-Path (Join-Path $ProjectRoot "config\research_pipeline.yaml")).Path
$WorkingDirectory = $ProjectRoot
if ($PythonPath) {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw "Python executable does not exist: $PythonPath"
    }
    $PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
    if ([IO.Path]::GetFileName($PythonPath) -ieq "pythonw.exe") {
        $PythonConsolePath = Join-Path (Split-Path -Parent $PythonPath) "python.exe"
        if (-not (Test-Path -LiteralPath $PythonConsolePath -PathType Leaf)) {
            throw "python.exe was not found beside the selected pythonw.exe; it is needed to validate the dry-run plan."
        }
    } else {
        $PythonConsolePath = $PythonPath
        $SiblingPythonw = Join-Path (Split-Path -Parent $PythonPath) "pythonw.exe"
        if (Test-Path -LiteralPath $SiblingPythonw -PathType Leaf) {
            $PythonPath = (Resolve-Path -LiteralPath $SiblingPythonw).Path
        }
    }
} else {
    $PythonCommand = Get-Command python -ErrorAction Stop
    $PythonConsolePath = $PythonCommand.Source
    $PythonPath = Join-Path (Split-Path -Parent $PythonConsolePath) "pythonw.exe"
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw "pythonw.exe was not found next to $PythonConsolePath. Pass -PythonPath to select an installed or locked Python environment."
    }
}
if ($RunAsSystem -and -not $WorkingDirectoryWasExplicit) {
    throw "-RunAsSystem requires an explicit -WorkingDirectory so the task has a known workspace and ACL target."
}
if (-not $DataRoot) {
    $DefaultF = "F:\Min\Python\Project\SportsLottery_Data\research_pipeline"
    if (Test-Path -LiteralPath $DefaultF) {
        $DataRoot = $DefaultF
    } else {
        $DataRoot = Join-Path $ProjectRoot "data\research_pipeline"
    }
} elseif (-not [System.IO.Path]::IsPathRooted($DataRoot)) {
    $DataRoot = Join-Path $ProjectRoot $DataRoot
}
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)

if ($Uninstall) {
    if ($DryRun) {
        Write-Output "DRY RUN: would unregister scheduled task '$TaskName' for current user."
        exit 0
    }
    $Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($Existing -and $Existing.Description -eq "Wallet-free isolated Taiwan sports research pipeline") {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Removed scheduled task '$TaskName' for current user."
    } elseif ($Existing) {
        throw "Task '$TaskName' exists but is not owned by this helper; refusing to remove it."
    } else {
        Write-Output "Task '$TaskName' does not exist."
    }
    exit 0
}

# Validate the exact root and use the runner's configured cadence before creating
# a host task. The runner's dry-run performs no fetch or filesystem writes.
$RunnerPlanText = & $PythonConsolePath $MainPath research-pipeline --config $ConfigPath --data-root $DataRoot --dry-run | Out-String
if ($LASTEXITCODE -ne 0) {
    throw "Research runner rejected this configuration or data root; no task was registered."
}
$RunnerPlan = $RunnerPlanText | ConvertFrom-Json
$CadenceMinutes = [int]$RunnerPlan.plan.cadence_minutes
if ($CadenceMinutes -lt 1 -or $CadenceMinutes -gt 1440) {
    throw "Task cadence must be between 1 and 1440 minutes."
}

$Arguments = '"{0}" research-pipeline --config "{1}" --data-root "{2}" --resume' -f `
    $MainPath, $ConfigPath, $DataRoot
$RunAs = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$LogonType = "Interactive"
if ($RunAsSystem) {
    $RunAs = "SYSTEM"
    $LogonType = "ServiceAccount"
}
$Plan = [pscustomobject]@{
    TaskName = $TaskName
    Executable = $PythonPath
    Arguments = $Arguments
    WorkingDirectory = $ProjectRoot
    CadenceMinutes = $CadenceMinutes
    RunAs = $RunAs
    LogonType = $LogonType
    DataRoot = $DataRoot
    CredentialsStored = $false
}
if ($DryRun) {
    $Plan | ConvertTo-Json -Depth 3
    exit 0
}

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing -and $Existing.Description -ne "Wallet-free isolated Taiwan sports research pipeline") {
    throw "Task '$TaskName' already exists and is not owned by this helper; choose another -TaskName."
}

$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument $Arguments -WorkingDirectory $WorkingDirectory
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $CadenceMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
if ($RunAsSystem) {
    $Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Limited
} else {
    $Principal = New-ScheduledTaskPrincipal -UserId $Plan.RunAs -LogonType Interactive -RunLevel Limited
}
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Principal $Principal -Settings $Settings -Description "Wallet-free isolated Taiwan sports research pipeline" -Force | Out-Null
Write-Output "Registered '$TaskName' for $($Plan.RunAs), every $CadenceMinutes minutes. No credentials were stored."
