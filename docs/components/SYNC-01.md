# Component Handoff: SYNC-01 — Assessment Publication, External ID Synchronization, and Recovery

Component ID: **SYNC-01**  
Status: **VERIFIED (Offline / Contract / Fake-Transport) — Live acceptance pending SF-01 schema and SF-02 authorization handoffs**  
Phase: **Phase 1**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026), especially §§4–6 and §§8–10  
Prerequisite Handoffs:
- [FND-01](FND-01.md) (**VERIFIED**)
- [DATA-01](DATA-01.md) (**VERIFIED**)
- [MATCH-01](MATCH-01.md) (**VERIFIED**)
- [SFCLIENT-01](SFCLIENT-01.md) (**VERIFIED**)
- **SF-01** (**ABSENT / PENDING PREREQUISITE**)
- **SF-02** (**ABSENT / PENDING PREREQUISITE**)  
Planning Reference: [docs/stories/SYNC-01.md](../stories/SYNC-01.md)  
Date Completed: 29 October 2026  
Direct Covered Requirements: [R04](../../IMPLEMENTATION_BLUEPRINT.md#r04), [R08](../../IMPLEMENTATION_BLUEPRINT.md#r08), [R09](../../IMPLEMENTATION_BLUEPRINT.md#r09), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16)  

---

## 1. Prerequisites and Missing Prerequisite Gates

Before implementing SYNC-01, upstream components, contracts, and repository assets were inspected:

| Prerequisite / Evidence | Found In Repository | Verification Status | Consequence for SYNC-01 |
|---|---|---|---|
| **DATA-01 Storage Engine** | `docs/components/DATA-01.md`, `src/job_automation/storage/` | **VERIFIED** | Extended schema via Migration 007 (`MIGRATION_007_SYNC_LIFECYCLE_AND_ORDERING`) with WAL mode, foreign keys, and atomic multi-table transaction support. |
| **MATCH-01 Assessment (C11)** | `docs/components/MATCH-01.md`, `src/job_automation/contracts/assessment.py` | **VERIFIED** | Enveloped `Assessment` contract into method-independent `SyncSubmission` carrying canonical references, evaluation timestamp, and input-generation tokens. |
| **SFCLIENT-01 Gateway Client** | `docs/components/SFCLIENT-01.md`, `src/job_automation/salesforce/gateway.py` | **VERIFIED** | Conforms to `SalesforceGatewayV2` Protocol for `upsert_by_external_id`, `get_record`, and `query_page`. Used in-memory stateful fake gateway (`FakeSalesforceGatewayV2`) for offline verification. |
| **SF-01 Schema Handoff** | `docs/components/SF-01.md`, `salesforce/` org metadata | **ABSENT** | **Missing prerequisite**. Target custom objects (`Job__c`, `Company__c`) and custom fields are not deployed to a live Salesforce org. SYNC-01 defines canonical mapping configurations and verified offline against `SalesforceGatewayV2`. |
| **SF-02 OAuth Authorization** | `docs/components/SF-02.md`, org Connected Apps | **ABSENT** | **Missing prerequisite**. No live OAuth credentials, client secrets, or refresh tokens exist in repository. Live network publication remains gated until SF-02 handoff. |

### Scope & Boundaries
1. **SYNC-01 does NOT deploy Salesforce schema** or mutate live org metadata.
2. **SYNC-01 does NOT implement OAuth flows** or credential setup (owned by `SF-02`).
3. **SYNC-01 does NOT build the pipeline runner or scheduler** (owned by `RUN-01` and `OPS-01`).
4. Full contract, durability, transaction, retry, reconciliation, and Windows platform verification has been demonstrated offline (86/86 SYNC-01 tests passing; 1176/1176 repository tests passing).

---

## 2. Field Mappings and Contract Models

SYNC-01 establishes a decoupled, versioned mapping layer defined by `SyncMappingConfig` and loaded from `config/sync.example.json`:

```json
{
  "schema_version": "1.0",
  "mapping_version": "1.0",
  "expected_org_id": "00D000000000001",
  "company_object": "Company__c",
  "company_external_id_field": "Canonical_Company_Id__c",
  "company_name_field": "Name",
  "job_object": "Job__c",
  "job_external_id_field": "Canonical_Job_Id__c",
  "job_company_lookup_field": "Company__c",
  "title_field": "Name",
  "availability_field": "Availability__c",
  "disposition_field": "Assessment_Disposition__c",
  "reason_field": "Assessment_Reasons__c",
  "score_field": "Relevance_Score__c",
  "score_scale_field": "Score_Scale__c",
  "last_evaluated_field": "Last_Evaluated_At__c",
  "source_urls_field": "Source_URLs__c",
  "sync_marker_field": "Sync_Operation_Marker__c",
  "sync_version_field": "Machine_Sync_Version__c",
  "disposition_mapping": {
    "eligible": "Eligible",
    "review": "Review",
    "rejected": "Rejected"
  },
  "availability_mapping": {
    "active": "Active",
    "not_seen": "Not Seen",
    "unavailable": "Unavailable",
    "unknown": "Unknown"
  },
  "candidate_fields": [
    "Application_Progress__c",
    "Candidate_Notes__c",
    "Candidate_Decision__c",
    "Follow_Up_Date__c",
    "Interview_Date__c"
  ]
}
```

### Assessment Handling (Rules-Only vs. LLM)
- **Rules-Only Assessments**: Score and scale are absent/null in C11. SYNC-01 explicitly maps `Relevance_Score__c: null` and `Score_Scale__c: null`.
- **LLM Assessments**: Structured score and scale are present in C11. SYNC-01 maps `Relevance_Score__c: score` and `Score_Scale__c: "0-100"`.
- Both assessment methods use the exact same `SyncSubmission` envelope, guaranteeing that publication authority is determined by publication policy rather than assessment method.

---

## 3. Field Ownership Architecture

Strict field ownership is enforced at configuration, mapping, write dispatch, and retry boundaries to ensure machine automation never overwrites or nulls human candidate workflow:

### Machine-Owned Fields (Published by SYNC-01)
- `Canonical_Job_Id__c` (External ID)
- `Name` (Job Title)
- `Company__c` (Parent Company Salesforce Record ID)
- `Availability__c` (Active, Not Seen, Unavailable, Unknown)
- `Assessment_Disposition__c` (Eligible, Review, Rejected)
- `Assessment_Reasons__c` (Formatted summary reasons)
- `Relevance_Score__c` (Nullable float score)
- `Score_Scale__c` (Nullable scale identifier)
- `Last_Evaluated_At__c` (ISO-8601 evaluation timestamp)
- `Sync_Operation_Marker__c` (Reconciliation marker)
- `Machine_Sync_Version__c` (Monotonic per-entity sequence)

### Candidate-Owned Fields (Protected and Backed Up)
- `Application_Progress__c`
- `Candidate_Notes__c`
- `Candidate_Decision__c`
- `Follow_Up_Date__c`
- `Interview_Date__c`

### Ownership Protection Mechanisms
1. **Configuration Collision Check**: `SyncMappingConfig` validation immediately raises `SyncOwnershipError` if any candidate field is mapped to any machine field.
2. **Payload Protection Assertion**: `assert_no_candidate_fields()` checks every outbound dictionary before serialization. Attempting to write a candidate field raises `SyncOwnershipError`.
3. **Pre-Update Snapshotting**: Prior to modifying machine fields on an already-tracked Job, `SyncDispatcher` reads the live candidate fields from Salesforce and records a `CandidateFieldSnapshot` in local SQLite (`candidate_snapshots` table).
4. **Periodic Candidate Backup Scanner**: `CandidateBackupService.backup_candidate_fields()` scans all remote jobs via `gateway.query_page`, captures snapshot records, and updates durable checkpoints in `candidate_backup_checkpoints`.

---

## 4. Publication Authority and Lifecycle

SYNC-01 implements the authoritative publication lifecycle:

### Initial Publication Rule
- **Eligible or Review Jobs**: Evaluated as `PublicationDecision.PUBLISH_INITIAL`. Generates an atomic plan with 2 write steps: Company upsert (if not already acknowledged) followed by Job upsert.
- **Rejected Jobs**: Evaluated as `PublicationDecision.LOCAL_ONLY_REJECTED`. Atomically persists the C11 assessment and a plan with 0 write steps. **No remote record is created in Salesforce.**

### Tracked Refresh Rule
- When an already-tracked job receives an updated assessment (or availability change to unavailable/rejected):
  - Evaluated as `PublicationDecision.UPDATE_TRACKED`.
  - Machine fields (availability, disposition, last evaluated at, monotonic version) are updated in Salesforce.
  - Candidate-owned fields (`Application_Progress__c`, etc.) are preserved intact remotely.

### Idempotency & Lost-Response Recovery
- `commit_assessment_and_plan()` validates `(canonical_job_id, assessment_id, generation_token)`.
- If an existing plan is found for the same assessment and generation token (lost T1 response), the service returns the existing plan and operation IDs without generating duplicate steps or advancing sequences.

---

## 5. Transaction Boundaries (T0–T5)

| Boundary | Name | Operations & Tables | Atomicity & Invariant |
|---|---|---|---|
| **T0** | Selection Registration | `sync_selection_heads` | Registers/advances active input generation token for job. Stale generations rejected. |
| **T1** | Assessment & Plan Commit | `assessments`, `sync_plans`, `sync_write_steps`, `sync_operations` | Atomically commits assessment, publication decision, allocated sequences, and frozen write payloads. |
| **T2** | Claim & Send Intent | `sync_write_steps` | Compare-and-set claim (`state='running'`, `claimed_by`, `claimed_at`, `may_have_been_sent=1`). Committed before physical HTTP mutation. |
| **T3** | Remote Acknowledgment | `sync_write_steps`, `sync_remote_mappings`, `sync_entity_heads`, `sync_operations` | Acknowledges write step, saves remote ID mapping, advances confirmed sequence, and clears barrier. |
| **T4** | Failure / Retry Decision | `sync_write_steps`, `sync_entity_heads` | Marks step `retry_wait` (with backoff `next_attempt_at`) or terminal `failed`. Uncertainty retains lane barrier. |
| **T5** | Candidate Backup | `candidate_snapshots`, `candidate_backup_checkpoints` | Persists candidate field snapshot and scan checkpoint. Completed scans recorded atomically. |

---

## 6. Ordering, Barriers, Retries, and Reconciliation

1. **Company-before-Job Ordering**:
   - Company upsert is planned as step 1 (`depends_on_step_id = None`).
   - Job upsert is planned as step 2 (`depends_on_step_id = comp_step_id`).
   - When the Company step succeeds, its Salesforce Record ID is dynamically injected into `frozen_payload['Company__c']` of the Job step.
2. **Company Deduplication & Reuse**:
   - Multiple jobs sharing the same `canonical_company_id` reuse the acknowledged `RemoteEntityMapping`.
   - Subsequent jobs do not generate redundant Company upsert steps.
3. **Uncertainty Barriers**:
   - If a gateway mutation fails with `remote_outcome == RemoteOutcome.UNKNOWN` (e.g. timeout after send), an uncertainty barrier is placed on `sync_entity_heads`.
   - The barrier prevents subsequent writes from dispatching on that entity lane until resolved.
4. **Lost-Response Reconciliation**:
   - `SyncReconciler.reconcile_due_work()` reads back remote records by External ID.
   - Matching `Sync_Operation_Marker__c` confirms the outstanding write, transitions the step to `succeeded`, commits the mapping, and clears the barrier.
   - Detecting a higher remote version (`Machine_Sync_Version__c > step.sequence_number`) supersedes the older step and clears the barrier.
5. **Bounded Retries**:
   - Maximum 3 attempts (`DEFAULT_MAX_ATTEMPTS = 3`).
   - Exponential backoff with jitter: 5.0s base, 300.0s ceiling.
   - Respects remote `retry_not_before` / `Retry-After`.
   - Permanent errors (403 Forbidden, permission, configuration) fail immediately without retry.

---

## 7. Migration 007 Implementation

Migration 007 (`MIGRATION_007_SYNC_LIFECYCLE_AND_ORDERING`) was appended to `src/job_automation/storage/migrations.py`:
- `sync_plans`: Durable publication plans with foreign keys to `canonical_jobs` and `assessments`.
- `sync_write_steps`: Ordered discrete write steps with parent step dependencies, frozen payloads, fingerprints, attempt counters, and reconciliation markers.
- `sync_entity_heads`: Per-entity monotonic sequence counters, confirmed sequences, and active barriers.
- `sync_remote_mappings`: Authoritative remote Salesforce ID mappings indexed by `(org_id, target_object, entity_id)` and `(org_id, target_object, external_id)`.
- `sync_selection_heads`: Active input-generation tokens preventing late stale assessments.
- `candidate_snapshots`: Historical snapshots of candidate-owned fields with content hashes.
- `candidate_backup_checkpoints`: Resumable scan progress and completion checkpoints.

Preserves checksums of migrations 001–006. Verified with SQLite WAL mode and foreign key integrity.

---

## 8. Verification & Test Evidence

### Test Suites (`tests/salesforce/sync/`)
- `test_contracts.py` (7 tests): Model validation, frozen immutability, schema registration.
- `test_mapping.py` (7 tests): Field mapping, rules vs. LLM mapping, external IDs, canonical payloads.
- `test_ownership.py` (5 tests): Ownership collision prevention, candidate field rejection.
- `test_publication.py` (5 tests): Initial eligible/review vs. rejected publication decisions.
- `test_refresh.py` (1 test): Tracked refresh preserves candidate history and evaluation timestamp.
- `test_atomic_submission.py` (2 tests): Multi-table T1 atomic rollback, duplicate submission idempotency.
- `test_candidate_preservation.py` (1 test): Candidate edits in Salesforce survive machine updates.
- `test_candidate_backup.py` (1 test): Candidate backup scan and checkpoint tracking.
- `test_dispatch.py` (3 tests): Company-before-Job ordering, company reuse, compare-and-set claim.
- `test_reconciliation.py` (2 tests): Lost-response reconciliation by External ID/marker, newer remote version.
- `test_stale_writes.py` (2 tests): Lane barriers block dispatch, replay prevention.
- `test_retry.py` (4 tests): Transient backoff delay, `retry_not_before`, 3 max attempts, immediate permanent failure.
- `test_recovery.py` (3 tests): Bounded operation limit, CallBudget exhaustion, storage engine restart.
- `test_crash_matrix.py` (5 tests): Matrix coverage of all failure points from `docs/stories/SYNC-01.md`.
- `test_windows_paths.py` (1 test): Paths with spaces and German umlauts (`Job Automation Prüfung für Entwickler äöüß`).
- `test_windows_restart.py` (1 test): Windows process restart with active barriers, retry wait, and reconciliation.

**Total SYNC-01 Tests: 86 passed.**  
**Total Repository Tests: 1176 passed in 16.37s.**

### Manual Smoke Script
`tests/manual/sync_smoke.py`:
- Safe read-only default with prerequisite reporting.
- Simulates complete local sync lifecycle against `FakeSalesforceGatewayV2`.
- Verifies Company->Job ordering, candidate edit survival, lost response reconciliation, and candidate backup.
- Command: `& ".\.venv\Scripts\python.exe" tests\manual\sync_smoke.py` (exits 0).

---

## 9. Limitations & Handoff to RUN-01

### Current Limitations
1. **Live Salesforce Org Deployment**: Dependent on `SF-01` metadata deployment and `SF-02` OAuth authorization handoff.
2. **Single-Worker Execution**: Default dispatcher deployment assumes single worker; compare-and-set claims and sequence allocation support concurrent workers, but distributed locking remains owned by `RUN-01`.

### Handoff Interfaces for RUN-01
- `SyncServicePort`: Entry point for publishing assessments (`commit_assessment_and_plan`), advancing selection tokens (`register_selection_token`), and queueing tracked refreshes (`queue_tracked_refresh`).
- `SyncDispatcherPort`: Entry point for draining due outbox operations (`drain_due_work`) and reconciling uncertain transmissions (`reconcile_due_work`).
- `CandidateBackupPort`: Entry point for scheduled background candidate field backups (`backup_candidate_fields`).

