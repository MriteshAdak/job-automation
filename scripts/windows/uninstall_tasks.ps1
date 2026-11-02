<#
.SYNOPSIS
    Uninstalls owned Windows Scheduled Tasks for Job Automation (AUTO-01).

.DESCRIPTION
    Safely unregisters JobAutomation_Dispatcher and JobAutomation_ModelSupervisor from Windows Task Scheduler.
    Does NOT touch database records, logs, or model weights.

.PARAMETER TaskPrefix
    Prefix for registered tasks to remove (default: JobAutomation).

.PARAMETER DryRun
    Preview tasks that would be unregistered without removing them.

.EXAMPLE
    .\uninstall_tasks.ps1
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$TaskPrefix = "JobAutomation",

    [Parameter(Mandatory = $false)]
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Job Automation - Windows Task Scheduler Uninstallation " -ForegroundColor Cyan
Write-Host " Component: AUTO-01 (Rollback Procedure)                " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$tasksToRemove = @(
    "$TaskPrefix`_Dispatcher",
    "$TaskPrefix`_ModelSupervisor"
)

foreach ($taskName in $tasksToRemove) {
    $query = & schtasks.exe /Query /TN "$taskName" 2>&1
    if ($LASTEXITCODE -eq 0) {
        if ($DryRun) {
            Write-Host "[DRY RUN] Would delete task: $taskName" -ForegroundColor Yellow
        } else {
            Write-Host "Disabling task: $taskName"
            & schtasks.exe /Change /TN "$taskName" /DISABLE | Out-Null
            Write-Host "Deleting task: $taskName"
            & schtasks.exe /Delete /TN "$taskName" /F
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  Removed '$taskName' successfully." -ForegroundColor Green
            } else {
                Write-Warning "  Failed to delete '$taskName'."
            }
        }
    } else {
        Write-Host "Task '$taskName' is not currently registered. (Skipped)" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "Task uninstallation complete." -ForegroundColor Cyan
Write-Host "Data root and application state remain intact." -ForegroundColor Gray

