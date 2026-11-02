# Component Handoff: INGEST-02 — Common Normalization and Validation

Component ID: **INGEST-02**  
Status: **VERIFIED**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Prerequisite Handoffs: [docs/components/FND-01.md](FND-01.md), [docs/components/SOURCE-02.md](SOURCE-02.md), [docs/components/INGEST-01.md](INGEST-01.md)  
Planning Reference: [docs/stories/INGEST-02.md](../stories/INGEST-02.md)  
Date Completed: 28 October 2026  
Direct Covered Requirements: [R03](../../IMPLEMENTATION_BLUEPRINT.md#r03) (map, normalize, and validate every posting into a common schema with provenance).  
Supporting Constraints: [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14) (native Windows conventions), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15) (untrusted text and safe diagnostics without secret leakage), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16) (inspectable quarantine handoffs).

---

## 1. Prerequisites and Contract Integrity Verification

INGEST-02 was implemented strictly using the existing C05 and C06 contracts without hand-editing generated schemas or altering shared models:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **C05 Contracts** | FND-01 | **VERIFIED** | Reused `SourceJobDraft` and `RawPosting` unchanged. Preserves `source_key`, `raw_reference`, `fetch_time`, `original_fields`, and `source_mapped_fields`. |
| **C06 Contracts** | FND-01 | **VERIFIED** | Reused `NormalizedPosting`, `StructuredLocation`, and `JobCompensation` unchanged. Retains all core types, enums (`WorkplaceType`, `EmploymentType`, `SalaryPeriod`, `CompensationProvenance`), and field definitions. |
| **Normalizer Protocol Boundary** | FND-01 | **VERIFIED** | Verified `Normalizer` Protocol conformance: `normalize(draft: SourceJobDraft) -> tuple[NormalizedPosting | None, list[ValidationIssue]]`. |
| **Capture Sinks & Adapters** | SOURCE-02 / SOURCE-03 | **VERIFIED** | Integrated with `RawCaptureSink`, `ManualTextAdapter`, `ManualCsvAdapter`, and `ArbeitnowAdapter`. |

---

## 2. Implementation Summary by Story

All eight planned stories from `docs/stories/INGEST-02.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **INGEST-02-S01** | Freeze contracts, provenance access and unknown semantics | **VERIFIED** | Preserved `Normalizer` protocol unchanged; established `RawProvenanceReader` port, `InMemoryRawProvenanceReader`, `CaptureSinkProvenanceReader`, and `NormalizationOptions` in `ports.py`. Enforced result invariants: fatal errors return `(None, issues)`; warnings return `(NormalizedPosting, issues)`; never returns `(None, [])`. |
| **INGEST-02-S02** | Establish fixtures for heterogeneous inputs and failures | **VERIFIED** | Created synthetic multi-shape test corpus in `tests/fixtures/ingestion/normalization/` covering manual HTML, CSV (UTF-8 BOM/CRLF), nested ATS, flat feed (Arbeitnow), hostile scripts, precision zones, multiple locations, workplace/restriction conflicts, compensation units/origins, invalid types, and mixed batches. |
| **INGEST-02-S03** | Preserve provenance and clean core text fields | **VERIFIED** | Implemented deterministic HTML-to-text parser using standard library `HTMLParser` in `text.py`. Decodes entities once, discards `<script>`, `<style>`, and comments, normalizes line endings (`\r\n` → `\n`), trims outer whitespace, preserves German umlauts/gender markers (`(m/w/d)`), keeps plain text (`C++`, `C#`, `x < 5`) intact, and validates HTTP/HTTPS URLs safely. |
| **INGEST-02-S04** | Normalize source dates without inventing precision | **VERIFIED** | Implemented UTC instant conversion for offset-aware ISO strings in `dates.py`. Accepts declared epoch units only (never guesses by digit count); rejects booleans as dates; preserves date-only precision as unknown timestamps with `unsupported_representation` warnings (never invents midnight or end-of-day); handles naive datetimes via IANA timezones (Europe/Berlin) including DST folds and gaps; maps `observed_at` from `draft.fetch_time` without wall-clock drift. Absent deadlines are not invented (`None`). |
| **INGEST-02-S05** | Normalize locations, workplace and remote restrictions | **VERIFIED** | Implemented multi-location normalization in `locations.py` preserving original text and stable order, normalizing country aliases (`Deutschland`/`Germany` → `DE`) without guessing ambiguous cities (`Springfield`). Implemented workplace and employment normalization in `workplace.py`: maps aliases, treats boolean `remote=False` as unknown, collapses equivalent employment labels (`Vollzeit`/`Full-time`), flags conflicting labels, and verifies that remote does NOT imply worldwide eligibility (restrictions stay empty/unknown without worldwide assumption). |
| **INGEST-02-S06** | Normalize compensation with explicit units and provenance | **VERIFIED** | Implemented Decimal-safe bounds parsing in `compensation.py`. Rejects booleans, negative amounts, and inverted ranges (`min > max`). Enforces explicit units: missing salary stays unknown (`None`); incomplete-unit compensation (e.g. `75.000 - 85.000 EUR` without period, or bare `70000`) remains `None` with `unsupported_representation` warnings, strictly preventing C06 `JobCompensation` from silently defaulting to yearly or EUR. Unsupported periods (weekly/daily) and ambiguous symbols (`$`) stay unknown. |
| **INGEST-02-S07** | Compose validation and emit inspectable quarantine results | **VERIFIED** | Composed field normalizers in `service.py` (`DefaultNormalizer`). Constructed `QuarantineHandoff` in `quarantine.py` preserving draft locators, issue lists, and raw references without secret leakage. Verified independent record failure isolation in mixed batches (malformed records quarantine while valid neighbors succeed). |
| **INGEST-02-S08** | Verify cross-source behavior and publish the handoff | **VERIFIED** | Verified cross-source equivalence across manual HTML, CSV, and API feed shapes in `test_normalization_equivalence.py`. Verified end-to-end integration with real `ManualTextAdapter`, `ManualCsvAdapter`, and `ArbeitnowAdapter` in `test_normalization_adapter_integration.py`. Verified native Windows constraints in `test_normalization_windows.py`. Executed full suite regression (543 passing tests). |

---

## 3. Files Created and Modified

### Normalization Component Package (`src/job_automation/ingestion/normalization/`)
- [`src/job_automation/ingestion/normalization/__init__.py`](../../src/job_automation/ingestion/normalization/__init__.py): Public normalization exports (`DefaultNormalizer`, `NormalizationOptions`, `RawProvenanceReader`, `QuarantineHandoff`, etc.).
- [`src/job_automation/ingestion/normalization/ports.py`](../../src/job_automation/ingestion/normalization/ports.py): Protocols (`RawProvenanceReader`), implementations (`InMemoryRawProvenanceReader`, `CaptureSinkProvenanceReader`), and `NormalizationOptions`.
- [`src/job_automation/ingestion/normalization/models.py`](../../src/job_automation/ingestion/normalization/models.py): Quarantine handoff envelope (`QuarantineHandoff`) and normalization outcome container (`NormalizationResult`).
- [`src/job_automation/ingestion/normalization/text.py`](../../src/job_automation/ingestion/normalization/text.py): HTML-to-text cleaning, script/style stripping, entity decoding, title/company cleaning, and safe URL validation.
- [`src/job_automation/ingestion/normalization/dates.py`](../../src/job_automation/ingestion/normalization/dates.py): ISO-8601 UTC conversion, declared epoch parsing, naive timezone resolution (Europe/Berlin), DST gap/fold handling, and `observed_at` semantics.
- [`src/job_automation/ingestion/normalization/locations.py`](../../src/job_automation/ingestion/normalization/locations.py): Multi-location parser, country alias normalization (`DE`, `AT`, `CH`), city state handling (Berlin, Hamburg), and duplicate removal.
- [`src/job_automation/ingestion/normalization/workplace.py`](../../src/job_automation/ingestion/normalization/workplace.py): Workplace arrangement mapping (`onsite`, `hybrid`, `remote`), boolean `remote=False` handling, remote eligibility restrictions, and employment type collapsing.
- [`src/job_automation/ingestion/normalization/compensation.py`](../../src/job_automation/ingestion/normalization/compensation.py): Decimal compensation bounds, currency/period resolution, gross/net detection, provenance tracking, and incomplete-unit warning fallback.
- [`src/job_automation/ingestion/normalization/provenance.py`](../../src/job_automation/ingestion/normalization/provenance.py): Field provenance builder linking populated C06 attributes to source/mapping paths.
- [`src/job_automation/ingestion/normalization/quarantine.py`](../../src/job_automation/ingestion/normalization/quarantine.py): `build_quarantine_handoff` builder preserving failed draft locators.
- [`src/job_automation/ingestion/normalization/service.py`](../../src/job_automation/ingestion/normalization/service.py): `DefaultNormalizer` implementing the `Normalizer` Protocol.

### Modified Files
- [`src/job_automation/ingestion/__init__.py`](../../src/job_automation/ingestion/__init__.py): Exposes `DefaultNormalizer`, options, readers, and quarantine handoff models.

### Test Suites and Fixtures (`tests/ingestion/` & `tests/fixtures/ingestion/normalization/`)
- [`tests/fakes/normalization_inputs.py`](../../tests/fakes/normalization_inputs.py): Test input builders and draft generators.
- [`tests/fixtures/ingestion/normalization/README.md`](../../tests/fixtures/ingestion/normalization/README.md): Documentation of the 14 synthetic fixture categories.
- Synthetic fixture files in `tests/fixtures/ingestion/normalization/`:
  - `manual_text/office_html.json`
  - `manual_csv/office_bom_crlf.csv`
  - `nested_ats/office_multilocation.json`
  - `flat_feed/remote_boolean.json`
  - `structured_board/hybrid_restricted.json`
  - `unknowns/absent_null_empty.json`
  - `text/hostile_and_malformed.json`
  - `dates/precision_and_zones.json`
  - `locations/multiple_and_ambiguous.json`
  - `workplace/restriction_conflicts.json`
  - `compensation/units_and_origins.json`
  - `invalid/typed_and_required.json`
  - `provenance/broken_and_replay.json`
  - `mixed/three_records.json`
- 12 automated test modules in `tests/ingestion/` (71 normalization tests):
  - `test_normalization_boundary.py` (protocol conformance, invariants, version rejection)
  - `test_normalization_text.py` (HTML cleaning, scripts, umlauts, inert plain text, title, company, URLs)
  - `test_normalization_dates.py` (ISO, UTC, declared epochs, date-only precision, DST gaps/folds, observed_at)
  - `test_normalization_locations.py` (country aliases, multi-location sets, ambiguous locations, deduplication)
  - `test_normalization_workplace.py` (remote does not imply worldwide, boolean false, restrictions, employment)
  - `test_normalization_compensation.py` (missing salary unknown, explicit units, incomplete-unit warnings, range invariants)
  - `test_normalization_validation.py` (composed pipeline, field provenance, warnings vs errors)
  - `test_normalization_quarantine.py` (failure isolation, quarantine envelope locators, mixed batch)
  - `test_normalization_equivalence.py` (cross-source factual equivalence across HTML, CSV, and API feeds)
  - `test_normalization_fixtures.py` (multi-shape synthetic corpus validation)
  - `test_normalization_adapter_integration.py` (integration with ManualTextAdapter, ManualCsvAdapter, ArbeitnowAdapter)
  - `test_normalization_windows.py` (Unicode paths with spaces/umlauts, handle release, alternate CWD, tzdata)

---

## 4. Key Architectural Decisions (D01–D08)

1. **D01: Injected Raw Provenance Reader & Protocol Preservation**:
   - Kept `normalize(draft: SourceJobDraft) -> tuple[NormalizedPosting | None, list[ValidationIssue]]` unchanged, strictly satisfying the boundary protocol in `job_automation.contracts.interfaces.Normalizer`.
   - Injected `RawProvenanceReader` resolves `draft.raw_reference` to immutable bytes and verifies the SHA-256 content hash. Unresolvable raw references yield an explicit `raw_reference_unresolved` error, never a fabricated hash.
2. **D02: C06 Contract Preservation & Unknown Collections**:
   - Implemented INGEST-02 strictly against existing C05 and C06 contracts without modifying shared models.
   - For collections, `locations` and `remote_eligibility_restrictions` default to `[]`. Where facts are unstated, empty collections are produced without inventing facts.
   - Required fields (`company_name_hint`, `title`, `description_clean`, `source_url`) emit blocking `missing_required_field` or `empty_after_cleaning` errors when absent.
3. **D03: Compensation Explicit Units & Incomplete-Unit Fallback**:
   - Because existing C06 `JobCompensation` defaults currency to EUR and period to yearly, constructing a `JobCompensation` instance on incomplete inputs (e.g. `75.000 - 85.000 EUR` lacking period, or bare `70000`) would silently fabricate yearly EUR comparability.
   - To prevent this, incomplete-unit compensation stays `None` (unknown) on `NormalizedPosting` and emits an `unsupported_representation` warning issue linking the raw text. Missing salary stays `None` with zero warnings.
4. **D04: Date Precision & Observation Semantics**:
   - Date-only and month-only strings (e.g. `2026-10-31`) leave the timestamp instant `None` with an `unsupported_representation` warning (never invents midnight or end-of-day).
   - Absent deadlines stay `None` without warnings.
   - `observed_at` strictly derives from `draft.fetch_time` converted to UTC, preventing wall-clock drift across replays.
   - Arbeitnow `created_at` remains unpromoted in `source_published_at` per U05.
5. **D05: Field Provenance Tracking**:
   - Populates `field_provenance` for every populated output field, carrying forward source paths from `draft.source_mapped_fields.get("provenance")`.
6. **D06: Honest Workplace & Remote Semantics**:
   - Boolean `remote=False` does not imply onsite; it maps to `WorkplaceType.UNKNOWN` with an `ambiguous_value` warning.
   - Remote workplace does NOT imply worldwide eligibility; missing restrictions remain `[]` without inferring worldwide access.
   - Explicit regional restrictions (e.g. `['DE']`, `['EU']`) are preserved.
7. **D07: Structured Quarantine Handoff Envelope**:
   - Failures produce an inspectable `QuarantineHandoff` carrying `quarantine_id`, `draft_reference`, `raw_content_hash`, `source_key`, `mapping_version`, `normalizer_version`, `observed_at`, `input_ref`, `record_index`, and ordered `ValidationIssue` records.
   - Allows failed records to be isolated and reviewed without failing valid neighbors.
8. **D08: Deterministic Parser & Zero External Network**:
   - Standard library `HTMLParser` extracts readable text without external dependencies or process launches.
   - Scripts, styles, and comments are dropped; entities are decoded once; plain text (`C++`, `C#`, `x < 5`) is preserved inertly.

---

## 5. Verification Matrix and Native PowerShell Checks

Verification was performed using native Windows PowerShell against `.venv\Scripts\python.exe` (Python 3.12.10, pytest 8.4.2, tzdata 2026.5).

```powershell
$ingest02Repo = (Get-Location).Path
$ingest02Python = Join-Path $ingest02Repo '.venv\Scripts\python.exe'
$ingest02Tests = Join-Path $ingest02Repo 'tests\ingestion'
$ingest02WindowsTest = Join-Path $ingest02Tests 'test_normalization_windows.py'
$ingest02Contracts = Join-Path $ingest02Repo 'tests\contracts'
$ingest02Sources = Join-Path $ingest02Repo 'tests\sources'
$ingest02Policy = Join-Path $ingest02Repo 'tests\policy'
$ingest02AllTests = Join-Path $ingest02Repo 'tests'
$ingest02TempRoot = Join-Path $env:TEMP ('Job Automation Prüfung ä INGEST-02 ' + [guid]::NewGuid().ToString())

& $ingest02Python -c "import platform, sys; from zoneinfo import ZoneInfo; print(platform.platform()); print(sys.version); print(ZoneInfo('Europe/Berlin'))"
$ingest02EnvironmentExit = $LASTEXITCODE
& $ingest02Python -m pip show pydantic pytest tzdata
& $ingest02Python -m pytest $ingest02Tests -k normalization
$ingest02FocusedExit = $LASTEXITCODE
& $ingest02Python -m pytest $ingest02Contracts $ingest02Sources $ingest02Policy
$ingest02BoundaryExit = $LASTEXITCODE

New-Item -ItemType Directory -Path $ingest02TempRoot | Out-Null
Push-Location $ingest02TempRoot
try {
    & $ingest02Python -m pytest $ingest02WindowsTest --basetemp (Join-Path $ingest02TempRoot 'Test Data Größe')
    $ingest02WindowsExit = $LASTEXITCODE
} finally {
    Pop-Location
}

& $ingest02Python -m pytest $ingest02AllTests
$ingest02RegressionExit = $LASTEXITCODE
[pscustomobject]@{
    EnvironmentExit = $ingest02EnvironmentExit
    FocusedExit     = $ingest02FocusedExit
    BoundaryExit    = $ingest02BoundaryExit
    WindowsExit     = $ingest02WindowsExit
    RegressionExit  = $ingest02RegressionExit
}
```

### Actual Check Results

| Check / Lane | Command | Exit Code | Result Summary |
|---|---|:---:|---|
| **Environment Check** | Python platform, version, ZoneInfo('Europe/Berlin') | `0` | Windows-11-10.0.26300-SP0, Python 3.12.10, Europe/Berlin |
| **Dependency Manifest** | `pip show pydantic pytest tzdata` | `0` | Pydantic 2.14.1, pytest 8.4.2, tzdata 2026.5 verified |
| **Focused Normalization** | `pytest tests/ingestion -k normalization` | `0` | **71 passed**, 56 deselected in 0.56s |
| **Boundary Regressions** | `pytest tests/contracts tests/sources tests/policy` | `0` | **321 passed** in 6.09s |
| **Native Windows Isolated** | `pytest test_normalization_windows.py --basetemp ...` | `0` | **4 passed** under Unicode root `Test Data Größe` |
| **Full Regression Suite** | `pytest tests` | `0` | **543 passed** in 9.21s |

---

## 6. Next Consumers and Handoff

1. **IDENTITY-01 (Company/Job Identity & Revisions)**:
   - Consumes validated C06 `NormalizedPosting` records to resolve canonical company mappings, generate revision hashes, and detect duplicates.
2. **MATCH-01 (Deterministic Rule Assessment)**:
   - Consumes C06 postings with honest unknown values (e.g. `compensation is None` or `workplace_type == UNKNOWN`) without premature eligibility pre-filtering.
3. **RUN-01 (Pipeline CLI & Orchestration)**:
   - Consumes `NormalizationResult` to route valid postings to identity/assessment while routing failed records to `QuarantineHandoff` storage.
4. **DATA-01 (Persistence & Ledger)**:
   - Retains raw capture references, hashes, and quarantine envelopes for auditing and reprocessing.

