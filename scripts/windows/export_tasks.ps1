<#
.SYNOPSIS
    Exports registered Job Automation tasks from Windows Task Scheduler to XML.

.DESCRIPTION
    Queries Windows Task Scheduler for JobAutomation tasks and exports their full XML definitions.

.PARAMETER DestinationDirectory
    Target directory for exported XML definitions (default: config\tasks_export).

.PARAMETER TaskPrefix
    Prefix for tasks to export (default: JobAutomation).

.EXAMPLE
    .\export_tasks.ps1
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$DestinationDirectory = "$PSScriptRoot\..\..\config\tasks_export",

    [Parameter(Mandatory = $false)]
    [string]$TaskPrefix = "JobAutomation"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $DestinationDirectory)) {
    New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null
}

$tasksToExport = @(
    "$TaskPrefix`_Dispatcher",
    "$TaskPrefix`_ModelSupervisor"
)

foreach ($taskName in $tasksToExport) {
    $outFile = Join-Path $DestinationDirectory "$taskName.xml"
    Write-Host "Exporting task '$taskName' to '$outFile'..."
    $xml = & schtasks.exe /Query /TN "$taskName" /XML 2>&1
    if ($LASTEXITCODE -eq 0) {
        $xml | Out-File -FilePath $outFile -Encoding utf8
        Write-Host "  Saved $outFile" -ForegroundColor Green
    } else {
        Write-Warning "Task '$taskName' is not registered or could not be queried."
    }
}

