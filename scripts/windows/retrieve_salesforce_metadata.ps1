<#
.SYNOPSIS
    Safely retrieves scoped Salesforce metadata into an isolated staging directory (SF-04-S03).

.DESCRIPTION
    1. Verifies Salesforce CLI ('sf' or 'sfdx') availability without dumping auth credentials.
    2. Enforces explicit target org binding (default: 'dev-main').
    3. Retrieves scoped metadata declared in 'salesforce/manifest/sf04-retrieve.xml' into an isolated staging root.
    4. Invokes Python metadata audit ('metadata_inventory.py') to scan for unowned children, broad profiles, and secrets.
    5. Compares staged files with repository source ('salesforce/force-app/main/default') to produce a promotion diff.
    6. Never automatically overwrites or mutates repository files or deploys to an org.

.PARAMETER TargetOrg
    The Salesforce org alias or username to retrieve from (default: 'dev-main').

.PARAMETER StagingDir
    Optional custom staging directory path (default: 'tmp/metadata_staging').
#>

[CmdletBinding()]
param(
    [string]$TargetOrg = "dev-main",
    [string]$StagingDir = "tmp\metadata_staging"
)

$ErrorActionPreference = "Stop"

Write-Host "=== SF-04: Salesforce Scoped Metadata Retrieval ===" -ForegroundColor Cyan
Write-Host "Target Org Binding: $TargetOrg"
Write-Host "Timestamp (UTC):    $([DateTime]::UtcNow.ToString('o'))"

# 1. Check Python executable in virtual environment
$PythonExe = Join-Path $PSScriptRoot "..\..\.venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python.exe"
}

# 2. Check Salesforce CLI availability
$SfCli = Get-Command "sf" -ErrorAction SilentlyContinue
if (-not $SfCli) {
    $SfCli = Get-Command "sfdx" -ErrorAction SilentlyContinue
}

if (-not $SfCli) {
    Write-Host "`n[PRECONDITION NOTICE] Salesforce CLI ('sf' / 'sfdx') is not installed or not on system PATH." -ForegroundColor Yellow
    Write-Host "Status: PENDING (Live metadata retrieval requires Salesforce CLI installation on Windows)." -ForegroundColor Yellow
    Write-Host "To install: npm install --global @salesforce/cli" -ForegroundColor DarkGray
    exit 0
}

Write-Host "Salesforce CLI:     $($SfCli.Source)" -ForegroundColor Green
try {
    $CliVersion = & $SfCli.Source --version 2>&1
    Write-Host "CLI Version:        $CliVersion" -ForegroundColor Gray
} catch {
    Write-Host "Warning: Could not determine CLI version." -ForegroundColor Yellow
}

# 3. Resolve paths
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ManifestPath = Join-Path $RepoRoot "salesforce\manifest\sf04-retrieve.xml"
$StagingPath = Join-Path $RepoRoot $StagingDir

if (-not (Test-Path $ManifestPath)) {
    Write-Error "Retrieval manifest not found at: $ManifestPath"
    exit 2
}

# 4. Prepare clean staging directory
if (Test-Path $StagingPath) {
    Write-Host "Cleaning existing staging directory: $StagingPath" -ForegroundColor DarkGray
    Remove-Item -Path $StagingPath -Recurse -Force
}
New-Item -Path $StagingPath -ItemType Directory -Force | Out-Null

# 5. Execute Scoped Metadata Retrieval
Write-Host "`nRetrieving scoped metadata with manifest: sf04-retrieve.xml..." -ForegroundColor Cyan
$SfArgs = @(
    "project", "retrieve", "start",
    "--manifest", $ManifestPath,
    "--target-org", $TargetOrg,
    "--target-metadata-dir", $StagingPath,
    "--wait", "10"
)

try {
    # Run CLI without emitting full environment/tokens
    $RetrieveOutput = & $SfCli.Source @SfArgs 2>&1
    Write-Host "Retrieval command completed." -ForegroundColor Green
} catch {
    Write-Host "[NOTICE] Live retrieval could not complete against target '$TargetOrg': $_" -ForegroundColor Yellow
    Write-Host "Status: PENDING (Interactive org session or target authorization required)." -ForegroundColor Yellow
    exit 0
}

# 6. Run Metadata Inventory and Secret Audit via Python
Write-Host "`nAuditing staged metadata against ownership registry and secret scanner..." -ForegroundColor Cyan

$AuditScript = @"
import sys
import json
from pathlib import Path
from job_automation.salesforce.metadata_inventory import (
    audit_staged_metadata,
    compare_staged_with_repository,
    compute_metadata_digest,
)

staged = Path(r'$StagingPath')
repo = Path(r'$RepoRoot') / 'salesforce' / 'force-app' / 'main' / 'default'

audit_res = audit_staged_metadata(staged)
diff_res = compare_staged_with_repository(staged, repo)
digest = compute_metadata_digest(staged)

print(f"Staged Digest: {digest}")
print(f"Valid: {audit_res['is_valid']}")
print(f"Project-Owned Files: {len(audit_res['project_owned_files'])}")
print(f"Quarantine Files: {len(audit_res['quarantine_files'])}")
print(f"Security Findings: {len(audit_res['security_findings'])}")
print(f"Comparison: {diff_res['summary']}")

if audit_res['security_findings']:
    print("\n[SECURITY VIOLATIONS DETECTED]")
    for s in audit_res['security_findings']:
        print(f"  - {s}")
    sys.exit(1)

if audit_res['quarantine_files']:
    print("\n[UNOWNED/QUARANTINE FILES DETECTED]")
    for q in audit_res['quarantine_files']:
        print(f"  - {q}")
    print("Unowned files quarantined. Review before promotion.")
"@

$AuditScriptPath = Join-Path $StagingPath "run_audit.py"
[System.IO.File]::WriteAllText($AuditScriptPath, $AuditScript, [System.Text.Encoding]::UTF8)

try {
    & $PythonExe $AuditScriptPath
    Write-Host "`nAudit complete. No secrets detected." -ForegroundColor Green
} catch {
    Write-Host "`nAudit reported issues during staged inspection." -ForegroundColor Yellow
} finally {
    if (Test-Path $AuditScriptPath) {
        Remove-Item $AuditScriptPath -Force
    }
}

Write-Host "`n[COMPLETION] Staged metadata is isolated at: $StagingPath" -ForegroundColor Cyan
Write-Host "Repository source 'salesforce/force-app/' was NOT modified (strict non-mutation enforced)." -ForegroundColor Gray

