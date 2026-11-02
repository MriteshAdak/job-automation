# SOURCE-03-arbeitnow — Arbeitnow API adapter

Status: **PLANNED** · Planning/research date: **28 October 2026** · Phase 0 · Scope: **SOURCE-03-arbeitnow only**

Baseline: [IMPLEMENTATION_BLUEPRINT.md][blueprint], version 1.0. References use its requirements (§2), contracts (§4), correctness rules (§5), component ownership (§6), integration gates (§7), implementation/handoff instructions (§8), and native Windows conventions (§9). These are implementation stories, not an adapter implementation or evidence that live adapter acceptance has passed.

## Repository evidence and dependencies

Read the blueprint, [README](../../README.md), [FND-01 handoff][fnd], [SOURCE-01 handoff][source01], [SOURCE-02 handoff][source02], [SOURCE-02 stories](SOURCE-02.md), and [DATA-01 handoff][data]. Inspected current contracts/schemas, source registry and access policy, adapter helpers/manual implementations, conformance tests, raw storage, configuration examples, and dependency declarations. No applicable `AGENTS.md` was found in the repository or its ancestors; `C:/Users/mrite/.codex/AGENTS.md` is empty. README and blueprint §§8–9 supply repository instructions.

SOURCE-02 code and its handoff became available during this review; this document uses that later snapshot, not the earlier SOURCE-02 story document's outdated statement that SOURCE-01 is unimplemented. Recheck the handoff and code before implementation because the workspace is being developed concurrently.

| Dependency/evidence | Current state and consequence |
|---|---|
| SOURCE-02, direct catalog dependency | Handoff reports VERIFIED, with 341 passing tests on native Windows. These are upstream reported results, not checks run for this story document. Its typed interface is now present. |
| FND-01 / SOURCE-01, transitive dependencies | Handoffs report VERIFIED. Use schema 1.0 C03/C05, `SourceRegistryService.select_sources`, and its selected `EffectiveSource`; never construct a permissive production selection to bypass registry checks. |
| [Adapter protocol][interfaces] | `fetch_page(config: SourceConfig, continuation: Continuation | None = None) -> AdapterPage`; `draft_posting(raw: RawPosting) -> DraftResult`. Do not implement the obsolete tuple/`FetchOutcome` return shape. |
| [Auxiliary contracts][results] | `AdapterPage` carries ordered `items`, `issues`, raw references, continuations, exhaustion/truncation, error and counts. `Continuation.encode()` supplies the `cont-v1:` C04 string bridge. `DraftResult` permits a draft with warnings or no draft with blocking errors. |
| [Binding helpers](../../src/job_automation/sources/adapters/binding.py) | Check enabled/access/method and source key/provider/board. They do not by themselves establish provider-host restrictions, full config equality, attribution readiness, or protection against mutable nested dictionaries. Add Arbeitnow-specific boundary checks; do not assume the helper proves those properties. |
| [Continuation helpers](../../src/job_automation/sources/adapters/continuation.py) | Check source/scope/adapter and immediate repeated values. Provider page syntax, supported versions/kinds, unsafe URLs and longer cycles still need explicit handling. Base64 is serialization, not authorization. |
| [Mapping helper](../../src/job_automation/sources/adapters/mapping.py) | Existing vocabulary includes raw location/workplace/employment/date fields plus `mapping_version` and `provenance`. The helper is manual-input oriented: it expects `source_url` and `company`/`company_name_hint`, stringifies some types and rejects empty description. Prevalidate provider types, translate aliases and restore provider field paths; do not pass Arbeitnow JSON straight through it. |
| [Raw capture](../../src/job_automation/sources/adapters/raw.py) / DATA-01 | `RawCaptureSink.capture(bytes, identifier_hint)` returns reference/hash; `get(ref)` resolves bytes. Available in-memory capture is not durable. Existing `Filestore` overwrites posting-derived names; raw repository rejects repeated source tuples. Neither proves immutable page capture or revision upserts. Durable capture remains INGEST-01/DATA-01 work. |
| C05 / schemas | C05 has no dedicated parent-page locator, attribution or mapping-version field. Nested mapped dictionaries permit a documented representation; do not add top-level fields silently. `UtcDatetime` requires awareness, not automatically zero offset; explicitly produce UTC. |
| Configuration | `config/sources.example.json` has disabled synthetic `arbeitnow_de`, provider `arbeitnow`, board `default`, `.invalid` endpoint and illustrative prose limits. Those are not permission or current rate-limit evidence. `active_sources` remains empty by default. |
| Runtime | No production HTTP adapter, fetch controller or normalizer exists in this snapshot. `pyproject.toml` declares Python >=3.12, Pydantic/tzdata and pytest dependencies with ranges, not exact pins; no HTTP client dependency is declared. |

Planning verification: PowerShell checks passed for all local/reference links, seven sequential story IDs, balanced code fences and readable UTF-8. An attempted documentation check through `.venv/Scripts/python.exe` failed because its referenced Python 3.12 installation could not be found. No application tests were run in this planning task. Revalidate or repair that environment before S07; upstream reported Windows passes do not establish that the current interpreter is runnable.

**Requirements:** directly R02 (permitted configurable acquisition, honest coverage) and R03 (raw preservation and source mapping); supporting R04 (scoped source identity only), R09 (capture handoff only), R14 (native Windows), R15 (untrusted input, safe access/diagnostics), R16 (bounded execution and explicit failures). Do not implement canonical identity or retention policy under those supporting references.

**Inputs → outputs:** checked C03/`EffectiveSource`, optional bound continuation, injected HTTP transport/clock/capture sink → one `AdapterPage` of C05 `RawPosting` records; each raw record → `DraftResult` containing C05 `SourceJobDraft` or traceable issues. C04 is a consumer contract, C06 is a downstream target, and neither is produced by this adapter.

**Excluded:** other SOURCE-03 providers; scraping job/detail/application pages; ATS enrichment; manual-adapter redesign; production retry loops, full-feed orchestration, C04 persistence, storage migrations, C06 normalization/HTML cleaning, C07 deduplication/availability, matching, Salesforce writes, applications, model calls and Phase 2 scheduling. A small opt-in smoke harness is permitted for verification, not a second pipeline CLI.

## Official API and terms evidence

Reviewed the following official sources on 28 October 2026. Documentation retrieval succeeded; **no live job-feed request or adapter smoke test was performed** during story planning. Search results from directories/wrappers were not used as API authority.

| Ref | Official source and freshness | Verified evidence and limits |
|---|---|---|
| E1 | [Arbeitnow API announcement][announcement], page says last updated 1 August 2026 | Advertises a free API without an API key, links E2, describes `remote`, and documents `visa_sponsorship=true/false`. Paid custom endpoints are separate and outside scope. This does not document arbitrary search, `remote=true`, page-size overrides or a single-job endpoint. |
| E2 | [Arbeitnow Postman documentation][postman], linked by E1 | Published collection contains a GET request and a saved HTTP 200 JSON example. Collection publication is 27 November 2021; saved response Date is also that day. It is documentation currently served, **not a response observed from the 2026 feed** or a formal required-field schema. |
| E2a | [Public collection backing E2][collection], discovered through the documentation page's own prefetch link | Used because the browser search reader returned an empty Postman page. This is a documentation resource, not an application endpoint for the adapter. Request uses `https://arbeitnow.com/api/job-board-api`; saved original request uses `https://www.arbeitnow.com/api/job-board-api`. Host canonicalization/redirect behavior remains untested. |
| E3 | [Arbeitnow terms][terms], especially §§2, 7 and 11 | §11 provides API use on an as-available basis, requires a link back to Arbeitnow.com on the platform and permits revocation. §2 separately limits website-material copying, public display and mirroring. The interaction with durable API storage/Salesforce transfer is not expressly resolved in the reviewed text; record the intended-use review instead of asserting unrestricted redistribution. Terms can change. |

The following is a **shape summary of E2's saved example**, not a declaration that every field is mandatory or immutable:

| JSON path | Example representation | Adapter consequence |
|---|---|---|
| Root | Object with `data`, `links`, `meta` | Validate envelope before interpreting it as jobs. Preserve additional root fields in the parent capture. |
| `data` | Array of objects | Preserve ordering; isolate invalid records where boundaries are trustworthy. |
| `data[i].slug` | String | Candidate provider posting key; permanence/uniqueness guarantees are undocumented. |
| `company_name`, `title`, `description`, `url`, `location` | Strings; description contains HTML, and one example description is empty | Do not infer usable description from its mere presence. URL is a listing URL, not evidence of a separate direct application URL. |
| `remote` | JSON boolean | Preserve true/false/unknown distinctly. |
| `tags`, `job_types` | Arrays of strings | Preserve labels; sample job types mix employment and seniority concepts. |
| `created_at` | Integer, e.g. `1638006745` | Looks consistent with Unix seconds, but the retrieved text does not define units or whether it means employer publication, import or refresh. Retain raw value. |
| `links.first`, `links.next` | Absolute API URLs with `?page=1` / `?page=2` | Validate against source restrictions before producing/requesting continuation. |
| `links.prev`, `links.last` | Null in saved first page | `last=null` does not mean the current page is terminal; that example also has a next link. |
| `meta` | `current_page`, `from`, `path`, `per_page`, `to`, `terms`, `info` | Pagination/notice evidence, not a total-count or complete-market guarantee. Example `per_page=100`, `to=100` accompany only six displayed records; do not derive actual counts from this saved example. |

E2's `meta.info` describes page-number pagination, hourly updates and ordering by `created_at`; direction, stable tie ordering and snapshot consistency are unspecified. The saved headers include rate-limit limit 3 and remaining 2, with no established window. These historical values must not become production quota assumptions. Null-next termination is a proposed conservative parser rule to verify, not a terminal response observed in E2. [Source: official Postman collection][postman]

### Uncertainties and safe decisions

These are engineering decisions for this instance, separate from provider promises and confirmed user requirements.

| ID | Uncertainty | Decision / closure owner |
|---|---|---|
| U01 | Current feed may differ from the 2021 saved schema; no formal requiredness/nullability specification found | S02/S05 retain unknown fields, explicitly validate known types and record drift. S07 performs bounded live observation; absence of live access remains pending. |
| U02 | Terminal-page, empty-page, out-of-range and relative-link behavior; host redirects | S03 tests proposed defensive behavior using synthetic fixtures. S07 may observe one next page; do not probe arbitrary page numbers or claim that two pages prove termination. |
| U03 | Current rate quota/window, maximum page count, supported page size, caching validators and Retry-After behavior | S02 uses finite local budgets and one transport attempt; INGEST-01 owns retry scheduling/caching. Capture actual relevant headers if supplied. Do not borrow limits from another provider or infer a window from historical headers. |
| U04 | Slug permanence, recycling and repost behavior | S04 uses exact slug as source identity with a documented conservative URL fallback only when absent. No numeric suffix extraction, content-hash identity or canonical merge. Preserve duplicates; IDENTITY-01 owns reconciliation. |
| U05 | `created_at` unit and event meaning | S05 retains it in `original_fields`; leave `source_published_raw=null` until documented meaning is resolved. A later mapping change needs a mapping-version decision. INGEST-02 owns eventual timestamp conversion; magnitude alone is insufficient evidence. |
| U06 | Completeness, retention horizon, deletion signals and consistency while feed changes | Use `filtered_feed`, even without query filters. Successful traversal never proves complete-board inventory or closure. INGEST-01/IDENTITY-02 consume this restriction. |
| U07 | Scope of copying/retention/transfer permission and exact placement of credit | S01 records a scoped access review against E3. A bounded local inspection and broader persistent/public use are separate review scopes. Preserve credit metadata now; SF/OPS owners must resolve their uses before enabling them. Do not contact the provider in this task. |
| U08 | Exact HTTP library and durable sink integration | S01 selects a minimal Windows-compatible transport; stdlib is sufficient if it meets the tests. Require injected `RawCaptureSink`; no implicit memory sink in production. INGEST-01/DATA-01 own durable integration. |
| U09 | No dedicated shared raw-envelope or attribution field; helper validation is narrower than provider needs | S01 freezes the adapter-owned derived-envelope and mapping metadata format below, coordinating with SOURCE-02/INGEST-02. C03/C04/C05 wire schema stays 1.0 unless an explicit shared-contract decision becomes necessary. |

## Contract decisions and C05 mapping

### Configuration, identity and continuation

Use `source_key="arbeitnow_de"` as the proposed configuration name, `provider="arbeitnow"` and `board_id="default"` to align with existing examples. `default` is a local namespace for the reviewed `.com` feed, not a provider-issued tenant ID or a claim that every job is German. Any later country-host feed needs a separate reviewed origin/board identity. A config alias is not a different posting identity; filters affect `scope_id`, not the posting tuple.

Initial implementation supports the unfiltered `.com` API and documented `page` traversal only. E1's visa filter is recorded but deferred; reject configured unimplemented filters rather than silently ignoring them or losing them on next links. Role/geography matching belongs downstream. Use SOURCE-01's scope computation; never derive scope from the page number.

Bind a detached checked source to the adapter. Proposed adapter identifier is `arbeitnow-v1`, with `Continuation.kind="page"` and a strictly validated positive page number encoded in `value`. Parse an approved next URL into that number rather than granting the URL arbitrary fetch authority. Reject unknown continuation versions/kinds, foreign source/scope/adapter, malformed or non-forward pages. Fetching a resumed page is not proof that preceding pages were fetched. Do not bind a live continuation to one response hash as though the feed were immutable.

Allow only HTTPS, the reviewed `arbeitnow.com` / `www.arbeitnow.com` hosts, port 443/default, exact `/api/job-board-api` path and supported query keys. Include both official spellings explicitly in the review; do not discover new hosts by following redirects. Disable automatic redirects or validate each hop before requesting it, with a finite hop cap. Reject userinfo, fragments, downgrade, alternate ports, suffix/lookalike hosts, unknown/duplicate query parameters and unsafe encoded path variants. Detail URLs are data and are never fetched.

### Raw evidence and record representation

1. Capture the entire response body before parsing. Define the byte boundary as the exact entity bytes returned by the transport after any explicitly documented content decoding, before text/JSON decoding. If compressed wire bytes are also retained, give them a separate hash/reference; never mix hashes from different representations. Capture safe status/headers separately; exclude cookies, credentials and arbitrary response-header dumps from logs.
2. Retain the parent reference in `AdapterPage.raw_response_refs`, including for malformed JSON/envelopes. An unidentified record has a `RecordIssue` at parent reference/hash plus 1-based `record_index` and `data[index]` path; no made-up `SourceKey` is needed.
3. Proposed provider-owned derived envelope for identified records: `envelope_version`, `record` (the exact parsed job object), and `capture` containing `parent_ref`, `parent_hash`, `record_index`, mapping identifier and reviewed attribution notice/link. Serialize deterministically to UTF-8 and capture those bytes through the same sink. `RawPosting.raw_payload_ref`, `raw_content_hash` and `raw_payload` refer to **that derived envelope**, not falsely to a byte-exact substring of the response. The envelope is explicitly derived and links back to original response bytes.
4. `SourceJobDraft.original_fields` is only the original job dictionary, including unknown fields and original null/empty values. Parent metadata is not injected into provider data. `raw_reference`, source tuple and fetch time match C05 raw input exactly. Drafting must work after serialization/reload using its raw reference/payload, with no hidden last-fetch cache.
5. Use existing `source_mapped_fields.mapping_version` and `provenance` conventions. Proposed mapping ID is `arbeitnow-map-v1`; provider paths such as `data[0].company_name` and the parent locator make aliases traceable. Document an adapter-owned `attribution` metadata entry carrying `notice`/`link`, not a new provider job fact. Confirm this extension with the downstream mapping vocabulary in S01.

The derived-envelope hash proves capture integrity; parent references or attribution metadata can change between observations. It is not a stable job-content fingerprint or job identity. IDENTITY-01 owns normalized revision comparison; this component must not promise that repeated observations deduplicate merely because raw hashes are available.

No storage migration or shared top-level C05 field is required by this proposal. If SOURCE-02 supplies a newer common envelope before implementation, use it and document compatibility rather than creating a competing format.

### Source-field mapping matrix

Prevalidate exact JSON types before calling the shared mapping helper; booleans are not numbers and strings such as `"false"` are not booleans. Preserve original whitespace in `original_fields`; candidate-field trimming performed by the existing helper must be documented and must never alter HTML or source identity. Missing and explicit null are distinguishable in `original_fields` even when both map to null.

| Provider field | C05 destination / proposed behavior | Missing/invalid behavior and C06 boundary |
|---|---|---|
| `slug` | `SourceKey.source_posting_id` = exact nonblank string; preserve case/leading zeros | Absent/null/blank permits documented `url-v1:sha256:<hex64>` fallback over exact validated URL, with warning. Wrong type is a blocking record issue. No valid slug or URL means issue only. Slug/URL disagreement is retained and flagged, not silently merged. |
| `company_name` | `company_name_hint` through an explicit alias | Missing/null/blank → null plus warning; wrong type → blocking mapping issue. No company ID or canonical company inferred. |
| `title` | `title` | Missing/null/blank → null plus warning, as SOURCE-02 permits. Wrong type → blocking issue. INGEST-02 validates required normalized title; no title from slug or first description line. |
| `description` | `description`, unchanged HTML/text | Missing/null/blank → no draft plus `missing_posting_text`, retaining raw evidence, consistent with current helper. Wrong type → blocking issue. Empty description is represented in E2, so it must be a supported failure case, not a page failure. No HTML execution/cleaning here. |
| `url` | `source_url`, original validated HTTP(S) listing URL | Required for a usable draft under the current helper. Invalid/missing → blocking mapping issue even if slug permits raw capture. Never manufacture a current listing route from slug; `/view/` in old examples is not a current route guarantee. |
| No documented direct apply field | `application_url=null` | Do not equate listing URL with direct application URL or follow links to discover one. New fields remain original-only pending mapping review. |
| `location` | `locations_raw` = unchanged string | Missing/null/blank → null; wrong type → blocking issue. No country default, geocoding or splitting into fictional cities. |
| `remote` | `workplace_type_raw` = original boolean | Missing/null → null; string/number → blocking issue. `false` does not establish onsite versus hybrid; `true` does not establish worldwide eligibility. INGEST-02 owns normalized workplace semantics. |
| `job_types` | `employment_type_raw` = copied array of strings | Absent/null → null; `[]` remains known empty; wrong container/member type → blocking issue. Do not pick a single normalized employment enum from mixed labels. |
| `tags` | Preserve in `original_fields` | No extraction of candidate skills, language levels, salary or visa eligibility from tags in this adapter. Validate supplied known array/string shape; preserve unknown future fields separately. |
| `created_at` | Preserve original numeric value; `source_published_raw=null` pending U05 | Missing/null stays unknown. Unexpected string/bool/fraction/structure produces a visible issue without coercion. Never substitute fetch time or HTTP Date. Unit conversion is conditional on later evidence and belongs to INGEST-02. |
| No verified compensation/deadline/update fields | `compensation_raw=null`, `source_deadline_raw=null`; no invented update value | Do not default to EUR/year, zero salary, current date, or a 30-day expiry. Unrecognized new fields stay in original data until reviewed. |
| No explicit remote restrictions, advert language, required language, eligibility or company ID | Retain absence; no new normalized facts | Unknown restrictions are not `[]` meaning worldwide. Do not infer language from German coverage, sponsorship from query membership, or employee eligibility from the advert. |
| Local receipt time | Both C05 fetch timestamps use injected aware clock converted to UTC | Reject a naive clock value rather than guessing a timezone. Source dates, observed time and downstream first/last seen remain distinct. |

### Pagination and error outcomes

| Observation | Required adapter result / future consumer consequence |
|---|---|
| Valid `links.next` | Bound continuation, `exhausted=false`. Never use `len(data) < per_page`, `last=null` or a local budget as end-of-feed evidence. |
| Valid envelope with explicit `links.next=null` | Proposed terminal rule: no continuation, `exhausted=true`, no page failure/truncation. Record issues remain visible. Live terminal behavior is still unverified. |
| Empty `data` plus valid next link | Zero records, continue; empty is not terminal by itself. |
| Missing/malformed `links` or `next`, contradictory current-page metadata, invalid next target | Preserve captured jobs where possible, return safe pagination error, `exhausted=false`. No invented next page or silent complete result. |
| Valid next beyond caller's page budget | Adapter still reports continuation; controller/harness stops as partial. Do not pretend a truncated traversal exhausted the source. |
| Same/backward next page or longer cycle | Reject non-forward continuation; bounded consumer tracks visited tokens as an additional guard. No retry loop inside adapter. |
| Non-JSON/HTML challenge, broken encoding, duplicate JSON keys, invalid root/data container | Captured parent reference plus classified page error. Never turn it into an empty successful feed. If record boundaries cannot be trusted, do not guess them. |
| Bad independent record | Ordered `RecordIssue`; retain parent bytes and valid neighbors. Counts distinguish raw records, drafts, rejected records and issues; duplicate observations are not canonical-job counts. |
| 401 / 403 | Authentication / permission error respectively, not retryable scraping fallbacks. |
| 429 / timeout / 5xx | Rate-limit / transient-network / transient-service error; pass safe retry hints if present. Recoverability is metadata, not permission to retry indefinitely. |
| Other unexpected HTTP result, including 404/304 | Explicit classified unsupported/validation result according to the recorded status table; no vacancy-closure inference. Without a cache controller, 304 is not an empty page. |
| Capture failure or response-byte cap | Permission/capacity or other applicable existing category, with no fabricated durable reference and no false exhaustion. Stop visibly; do not silently truncate JSON and parse a prefix as a complete response. |

## Ordered implementation stories

Every story is **PLANNED**. Paths below describe future ownership; this planning task creates only this Markdown file. Use provider-local files unless a shared change has been explicitly coordinated under blueprint §8.

### SOURCE-03-arbeitnow-S01 — Freeze access, mapping and interface decisions

**Objective/references:** Establish a reviewable Arbeitnow specification before HTTP work. R02/R03/R15; C03/C05, adapter boundary; blueprint §§4, 6/SOURCE-03, 8; SOURCE-01 decisions D04–D09 and SOURCE-02 D01–D05/D10; E1–E3 and U01–U09.

**Dependencies:** FND-01, SOURCE-01, SOURCE-02 handoff/code available at implementation time. DATA-01/INGEST-01 are capture coordination owners, not authorization to implement them.

**Owned files:** initial `docs/components/SOURCE-03-arbeitnow.md`; proposed `config/sources.arbeitnow.example.json`; `tests/fixtures/sources/arbeitnow/README.md`; provider-specific test configuration builders. Shared `config/app.example.json` and SOURCE-01 examples need no changes.

**Inputs → outputs:** Current official evidence and shared contracts → versioned provider decisions, disabled provider example, fixture provenance catalog and dependency-gap list.

**Tasks:**

1. Recheck E1–E3, recording review time in UTC, URLs, document/example dates and intended use. Keep documentation evidence separate from future live observations; close only uncertainties actually resolved.
2. Produce a disabled C03 example using the reviewed endpoint, provider/board above, API acquisition and `filtered_feed`. Encode structured access/attribution review as SOURCE-01 expects; no fictitious reviewer, no copied synthetic permission. Unresolved use scope stays unreviewed with notes. Keep actual operator enablement outside tracked defaults.
3. Preserve the required link and choose an explicit notice such as `Source: Arbeitnow` (project wording, not a mandated provider phrase). Trace its route from checked source through envelope/mapped metadata to future display owners. Credit must not be lost when descriptions are rejected.
4. Freeze the raw envelope, candidate vocabulary, mapping version, timestamp policy and missing-value decisions above. Reconcile helper limitations and record owner-visible gaps. Do not silently alter shared C05/auxiliary contracts or the manual import behavior.
5. Select injected one-attempt HTTP transport and clock interfaces. Prefer the standard library if adequate; any dependency addition must be free, Windows-compatible and justified. Define timeout/body limits and redirect policy as project choices, not published API limits.

**Fixtures/tests:** `registry_disabled.json`, checked synthetic API configuration builder, denied/unreviewed/unknown-attribution cases; actual SOURCE-01 selection integration with network prohibited.

**Acceptance examples:** Disabled, wrong-provider, manual-method or unreviewed configurations yield zero requests. A reviewed fixture binds with credit intact. Changing only page number leaves scope unchanged; changing a membership filter cannot be silently accepted. `complete_board` for this instance is rejected despite registry-level structural validity.

**Migration/configuration:** No database migration; no source enabled by default; shared wire versions unchanged. Handoff records selected transport and U07/U09 decisions. Native Windows: parse UTF-8 configuration from a path with spaces/umlauts and use the existing read-only `sources check` command.

### SOURCE-03-arbeitnow-S02 — Fetch one bounded response and preserve evidence

**Objective/references:** Acquire exactly one permitted API page with explicit failures. R02/R03/R14/R15/R16; C03/C05, `AdapterPage`, `ClassifiedError`; blueprint §§4–6, SOURCE-02 D02/D04; E1/E2 and U01/U03/U08.

**Dependencies:** S01; checked selection and injected `RawCaptureSink`. HTTP test doubles stay in tests.

**Owned files:** proposed `src/job_automation/sources/adapters/arbeitnow.py`, `arbeitnow_http.py`; minimal export in `sources/adapters/__init__.py`; `tests/sources/test_arbeitnow_http.py`, `tests/sources/test_arbeitnow_access.py`, `tests/fakes/arbeitnow_transport.py`; dependency declaration only if S01 justifies it.

**Inputs → outputs:** Bound source, validated page descriptor, transport and sink → status/body evidence and a page/error, without a multi-page loop.

**Tasks:**

1. Take a detached checked source; enforce `is_valid`, `is_runnable`, required attribution, correct provider/method/origin and exact runtime config snapshot before I/O. Reuse binding helpers and add the missing provider checks locally.
2. Execute one GET attempt with finite timeout/body cap, TLS verification and no credential requirement. Use the endpoint allowlist and redirect rules above. Importing/constructing the adapter performs no network or directory creation.
3. Capture response bytes before strict text/JSON parsing, including error bodies when safely bounded. Reject duplicate JSON keys and nonstandard numeric constants. Preserve unknown envelope keys; validate object/array boundaries.
4. Return the stated error categories with safe templates, status and allowlisted retry headers. Do not dump exception strings, descriptions, cookies or credential-bearing URLs. Do not implement retry/backoff/caching; preserve enough evidence for INGEST-01.
5. Close response handles on every branch. Surface capture failures; no successful C05 result with an invented path/hash or an unresolvable memory reference labelled durable.

**Fixtures/tests:** 200 JSON, HTML challenge, invalid UTF-8/JSON, duplicate keys, wrong envelope, unknown keys, 301/302 approved and forbidden targets, redirect cycle, 401/403/404/429/500/503, timeout/TLS failure, body cap and sink failure. Default tests use fake transport and a fail-on-network guard.

**Acceptance examples:** A 429 causes one call and a rate-limit error with no exhaustion. A redirect to a different host causes no second request. Broken JSON retains a parent reference. A source whose config changes after binding cannot redirect the request. Handles close after both success and error.

**Migration/configuration:** Provider-local implementation only; document byte-limit and timeout units. Native Windows: transport/context-manager and capture-failure tests run with the native interpreter; real TLS connectivity is separately pending until S07.

### SOURCE-03-arbeitnow-S03 — Validate pagination without overstating coverage

**Objective/references:** Translate provider links into safe typed continuations. R02/R03/R16; C03/C04 boundary, `AdapterPage`/`Continuation`; blueprint §§4–6; SOURCE-02 D03; E2 and U02/U03/U06.

**Dependencies:** S01–S02. INGEST-01 owns production traversal, visited-token history, budgets, retries and manifests.

**Owned files:** proposed `sources/adapters/arbeitnow_pagination.py`, pagination wiring in `arbeitnow.py`; `tests/sources/test_arbeitnow_pagination.py`, provider fixtures; focused reuse of `tests/sources/test_adapter_consumers.py` where useful.

**Inputs → outputs:** Requested page and response `links`/`meta` → validated bound continuation or explicit exhaustion/error facts.

**Tasks:**

1. Default a new traversal to page 1. Reuse SOURCE-02 continuation creation/validation/encoding with strict provider-specific validation and version checks.
2. Validate next-link origin/path/query before extracting a page number. Proposed relative-link handling resolves against the reviewed endpoint and subjects the result to identical checks; mark relative fixtures defensive, not observed API behavior.
3. Apply the pagination outcome table. Validate supplied `current_page` type/value against the request; retain other metadata but do not use `per_page`, `to` or `last` to manufacture counts/termination.
4. Reject self/backward progression and repeated/conflicting page parameters. Preserve valid page items even when continuation metadata fails, with `page_error` and `exhausted=false`.
5. Demonstrate lossless `Continuation.encode/decode` use in a bounded test consumer. Keep successful terminal traversal separate from board completeness and record rejection counts; assert `filtered_feed` throughout.

**Fixtures/tests:** first/middle/terminal, empty terminal, empty with next, short page with next, missing next, `last=null` with next, metadata mismatch, cross-host/downgrade/userinfo/encoded-path links, self/backward/cycle, cap and changed-scope token.

**Acceptance examples:** Two records with `per_page=100` and page-2 next link remain nonterminal. Stopping a two-page fixture sequence at a one-page cap is partial. Null-next on a valid synthetic terminal page ends traversal, but a previously observed job absent from this feed is never marked closed. Missing-next is an error, not null-next.

**Migration/configuration:** No C04 model/schema change. Document continuation version and unsupported filters. Native Windows: encode/decode and changed-directory tests are platform-independent in logic but run natively under S07.

### SOURCE-03-arbeitnow-S04 — Preserve source identities and replayable raw records

**Objective/references:** Make each record traceable without canonical resolution. R03/R04/R09/R15; C05/`SourceKey`/`RecordIssue`; blueprint §§4–5; SOURCE-02 D04/D05; E2 and U04/U08/U09.

**Dependencies:** S01 envelope decision, S02 capture and S03 page context.

**Owned files:** proposed `sources/adapters/arbeitnow_records.py`, record extraction in `arbeitnow.py`; `tests/sources/test_arbeitnow_identity.py`, `test_arbeitnow_raw.py`; fixtures under `tests/fixtures/sources/arbeitnow/`.

**Inputs → outputs:** Captured response and job objects → C05 raw records with exact scoped identity, UTC observation and parent provenance; ordered issues for unidentified/malformed records.

**Tasks:**

1. Extract slug exactly, never split its numeric suffix. Implement the explicitly versioned URL fallback for absent/null/blank slug; type errors must not silently take a different identity path.
2. Preserve duplicate source tuples across/on pages, with an observation warning where appropriate; do not overwrite them or allocate canonical UUIDs. Changing content at the same slug preserves source identity; changing board changes it.
3. Capture the derived envelope separately from parent bytes. Verify both hashes against their own byte representations and preserve parent/index linkage through raw serialization and reload.
4. Preserve unknown nested values and deep-copy outputs. One bad record must not remove valid neighbors or page evidence. Record an issue before identity is available without fabricating a posting ID.
5. Produce UTC fetch time from an injected aware clock. Map a reloaded raw record independently of fetch order or cached state, validating provider/board/envelope version and reference/hash consistency.

**Fixtures/tests:** mixed valid/unidentified records, absent slug with URL, both absent, invalid slug type, `"0007"` versus `"7"`, case variants, changed content/same slug, duplicate slug, different board, changed fallback URL, nested fields, altered/tampered envelope, sink failure.

**Acceptance examples:** Two sightings of slug `"0007"` with changed descriptions have the same source key and different content evidence; neither is silently discarded. A record with neither usable identity path produces a parent-linked issue while its neighbors remain. Drafting serialized raw input with a fresh adapter preserves identity and evidence.

**Migration/configuration:** No revision/upsert/storage migration. Document fallback false-negative risk when a later slug appears or a URL changes. Native Windows: opaque IDs never become unsafe filenames; capture under a Unicode path, then rename captured files after close to expose leaked handles.

### SOURCE-03-arbeitnow-S05 — Map fields, timestamps, attribution and missing values into C05

**Objective/references:** Extract source meaning without premature normalization. R02/R03/R15; C05 and C06 boundary; blueprint §4/global conventions and C06 details; SOURCE-02 D05/D08; mapping matrix, E1–E3, U01/U05/U07/U09.

**Dependencies:** S01 mapping agreement and S04 replayable raw records.

**Owned files:** proposed `sources/adapters/arbeitnow_mapping.py`, `draft_posting` wiring in `arbeitnow.py`; `tests/sources/test_arbeitnow_mapping.py`, `test_arbeitnow_timestamps.py`, `test_arbeitnow_attribution.py`; expected-draft fixtures. Shared `mapping.py` is a dependency, not permission to redesign all adapters.

**Inputs → outputs:** Valid C05 raw envelope → `DraftResult` with copied source fields, agreed mapped vocabulary/provenance/credit, or blocking record issues retaining `raw_reference`.

**Tasks:**

1. Implement every row of the mapping matrix with explicit type checks before helper coercion. Translate `company_name`/`url` into helper input aliases while preserving the original dictionary and provider provenance paths.
2. Reuse the common mapper where compatible; supplement provider warnings/type validation and documented attribution metadata locally. Do not let helper convenience fabricate values, lose array emptiness or conflate false and absent.
3. Keep `created_at` unchanged and publication unknown under U05. Missing/invalid source timestamps never fall back to fetch time, HTTP Date, local time or an inferred deadline. If later evidence settles seconds and publication meaning, record a new mapping decision and downstream normalization tests before populating publication candidates.
4. Preserve HTML, tags, job-type labels and future fields as data; no commands, links, scripts or prompts are executed. Avoid deriving remote eligibility, salary, language proficiency or visa facts.
5. Return draft plus warnings for allowed missing title/company; return no draft plus errors for unusable description/URL or invalid known types. Preserve raw records on failure. Propagate reviewed credit even when mapped fields are sparse; no requirement to build Salesforce UI here.

**Fixtures/tests:** all field mappings; missing vs null vs blank vs empty array; boolean false vs missing vs `"false"`; malformed lists; non-ASCII HTML; hostile content; empty description matching the official example's shape; unknown extra fields; `created_at` integer/null/string/bool/fraction/large value; aware Berlin clock converted to UTC and naive-clock rejection.

**Acceptance examples:** `remote=false` survives unchanged, with no onsite claim. `job_types=[]` stays empty while missing job types maps to null. Missing salary yields no EUR/year object. An integer creation value is preserved without asserting employer publication. If epoch seconds are later confirmed, a downstream synthetic `1704067200` conversion must be `2024-01-01T00:00:00Z`, independent of Windows timezone; that conditional example is not provider evidence. Missing title yields warning plus null, not a slug-derived title. Empty description yields traceable rejection, not a failed whole page.

**Migration/configuration:** C05 wire version unchanged; mapping/envelope versions and reserved metadata documented. Any shared vocabulary extension requires explicit coordination and regression checks. Native Windows: Unicode JSON round-trip and UTC production tests; no dependence on machine locale/DST.

### SOURCE-03-arbeitnow-S06 — Prove shared-consumer behavior and failure isolation

**Objective/references:** Show that the concrete adapter fits SOURCE-02's consumer boundary. R02/R03/R14/R15/R16; C03/C05, auxiliary results, C04 consumer examples; blueprint §§6–8; SOURCE-02 S07/S08.

**Dependencies:** S01–S05; existing fake/manual conformance harness and SOURCE-01 real registry service.

**Owned files:** `tests/sources/test_arbeitnow_conformance.py`, `test_arbeitnow_failures.py`; minimal parameterization in `tests/sources/test_adapter_conformance.py`; provider fake/fixtures; component handoff verification section.

**Inputs → outputs:** Scripted HTTP pages through real adapter and checked selection → replayable C05 drafts/issues and recorded consumer outcomes, with no real network.

**Tasks:**

1. Add Arbeitnow to shared conformance using injected transport/capture. Consumers call only `fetch_page` and `draft_posting`, not provider-specific success/error methods.
2. Test page-1 success followed by timeout/429/bad pagination, budget stop, invalid record between valid records and duplicate observations. Strengthen test-consumer assertions for `page_error`/`truncated`; the simple existing collection helper's exhaustion boolean alone is not proof of a successful inventory.
3. Assert issue accounting does not double-count the same mapping rejection at fetch and draft stages. Raw item count, accepted draft count, rejected record count and issue count have distinct units; C15/canonical-job aggregation stays out of scope.
4. Assert all outputs conform to typed models and unchanged generated schemas, including round trips, independent reload and version rejection. A runtime `isinstance(Adapter)` check alone is insufficient.
5. Prove import/construction/drafting are network-free; only explicit fetch may invoke the injected transport. Verify safe diagnostics and no candidate data, credentials or full job text enter routine logs.

**Fixtures/tests:** shared scripted pages, fail-on-network fixture, real registry selection, failing capture fake, logging assertions and golden C05 outputs. Keep synthetic provider-shaped data distinct from live evidence.

**Acceptance examples:** After page 2 fails, page 1 raw/drafts remain available and the test consumer reports partial traversal. Rejected records retain locators without changing neighboring IDs. Manual imports remain network-free and existing conformance cases still pass. No test claims durable DB rerun idempotency or complete-board coverage.

**Migration/configuration:** No production orchestration or manifest persistence. Native Windows: run focused contracts/sources tests and the full regression suite under S07; document any pre-existing failures separately rather than fixing unrelated components silently.

### SOURCE-03-arbeitnow-S07 — Native Windows checks, bounded live observation and handoff

**Objective/references:** Demonstrate component acceptance with honest verification status. R02/R03/R14/R16; blueprint §§6/SOURCE-03, 7–9; E1–E3 and unresolved U01–U09.

**Dependencies:** S01–S06; reviewed source configuration and working capture/transport for optional live verification. Live unavailability does not justify scraping or another provider implementation.

**Owned files:** `tests/sources/test_arbeitnow_windows.py`; proposed `tests/manual/arbeitnow_smoke.py` (opt-in verification helper); final `docs/components/SOURCE-03-arbeitnow.md`; fixture README and concise README usage note if needed. No new production CLI command is required.

**Inputs → outputs:** Implemented adapter, synthetic checks and at most two permitted feed requests → separate unit/contract, fake integration, live and native Windows results; limitations and next-consumer handoff.

**Tasks:**

1. Execute the Windows recipe below with actual interpreter/package/OS versions recorded. Check Unicode/space paths, changed working directory, CRLF fixture handling, exact hashes, UTC, file-handle release and no persistent dependency on an activated shell.
2. Export schemas into a temporary directory and compare semantically with checked-in schemas if shared contracts/exports changed; do not overwrite tracked schemas just to verify them. Test mapping semantics as well as JSON validity.
3. Implement an explicit opt-in smoke helper using the adapter and checked selection. It accepts an absolute registry/data destination, bounded pages and the project budgets below; it cannot run under default pytest collection or initiate background polling.
4. Perform the small live plan only if access/attribution and capture prerequisites are met. Record denied/unavailable/capped/drift outcomes faithfully; live pending is a valid reported limitation, not a fabricated pass.
5. Complete the handoff checklist, record unresolved decisions/owners, and distinguish an implemented adapter from complete G1 integration. No live Salesforce or full pipeline claim.

**Acceptance examples:** Offline conformance and native Windows checks have reproducible results. A permitted GET reaches the real API through the adapter and yields captured, mapped records or explicitly reported source-data issues; any unmet acceptance is visible. If access is blocked, handoff says live verification pending, with reason and next action. No implementation status is inferred from this planning document.

**Migration/configuration:** No enabled production source, scheduler or database migration. Smoke evidence stays in an explicit local runtime directory outside tracked source. Any retention permission question remains assigned to its owning review/OPS work.

## Synthetic fixture catalog

Future fixture root: `tests/fixtures/sources/arbeitnow/`. Use original synthetic employer/text values and `.invalid` listing URLs; endpoint allowlist tests may contain the real documented host but transport must be intercepted. Do not commit real job descriptions, copied Postman descriptions or live bodies. Fixture README records source URL/date, whether shape is documented or defensive, expected outcome and content-hash generation method.

| Fixture group (proposed names) | Evidence basis and expected coverage | Stories |
|---|---|---|
| `page_1.json`, `page_2.json`, `page_terminal.json` | E2-shaped `data/links/meta`; terminal is explicitly synthetic/unverified. Include office/customer-service and technical roles so adapter behavior is not hardcoded to tech. | S02–S06 |
| `empty_terminal.json`, `empty_with_next.json`, `short_with_next.json`, `last_null_with_next.json` | Defensive pagination cases; do not claim each was observed live. | S03/S06 |
| `bad_envelope.json`, `duplicate_keys.json`, `invalid_json.txt`, `invalid_utf8.bin`, `challenge.html` | Page errors preserve bounded raw evidence; no false empty success. | S02/S06 |
| `unsafe_links.json`, `bad_pagination.json`, `cycle_pages.json` | Host/path/query/redirect/token/metadata safety and partial traversal. | S02/S03 |
| `mixed_records.json`, `duplicate_slug.json`, `identity_variants.json` | Record isolation, missing identity, exact slug/URL fallback and duplicate observations. | S04/S06 |
| `missing_fields.json`, `wrong_types.json`, `unknown_fields.json`, `empty_description.json` | Preserve null/empty distinctions; explicit failures; empty description exists in E2. | S04/S05 |
| `timestamps.json`, `unicode_hostile_html.json`, `expected_drafts.json` | Raw date policy, local UTC, inert HTML, mapping/provenance/attribution golden cases. | S05/S06 |
| `http_scenarios.json`, capture/clock/transport fakes | Status/errors, timeout, body caps, failure after prior success; fake quota values never treated as current provider policy. | S02/S06/S07 |

## Native Windows verification recipe

**Future implementation checks, not results from this planning session.** Run from repository root in native PowerShell. Proposed `test_arbeitnow_windows.py` must exist before executing the Windows-specific command. No WSL, Bash, Docker, paid service or installed Office is required.

```powershell
$source03Repo = (Get-Location).Path
$source03Python = Join-Path $source03Repo '.venv\Scripts\python.exe'
$source03Tests = Join-Path $source03Repo 'tests'
$source03SourceTests = Join-Path $source03Tests 'sources'
$source03ContractTests = Join-Path $source03Tests 'contracts'
$source03WindowsTests = Join-Path $source03SourceTests 'test_arbeitnow_windows.py'
$source03TempRoot = Join-Path $env:TEMP ('Job Automation Prüfung ä SOURCE-03 ' + [guid]::NewGuid().ToString())

& $source03Python -c "import platform, sys; from zoneinfo import ZoneInfo; print(platform.platform()); print(sys.version); print(ZoneInfo('Europe/Berlin'))"
if ($LASTEXITCODE -ne 0) { throw 'Environment check failed.' }
& $source03Python -m pip show pydantic pytest tzdata
& $source03Python -m pytest $source03ContractTests $source03SourceTests
if ($LASTEXITCODE -ne 0) { throw 'Contract/source checks failed.' }

New-Item -ItemType Directory -Path $source03TempRoot | Out-Null
Push-Location $source03TempRoot
try {
    & $source03Python -m pytest $source03WindowsTests --basetemp (Join-Path $source03TempRoot 'Test Data Größe')
    $source03WindowsExit = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($source03WindowsExit -ne 0) { throw 'Native Windows checks failed.' }

& $source03Python -m pytest $source03Tests
if ($LASTEXITCODE -ne 0) { throw 'Regression checks failed.' }
```

Record added HTTP-package versions if applicable. Tests must avoid real networking and use a fresh temporary path; retain artifacts only as needed for investigation. The current SOURCE-02 reported test count is historical and should not be asserted as the expected future total.

## Small permitted live-verification plan

This plan is for S07 after implementation. It is not executed or authorized as ongoing collection by this story-planning task.

1. Revisit E1/E3 and record a current scoped SOURCE-01 API review. Use a deliberately enabled **local** configuration selected through `SourceRegistryService`; keep tracked examples disabled. Make credit visible in the smoke report as [Source: Arbeitnow](https://www.arbeitnow.com), and preserve it with captured/mapped evidence. Resolve U07 for the intended capture/retention use; if that use cannot be justified, leave live pending.
2. Default to **one GET**, page 1 of `https://www.arbeitnow.com/api/job-board-api`. Permit a second GET only when needed to inspect a returned, validated next link. Hard maximum is **two HTTP requests total, including redirect hops**, one attempt each, sequentially, at least 60 seconds apart. A redirect consumes the request budget; it must be checked before following. No page-number probing, detail requests, auth, concurrency, polling or automated retries.
3. Proposed local budgets: 30-second bounded request time and 10 MiB maximum entity body per response, no background work. These are conservative test choices, not provider limits or a promise of permission at that rate. Honor a longer server wait instruction by stopping and recording pending verification, rather than shortening it. Stop on denial, rate limit, challenge, unexpected redirect or schema drift.
4. Use the real adapter and an explicitly supplied resolvable capture sink. A small test-only file sink beneath the chosen runtime directory may demonstrate capture; label it as test infrastructure, not production durable ingestion. Do not use the existing overwriting filestore to claim revision retention. Record actual UTC time, endpoint/status, content type, byte count/hash, allowed rate/retry headers, top-level/record field names/types, record/issue counts, continuation and mapping version. Keep raw bodies out of Git and ordinary logs.
5. Inspect a small number of mapped records locally for identity, timestamp treatment, HTML preservation, nulls and attribution. Compare shapes with E2; record observations rather than strengthening undocumented guarantees. A two-page run with another next link is intentionally **partial**. No completeness, current quota window, stable ordering, slug permanence, closure or general market-coverage conclusion follows from this smoke test.
6. Record outcome as passed within the stated small scope, failed with reason, or pending. Fixture-only success is not live verification. Access failure does not trigger scraping, a paid endpoint or implementation of another source. Stop after the bounded attempt and hand off remaining uncertainty.

## Implementation handoff checklist

- Component ID, status, objective, requirement/contract references, implementation date and exact prerequisite versions/snapshot.
- Owned files changed, public adapter signatures, envelope/mapping/continuation versions, schema compatibility, provider/board/config identities and unsupported configuration.
- Official evidence URLs/review times, old-example versus live-observation distinction, access/attribution decisions and unresolved U01–U09 with owners.
- Response validation, pagination/end/cap/error semantics, count units, raw byte boundary and resolvable parent/record hashes; unidentified and duplicate-record handling.
- Complete source-to-C05 mapping, timestamps, unknown/null/empty behavior, provenance and downstream credit obligations; no inferred C06/canonical facts.
- Unit/contract checks, fake HTTP/shared-consumer checks, native Windows commands/results and live checks listed **separately**. Include environment/package versions and any failures or pending work.
- Durable sink/revision persistence and production controller remain INGEST-01/DATA-01; normalization remains INGEST-02; identity/availability remains IDENTITY-01/02; display/retention decisions remain with their owners.
- Mark IMPLEMENTED when code exists with specified verification pending; mark VERIFIED only when declared component acceptance is demonstrated. Do not claim G1, Salesforce synchronization or overall Phase 0 completion.

[blueprint]: ../../IMPLEMENTATION_BLUEPRINT.md
[fnd]: ../components/FND-01.md
[source01]: ../components/SOURCE-01.md
[source02]: ../components/SOURCE-02.md
[data]: ../components/DATA-01.md
[interfaces]: ../../src/job_automation/contracts/interfaces.py
[results]: ../../src/job_automation/contracts/adapter_results.py
[announcement]: https://www.arbeitnow.com/blog/job-board-api
[postman]: https://documenter.getpostman.com/view/18545278/UVJbJdKh
[collection]: https://documenter.gw.postman.com/api/collections/18545278/UVJbJdKh?segregateAuth=true&versionTag=latest
[terms]: https://www.arbeitnow.com/terms
