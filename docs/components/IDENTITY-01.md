# Component Handoff: IDENTITY-01 — Company/Job Identity and Revisions

Component ID: **IDENTITY-01**  
Status: **VERIFIED**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Prerequisite Handoffs: [docs/components/FND-01.md](FND-01.md), [docs/components/DATA-01.md](DATA-01.md), [docs/components/INGEST-02.md](INGEST-02.md)  
Planning Reference: [docs/stories/IDENTITY-01.md](../stories/IDENTITY-01.md)  
Date Completed: 28 October 2026  
Direct Covered Requirements: [R04](../../IMPLEMENTATION_BLUEPRINT.md#r04) (resolve company and job identity conservatively, track revisions, support reversible merges).  
Supporting Constraints: [R03](../../IMPLEMENTATION_BLUEPRINT.md#r03) (provenance), [R09](../../IMPLEMENTATION_BLUEPRINT.md#r09) (durable compact identities), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14) (native Windows conventions), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15) (untrusted input and safe diagnostics), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16) (auditability and recovery).

---

## 1. Prerequisites and Contract Verification

IDENTITY-01 was implemented strictly using the existing C06 (`NormalizedPosting`) and C07 (`CanonicalJob`, `PostingRevision`) contracts and DATA-01 storage repositories without hand-editing generated JSON schemas or mutating shared contract models:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **C06 Contract** | FND-01 / INGEST-02 | **VERIFIED** | Consumes `NormalizedPosting` with full field provenance, clean text, and structured metadata. Verified end-to-end integration with `DefaultNormalizer`. |
| **C07 Contracts** | FND-01 | **VERIFIED** | Produces `CanonicalJob` and `PostingRevision` adhering to the shared schema. Populates `canonical_job_id`, `canonical_company_id`, `company_name`, `revisions`, `current_revision_id`, `linked_source_keys`, `first_seen_at`, `last_seen_at`, and `merge_lineage`. |
| **DATA-01 Storage Repositories** | DATA-01 | **VERIFIED** | Reused `StorageEngine`, `CanonicalJobRepository`, and `connection.transaction` context manager for atomic multi-table unit-of-work persistence. Added non-breaking Migration 4. |
| **IdentityResolver Protocol** | FND-01 | **VERIFIED** | `IdentityService` conforms to `IdentityResolver.resolve(normalized, existing) -> tuple[UUID, PostingRevision, IdentityMatchDecision]`. |

---

## 2. Implementation Summary by Story

All nine planned stories from `docs/stories/IDENTITY-01.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **IDENTITY-01-S01** | Freeze contracts and compatibility decisions | **VERIFIED** | Defined `IdentityMatchDecision`, `MatchOutcome` enum, `CompanyIdentity`, `ReviewCase`, `MergeOperation`, `ReversalOperation`, and `IdentityResolutionResult` in `models.py`. Standardized error hierarchy under `IdentityError` in `errors.py`. Guaranteed zero modification to C06/C07 schemas. |
| **IDENTITY-01-S02** | Persist mappings, snapshots, and audit records atomically | **VERIFIED** | Implemented `MIGRATION_004_IDENTITY_TRACKING_AND_LINEAGE` in `migrations.py` adding `companies`, `company_aliases`, `source_identities`, `posting_observations`, `identity_review_cases`, and `identity_merge_events`. Created `IdentityRepository` in `src/job_automation/storage/repositories/identity.py`. |
| **IDENTITY-01-S03** | Resolve stable company identities conservatively | **VERIFIED** | Implemented `CompanyResolver` in `companies.py`. Generates stable local UUIDs. Normalizes legal forms (`GmbH`, `AG`, `LLC`, `Co. KG`) for alias matching while keeping substantive distinctions (`Nordlicht GmbH` vs `Nordlicht Services GmbH`) separate unless corroborated. Scopes employer IDs by `provider:board_id`. |
| **IDENTITY-01-S04** | Match scoped job identities and strong URL/requisition evidence | **VERIFIED** | Implemented `JobMatcher` in `matching.py` and `urls.py`. Enforces conservative matching order: exact source mapping → employer + namespaced requisition → job-specific application URL. Requisition mismatch strictly vetoes automatic linking. Text similarity produces review candidates only. |
| **IDENTITY-01-S05** | Retain immutable revisions, observations, and alternate sources | **VERIFIED** | Implemented deterministic field-by-field hash projection in `hashing.py` producing `sha256:<hex64>`. Implemented `revisions.py` tracking observations, accumulating historical URLs, and selecting current revision deterministically (`last_seen_at` descending, stable tie-breakers). |
| **IDENTITY-01-S06** | Compose an atomic, replayable identity service | **VERIFIED** | Implemented `IdentityService` in `service.py`. Executes `resolve_and_commit` inside an atomic transaction committing company, source identity, canonical job, revision snapshot, observation, and review cases simultaneously. Replays are idempotent. Fault injection leaves zero partial state. |
| **IDENTITY-01-S07** | Make uncertain matches inspectable and decidable | **VERIFIED** | Implemented `ReviewCaseManager` in `review.py` and identity CLI in `cli.py` (`job_automation identity review list/show/decide`). Deduplicates review proposals, supports `accept`, `reject`, and `defer`, and redacts credentials/sensitive URLs. |
| **IDENTITY-01-S08** | Merge and reverse without losing links or history | **VERIFIED** | Implemented `execute_merge` and `execute_reversal` in `merges.py`. Merges capture full pre-merge snapshots in `identity_merge_events` and re-parent revisions without row deletion. Reversals partition revisions back to original owners, restore active availability on predecessor jobs, and preserve observation history. |
| **IDENTITY-01-S09** | Verify boundary, native Windows constraints, and publish handoff | **VERIFIED** | Verified contract boundaries, restart persistence, space/Unicode Windows paths (`Data Größe`, `Pytest Daten ä`), and abrupt child-process termination. Verified end-to-end integration with INGEST-02 `DefaultNormalizer`. Executed full test suite (580 passing tests). |

---

## 3. Files Created and Modified

### Identity Package (`src/job_automation/identity/`)
- [`src/job_automation/identity/__init__.py`](../../src/job_automation/identity/__init__.py): Public package exports (`IdentityService`, models, outcomes, exceptions).
- [`src/job_automation/identity/errors.py`](../../src/job_automation/identity/errors.py): Custom exception hierarchy (`IdentityError`, `ConflictError`, `InvalidOperationError`, `MergeError`, `ReversalError`, `ReviewCaseNotFoundError`).
- [`src/job_automation/identity/models.py`](../../src/job_automation/identity/models.py): Domain models (`MatchOutcome`, `CompanyIdentity`, `ReviewCase`, `MergeOperation`, `ReversalOperation`, `IdentityResolutionResult`).
- [`src/job_automation/identity/hashing.py`](../../src/job_automation/identity/hashing.py): Deterministic normalized content projection and SHA-256 hash calculation (`sha256:<hex64>`).
- [`src/job_automation/identity/urls.py`](../../src/job_automation/identity/urls.py): Conservative URL validation, job-specific endpoint detection, and strict equivalence.
- [`src/job_automation/identity/companies.py`](../../src/job_automation/identity/companies.py): Conservative employer resolution, legal suffix normalization, provider-scoped employer IDs.
- [`src/job_automation/identity/matching.py`](../../src/job_automation/identity/matching.py): Matching cascade (exact source → employer + requisition → application URL → text similarity review).
- [`src/job_automation/identity/revisions.py`](../../src/job_automation/identity/revisions.py): Revision creation, URL accumulation, and deterministic `select_current_revision`.
- [`src/job_automation/identity/merges.py`](../../src/job_automation/identity/merges.py): Non-destructive merge execution (`execute_merge`) and complete compensating reversal (`execute_reversal`).
- [`src/job_automation/identity/review.py`](../../src/job_automation/identity/review.py): Review case deduplication and decision lifecycle (`accept`, `reject`, `defer`).
- [`src/job_automation/identity/service.py`](../../src/job_automation/identity/service.py): `IdentityService` providing atomic `resolve_and_commit` and `IdentityResolver` protocol implementation.
- [`src/job_automation/identity/cli.py`](../../src/job_automation/identity/cli.py): CLI handlers for `job_automation identity review`, `merge`, and `reverse-merge`.

### Storage Extensions (`src/job_automation/storage/`)
- [`src/job_automation/storage/migrations.py`](../../src/job_automation/storage/migrations.py): Added `MIGRATION_004_IDENTITY_TRACKING_AND_LINEAGE` (version 4) establishing `companies`, `company_aliases`, `source_identities`, `posting_observations`, `identity_review_cases`, and `identity_merge_events`.
- [`src/job_automation/storage/repositories/identity.py`](../../src/job_automation/storage/repositories/identity.py): `IdentityRepository` providing full persistence and query methods for identity entities.
- [`src/job_automation/storage/repositories/canonical_jobs.py`](../../src/job_automation/storage/repositories/canonical_jobs.py): Coordinated transaction nesting with `connection.transaction()`, added `UPDATE` support in `_save_revision_internal` for re-parented revisions, and synchronized `source_identities`.
- [`src/job_automation/storage/repositories/__init__.py`](../../src/job_automation/storage/repositories/__init__.py): Exported `IdentityRepository`.
- [`src/job_automation/storage/engine.py`](../../src/job_automation/storage/engine.py): Cached `identity` and `canonical_jobs` repository properties.
- [`src/job_automation/cli.py`](../../src/job_automation/cli.py): Registered `identity` subparser and CLI dispatch.

### Test Suites and Fixtures (`tests/identity/` & `tests/fixtures/identity/`)
- [`tests/fixtures/identity/README.md`](../../tests/fixtures/identity/README.md): Documentation of identity test scenarios.
- 12 automated test modules in `tests/identity/` (37 tests):
  - `test_contract_boundary.py` (5 tests: protocol conformance, tuple return, envelope, error hierarchy, INGEST-02 normalizer integration)
  - `test_hashing.py` (4 tests: deterministic hash, material vs metadata changes, null handling, formatting invariance)
  - `test_urls.py` (3 tests: conservative equivalence, job-specific endpoint classification, scheme/credential rejection)
  - `test_companies.py` (4 tests: legal form normalization, substantive name separation, scoped provider IDs, alias persistence)
  - `test_strong_matching.py` (5 tests: exact source, requisition matching, requisition conflict veto, board scoping, URL matching)
  - `test_similarity_and_review.py` (3 tests: text similarity review candidate, deduplication, no automatic merge)
  - `test_revisions_and_sources.py` (3 tests: observation recording, revision creation on content edit, deterministic current revision)
  - `test_merges_and_reversal.py` (3 tests: non-destructive merge, complete reversal, historical reference preservation)
  - `test_atomic_service.py` (3 tests: multi-table atomic commit, rollback on partial fault, idempotent replay)
  - `test_cli.py` (2 tests: CLI review commands, CLI merge and reverse-merge commands)
  - `test_windows_paths.py` (1 test: space and German umlaut paths on native Windows)
  - `test_windows_restart.py` (1 test: process restart, handle release, database reopen)

---

## 4. Key Architectural Decisions (D01–D11)

1. **D01: Forward Migration 4 (`004_identity_tracking_and_lineage`)**:
   - Added schema version 4 with tables: `companies`, `company_aliases`, `source_identities`, `posting_observations`, `identity_review_cases`, and `identity_merge_events`.
   - Backward compatible with existing versions 1, 2, and 3; leaves all foreign key cascades intact.
2. **D02: Conservative Company Identity Resolution**:
   - Allocates UUIDs only for evidenced company entries. Legal entity suffixes (`GmbH`, `AG`, `LLC`, `Co. KG`, `e.K.`) are stripped solely for lookup aliases.
   - Substantive name differences (`Nordlicht GmbH` vs `Nordlicht Services GmbH`) remain distinct unless explicitly corroborated.
   - Provider employer IDs are scoped strictly by `provider:board_id` (e.g. ID `0012` on tenant A is not assumed equal to `0012` on tenant B).
3. **D03: Strong Matching vs Fuzzy Similarity Review Candidates**:
   - Strong matches require either an existing source mapping, or matching company + namespaced requisition, or matching company + job-specific application URL.
   - Differing explicit requisition IDs strictly veto merging regardless of text similarity.
   - High text similarity (>0.85 token set ratio) routes exclusively to `MatchOutcome.REVIEW_CANDIDATE` and creates a `ReviewCase`. It never automatically merges opportunities.
4. **D04: Deterministic Revision Projection and Content Hashing**:
   - Computes `sha256:<hex64>` over a stable JSON projection of material C06 fields: title, description, company hint, URLs, locations, workplace, employment, compensation, language, and dates.
   - Excludes non-material observation metadata (`observed_at`, raw references, run IDs).
   - `select_current_revision` sorts by `last_seen_at` descending, with deterministic tie-breakers: `first_seen_at`, `provider`, `board_id`, `source_posting_id`, `revision_id`.
5. **D05: Reversible Merge and Reversal Lineage Architecture**:
   - `execute_merge` chooses the surviving job deterministically (oldest `first_seen_at` with UUID tie-breaker), re-parents revisions and source identities, clears source keys from predecessor, and writes a full JSON pre-merge snapshot to `identity_merge_events`. Predecessor rows are NEVER deleted.
   - `execute_reversal` reads the structured event, restores predecessor source identities and revisions, restores predecessor active availability, and logs a compensating `reversal` event.
6. **D06: Composable Transaction Boundaries**:
   - `IdentityService.resolve_and_commit` uses `with transaction(self.conn):` wrapping company, source, job, revision, observation, and review case persistence in a single ACID transaction. Fault injection at any point rolls back all partial writes cleanly.
7. **D07: Composite Source Key Scoping**:
   - Source identity is defined strictly by the composite tuple `(provider, board_id, source_posting_id)`.
   - Separate job boards sharing identical source posting IDs (e.g. ID `1001` on board A vs board B) remain strictly isolated as distinct canonical opportunities.
8. **D08: Availability Boundary Preservation**:
   - IDENTITY-01 does not infer posting availability.
   - Newly created postings pass through availability as defined by C06/C07 contracts (`active`). Merged predecessor jobs retain their original availability or mark merge metadata without availability alteration since IDENTITY-02 alone owns availability transitions.
9. **D09: Conservative URL Validation and Equivalence**:
   - Compares URLs conservatively: normalizes scheme and hostname to lowercase, strips default ports (80/443), preserves path case, query parameters, and fragments.
   - Classifies URLs with path segments like `/jobs/`, `/careers/`, `?job_id=`, or `?gh_jid=` as job-specific. Generic landing pages (`/careers`) are rejected as strong application keys.
10. **D10: Deduplicated Human Review Cases**:
    - Review cases are deduplicated by sorted candidate job IDs and reason code. Repeated sightings of similar postings update the existing case rather than flooding the review queue.
    - CLI commands support listing pending cases, inspecting evidence, and recording decisions (`accept`, `reject`, `defer`).
11. **D11: Safe Diagnostics and Redaction**:
    - Redacts credentials, query parameters containing auth tokens, and raw payloads from CLI listings and error messages to ensure zero sensitive data leakage.

---

## 5. Walkthrough of the Five Critical Scenarios

### Scenario 1: Repeated Postings (Unchanged Content)
- **Input**: Source posting observed at $t_1$, then re-observed at $t_2$ with identical content.
- **Behavior**: Resolver detects existing exact source mapping and identical revision content hash.
- **Outcome**:
  - Reuses the existing canonical job UUID and revision UUID.
  - Updates `last_seen_at` on both the canonical job and the revision to $t_2$.
  - Appends a new sighting record to `posting_observations`.
  - Zero duplicate rows in `canonical_jobs` or `posting_revisions`.

### Scenario 2: Changed Descriptions / Compensation (Material Edit)
- **Input**: Source posting observed at $t_1$, then re-observed at $t_2$ with modified description or salary.
- **Behavior**: Resolver matches the existing source key but detects a new normalized content hash.
- **Outcome**:
  - Reuses the existing canonical job UUID.
  - Creates a new `PostingRevision` with a distinct `revision_id` and new `content_hash`.
  - Sets `current_revision_id` on the canonical job to the new revision.
  - Retains the previous revision intact; historic downstream references (e.g. C08 evidence quotes, C13 frozen inputs) remain fully resolvable.

### Scenario 3: Different Boards with Identical Source IDs
- **Input**: Provider `greenhouse`, board `alpha`, posting ID `5001` vs provider `greenhouse`, board `beta`, posting ID `5001`.
- **Behavior**: Resolver evaluates composite source keys `(greenhouse, alpha, 5001)` and `(greenhouse, beta, 5001)`.
- **Outcome**:
  - Recognizes two distinct source identities.
  - Assigns two distinct canonical job UUIDs and independent revisions.
  - Prevents cross-tenant ID collisions.

### Scenario 4: Distinct Requisitions with Shared Text / Generic URLs
- **Input**: Two postings under the same company with identical job descriptions and a generic `/careers/apply` URL, but distinct requisition numbers `REQ-101` and `REQ-102`.
- **Behavior**: Requisition numbers are compared during strong matching. Differing explicit requisitions trigger an explicit veto.
- **Outcome**:
  - Automatic linking is blocked.
  - Two independent canonical job opportunities are maintained.
  - Prevents false conflation of distinct vacancies within the same employer.

### Scenario 5: Reversible Merge and Compensation
- **Input**: Job A and Job B exist independently. Operator executes `job_automation identity merge --surviving <UUID_A> --merged <UUID_B> --actor "admin" --reason "Confirmed duplicate"`. Later, operator reverses the merge with `job_automation identity reverse-merge --operation-id <OP_UUID>`.
- **Behavior**:
  - **Merge**: Re-parents Job B's revisions and source identities to Job A; updates `merge_lineage` on Job A; records full pre-merge state snapshot in `identity_merge_events`.
  - **Reversal**: Reads `identity_merge_events` snapshot; restores Job B's revisions and source keys; restores Job B's active availability; records compensating reversal event.
- **Outcome**:
  - Both jobs retain their original canonical UUIDs.
  - Revisions and observation history received during the merged state remain attached to their originating source keys without loss.

---

## 6. Native Windows Verification Evidence

The full verification recipe from `docs/stories/IDENTITY-01.md` was executed on Windows 11 with an isolated temporary directory containing spaces and German characters:

```powershell
$identity01Repo = (Resolve-Path '.').Path
$identity01Python = Join-Path $identity01Repo '.venv\Scripts\python.exe'
$identity01Config = Join-Path $identity01Repo 'config\app.example.json'
$identity01Tests = Join-Path $identity01Repo 'tests\identity'
$identity01AllTests = Join-Path $identity01Repo 'tests'
$identity01Temp = Join-Path $env:TEMP ('Job Automation Identität Prüfung ' + [guid]::NewGuid().ToString())
$identity01Data = Join-Path $identity01Temp 'Data Größe'
```

### Actual Verification Results:

```
Windows-11-10.0.26300-SP0
3.12.10 (tags/v3.12.10:0cc8128, Apr  8 2025, 12:21:36) [MSC v.1943 64 bit (AMD64)]
SQLite: 3.49.1
Timezone: Europe/Berlin

Packages:
- pydantic: 2.14.1
- pytest: 8.4.2
- tzdata: 2026.5

Storage Migration Output:
Storage migration: SUCCESS
  Database Path:     C:\Users\mrite\AppData\Local\Temp\Job Automation Identität Prüfung dbc4f296-d910-4777-ba59-71307ad12489\Data Größe\database\job_automation.db
  Newly Applied:     [1, 2, 3, 4]
  Current Version:   4
Storage status: OK
  Database Path:     C:\Users\mrite\AppData\Local\Temp\Job Automation Identität Prüfung dbc4f296-d910-4777-ba59-71307ad12489\Data Größe\database\job_automation.db
  Current Version:   4
  Applied Count:     4
    v1 (001_initial): applied at 2026-10-28T15:23:29.086437+00:00
    v2 (002_stage_checkpoints_and_audit): applied at 2026-10-28T15:23:29.087463+00:00
    v3 (003_profile_evidence_and_snapshots): applied at 2026-10-28T15:23:29.088462+00:00
    v4 (004_identity_tracking_and_lineage): applied at 2026-10-28T15:23:29.088462+00:00

Test Suite Results:
- tests\identity: 37 passed in 1.66s
- Boundary & Storage Tests: 422 passed in 3.39s
- Windows Path & Restart Tests: 2 passed in 0.77s
- Full Regression Suite: 580 passed in 11.14s

Exit Codes:
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

IDENTITY-01 produces durable canonical job and revision states consumed by:

1. **IDENTITY-02 (Posting Availability & Lifecycle)**:
   - Consumes `posting_observations` and `CanonicalJob` revision history.
   - Evaluates missing/grace counters and transitions posting availability (`active` -> `not_seen` -> `unavailable`).
2. **MATCH-01 (Eligibility & Assessment)**:
   - Consumes `CanonicalJob` and `PostingRevision` snapshots.
   - Links assessments (C11) to durable `canonical_job_id` and `revision_id`.
3. **RUN-01 (Pipeline Orchestration)**:
   - Drives ingestion -> normalization -> identity pipeline stages.
   - Consumes `IdentityResolutionResult` metrics (`is_new_canonical`, `is_new_revision`, `outcome`).
4. **SYNC-01 (Salesforce Reconciliation)**:
   - Uses permanent `canonical_job_id` and `canonical_company_id` for external synchronization.
   - Consumes merge/reversal lineage events when reconciling remote duplicate records.
5. **GEN-02 / OPS-01**:
   - Resolves historical text spans from frozen `PostingRevision` content hashes for tailoring and audit logs.

