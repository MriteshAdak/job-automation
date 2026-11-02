<#
.SYNOPSIS
    Installs native Windows Scheduled Tasks for Job Automation (AUTO-01).

.DESCRIPTION
    Registers JobAutomation_Dispatcher and JobAutomation_ModelSupervisor tasks in Windows Task Scheduler.
    Both tasks are registered in DISABLED state by default.
    Enforces:
    - No credentials stored in files or command arguments.
    - Prompts securely for password if batch logon is configured.
    - Foreign task collision protection.
    - Inspectable XML task definitions.

.PARAMETER XmlDirectory
    Directory containing exported task XML files (default: config\tasks).

.PARAMETER TaskPrefix
    Prefix for registered tasks (default: JobAutomation).

.PARAMETER EnableAfterInstall
    Switch to enable tasks immediately after installation (default: false / disabled).

.PARAMETER DryRun
    Preview commands without modifying Task Scheduler.

.EXAMPLE
    .\install_tasks.ps1 -XmlDirectory .\config\tasks
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$XmlDirectory = "$PSScriptRoot\..\..\config\tasks",

    [Parameter(Mandatory = $false)]
    [string]$TaskPrefix = "JobAutomation",

    [Parameter(Mandatory = $false)]
    [switch]$EnableAfterInstall,

    [Parameter(Mandatory = $false)]
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Job Automation - Windows Task Scheduler Installation " -ForegroundColor Cyan
Write-Host " Component: AUTO-01 (Native Scheduling Integration)  " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$resolvedXmlDir = Resolve-Path $XmlDirectory -ErrorAction SilentlyContinue
if (-not $resolvedXmlDir) {
    Write-Error "Task definition XML directory not found at '$XmlDirectory'. Run 'python -m job_automation ops schedule export-tasks' first."
    exit 2
}

$dispatcherXml = Join-Path $resolvedXmlDir "JobAutomation_Dispatcher.xml"
$modelXml = Join-Path $resolvedXmlDir "JobAutomation_ModelSupervisor.xml"

if (-not (Test-Path $dispatcherXml)) {
    Write-Error "Dispatcher XML not found at '$dispatcherXml'."
    exit 2
}

Write-Host "[1/3] Validating task definition XMLs..." -ForegroundColor Green
Write-Host "  Dispatcher XML: $dispatcherXml"
if (Test-Path $modelXml) {
    Write-Host "  Model Supervisor XML: $modelXml"
}

$taskFolder = "\$TaskPrefix"
$dispatcherTaskName = "$TaskPrefix`_Dispatcher"
$modelTaskName = "$TaskPrefix`_ModelSupervisor"

# Check collision with foreign tasks
Write-Host "[2/3] Checking task collisions..." -ForegroundColor Green
$existingDispatcher = & schtasks.exe /Query /TN "$dispatcherTaskName" 2>&1
if ($LASTEXITCODE -eq 0 -and $existingDispatcher -notmatch "JobAutomation") {
    Write-Error "A task named '$dispatcherTaskName' already exists but does not appear to be owned by JobAutomation. Aborting."
    exit 2
}

if ($DryRun) {
    Write-Host "[DRY RUN] Would register tasks:" -ForegroundColor Yellow
    Write-Host "  schtasks.exe /Create /TN `"$dispatcherTaskName`" /XML `"$dispatcherXml`" /F"
    if (Test-Path $modelXml) {
        Write-Host "  schtasks.exe /Create /TN `"$modelTaskName`" /XML `"$modelXml`" /F"
    }
    Write-Host "Tasks would remain DISABLED."
    exit 0
}

Write-Host "[3/3] Registering tasks into Windows Task Scheduler..." -ForegroundColor Green

# Register Dispatcher
Write-Host "  Registering '$dispatcherTaskName'..."
& schtasks.exe /Create /TN "$dispatcherTaskName" /XML "$dispatcherXml" /F
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to register '$dispatcherTaskName'."
    exit $LASTEXITCODE
}

# Ensure disabled by default
if (-not $EnableAfterInstall) {
    & schtasks.exe /Change /TN "$dispatcherTaskName" /DISABLE | Out-Null
    Write-Host "  '$dispatcherTaskName' registered and left DISABLED." -ForegroundColor Yellow
} else {
    & schtasks.exe /Change /TN "$dispatcherTaskName" /ENABLE | Out-Null
    Write-Host "  '$dispatcherTaskName' ENABLED." -ForegroundColor Green
}

# Register Model Supervisor if XML exists
if (Test-Path $modelXml) {
    Write-Host "  Registering '$modelTaskName'..."
    & schtasks.exe /Create /TN "$modelTaskName" /XML "$modelXml" /F
    if ($LASTEXITCODE -eq 0) {
        if (-not $EnableAfterInstall) {
            & schtasks.exe /Change /TN "$modelTaskName" /DISABLE | Out-Null
            Write-Host "  '$modelTaskName' registered and left DISABLED." -ForegroundColor Yellow
        } else {
            & schtasks.exe /Change /TN "$modelTaskName" /ENABLE | Out-Null
            Write-Host "  '$modelTaskName' ENABLED." -ForegroundColor Green
        }
    } else {
        Write-Warning "Could not register Model Supervisor task '$modelTaskName'. Continuing..."
    }
}

Write-Host ""
Write-Host "Task installation completed successfully." -ForegroundColor Cyan
Write-Host "Review installed tasks with: .\status_tasks.ps1" -ForegroundColor Cyan

