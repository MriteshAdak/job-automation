# Component Handoff: SOURCE-01 — Source Registry and Access Policy

Component ID: **SOURCE-01**  
Status: **VERIFIED**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Prerequisite Handoffs: [docs/components/FND-01.md](FND-01.md)  
Planning Reference: [docs/stories/SOURCE-01.md](../stories/SOURCE-01.md)  
Date Completed: 28 October 2026  
Direct Covered Requirements: [R02](../../IMPLEMENTATION_BLUEPRINT.md#r02), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15) (supporting R04, R14, R16)  

---

## 1. Prerequisites and Upstream Dependencies Verification

Before implementing SOURCE-01, foundational contracts and configurations from **FND-01** were inspected and verified:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **C03 SourceConfig Contract** | FND-01 | **VERIFIED** | `job_automation.contracts.sources.SourceConfig`. Reused directly without modifying the shared C03 contract model. |
| **C04 FetchManifest & Primitives** | FND-01 | **VERIFIED** | `job_automation.contracts.postings.FetchManifest`, `SourceKey`, `InventorySemantics`, `AcquisitionMethod`. |
| **Error Taxonomy & Issues** | FND-01 | **VERIFIED** | `job_automation.contracts.errors.ValidationIssue`, `ClassifiedError`. |
| **Configuration & Paths** | FND-01 | **VERIFIED** | `job_automation.configuration.AppConfig`, `ResolvedPaths`, `load_config`. Added non-breaking `source_registry_ref` resolution. |

### Downstream Handoff Status
- **SOURCE-02 (Adapter Interface & Manual Import)**: Downstream consumer. Receives checked `EffectiveSource` instances and preserves manual-input provenance.
- **SOURCE-03 (Concrete Adapters)**: Downstream consumer. Concrete implementations for real providers remain pending real permission evidence.
- **INGEST-01 (Fetch Controller)**: Downstream consumer. Enforces bounded request policies and creates honest C04 manifests with deterministic `scope_id`.
- **IDENTITY-02 (Availability Tracking)**: Downstream consumer. Compares only C04 manifests of the same `scope_id` and complete-board inventory semantics before evaluating disappearance.

---

## 2. Implementation Summary by Story

All eight planned stories from `docs/stories/SOURCE-01.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **SOURCE-01-S01** | C03 semantics, public boundary & compatibility specification | **VERIFIED** | Reused existing C03 `SourceConfig`. Established typed domain models (`AccessReview`, `AttributionReview`, `EffectiveRequestPolicy`, `InventoryScope`, `EffectiveSource`, `SourceSelectionResult`) in `models.py`. |
| **SOURCE-01-S02** | File-backed registry, identity checks & app-config reference | **VERIFIED** | `loader.py`. Enforces UTF-8 with BOM support, duplicate JSON key detection, duplicate `source_key` rejection, exact provider/board identity preservation (casing and leading zeros), config-relative path resolution, and immediate file handle release. |
| **SOURCE-01-S03** | Scoped access and attribution review validation | **VERIFIED** | `access.py`. Rejects public/robots-only claims as sufficient authorization; validates structured JSON review (timestamp, evidence reference, method scope, expiration); detects explicit denials; preserves exact attribution notices and links; distinguishes unknown attribution from `none_required`. |
| **SOURCE-01-S04** | Acquisition-specific endpoints & bounded request policy | **VERIFIED** | `request_policy.py`. Enforces HTTPS (or loopback HTTP) for automated sources; validates manual import provenance paths; enforces finite positive timeouts; converts legacy `'timeout'` to `'timeout_seconds'`; validates bounded attempts [1, 10] and backoff; strictly rejects inline userinfo/passwords and secret headers/parameters (`Authorization`, `Cookie`, `api_key`); rejects unknown typo keys. |
| **SOURCE-01-S05** | Inventory semantics & stable scope identity | **VERIFIED** | `inventory.py`. Distinguishes `complete_board`, `filtered_feed`, and `search_results`; detects contradictions between complete-board coverage and search queries; derives deterministic `scope-v1:sha256:<hex64>` invariant to timeouts, retries, headers, and pagination cursors. |
| **SOURCE-01-S06** | Checked enabled/selected-source boundary | **VERIFIED** | `service.py`. Enforces preflight selection gate: unconfigured, disabled, unreviewed, or invalid sources cannot be selected; mixed selections fail atomically (zero executable sources returned); returns detached deep copies to prevent caller mutation. |
| **SOURCE-01-S07** | Read-only CLI, examples & operator guidance | **VERIFIED** | `cli.py`, `config/sources.example.json`, `config/app.example.json`. Registered `sources check` and `sources list`; exit code 0 for valid selection (including empty selection), exit code 2 on blockers/errors; safe error output without credential leakage. |
| **SOURCE-01-S08** | Consumer-boundary checks, Windows evidence & handoff | **VERIFIED** | `test_consumer_boundary.py`, synthetic fixture catalog, native Windows verification recipe execution (Part 1 and Part 2), and component handoff document. |

---

## 3. Files Created and Modified

### Source Files (`src/job_automation/sources/`)
- [`src/job_automation/sources/__init__.py`](../../src/job_automation/sources/__init__.py): Public exports for models, validators, loader, and service facade.
- [`src/job_automation/sources/models.py`](../../src/job_automation/sources/models.py): Domain models (`SourceRegistryEnvelope`, `AccessReview`, `AccessReviewStatus`, `AttributionReview`, `AttributionStatus`, `EffectiveRequestPolicy`, `InventoryScope`, `EffectiveSource`, `SourceSelectionResult`).
- [`src/job_automation/sources/errors.py`](../../src/job_automation/sources/errors.py): Standard error codes and `make_issue` helper.
- [`src/job_automation/sources/loader.py`](../../src/job_automation/sources/loader.py): Safe registry loader with UTF-8 BOM support, duplicate key detection, and C03 validation.
- [`src/job_automation/sources/access.py`](../../src/job_automation/sources/access.py): Scoped access authorization and attribution validation.
- [`src/job_automation/sources/request_policy.py`](../../src/job_automation/sources/request_policy.py): Bounded request policy, credential checking, and endpoint validation.
- [`src/job_automation/sources/inventory.py`](../../src/job_automation/sources/inventory.py): Inventory semantics validation and deterministic `scope_id` generator.
- [`src/job_automation/sources/validation.py`](../../src/job_automation/sources/validation.py): Comprehensive per-source semantic validation coordinator.
- [`src/job_automation/sources/service.py`](../../src/job_automation/sources/service.py): `SourceRegistryService` facade providing registry loading and checked selection.
- [`src/job_automation/sources/cli.py`](../../src/job_automation/sources/cli.py): CLI subcommand handlers for `sources check` and `sources list`.

### Shared Files Modified
- [`src/job_automation/configuration.py`](../../src/job_automation/configuration.py): Added optional `source_registry_ref` field to `AppConfig` and `source_registry_path` to `ResolvedPaths` with config-relative resolution.
- [`src/job_automation/cli.py`](../../src/job_automation/cli.py): Registered `sources` subcommand parser and dispatch handlers; added source registry path to `config check` output.
- [`config/app.example.json`](../../config/app.example.json): Updated to set `source_registry_ref: "sources.example.json"` and `active_sources: []`.
- [`config/sources.example.json`](../../config/sources.example.json): Synthetic example registry with 5 disabled sources covering API, scraping, manual import, and diverse inventory semantics.
- [`schemas/v1/app_config.schema.json`](../../schemas/v1/app_config.schema.json): Regenerated JSON schema reflecting `source_registry_ref`.
- [`README.md`](../../README.md): Documented `job_automation sources check` and `job_automation sources list` usage.

### Fixtures and Tests (`tests/`)
- [`tests/fixtures/sources/README.md`](../../tests/fixtures/sources/README.md): Catalog of synthetic fixtures.
- 10 synthetic fixtures in `tests/fixtures/sources/`:
  - `valid_registry.json`, `empty_registry.json`, `invalid_duplicate_source_key.json`, `invalid_duplicate_json_key.json`, `invalid_unsupported_schema.json`, `invalid_secret_credentials.json`, `invalid_complete_board_filter.json`, `invalid_request_policy_bounds.json`, `invalid_denied_access.json`, `invalid_expired_access.json`.
- 12 test modules under [`tests/sources/`](../../tests/sources/) and [`tests/test_cli_sources.py`](../../tests/test_cli_sources.py):
  - `test_contract_boundary.py`, `test_registry.py`, `test_identity.py`, `test_access.py`, `test_attribution.py`, `test_request_policy.py`, `test_acquisition.py`, `test_inventory.py`, `test_scope_identity.py`, `test_selection.py`, `test_consumer_boundary.py`, `test_cli_sources.py`.

---

## 4. Key Architectural Decisions (D01–D10)

1. **D01: C03 Metadata Representation & Supported Versions**: Reused existing C03 `SourceConfig` without altering its contract or fields. Layered typed domain models (`AccessReview`, `AttributionReview`, `EffectiveRequestPolicy`, `InventoryScope`) in the service layer. Registry envelope version is strictly validated against `{"1.0"}`.
2. **D02: Registry Format & Path Rules**: File format is a versioned JSON envelope (`{"schema_version": "1.0", "sources": [...]}`). Resolved relative to application configuration directory; CLI `--registry` takes precedence. No implicit working-directory scans.
3. **D03: Configuration Identity & Duplicate Scopes**: Exact preservation of provider and `board_id` strings, including casing and leading zeros (`"00042"`). Duplicate `source_key` entries are rejected. Multiple source configurations may reference the same provider and board with different search scopes.
4. **D04: Access Review & Attribution States**: Access state is explicitly classified (`unreviewed`, `permitted`, `denied`). Prose notes alone do not grant permission; structured JSON review requires `reviewed_at`, `evidence_ref`, and matching `permitted_methods`. Expired reviews are detected. Attribution distinguishes `unknown` (readiness blocker) from `none_required` and `required` (preserves notice and credit link).
5. **D05: Request Policy Vocabulary & Legacy Keys**: Finite policy vocabulary (`timeout_seconds`, `request_spacing_seconds`, `max_attempts`, `backoff_factor`, `backoff_max_seconds`, `max_pages`, `headers`, `params`, `credential_ref`). Resolves legacy `'timeout'` to `'timeout_seconds'`. Rejects unknown keys, negative/zero/boolean timeouts, and out-of-range retries. Strictly forbids inline credentials and secret headers.
6. **D06: Manual Import Origin & Endpoints**: Automated acquisition requires HTTPS (or loopback HTTP). Manual import accepts provenance paths (`manual://...`, `file://...`) and requires no HTTP transport settings.
7. **D07: Inventory Scope Identity & Completeness Evidence**: Explicit semantics (`complete_board`, `filtered_feed`, `search_results`). Complete board with query/filter parameters is rejected as a contradiction. Scope identity is deterministic (`scope-v1:sha256:<hex64>`) over canonical membership fields, invariant to transport timeouts, retries, headers, and pagination cursors.
8. **D08: Checked Selection Gate**: Atomic selection boundary. If any requested source is missing, disabled, unreviewed, or invalid, the entire selection fails and returns zero executable sources. Returns deep copies to ensure snapshot immutability.
9. **D09: Initial Sources & Pending External Evidence**: Live provider agreements and verified scraping terms remain pending real user configuration. Synthetic examples are clearly marked and disabled by default.
10. **D10: Native Windows Inspection CLI**: Provided `python -m job_automation sources check` and `sources list`. Check returns exit code 0 for valid selection (including empty selection) and exit code 2 on blockers or errors. Operates cleanly with German umlauts, spaces, and releases file handles immediately.

---

## 5. Verification Commands and Actual Results

### Automated Test Suite Execution
Command executed:
```powershell
& ".\.venv\Scripts\python.exe" -m pytest
```
Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0
rootdir: C:\Users\mrite\Projects\job-search
configfile: pyproject.toml
testpaths: tests
plugins: cov-6.3.0
collected 286 items

tests\contracts\test_context_model_assessment.py ......                  [  2%]
tests\contracts\test_contract_catalog.py ............................... [ 12%]
.                                                                        [ 13%]
tests\contracts\test_errors.py ...                                       [ 14%]
tests\contracts\test_interfaces.py .....                                 [ 16%]
tests\contracts\test_primitives.py .......                               [ 18%]
tests\contracts\test_profile_policy_evidence.py ....                     [ 19%]
tests\contracts\test_source_posting_identity.py ......                   [ 22%]
tests\contracts\test_work_records.py ....                                [ 23%]
tests\policy\test_cli.py .........                                       [ 26%]
tests\policy\test_conflicts.py ......                                    [ 28%]
tests\policy\test_contract_boundary.py .....                             [ 30%]
tests\policy\test_criteria.py ........                                   [ 33%]
tests\policy\test_fingerprint.py .....                                   [ 34%]
tests\policy\test_integration.py ..                                      [ 35%]
tests\policy\test_loader.py ........                                     [ 38%]
tests\policy\test_missing.py ..                                          [ 39%]
tests\policy\test_schema_compatibility.py ...                            [ 40%]
tests\policy\test_vocabulary.py ............                             [ 44%]
tests\profile\test_evidence_store.py ....                                [ 45%]
tests\profile\test_history.py .                                          [ 46%]
tests\profile\test_inclusion.py ....                                     [ 47%]
tests\profile\test_intake.py .....                                       [ 49%]
tests\profile\test_lifecycle.py .                                        [ 49%]
tests\profile\test_provenance.py ..                                      [ 50%]
tests\profile\test_publication.py .....                                  [ 52%]
tests\profile\test_references.py ..                                      [ 52%]
tests\profile\test_repository.py .....                                   [ 54%]
tests\profile\test_validation.py .........                               [ 57%]
tests\sources\test_access.py ......                                      [ 59%]
tests\sources\test_acquisition.py ...                                    [ 60%]
tests\sources\test_attribution.py .....                                  [ 62%]
tests\sources\test_consumer_boundary.py ...                              [ 63%]
tests\sources\test_contract_boundary.py ......                           [ 65%]
tests\sources\test_identity.py ....                                      [ 67%]
tests\sources\test_inventory.py ....                                     [ 68%]
tests\sources\test_registry.py ........                                  [ 71%]
tests\sources\test_request_policy.py ...........                         [ 75%]
tests\sources\test_scope_identity.py .....                               [ 76%]
tests\sources\test_selection.py .........                                [ 80%]
tests\storage\test_connection.py ...                                     [ 81%]
tests\storage\test_duplicate_keys.py ......                              [ 83%]
tests\storage\test_filestore.py ....                                     [ 84%]
tests\storage\test_migrations.py ....                                    [ 86%]
tests\storage\test_recovery.py ....                                      [ 87%]
tests\storage\test_repositories.py .......                               [ 89%]
tests\storage\test_transactions.py ....                                  [ 91%]
tests\test_cli.py .....                                                  [ 93%]
tests\test_cli_profile.py ..                                             [ 93%]
tests\test_cli_sources.py ..........                                     [ 97%]
tests\test_cli_storage.py ..                                             [ 97%]
tests\test_configuration.py ......                                       [100%]

============================= 286 passed in 7.72s =============================
```

### Native Windows Verification Execution
Command executed (Part 1):
```powershell
$repoPath = (Get-Location).Path
$sourcePython = Join-Path $repoPath '.venv\Scripts\python.exe'
$sourceAppConfig = Join-Path $repoPath 'config\app.example.json'
$sourceRegistry = Join-Path $repoPath 'config\sources.example.json'
$sourceDataRoot = Join-Path $env:LOCALAPPDATA ('Job Automation Source Prüfung ä ' + [guid]::NewGuid().ToString('N'))

& $sourcePython -c "import platform, sys; print(sys.version); print(platform.platform())"
& $sourcePython -m job_automation sources check --config $sourceAppConfig --data-root $sourceDataRoot
$validSourceExit = $LASTEXITCODE
& $sourcePython -m job_automation sources list --config $sourceAppConfig --data-root $sourceDataRoot --json
$listSourceExit = $LASTEXITCODE
& $sourcePython -m job_automation sources check --config $sourceAppConfig --data-root $sourceDataRoot --source 'not-configured'
$invalidSourceExit = $LASTEXITCODE
$dataRootExists = Test-Path -LiteralPath $sourceDataRoot

Write-Output "RESULT: validExit=$validSourceExit listExit=$listSourceExit invalidExit=$invalidSourceExit dataRootExists=$dataRootExists"
```
Output:
```text
3.12.10 (tags/v3.12.10:0cc8128, Apr  8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]
Windows-11-10.0.26300-SP0
Sources check: VALID
  Requested Sources: []
  Selected Count:    0
{ ... JSON source listing ... }
Sources check: FAILED
  Requested Sources: ['not-configured']
  Blockers (1):
    - Source 'not-configured' is not configured in source registry
RESULT: validExit=0 listExit=0 invalidExit=2 dataRootExists=False
```

Command executed (Part 2 — Changed Directory & Handle Release):
```powershell
$sourceProbeRoot = Join-Path $env:TEMP ('Source Registry Prüfung ä ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $sourceProbeRoot | Out-Null
$sourceProbeConfig = Join-Path $sourceProbeRoot 'app.json'
$sourceProbeRegistry = Join-Path $sourceProbeRoot 'sources.example.json'
Copy-Item -LiteralPath $sourceRegistry -Destination $sourceProbeRegistry
$sourceProbeSettings = Get-Content -LiteralPath $sourceAppConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$sourceProbeSettings.source_registry_ref = 'sources.example.json'
$sourceProbeSettings.active_sources = @()
$sourceProbeSettings.data_root = $sourceDataRoot
$sourceProbeSettings.active_policy_ref = $null
$sourceProbeJson = $sourceProbeSettings | ConvertTo-Json -Depth 30
[System.IO.File]::WriteAllText($sourceProbeConfig, $sourceProbeJson, [System.Text.UTF8Encoding]::new($false))

Push-Location $env:TEMP
try {
    & $sourcePython -m job_automation sources check --config $sourceProbeConfig
    $changedDirectorySourceExit = $LASTEXITCODE
    & $sourcePython -m job_automation sources list --config $sourceProbeConfig --json
    $changedDirectoryListExit = $LASTEXITCODE
} finally {
    Pop-Location
}
$dataRootExists = Test-Path -LiteralPath $sourceDataRoot
$renamedRegistry = Join-Path $sourceProbeRoot 'sources_renamed.json'
Rename-Item -LiteralPath $sourceProbeRegistry -NewName $renamedRegistry
$renamedExists = Test-Path -LiteralPath $renamedRegistry
Remove-Item -LiteralPath $sourceProbeRoot -Recurse -Force

Write-Output "RESULT: changedDirCheckExit=$changedDirectorySourceExit changedDirListExit=$changedDirectoryListExit dataRootExists=$dataRootExists handleReleased=$renamedExists"
```
Output:
```text
RESULT: changedDirCheckExit=0 changedDirListExit=0 dataRootExists=False handleReleased=True
```

---

## 6. Known Limitations and Pending Work

1. **Concrete Source Adapters**: Network collection, HTTP pagination, and HTML scraping belong to **SOURCE-02** and **SOURCE-03**. No network calls are made by SOURCE-01.
2. **Real Provider Authorization**: Terms of service and API licenses for live providers (e.g. Arbeitnow, Greenhouse) remain pending real operator configuration.
3. **Disappearance Inference**: Job closure logic belongs to **IDENTITY-02**. SOURCE-01 defines scope identity and completeness semantics only.

---

## 7. Guidance for Dependent Components

- **SOURCE-02 (Adapter Interface & Manual Import)**:
  - Consume checked `EffectiveSource` instances from `SourceRegistryService.select_sources()`.
  - For `manual_import`, preserve `base_url` as provenance; read files from the local filesystem without issuing HTTP requests.
- **INGEST-01 (Fetch Controller)**:
  - Honor `request_policy.request_spacing_seconds`, `timeout_seconds`, and `max_attempts`.
  - Propagate `inventory_scope.scope_id` and `inventory_scope.semantics` into created `FetchManifest` (C04) records.
  - Record execution outcome honestly (`complete`, `partial`, `failed`); never mark a partial run as complete.
- **IDENTITY-02 (Availability Tracking)**:
  - Compare vacancy presence only across manifests sharing the same exact `scope_id`.
  - Never infer job closure from `search_results` or `filtered_feed` runs, even if execution completed with zero results.
- **RUN-01 (Pipeline Orchestrator)**:
  - Invoke `SourceRegistryService.load_from_config()` during preflight.
  - Abort pipeline before starting fetch stages if any requested active source has validation or readiness blockers.

