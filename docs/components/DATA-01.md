# Component Handoff: DATA-01 — Storage, Migrations, and Run Ledger

Component ID: **DATA-01**  
Status: **VERIFIED**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Prerequisite Handoff: [docs/components/FND-01.md](FND-01.md)  
Planning Reference: `docs/stories/DATA-01.md` (Note: not present in repository; requirements derived directly from Blueprint §2 R04/R09/R16, §3, §4, §5, §6/DATA-01, §8, §9, §10, and FND-01 guidance)  
Date Completed: 27 October 2026  
Direct Covered Requirements: [R04](../../IMPLEMENTATION_BLUEPRINT.md#r04), [R09](../../IMPLEMENTATION_BLUEPRINT.md#r09), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16)  

---

## 1. Prerequisites and Contract Verification

Before implementation, all required upstream contracts established by **FND-01** were inspected and verified:

| Contract / Prerequisite | Found In | Version | Verification Status | Notes |
|---|---|---|---|---|
| **C01 ProfileSnapshot** | `job_automation.contracts.profile` | 1.0 | **VERIFIED** | Preserved precision dates, facts, allowed uses. |
| **C02 SearchPolicy** | `job_automation.contracts.policy` | 1.0 | **VERIFIED** | Search policy criteria, preferences, aliases. |
| **C03 SourceConfig** | `job_automation.contracts.sources` | 1.0 | **VERIFIED** | Provider, board_id, inventory semantics. |
| **C04 FetchManifest** | `job_automation.contracts.postings` | 1.0 | **VERIFIED** | Run ID, source scope, cursor, observed IDs. |
| **C05 RawPosting / SourceJobDraft** | `job_automation.contracts.postings` | 1.0 | **VERIFIED** | Source key, raw payload ref, content hash. |
| **C06 NormalizedPosting** | `job_automation.contracts.postings` | 1.0 | **VERIFIED** | Title, location, workplace type, provenance. |
| **C07 CanonicalJob / PostingRevision** | `job_automation.contracts.identity` | 1.0 | **VERIFIED** | Canonical ID, revisions, merge lineage. |
| **C08 EvidenceReference** | `job_automation.contracts.evidence` | 1.0 | **VERIFIED** | Candidate vs job evidence discriminators. |
| **C09 ContextBundle** | `job_automation.contracts.context` | 1.0 | **VERIFIED** | JSON/RAG context strategy models. |
| **C10 ModelCall / ModelResult** | `job_automation.contracts.models` | 1.0 | **VERIFIED** | Local model execution metadata & tokens. |
| **C11 Assessment** | `job_automation.contracts.assessment` | 1.0 | **VERIFIED** | Hard rules, relevance score, disposition. |
| **C12 SyncOperation / SyncPayload** | `job_automation.contracts.sync` | 1.0 | **VERIFIED** | Machine-owned sync fields, attempt counts. |
| **C13 GenerationRequest / FrozenInputVersions** | `job_automation.contracts.generation` | 1.0 | **VERIFIED** | Durable generation request, claimed state. |
| **C14 DraftDocument / Artifact** | `job_automation.contracts.artifacts` | 1.0 | **VERIFIED** | Structured claims, physical file artifact. |
| **C15 RunSummary** | `job_automation.contracts.runs` | 1.0 | **VERIFIED** | Pipeline metrics with explicit counter units. |
| **8 State Domain Enums** | `job_automation.contracts.enums` | 1.0 | **VERIFIED** | Independent lifecycle state domains. |
| **ClassifiedError & Primitives** | `job_automation.contracts.errors`, `primitives` | 1.0 | **VERIFIED** | SourceKey tuple, ContentHash, UtcDatetime. |
| **Configuration & ResolvedPaths** | `job_automation.configuration` | 1.0 | **VERIFIED** | Database path, raw dir, artifacts dir. |

**Missing Prerequisite Report**: Zero missing prerequisites. All required contracts and configuration interfaces exist and conform to the Blueprint.

---

## 2. Implementation Summary

DATA-01 implements the durable persistence, schema migrations, and ledger recovery layer for the application on native Windows:

| Story / Focus Area | Description | Status | Verification Summary |
|---|---|---|---|
| **DATA-01-S01** | Database connection, WAL mode & PRAGMAs | **VERIFIED** | `open_connection` with `PRAGMA foreign_keys = ON;`, `journal_mode = WAL;`, `busy_timeout = 5000;`, `synchronous = NORMAL;`. Tested with native Windows paths containing spaces and German umlauts (`Prüfung äöü`). |
| **DATA-01-S02** | Versioned schema migrations | **VERIFIED** | `apply_migrations` runner with `schema_migrations` tracking table, checksum verification, and atomic transaction rollback on failure. Migrations `001_initial` and `002_stage_checkpoints_and_audit` applied and verified. |
| **DATA-01-S03** | Bulky raw & artifact filestore | **VERIFIED** | `Filestore` manages large raw payloads beneath `raw_dir` and binary DOCX/PDF artifacts beneath `artifacts_dir` referenced by hash/path. Implements Windows path sanitization for characters like `[<>:"/\\|?*]`. |
| **DATA-01-S04** | Run ledger & stage checkpoints | **VERIFIED** | `RunLedgerRepository` manages C15 `RunSummary`, pipeline stage transitions (`PipelineStage`), granular stage checkpoints (`pipeline_checkpoints`), and crash recovery. |
| **DATA-01-S05** | Raw postings & fetch manifests | **VERIFIED** | `RawPostingRepository` manages C04 `FetchManifest` and C05 `RawPosting`, strictly enforcing source uniqueness on `(provider, board_id, source_posting_id)`. |
| **DATA-01-S06** | Normalized postings & canonical jobs | **VERIFIED** | `CanonicalJobRepository` manages C06 `NormalizedPosting`, C07 `CanonicalJob`, and `PostingRevision`, enforcing unique constraints and revision lineage. |
| **DATA-01-S07** | Job assessments & atomic sync outbox | **VERIFIED** | `AssessmentRepository` and `SyncOutboxRepository` (C11, C12). Implements `atomic_commit_assessment_and_sync` guaranteeing atomic persistence of an assessment with its corresponding pending Salesforce sync write. |
| **DATA-01-S08** | Generation requests & artifacts | **VERIFIED** | `GenerationRequestRepository` (C13) and `ArtifactRepository` (C14) managing request claiming, frozen input snapshots, delivery status tracking, and unfinished request recovery. |
| **DATA-01-S09** | CLI storage commands | **VERIFIED** | Extended CLI with `storage migrate` and `storage status` commands reporting applied versions and timestamps with safe diagnostic exit codes. |

---

## 3. Files Changed and Artifacts Established

### New Source Files (`src/job_automation/storage/`)
- [`src/job_automation/storage/__init__.py`](../../src/job_automation/storage/__init__.py): Package exports for storage engine, repositories, exceptions, and filestore.
- [`src/job_automation/storage/exceptions.py`](../../src/job_automation/storage/exceptions.py): Storage exceptions (`StorageError`, `DuplicateKeyError`, `MigrationError`, `RecordNotFoundError`, `TransactionError`).
- [`src/job_automation/storage/connection.py`](../../src/job_automation/storage/connection.py): SQLite connection factory and `transaction()` atomic context manager.
- [`src/job_automation/storage/filestore.py`](../../src/job_automation/storage/filestore.py): Filesystem storage for large raw JSON/HTML and binary artifacts with SHA-256 calculation.
- [`src/job_automation/storage/migrations.py`](../../src/job_automation/storage/migrations.py): Migration definitions (v1 baseline and v2 checkpoints/audit) and sequential runner.
- [`src/job_automation/storage/engine.py`](../../src/job_automation/storage/engine.py): `StorageEngine` coordinating connections, transactions, filestore, and all repositories.
- [`src/job_automation/storage/repositories/base.py`](../../src/job_automation/storage/repositories/base.py): Base repository class.
- [`src/job_automation/storage/repositories/runs.py`](../../src/job_automation/storage/repositories/runs.py): `RunLedgerRepository` (C15, stages, checkpoints, run recovery).
- [`src/job_automation/storage/repositories/raw_postings.py`](../../src/job_automation/storage/repositories/raw_postings.py): `RawPostingRepository` (C04, C05, unique source keys).
- [`src/job_automation/storage/repositories/canonical_jobs.py`](../../src/job_automation/storage/repositories/canonical_jobs.py): `CanonicalJobRepository` (C06, C07, revisions).
- [`src/job_automation/storage/repositories/assessments.py`](../../src/job_automation/storage/repositories/assessments.py): `AssessmentRepository` (C11).
- [`src/job_automation/storage/repositories/sync_outbox.py`](../../src/job_automation/storage/repositories/sync_outbox.py): `SyncOutboxRepository` (C12, atomic transactions, outbox recovery).
- [`src/job_automation/storage/repositories/generation_requests.py`](../../src/job_automation/storage/repositories/generation_requests.py): `GenerationRequestRepository` (C13, claiming, frozen inputs, recovery).
- [`src/job_automation/storage/repositories/artifacts.py`](../../src/job_automation/storage/repositories/artifacts.py): `ArtifactRepository` (C14, delivery status).
- [`src/job_automation/storage/repositories/__init__.py`](../../src/job_automation/storage/repositories/__init__.py): Repository package exports.

### Modified Files
- [`src/job_automation/cli.py`](../../src/job_automation/cli.py): Added `storage migrate` and `storage status` subcommands.

### New Test Files (`tests/storage/` and `tests/`)
- [`tests/storage/test_connection.py`](../../tests/storage/test_connection.py): PRAGMA checks, WAL mode, space/Unicode Windows paths, no import side effects.
- [`tests/storage/test_transactions.py`](../../tests/storage/test_transactions.py): Transaction commit, transaction rollback on failure, atomic assessment + sync commit.
- [`tests/storage/test_duplicate_keys.py`](../../tests/storage/test_duplicate_keys.py): Duplicate key rejection for raw postings, canonical jobs, revisions, sync ops, requests, artifacts.
- [`tests/storage/test_migrations.py`](../../tests/storage/test_migrations.py): Sequential migration, idempotency, data preservation across upgrades, rollback on migration error.
- [`tests/storage/test_recovery.py`](../../tests/storage/test_recovery.py): Interrupted run recovery, stage checkpoint recovery across restart, sync outbox recovery, generation request recovery.
- [`tests/storage/test_filestore.py`](../../tests/storage/test_filestore.py): Filestore hashing, raw saving, artifact saving, Windows reserved char sanitization.
- [`tests/storage/test_repositories.py`](../../tests/storage/test_repositories.py): Contract round-trip checks for all repositories.
- [`tests/test_cli_storage.py`](../../tests/test_cli_storage.py): CLI storage migrate and status integration tests.

---

## 4. Key Verification Scenarios

### 1. Duplicate-Key Handling
- **Raw Posting Source Key Uniqueness**: Enforces `(provider, board_id, source_posting_id)`. Re-inserting an identical tuple raises `DuplicateKeyError`.
- **Normalized Posting Uniqueness**: Enforces uniqueness on `(provider, board_id, source_posting_id)`.
- **Canonical Job Uniqueness**: Enforces uniqueness on `canonical_job_id`.
- **Revision Uniqueness**: Enforces uniqueness on `(canonical_job_id, content_hash)`.
- **Sync Outbox Uniqueness**: Enforces uniqueness on `operation_id`.
- **Generation Request Uniqueness**: Enforces uniqueness on `request_id`.
- **Artifact Uniqueness**: Enforces uniqueness on `artifact_id`.

### 2. Transaction Rollback
- Multi-statement transactions executed via `with engine.transaction()` cleanly roll back on exception, leaving zero rows committed.
- Atomic assessment and sync commit (`atomic_commit_assessment_and_sync`): When committing a C11 `Assessment` and a C12 `SyncOperation` together, if the sync operation experiences a constraint conflict, the assessment is rolled back and neither record is inserted.

### 3. Preservation of Existing Data During Migration
- Migration `001_initial` applied to empty database.
- Complete set of records inserted (runs, raw postings, canonical jobs, revisions).
- Migration `002_stage_checkpoints_and_audit` applied, creating `pipeline_checkpoints` and adding columns `runs.notes` and `sync_operations.reconciliation_marker`.
- Verified that all previously inserted records remain intact with full field fidelity.
- Migration failure rollback verified: a faulty migration script with syntax errors rolls back completely, leaving `schema_migrations` at version 1 with zero partial tables created.

### 4. Recovery of Unfinished Records
- **Interrupted Runs**: Runs left in `running` status or without an `end_time` upon process crash are detected by `get_unfinished_runs()`. Calling `recover_interrupted_runs()` transitions them to `failed`, records an ISO-8601 UTC end timestamp, and attaches a `ClassifiedError` (`TRANSIENT_SERVICE`). Incomplete stages are similarly transitioned to `failed`.
- **Checkpoints**: Intermediate stage progress (e.g. pagination cursors, item counts) saved via `save_checkpoint()` can be read back across process restarts via `get_checkpoint()`.
- **Sync Outbox**: Operations left in `running` state are detected by `get_unfinished_operations()`. `recover_stale_running()` transitions them to `retry_wait` for retry.
- **Generation Requests**: Requests claimed and in `running` or `upload_pending` state are detected by `get_unfinished_requests()`. `recover_interrupted_requests()` transitions them to `failed` with a classified error for reconciliation with Salesforce.

---

## 5. Technical Decisions Recorded

1. **Database Engine**: Python standard library `sqlite3` (bundled version `3.49.1` with Python 3.12.10). Requires zero external packages, perfectly aligning with zero-budget requirements and native Windows.
2. **Concurrency PRAGMAs**:
   - `PRAGMA journal_mode = WAL;`: Write-Ahead Logging for concurrent reading and single-writer concurrency.
   - `PRAGMA foreign_keys = ON;`: Enforces relational integrity across jobs, revisions, stages, and requests.
   - `PRAGMA busy_timeout = 5000;`: Prevents transient locks from causing errors during bursts.
   - `PRAGMA synchronous = NORMAL;`: Safe durability in WAL mode.
3. **Bulky Storage Split**: Raw API response payloads (JSON/HTML) and binary documents (DOCX/PDF) are kept strictly on disk outside SQLite under `raw_dir` and `artifacts_dir`, referenced by relative/absolute path and SHA-256 hash (`sha256:...`). SQLite tables store compact metadata, hashes, and relational keys.
4. **No Import Side Effects**: Merely importing `job_automation.storage` creates no files or directories. Parent directories are created lazily upon explicit connection or write.
5. **Windows Path Handling**: All paths use `pathlib.Path` with native Windows conventions (`$env:LOCALAPPDATA`, `Join-Path`). Filename sanitization replaces reserved Windows characters (`[<>:"/\\|?*]`).
6. **Resource Cleanup**: `StorageEngine.close()` and context manager support (`with StorageEngine(...) as engine:`) explicitly close connections and release Windows file locks.

---

## 6. Commands and Test Results

### Automated Test Suite Execution
```powershell
& ".\.venv\Scripts\python.exe" -m pytest --cov=job_automation.storage --cov-report=term-missing
```

Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0
rootdir: C:\Users\mrite\Projects\job-search
configfile: pyproject.toml
testpaths: tests
plugins: cov-6.3.0
collected 112 items

tests\contracts\test_context_model_assessment.py ......                  [  5%]
tests\contracts\test_contract_catalog.py ............................... [ 33%]
.                                                                        [ 33%]
tests\contracts\test_errors.py ...                                       [ 36%]
tests\contracts\test_interfaces.py .....                                 [ 41%]
tests\contracts\test_primitives.py .......                               [ 47%]
tests\contracts\test_profile_policy_evidence.py ....                     [ 50%]
tests\contracts\test_source_posting_identity.py ......                   [ 56%]
tests\contracts\test_work_records.py ....                                [ 59%]
tests\storage\test_connection.py ...                                     [ 62%]
tests\storage\test_duplicate_keys.py ......                              [ 67%]
tests\storage\test_filestore.py ....                                     [ 71%]
tests\storage\test_migrations.py ....                                    [ 75%]
tests\storage\test_recovery.py ....                                      [ 78%]
tests\storage\test_repositories.py .......                               [ 84%]
tests\storage\test_transactions.py ....                                  [ 88%]
tests\test_cli.py .....                                                  [ 92%]
tests\test_cli_storage.py ..                                             [ 94%]
tests\test_configuration.py ......                                       [100%]

=============================== tests coverage ================================
Name                                                             Stmts   Miss  Cover
------------------------------------------------------------------------------------
src\job_automation\storage\__init__.py                               7      0   100%
src\job_automation\storage\connection.py                            22      0   100%
src\job_automation\storage\engine.py                                72      0   100%
src\job_automation\storage\exceptions.py                             9      0   100%
src\job_automation\storage\filestore.py                             44      2    95%
src\job_automation\storage\migrations.py                            63      2    97%
src\job_automation\storage\repositories\__init__.py                  9      0   100%
src\job_automation\storage\repositories\artifacts.py                33      3    91%
src\job_automation\storage\repositories\assessments.py              32      5    84%
src\job_automation\storage\repositories\base.py                      8      0   100%
src\job_automation\storage\repositories\canonical_jobs.py           69     16    77%
src\job_automation\storage\repositories\generation_requests.py      58      3    95%
src\job_automation\storage\repositories\raw_postings.py             54      9    83%
src\job_automation\storage\repositories\runs.py                     98      5    95%
src\job_automation\storage\repositories\sync_outbox.py              76      3    96%
------------------------------------------------------------------------------------
TOTAL                                                              654     48    93%
============================= 112 passed in 3.13s =============================
```

### Native Windows CLI Verification
```powershell
$testDataRoot = Join-Path $env:TEMP "Job Automation Prüfung ä"
& ".\.venv\Scripts\python.exe" -m job_automation storage migrate --config config/app.example.json --data-root "$testDataRoot"
& ".\.venv\Scripts\python.exe" -m job_automation storage status --config config/app.example.json --data-root "$testDataRoot"
```

Output:
```text
Storage migration: SUCCESS
  Database Path:     C:\Users\mrite\AppData\Local\Temp\Job Automation Prüfung ä\database\job_automation.db
  Newly Applied:     [1, 2]
  Current Version:   2
Storage status: OK
  Database Path:     C:\Users\mrite\AppData\Local\Temp\Job Automation Prüfung ä\database\job_automation.db
  Current Version:   2
  Applied Count:     2
    v1 (001_initial): applied at 2026-10-27T12:54:32.681929+00:00
    v2 (002_stage_checkpoints_and_audit): applied at 2026-10-27T12:54:32.683495+00:00
```

---

## 7. Native Windows Verification Status

| Scenario | Command / Action | Result | Exit Code | Notes |
|---|---|---|---|---|
| **Space & Unicode Path** | Connect to `C:\Users\mrite\AppData\Local\Temp\Job Automation Prüfung ä` | Directories created, DB initialized | 0 | Handles German characters and spaces cleanly |
| **CLI `storage migrate`** | `python -m job_automation storage migrate --config config/app.example.json` | `Storage migration: SUCCESS` | 0 | Applied v1 and v2 |
| **CLI `storage status`** | `python -m job_automation storage status --config config/app.example.json` | `Storage status: OK` | 0 | Verified applied versions |
| **CLI Missing Config** | `python -m job_automation storage migrate --config missing.json` | `Storage migration: FAILED` | 2 | Safe failure message |
| **Import Side Effects** | `import job_automation.storage` | `Storage imported cleanly without side effects` | 0 | No filesystem mutations on import |
| **Connection Cleanup** | `engine.close()` | Lock released | 0 | Temp folders cleanly removable on Windows |

---

## 8. Live Service Verification Status

- **External Network / APIs**: Not applicable (DATA-01 is completely offline).
- **Salesforce Org**: Not applicable (no outbound network calls belong in DATA-01; outbox tables and atomic writes are verified locally).
- **Local Model Service**: Not applicable (Ollama execution belongs to MODEL-01 / LLM-01).

---

## 9. Known Limitations and Pending Work

1. **FTS5 / Vector Search**: Full-Text Search 5 or vector embeddings are not initialized in DATA-01 (owned by **CONTEXT-03** / **CONTEXT-04** for RAG retrieval).
2. **Automated Source Fetching**: Concrete adapters and network fetching belong to **SOURCE-02** and **SOURCE-03**.
3. **Pipeline Runner**: The multi-stage orchestrator, file-based worker lock, and CLI run command belong to **RUN-01**.
4. **Salesforce Gateway**: Real Salesforce OAuth connection and REST client belong to **SFCLIENT-01** and **SYNC-01**.

---

## 10. Guidance for Dependent Components

- **PROFILE-01 (Candidate Evidence)**:
  - Can store approved candidate evidence versions or snapshots using `StorageEngine` or filestore.
- **INGEST-01 (Fetch Controller)**:
  - Persist raw postings via `storage.raw_postings.save_raw_posting(raw)`.
  - Persist fetch manifests via `storage.raw_postings.save_manifest(manifest)`.
  - Check source posting uniqueness; duplicate postings will raise `DuplicateKeyError`.
- **IDENTITY-01 (Identity & Revisions)**:
  - Store and query canonical jobs via `storage.canonical_jobs.save_canonical_job(job)`.
  - Use `storage.canonical_jobs.find_by_source_key(source_key)` to check existing mappings.
- **MATCH-01 / MATCH-02 (Assessment)**:
  - Commit assessment and pending sync operations atomically via `storage.sync_outbox.atomic_commit_assessment_and_sync(assessment, sync_op)`.
- **RUN-01 (CLI Pipeline & Recovery)**:
  - Create run ledger entries via `storage.runs.create_run(run_id)`.
  - Record stage progress via `storage.runs.record_stage(...)`.
  - On worker startup, call `storage.runs.recover_interrupted_runs()` and `storage.sync_outbox.recover_stale_running()`.
- **GEN-01 (Generation Request Worker)**:
  - Poll or query unfinished requests with `storage.generation_requests.get_unfinished_requests()`.
  - Freeze inputs and claim requests atomically with `storage.generation_requests.claim_request(request_id, frozen_inputs)`.
  - Store rendered document artifacts on disk via `storage.filestore.save_artifact_file(...)` and record metadata via `storage.artifacts.save_artifact(...)`.

