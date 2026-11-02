<#
.SYNOPSIS
    Displays status, last run time, and last exit code of Job Automation scheduled tasks.

.DESCRIPTION
    Queries Windows Task Scheduler and displays status for JobAutomation tasks.

.PARAMETER TaskPrefix
    Prefix for tasks to query (default: JobAutomation).

.EXAMPLE
    .\status_tasks.ps1
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$TaskPrefix = "JobAutomation"
)

$tasksToQuery = @(
    "$TaskPrefix`_Dispatcher",
    "$TaskPrefix`_ModelSupervisor"
)

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Job Automation - Windows Task Scheduler Status " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

foreach ($taskName in $tasksToQuery) {
    Write-Host "`nTask: $taskName" -ForegroundColor Yellow
    $info = & schtasks.exe /Query /TN "$taskName" /FO LIST /V 2>&1
    if ($LASTEXITCODE -eq 0) {
        $info | ForEach-Object {
            if ($_ -match "^(TaskName|Status|Last Run Time|Next Run Time|Last Result|Author|Task To Run):") {
                Write-Host "  $_"
            }
        }
    } else {
        Write-Host "  Status: NOT REGISTERED" -ForegroundColor Gray
    }
}

