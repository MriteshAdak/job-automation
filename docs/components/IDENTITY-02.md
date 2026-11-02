# Component Handoff: IDENTITY-02 — Posting Availability and Lifecycle Tracking

Component ID: **IDENTITY-02**  
Status: **VERIFIED**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026, §4–6, §8–9)  
Prerequisite Handoffs: [docs/components/FND-01.md](FND-01.md), [docs/components/DATA-01.md](DATA-01.md), [docs/components/INGEST-01.md](INGEST-01.md), [docs/components/INGEST-02.md](INGEST-02.md), [docs/components/IDENTITY-01.md](IDENTITY-01.md)  
Planning Reference: [docs/stories/IDENTITY-02.md](../stories/IDENTITY-02.md)  
Date Completed: 28 October 2026  
Direct Covered Requirements: [R04](../../IMPLEMENTATION_BLUEPRINT.md#r04) (track posting lifecycle and availability conservatively; multi-source canonical aggregation), [R08](../../IMPLEMENTATION_BLUEPRINT.md#r08) (detect disappearance without altering candidate decisions, application status, or candidate notes), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16) (auditability, transition ledger, idempotent replay, and crash recovery).  
Supporting Constraints: [R02](../../IMPLEMENTATION_BLUEPRINT.md#r02) (manifest evidence eligibility), [R03](../../IMPLEMENTATION_BLUEPRINT.md#r03) (provenance), [R09](../../IMPLEMENTATION_BLUEPRINT.md#r09) (durable state in SQLite), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14) (native Windows conventions), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15) (untrusted input and safe diagnostics).

---

## 1. Prerequisites and Contract Verification

IDENTITY-02 was implemented using existing contracts (C04 `RunManifest`, C06 `NormalizedPosting`, C07 `CanonicalJob`, `PostingRevision`) and storage repositories from DATA-01, INGEST-01, and IDENTITY-01 without modifying shared contract schemas or mutating candidate-owned fields:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **C04 Contract** | FND-01 / INGEST-01 | **VERIFIED** | Consumes `RunManifest` metadata to validate capture completeness, scope identity, and error state. Implemented strict eligibility filtering: requires `ManifestStatus.COMPLETE` AND `FeedType.COMPLETE_BOARD`, zero errors (`error_count == 0`), and valid chronology (`started_at <= completed_at`). Partial, failed, and search-only runs strictly block negative inference. |
| **C06 Contract** | FND-01 / INGEST-02 | **VERIFIED** | Positive sightings extract composite source identity `(provider, board_id, source_posting_id)` and observation timestamps directly from normalized records. |
| **C07 Contracts** | FND-01 / IDENTITY-01 | **VERIFIED** | Manages availability states (`active`, `not_seen`, `unavailable`, `unknown`) on `CanonicalJob` while preserving revisions, company linkages, and merge lineage. Updates both SQLite column and `job_json` projection synchronously via immutable model copies. |
| **C11 Assessment & Candidate State** | FND-01 / MATCH-01 | **VERIFIED** | Availability tracking strictly operates as a read-only observer relative to candidate-owned fields. Candidate application statuses (`Applied`, `Interviewing`, `Offered`), decisions, notes, and assessment scores are never altered by availability transitions. |
| **DATA-01 Storage Engine & Repositories** | DATA-01 / IDENTITY-01 | **VERIFIED** | Implemented `AvailabilityRepository` and extended `StorageEngine` and `CanonicalJobRepository`. Added non-breaking forward migration `MIGRATION_005_AVAILABILITY_TRACKING` (schema version 5). Transactional unit-of-work ensures multi-table consistency and replay idempotency. |

---

## 2. Implementation Summary by Story

All eight planned stories from `docs/stories/IDENTITY-02.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **IDENTITY-02-S01** | Freeze availability states, models, and policy configuration | **VERIFIED** | Defined `PostingAvailability` (`ACTIVE`, `NOT_SEEN`, `UNAVAILABLE`, `UNKNOWN`), `AvailabilityTransitionReason`, `SourcePostingAvailability`, `AvailabilityDecision`, and change results in `models.py`. Implemented `AvailabilityRuleSettings` (consecutive misses $\ge 2$, finite grace $\ge 0.0\,\text{s}$) and `AvailabilityPolicy` (with source/scope overrides and SHA-256 fingerprinting) in `settings.py`. Configured defaults: threshold = 3, grace = 48 hours (172,800.0s). Standardized errors under `AvailabilityError` in `errors.py`. |
| **IDENTITY-02-S02** | Classify manifest evidence and guard negative inference boundaries | **VERIFIED** | Implemented `is_manifest_eligible_for_negative_inference` and `compute_manifest_fingerprint` in `evidence.py`. Incomplete manifests, partial page commits, execution failures, filtered query parameters, search-only feeds, or chronologically inverted runs are blocked from negative inference with explicit reason codes (`STATUS_INCOMPLETE`, `NOT_COMPLETE_BOARD`, `ERRORS_RECORDED`, `INVALID_CHRONOLOGY`). |
| **IDENTITY-02-S03** | Persist source availability, decision ledger, and inventory receipts | **VERIFIED** | Implemented `MIGRATION_005_AVAILABILITY_TRACKING` (version 5) in `migrations.py` creating `source_posting_availability`, `availability_decisions`, and `consumed_inventories` tables. Created `AvailabilityRepository` in `src/job_automation/storage/repositories/availability.py` with indexed lookups, atomic upserts, and decision logging. |
| **IDENTITY-02-S04** | Process positive sightings and reset disappearance counters | **VERIFIED** | Implemented `evaluate_sighting` in `rules.py`. Positive observations in any manifest (complete, partial, or search) immediately update `last_seen_at`, advance state to `ACTIVE`, and reset consecutive miss streak to 0 and `first_missed_at` to `None`. |
| **IDENTITY-02-S05** | Evaluate consecutive misses and grace period conjunction | **VERIFIED** | Implemented `evaluate_miss` in `rules.py`. A posting transitions to `NOT_SEEN` on the first qualifying miss. Transition to `UNAVAILABLE` strictly requires the conjunction of both conditions: `consecutive_misses >= threshold` AND `(manifest.completed_at - first_missed_at).total_seconds() >= grace_seconds`. If threshold is met before grace expires (or vice-versa), state remains `NOT_SEEN`. Mid-streak policy changes are prevented by freezing policy fingerprints per miss streak. |
| **IDENTITY-02-S06** | Aggregate multi-source canonical availability conservatively | **VERIFIED** | Implemented `compute_canonical_availability` in `aggregate.py`. Evaluates all linked source postings: if ANY source is `ACTIVE`, canonical is `ACTIVE`; else if ANY source is `NOT_SEEN`, canonical is `NOT_SEEN`; else if ANY source is `UNKNOWN` (or empty), canonical is `UNKNOWN`; only when ALL linked sources are `UNAVAILABLE` does canonical become `UNAVAILABLE`. Spans min `first_seen_at` and max `last_seen_at`. |
| **IDENTITY-02-S07** | Coordinate atomic replayable availability service and safe diagnostics | **VERIFIED** | Implemented `AvailabilityService` in `service.py`. Coordinates manifest receipt validation, positive sighting processing, baseline absence detection, canonical re-aggregation, and atomic transaction commits. Manifest replay is idempotent via `consumed_inventories`. Implemented safe diagnostic summary in `inspection.py` (`CanonicalAvailabilitySummary`) ensuring zero credential leakage. |
| **IDENTITY-02-S08** | Verify boundaries, crash recovery, native Windows execution, and handoff | **VERIFIED** | Verified contract boundaries, SQL/JSON projection consistency on frozen `CanonicalJob` models, non-mutation of candidate progress and C11 assessments, process termination / reopen, and native Windows paths with spaces and German umlauts (`Job Automation Verfügbarkeit Prüfung`, `Daten Größe`, `Test Daten ä`). All 56 focused tests and 636 regression tests pass with zero exit codes. |

---

## 3. Files Created and Modified

### Availability Package (`src/job_automation/identity/availability/`)
- [`src/job_automation/identity/availability/__init__.py`](../../src/job_automation/identity/availability/__init__.py): Public package exports (`AvailabilityService`, `PostingAvailability`, `AvailabilityPolicy`, `AvailabilityRuleSettings`, models, inspection).
- [`src/job_automation/identity/availability/errors.py`](../../src/job_automation/identity/availability/errors.py): Custom exception hierarchy (`AvailabilityError`, `AvailabilityConfigurationError`, `AvailabilityScopeError`, `AvailabilityConflictError`, `AvailabilityLedgerError`).
- [`src/job_automation/identity/availability/settings.py`](../../src/job_automation/identity/availability/settings.py): Policy validation rules (`AvailabilityRuleSettings`, `AvailabilityPolicy`, `load_availability_policy`, policy fingerprinting).
- [`src/job_automation/identity/availability/models.py`](../../src/job_automation/identity/availability/models.py): Domain models (`PostingAvailability`, `AvailabilityTransitionReason`, `SourcePostingAvailability`, `AvailabilityDecision`, `SourceChangeResult`, `CanonicalChangeResult`, `AvailabilityProcessResult`).
- [`src/job_automation/identity/availability/evidence.py`](../../src/job_automation/identity/availability/evidence.py): Manifest eligibility evaluation (`is_manifest_eligible_for_negative_inference`) and deterministic scope fingerprinting (`compute_manifest_fingerprint`).
- [`src/job_automation/identity/availability/rules.py`](../../src/job_automation/identity/availability/rules.py): Pure transition logic for positive sightings (`evaluate_sighting`) and qualifying misses (`evaluate_miss`).
- [`src/job_automation/identity/availability/aggregate.py`](../../src/job_automation/identity/availability/aggregate.py): Multi-source canonical aggregation rules (`compute_canonical_availability`).
- [`src/job_automation/identity/availability/inspection.py`](../../src/job_automation/identity/availability/inspection.py): Safe diagnostic data model (`CanonicalAvailabilitySummary`) and projection helper (`build_canonical_summary`).
- [`src/job_automation/identity/availability/service.py`](../../src/job_automation/identity/availability/service.py): `AvailabilityService` coordinating manifest ingestion, baseline comparison, ledger updates, canonical synchronization, and atomic transactions.

### Storage & Configuration Extensions (`src/job_automation/storage/` & `src/job_automation/`)
- [`src/job_automation/storage/migrations.py`](../../src/job_automation/storage/migrations.py): Added `MIGRATION_005_AVAILABILITY_TRACKING` (schema version 5) establishing `source_posting_availability`, `availability_decisions`, and `consumed_inventories` tables and performance indexes.
- [`src/job_automation/storage/repositories/availability.py`](../../src/job_automation/storage/repositories/availability.py): `AvailabilityRepository` providing CRUD, inventory deduplication, active baseline queries, and decision ledger logging.
- [`src/job_automation/storage/repositories/canonical_jobs.py`](../../src/job_automation/storage/repositories/canonical_jobs.py): Added `update_availability` method updating both relational columns and deserialized `job_json` projections via `model_copy(update={...})` in a single transaction.
- [`src/job_automation/storage/repositories/__init__.py`](../../src/job_automation/storage/repositories/__init__.py): Exported `AvailabilityRepository`.
- [`src/job_automation/storage/engine.py`](../../src/job_automation/storage/engine.py): Added cached `availability` repository property and connection cleanup.
- [`src/job_automation/configuration.py`](../../src/job_automation/configuration.py): Added `availability_policy_ref` and `availability_policy_path` fields to `AppConfiguration`.
- [`config/availability.example.json`](../../config/availability.example.json): Example availability policy configuration with defaults (threshold=3, grace=48h) and scoped overrides.
- [`config/app.example.json`](../../config/app.example.json): Referenced `config/availability.example.json`.

### Test Suites and Fixtures (`tests/identity/availability/` & `tests/fixtures/identity/availability/`)
- [`tests/fixtures/identity/availability/README.md`](../../tests/fixtures/identity/availability/README.md): Comprehensive fixture documentation for availability scenarios.
- 24 automated test modules in `tests/identity/availability/` (56 focused tests):
  - `test_contract_boundary.py` (5 tests: C04/C06/C07 contract boundaries, model immutability, enum mapping)
  - `test_settings.py` (8 tests: threshold $\ge 2$, finite grace, defaults, overrides, policy fingerprinting)
  - `test_manifest_evidence.py` (9 tests: complete vs partial, search-only, error blocking, chronology validation)
  - `test_scope_boundary.py` (2 tests: scope isolation, non-cross-scope baseline interference)
  - `test_repository.py` (4 tests: repository persistence, active baseline queries, decision append, inventory tracking)
  - `test_migrations.py` (1 test: migration 5 application, idempotency, table/index creation)
  - `test_transactions.py` (1 test: atomic rollback on fault injection, zero partial ledger writes)
  - `test_observations.py` (2 tests: positive sightings update `last_seen_at` and reset miss counters)
  - `test_reopening.py` (2 tests: reappearance reopens `unavailable` -> `active`, clears miss streak)
  - `test_baselines.py` (1 test: baseline enrollment on first complete inventory)
  - `test_miss_rules.py` (2 tests: first miss -> `not_seen`, consecutive misses increment)
  - `test_grace.py` (4 tests: grace conjunction, threshold without grace, grace without threshold, expiration)
  - `test_manifest_matrix.py` (2 tests: decision matrix for partial, failed, search, and complete runs)
  - `test_policy_changes.py` (1 test: frozen policy fingerprint per streak prevents shifting thresholds)
  - `test_multi_source.py` (2 tests: conservative aggregation truth table, single active source preserves canonical active)
  - `test_membership_changes.py` (1 test: merge and reversal recomputes canonical availability)
  - `test_protected_state.py` (1 test: candidate application progress, decisions, notes, and C11 assessments strictly unchanged)
  - `test_service.py` (1 test: end-to-end `AvailabilityService.process_manifest` lifecycle)
  - `test_replay.py` (2 tests: idempotent manifest replay, zero duplicate decisions)
  - `test_recovery.py` (1 test: recovery after simulated crash/restart)
  - `test_safe_diagnostics.py` (1 test: `CanonicalAvailabilitySummary` safe inspection, zero secrets leaked)
  - `test_integration.py` (1 test: end-to-end pipeline integration from ingestion manifests to canonical jobs)
  - `test_windows_paths.py` (1 test: paths with spaces, German umlauts, and long directory names)
  - `test_windows_restart.py` (1 test: sub-process execution, SQLite file-handle release, and database reopen)

---

## 4. Key Architectural Decisions (D01–D10)

1. **D01: Grounding in Real IDENTITY-01 Repositories and Interfaces**:
   - Integrated directly with `companies`, `source_identities`, `posting_observations`, and `canonical_jobs`.
   - Identified and handled composite source keys `(provider, board_id, source_posting_id)` rather than fragile un-scoped identifiers.
   - Handled re-parented revisions and merge reversals without creating synthetic source records or losing observation history.
2. **D02: Verified Scope Fingerprint vs Raw Provider Board Strings**:
   - Scope identity is grounded in deterministic fingerprinting (`compute_manifest_fingerprint`) comprising `provider`, `board_id`, canonical `scope_id`, feed type, and normalized query parameters.
   - Prevents conflating broad boards with query-filtered subsets (e.g. `remote=true` vs full catalog).
3. **D03: Durable Capture & Finality Boundary**:
   - Negative inference is strictly gated by `is_manifest_eligible_for_negative_inference`.
   - Requires `ManifestStatus.COMPLETE`, `FeedType.COMPLETE_BOARD`, zero errors (`error_count == 0`), non-empty timestamps, and `started_at <= completed_at`.
   - Ineligible manifests process positive sightings only; negative inference is strictly skipped with explicit reason codes logged.
4. **D04: Dual-Layer Availability Tracking (Source vs Canonical)**:
   - Tracks fine-grained source availability in `source_posting_availability` table with miss counters, grace anchors, and policy fingerprints.
   - Synchronizes aggregate canonical availability to `canonical_jobs.availability` and `canonical_jobs.job_json['availability']` using immutable Pydantic `model_copy`.
   - Historical `PostingRevision` content and quotes remain immutable.
5. **D05: Conservative Threshold & Grace Period Conjunction**:
   - Default policy: `consecutive_misses_threshold = 3`, `grace_seconds = 172800.0` (48 hours).
   - Closing a posting (`UNAVAILABLE`) strictly requires both conditions: `miss_count >= threshold` AND `elapsed_seconds >= grace_seconds`.
   - Policy fingerprints are captured at the start of a miss streak and frozen until the streak completes or resets, preventing policy edits from unfairly closing jobs retroactively.
6. **D06: Multiple Scopes and Isolation**:
   - Baselines are scoped by `scope_id`. Missing a posting in Scope B does not record a miss against Scope A.
   - Renaming source registry keys does not invalidate underlying board identity when provider and board parameters match.
7. **D07: Idempotent Manifest Replay and Duplicate Prevention**:
   - Processed manifests record entry in `consumed_inventories` keyed by `manifest_fingerprint`.
   - Replaying an already-consumed manifest is a safe no-op that yields an empty result set and appends zero duplicate decisions to `availability_decisions`.
8. **D08: Conservative Canonical Aggregation Precedence**:
   - Evaluates multi-source linkages strictly:
     $$\text{ACTIVE} \succ \text{NOT\_SEEN} \succ \text{UNKNOWN} \succ \text{UNAVAILABLE}$$
   - As long as at least one linked source posting remains `ACTIVE`, the `CanonicalJob` remains `ACTIVE`.
   - A vacancy only becomes `UNAVAILABLE` when every single linked source is confirmed unavailable.
9. **D09: Non-Mutation of Candidate and Application Progress**:
   - Candidate state (application status like `Applied` or `Interviewing`, user decisions, candidate notes, and C11 assessments) is strictly immutable by availability operations.
   - When a job becomes `unavailable`, candidate applications remain active for tracking and interview preparation.
10. **D10: Complete Audit Ledger and Safe Diagnostics**:
    - Every source and canonical transition is recorded in the immutable `availability_decisions` ledger with transition reason, miss count, elapsed grace, policy fingerprint, and UTC timestamp.
    - Diagnostics are exposed via `CanonicalAvailabilitySummary` with sanitized URLs, credential redaction, and bounded reason codes.

---

## 5. Walkthrough of Critical Availability Scenarios

### Scenario 1: Partial / Failed Fetches (No Negative Inference)
- **Input**: Ingestion run for board `arbeitnow` encounters a network error on page 3 or is cancelled mid-run (`status = FAILED` or `PARTIAL`).
- **Behavior**: `is_manifest_eligible_for_negative_inference` inspects manifest status and error count, returning `(False, "STATUS_INCOMPLETE")` or `(False, "ERRORS_RECORDED")`.
- **Outcome**:
  - Positive sightings on pages 1–2 are processed normally (updating `last_seen_at`).
  - Negative absence comparison is skipped entirely.
  - Zero misses are recorded; active postings absent from the partial run remain `active`.

### Scenario 2: Search-Only Feeds / Query-Filtered Manifests
- **Input**: User runs an ad-hoc query `python -m job_automation ingest --query "python developer"` (`feed_type = SEARCH_RESULTS`).
- **Behavior**: `is_manifest_eligible_for_negative_inference` verifies `feed_type == FeedType.COMPLETE_BOARD`. Returns `(False, "NOT_COMPLETE_BOARD")`.
- **Outcome**:
  - Unseen postings on the board are never penalized for being absent from a targeted search.
  - Positive search results update observation timestamps without altering baseline eligibility.

### Scenario 3: Scope Changes (Baseline Enrollment)
- **Input**: Employer board transitions from scope `de_tech` to `eu_all`.
- **Behavior**: Postings previously enrolled in `de_tech` are not compared against the baseline of `eu_all` until they are observed within `eu_all`.
- **Outcome**:
  - Independent baselines prevent cross-scope miss carryovers.
  - No false closures due to scope reconfiguration.

### Scenario 4: Repeated Misses and Grace Period Conjunction
- **Input**: Active posting $P$ on a daily complete crawl with policy `threshold = 3`, `grace = 48h`.
  - Day 1 ($t_0$): $P$ is absent. Miss count becomes 1. State transitions `active` $\to$ `not_seen`. Anchor `first_missed_at` is set to $t_0$.
  - Day 2 ($t_0 + 24\text{h}$): $P$ is absent. Miss count becomes 2. Elapsed is 24h (< 48h). State remains `not_seen`.
  - Day 3 ($t_0 + 48\text{h}$): $P$ is absent. Miss count becomes 3 ($\ge 3$), elapsed is 48h ($\ge 48\text{h}$).
- **Behavior**: Conjunction of both `miss_count >= 3` AND `elapsed >= 48h` is satisfied.
- **Outcome**:
  - State transitions `not_seen` $\to$ `unavailable`.
  - Reason code `CONSECUTIVE_MISSES_AND_GRACE_EXPIRED` recorded in audit ledger.

### Scenario 5: Reappearing Postings (Reopening)
- **Input**: Posting $P$ marked `unavailable` reappears on the board 2 weeks later.
- **Behavior**: `evaluate_sighting` processes positive observation.
- **Outcome**:
  - State immediately transitions `unavailable` $\to$ `active`.
  - `consecutive_misses` reset to 0; `first_missed_at` reset to `None`.
  - Canonical job re-evaluates to `active`.
  - Audit record created with reason `REAPPEARED`.

### Scenario 6: Multiple Linked Sources (Canonical Aggregation)
- **Input**: Canonical job $J$ linked to Source A (Arbeitnow) and Source B (Company Direct).
  - Source A misses 3 complete inventories and exceeds grace $\to$ Source A becomes `unavailable`.
  - Source B is observed today $\to$ Source B is `active`.
- **Behavior**: `compute_canonical_availability` evaluates all linked sources: Source B is `active`.
- **Outcome**:
  - Canonical job $J$ remains `active`.
  - Prevents premature vacancy closure while an alternate recruitment channel is actively listing the role.

### Scenario 7: Preservation of Candidate State
- **Input**: Candidate applied to Canonical Job $J$; application status is `Applied`, decision is `Pursue`, candidate note is `"Spoke with recruiter on Tuesday"`, and C11 Assessment score is `0.88`. Later, Job $J$ transitions to `unavailable`.
- **Behavior**: Availability engine executes narrow `update_availability` on `canonical_jobs`.
- **Outcome**:
  - Only `availability` and `last_seen_at` are modified.
  - Candidate application status remains `Applied`.
  - Candidate decisions, notes, and assessment records remain 100% unaltered.

---

## 6. Native Windows Verification Evidence

The full verification recipe from `docs/stories/IDENTITY-02.md` was executed on native Windows 11 with isolated temporary directories containing spaces and non-ASCII German characters (`Job Automation Verfügbarkeit Prüfung`, `Daten Größe`, `Test Daten ä`):

```powershell
$identity02Repo = (Resolve-Path '.').Path
$identity02Python = Join-Path $identity02Repo '.venv\Scripts\python.exe'
$identity02Config = Join-Path $identity02Repo 'config\app.example.json'
$identity02Tests = Join-Path $identity02Repo 'tests\identity\availability'
$identity02Temp = Join-Path $env:TEMP ('Job Automation Verfügbarkeit Prüfung ' + [guid]::NewGuid().ToString())
$identity02Data = Join-Path $identity02Temp 'Daten Größe'

& $identity02Python -c "import platform, sys, sqlite3; from zoneinfo import ZoneInfo; print(platform.platform()); print(sys.version); print(sqlite3.sqlite_version); print(ZoneInfo('Europe/Berlin'))"
$identity02EnvironmentExit = $LASTEXITCODE
& $identity02Python -m pip show pydantic pytest tzdata
$identity02VersionsExit = $LASTEXITCODE
& $identity02Python -m pytest $identity02Tests
$identity02FocusedExit = $LASTEXITCODE
& $identity02Python -m pytest (Join-Path $identity02Repo 'tests\contracts') (Join-Path $identity02Repo 'tests\storage') (Join-Path $identity02Repo 'tests\sources') (Join-Path $identity02Repo 'tests\ingestion') (Join-Path $identity02Repo 'tests\test_configuration.py') (Join-Path $identity02Repo 'tests\test_cli_storage.py')
$identity02BoundaryExit = $LASTEXITCODE

New-Item -ItemType Directory -Path $identity02Temp | Out-Null
Push-Location $identity02Temp
try {
    & $identity02Python -m job_automation storage migrate --config $identity02Config --data-root $identity02Data
    $identity02MigrationExit = $LASTEXITCODE
    & $identity02Python -m job_automation storage status --config $identity02Config --data-root $identity02Data
    $identity02StatusExit = $LASTEXITCODE
    & $identity02Python -m pytest (Join-Path $identity02Tests 'test_windows_paths.py') (Join-Path $identity02Tests 'test_windows_restart.py') --basetemp (Join-Path $identity02Temp 'Test Daten ä')
    $identity02WindowsExit = $LASTEXITCODE
} finally {
    Pop-Location
}

& $identity02Python -m pytest (Join-Path $identity02Repo 'tests')
$identity02RegressionExit = $LASTEXITCODE
[pscustomobject]@{
    EnvironmentExit = $identity02EnvironmentExit
    VersionsExit = $identity02VersionsExit
    FocusedExit = $identity02FocusedExit
    BoundaryExit = $identity02BoundaryExit
    MigrationExit = $identity02MigrationExit
    StatusExit = $identity02StatusExit
    WindowsExit = $identity02WindowsExit
    RegressionExit = $identity02RegressionExit
}
```

### Actual Verification Results:

```
Platform: Windows-11-10.0.26300-SP0
Python:   3.12.10 (tags/v3.12.10:0cc8128, Apr  8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]
SQLite:   3.49.1
Timezone: Europe/Berlin

Installed Packages:
- pydantic: 2.14.1
- pytest:   8.4.2
- tzdata:   2026.5

Storage Migration Output:
Storage migration: SUCCESS
  Database Path:     C:\Users\mrite\AppData\Local\Temp\Job Automation Verfügbarkeit Prüfung 4b0b8872-dce7-482b-ab9e-382ca93e9292\Daten Größe\database\job_automation.db
  Newly Applied:     [1, 2, 3, 4, 5]
  Current Version:   5
Storage status: OK
  Database Path:     C:\Users\mrite\AppData\Local\Temp\Job Automation Verfügbarkeit Prüfung 4b0b8872-dce7-482b-ab9e-382ca93e9292\Daten Größe\database\job_automation.db
  Current Version:   5
  Applied Count:     5
    v1 (001_initial): applied at 2026-10-28T16:07:41.360547+00:00
    v2 (002_stage_checkpoints_and_audit): applied at 2026-10-28T16:07:41.361546+00:00
    v3 (003_profile_evidence_and_snapshots): applied at 2026-10-28T16:07:41.363550+00:00
    v4 (004_identity_tracking_and_lineage): applied at 2026-10-28T16:07:41.364632+00:00
    v5 (005_availability_tracking): applied at 2026-10-28T16:07:41.365634+00:00

Test Suite Results:
- tests\identity\availability (Focused): 56 passed in 2.76s
- Boundary & Storage Tests:            428 passed in 5.84s
- Windows Path & Restart Tests:          2 passed in 1.20s
- Full Regression Suite:               636 passed in 19.67s

Recorded Exit Codes:
EnvironmentExit : 0
VersionsExit    : 0
FocusedExit     : 0
BoundaryExit    : 0
MigrationExit   : 0
StatusExit      : 0
WindowsExit     : 0
RegressionExit  : 0
```

---

## 7. Downstream Consumer Handoff

IDENTITY-02 produces durable posting and canonical availability state consumed by downstream components:

1. **RUN-01 (Pipeline Orchestration & Daily Ingestion)**:
   - Orchestrates the end-to-end ingestion cycle: fetch $\to$ normalize $\to$ identity $\to$ availability.
   - Passes finalized `RunManifest` and normalized postings to `AvailabilityService.process_manifest`.
   - Consumes `AvailabilityProcessResult` containing `source_changes`, `canonical_changes`, and `decisions_logged` for run reporting and metrics.
2. **MATCH-01 (Job Matching & Eligibility Filtering)**:
   - Evaluates match criteria exclusively against `CanonicalJob.availability == PostingAvailability.ACTIVE`.
   - Filters out `unavailable` jobs from new candidate recommendation batches while preserving existing candidate evaluations.
3. **SYNC-01 (External CRM / Salesforce Synchronization)**:
   - Synchronizes posting status (`active`, `closed`/`unavailable`) to remote job tracking entities.
   - Reads `CanonicalJob.availability` and `availability_decisions` audit trail to detect state changes requiring outbound push.
   - Guarantees that external application progress records (`Applied`, `Interviewing`) are never overwritten when a posting closes.
4. **OPS-01 / Diagnostic CLI**:
   - Uses `build_canonical_summary` from `inspection.py` to display posting lifecycle and availability health in operator dashboards without exposing raw authentication secrets or malformed URLs.

