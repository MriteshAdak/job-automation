<#
.SYNOPSIS
    Revoke Salesforce OAuth tokens and purge protected credentials from local store (SF-02).

.DESCRIPTION
    Submits a revocation request to the Salesforce OAuth revocation endpoint (/services/oauth2/revoke)
    and removes protected credential files from the Windows DPAPI store.

.PARAMETER Config
    Path to configuration JSON file (salesforce.json or app.json).
#>

[CmdletBinding()]
param (
    [Parameter(Mandatory = $false)]
    [string]$Config
)

$ErrorActionPreference = "Stop"

Write-Host "=== Job Automation: Salesforce OAuth Revocation (SF-02) ===" -ForegroundColor Cyan

# 1. Resolve Python executable
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (Test-Path $venvPython) {
    $pythonExe = $venvPython
} else {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $pythonExe = $pythonCmd.Source
    } else {
        Write-Error "Python executable not found in .venv or system PATH."
        exit 1
    }
}

# 2. Build arguments
$cmdArgs = @("-m", "job_automation.salesforce.enrollment", "--revoke")

if ($Config) {
    $cmdArgs += @("--config", $Config)
}

# 3. Execute revocation
Push-Location $repoRoot
try {
    & $pythonExe $cmdArgs
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        Write-Host "`nRevocation procedure completed successfully." -ForegroundColor Green
    } else {
        Write-Host "`nRevocation failed with exit code $exitCode." -ForegroundColor Red
    }
    exit $exitCode
} finally {
    Pop-Location
}

