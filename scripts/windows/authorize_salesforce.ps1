<#
.SYNOPSIS
    Interactive OAuth 2.0 PKCE enrollment for the Salesforce Job Automation worker (SF-02).

.DESCRIPTION
    Launches the system browser for interactive user authentication against the configured
    Salesforce instance. Exchanges the resulting authorization code with PKCE S256 for a
    refresh token, verifies identity against expected Org/User IDs, and stores the credentials
    using native Windows DPAPI (CryptProtectData). Never logs or leaks secrets.

.PARAMETER Config
    Path to configuration JSON file (salesforce.json or app.json).

.PARAMETER ClientId
    Salesforce External Client App Consumer Key (Client ID).

.PARAMETER TimeoutSeconds
    Timeout in seconds to wait for browser callback (default: 120).
#>

[CmdletBinding()]
param (
    [Parameter(Mandatory = $false)]
    [string]$Config,

    [Parameter(Mandatory = $false)]
    [string]$ClientId,

    [Parameter(Mandatory = $false)]
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"

Write-Host "=== Job Automation: Salesforce OAuth PKCE Enrollment (SF-02) ===" -ForegroundColor Cyan

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
$cmdArgs = @("-m", "job_automation.salesforce.enrollment")

if ($Config) {
    $cmdArgs += @("--config", $Config)
}

if ($ClientId) {
    $cmdArgs += @("--client-id", $ClientId)
}

if ($TimeoutSeconds) {
    $cmdArgs += @("--timeout", $TimeoutSeconds.ToString())
}

# 3. Execute enrollment
Push-Location $repoRoot
try {
    & $pythonExe $cmdArgs
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        Write-Host "`nAuthorization and credential provisioning completed successfully." -ForegroundColor Green
    } else {
        Write-Host "`nAuthorization failed with exit code $exitCode." -ForegroundColor Red
    }
    exit $exitCode
} finally {
    Pop-Location
}

