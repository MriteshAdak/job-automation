# Component Handoff: INGEST-01 — Fetch Controller

Component ID: **INGEST-01**  
Status: **VERIFIED**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Prerequisite Handoffs: [docs/components/DATA-01.md](DATA-01.md), [docs/components/SOURCE-02.md](SOURCE-02.md), [docs/components/SOURCE-01.md](SOURCE-01.md), [docs/components/FND-01.md](FND-01.md)  
Planning Reference: [docs/stories/INGEST-01.md](../stories/INGEST-01.md)  
Date Completed: 28 October 2026  
Direct Covered Requirements: [R02](../../IMPLEMENTATION_BLUEPRINT.md#r02) (permitted acquisition with honest coverage), [R09](../../IMPLEMENTATION_BLUEPRINT.md#r09) (durable raw processing state), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16) (bounded recoverable execution).  
Supporting constraints: [R03](../../IMPLEMENTATION_BLUEPRINT.md#r03) (raw provenance and C05 mapping handoff), [R04](../../IMPLEMENTATION_BLUEPRINT.md#r04) (preserve scoped identities and repeated observations without canonical deduplication), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14) (native Windows), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15) (safe access, credentials and untrusted data).

---

## 1. Prerequisites and Upstream Dependencies Verification

Before implementing INGEST-01, upstream foundational contracts, storage engines, and adapter interfaces were verified:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **Storage Engine & Migrations** | DATA-01 | **VERIFIED** | Reused `StorageEngine`, SQLite PRAGMA configuration, migrations 1–3, `RunLedgerRepository`, and `RawPostingRepository`. Verified that SQLite connection operates in atomic blocks via `with storage.conn:`. |
| **Adapter Protocol Boundary** | SOURCE-02 | **VERIFIED** | Reused `Adapter` protocol: `fetch_page(config, continuation=None) -> AdapterPage` and `draft_posting(raw) -> DraftResult`. Reused auxiliary contracts (`AdapterPage`, `Continuation`, `RecordIssue`, `DraftResult`). Reused `RawCaptureSink` protocol, `ManualTextAdapter`, and `ManualCsvAdapter`. |
| **Checked Selection & EffectiveSource** | SOURCE-01 | **VERIFIED** | Reused `SourceRegistryService.select_sources` atomic preflight validation. Enforces that invalid requested selections reject before any network or storage actions. |
| **Concrete Provider Adapter** | SOURCE-03 | **VERIFIED** | Reused concrete `ArbeitnowAdapter` from `src/job_automation/sources/adapters/arbeitnow.py` for live end-to-end verification. |

---

## 2. Implementation Summary by Story

All nine planned stories from `docs/stories/INGEST-01.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **INGEST-01-S01** | Freeze controller boundary and dependency decisions | **VERIFIED** | Established local data models (`ControllerOptions`, `AttemptRecord`, `PageReceipt`, `SourceCheckpoint`, `CacheEntry`, `SourceFetchResult`, `FetchStageResult`) in `models.py`. Defined injected clock (`ClockProtocol`, `SystemClock`) and sleeper (`SleeperProtocol`, `SystemSleeper`) in `ports.py`. Established `AdapterRegistry` mapping sources to factories with zero untrusted class imports. |
| **INGEST-01-S02** | Durable capture and atomic page commits | **VERIFIED** | Implemented `DurableRawCaptureSink` in `capture.py` writing exact unmutated bytes atomically via `.tmp` files with SHA-256 verification and path traversal rejection. Implemented `PagePersistenceManager` in `persistence.py` committing raw postings and checkpoints in a single SQLite transaction with fault-injection rollback verification. |
| **INGEST-01-S03** | Execute checked adapters and retain C05 results | **VERIFIED** | Implemented `PageExecutor` in `execution.py`. Enforces provider/board identity checks, isolates foreign records, maps drafts through `draft_posting`, reconciles record issues, and catches adapter exceptions safely without secret leakage. |
| **INGEST-01-S04** | Enforce request limits, bounded retries and timeouts | **VERIFIED** | Implemented `RequestBudget` (stricter cap precedence between source policy and options, monotonic deadlines) and `DomainRateLimiter` (inter-request spacing per domain) in `request_control.py`. Implemented error classification, exponential backoff, and HTTP-date/seconds `Retry-After` parsing in `retry.py`. |
| **INGEST-01-S05** | Bounded pagination traversal and checkpoint resumption | **VERIFIED** | Implemented `PaginationTraverser` in `pagination.py`. Traverses intermediate pages, bounds pages/requests/deadlines, detects pagination cycles via visited tokens, and accumulates prior-segment evidence on resume without advancing checkpoints past uncommitted evidence. |
| **INGEST-01-S06** | Cache captured pages without fabricating fresh inventory | **VERIFIED** | Implemented `PageCache` in `cache.py`. Generates deterministic SHA-256 cache keys, enforces TTL expiry, verifies payload file existence and hashes before hit, and strictly projects any traversal reusing cached pages as `PARTIAL` (`cache_reuse`), never `COMPLETE`. |
| **INGEST-01-S07** | Honest, idempotent C04 manifests | **VERIFIED** | Implemented `build_fetch_manifest` and `finalize_manifest` in `manifests.py`. Pure projection enforcing exact outcome rules (`COMPLETE`, `PARTIAL`, `FAILED`), preserving exact posting ID strings (leading zeros), encoding cursors (`cont-v1:...`), and ensuring idempotent SQLite finalization. |
| **INGEST-01-S08** | Runtime source failure isolation & stage aggregation | **VERIFIED** | Implemented `FetchController` in `controller.py`. Enforces atomic preflight selection, executes sources sequentially in isolated contexts (failure of source B never rolls back or invalidates sources A or C), and produces comprehensive `FetchStageResult` metrics. |
| **INGEST-01-S09** | Native Windows verification, restart checks & live smoke | **VERIFIED** | Implemented `test_windows_paths.py` (paths with spaces and German umlauts `Prüfung äöü`, handle release), `test_windows_restart.py` (child process interruption and resumption across separate native Python processes), and `tests/manual/ingest_smoke.py` (bounded live fetch against Arbeitnow API). |

---

## 3. Files Created and Modified

### Ingestion Component Package (`src/job_automation/ingestion/`)
- [`src/job_automation/ingestion/__init__.py`](../../src/job_automation/ingestion/__init__.py): Public package exports.
- [`src/job_automation/ingestion/models.py`](../../src/job_automation/ingestion/models.py): Local typed models (`ControllerOptions`, `AttemptRecord`, `PageReceipt`, `SourceCheckpoint`, `CacheEntry`, `SourceFetchResult`, `FetchStageResult`).
- [`src/job_automation/ingestion/ports.py`](../../src/job_automation/ingestion/ports.py): Protocols (`ClockProtocol`, `SleeperProtocol`), implementations (`SystemClock`, `SystemSleeper`), and `AdapterRegistry`.
- [`src/job_automation/ingestion/capture.py`](../../src/job_automation/ingestion/capture.py): `DurableRawCaptureSink` file-backed byte capture implementation.
- [`src/job_automation/ingestion/persistence.py`](../../src/job_automation/ingestion/persistence.py): `PagePersistenceManager` atomic SQLite commit manager.
- [`src/job_automation/ingestion/execution.py`](../../src/job_automation/ingestion/execution.py): `PageExecutor` single-page execution and C05 drafting bridge.
- [`src/job_automation/ingestion/request_control.py`](../../src/job_automation/ingestion/request_control.py): `RequestBudget` and `DomainRateLimiter`.
- [`src/job_automation/ingestion/retry.py`](../../src/job_automation/ingestion/retry.py): Recoverable error classifier, backoff calculator, and `Retry-After` parser.
- [`src/job_automation/ingestion/cache.py`](../../src/job_automation/ingestion/cache.py): `PageCache` persistent cache manager.
- [`src/job_automation/ingestion/manifests.py`](../../src/job_automation/ingestion/manifests.py): C04 `FetchManifest` projection and idempotent SQLite finalization.
- [`src/job_automation/ingestion/pagination.py`](../../src/job_automation/ingestion/pagination.py): `PaginationTraverser` pagination loop and checkpointing.
- [`src/job_automation/ingestion/controller.py`](../../src/job_automation/ingestion/controller.py): `FetchController` multi-source ingestion coordinator.

### Test Suites and Tools (`tests/ingestion/` & `tests/manual/`)
- [`tests/fixtures/ingestion/README.md`](../../tests/fixtures/ingestion/README.md): Fixture and synthetic evidence catalog.
- [`tests/ingestion/__init__.py`](../../tests/ingestion/__init__.py): Test package marker.
- [`tests/sources/__init__.py`](../../tests/sources/__init__.py): Test package marker.
- 24 test modules in `tests/ingestion/` (56 automated tests):
  - `test_contract_boundary.py`, `test_capture.py`, `test_page_commit.py`, `test_observation_replay.py`, `test_execution.py`, `test_manual_integration.py`, `test_request_limits.py`, `test_retries.py`, `test_timeouts.py`, `test_safe_diagnostics.py`, `test_pagination.py`, `test_resume.py`, `test_crash_boundaries.py`, `test_cache.py`, `test_cache_invalidation.py`, `test_cache_completeness.py`, `test_manifests.py`, `test_manifest_finalization.py`, `test_inventory_boundary.py`, `test_source_isolation.py`, `test_fetch_stage_results.py`, `test_controller_integration.py`, `test_windows_paths.py`, `test_windows_restart.py`.
- [`tests/manual/ingest_smoke.py`](../../tests/manual/ingest_smoke.py): Opt-in live smoke verification tool for `FetchController` + `ArbeitnowAdapter`.

---

## 4. Key Architectural Decisions (D01–D10)

1. **D01: Adapter Protocol Boundary & Injected Ports**:
   - Reused the `Adapter` protocol unchanged (`fetch_page` returning `AdapterPage`, `draft_posting` returning `DraftResult`).
   - Injected clocks (`ClockProtocol`) and sleepers (`SleeperProtocol`) decouple business logic from real-time and network in unit tests.
2. **D02: Immutable Byte Publication**:
   - `DurableRawCaptureSink` stores original, unmutated bytes beneath `<raw_dir>/captures/<sanitized_hint>_<hex16>.dat`.
   - Atomic writes via temporary hidden files (`.tmp_*.dat`) prevent partially written payloads. Content hashes (`sha256:<hex64>`) are verified on retrieval.
3. **D03: Atomic Page & Checkpoint Persistence**:
   - `PagePersistenceManager` performs raw posting insertions and checkpoint updates within a single outer `with storage.conn:` transaction block.
   - Tested and verified via fault injection: a failure rolls back both raw posting insertions and checkpoint advancement atomically.
4. **D04: Honest Manifest Completeness Invariants**:
   - `COMPLETE`: requires valid traversal from beginning (`cursor_in=None`), terminal exhaustion reached, all pages committed, zero truncation, zero page errors, zero cache reuse, and no blocking record errors.
   - `PARTIAL`: emitted on page cap reached, request limit reached, monotonic deadline exceeded, recoverable error exhausted after progress, or any page served from cache.
   - `FAILED`: emitted when an unrecoverable error occurs before usable progress.
5. **D05: Finite Budgets & Precedence Rules**:
   - Strict budget precedence: between source-level policy and caller options, the more restrictive cap always wins.
   - Booleans are rejected for integer budgets before coercion.
6. **D06: Cache Invalidation & Partial Semantics**:
   - Reusing cached pages can never prove fresh current inventory. Any traversal reusing cached pages produces a `PARTIAL` C04 manifest with a `"cache_reuse"` diagnostic reason.
   - Missing or tampered raw files on disk invalidate the cache entry immediately.
7. **D07: Idempotent Authoritative Finalization**:
   - `finalize_manifest` performs an idempotent upsert on `(run_id, source_key, scope_id)`.
   - Repeated calls or resumed segments update the authoritative record rather than creating conflicting duplicate manifests.
8. **D08: Safe Diagnostics & Credential Redaction**:
   - Diagnostics in `PageReceipt` and `ClassifiedError` redact query parameters, secrets, and authorization headers.
9. **D09: Independent Runtime Source Failure Isolation**:
   - Sequential source execution with per-source database transaction and error handling boundaries.
   - A runtime failure in one source (e.g. 403 Forbidden on Source B) is recorded as `FAILED` for Source B while Source A and Source C remain `COMPLETE` with all raw postings intact.
10. **D10: Strict Inventory Boundaries**:
    - INGEST-01 persists raw postings and manifests only. It does NOT perform canonical job deduplication, does NOT update canonical job statuses, and does NOT infer job closure or deletion (owned by IDENTITY-01 / IDENTITY-02).

---

## 5. Verification Commands and Actual Results

### Native Windows Execution Environment
- **Platform**: Windows 11 (10.0.26300-SP0), AMD64
- **Python**: 3.12.10 (tags/v3.12.10:0cc8128, 64-bit)
- **Key Packages**: `pydantic==2.14.1`, `pytest==8.4.2`, `tzdata==2026.5`

### 1. Focused Component Test Suite
```powershell
.\.venv\Scripts\python.exe -m pytest tests/ingestion tests/contracts tests/sources tests/storage
```
**Result**: `349 passed in 3.26s`

### 2. Native Windows Recipe Execution (Umlauts, Spaces & CWD Switch)
Executed with `Push-Location` in temporary directory `Job Automation Prüfung ä INGEST-01 <guid>` with basetemp `Daten Größe`:
```powershell
Push-Location $ingest01TempRoot
.\.venv\Scripts\python.exe -m pytest tests/ingestion/test_windows_paths.py tests/ingestion/test_windows_restart.py --basetemp (Join-Path $ingest01TempRoot 'Daten Größe')
Pop-Location
```
**Result**: `2 passed in 1.48s` (verified handle release, SQLite locks, process interruption and resume across child processes).

### 3. Full Repository Regression Suite
```powershell
.\.venv\Scripts\python.exe -m pytest tests
```
**Result**: `472 passed in 9.41s` (100% pass across all repository tests).

### 4. Live External API Smoke Verification
Executed `tests/manual/ingest_smoke.py` against live `https://www.arbeitnow.com/api/job-board-api` with bounded envelope (max 1 page, 30s timeout, 10 MiB cap):
```powershell
.\.venv\Scripts\python.exe tests/manual/ingest_smoke.py --data-dir "local_data/ingest_smoke_live" --max-pages 1
```
**Actual Live Output**:
```text
========================================================================
INGEST-01 FetchController Live Verification with ArbeitnowAdapter
Timestamp (UTC): 2026-10-28T13:09:50.050821+00:00
Data directory:  local_data\ingest_smoke_live
Max pages cap:   1 (bounded upper limit: 2)
========================================================================

Executing FetchController.run_fetch ...

Fetch execution finished.
Sources attempted: 1
Sources completed: 0
Sources partial:   1
Sources failed:    0
Total requests:    1
Total pages:       1
Total raw records: 300
Unique identities: 300

Authoritative C04 Manifest:
  Run ID:        b6b5ff75-0a80-41f2-bac5-6c7f8522a609
  Source key:    arbeitnow_de
  Scope ID:      arbeitnow_default
  Outcome:       partial
  Page count:    1
  Identities:    300
  Raw refs:      1
  Cursor in:     None
  Cursor out:    cont-v1:eyJhZGFwdGVyX25hbWUiOiJhcmJlaXRub3ctdjEiLCJpbnB1dF9oYXNoIjpudWxsLCJraW5kIjoicGFnZSIsIm9wdGlvbnNfaGFzaCI6bnVsbCwic2NoZW1hX3ZlcnNpb24iOiIxLjAiLCJzY29wZV9pZCI6InNjb3BlLXYxOnNoYTI1Njo0YjM2OTgwZTc0NGE1MjNlNmNhNzA4ZDZkNDEwMzVkYzFkYTdiYjQ2ZjUyZTc0MTI0ZDA2Y2M0Y2E5OGU5NDFmIiwic291cmNlX2tleSI6ImFyYmVpdG5vd19kZSIsInZhbHVlIjoiMiJ9
  Error:         None

[OK] Manifest verified in SQLite fetch_manifests table.
[OK] Raw capture file verified on disk: local_data\ingest_smoke_live\raw\captures\arbeitnow_page_1_f2bd1032153663a8.dat (2622269 bytes)

[SUCCESS] INGEST-01 Live Smoke Verification completed successfully.
```

---

## 6. Downstream Handoff Instructions and Integration Gaps

### Interfaces for Next Components
1. **INGEST-02 (Common Normalization & Validation)**:
   - Consumes C05 `RawPosting` records and `SourceJobDraft` objects produced and persisted by `FetchController`.
   - Normalizes titles, locations, compensation, and descriptions into C06 `NormalizedPosting`, quarantine-routing records with critical schema or vocabulary defects.
2. **IDENTITY-01 (Canonical Posting Identification & Dedup)**:
   - Evaluates unique posting identities preserved in C04 `FetchManifest.observed_posting_identities` and C05 records.
   - Performs canonical job clustering, deduplication, and revision tracking across different sources and runs.
3. **IDENTITY-02 (Availability & Closure Tracking)**:
   - Evaluates C04 `FetchManifest` records to track vacancy availability.
   - Respects honest completeness invariants: only a `COMPLETE` manifest over a verified `COMPLETE_BOARD` inventory scope may be used as disappearance evidence for job closure. `PARTIAL`, `FAILED`, `SEARCH_RESULTS`, or `FILTERED_FEED` manifests must never be used to infer vacancy closure.
4. **RUN-01 (Orchestration Pipeline & CLI)**:
   - Controls top-level `run_id` lifecycle, process locking, worker concurrency, and stage sequencing.
   - Calls `FetchController.run_fetch(run_id=..., source_keys=...)` and consumes `FetchStageResult` for pipeline progress tracking.

### Confirmed Constraints & Exclusions
- **No Deduplication**: Raw postings are preserved as sighted; deduplication is strictly owned by IDENTITY-01.
- **No Job Closure Inference**: Manifest completeness is recorded honestly; availability transitions are strictly owned by IDENTITY-02.
- **No Canonical Job Mutations**: The `canonical_jobs` table is not queried or modified by INGEST-01.

