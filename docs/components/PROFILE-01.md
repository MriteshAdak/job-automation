# Component Handoff: PROFILE-01 — Candidate Evidence Management

Component ID: **PROFILE-01**  
Status: **VERIFIED**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Prerequisite Handoffs: [docs/components/FND-01.md](FND-01.md), [docs/components/DATA-01.md](DATA-01.md)  
Planning Reference: [docs/stories/PROFILE-01.md](../stories/PROFILE-01.md)  
Date Completed: 28 October 2026  
Direct Covered Requirements: [R06](../../IMPLEMENTATION_BLUEPRINT.md#r06), [R11](../../IMPLEMENTATION_BLUEPRINT.md#r11), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15) (supporting R01, R04, R09, R14, R16)  

---

## 1. Prerequisites and Upstream Dependencies Verification

Before implementing PROFILE-01, all prerequisite contracts and services from **FND-01** and **DATA-01** were inspected and verified:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **C01 ProfileSnapshot** | FND-01 | **VERIFIED** | `job_automation.contracts.profile` (CandidateEligibility, CandidateFact, ProfileApprovalMetadata). |
| **C08 EvidenceReference** | FND-01 | **VERIFIED** | `job_automation.contracts.evidence` (CandidateEvidenceReference discriminated union). |
| **StorageEngine & Migrations** | DATA-01 | **VERIFIED** | SQLite connection, PRAGMA WAL mode, sequential migration runner, atomic transactions. |
| **AppConfig & ResolvedPaths** | FND-01 | **VERIFIED** | `profiles_dir`, `database_path`, loopback model endpoint, Windows path resolution. |

**Missing Prerequisite Report**: Zero missing prerequisites. All upstream dependencies are present and functional.

---

## 2. Implementation Summary by Story

All eight stories mapped in `docs/stories/PROFILE-01.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **PROFILE-01-S01** | Profile invariants, domain models & validation | **VERIFIED** | `src/job_automation/profile/models.py`, `validation.py`, `errors.py`. Graph cycle detection, parent kind integrity, precision date validation, calendar checks, and allowed uses vocabulary. |
| **PROFILE-01-S02** | Durable storage, evidence store & Migration 003 | **VERIFIED** | `MIGRATION_003_PROFILE_EVIDENCE_AND_SNAPSHOTS` in `migrations.py`, `ProfileRepository` in `storage/repositories/profiles.py`, `EvidenceStore` in `profile/evidence_store.py`. Enforces immutable snapshots, atomic transactions, and path sanitization. |
| **PROFILE-01-S03** | Manual draft intake, stable IDs & provenance | **VERIFIED** | `src/job_automation/profile/intake.py`, `provenance.py`. Stable UUID preservation across corrections, SHA-256 digest computation, and explicit rejection of imported approval authority. |
| **PROFILE-01-S04** | Explicit approval & atomic immutable publication | **VERIFIED** | `src/job_automation/profile/approval.py`. Enforces digest binding, base version validation, monotonic version sequencing, and idempotent re-publication. |
| **PROFILE-01-S05** | Shared inclusion rules for JSON and RAG | **VERIFIED** | `src/job_automation/profile/inclusion.py`. Enforces purpose filtering (`assessment`, `cv`, `cover_letter`), parent privacy protection, mandatory context conflict detection, and deterministic ordering. |
| **PROFILE-01-S06** | Version history, diffs & exact C08 resolution | **VERIFIED** | `src/job_automation/profile/history.py`, `references.py`. Structural diffing (added/removed/updated), version timeline, and exact historical C08 citation lookup without fallback to latest. |
| **PROFILE-01-S07** | Native Windows operator CLI workflow | **VERIFIED** | `src/job_automation/profile/cli.py`, `src/job_automation/cli.py`. Subcommands `import`, `review`, `approve`, `history`, `show`, `resolve` with safe output and exit codes. |
| **PROFILE-01-S08** | Synthetic fixtures, integrated lifecycle & handoff | **VERIFIED** | `tests/profile/test_lifecycle.py`, consumer fakes `tests/fakes/profile_consumers.py`, synthetic fixtures in `tests/fixtures/profile/`, and component handoff. |

---

## 3. Files Created and Modified

### New Source Files (`src/job_automation/profile/`)
- [`src/job_automation/profile/__init__.py`](../../src/job_automation/profile/__init__.py): Public exports for models, services, errors, and inclusion.
- [`src/job_automation/profile/errors.py`](../../src/job_automation/profile/errors.py): Safe domain exceptions (`ProfileValidationError`, `ProfileApprovalError`, `ProfileConflictError`, `FactNotFoundError`, `InclusionConflictError`, etc.).
- [`src/job_automation/profile/models.py`](../../src/job_automation/profile/models.py): Domain models (`DraftFact`, `DraftProfile`, `ProvenanceRecord`, `ProfileVersionRecord`, `ProfileInclusionView`, `ProfileDiff`).
- [`src/job_automation/profile/validation.py`](../../src/job_automation/profile/validation.py): Invariant validators (calendar dates, date ranges, parent graph cycle detection, allowed uses).
- [`src/job_automation/profile/evidence_store.py`](../../src/job_automation/profile/evidence_store.py): Content-addressable bulky file storage under `profiles_dir` with Windows path sanitization and directory traversal prevention.
- [`src/job_automation/profile/intake.py`](../../src/job_automation/profile/intake.py): Structured draft parser assigning stable UUIDs, preserving IDs on corrections, and computing SHA-256 digests.
- [`src/job_automation/profile/provenance.py`](../../src/job_automation/profile/provenance.py): Provenance record factory for documents and attestations.
- [`src/job_automation/profile/approval.py`](../../src/job_automation/profile/approval.py): Human approval validator binding draft digests and publishing `ProfileSnapshot`.
- [`src/job_automation/profile/inclusion.py`](../../src/job_automation/profile/inclusion.py): Shared inclusion rule evaluator for downstream JSON and RAG consumers.
- [`src/job_automation/profile/references.py`](../../src/job_automation/profile/references.py): Exact C08 citation resolver querying historical snapshots.
- [`src/job_automation/profile/history.py`](../../src/job_automation/profile/history.py): Version history timeline and structural snapshot comparison.
- [`src/job_automation/profile/service.py`](../../src/job_automation/profile/service.py): `ProfileService` facade coordinating storage, intake, approval, inclusion, and references.
- [`src/job_automation/profile/cli.py`](../../src/job_automation/profile/cli.py): CLI subcommand handlers.

### Storage Additions (`src/job_automation/storage/`)
- [`src/job_automation/storage/repositories/profiles.py`](../../src/job_automation/storage/repositories/profiles.py): `ProfileRepository` managing tables `profiles`, `profile_current`, `profile_facts`, `profile_provenance`, `profile_drafts`.
- [`src/job_automation/storage/migrations.py`](../../src/job_automation/storage/migrations.py): Added `MIGRATION_003_PROFILE_EVIDENCE_AND_SNAPSHOTS` to `ALL_MIGRATIONS`.
- [`src/job_automation/storage/engine.py`](../../src/job_automation/storage/engine.py): Added `profiles` repository property and `profiles_dir` resolution.
- [`src/job_automation/storage/repositories/__init__.py`](../../src/job_automation/storage/repositories/__init__.py): Exported `ProfileRepository`.
- [`src/job_automation/storage/connection.py`](../../src/job_automation/storage/connection.py): Composable nested transaction context manager without premature inner commits.

### CLI & Configuration
- [`src/job_automation/cli.py`](../../src/job_automation/cli.py): Registered `profile` subparser and command dispatcher.
- [`README.md`](../../README.md): Documented `job_automation profile` commands.

### Fixtures and Tests (`tests/`)
- `tests/fixtures/profile/synthetic_draft_v1.json`: Baseline synthetic draft fixture.
- `tests/fixtures/profile/synthetic_draft_v2_correction.json`: Multi-version correction and permission restriction fixture.
- `tests/fixtures/profile/README.md`: Fixture catalog and synthetic data guarantee.
- `tests/fakes/profile_consumers.py`: `FakeJsonContextConsumer` and `FakeRagContextConsumer`.
- `tests/profile/test_validation.py`: Invariants, date ranges, calendar validity, parent graph cycles.
- `tests/profile/test_repository.py`: Draft persistence, immutable snapshots, rollback, detached reads.
- `tests/profile/test_evidence_store.py`: Bulky file storage, staging, path sanitization, traversal rejection.
- `tests/profile/test_intake.py`: Intake parsing, stable ID assignment, approval separation.
- `tests/profile/test_provenance.py`: Attestation and document provenance records.
- `tests/profile/test_publication.py`: Digest binding, stale review rejection, monotonic version sequence.
- `tests/profile/test_inclusion.py`: Purpose matrix, parent privacy, mandatory conflicts, JSON/RAG parity.
- `tests/profile/test_history.py`: History listing and structural diffs.
- `tests/profile/test_references.py`: Exact C08 resolution across versions, job reference rejection.
- `tests/profile/test_lifecycle.py`: Complete multi-version lifecycle across simulated process restart.
- `tests/test_cli_profile.py`: CLI subprocess and runner tests for all subcommands.

---

## 4. Key Architectural Decisions (D01–D09)

1. **D01: Candidate and Fact Identity Stability**: A persistent candidate UUID is generated once or supplied explicitly. Fact UUIDs are allocated once and preserved across revisions when correcting assertions. Different assertions receive distinct UUIDs. Content hashes are used for revision tracking and digest checks, not as permanent entity keys.
2. **D02: Policy and Eligibility Separation**: Candidate truth (`explicit_eligibility`) remains strictly distinct from desired job preferences (`SearchPolicy` / C02). Omitted proficiencies or authorizations remain unknown and are never defaulted to affirmative values.
3. **D03: Precision Dates & Calendar Consistency**: Precision dates (`year`, `month`, `day`) preserve input granularity. Day precision is strictly validated against calendar rules (e.g. `2021-02-31` fails). Start date must precede or equal end date. Ongoing employment is explicitly marked (`is_ongoing=True`), keeping null end dates representing unspecified/unknown.
4. **D04: Provenance Modeling & Evidence Storage**: Immutable provenance records link to source documents or candidate attestations. Bulky source documents are stored content-addressably under `profiles_dir/<candidate_id>/` with SHA-256 hashes and atomic staging. Windows reserved characters and path traversal attempts are safely rejected.
5. **D05: Purpose-Aware Inclusion & Privacy Invariants**: Downstream use is restricted to supported purposes (`assessment`, `cv`, `cover_letter`). Default is empty permissions (`[]`), meaning private and excluded from all operational views. When a child fact is permitted but its parent is restricted, the child is included without expanding or leaking the restricted parent; if that parent is mandatory, an explicit `InclusionConflictError` is raised.
6. **D06: Immutability and Transaction Composability**: Published snapshots stored in SQLite are insert-only. Re-publishing under an existing version with different content raises `DuplicateKeyError`. Transactions are composable without premature inner commits.
7. **D07: Approval Binding to Review Digest**: Human approval requires deliberate invocation specifying the exact draft ID and SHA-256 content digest. Any edit made between review and approval invalidates the digest and causes an immediate conflict.
8. **D08: Historical Resolution vs. Permission for New Use**: Historical C08 citations `(profile_version, fact_id)` remain permanently resolvable for audit, even after facts are corrected, restricted, or removed in newer snapshots. Audit resolution does not grant permission for new generation.
9. **D09: Native Windows CLI**: Added `job_automation profile` command group (`import`, `review`, `approve`, `history`, `show`, `resolve`). Commands operate cleanly with absolute paths, non-ASCII directories, and exit code 0 on success, exit code 2 on error/conflict without leaking private claim text in diagnostics.

---

## 5. Verification Commands and Actual Results

### Automated Test Suite Execution
```powershell
& ".\.venv\Scripts\python.exe" -m pytest --cov=job_automation.profile --cov=job_automation.storage.repositories.profiles
```
Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0
rootdir: C:\Users\mrite\Projects\job-search
configfile: pyproject.toml
testpaths: tests
plugins: cov-6.3.0
collected 152 items

tests\contracts\test_context_model_assessment.py ......                  [  3%]
tests\contracts\test_contract_catalog.py ............................... [ 24%]
.                                                                        [ 25%]
tests\contracts\test_errors.py ...                                       [ 26%]
tests\contracts\test_interfaces.py .....                                 [ 30%]
tests\contracts\test_primitives.py .......                               [ 34%]
tests\contracts\test_profile_policy_evidence.py ....                     [ 37%]
tests\contracts\test_source_posting_identity.py ......                   [ 41%]
tests\contracts\test_work_records.py ....                                [ 44%]
tests\profile\test_evidence_store.py ....                                [ 46%]
tests\profile\test_history.py .                                          [ 47%]
tests\profile\test_inclusion.py ....                                     [ 50%]
tests\profile\test_intake.py .....                                       [ 53%]
tests\profile\test_lifecycle.py .                                        [ 53%]
tests\profile\test_provenance.py ..                                      [ 55%]
tests\profile\test_publication.py .....                                  [ 58%]
tests\profile\test_references.py ..                                      [ 59%]
tests\profile\test_repository.py .....                                   [ 63%]
tests\profile\test_validation.py .........                               [ 69%]
tests\storage\test_connection.py ...                                     [ 71%]
tests\storage\test_duplicate_keys.py ......                              [ 75%]
tests\storage\test_filestore.py ....                                     [ 77%]
tests\storage\test_migrations.py ....                                    [ 80%]
tests\storage\test_recovery.py ....                                      [ 82%]
tests\storage\test_repositories.py .......                               [ 87%]
tests\storage\test_transactions.py ....                                  [ 90%]
tests\test_cli.py .....                                                  [ 93%]
tests\test_cli_profile.py ..                                             [ 94%]
tests\test_cli_storage.py ..                                             [ 96%]
tests\test_configuration.py ......                                       [100%]

=============================== tests coverage ================================
TOTAL: 152 passed in 1.59s (88% coverage on profile, 95% on profile repository)
```

### Native Windows Verification Status

The native Windows verification recipe from `docs/stories/PROFILE-01.md` Section 9 was executed directly in PowerShell:

| Verification Scenario | Command / Target | Result | Exit Code | Notes |
|---|---|---|---|---|
| **Environment Check** | OS Version, Python 3.12.10, PowerShell 5.1 | `10.0.26300.0`, `5.1.26100.9711` | 0 | Verified native Windows 11 |
| **PROFILE-01 Suite** | `pytest tests/profile tests/test_cli_profile.py` | 40 passed in 0.74s | 0 | All targeted unit/integration tests passed |
| **Baseline Suite** | `pytest tests/contracts tests/storage tests/test_*.py` | 112 passed | 0 | All foundation/storage tests passed |
| **Storage Migration 003** | `storage migrate` to path containing spaces and umlauts (`PROFILE-01 Prüfung ä <uuid>`) | `Current Version: 3` | 0 | Migration 3 applied successfully |
| **Migration Idempotency** | Second `storage migrate` invocation | `Newly Applied: []` | 0 | Zero duplicate migrations applied |
| **Config Check from `$env:TEMP`** | `config check` from external working directory | `Configuration check: VALID` | 0 | Relative paths remain anchored to config |
| **CLI Profile Import** | `profile import --input synthetic_draft_v1.json` | `Status: UNAPPROVED` | 0 | Reports draft ID & content digest |
| **CLI Profile Review** | `profile review --draft-id <id>` | Lists draft facts and dates | 0 | Displayed facts cleanly |
| **CLI Profile Approve** | `profile approve --draft-id <id> --digest <digest>` | `Profile publication: SUCCESS (v1)` | 0 | Created approved immutable snapshot |
| **CLI Profile History** | `profile history` | `Sequence 1: version 'v1' [CURRENT]` | 0 | Lists version progression |
| **CLI Profile Show & Export** | `profile show --version v1 --export <path>` | Exported snapshot JSON | 0 | Created valid exported JSON file |
| **CLI C08 Resolve** | `profile resolve --version v1 --fact-id <uuid>` | `C08 Citation Resolution: SUCCESS` | 0 | Resolved exact historical fact |
| **Full Regression Suite** | `pytest` | 152 passed in 1.59s | 0 | 100% green test suite |

---

## 6. Known Limitations and Downstream Integration

1. **Downstream Context Construction (CONTEXT-01–04)**: PROFILE-01 provides the purpose-filtered `ProfileInclusionView`. Downstream components CONTEXT-01 (Full JSON) and CONTEXT-02–04 (RAG chunking, indexing, and retrieval) will consume this view directly. PROFILE-01 intentionally does not generate prompt chunks, compute token budgets, or call embedding models.
2. **Deterministic Matching (MATCH-01)**: MATCH-01 will consume `explicit_eligibility` and candidate facts from the active `ProfileSnapshot` alongside `SearchPolicy` (POLICY-01) to evaluate deterministic rules.
3. **Generation Worker Inputs (GEN-02)**: When freezing inputs for document generation, GEN-02 will freeze `profile_version` and resolve cited claims using `resolve_candidate_evidence_reference`.
4. **Data Retention & Backups (OPS-01)**: All published versions in `profiles` and bulky files in `profiles_dir` must be preserved by OPS-01; they are never deleted or truncated by PROFILE-01.
5. **Real Candidate Onboarding**: All verification was performed using synthetic fixtures. Real candidate onboarding and approval remains a candidate-facing operational step. Real candidate facts must not be committed to Git.

