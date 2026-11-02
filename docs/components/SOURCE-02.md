# Component Handoff: SOURCE-02 — Adapter Interface and Manual Import

Component ID: **SOURCE-02**  
Status: **VERIFIED**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Prerequisite Handoffs: [docs/components/FND-01.md](FND-01.md), [docs/components/SOURCE-01.md](SOURCE-01.md)  
Planning Reference: [docs/stories/SOURCE-02.md](../stories/SOURCE-02.md)  
Date Completed: 28 October 2026  
Direct Covered Requirements: [R02](../../IMPLEMENTATION_BLUEPRINT.md#r02) (permitted acquisition, manual imports, honest coverage), [R03](../../IMPLEMENTATION_BLUEPRINT.md#r03) (preserved raw input and source mapping). Supporting constraints: [R04](../../IMPLEMENTATION_BLUEPRINT.md#r04) (source identity), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14) (native Windows), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15) (untrusted text and safe diagnostics), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16) (explicit failures and continuation evidence).

---

## 1. Prerequisites and Upstream Dependencies Verification

Before implementing SOURCE-02, foundational contracts and interfaces were verified:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **C03 SourceConfig Contract** | FND-01 | **VERIFIED** | Reused directly. `SourceConfig.acquisition_method == AcquisitionMethod.MANUAL_IMPORT` for manual sources. |
| **C05 RawPosting & SourceJobDraft** | FND-01 | **VERIFIED** | Reused directly with unchanged wire schema. Exact byte hash and scoped `SourceKey` preserved. |
| **Adapter Protocol Boundary** | FND-01 | **VERIFIED & REVISED** | Revised from untyped tuple/direct draft to typed `fetch_page(config, continuation=None) -> AdapterPage` and `draft_posting(raw) -> DraftResult`. Updated `FakeAdapter` and all foundation interface tests. |
| **Checked Selection & EffectiveSource** | SOURCE-01 | **VERIFIED** | Consumes checked `EffectiveSource` instances. Binds adapter capability to source acquisition method and verifies source enablement and permitted access review before invocation. |

---

## 2. Implementation Summary by Story

All eight planned stories from `docs/stories/SOURCE-02.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **SOURCE-02-S01** | Interface, result/provenance contracts & compatibility specification | **VERIFIED** | Established typed auxiliary contracts (`Continuation`, `RecordIssue`, `AdapterPage`, `DraftResult`) in `job_automation.contracts.adapter_results`. Updated `Adapter` Protocol in `interfaces.py`, updated foundation `FakeAdapter`, and exported 25 JSON schemas in `schemas/v1/`. |
| **SOURCE-02-S02** | Checked binding & continuation behavior | **VERIFIED** | `binding.py` and `continuation.py`. Enforces checked `EffectiveSource` selection, rejects disabled/unreviewed sources, validates continuation tokens, binds input/options hashes, and detects immediate non-progress cycles. |
| **SOURCE-02-S03** | Raw capture boundary, source identity & C05 mapping conventions | **VERIFIED** | `raw.py`, `manual_identity.py`, and `mapping.py`. Defines `RawCaptureSink` Protocol and `InMemoryRawCaptureSink`. Derives source identity preserving explicit IDs (casing and leading zeros) or conservative URL fallback (`url-v1:sha256:<hex64>`). Maps candidate fields without premature normalization and returns warnings for missing title. |
| **SOURCE-02-S04** | Manual URL-plus-text adapter | **VERIFIED** | `manual_text.py`. Single-record manual import from URL + text string or relative file path (with explicit `input_base_path`). Proves zero automated network calls via test socket guards. Inert handling of HTML, shell scripts, and SQL injection strings. |
| **SOURCE-02-S05** | Manual CSV adapter | **VERIFIED** | `manual_csv.py`. Standard CSV parser supporting UTF-8, UTF-8 BOM, CRLF line endings, multiline fields, commas, and explicit semicolons. Validates headers (duplicate/empty headers fail). Isolates record-level errors so invalid rows do not discard valid neighbor rows. Bounded pagination with input-hash binding. |
| **SOURCE-02-S06** | Record-level error isolation & import report API | **VERIFIED** | `import_report.py`. Pure diagnostic aggregator producing `ImportReport` with accurate counters (`records_encountered`, `records_accepted`, `records_rejected`, `records_with_warnings`, `total_issues`), status classification (`accepted`, `partial`, `failed`), and actionable guidance without credential leakage. |
| **SOURCE-02-S07** | Fake paginated adapter & shared conformance verification | **VERIFIED** | `tests/fakes/paginated_adapter.py`, `test_adapter_conformance.py`, `test_adapter_consumers.py`. Kept test fake strictly in test code. Built parameterized conformance harness proving `ScriptedPaginatedFakeAdapter`, `ManualTextAdapter`, and `ManualCsvAdapter` all satisfy the identical `Adapter` interface without adapter-specific branching. Verified C04 manifest simulation and mid-stream failure recovery. |
| **SOURCE-02-S08** | Native Windows, compatibility checks & component handoff | **VERIFIED** | `test_windows_import_paths.py`, fixture README, and native Windows recipe execution. Verified paths with spaces, German umlauts (`Stellen Prüfung ä.txt`), CRLF endings, handle release, and changed current working directory. Executed full test suite: 341/341 passed. |

---

## 3. Files Created and Modified

### Contracts and Interfaces
- [`src/job_automation/contracts/adapter_results.py`](../../src/job_automation/contracts/adapter_results.py): Auxiliary contract models (`Continuation`, `RecordIssue`, `AdapterPage`, `DraftResult`).
- [`src/job_automation/contracts/interfaces.py`](../../src/job_automation/contracts/interfaces.py): Updated `Adapter` Protocol (`fetch_page` and `draft_posting`).
- [`src/job_automation/contracts/export_schemas.py`](../../src/job_automation/contracts/export_schemas.py): Added auxiliary models to `CONTRACT_MODELS` and exported 25 JSON schemas.
- [`schemas/v1/adapter_page.schema.json`](../../schemas/v1/adapter_page.schema.json): Exported schema for `AdapterPage`.
- [`schemas/v1/continuation.schema.json`](../../schemas/v1/continuation.schema.json): Exported schema for `Continuation`.
- [`schemas/v1/record_issue.schema.json`](../../schemas/v1/record_issue.schema.json): Exported schema for `RecordIssue`.
- [`schemas/v1/draft_result.schema.json`](../../schemas/v1/draft_result.schema.json): Exported schema for `DraftResult`.

### Adapter Package Source Files (`src/job_automation/sources/adapters/`)
- [`src/job_automation/sources/adapters/__init__.py`](../../src/job_automation/sources/adapters/__init__.py): Public package exports.
- [`src/job_automation/sources/adapters/raw.py`](../../src/job_automation/sources/adapters/raw.py): `RawCaptureSink` Protocol, `InMemoryRawCaptureSink`, byte hashing and verification helpers.
- [`src/job_automation/sources/adapters/manual_identity.py`](../../src/job_automation/sources/adapters/manual_identity.py): Safe URL syntax validation and deterministic posting ID derivation.
- [`src/job_automation/sources/adapters/mapping.py`](../../src/job_automation/sources/adapters/mapping.py): Source-to-draft field mapping and candidate field vocabulary (`STANDARD_MAPPED_FIELDS`).
- [`src/job_automation/sources/adapters/binding.py`](../../src/job_automation/sources/adapters/binding.py): Preflight validation binding `EffectiveSource` to adapter instances.
- [`src/job_automation/sources/adapters/continuation.py`](../../src/job_automation/sources/adapters/continuation.py): Traversal token generation, validation, and cycle detection.
- [`src/job_automation/sources/adapters/manual_text.py`](../../src/job_automation/sources/adapters/manual_text.py): `ManualTextAdapter` implementation.
- [`src/job_automation/sources/adapters/manual_csv.py`](../../src/job_automation/sources/adapters/manual_csv.py): `ManualCsvAdapter` implementation.
- [`src/job_automation/sources/adapters/import_report.py`](../../src/job_automation/sources/adapters/import_report.py): `ImportReport` model and `build_import_report` aggregator.
- [`src/job_automation/sources/__init__.py`](../../src/job_automation/sources/__init__.py): Re-exported adapter types at the `job_automation.sources` namespace.

### Test Doubles, Fixtures, and Tests (`tests/`)
- [`tests/fakes/fake_services.py`](../../tests/fakes/fake_services.py): Updated foundation `FakeAdapter` conforming to revised `AdapterPage` / `DraftResult` interface.
- [`tests/fakes/paginated_adapter.py`](../../tests/fakes/paginated_adapter.py): Deterministic test fake `ScriptedPaginatedFakeAdapter` kept strictly in test code.
- [`tests/fixtures/sources/manual/text/`](../../tests/fixtures/sources/manual/text/): Synthetic text fixtures (`valid_job.txt`, `empty_job.txt`, `hostile_job.txt`).
- [`tests/fixtures/sources/manual/csv/`](../../tests/fixtures/sources/manual/csv/): Synthetic CSV fixtures (`valid_jobs.csv`, `valid_semicolon.csv`, `multiline_quoted.csv`, `invalid_missing_columns.csv`, `invalid_duplicate_headers.csv`, `mixed_errors.csv`, `bom_jobs.csv`).
- [`tests/fixtures/sources/paginated/scripted_pages.json`](../../tests/fixtures/sources/paginated/scripted_pages.json): Multi-page fixture scenario for fake paginated testing.
- [`tests/fixtures/sources/manual/README.md`](../../tests/fixtures/sources/manual/README.md): Catalog of manual import fixtures.
- 12 test modules under `tests/sources/` and `tests/contracts/`:
  - `test_adapter_results.py`, `test_adapter_binding.py`, `test_continuation.py`, `test_raw_provenance.py`, `test_manual_identity.py`, `test_source_mapping.py`, `test_manual_text.py`, `test_manual_csv.py`, `test_csv_continuation.py`, `test_import_report.py`, `test_adapter_conformance.py`, `test_adapter_consumers.py`, `test_windows_import_paths.py`.

---

## 4. Key Architectural Decisions (D01–D08)

1. **D01: Typed Adapter Boundary & Consumer Migration**:
   - Upgraded `Adapter.fetch_page` from returning `tuple[list[RawPosting], str | None, FetchOutcome]` to `AdapterPage`.
   - Upgraded `Adapter.draft_posting` from returning `SourceJobDraft` to `DraftResult` (isolating record-level mapping issues).
   - Preserved C03, C04, and C05 contract schemas without wire breaks; auxiliary types live in `contracts/adapter_results.py`.
2. **D02: Checked Selection Binding**:
   - Adapters require a validated `EffectiveSource` from SOURCE-01. Disabled, unreviewed, or method-mismatched sources fail preflight.
   - Verified that `fetch_page(config)` matches the bound source key, provider, and board identity.
3. **D03: Continuation Token State & C04 Bridge**:
   - `Continuation` encodes traversal kind (`cursor`, `page`, `offset`, `local_record`), value, source key, scope ID, adapter binding, input hash, and options hash.
   - Deterministic reversible string encoding `cont-v1:<urlsafe_base64>` bridges losslessly to string fields (`cursor_in`, `cursor_out`) in C04 `FetchManifest`.
4. **D04: Exact-Byte Raw Capture Boundary**:
   - Preserves exact raw bytes (including BOM, CRLF, and custom delimiters) via `RawCaptureSink` protocol.
   - Computes `sha256:<hex64>` content hash directly over bytes. Parent batch file references remain distinct from individual row payload references.
5. **D05: Conservative Source Identity & Candidate Vocabulary**:
   - Prefers explicit `source_posting_id` (preserving exact string, casing, and leading zeros like `"0007"`).
   - Fallback is conservative URL identity: `url-v1:sha256:<hex64>` of the exact validated URL string.
   - Documented candidate vocabulary: `title`, `company_name_hint`, `description`, `source_url`, `application_url`, `locations_raw`, `workplace_type_raw`, `employment_type_raw`, `compensation_raw`, `source_published_raw`, `source_deadline_raw`. Missing title produces a non-blocking warning, not an inferred title.
6. **D06: Manual Import Input Modes & Zero-Network Guarantee**:
   - URL-plus-text and CSV import require zero network activity (enforced by test socket guards).
   - Relative paths are resolved strictly against an explicit `input_base_path` parameter, never relying on process working directory.
7. **D07: CSV Header Contract & Dialect Options**:
   - Required columns: `source_url` and `text` (or mapped custom headers via `column_mapping`).
   - Default comma delimiter with explicit semicolon option for European/German exports.
   - Bounded page sizes with token invalidation if file bytes are modified between pagination requests.
8. **D08: Record-Level Error Isolation & Diagnostic Reporting**:
   - Malformed rows (bad URLs, missing text, column count mismatches) produce `RecordIssue` items locating physical and logical positions. Valid neighbor rows are preserved and drafted.
   - `build_import_report` compiles safe, redacted diagnostics without dumping raw job descriptions or sensitive parameters.

---

## 5. Verification Commands and Actual Results

### Native Windows Execution Environment
- **Platform**: Windows 11 (10.0.26300-SP0), AMD64
- **Python**: 3.12.10 (tags/v3.12.10:0cc8128, 64-bit)
- **Key Packages**: `pydantic==2.14.1`, `pytest==8.4.2`, `tzdata==2026.5`

### Verification Recipe Execution
The exact PowerShell verification recipe from `docs/stories/SOURCE-02.md` was executed:

```powershell
$source02Repo = (Get-Location).Path
$source02Python = Join-Path $source02Repo '.venv\Scripts\python.exe'
$source02SourceTests = Join-Path $source02Repo 'tests\sources'
$source02ContractTests = Join-Path $source02Repo 'tests\contracts'
$source02WindowsTests = Join-Path $source02SourceTests 'test_windows_import_paths.py'
$source02TempRoot = Join-Path $env:TEMP ('Job Automation Prüfung ä SOURCE-02 ' + [guid]::NewGuid().ToString())

& $source02Python -c "import platform, sys; print(platform.platform()); print(sys.version)"
& $source02Python -m pip show pydantic pytest tzdata
& $source02Python -m pytest $source02ContractTests $source02SourceTests
$source02FocusedExit = $LASTEXITCODE

New-Item -ItemType Directory -Path $source02TempRoot | Out-Null
Push-Location $source02TempRoot
try {
    & $source02Python -m pytest $source02WindowsTests --basetemp (Join-Path $source02TempRoot 'Test Data Größe')
    $source02WindowsExit = $LASTEXITCODE
} finally {
    Pop-Location
}

& $source02Python -m pytest
$source02RegressionExit = $LASTEXITCODE

[pscustomobject]@{
    FocusedExit = $source02FocusedExit
    WindowsExit = $source02WindowsExit
    RegressionExit = $source02RegressionExit
}
```

### Actual Test Results
```text
FocusedExit WindowsExit RegressionExit
----------- ----------- --------------
          0           0              0
```
- **Focused checks (`tests/contracts` + `tests/sources`)**: 186 passed in 0.79s.
- **Windows-specific checks (isolated temp dir with umlauts/spaces)**: 3 passed in 0.28s.
- **Complete repository regression suite**: 341 passed in 9.74s.

---

## 6. Downstream Handoff Instructions and Integration Gaps

### Interfaces for Next Components
1. **SOURCE-03 (Concrete Adapters)**:
   - Implement the `Adapter` Protocol: `fetch_page(config, continuation=None) -> AdapterPage` and `draft_posting(raw) -> DraftResult`.
   - Use `create_continuation` and `validate_continuation` to produce and check provider pagination tokens.
   - Use `map_raw_record_to_draft_fields` for candidate fields.
2. **INGEST-01 (Fetch Controller)**:
   - Orchestrates multi-page fetching via `fetch_page`, tracks cursors with `Continuation.encode()`, and persists raw payloads via durable `RawCaptureSink`.
   - Aggregates page results into C04 `FetchManifest` without overwriting successful earlier pages when a mid-stream failure occurs.
3. **INGEST-02 (Common Normalization & Validation)**:
   - Consumes `SourceJobDraft.source_mapped_fields` produced by `draft_posting`.
   - Normalizes raw locations, currencies, workplace types, and HTML descriptions into C06 `NormalizedPosting`, quarantine-routing any unresolved missing titles or invalid types.

### Known Gaps and Deferred Decisions
- **D09 (Production Operator CLI & Durable Storage)**: Owned by INGEST-01/RUN-01. Manual import CLI and SQLite persistence of raw revisions will be connected in future orchestration stories.
- **D10 (Provider-Specific Remote Integration)**: Owned by SOURCE-03 instances. No external job board or live API was contacted during this component.

