# Component Handoff: FND-01 — Project Foundation and Shared Contracts

Component ID: **FND-01**  
Status: **VERIFIED**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Planning Reference: [docs/stories/FND-01.md](../stories/FND-01.md)  
Date Completed: 27 October 2026  
Direct Covered Requirements: [R03](../../IMPLEMENTATION_BLUEPRINT.md#r03), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15)  

---

## 1. Implementation Status by Story

All nine stories planned under FND-01 are implemented, tested, and verified on native Windows:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **FND-01-S01** | Python project & ownership boundaries | **VERIFIED** | `pyproject.toml`, `.gitignore`, `src/job_automation/` package baseline; pinned dependencies installed and imported cleanly without side effects. |
| **FND-01-S02** | Shared primitives, serialization, enums & errors | **VERIFIED** | Base models, 8 state domains, classified errors, UTC validation, precision dates, and `common.schema.json`. Unit tests pass. |
| **FND-01-S03** | Profile, policy, & evidence contracts (C01, C02, C08) | **VERIFIED** | C01 `ProfileSnapshot`, C02 `SearchPolicy`, C08 `EvidenceReference` union with candidate/job discriminators, schemas, and fixtures. |
| **FND-01-S04** | Source, posting, & identity contracts (C03–C07) | **VERIFIED** | C03 `SourceConfig`, C04 `FetchManifest`, C05 `RawPosting`/`SourceJobDraft`, C06 `NormalizedPosting`, C07 `CanonicalJob`/`PostingRevision`. |
| **FND-01-S05** | Context, model, & assessment contracts (C09–C11) | **VERIFIED** | C09 `ContextBundle`, C10 `ModelCall`/`ModelResult`, C11 `Assessment` with rule outcomes and hard failure precedence. |
| **FND-01-S06** | Sync, request, document, & summary contracts (C12–C15) | **VERIFIED** | C12 `SyncOperation`, C13 `GenerationRequest`, C14 `DraftDocument`/`Artifact`, C15 `RunSummary` with explicit counter units. |
| **FND-01-S07** | Service-independent interface boundaries | **VERIFIED** | 10 service protocols (`Adapter`, `Normalizer`, `IdentityResolver`, `RuleEvaluator`, `ContextSelector`, `ModelProvider`, `Assessor`, `SalesforceGateway`, `Generator`, `RendererDelivery`) and in-memory fakes. |
| **FND-01-S08** | Non-secret configuration & native Windows CLI | **VERIFIED** | `AppConfig`, path resolution, safe CLI `config check` with exit code 0 on success, exit code 2 on error/missing file. |
| **FND-01-S09** | Schema/fixture verification & component handoff | **VERIFIED** | 21 JSON schemas, positive/negative fixture catalog for all C01–C15 contracts, 78/78 tests passing on native Windows. |

---

## 2. Files Changed and Contracts Established

### Package and Source Files (`src/job_automation/`)
- [`src/job_automation/__init__.py`](../../src/job_automation/__init__.py): Package version `0.1.0`.
- [`src/job_automation/py.typed`](../../src/job_automation/py.typed): PEP 561 marker.
- [`src/job_automation/__main__.py`](../../src/job_automation/__main__.py): Entry point for `python -m job_automation`.
- [`src/job_automation/cli.py`](../../src/job_automation/cli.py): CLI parser and safe `config check` handler.
- [`src/job_automation/configuration.py`](../../src/job_automation/configuration.py): `AppConfig` and `ResolvedPaths`.

### Contracts (`src/job_automation/contracts/`)
- [`base.py`](../../src/job_automation/contracts/base.py): `ContractModel` base class (`frozen=True`, `extra="forbid"`, `schema_version="1.0"`).
- [`primitives.py`](../../src/job_automation/contracts/primitives.py): `LocalId`, `ProviderId`, `SourceKey`, `ContentHash`, `PrecisionDate`, `MoneyAmount`, `UtcDatetime`.
- [`enums.py`](../../src/job_automation/contracts/enums.py): 8 independent state domains and classification enums:
  1. `PipelineStage` (pending, running, succeeded, failed, skipped)
  2. `HardCriterionResult` (pass, fail, unknown)
  3. `AssessmentDisposition` (eligible, review, rejected)
  4. `PostingAvailability` (active, not_seen, unavailable, unknown)
  5. `ApplicationProgress` (New, Review, Shortlisted, Applied, Interviewing, Offer, Rejected, Withdrawn, Archived)
  6. `SyncOperationState` (pending, running, retry_wait, succeeded, failed)
  7. `GenerationProcessing` (pending, running, upload_pending, ready_for_review, failed)
  8. `DocumentApproval` (draft, approved, superseded)
- [`errors.py`](../../src/job_automation/contracts/errors.py): `ErrorCategory`, `RECOVERABLE_CATEGORIES`, `ValidationIssue`, `ClassifiedError`.
- [`evidence.py`](../../src/job_automation/contracts/evidence.py): C08 `CandidateEvidenceReference`, `JobEvidenceReference`, `SourceSpan`.
- [`profile.py`](../../src/job_automation/contracts/profile.py): C01 `ProfileSnapshot`, `ProfileApprovalMetadata`, `CandidateEligibility`, `CandidateFact`.
- [`policy.py`](../../src/job_automation/contracts/policy.py): C02 `SearchPolicy`, `HardCriterion`, `PreferenceRule`, `RelevanceConfig`.
- [`sources.py`](../../src/job_automation/contracts/sources.py): C03 `SourceConfig`.
- [`postings.py`](../../src/job_automation/contracts/postings.py): C04 `FetchManifest`, C05 `RawPosting`, `SourceJobDraft`, C06 `NormalizedPosting`, `StructuredLocation`, `JobCompensation`.
- [`identity.py`](../../src/job_automation/contracts/identity.py): C07 `CanonicalJob`, `PostingRevision`.
- [`context.py`](../../src/job_automation/contracts/context.py): C09 `ContextBundle`.
- [`models.py`](../../src/job_automation/contracts/models.py): C10 `ModelCall`, `ModelResult`, `TokenUsage`.
- [`assessment.py`](../../src/job_automation/contracts/assessment.py): C11 `Assessment`, `RuleOutcome`, `LLMAssessmentMetadata`.
- [`sync.py`](../../src/job_automation/contracts/sync.py): C12 `SyncOperation`, `SyncPayload`.
- [`generation.py`](../../src/job_automation/contracts/generation.py): C13 `GenerationRequest`, `FrozenInputVersions`.
- [`artifacts.py`](../../src/job_automation/contracts/artifacts.py): C14 `DraftDocument`, `Artifact`, `DocumentClaim`, `SubjectiveSection`.
- [`runs.py`](../../src/job_automation/contracts/runs.py): C15 `RunSummary`.
- [`interfaces.py`](../../src/job_automation/contracts/interfaces.py): 10 service Protocols and auxiliary response models.
- [`export_schemas.py`](../../src/job_automation/contracts/export_schemas.py): Deterministic JSON schema generator.

### Schemas (`schemas/v1/`)
- 21 JSON Schemas (Draft 2020-12) generated from contract models, plus `schemas/v1/common.schema.json` and `schemas/README.md`.

### Fixtures and Tests (`tests/`)
- Positive and negative fixtures in `tests/fixtures/contracts/C01/` through `C15/` with `tests/fixtures/contracts/README.md`.
- Conformance fakes in `tests/fakes/fake_services.py`.
- 10 test modules covering primitives, errors, profile/policy/evidence, sources/postings/identity, context/models/assessment, work records, interfaces, configuration, CLI, and contract catalog audit.

---

## 3. Decisions and Dependency Versions

### Technical Decisions Recorded
1. **Python Environment**: Selected Python 3.12.10 (64-bit) on native Windows.
2. **Build and Packaging**: Standard `setuptools` build backend (`setuptools.build_meta`) via `pyproject.toml`.
3. **Validation & Serialization**: Pydantic v2.14 (`pydantic>=2.9,<3` with `pydantic-core==2.50.1`). All models inherit from `ContractModel` with `frozen=True`, `extra="forbid"`, `validate_default=True`.
4. **Timezone Support**: Added `tzdata>=2024.1` dependency ensuring native Windows resolution of IANA timezones (specifically `Europe/Berlin`).
5. **Test Framework**: Selected and pinned `pytest>=8.3,<9` and `pytest-cov>=6.0,<7`.
6. **Local Model Loopback Boundary**: Hard-validated that `model_service_url` in configuration must resolve to loopback (`127.0.0.1`, `localhost`, or `::1`). No external model APIs or remote endpoints can be configured.
7. **Strict Runtime Boundary**: `data_root` is required to be an absolute path and must reside strictly outside the repository tree.

### Resolved Dependency Versions
- `python`: `3.12.10`
- `pydantic`: `2.14.1`
- `pydantic-core`: `2.50.1`
- `tzdata`: `2026.5`
- `pytest`: `8.4.2`
- `pytest-cov`: `6.3.0`

---

## 4. Commands and Test Results

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
collected 78 items

tests\contracts\test_context_model_assessment.py ......                  [  7%]
tests\contracts\test_contract_catalog.py ............................... [ 47%]
.                                                                        [ 48%]
tests\contracts\test_errors.py ...                                       [ 52%]
tests\contracts\test_interfaces.py .....                                 [ 58%]
tests\contracts\test_primitives.py .......                               [ 67%]
tests\contracts\test_profile_policy_evidence.py ....                     [ 73%]
tests\contracts\test_source_posting_identity.py ......                   [ 80%]
tests\contracts\test_work_records.py ....                                [ 85%]
tests\test_cli.py .....                                                  [ 92%]
tests\test_configuration.py ......                                       [100%]

============================= 78 passed in 0.39s ==============================
```

---

## 5. Native Windows Verification Status

All native Windows verification steps from `docs/stories/FND-01.md` Section 9 were executed directly on native Windows:

| Verification Scenario | Command / Target | Result | Exit Code | Notes |
|---|---|---|---|---|
| **Timezone Resolution** | `ZoneInfo('Europe/Berlin')` | `Europe/Berlin` | 0 | Resolved without system errors |
| **CLI Help & Version** | `python -m job_automation --help`, `--version` | Expected help & `0.1.0` | 0 | Clean output |
| **Unicode & Space Path** | `config check` with path `C:\Users\mrite\AppData\Local\Job Automation Prüfung ä` | `Configuration check: VALID` | 0 | Paths resolved beneath data root |
| **Config-Relative Reference** | Policy referenced as relative `policy.example.json` | Resolved to parent directory of config file | 0 | Independent of current working directory |
| **Different Working Directory** | Executed from `$env:TEMP` | `Configuration check: VALID` | 0 | Relative paths remain anchored to config |
| **Nonexistent Config** | `config check --config config\does-not-exist.json` | `Configuration check: FAILED` | 2 | Safe error message |
| **Relative Data Root** | `config check --data-root relative\path` | `Configuration check: FAILED` | 2 | Rejection enforced |
| **Inside-Repo Data Root** | `config check --data-root <repo>\data` | `Configuration check: FAILED` | 2 | Enforced strictly outside repo |
| **No File Side Effects** | Inspected `$env:LOCALAPPDATA\Job Automation Prüfung ä` | `Test-Path` returned `False` | 0 | No directories created by check |

### Live Service Verification
- **External Network / APIs**: Not applicable (FND-01 is fully offline).
- **Salesforce Org**: Not applicable (no mutations belong in FND-01; fakes verified conformance).
- **Ollama / Local Model Service**: Not applicable (mocked via `ModelProvider` fake; real runtime belongs to MODEL-01 / LLM-01).

---

## 6. Known Limitations and Pending Work

1. **Storage Repositories & Migrations**: Durable SQLite persistence, transactions, and run ledgers are not implemented here (owned by **DATA-01**).
2. **Real Candidate Facts & Search Criteria**: Approved candidate history and specific role criteria remain to be configured in **PROFILE-01** and **POLICY-01**.
3. **Source Adapters**: No live scraping or API calls are implemented; concrete adapters belong to **SOURCE-02** and **SOURCE-03**.
4. **Model Execution**: Local Ollama execution, benchmarks, and inference prompts belong to **MODEL-01**, **MODEL-02**, and **LLM-01**.
5. **Salesforce Integration**: Real OAuth connectivity and record upserts belong to **SFCLIENT-01** and **SYNC-01**.

---

## 7. Guidance for Dependent Components

- **DATA-01 (Storage & Migrations)**:
  - Consume `contracts/` models directly.
  - Store raw payloads and artifacts outside the SQLite database; retain paths/hashes and UUID keys in the database tables.
  - Enforce uniqueness on `(provider, board_id, source_posting_id)`.
- **PROFILE-01 (Candidate Evidence)**:
  - Use `ProfileSnapshot` (C01) and `CandidateFact`.
  - Preserve `PrecisionDate` (day/month/year) without fabricating days.
- **POLICY-01 (Search Policy)**:
  - Consume `SearchPolicy` (C02) and `HardCriterion`.
- **SOURCE-01 / SOURCE-02 (Adapters)**:
  - Implement the `Adapter` protocol from `job_automation.contracts.interfaces`.
  - Produce C05 `RawPosting` and `SourceJobDraft` without premature normalization.
- **INGEST-02 (Normalization)**:
  - Implement the `Normalizer` protocol to transform `SourceJobDraft` into `NormalizedPosting` (C06).
- **SFCLIENT-01 & SYNC-01 (Salesforce)**:
  - Implement `SalesforceGateway` protocol.
  - Push strictly `SyncPayload` fields to Salesforce `Job__c`, preserving user-owned fields.

