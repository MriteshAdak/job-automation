# SOURCE-02 — Adapter interface and manual import

Status: **VERIFIED** · Planning date: 28 October 2026 · Completed: 28 October 2026 · Component: **SOURCE-02 only** · Phase 0

Baseline: [IMPLEMENTATION_BLUEPRINT.md][blueprint], v1.0. References below use its requirement register (§2), contracts (§4), correctness rules (§5), component boundaries (§6), integration gates (§7), handoff instructions (§8), and Windows conventions (§9). This document contains ordered implementation stories; it does not implement them.

## Evidence, dependency status, and scope

Read the blueprint, [README](../../README.md), [FND-01 handoff][fnd], [SOURCE-01 stories][source01], relevant current contracts, configuration, CLI, schemas, fixtures, interface tests, and storage code. The [DATA-01 handoff][data] is a persistence coordination reference. No applicable `AGENTS.md` was found in the repository or its ancestors; the user-level `.codex/AGENTS.md` is empty. README and blueprint §§8–9 supply repository instructions.

| Evidence | Current state and consequence |
|---|---|
| FND-01 | Handoff reports VERIFIED, Python 3.12.10 on native Windows, and contract schema 1.0. Its historical checks are not SOURCE-02 verification. Current `pyproject.toml` uses dependency ranges; do not describe these as exact pins. |
| SOURCE-01 | Only `docs/stories/SOURCE-01.md` is available, marked PLANNED. There is no `docs/components/SOURCE-01.md` or implemented `sources/` package. Its proposed checked selection, scope, manual-origin and request-policy APIs are dependencies to reconcile, not available code. |
| [Adapter protocol][interfaces] | `fetch_page(config, cursor=None)` returns `tuple[list[RawPosting], str | None, FetchOutcome]`; `draft_posting(raw)` returns `SourceJobDraft`. There is no typed page metadata, record-error result, input binding, or continuation validation. |
| [Foundation fake](../../tests/fakes/fake_services.py) and [interface tests](../../tests/contracts/test_interfaces.py) | `FakeAdapter` always returns the same list, `"cursor_next"`, and `COMPLETE`; its draft invents `"Draft Title"`. Existing tests assert that behavior. This verifies basic shape, not real pagination, source mapping, or exhaustion. Replace those assumptions explicitly. |
| [C03](../../src/job_automation/contracts/sources.py) | Configuration key is a string; provider/board identify the configured origin. `base_url` is currently required even for manual sources. SOURCE-01 D06 owns that mismatch; SOURCE-02 must not invent an HTTP endpoint. |
| [C04/C05][postings] | C04 is a run/scope manifest. C05 `RawPosting` requires a real payload reference, byte hash, scoped `SourceKey`, fetch time and text; `SourceJobDraft` carries reference, identity, time, original dictionary and mapped dictionary. It has no dedicated mapping-version, record-locator or field-provenance member. |
| [Primitives](../../src/job_automation/contracts/primitives.py) | `SourceKey` is `(provider, board_id, source_posting_id)`, distinct from the C03 configuration key. `ContentHash` is `sha256:` plus 64 lowercase hexadecimal characters. IDs remain opaque strings. |
| Contract validation | `extra="forbid"`, but `schema_version` is an unrestricted string and nested dictionaries remain mutable. `UtcDatetime` requires timezone awareness; its annotation alone does not enforce offset zero. Source-boundary version checks, detached data and UTC production need explicit verification. |
| [Raw repository](../../src/job_automation/storage/repositories/raw_postings.py) | Inserts one row per source tuple and raises `DuplicateKeyError` on repeats; it is not an import revision/upsert service. No SOURCE-02 story should silently replace rows or claim durable rerun idempotency. |
| [Filestore](../../src/job_automation/storage/filestore.py) | Can save bytes and hash them, but uses a mutable posting-derived filename and decodes reads with replacement. That is insufficient evidence of immutable, exact-byte import snapshots. Do not change storage semantics incidentally in this component. |
| Application surface | CLI has config/storage/profile/policy commands, no import command. App paths use an absolute data root outside the repository. No production fetch controller or normalizer is present. |

**Direct requirements:** R02 (permitted acquisition, manual imports, honest coverage) and R03 (preserved raw input and source mapping). Supporting constraints: R14 (native Windows), R15 (untrusted text and safe diagnostics), R16 (explicit failures and continuation evidence). R04 is referenced only for source identity; SOURCE-02 does not resolve canonical jobs.

**Catalog dependencies:** FND-01 and SOURCE-01. Tests may inject a clearly labelled checked-selection fake while SOURCE-01 is unavailable. Do not implement its registry, access review, inventory hashing, or enablement rules here. Actual SOURCE-01 integration remains pending until its handoff and public API exist. DATA-01 is a coordination boundary, not a new catalog prerequisite.

**In scope:** one shared adapter interface, page/continuation and mapping-result representations, C05 raw/mapped outputs, local URL-plus-text and CSV adapters, record-level errors, a reusable conformance suite with a test-only paginated adapter, native Windows evidence, and a component handoff.

**Outside scope:** real provider adapters or scraping; HTTP/DNS/HEAD requests for imported URLs; redirects, previews or metadata enrichment; retry/backoff execution; production multi-page orchestration or C04 creation; storage migrations and revision persistence; C06 normalization/quarantine; C07 identity/availability; matching, models, Salesforce, scheduling and application submission. No real employer/source permissions are inferred. The import API is usable independently; a pipeline import CLI and durable run integration belong to INGEST-01/RUN-01. Do not add a separate command framework to verify this component.

## Contract and behavior decisions to establish first

The following are **proposed technical choices**, not additional user requirements. S01 must settle names, signatures, supported versions and compatibility before later stories implement them. Existing blueprint invariants and the user's prohibition on URL fetching are mandatory.

### Shared boundary

Prefer a typed page/result extension of the foundation boundary rather than parallel provider-specific APIs:

| Representation | Required information and semantics |
|---|---|
| Adapter binding | Checked SOURCE-01 selection, exact C03/scope snapshot, supported method/provider, immutable manual input descriptor when relevant, injected clock and payload capture capability. Binding uses explicit application registrations, never a module name or code supplied in CSV/configuration. |
| `Continuation` | Version, kind (`cursor`, `page`, `offset`, or local-record position), opaque value, source configuration key, scope ID, adapter/version binding; manual tokens also bind input hash and parsing options. No credentials. This is traversal state, not job identity. |
| `AdapterPage` | Version, ordered C05 raw records, ordered record issues, raw response/input references, input/output continuation, explicit exhaustion/truncation facts, and optional classified page failure. Include safe counts with defined units. A page is not a C04 manifest. |
| `RecordIssue` | Version, input reference/hash, logical record index and available physical line/span, optional source tuple, field path, stable code, severity, safe message and classified category. It must work before a valid C05/source identity exists. |
| `DraftResult` | Either a C05 draft with warnings or no draft with one or more blocking issues; retain the raw reference in both cases. A mapper cannot return an apparently successful draft with unresolved blocking errors. |
| Raw capture/reference capability | Caller supplies a boundary that retains exact bytes and returns a resolvable immutable reference and matching hash. Adapters do not fabricate filenames. An explicit in-memory implementation is test-only; durable capture is owned by INGEST-01/DATA-01. |

The intended public operations remain **one page acquisition** and **one raw-record mapping**. Proposed signatures are `fetch_page(config, continuation=None) -> AdapterPage` and `draft_posting(raw) -> DraftResult`, with checked selection/input/capture dependencies bound at construction. Validate that passed config matches that binding. Both manual adapters and the fake implement exactly these operations; callers must not branch on adapter class to obtain errors or continue traversal.

This changes the existing tuple and direct-draft return shapes. S01 must record an explicit interface revision and consumer migration, update the foundation fake/tests, and record the blueprint decision required for incompatible changes. Do not silently reinterpret `FetchOutcome.COMPLETE` or claim the signature is backward compatible. C03/C04/C05 wire versions need not change merely because the Python interface changes. Any necessary C05 additions have their own compatibility decision, generated schemas and fixtures. Do not create a new numbered C-contract for every auxiliary result.

### Pagination and coverage invariants

| Page situation | Required representation | Future controller consequence, not implemented here |
|---|---|---|
| Valid page with more data | Next continuation, `exhausted=false`, no page failure | Continue within controller budgets; no complete inventory claim |
| Empty page with valid next token | Zero records, next continuation, `exhausted=false` | Empty does not imply end |
| Successful terminal page, including empty | No next token, `exhausted=true`, no truncation/failure | Eligible for successful traversal only if all previous pages succeeded |
| Cap/truncation | Explicit reason, `exhausted=false`; next token if meaningful | Partial traversal even when no continuation is available |
| Operational failure | Classified error and no false exhaustion; retain already captured records/references if any | Retry only via INGEST-01 policy; preserve prior success and report partial/failed |
| Local CSV EOF with bad records | `exhausted=true` describes EOF; record issues and rejected count remain visible | Exhaustion does not mean every row imported successfully |

Pagination metadata must represent page numbers, offsets, cursors and next-link tokens without forcing INGEST-01 to parse provider content. A next URL is opaque adapter data, not arbitrary fetch authority. Future SOURCE-03 validates any next-link target against its checked source restrictions. SOURCE-02 never follows it. Scope identity comes from SOURCE-01, not from the cursor. Tokens cannot be replayed against a changed board, input, dialect or scope. Serialization must be deterministic and reversible if tokens are persisted; opaque secrets must not be logged.

C04 remains owned by INGEST-01. Document a lossless bridge to its current string `cursor_in`/`cursor_out` (versioned serialization or a coordinated C04 change); do not drop continuation kind/binding. Neither complete file reading nor a successful search grants complete-board semantics. Manual subsets never support disappearance inference. Record rejection and transport failure remain separate facts even when the controller later summarizes both.

### Raw data, identity, and mapping invariants

- Retain the exact original input bytes before parsing, including BOM, CSV quoting and line endings. Hash bytes, not a normalized/re-encoded approximation. For pasted text with no original byte stream, define UTF-8 encoding as the capture boundary. Capturing a batch file and locating a row is different from claiming reserialized row JSON is the original file.
- Preserve invalid/unidentified records through input-level references and locators. C05 requires a nonempty `SourceKey`; a bad row without an ID/usable URL must produce `RecordIssue`, not an invented posting ID to satisfy Pydantic.
- Prefer an explicitly supplied source posting ID. Otherwise use a documented conservative URL fallback scoped to the configured manual provider/board. Proposed baseline is a namespaced digest of the exact validated URL string; it is a URL identity fallback, not a description/content hash. Preserve the original URL. Do not lowercase paths, drop queries/fragments, follow redirects, or merge URL variants without an owning identity decision. Reject padded/invalid input rather than silently rewriting it. Document possible false negatives.
- Explicit IDs such as `"0007"` retain zeros and case. Changing text/title at the same ID/URL preserves source identity; changing board changes identity. A row number is a locator, never a durable posting ID. Duplicate source identities in a batch stay visible and ordered; no last-row-wins behavior or canonical deduplication occurs here.
- Keep `RawPosting.raw_payload` consistent with the captured record representation; document encoding and any derived record envelope. Preserve the parent file reference/hash and locator in an auxiliary provenance record or explicit compatible C05 addition. A derived envelope must be labelled derived and traceable to exact source bytes. Its hash must match its own reference, not the entire CSV by accident.
- `SourceJobDraft.raw_reference`, `source_key` and `fetch_time` match the raw input. `original_fields` retains original keys, extra columns and supplied values; `source_mapped_fields` uses a documented vocabulary and source-field paths. Carry mapping version and provenance through the agreed boundary, not undocumented reserved keys in user data.
- Extract structure only. Preserve HTML/text, location wording, remote restrictions, raw salary/currency/period, language labels and stated date precision. No HTML cleanup, inferred company/title, salary annualization, date completion, timezone guessing, employer merging, job scoring or C06 production. Missing fields remain absent/null under documented rules; blank is not zero/false. The literal text `"null"` is not automatically JSON null.
- Missing title/company may still yield C05 with a visible missing-field warning; INGEST-02 owns required normalized-field validation. Missing identity, unusable import text, malformed row structure and unsupported field types are import/mapping errors. Never extract a title from the first description line as a substitute.
- Text, CSV cells, URLs and metadata are untrusted data. No shell, expression evaluation, macros, formula execution, local-file URL opening, browser navigation, LLM calls, or dynamic imports. Ordinary diagnostic reports never echo descriptions, raw rows, credential-bearing URLs, tokens or arbitrary exceptions.

## Ordered stories

Every story below is **PLANNED**, belongs only to SOURCE-02, and lists proposed future owned files. Only this story document is created by this planning task.

| Order | Story | Deliverable | Dependencies within SOURCE-02 |
|---|---|---|---|
| 1 | [SOURCE-02-S01](#source-02-s01) | Interface, result/provenance contracts and compatibility specification | None |
| 2 | [SOURCE-02-S02](#source-02-s02) | Checked binding and continuation behavior | S01 |
| 3 | [SOURCE-02-S03](#source-02-s03) | Raw capture boundary, source identity and C05 mapping conventions | S01–S02 |
| 4 | [SOURCE-02-S04](#source-02-s04) | Manual URL-plus-text adapter | S01–S03 |
| 5 | [SOURCE-02-S05](#source-02-s05) | Manual CSV adapter | S01–S04 |
| 6 | [SOURCE-02-S06](#source-02-s06) | Record-level error isolation and import report API | S03–S05 |
| 7 | [SOURCE-02-S07](#source-02-s07) | Fake paginated adapter and shared conformance verification | S01–S06 |
| 8 | [SOURCE-02-S08](#source-02-s08) | Native Windows, compatibility checks and component handoff | S01–S07 |

### SOURCE-02-S01

**Objective/references.** Settle the shared interface before manual parsing. R02/R03; supporting R14/R15/R16. Blueprint §§4/C03–C05 and adapter/error boundaries, 6/SOURCE-02, 8. FND-01-S04/S07; SOURCE-01-S01/S05/S06 and decisions D01/D05–D08.

**Dependencies.** FND-01 implemented contracts; SOURCE-01 planned checked-selection/scope boundary. Reinspect its handoff if it becomes available. Missing SOURCE-01 does not authorize implementing its registry.

**Owned files.** Adapter portion of `src/job_automation/contracts/interfaces.py`; proposed `contracts/adapter_results.py`; explicit exports and schema exporter/affected schemas and fixtures; `tests/contracts/test_adapter_results.py`; affected `tests/contracts/test_interfaces.py` and adapter portion of `tests/fakes/fake_services.py`; initial `docs/components/SOURCE-02.md`. Coordinate shared ownership with FND-01. Do not edit unrelated service protocols.

**Inputs → outputs.** Existing C03–C05 and foundation signatures → exact versioned page, continuation, draft-result, record-issue and raw-provenance representations; public signatures and compatibility notes.

**Tasks.**

1. Resolve the proposed boundary above, including invariants, supported schema versions, source/scope binding, per-record versus page failure and optional metadata. Choose where auxiliary models live and how they are exported.
2. Define valid result combinations: no draft plus blocking issue; draft plus warnings; no fabricated successful empty result on failure. Specify what can survive a partial page failure.
3. Decide the exact raw-reference/parent-locator representation and mapping vocabulary. If C05 needs additive fields, record a version and reader compatibility matrix; old `extra="forbid"` readers will reject them. Avoid treating arbitrary dictionaries as a substitute for an agreed contract.
4. Record the interface revision, all known callers/fakes/tests to update, and a C04 continuation serialization bridge. Update the blueprint decision if taking the incompatible return-shape proposal. Do not mutate historical manifests.
5. Validate semantic versions at the service boundary, UTC timestamps, detached nested data and safe structured errors. Generate changed schemas from models; do not hand-edit them.

**Acceptance examples.** A serialized page with two raw records and one unidentified-row issue round-trips without losing order/locator. An exhausted page with a next token is rejected as contradictory. A terminal CSV page with a row error is representable. An unknown wire version fails explicitly. Old C05 fixtures remain readable under the documented compatibility path.

**Tests.** Positive/negative result combinations, version matrix, JSON round trips, UTC production, nested mutation isolation, generated schema parity, and changed foundation interface tests. Runtime `isinstance(..., Adapter)` alone is not signature/behavior verification.

**Native Windows.** Run contract tests with explicit `.venv\Scripts\python.exe`; include non-ASCII text in round trips.

**Migration/configuration and handoff.** No database migration. Record precise interface/auxiliary/C05 versions separately, required consumer changes and closure of D01–D03/D05 below. Do not claim SOURCE-01 integration until its actual API is tested.

### SOURCE-02-S02

**Objective/references.** Bind adapters to checked sources and make traversal state explicit. R02; supporting R15/R16 and source-identity constraint R04. Blueprint §§4/C03–C05, 5, 6/SOURCE-01/02/INGEST-01. SOURCE-01-S05/S06.

**Dependencies.** S01; actual checked SOURCE-01 selection or a labelled test-only substitute.

**Owned files.** Proposed `src/job_automation/sources/adapters/__init__.py`, `binding.py`, `continuation.py`; `tests/sources/test_adapter_binding.py`, `test_continuation.py`; synthetic selection/token fixtures. Keep SOURCE-01's registry models/service owned there.

**Inputs → outputs.** Checked source snapshot, registered adapter capability and optional continuation → one bound page request or a safe configuration/validation error. No traversal loop or network call is introduced.

**Tasks.**

1. Provide explicit adapter registration/binding and reject unavailable capabilities. Manual adapters accept only their declared method/input format. Never fall back from unsupported API acquisition to scraping or manual mode.
2. Require checked enabled/selected source metadata and preserve attribution/request restrictions/scope unchanged. No public convenience import route may bypass the same gate. Selection itself stays SOURCE-01's responsibility.
3. Implement deterministic continuation serialization/validation. Preserve opaque cursors, string IDs and numeric zero where meaningful; distinguish initial `None` from terminal response metadata. Validate page/offset bounds by declared kind.
4. Bind tokens to source/scope/adapter and local input fingerprint/options. Expose enough information for future controllers to detect cycles. Detect immediate non-progress when it is locally knowable; longer cycles and traversal budgets remain controller responsibilities.
5. Document exhaustion, truncation and failure semantics from the table. Define errors for invalid/stale/wrong-input tokens and incompatible adapter versions. No retries, sleep, caching, persistence or C04 aggregation.

**Acceptance examples.** Offset `0` is valid. Token for board A fails on board B before reading input. An unchanged CSV can resume at record 3; changed CSV bytes or delimiter invalidate that token. Empty page plus next token remains nonterminal. An unregistered real-provider name returns missing configuration, with no network fallback.

**Tests.** Token round trips and malformed/negative/wrong-kind values; source/scope/version mismatch; changed snapshot/dialect; opaque next-link preservation; immediate non-progress; missing capability; blocked-source recorder never invoked. Use checked-selection fakes only in tests.

**Native Windows.** Run continuation tests in separate processes and with Unicode fixture metadata. Confirm URLs/tokens are never passed through filesystem separator replacement.

**Migration/configuration and handoff.** No registry format redesign. Publish registration keys, snapshot obligations and continuation version/bridge for SOURCE-03/INGEST-01. Resolve D02/D03; SOURCE-01 live boundary verification may remain pending.

### SOURCE-02-S03

**Objective/references.** Produce truthful, traceable C05 records without performing normalization. R03; supporting R02/R15/R16 and R04 source identity. Blueprint §§4/C05, 5 identity/raw-data rules, 6/SOURCE-02/INGEST-02.

**Dependencies.** S01–S02; DATA-01 code is a coordination reference for the injected capture interface, not permission to modify storage.

**Owned files.** Proposed `sources/adapters/raw.py`, `mapping.py`, `manual_identity.py`; `tests/sources/test_raw_provenance.py`, `test_source_mapping.py`, `test_manual_identity.py`; `tests/fakes/raw_capture.py`; C05 mapping/provenance fixtures and their README.

**Inputs → outputs.** Exact input bytes/text, source identity hints, record locator and injected capture/clock → C05 raw record plus mapping result, or a locator-bearing issue when C05 cannot exist.

**Tasks.**

1. Implement the S01 capture/reference protocol and verify returned hashes against bytes. Require a successful capture before returning a record as preserved. Capture failure is an operational error, not a malformed row or fabricated reference.
2. Specify separate parent-file and per-record representations. Preserve CSV byte/line boundaries without requiring a parser to recreate original quoting. Keep all source evidence resolvable through the agreed provenance link, including invalid rows and unmapped columns.
3. Implement explicit-ID preference and conservative URL fallback; retain method/version used. Do not use body hashes, title, company, row index or import run UUID as a posting identity. Keep raw-content hashes solely for snapshot/revision evidence.
4. Implement common mapping helpers with a documented candidate vocabulary, e.g. `title`, `company_name_hint`, `description`, `source_url`, `application_url`, `locations_raw`, `compensation_raw`, `source_published_raw`. Exact keys and provenance paths must be frozen in S01 for INGEST-02. Preserve values/types rather than coercing normalized fields.
5. Emit UTC observation/import times from an injected clock; retain separately any source-declared dates. Verify raw/draft reference, source tuple and time agreement. Copy nested source data so later mutation cannot alter accepted results.
6. Keep duplicate raw observations visible. Record the current DATA-01 duplicate-row/mutable-filename limitations as pending durable integration; do not add upsert/revision/file-retention code here.

**Acceptance examples.** ID `"0007"` survives; edited text changes raw hash without changing identity. The same ID in another board differs. A row with no ID or valid URL has an issue and parent reference, no C05. Salary `"60.000–70.000 EUR/Jahr"` and `"remote, nur Deutschland"` remain source strings. Missing title is not replaced with `"Draft Title"`. A supplied nonzero timestamp offset is converted to UTC for observation time, not silently attached to a source date.

**Tests.** Exact-byte hashes with BOM/CRLF/umlauts, parent/record hash distinction, capture failure, reference resolution, missing identity, edited body/stable ID, URL fallback variants, scoped ID collisions, duplicate observations, mapping omissions/null/empty/zero, metadata mutation and no normalization.

**Native Windows.** Capture fixtures through a test sink under a temporary path containing spaces/umlauts; verify bytes after reopen and release handles. Do not invoke the mutable production filestore as proof of immutable capture.

**Migration/configuration and handoff.** No database migration or durable snapshot implementation. Document capture obligations, URL identity version, mapped-field vocabulary, provenance and known storage integration gaps. Close D04/D05 before S04/S05 acceptance.

### SOURCE-02-S04

**Objective/references.** Import a user-supplied URL with local posting text through the shared adapter. R02/R03; supporting R14/R15. Blueprint §6/SOURCE-02 and §4/C05; explicit user constraint: never fetch imported URLs automatically.

**Dependencies.** S01–S03; SOURCE-01 manual-origin decision D06 and checked manual selection. Use a fixture if the registry is still unavailable, and label that limitation.

**Owned files.** Proposed `sources/adapters/manual_text.py`, manual input descriptors; `tests/sources/test_manual_text.py`; `tests/fixtures/sources/manual/text/` synthetic text and metadata fixtures.

**Inputs → outputs.** Checked manual C03, supplied source URL, text string or explicit local text path, optional posting ID and explicitly supplied title/company/application URL → one terminal C05 page and a C05 draft/mapping issues. Input reading does not perform durable run persistence.

**Tasks.**

1. Expose a documented callable import entry point/factory accepting exactly one text source. Resolve a relative local path against a required input base, never an implicit process working directory. Keep text content out of ordinary diagnostics.
2. Require nonblank supplied posting text and a syntactically valid HTTP(S) source URL for this mode. URL-only input yields `missing_posting_text`. No DNS, GET/HEAD, redirect resolution, link preview, browser opening or HTML asset loading.
3. Preserve text/HTML and supplied metadata; map only explicit fields. If title/company are not supplied, retain them as unknown with mapping warnings and leave normalized-field acceptance to INGEST-02.
4. Validate metadata field types and reject URL userinfo/unsupported schemes safely. Preserve admissible query text in protected provenance without logging it. Embedded links and instructions are inert text.
5. Use the same page/draft result interface as CSV and fake adapters. A single valid record is terminal; an import error is inspectable and never masquerades as a successful empty page.

**Acceptance examples.** `https://jobs.example.invalid/vacancies/0007` plus German HTML text produces C05 without attempting a connection. That URL alone yields a field-level issue. `file:`, `javascript:` and credential-bearing URLs are rejected without opening them. Text containing shell commands and an external image remains unchanged data. Missing title yields a draft with unknown title, not a guessed heading.

**Tests.** Valid plain text/HTML, whitespace-only input, invalid/missing URL, explicit metadata types, ID/fallback identity, unchanged source bytes, nonexistent/unreadable local file, conflicting inputs, no title inference and a fail-on-network guard. Test both text-string and local-file entry points.

**Native Windows.** Import a UTF-8 file named `Stellen Prüfung ä.txt` from a path with spaces using an explicit base and again from another working directory. Check CRLF preservation, strict decoding and handle closure.

**Migration/configuration and handoff.** No HTTP client, new dependency or CLI command required. Publish callable examples and configuration/input requirements; do not patch C03 `base_url` ad hoc. Close D06 input-path/encoding rules; record SOURCE-01 origin integration if pending.

### SOURCE-02-S05

**Objective/references.** Import local CSV postings with stable record locations and explicit source mapping. R02/R03; supporting R14/R15/R16. Blueprint §§4/C05, 6/SOURCE-02 and 9.

**Dependencies.** S01–S04; reuse mapping, identity, capture, error and binding behavior rather than building a separate CSV pipeline.

**Owned files.** Proposed `sources/adapters/manual_csv.py`, CSV input options; `tests/sources/test_manual_csv.py`, `test_csv_continuation.py`; `tests/fixtures/sources/manual/csv/` files and expected mapping/issue fixtures.

**Inputs → outputs.** Checked manual source, explicit local CSV path/bytes, base path and declared parsing/column options → bounded C05 pages, continuation, original-row provenance and record issues; each raw record maps through the same draft operation.

**Tasks.**

1. Use Python's standard CSV parser with correct newline handling. Proposed baseline: UTF-8/UTF-8 BOM, comma delimiter, double-quote escaping; explicit semicolon option for German exports. No heuristic delimiter/encoding guessing. Reject unsupported formats, including `.xlsx`, with `unsupported_input`.
2. Publish a small header/column contract: required `source_url` and `text`; optional `source_posting_id`, `title`, `company`, `application_url`, and declared raw location/pay/date fields. Required column presence differs from row-level field validity. Preserve extra columns in `original_fields`; report unmapped columns without silently discarding them. Explicit column mappings must be unique and unambiguous.
3. Validate the header before record mapping: duplicate/empty headings, missing required columns and conflicting mappings are file-level failures. Do not allow `DictReader` to silently overwrite duplicate headings or discard excess cells.
4. Give each logical data record a stable 1-based record index, excluding the header; record physical start/end lines for quoted multiline records. Define blank-line/empty-row behavior and counters. Preserve record order and source values including leading zeros and literal formula-like strings.
5. Page by a validated positive record-count option. Bind continuation to file hash, parsing/mapping version/options and next logical record. Avoid live mutable-file cursors; an input edit invalidates resumption. Resource limits must fail visibly rather than silently truncate or drop oversized records.
6. Isolate recoverable row problems: wrong cell count, missing/invalid URL or text, and invalid explicitly typed metadata. Continue at trustworthy record boundaries. An unterminated quoted field or undecodable byte sequence that destroys boundaries stops the remaining import, with last safe position and retained source reference; do not guess subsequent rows.

**Acceptance examples.** A three-row file with a bad URL on record 2 yields records 1 and 3 plus an issue locating record 2. A quoted description spanning lines 3–5 is one record with that span. UTF-8 BOM is accepted without altering the raw hash. A semicolon file requires an explicit semicolon dialect. Duplicate `text` headers fail before any draft is accepted. A changed file cannot resume an old token.

**Tests.** CRLF/LF, BOM/non-ASCII, commas/semicolons, escaped quotes, multiline fields, duplicate/missing/extra columns, blank rows, header-only and empty files, cell-count mismatch, literal `=...` content, invalid encoding, unterminated quotes, size limits, page-size boundaries and snapshot resumption. Header-only valid CSV is a successful empty traversal; a zero-byte file is a missing-header error.

**Native Windows.** Read `Stellen Übersicht.csv` from a spaced Unicode directory using `newline=""`/explicit encoding; reopen it after import to demonstrate handle release. Run tests from a different current directory with an explicit input base.

**Migration/configuration and handoff.** No database or C03 changes for CSV options: they belong to the manual input descriptor, not HTTP request policy. Record CSV dialect/header/null/blank-row rules and resource-limit units/defaults. Close D06/D07.

### SOURCE-02-S06

**Objective/references.** Make partial manual imports reviewable without losing valid records or leaking raw content. R02/R03; supporting R15/R16. Blueprint §§4 error taxonomy/C05, 6/SOURCE-02.

**Dependencies.** S03–S05 and S01 result contracts.

**Owned files.** Proposed `sources/adapters/import_report.py`, import diagnostics helpers; `tests/sources/test_import_errors.py`, `test_import_report.py`; expected safe report fixtures. Use the shared `ValidationIssue`/`ClassifiedError` taxonomy, not a competing category enum.

**Inputs → outputs.** Pages, draft results and original input references → deterministic safe report and programmatic accepted-record/error results. Report generation is pure; traversal/record persistence remains the caller's job.

**Tasks.**

1. Define counters: encountered logical records, accepted drafts, rejected records, warning records, total issues and unread remainder (known/unknown). Multiple issues on one row count as one rejected record. File/header errors are not fabricated row counts.
2. Preserve all record issues in input order with field path, code, severity, input locator/reference and optional source identity. Report complete scan with rejections separately from truncated/failed scan. `exhausted` never suppresses rejected counts.
3. Classify missing/invalid data as non-retryable validation or unsupported input; distinguish missing file/configuration, permissions and capacity failures. Use safe template messages and allowlisted details, not `str(exception)` or raw Pydantic input dumps. Retry execution is outside this component.
4. Continue after independent record errors and preserve prior good results on later failure. Block unsafe continued parsing when boundaries are unknown. Do not require a valid source ID to report an error.
5. Define summary status, proposed `accepted`, `partial`, `failed`: empty valid file may be accepted with zero records; mixed accepted/rejected or a later fatal interruption is partial; no accepted records with blocking errors is failed. State scan completeness separately. Warnings alone do not reject a draft.
6. Publish correction/reimport guidance: locator identifies the bad record; a changed file is a new input snapshot; original evidence remains referenced. Reimports preserve source identity but do not promise database upsert or revision deduplication before INGEST-01/IDENTITY-01 integration.

**Acceptance examples.** Three records, with two issues on record 2, report encountered 3, accepted 2, rejected 1, issues 2. All-invalid rows report failed with each locator. Missing title warnings alone leave C05 accepted for later normalization. A late fatal parse error retains earlier drafts, marks scan incomplete and leaves unread count unknown. Secret sentinels in a query, CSV cell or exception are absent from human/JSON diagnostics.

**Tests.** Mixed/all-invalid/empty/warnings-only batches, multiple issues per record, rejected-record conservation, unknown remainder after fatal input, ordered diagnostics, safe JSON round trip, no raw-content logging, classified operational errors and repeated report determinism.

**Native Windows.** Run safe-report tests under native PowerShell with Unicode filenames/messages and verify valid JSON encoding, stable record numbers and absence of tracebacks/raw content for expected input failures.

**Migration/configuration and handoff.** No quarantine table, error database or run summary/C15 implementation. Document report version, counts, status/error semantics and ownership of durable error capture downstream. Close D08.

### SOURCE-02-S07

**Objective/references.** Demonstrate that the fake paginated source and manual fixtures obey the same interface. R02/R03; supporting R14/R15/R16. Blueprint §§4 service-independent interfaces, 6/SOURCE-02 completion criterion and 7 verification distinctions.

**Dependencies.** S01–S06. No real provider, credentials, database, model runtime or Salesforce required.

**Owned files.** `tests/fakes/paginated_adapter.py`, `tests/sources/test_adapter_conformance.py`, `test_adapter_consumers.py`; scripted fixture pages and expected results under `tests/fixtures/sources/paginated/`; updated foundation fake/interface tests as specified in S01. Fakes remain under `tests/`, never production registrations.

**Inputs → outputs.** Scripted synthetic pages plus manual fixtures → executable conformance evidence for shared page/mapping operations, raw provenance, pagination and record-error behavior.

**Tasks.**

1. Build a deterministic fake with injected time/capture, at least three scripted pages, explicit token lookup, call recording and real field extraction from fixtures. Unknown tokens return classified errors. Repeating a request against unchanged scripted input returns equivalent data without advancing hidden global state.
2. Include normal terminal and empty-terminal cases, an empty intermediate page with continuation, duplicate posting observations, immediate/repeated-token defects, truncation, a mid-stream classified failure and malformed record mapping. The fake declares only synthetic scope semantics and never a live-provider capability.
3. Parameterize a common consumer/conformance harness over fake, URL-plus-text and CSV adapters. The harness calls the shared interface, validates results, resolves raw references and maps records without implementation-specific branches. Test-only bounded iteration is acceptable; it must not become a production fetch controller.
4. Verify later failure does not erase earlier records, partial/truncated traversal cannot be represented as exhausted success, and manual/search scope remains non-board coverage. Use consumer examples to document C04 consequences without writing a manifest aggregator or availability logic.
5. Remove the old perpetual `cursor_next`/`COMPLETE` assertion and fabricated title. Keep unaffected foundation protocols/fakes working. Add fail-on-network guards for all manual and fake acceptance paths, including URL fallback and metadata processing.

**Acceptance examples.** Scripted page 1 contains two records and token `p2`; page 2 is empty with token `p3`; page 3 contains one record and is exhausted. The harness sees exactly three records. Failure at page 3 retains the first two and records incomplete traversal. The same harness accepts CSV/text results and finds record issues without checking class names. No production code imports the test fake.

**Tests.** Shared contract behavior plus malformed-page negative cases, safe failure classification, raw/draft identity agreement, frozen timestamps, traversal progress, no external calls and affected foundation regressions. Test signatures through actual invocation, not only structural runtime checks.

**Native Windows.** Run the fake/manual conformance suite with the native interpreter and networking blocked by test guards. Record this as fake integration, not live provider verification.

**Migration/configuration and handoff.** No production provider registration or shipped enabled fake source. Publish the conformance harness for future SOURCE-03 instances and downstream normalization/fetch-controller tests.

### SOURCE-02-S08

**Objective/references.** Verify SOURCE-02's declared acceptance and provide an implementer handoff. R02/R03; supporting R14/R15/R16. Blueprint §§6/SOURCE-02, 7–9.

**Dependencies.** S01–S07; actual SOURCE-01 integration if available, otherwise explicit pending status.

**Owned files.** `tests/sources/test_windows_import_paths.py`, source fixture README and focused regression additions; `docs/components/SOURCE-02.md`; relevant import API/verification examples in `README.md`. No unrelated CLI refactor.

**Inputs → outputs.** Implemented adapters, tests and resolved decisions → recorded checks, native Windows evidence, accurate status, limitations and consumer instructions.

**Tasks.**

1. Run component/affected contract checks, generated-schema comparisons and the existing regression suite. If new auxiliary schemas are exported, compare exporter output to checked-in artifacts. JSON parsing alone is not schema/semantic parity.
2. Run native Windows path/encoding tests below. Record actual OS, interpreter, dependency versions, commands, outcomes and failures. Historical FND-01/DATA-01 evidence is not a substitute.
3. Verify imports/module loading perform no external calls, runtime directory creation or database setup. Prove the no-fetch promise for both import modes, including invalid URLs and hostile text.
4. Exercise SOURCE-01's actual checked selection when available; otherwise record fake-selection evidence and pending real wiring. Document manual-origin/C03 compatibility and the capture sink's production status explicitly.
5. Produce the handoff checklist below with closed and unresolved decisions. Mark implementation VERIFIED only against declared component acceptance, and state any pending integration separately. Do not claim a production durable import workflow, real provider, G1/G2, normalization or end-to-end search completion.

**Acceptance examples.** The handoff identifies exact interfaces and CSV columns, demonstrates good records surviving a malformed neighbor, shows fake pagination exhaustion/failure checks, lists native Windows results, and clearly states that no URL was fetched. Missing SOURCE-01 or durable-capture integration is visible rather than silently represented by a production fake.

**Tests/native Windows.** Execute the matrix and commands below after the corresponding files exist. If the virtual environment is unavailable, record that limitation; this planning task does not repair it or claim new application-test results.

**Migration/configuration and handoff.** Record all interface/schema versions and consumer migration decisions. No storage migration or real-source configuration is expected. Next consumers are SOURCE-03 (one provider at a time), INGEST-01 and INGEST-02.

## Verification matrix and native Windows recipe

These are **future implementation checks**, not results from this planning session. All source URLs/identities are synthetic; fixture URLs use `.invalid`. No live service check is required for SOURCE-02.

| Area | Required evidence | Stories |
|---|---|---|
| Interface compatibility | Exact revised signatures, existing fake/test migration, supported model versions and schema parity | S01, S08 |
| Source gate | Missing/disabled/unreviewed/mismatched selection never invokes adapter; explicit capability binding | S02, S07 |
| Continuation | Cursor/page/offset/local record kinds; empty intermediate/terminal; scope/input binding; truncation/failure; cycles visible | S02, S05, S07 |
| C05 provenance | Byte hashes, resolvable references, parent/record locator, UTC, source tuple, original/mapped separation | S03–S05 |
| Manual text | Supplied URL and text; unknown title; URL-only error; HTML/instructions inert; zero network calls | S04, S07 |
| CSV | BOM, multiline quoting, dialect, leading zeros, bad headers/rows/encoding, bounded paging, changed-input resume rejection | S05 |
| Import errors | Stable codes/locators, valid neighbors retained, fatal-boundary stop, counters/status, redacted reports | S06 |
| Windows | Explicit interpreter/base paths, spaces/umlauts, CRLF, changed working directory, released handles | S04–S08 |

From the repository root in native PowerShell, after implementation:

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
if ($source02FocusedExit -ne 0) { throw 'SOURCE-02 focused checks failed; investigate before continuing.' }

New-Item -ItemType Directory -Path $source02TempRoot | Out-Null
Push-Location $source02TempRoot
try {
    & $source02Python -m pytest $source02WindowsTests --basetemp (Join-Path $source02TempRoot 'Test Data Größe')
    $source02WindowsExit = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($source02WindowsExit -ne 0) { throw 'SOURCE-02 Windows checks failed; investigate before continuing.' }

& $source02Python -m pytest
$source02RegressionExit = $LASTEXITCODE
[pscustomobject]@{
    FocusedExit = $source02FocusedExit
    WindowsExit = $source02WindowsExit
    RegressionExit = $source02RegressionExit
}
```

The Windows test must call actual import APIs using explicit absolute input paths and explicit bases for relative paths. Include a different working directory, an input file changed between pages, UTF-8 BOM, CRLF, spaces/non-ASCII, missing/unreadable input, and file reopening/renaming after handles close. Test destinations belong under the temporary directory, outside the repository. Python uses `pathlib.Path`; URLs never pass through path normalization. Run regression checks once after focused checks pass; investigate failures before claiming acceptance. The temporary-directory command is verification setup, not application persistence.

## Unresolved decisions and closure owners

| ID | Decision / present gap | Proposed direction and closure gate |
|---|---|---|
| D01 | Existing tuple/direct-draft interface cannot carry the required errors/provenance | S01 with FND-01: typed page/draft results, explicit interface revision and consumer migration; record blueprint decision for breaking signatures. |
| D02 | SOURCE-01 is planned, including checked selection and manual `base_url` handling | S01/S02 with SOURCE-01 D01/D06–D08: consume the actual handoff when present; fixtures may verify isolation, but actual binding remains pending. No registry implementation or invented URL here. |
| D03 | Continuation kinds, token version and C04 string bridge | S01/S02: explicit tagged metadata with source/scope/input binding and reversible encoding; INGEST-01 owns storage, retry and aggregate completeness. |
| D04 | Exact-byte raw references and durable capture ownership | S01/S03 with INGEST-01/DATA-01: agree capture protocol and immutable parent/record references. Current filestore overwrites names and repository rejects repeated keys; durable revisions require their own owner, not an incidental SOURCE-02 migration. |
| D05 | Mapping vocabulary/provenance and conservative manual identity fallback | S01/S03 with FND-01/INGEST-02: freeze candidate keys and metadata placement; preserve source text, field paths and explicit IDs; document URL fallback algorithm/version and limits. C05 changes need schema/reader decisions. |
| D06 | Manual input modes, encoding, dialect, headers, blank values/lines and path bases | S04/S05: explicit text or local file; UTF-8/BOM baseline; comma default with explicit semicolon option; no format guessing; snapshot-bound paths and exact original bytes. |
| D07 | Resource/page limits and duplicate-row policy | S05: choose documented finite limits with units and visible overflow; retain duplicate observations with warnings, no merge/overwrite. Limits are local technical defaults, not provider quotas. |
| D08 | Error aggregation, report status and safe output | S01/S06: distinguish record/page/file failure, scan completeness and accepted/rejected counts; non-retryable malformed input; redact by allowlist. No automatic retry loop. |
| D09 | Production operator command and durable import integration | INGEST-01/RUN-01: consume the import API, capture bytes durably, persist results/errors and report runs. SOURCE-02 documents callable examples and pending wiring, not a separate pipeline CLI. |
| D10 | Provider-specific pagination, permissions, rate limits and mapping | SOURCE-03 instance with SOURCE-01: verify only when that provider is selected for implementation. Explicitly outside this task; do not browse/fetch sources to resolve it here. |

D01–D08 must be sufficiently resolved for their dependent implementation stories. Remaining production integration gaps must have named owners and truthful verification status; do not turn technical choices into invented user preferences. D09/D10 are downstream work.

## Implementation handoff checklist

- Component/status, objective, R02/R03 and supporting requirements; exact FND-01/SOURCE-01 dependency versions and actual availability.
- Files changed; final adapter signatures, result/token/report schemas and version/reader migration decisions; changed foundation consumer tests.
- C03 selection/scope/manual-origin assumptions; C05 original/mapped vocabulary, source identity fallback, capture references/byte hashes and provenance; C04 bridge.
- Callable URL-plus-text/CSV examples, columns/dialects/encoding/path rules, limits, duplicate behavior and record-error correction workflow.
- Unit/contract results, fake paginated/manual conformance results, actual SOURCE-01 integration status, native Windows commands/results, and live-provider checks explicitly not performed/not applicable.
- Evidence of zero automatic URL fetching, safe diagnostics and inert text/CSV; no production fake registration.
- Known storage/capture and import CLI integration gaps, unresolved decisions with owners, and next work for SOURCE-03, INGEST-01 and INGEST-02. No G1/G2 or full pipeline completion claim.

[blueprint]: ../../IMPLEMENTATION_BLUEPRINT.md
[fnd]: ../components/FND-01.md
[source01]: SOURCE-01.md
[data]: ../components/DATA-01.md
[interfaces]: ../../src/job_automation/contracts/interfaces.py
[postings]: ../../src/job_automation/contracts/postings.py
