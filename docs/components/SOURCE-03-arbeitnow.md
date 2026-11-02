# Component Handoff: SOURCE-03-arbeitnow — Arbeitnow API Adapter

Component ID: **SOURCE-03-arbeitnow**  
Status: **IMPLEMENTED** (Unit, contract, auxiliary, and Windows conformance verified; live external API verification pending sandbox network access)  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Prerequisite Handoffs: [docs/components/FND-01.md](FND-01.md), [docs/components/SOURCE-01.md](SOURCE-01.md), [docs/components/SOURCE-02.md](SOURCE-02.md)  
Planning Reference: [docs/stories/SOURCE-03-arbeitnow.md](../stories/SOURCE-03-arbeitnow.md)  
Date Completed: 28 October 2026  
Direct Covered Requirements: [R02](../../IMPLEMENTATION_BLUEPRINT.md#r02) (permitted acquisition, honest coverage), [R03](../../IMPLEMENTATION_BLUEPRINT.md#r03) (preserved raw input, source-field mapping without normalization). Supporting: [R04](../../IMPLEMENTATION_BLUEPRINT.md#r04) (scoped source identity), [R09](../../IMPLEMENTATION_BLUEPRINT.md#r09) (raw capture handoff), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14) (native Windows conventions), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15) (untrusted HTML/text as inert data, safe error logging without credential leakage), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16) (bounded execution, isolated failures, explicit classified errors).

---

## 1. Prerequisites and Upstream Dependencies Verification

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **C03 SourceConfig Contract** | FND-01 | **VERIFIED** | Reused directly. `provider="arbeitnow"`, `board_id="default"`, `acquisition_method=AcquisitionMethod.API`, `inventory_semantics=InventorySemantics.FILTERED_FEED`. `complete_board` is explicitly rejected. |
| **C05 RawPosting & SourceJobDraft** | FND-01 | **VERIFIED** | Reused directly with unchanged wire schemas. Exact byte hash, derived record envelope (`arbeitnow-env-v1`), and scoped `SourceKey` preserved. |
| **Adapter Protocol Boundary** | SOURCE-02 | **VERIFIED** | Implements `fetch_page(config, continuation=None) -> AdapterPage` and `draft_posting(raw) -> DraftResult`. Protocol conformance verified via `isinstance(adapter, Adapter)` and shared consumer test harness. |
| **Checked Selection & EffectiveSource** | SOURCE-01 | **VERIFIED** | Consumes checked `EffectiveSource` instances from `SourceRegistryService`. Verified that disabled, unreviewed, or method-mismatched sources fail at binding before any I/O occurs. |

---

## 2. Official API Evidence and Terms Review

Official sources were reviewed on 28 October 2026 UTC:

| Ref | Source | URL / Evidence | Findings & Operational Limits |
|---|---|---|---|
| **E1** | Arbeitnow Blog Announcement | [https://www.arbeitnow.com/blog/job-board-api](https://www.arbeitnow.com/blog/job-board-api) | Public, free API without API keys; GET method; describes `remote` and `visa_sponsorship` query parameters. |
| **E2** | Arbeitnow Postman Collection | [https://documenter.getpostman.com/view/18545278/UVJbJdKh](https://documenter.getpostman.com/view/18545278/UVJbJdKh) | Documented JSON response shape: root `{data, links, meta}`; jobs carry `slug`, `company_name`, `title`, `description` (HTML), `remote` (bool), `url`, `tags`, `job_types`, `location`, `created_at` (int). |
| **E3** | Arbeitnow Terms of Service | [https://www.arbeitnow.com/terms](https://www.arbeitnow.com/terms) | **§11 (API Use):** users agree to provide a link back to Arbeitnow.com on their platform; access provided on an as-available basis and may be revoked. **§2:** limits copying/mirroring of website material. Persistent retention and Salesforce transfer scope (U07) remain under review before large-scale automated ingest. |

---

## 3. Architecture and Contract Decisions

### 3.1 Identifiers, Scoping, and Allowlist
- **Source identifier:** `provider="arbeitnow"`, `board_id="default"`, `source_key="arbeitnow_de"`.
- **Adapter identifier:** `ADAPTER_NAME = "arbeitnow-v1"`.
- **Continuation:** `kind="page"`, `value=str(page_number)`. Strictly forward integer progression required.
- **Strict URL allowlist:** Scheme must be `https`; host must be `arbeitnow.com` or `www.arbeitnow.com`; port 443; exact path `/api/job-board-api`; query parameters allowlisted to `page` only.
- **Redirects:** Maximum 2 hops; each target is validated against the allowlist before following. Off-host redirects are rejected immediately without requesting the destination.
- **Body cap:** 10 MiB upper bound per response to protect local hardware memory limits.

### 3.2 Raw Capture and Envelope (`arbeitnow-env-v1`)
1. Raw response body is captured in `RawCaptureSink` **before** JSON parsing or size checks.
2. For each identified job record, a provider-owned derived envelope is generated:
   ```json
   {
     "envelope_version": "arbeitnow-env-v1",
     "record": { ...original job object... },
     "capture": {
       "parent_ref": "...",
       "parent_hash": "...",
       "record_index": 1,
       "mapping_id": "arbeitnow-map-v1",
       "attribution": {
         "notice": "Source: Arbeitnow",
         "link": "https://www.arbeitnow.com"
       }
     }
   }
   ```
3. The envelope is captured through the sink to obtain `raw_payload_ref` and `raw_content_hash`. It links back to the original response bytes without falsely claiming to be an exact substring of the raw response.

### 3.3 Source Identity and Fallback
- **Primary identity:** Exact provider `slug` string (e.g. `kueche-und-co-sachbearbeiter-0007`). Numeric suffixes are preserved; leading zeros are not stripped (`"0007"` ≠ `"7"`).
- **Conservative fallback:** If `slug` is absent, blank, or null, fallback to `url-v1:sha256:<hex64>` over exact UTF-8 bytes of the validated `url`.
- **Precedence:** When `slug` is present, it takes precedence. When neither slug nor URL is available, a `RecordIssue` with `code="missing_posting_identity"` is recorded and the invalid record is skipped while preserving valid neighbours.
- Duplicate slug sightings on repeated or within-page fetches are preserved as distinct `RawPosting` records with different content hashes; deduplication is deferred to `IDENTITY-01`.

### 3.4 Source-to-C05 Field Mapping Matrix

Mapping ID: `arbeitnow-map-v1`. Extracts source structure into candidate fields without premature normalization:

| Provider field | Type in JSON | C05 Draft Destination | Mapping & Validation Behaviour |
|---|---|---|---|
| `slug` | `str` | `source_key.source_posting_id` | Exact string preserved. Wrong type → blocking issue. Absent/blank → URL fallback. |
| `company_name` | `str` | `company_name_hint` | Trimmed string. Null/absent → `None` with warning. Wrong type → blocking issue. |
| `title` | `str` | `title` | Trimmed string. Null/absent → `None` with warning (SOURCE-02 convention). Wrong type → blocking issue. |
| `description` | `str` (HTML) | `description` | Raw HTML preserved as inert text. Null/empty string → blocking `missing_posting_text` error (preserves raw record for inspection). |
| `url` | `str` | `source_url` | Validated HTTP(S) URL. Null/absent/wrong type → blocking `missing_source_url` error. |
| *(None)* | — | `application_url` | Set to `None`. No direct ATS application link inferred. |
| `location` | `str` | `locations_raw` | Raw unparsed location string preserved. Null/absent → `None`. |
| `remote` | `bool` | `workplace_type_raw` | Preserved as exact boolean `True` or `False`. Null/absent → `None`. Non-boolean → blocking issue. |
| `job_types` | `list[str]` | `employment_type_raw` | Preserved as list of strings. Empty list `[]` preserved as known empty. Null/absent → `None`. Wrong container/item type → blocking issue. |
| `tags` | `list[str]` | `original_fields["tags"]` | Preserved in original dictionary only. No skill or proficiency extraction in this adapter. |
| `created_at` | `int` | `original_fields["created_at"]` | Preserved in original dictionary only. `source_published_raw=None` per U05 decision (event semantics unresolved). Non-integer/bool/float/string → blocking issue. |
| *(None)* | — | `compensation_raw` | Set to `None`. No fabricated salary. |
| *(None)* | — | `source_deadline_raw` | Set to `None`. No fabricated expiry dates. |
| *(None)* | — | `attribution` | Propagated in `source_mapped_fields["attribution"]`: `{"notice": "Source: Arbeitnow", "link": "https://www.arbeitnow.com"}`. |

---

## 4. Uncertainties and Downstream Ownership (U01–U09)

| ID | Description | Resolution in SOURCE-03 / Downstream Owner |
|---|---|---|
| **U01** | Feed schema evolution / undocumented fields | Known fields strictly type-checked; unknown fields preserved in `original_fields` without extraction. Downstream: `INGEST-02`. |
| **U02** | Live terminal pagination behavior | Synthetic tests cover `links.next=null` (terminal) and empty data with next. Traversal stops on null next. Downstream: `INGEST-01`. |
| **U03** | Live rate limits and quota windows | Conservative 60s request spacing in example configuration. 429 parses `Retry-After`. Single attempt per call; bounded retries owned by `INGEST-01`. |
| **U04** | Slug recycling and permanence | Exact slug identity preserved without deduplication. Canonical resolution and merge lineage owned by `IDENTITY-01`. |
| **U05** | `created_at` timestamp meaning | Preserved as raw integer in `original_fields`; `source_published_raw=None`. Conversion to publication date deferred to `INGEST-02` pending documented evidence. |
| **U06** | Completeness and deletion tracking | Classified as `filtered_feed`. Adapter rejects `complete_board`. Disappearance cannot prove vacancy closure. Downstream: `IDENTITY-02`. |
| **U07** | Copying/retention scope under E3 §2/§11 | Attribution metadata propagated with all drafts. Durable storage and Salesforce transfer policy to be resolved before large-scale automated ingestion. Downstream: `SFCLIENT-01`, `OPS-01`. |
| **U08** | Durable sink integration | Adapter requires injected `RawCaptureSink`. In-memory sink used for unit tests; filesystem sink used for Windows tests. Durable SQLite/filestore capture owned by `INGEST-01` / `DATA-01`. |
| **U09** | C05 shared attribution representation | Attribution stored in `source_mapped_fields["attribution"]` and derived envelope metadata without modifying shared C05 wire schema. |

---

## 5. Files Created and Modified

### Source Code (`src/job_automation/sources/adapters/`)
- [`src/job_automation/sources/adapters/arbeitnow.py`](../../src/job_automation/sources/adapters/arbeitnow.py): Complete implementation of `ArbeitnowAdapter`, `HttpTransport` Protocol, `ClockProtocol`, URL validation, redirect handling, envelope serialization, and field mapping.
- [`src/job_automation/sources/adapters/__init__.py`](../../src/job_automation/sources/adapters/__init__.py): Exported `ArbeitnowAdapter`.

### Configuration (`config/`)
- [`config/sources.arbeitnow.example.json`](../../config/sources.arbeitnow.example.json): Non-secret C03 example with `enabled=false`, reviewed endpoint, structured access review (`E3-arbeitnow-terms-section-11`), required attribution, and `filtered_feed` semantics.

### Fixtures (`tests/fixtures/sources/arbeitnow/`)
- [`tests/fixtures/sources/arbeitnow/README.md`](../../tests/fixtures/sources/arbeitnow/README.md): Fixture catalog documenting evidence bases and expected test coverage.
- `page_1.json`: First page with 2 jobs and `links.next` to page 2.
- `page_2.json`: Second page with 1 job and `links.next` to page 3.
- `page_terminal.json`: Terminal page with 1 job and `links.next=null`.
- `empty_terminal.json`: Empty data array with `links.next=null`.
- `empty_with_next.json`: Empty data array with valid `links.next` URL.
- `missing_fields.json`: Records with missing descriptions, missing titles, missing slugs, and missing URLs.
- `wrong_types.json`: Records with invalid field types (integer slug, string remote, etc.).
- `unknown_fields.json`: Records with forward-compatible future fields (`salary_min`, `visa_sponsorship`, etc.).
- `bad_envelope.json`: Invalid envelope missing the `data` key.
- `duplicate_slug.json`: Records sharing the identical slug to verify duplicate handling.
- `timestamps.json`: Records with integer, null, large, and invalid string/bool timestamps.

### Test Suites (`tests/sources/` and `tests/manual/`)
- [`tests/sources/arbeitnow_helpers.py`](../../tests/sources/arbeitnow_helpers.py): Shared test harness, `FakeTransport`, `FakeClock`, `FailOnNetworkTransport`, and `build_arbeitnow_source()` builder.
- [`tests/sources/test_arbeitnow_access.py`](../../tests/sources/test_arbeitnow_access.py): Binding, access review status, and configuration validation tests (10 tests).
- [`tests/sources/test_arbeitnow_http.py`](../../tests/sources/test_arbeitnow_http.py): Status classification (401, 403, 404, 429, 500, 304), timeout/connection errors, body capacity limits, redirect safety, and capture failures (19 tests).
- [`tests/sources/test_arbeitnow_pagination.py`](../../tests/sources/test_arbeitnow_pagination.py): Forward pagination, terminal detection, continuation encoding/decoding, and loop protection (15 tests).
- [`tests/sources/test_arbeitnow_identity.py`](../../tests/sources/test_arbeitnow_identity.py): Exact slug preservation, case/leading zeros, URL fallback, and record isolation (6 tests).
- [`tests/sources/test_arbeitnow_mapping.py`](../../tests/sources/test_arbeitnow_mapping.py): C05 draft mapping, boolean remote preservation, job types list handling, timestamp preservation, HTML preservation, and serialization roundtrips (15 tests).
- [`tests/sources/test_arbeitnow_conformance.py`](../../tests/sources/test_arbeitnow_conformance.py): Adapter protocol conformance, 3-page traversal, mid-stream failure recovery, and Pydantic model compliance (5 tests).
- [`tests/sources/test_adapter_conformance.py`](../../tests/sources/test_adapter_conformance.py): Added `build_arbeitnow_conformance_adapter` to the shared multi-adapter conformance parametrization (4 passed).
- [`tests/sources/test_arbeitnow_windows.py`](../../tests/sources/test_arbeitnow_windows.py): Native Windows paths with spaces and umlauts (`ä, ö, ü, ß`), file handle release, aware Berlin timezone conversion to UTC, and working-directory independence (4 tests).
- [`tests/manual/arbeitnow_smoke.py`](../../tests/manual/arbeitnow_smoke.py): Standalone opt-in live smoke CLI helper with strict 2-page cap and explicit attribution reporting.

---

## 6. Verification Results

### 6.1 Unit, Contract, and Conformance Test Suite
Executed using native Windows Python interpreter (`.venv\Scripts\python.exe`):
```text
Platform: Windows-11-10.0.26300-SP0
Python: 3.12.10 (AMD64)
Pytest: 8.4.2
Pydantic: 2.14.1
Tzdata: 2026.5
Result: 416 passed in 7.78s (0 failures, 0 warnings)
```
- Upstream regression baseline: 341 passed (SOURCE-02 handoff)
- New tests added: 75 tests covering Arbeitnow access, HTTP transport, pagination, identity, field mapping, Windows paths/handles, and conformance.
- Total test count: **416 passed**.

### 6.2 Native Windows Verification Recipe
The official verification recipe from `docs/stories/SOURCE-03-arbeitnow.md` was executed in native PowerShell:
1. Environment check (platform, Python 3.12.10, ZoneInfo `Europe/Berlin`): **PASSED**
2. Package check (`pydantic 2.14.1`, `pytest 8.4.2`, `tzdata 2026.5`): **PASSED**
3. Contract and source tests (261 tests): **PASSED**
4. Windows Unicode & CWD test in temporary directory `Job Automation Prüfung ä SOURCE-03 ...` with `--basetemp "Test Data Größe"`: **PASSED**
5. Full regression suite (416 tests): **PASSED**

### 6.3 Live Smoke Verification Status
- **Harness:** `tests/manual/arbeitnow_smoke.py`
- **Default check:** Verified that passing `config/sources.arbeitnow.example.json` (disabled) cleanly blocks execution and outputs `Live verification marked PENDING (no enabled local configuration)`.
- **Live network check:** Executed in sandboxed mode; outbound socket connection to `www.arbeitnow.com` was intercepted and safely classified as `transient_network: Connection error: URLError` without credential leakage or crash.
- **Status:** **LIVE VERIFICATION PENDING** (live network access to `arbeitnow.com` is required outside sandbox isolation to perform the 1-page smoke fetch).

---

## 7. Downstream Consumer Handoff Notes

1. **For INGEST-01 (Fetch Controller):**
   - Use `adapter.fetch_page(source_config, continuation=token)`.
   - Treat `exhausted=True` as end of available feed for that run.
   - Enforce bounded retries for `page_error` with `recoverable=True` (e.g. 429, 5xx, timeouts).
   - Use `Continuation.encode()` / `Continuation.decode()` for persistent cursor storage in C04 manifests.

2. **For INGEST-02 (Common Normalizer):**
   - Input is `SourceJobDraft` with `mapping_version="arbeitnow-map-v1"`.
   - `workplace_type_raw` contains exact boolean `True` (remote) or `False` (non-remote) or `None` (unspecified). Normalize to `WorkplaceType.REMOTE` vs `UNKNOWN` (do not assume onsite).
   - `employment_type_raw` contains a list of raw string labels (e.g. `["Vollzeit"]`).
   - `source_published_raw` is currently `None`. If epoch seconds from `created_at` are approved for publication timestamp conversion, document the rule and test for UTC awareness.
   - `description` contains raw HTML; strip and clean tags during normalization to produce `description_clean`.

3. **For IDENTITY-01 (Canonical Identity & Lineage):**
   - Source postings are identified by `SourceKey(provider="arbeitnow", board_id="default", source_posting_id=slug)`.
   - Fallback IDs use `url-v1:sha256:<hex64>`.
   - Multiple postings with the same `source_key` across runs represent revisions/sightings; compare `raw_content_hash` and normalized hashes to track changes.

