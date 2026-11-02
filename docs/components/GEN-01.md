# Component Handoff: GEN-01 — Document Generation Request Worker, Polling, Checkpoints, and Recovery

Component ID: **GEN-01**  
Status: **VERIFIED (Unit / Integration / Subprocess / Restart Crash Matrix / Windows Native Locking) — Live Salesforce acceptance pending real sandbox/org credentials and live downstream stages (GEN-02 through GEN-06)**  
Phase: **Phase 0 / P0 (S01–S08 Implemented)**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) §§4, 5, 8, 9; [docs/stories/GEN-01.md](../stories/GEN-01.md)  
Prerequisite Handoffs:
- [DATA-01](DATA-01.md) (**VERIFIED**)
- [INGEST-01](INGEST-01.md) (**VERIFIED**)
- [INGEST-02](INGEST-02.md) (**VERIFIED**)
- [IDENTITY-01](IDENTITY-01.md) (**VERIFIED**)
- [IDENTITY-02](IDENTITY-02.md) (**VERIFIED**)
- [MATCH-01](MATCH-01.md) (**VERIFIED**)
- [MATCH-02](MATCH-02.md) (**VERIFIED**)
- [SYNC-01](SYNC-01.md) (**VERIFIED**)
- [SFCLIENT-01](SFCLIENT-01.md) (**VERIFIED**)
- [RUN-01](RUN-01.md) (**VERIFIED**)  
Date Completed: 29 October 2026  
Direct Covered Requirements: [R10](../../IMPLEMENTATION_BLUEPRINT.md#r10), [R11](../../IMPLEMENTATION_BLUEPRINT.md#r11), [R12](../../IMPLEMENTATION_BLUEPRINT.md#r12), [R06](../../IMPLEMENTATION_BLUEPRINT.md#r06), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16)

---

## 1. Executive Summary & Component Scope

`GEN-01` delivers the manually started, single-active Windows generation request worker responsible for outbound polling, idempotent admission, staged coordination, persistent checkpoints, and restart reconciliation of tailored document generation requests (`GenerationRequest`, C13).

It coordinates the complete generation lifecycle—from input freezing through draft generation, validation, document rendering, and artifact delivery—without coupling the worker directly to incomplete downstream implementations.

### Core Architecture & Behavioral Invariants

1. **Strict Dependency Gates & Port Contracts**:
   - GEN-01 acts strictly as an orchestrator and coordinator.
   - It **does not implement miniature versions or fallback mock implementations of missing dependencies** (such as ad-hoc context building or latest-profile database querying).
   - If a required downstream component (GEN-02 input freezer, GEN-03 draft generator, GEN-04 draft validator, GEN-05 renderer, or GEN-06 deliverer) is absent, the generation request halts gracefully in a visible `BLOCKED` status.
   - Requests are **never falsely marked `ready_for_review`** or completed when downstream stages have not run.

2. **Windows Single-Active Process Mutual Exclusion**:
   - Generation execution is guarded by `WindowsWorkerLock(data_root)` with `OwnerKind.GENERATION`.
   - Mutually exclusive with search workers (`OwnerKind.SEARCH`): if a search worker is running, the generation worker exits immediately with code `3` (`LockContentionError`).
   - Runner lock ordering: lock acquisition strictly precedes SQLite database opening and schema migration so losing processes make zero database writes.
   - When a worker process terminates abnormally (e.g. `SIGKILL` or unhandled crash), the Windows operating system releases file handles immediately, allowing successor workers to acquire the lock and recover state.

3. **Atomic Freeze Commitment Before Remote Projection**:
   - Input snapshots and request state transition to `running` commit locally to SQLite in **one atomic transaction** (`commit_frozen_request`) *before* any remote `Running` mutation is dispatched to Salesforce.
   - Prevents inconsistent remote state: Salesforce never reflects `Running` if local state failed to commit.
   - Freeze-once invariance: once claimed and frozen, input versions are immutable; conflicting re-freeze attempts raise `FreezeConflictError`.

4. **Restart Reconciliation & Stale Ownership Handling**:
   - Unacknowledged projection intents in `PENDING` or `UNCERTAIN` status are reconciled upon restart using readback verification matching operation markers.
   - Local unfinished requests resume from their latest committed stage checkpoint (`freeze`, `context`, `draft`, `validation`, `rendering`, `delivery`).
   - Stale remote `Running` requests with preserved local freeze manifests resume execution.
   - Orphan stale remote `Running` requests (missing local state or freeze manifest) are projected to terminal `Failed` with reason `orphan_remote_running`; the worker **never resets an orphan request to `Pending` or freezes current/latest inputs under the old request ID**.

5. **Deliberate Regenerations vs. Idempotent Retries**:
   - Repeated polling of the same Salesforce request record idempotently matches the existing C13 record and reuses existing checkpoints.
   - Deliberate regenerations (identified by new Salesforce record IDs or explicit client keys) receive fresh, distinct C13 UUIDs, link to predecessors via `predecessor_request_id`, and write to distinct artifact output slots.

6. **Preflight Availability Gate**:
   - Requests for jobs marked `unavailable` fail preflight immediately and transition to terminal `Failed` without claiming or projecting `Running`, unless an explicit candidate override (`allow_unavailable_job=True`) was recorded.

---

## 2. Architecture & Component Interfaces

### Module Overview

| Module | Purpose |
|---|---|
| `src/job_automation/generation/records.py` | Data contracts: `GenerationRequestObservation`, `FreezeManifest`, `StageCheckpoint`, `StageAttempt`, `ProjectionIntent`, `ArtifactDeliveryRecord`, `GenerationWorkerReport`. |
| `src/job_automation/generation/errors.py` | Exception hierarchy: `GenerationError`, `MissingComponentError`, `DependencyBlockedError`, `FreezeConflictError`, `InvalidRequestStateError`, `ProjectionUncertainError`. |
| `src/job_automation/generation/ports.py` | Protocols for decoupled ports: `GenerationRequestSource`, `GenerationInputService` (GEN-02), `DraftValidator` (GEN-04), `DocumentRenderer` (GEN-05), `ArtifactDeliverer` (GEN-06), `RequestStateProjector`. |
| `src/job_automation/generation/request_mapping.py` | Canonical 15-to-18 character Salesforce ID conversion (case-preserving), `derive_local_request_id` (UUIDv5), `compute_options_digest`. |
| `src/job_automation/generation/settings.py` | Configuration models: `GenerationSettings`, `GenerationLimits`, `GenerationStaleness`, `GenerationRetryPolicy`. |
| `src/job_automation/generation/polling.py` | `SalesforceGenerationRequestSource`: SOQL polling across pending/running lanes, SOQL injection guards, observation mapping and persistence. |
| `src/job_automation/generation/admission.py` | `GenerationAdmitter`: validates observations, resolves predecessor links, enforces client-key conflicts, and performs preflight availability checks. |
| `src/job_automation/generation/projection.py` | `SalesforceRequestStateProjector`: dispatches durable state projections via `SalesforceGatewayV2`, marks `UNCERTAIN` on network timeouts, and reconciles via readback. |
| `src/job_automation/generation/coordinator.py` | `GenerationCoordinator`: manages the staged progression (`FREEZE -> CONTEXT -> DRAFT -> VALIDATION -> RENDERING -> DELIVERY`), halting cleanly at absent stages. |
| `src/job_automation/generation/recovery.py` | `GenerationRecoveryManager`: reconciles unacknowledged intents, resumes local unfinished requests, and projects failure for orphan stale Running requests. |
| `src/job_automation/generation/reporting.py` | `format_worker_report`: produces safe human-readable text and structured JSON without leaking tokens or candidate facts. |
| `src/job_automation/generation/worker.py` | `GenerationWorker`: manages exclusive Windows process lock, bounded polling cycles, watch mode loop, and overall worker exit codes. |
| `src/job_automation/generation/cli.py` | CLI commands registered under `job_automation generation` (`work`, `show`, `retry`). |

### Storage Schema (Migration 010)

Migration 010 (`MIGRATION_010_GENERATION_WORKFLOW_AND_CHECKPOINTS`) adds companion tables to SQLite supporting persistent checkpoints, freeze associations, and projections:

```sql
-- Companion tables created in Migration 010
CREATE TABLE IF NOT EXISTS generation_request_observations (...);
CREATE TABLE IF NOT EXISTS generation_freeze_associations (...);
CREATE TABLE IF NOT EXISTS generation_request_checkpoints (...);
CREATE TABLE IF NOT EXISTS generation_request_attempts (...);
CREATE TABLE IF NOT EXISTS generation_projection_intents (...);
CREATE TABLE IF NOT EXISTS generation_artifact_deliveries (...);

-- Trigger protecting claimed canonical jobs against cascade deletion
CREATE TRIGGER IF NOT EXISTS trg_protect_claimed_generation_requests
BEFORE DELETE ON canonical_jobs
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'Cannot delete canonical job claimed by generation request')
    WHERE EXISTS (
        SELECT 1 FROM generation_requests
        WHERE canonical_job_id = OLD.canonical_job_id
          AND state IN ('running', 'ready_for_review', 'completed')
    );
END;
```

---

## 3. Recovery Matrix & Failure Handling

| Failure Scenario | Immediate Worker Behavior | Recovery on Next Restart |
|---|---|---|
| **Crash before local freeze persistence** | Request remains in `PENDING` state in SQLite. | Re-polled or picked up from local unfinished queue as `PENDING`; preflight checks re-evaluated cleanly. |
| **Crash after local freeze, before remote Running dispatch** | Request is `RUNNING` locally; `ProjectionIntent` is `PENDING`. | `GenerationRecoveryManager` detects unacknowledged intent and dispatches `Running` projection to Salesforce. |
| **Network timeout during remote Running dispatch** | Intent marked `UNCERTAIN` with timestamp; worker halts request progression. | Readback checks Salesforce `Operation_Marker__c`. If marker matches, intent marked `ACKNOWLEDGED`. If remote record remained `Pending`, safe to re-dispatch. |
| **Crash during CONTEXT / DRAFT / VALIDATION / RENDERING** | Latest stage attempt recorded in `generation_request_attempts`. | Coordinator inspects completed `StageCheckpoint` records; resumes execution at first uncompleted stage without repeating earlier stages. |
| **Missing downstream component (e.g. GEN-03)** | Coordinator logs dependency gate, saves checkpoint with status `BLOCKED`, exits cycle with code `4`. | Request remains in `RUNNING` state (frozen). When GEN-03 is deployed, successor cycle resumes draft generation using frozen inputs. |
| **Stale remote Running request with preserved local freeze** | Worker detects remote request age $>30$ minutes (configurable). Local database has matching freeze manifest. | Worker resumes generation from preserved frozen inputs; does NOT re-freeze latest candidate profile. |
| **Stale remote Running request without local freeze (orphan)** | Worker detects remote request age $>30$ minutes. Local database has no record or missing freeze. | Worker projects terminal `Failed` with reason `orphan_remote_running`. Worker **never resets to Pending** to substitute latest profile inputs. |
| **Lock contention with Search worker** | Generation worker fails to acquire `WindowsWorkerLock(owner_kind=OwnerKind.GENERATION)`. | Exits immediately with code `3`. Zero SQLite reads/writes or migrations performed. |
| **Worker process crash / kill** | Windows OS closes file handle immediately upon process termination. | Successor worker acquires lock cleanly without manual cleanup or stale PID file deletion. |

---

## 4. CLI Interface & Exit Codes

```bash
# Execute single bounded generation cycle
python -m job_automation generation work --once --data-root <path>

# Run continuously in foreground watch mode
python -m job_automation generation work --watch --data-root <path>

# Coordinate stages through a specific milestone (e.g. context building only)
python -m job_automation generation work --once --through context --data-root <path>

# Output execution report in JSON format
python -m job_automation generation work --once --json --data-root <path>

# Inspect request details, stage checkpoints, and deliveries
python -m job_automation generation show --request-id <uuid> --data-root <path>

# Retry a failed generation request with preserved identity
python -m job_automation generation retry --request-id <uuid> --data-root <path>
```

### Exit Codes
- `0`: Success (requests completed cleanly or queue empty).
- `1`: Fatal error or unhandled exception.
- `2`: Invalid CLI arguments or preflight validation failure.
- `3`: Lock contention (`OwnerKind.SEARCH` or another `GENERATION` worker holds deployment lock).
- `4`: Requests admitted and frozen, but progression is `BLOCKED` awaiting downstream components.

---

## 5. Verification Test Suite

The GEN-01 implementation is verified by an extensive, comprehensive test suite covering unit contracts, storage transactions, polling, state projection, coordination gates, worker lifecycle, native Windows path conventions, cross-process restart semantics, and the complete failure matrix:

| Test File | Test Count | Scope |
|---|---|---|
| `tests/generation/test_records.py` | 7 | Record contracts, validation, mutability constraints, options digest. |
| `tests/generation/test_storage.py` | 6 | Migration 010 schema, CRUD for companion tables, atomic freeze commitment, rollback on failure, cascade delete protection trigger. |
| `tests/generation/test_polling.py` | 3 | SOQL query generation, injection protection, lane filtering, observation storage. |
| `tests/generation/test_admission.py` | 5 | Observation validation, idempotent reuse, client-key conflict detection, unavailable job preflight rejection and override. |
| `tests/generation/test_projection.py` | 2 | Intent persistence, dispatch acknowledgment, network timeout handling (`UNCERTAIN`), readback reconciliation. |
| `tests/generation/test_coordinator.py` | 4 | Staged progression, missing component dependency gates, `--through <stage>` execution boundaries, full pipeline to `ready_for_review`. |
| `tests/generation/test_recovery.py` | 6 | Unacknowledged intent recovery, readback reconciliation, corrupt local request failure, stale remote running resumption and orphan failure projection. |
| `tests/generation/test_worker.py` | 6 | Single cycle, exit codes (0, 3, 4), bounded watch loop, safe report text/JSON formatting. |
| `tests/generation/test_cli.py` | 5 | CLI dispatch for `work`, `show`, `retry`, argument validation, error formatting. |
| `tests/generation/test_windows_paths.py` | 5 | Paths with spaces, German umlauts (`ä, ö, ü, ß`), trailing slashes, alternate working directories. |
| `tests/generation/test_windows_restart.py` | 2 | Native Windows subprocess tests: mutual exclusion between search and generation workers, exit code 3 on contention, clean lock release upon process termination (`SIGKILL`). |
| `tests/generation/test_crash_matrix.py` | 12 | Crash matrix scenarios (GEN-T01 to GEN-T20): crash before/after local persistence and remote acknowledgment, stale running requests, repeated polling, deliberate regeneration, lock contention. |
| **Total Generation Tests** | **58** | **All 58 Tests Passing Cleanly** |

---

## 6. Pending Live & End-to-End Verification

The following verification items are formally cataloged for live end-to-end acceptance once external dependencies are available:

1. **Downstream Pipeline Stages (GEN-02 through GEN-06)**:
   - Verification with real `GenerationInputService` (GEN-02) providing frozen candidate facts, posting snapshots, and search policies.
   - Verification with real LLM document generator (GEN-03), hallucination/rule validator (GEN-04), document renderer (GEN-05), and Salesforce ContentVersion deliverer (GEN-06).
   - In accordance with blueprint requirements, GEN-01 currently holds requests in visible `BLOCKED` status awaiting these components.

2. **Salesforce Sandbox Acceptance**:
   - Live polling from connected Salesforce developer org or scratch org with custom object `Generation_Request__c`.
   - Verification of live custom fields: `Job__c`, `Status__c`, `Document_Type__c`, `Target_Language__c`, `Template_Id__c`, `Worker_Claimed_At__c`, `Operation_Marker__c`, `Client_Request_Key__c`, `Predecessor_Request__c`.
   - Real OAuth refresh-token token exchange and network latency tests.

