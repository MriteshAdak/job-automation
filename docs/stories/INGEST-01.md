# INGEST-01 — Fetch controller

Status: **VERIFIED** · Planning date: **28 October 2026** · Completed: **28 October 2026** · Phase 0 · Scope: **INGEST-01 only**

Baseline: [IMPLEMENTATION_BLUEPRINT.md][blueprint], v1.0. References below use requirements (§2), contracts (§4), correctness rules (§5), component ownership (§6), integration gates (§7), implementation/handoff instructions (§8), and native Windows conventions (§9). This document orders future implementation work. It does not implement the controller, change prerequisites, or establish new test results.

## Repository evidence and scope

Read the blueprint, [README](../../README.md), [FND-01][fnd], [DATA-01][data], [SOURCE-01][source01], [SOURCE-02][source02], the SOURCE-02 stories, and [SOURCE-03-arbeitnow planning document][arbeitnow]. Inspected the current adapter/contracts/schemas, selection and request-policy code, manual adapters, raw capture, storage repositories/migrations, configuration, and relevant fake/consumer/storage tests. No applicable `AGENTS.md` was found in the repository or checked ancestor directories; the user-level `.codex/AGENTS.md` is empty. README and blueprint §§8–9 provide repository instructions.

The component directly covers **R02, R09, R16**: permitted acquisition with honest coverage, durable raw processing state, and bounded recoverable execution. Supporting constraints are **R03** (raw provenance and C05 mapping handoff), **R04** (preserve scoped identities and repeated observations, without canonical deduplication), **R14** (native Windows), and **R15** (safe access, credentials and untrusted data).

**Inputs → outputs:** caller-owned run UUID, checked C03 source selection, registered adapters, manual input descriptors where applicable, explicit controller options, clocks and storage capabilities → durable raw captures, C05 raw records and draft results/issues, per-source traversal checkpoints and C04 manifests, plus fetch-stage results for RUN-01. C06 normalization, C07 identity/availability and whole-run C15 aggregation remain downstream.

**Excluded:** provider HTTP/parsing implementations, registry/access-review redesign, prerequisite storage migrations, shared-contract redesign without its owner, normalization/quarantine policy, canonical identities/revisions, closure decisions, Salesforce/model calls, retention deletion/backups, production pipeline/import CLI, process-wide locking, scheduling and automatic generation. INGEST-01 exposes a callable service; RUN-01 owns commands, the worker lock, stage ordering and startup recovery. A test-only live smoke helper is not a second production CLI.

### What exists and what does not

| Evidence | Current state and implementation consequence |
|---|---|
| Direct dependencies DATA-01 and SOURCE-02 | Handoffs report VERIFIED. Their historical Windows/test results are upstream evidence only; they do not verify INGEST-01. |
| Provider-adapter handoffs | No `docs/components/SOURCE-03-*.md` or production provider adapter is present. Arbeitnow has seven **planned** stories, not an implemented/live-verified adapter. A concrete adapter is required only for live verification. Do not implement it here. |
| Package layout | `src/job_automation/ingestion/` does not yet exist. No fetch controller, cache, production fetch command or normalizer is present. |
| [Adapter protocol][interfaces] | Current signatures are `fetch_page(config, continuation=None) -> AdapterPage` and `draft_posting(raw) -> DraftResult`. The old tuple/`FetchOutcome` interface is obsolete. |
| [Auxiliary results][results] | Schema 1.0 `AdapterPage`, `Continuation`, `RecordIssue`, `DraftResult` exist. `AdapterPage` checks item/issue counts and exhausted-with-continuation, but permits other unsafe combinations, including exhaustion with `page_error` or `truncated`. |
| [C04/C05 contracts][postings] | Schema 1.0. C04 has one error, string cursors/identities, page count and response references. It has no attempt ledger, cache freshness, traversal ID, record-issue collection, or persistent manifest ID. C04 currently lacks semantic completeness validators. Its valid fixture even has `outcome=complete` with `cursor_out="page_2"`; that fixture is not an acceptable controller outcome. |
| [SOURCE-01 selection][selection] | `select_sources` rejects a mixed invalid selection atomically. Preserve that preflight behavior. Independent runtime failure after successful selection is a different concern. Detached models still contain mutable nested collections; freeze/deep-copy the execution snapshot. |
| [Request policy][policy-code] | Effective timeout defaults to 30 seconds, attempts to 1, backoff factor to 1 and cap to 30; spacing and max pages can be absent. Rate aliases resolve to spacing. There is no cache TTL, response-byte cap, total-request cap or source deadline in the effective model. C03 rejects unknown policy keys; do not insert new keys casually. |
| [Capture boundary][raw] | `RawCaptureSink.capture(bytes, identifier_hint)` returns reference/hash; `get(ref)` returns bytes or `None`. Only `InMemoryRawCaptureSink` implements it today. Production must receive a durable implementation. |
| [Filestore][filestore] | Raw files are named from sanitized provider/board/posting IDs and overwritten. Reading decodes text with replacement. This is not immutable exact-byte parent/page storage. Never reconstruct original bytes from `RawPosting.raw_payload`. |
| [Raw repository][raw-repository] | `save_raw_posting` rejects repeated `(provider, board_id, source_posting_id)`, including unchanged reruns. It cannot retain multiple observations. Missing payloads can read back as empty text. `save_manifest` allocates a new UUID every call, so finalization retries are not idempotent. |
| [Run ledger][run-repository] / [transactions][transactions] | Checkpoint storage exists, but individual repository methods use `with self.conn`. Do not assume wrapping several calls in `engine.transaction()` makes a page/records/checkpoint operation atomic; verify actual rollback with fault injection. DATA-01 must supply/confirm the required transaction boundary. |
| [Migrations][migrations] | Current code registers versions 1–3, including PROFILE-01 additions; DATA-01's older handoff reports only 1–2. Do not reserve or invent the next migration number in this plan. |
| Manual adapters | Existing text/CSV adapters accept an injected sink and use no network. Some failure branches reference nonexistent `ErrorCategory.STORAGE`; manual text treats any non-null continuation as exhausted. Manual drafting also uses instance metadata/caches. These are upstream gaps, not permission to repair SOURCE-02 here. Persist draft results and input/options snapshots for replay. |
| Existing fake tests | `ScriptedPaginatedFakeAdapter` is useful for scripted behavior, but its default draft is fabricated and some references are unresolved. Existing consumer tests simulate a manifest in memory; they are not durable controller verification. New controller fixtures must provide actual captured bytes and explicit drafts. |

Planning validation passed for nine ordered story headings, required story fields, local links, UTF-8, balanced code fences and PowerShell recipe syntax. These are document checks only; no application tests, live requests, environment repair or migrations were performed. The Arbeitnow plan reports an unavailable base Python behind `.venv/Scripts/python.exe`; verify the current environment before implementation checks rather than inheriting either that failure or earlier passing counts as current evidence.

## Contract and ownership decisions before business logic

These are proposed engineering choices, not new user facts or provider guarantees. S01 records the final decisions and closes the required owner handoffs. Existing schema 1.0 fields retain their meanings unless FND-01 approves an explicit migration/consumer plan under blueprint §8.

### Execution and persistence boundaries

- Use an explicit adapter factory/registration map supplied at composition time. Never import classes named by source data or use a test fake as a production fallback. The factory receives the checked source, durable sink, bounded request capability and input descriptor, as applicable; keep the two public adapter methods unchanged where possible.
- Add versioned **ingestion-local** records for controller options, source attempts, page receipts, cache entries, checkpoint state and fetch-stage results. Names and exact fields are frozen in S01. Do not overload C04 `error.details` as a success metadata store or invent extra C04 fields that the schema forbids.
- A page receipt links traversal/page/attempt identity, requested and returned continuation, source/config/scope/adapter versions, response references and hashes, C05 observation references, draft results/issues, cache origin, time and stop/error facts. Preserve safe response metadata and attempt errors separately from the one terminal error projected into C04.
- DATA-01 owns immutable byte publication, observation/receipt/cache persistence, atomic commit support and stable manifest finalization. INGEST-01 owns its `RawCaptureSink` bridge and orchestration against those capabilities. The interfaces are **required additions or confirmed capabilities**, not APIs claimed to exist today. Fake ports can unblock isolated tests; durable acceptance remains pending until the owner handoff exists.
- Persist original response bytes before parsing/mapping. Adapters perform the capture through the injected sink; the controller verifies and commits references, not a second serialization of the provider response. Keep parent response and derived row/envelope captures distinct. Link manual CSV rows to the parent page receipt without claiming that row JSON is an exact slice of CSV bytes.
- Keep source identity separate from observation identity and content hashes. One source tuple may have repeated or changed observations, including duplicates on one page. Replaying one committed page must not insert duplicate observations; a later run may record a new sighting of the same tuple. C07 canonical deduplication/revisions remain IDENTITY-01 work.
- Publication order is immutable files, then one database commit for the receipt/observations/draft results/issues and next checkpoint. No checkpoint may advance beyond committed evidence. Files left after a failed transaction are unreferenced evidence, not success; cleanup is OPS-01 work. Do not promise an atomic transaction across filesystem and SQLite or exactly-once network execution.

### Limits, retry and timeout semantics

Use SOURCE-01's effective policy and source restrictions without weakening them. Additional controller options initially enter through a typed callable argument, not unsupported C03 keys. Require finite positive page, request, response-byte and per-source elapsed-time budgets for automated execution; S01/D05 must select and document defaults before production wiring. A missing optional C03 `max_pages` must not mean unbounded execution. More restrictive caller/source caps win. Manual inputs retain separate finite file/record/page budgets and zero HTTP requests.

`max_attempts` includes the initial page attempt; attempts do not reset after restart. Each outbound request, including retries and allowed redirect hops, consumes the request budget and respects spacing. Page caps count logical page positions, not HTTP attempts. Per-provider/origin scheduling must cover source aliases sharing a quota; a different source key must not bypass the same rate restriction. No provider quota is inferred from example configuration or Arbeitnow's historical headers.

Retry only an explicitly recoverable operation in an eligible category, within attempts and all remaining budgets. Transient network/service errors and rate limits may qualify. Validation, missing configuration, authentication, permission and unsupported input do not. A capacity error can be marked recoverable by the shared taxonomy but must not trigger repeated downloads into a full disk; suspend acquisition and report pending work. Unexpected exceptions become safe visible failures, not arbitrary retries.

For failed attempt number `n` starting at 1, proposed local delay is `min(backoff_max_seconds, backoff_factor * 2 ** (n - 1))`. Inject clock/sleeper; no real sleeps in unit tests. The next request starts no earlier than spacing, backoff and a valid server retry hint permit. Parse bounded, allowlisted `Retry-After` seconds/HTTP-date metadata only when the adapter exposes it. A server wait longer than the remaining source budget stops/defer-marks that source; never truncate the server wait to the local backoff cap. Absence/malformed hints use the documented fallback.

Enforce timeouts at the actual transport, including connection/read/streaming/redirect handling, with the remaining monotonic source deadline propagated. A timer around synchronous `fetch_page`, an elapsed-time check after it returns, or timing out a future while its thread keeps fetching does not bound I/O. SOURCE-02/SOURCE-03 must expose an injected request/deadline capability or document an equivalent enforceable transport contract. Unsupported adapters cannot be advertised as bounded. Cancellation must release handles and prevent late writes. RUN-01 owns process-wide cancellation/locking; INGEST-01 consumes a cooperative cancellation signal.

### C04 completeness and counting rules

C04 describes a source/scope traversal, not the whole pipeline or job availability. Only emit a terminal C04 after the corresponding evidence is durably committed. Before finalization, use checkpoint/receipt state; C04 requires an end time and has no `running` outcome.

Proposed v1 projection: one authoritative final manifest per `(run_id, source_key, scope_id)` traversal; same-run continuation resumes that traversal. A deliberate fresh traversal uses a new caller-owned run ID. Store stable internal finalization identity through DATA-01; do not repeatedly call the current insert-only `save_manifest` and assume uniqueness.

| Situation | Required C04/result behavior |
|---|---|
| Valid traversal from its start, explicit terminal exhaustion, all pages/evidence committed, no truncation/page failure/blocking record loss | `complete`, `cursor_out=null`, no terminal error. A legitimate empty terminal page can be complete with zero observations. |
| Empty or short intermediate page with continuation | Continue. Record count is not termination evidence. |
| Cap, deadline, cancellation, continuation defect or exhausted retries after committed usable progress | `partial`; keep prior evidence and the safe retry/next cursor where known. A cap is not exhaustion. |
| Failure before any usable page/record progress | `failed`, retaining captured error responses/issues if available. A captured 403/HTML body alone is not usable progress. |
| Exhausted page also has `page_error` or `truncated` | Never complete. Error/truncation wins over exhaustion. Preserve valid items and classify partial/failed by durable usable progress. |
| Blocking record errors, including unidentified records, despite terminal exhaustion | Conservatively partial when usable records/pages remain; failed if all records are rejected with no usable progress. Record scan exhaustion separately. Warnings alone do not prevent completion. This protects v1 consumers from treating dropped identities as absent. |
| One fresh terminal page reached from an arbitrary resume cursor | Partial unless persisted, validated prefix evidence proves traversal from the beginning within the same coherent scope/input. A cursor alone is not that proof. |
| Unrevalidated prior-run cache reuse, even within local TTL, or mixed cached/fresh pages | Partial with a visible cache-reuse reason under v1. Preserve original observation times; no fresh inventory/last-seen claim. Current C04 cannot express freshness separately. |
| Successful `filtered_feed` or `search_results` traversal | May be complete as an execution, but retains its original inventory semantics. It cannot support disappearance inference. |
| Complete-board traversal | Potential evidence only for the same exact scope and reviewed coverage, with coherent fresh traversal evidence. INGEST-01 never closes jobs; IDENTITY-02 owns misses/grace/alternate-source decisions. |

For an interrupted mutable remote feed without a documented snapshot or freshness guarantee, use a fresh traversal or retain partial status; joining an old prefix to a new tail does not automatically prove complete-board coverage. Manual snapshots must match exact bytes/options. A changed input or scope invalidates the continuation and requires a new traversal, not silent fallback to page one under the old manifest.

Freeze the following count definitions in S01 with FND-01 consumers:

- `page_count`: distinct logical page positions with a returned `AdapterPage` consumed in the traversal, including an error-bearing page, counted once across retries. Include verified receipts restored within that traversal and explicitly labelled cache reuse; no response/exception-only attempts do not add a page. Store network requests, attempts, cache hits and committed successful pages as separate counters. The existing SOURCE-02 page-1-success/page-2-error example therefore remains two pages.
- `observed_posting_identities`: stable first-observation-order unique **exact provider posting ID strings**, scoped by the manifest's persisted C03 provider/board snapshot. Preserve leading zeros/case; do not concatenate tuple fields with ambiguous delimiters or replace IDs with hashes. C05 retains the full `SourceKey`; validate every item belongs to that provider/board before including it. Include identified raw observations even when drafting fails, while keeping the conservative partial result.
- `raw_response_refs`: ordered distinct resolvable parent response references, including safely captured error responses. Derived record references live in the page receipts/C05. Keep byte hashes and origin metadata in durable receipts; C04 only has reference strings.
- Raw observations, distinct source identities, accepted drafts, rejected records and issue counts are different units. `AdapterPage.record_count` equals `len(items)` and excludes records rejected before identity creation. Do not infer total encountered records from it. Reconcile record locators, not number of issues; an unknown remainder stays unknown. Never label these canonical-job counts.
- `cursor_in` is the logical traversal's original input; `cursor_out` is the next safely executable checkpoint token or the failed page input to retry. Encode with `Continuation.encode()` (`cont-v1:`). Null output on failure means no safe cursor, not completion; an initial-page retry is distinguished by checkpoint/error state. Keep tokens in protected state, not logs.

The page-count/cache and conservative completeness choices need a recorded producer/consumer agreement; do not silently reinterpret older stored C04 records. Legacy manifests lacking trusted freshness/prefix evidence must not gain eligibility for disappearance inference through a reader upgrade.

## Ordered implementation stories

Every story is **PLANNED**. Paths describe future owned files. In the lists below, `ingestion/` means `src/job_automation/ingestion/`. Prerequisite owner work is a dependency gate, not another component's implementation story hidden in INGEST-01.

| Order | Story | Depends on | Result |
|---|---|---|---|
| 1 | INGEST-01-S01 | DATA-01, SOURCE-02; transitive FND-01/SOURCE-01 | Frozen boundaries, semantics and prerequisite gates |
| 2 | INGEST-01-S02 | S01; DATA-01 durable evidence capabilities | Durable capture and page-commit integration |
| 3 | INGEST-01-S03 | S01–S02; current SOURCE-01/02 | Checked one-page execution and C05 handoff |
| 4 | INGEST-01-S04 | S01–S03; enforceable adapter transport boundary | Request budgets, retries, timeouts and safe errors |
| 5 | INGEST-01-S05 | S02–S04; durable checkpoint transaction | Bounded pagination and resumable evidence |
| 6 | INGEST-01-S06 | S02–S05; DATA-01 cache metadata capability | Safe persistent cache reuse/invalidation |
| 7 | INGEST-01-S07 | S01–S06; stable manifest finalization | Honest durable C04 projection |
| 8 | INGEST-01-S08 | S03–S07 | Independent runtime source outcomes |
| 9 | INGEST-01-S09 | S01–S08; SOURCE-03 only for live checks | Separate verification evidence and handoff |

### INGEST-01-S01 — Freeze the controller boundary and dependency decisions

**Objective/references.** Make the implementation possible without silently redesigning prerequisites. R02/R09/R16; supporting R03/R14/R15; C03–C05, adapter/auxiliary contracts; blueprint §§4–6/INGEST-01, 8–9; DATA-01 guidance and SOURCE-02 D03/D04/D09.

**Dependencies.** DATA-01/SOURCE-02 code and handoffs; FND-01/SOURCE-01 transitive contracts. No concrete provider needed.

**Owned files.** Proposed `ingestion/models.py`, `ingestion/ports.py`, `ingestion/__init__.py`; initial `docs/components/INGEST-01.md`; `tests/ingestion/test_contract_boundary.py`, `tests/fixtures/ingestion/README.md`. This story owns local types/specification only; no controller loop, shared schemas or storage migration.

**Inputs → outputs.** Current contracts and gaps → versioned controller input/result/receipt/checkpoint/cache shapes, exact port signatures, recorded decisions and a dependency readiness matrix.

**Tasks.**

1. Freeze service inputs: run ID, successful checked selection, adapter factories, optional input descriptors, explicit limits/cache options, storage ports, UTC/monotonic clocks and cancellation. Freeze per-source outputs and safe fetch-stage counters for RUN-01 without producing final C15.
2. Specify required immutable byte storage, page commit, observation replay, cache metadata and stable finalization operations with DATA-01. Include duplicate tuple, file/DB failure and nested transaction scenarios. Mark each capability available, pending or demonstrated only by fake.
3. Agree request instrumentation/deadline/redirect accounting with SOURCE-02 and each future SOURCE-03 consumer. Capture safe retry hints through a documented result/attempt boundary, not provider-specific dictionary guesses in the controller.
4. Record C04 projection/count/identity/freshness rules above and dependency decisions D01–D10 below. Keep shared contract/schema work with FND-01. If incompatible, require a recorded blueprint decision and reader/migration plan before dependent implementation.
5. Select finite controller defaults/maximums, units, cache TTL/mode and budget precedence. Proposed cache default is disabled (`ttl_seconds=0`); no provider-specific numbers are invented. Reject booleans, NaN/infinity, negative caps and unknown options.
6. Document owner boundaries and incomplete prerequisites. Do not mark fake-backed integration as durable completion or repair manual adapters as incidental controller work.

**Acceptance examples.** A reviewer can trace every field from C03/adapter through a page receipt to C04. An unsupported transport cannot be registered as bounded. Passing `cache_ttl` inside current C03 remains invalid; a typed ingestion option is used instead. Every missing storage capability has a named owner and dependent story.

**Tests.** Local model round trips/version rejection; budget validation; unsupported adapter capability; current public signature invocation. No network, database migration or new provider test.

**Native Windows.** Import new modules using the explicit native interpreter; assert import/construction alone does not create runtime directories or connections. Validate option/path handling from a different working directory.

**Migration/configuration and handoff.** Record current C03/C04/C05 and auxiliary versions as 1.0; document local record versions separately. Any shared schema, config or database changes are prerequisite-owner requests. S02/S04 must not proceed with unsupported production assumptions.

### INGEST-01-S02 — Integrate immutable capture and durable page commits

**Objective/references.** Preserve original inputs and successful prior observations across reruns/failures. R09/R16; supporting R03/R04/R14/R15; C04/C05; blueprint §§3–5; DATA-01 and SOURCE-02 D04/D09.

**Dependencies.** S01; DATA-01 D02/D03/D07 capabilities delivered or explicitly pending. Pure bridge tests may use fakes while those gates are open; real persistence acceptance may not.

**Owned files.** Proposed `ingestion/capture.py`, `ingestion/persistence.py`; `tests/ingestion/test_capture.py`, `test_page_commit.py`, `test_observation_replay.py`; synthetic bytes under `tests/fixtures/ingestion/raw/`. No direct SQL, migration or replacement storage engine under `ingestion/`.

**Inputs → outputs.** Adapter-captured parent/record bytes and page evidence → immutable resolvable references with hashes, durable C05/draft/issue observations and an atomic next checkpoint.

**Tasks.**

1. Implement `RawCaptureSink` against the approved DATA-01 byte capability. Use opaque safe names/content keys under configured `raw_dir`; provider strings and `identifier_hint` never authorize paths. Verify exact bytes/hash on reuse and read; reject traversal/out-of-root references and hash mismatch.
2. Keep bytes before decoding, including BOM, CRLF, non-UTF-8/error bodies. Text is not a byte reconstruction source. Do not use the current overwriting `save_raw_payload` or replacement-decoding reader to claim immutable evidence.
3. Commit ordered page receipts, observation references, C05 objects, `DraftResult`/issues and continuation atomically through the owner API. Do not expose a persisted-success result before commit. Preserve all available raw evidence when mapping fails.
4. Use stable traversal/page/observation identities for retries, separate from `(provider, board_id, source_posting_id)`. Preserve changed content at the same source key and distinct duplicate occurrences. Do not suppress every `DuplicateKeyError` as an unchanged posting.
5. Persist mapping/input context or already computed draft results so reloading does not depend on the original adapter instance's cache. Parent hashes, row locators and attribution must remain resolvable after reopening.
6. Surface permission/capacity/corruption failures safely. File publication without a database commit leaves an inspectable orphan and the old checkpoint. Missing/tampered bytes never return an invented empty payload or durable-success flag.

**Acceptance examples.** Two runs see ID `"0007"` with different bytes: one source identity, two retained observations and readable old/new evidence. Replaying the same committed page produces no additional logical observations. A failure between observation writes and checkpoint commit leaves neither advanced checkpoint nor partial committed page. A captured malformed response remains readable even with no C05 items.

**Tests.** Byte/hash round trips; multiple parent/derived records; same tuple/same and changed content; duplicate occurrences; sink/DB fault injection before/after each publication boundary; missing/corrupt file; reopen through a new storage/controller instance. Real DATA-01 integration tests must demonstrate rollback, not only mocked calls.

**Native Windows.** Use `pathlib.Path` and explicit absolute data roots with spaces/umlauts, reserved-character identifier hints and changed CWD. Verify handles close on success/failure and captured files can be reopened/renamed after shutdown. Simulate denied writes/full disk without exhausting the real disk.

**Migration/configuration and handoff.** Consume the DATA-01 migration/version returned by its handoff; do not hardcode a planned migration number. Retain raw data outside tracked source. Retention cleanup and backup policy stay OPS-01 responsibilities.

### INGEST-01-S03 — Execute checked adapters and retain C05 results

**Objective/references.** Execute a page through the current interface with explicit source and record boundaries. R02/R09; supporting R03/R15; C03/C05, `AdapterPage`/`DraftResult`; blueprint §§4–6; SOURCE-01 D08 and SOURCE-02 D01/D02/D08.

**Dependencies.** S01–S02; current SOURCE-01 selection and SOURCE-02 adapters. Upstream manual failure/replay gaps remain tracked under D08.

**Owned files.** Proposed `ingestion/execution.py`, adapter factory wiring in `ingestion/ports.py`; `tests/ingestion/test_execution.py`, `test_manual_integration.py`; explicit fake drafts/capture fixtures. No changes to provider parsers or source registry.

**Inputs → outputs.** Checked source snapshot, adapter/input binding and one continuation → validated page evidence, ordered durable raw/draft results and safe record/page failures.

**Tasks.**

1. Consume the actual `SourceSelectionResult`; invalid selections execute nothing and produce preflight diagnostics, not fictitious source fetches. Empty valid selection is an explicit no-op. Revalidate readiness/frozen config at the execution boundary where needed; do not weaken access/attribution restrictions.
2. Bind only explicitly registered compatible adapters to their exact source/provider/board/config snapshot and sink. Missing adapters become visible source execution failures after valid registry selection. No class import, network call or manual URL fetch is triggered by untrusted text.
3. Invoke `fetch_page` using the current signature; validate result/schema/version/source identities and cross-field states. A foreign-source item or malformed result cannot contribute trusted inventory evidence.
4. Call `draft_posting` for each available valid raw record, retaining raw records before interpreting draft success. Persist both accepted drafts and blocking issues; warning-only missing fields stay unknown for INGEST-02. Record a mapping exception for that record and continue independent neighbors where raw boundaries are trustworthy.
5. Reconcile issues surfaced in both page and draft results by stable input/record/code/field identity; do not double-count rejected records or erase distinct issues. Retain parent-linked issues with no source ID. Never run normalization, HTML cleaning, job deduplication or quarantine policy here.
6. Wrap expected failures with existing `ClassifiedError` categories and allowlisted codes. Catch unexpected ordinary adapter exceptions at the source boundary without logging raw exception/config/body content; preserve debugging references securely. Do not swallow process cancellation as ordinary success.

**Acceptance examples.** Disabled+valid requested sources yield zero adapter calls because selection is atomic. After valid selection, an unregistered adapter is reported explicitly. Three records with one mapping rejection retain all three raw records, two drafts and one rejected-record count. A manual URL containing hostile job text causes zero network calls.

**Tests.** Actual selection service plus fake factories; deep-copy/config mutation; foreign provider/board; malformed page/draft; duplicate issue reporting; manual text and paged CSV through the real adapters and durable sink. Use explicit drafts rather than the scripted fake's fabricated default. Include missing manual input to expose D08; do not describe that upstream branch as passing until resolved.

**Native Windows.** Import from UTF-8 BOM/CRLF text/CSV files in a Unicode directory with explicit input bases. Change CWD and reopen files. A network guard applies to all manual cases.

**Migration/configuration and handoff.** No source enabled by default, no invented manual-origin URL, no new CLI. Document callable composition and the exact C05/draft-result handoff to INGEST-02/RUN-01.

### INGEST-01-S04 — Enforce request limits, bounded retries and timeouts

**Objective/references.** Bound external work and make rate/network failures inspectable. R02/R16; supporting R14/R15; C03 request policy, error taxonomy, page/attempt evidence; blueprint §§4–6; SOURCE-01 D05 and Arbeitnow U03/U08.

**Dependencies.** S01–S03; D01 enforceable request/deadline boundary from adapter owners; D05 finite options and scheduling-key decision. No production provider is needed for fake transport verification.

**Owned files.** Proposed `ingestion/request_control.py`, `ingestion/retry.py`, `ingestion/errors.py`; `tests/ingestion/test_request_limits.py`, `test_retries.py`, `test_timeouts.py`, `test_safe_diagnostics.py`; fake clock/sleeper/request executor under `tests/fakes/`.

**Inputs → outputs.** Effective request policy, finite budgets, current checkpoint and classified attempt outcome → permitted single attempt, bounded delay, or visible stop/defer result with counters and raw evidence references.

**Tasks.**

1. Implement the limits/retry rules above with monotonic deadlines and injected UTC timestamps. Count every physical outbound request, including redirect hops, while keeping logical pages and attempts distinct. Disable hidden transport retries or require their explicit accounting.
2. Share spacing/cooldown state for the agreed provider/origin quota key. Preserve remaining budget/attempt history across resume; do not grant a fresh retry allowance merely by reconstructing the controller. Apply the stricter reviewed source/caller limits.
3. Retry the same page input without advancing checkpoints. Retain failed response evidence and attempt diagnostics. Commit successful page data once; where a failed page already carries records, preserve attempt observations but do not treat that as a committed successful traversal step.
4. Implement backoff, safe retry-hint parsing and deadline-aware waiting. Bound wait as well as requests. A long server wait defers that source without blocking unrelated origins indefinitely.
5. Pass remaining deadline/timeout/body limits to the transport capability; stop reads and release resources on expiry. If an adapter cannot meet the contract, return a capability/configuration failure rather than claim a cancellable request. Manual inputs do not acquire an HTTP transport.
6. Handle validation/auth/permission as terminal, capacity as acquisition-stopping, and unexpected exceptions as safe failures. Do not implement retry loops inside provider adapters or retry draft mapping errors with another download.

**Acceptance examples.** `max_attempts=3` with two transient failures then success makes exactly three page attempts; three failures never make a fourth. With spacing 2 seconds and first backoff 1 second, the next request waits at least 2 seconds. A 120-second server wait with 30 seconds remaining stops the source. A two-request budget permits one failed GET plus one retry, with no request for the next page. A slow streaming body reaches the deadline and closes; no background download continues.

**Tests.** Fake-time exact call/delay assertions; 429/5xx/timeouts versus 401/403/schema errors; both retry-hint forms and invalid hints; spacing across aliases; redirects consuming budget; request/byte/time cap precedence; resumed attempts; cancellation; no real sleeps/network. Add a bounded loopback/native transport check only when an actual transport capability exists; a fake does not prove real timeout enforcement.

**Native Windows.** Verify monotonic timing independent of wall-clock/DST shifts, transport handle closure and cancellation under the native interpreter. Avoid Unix signals or a thread timeout that leaves requests running. Record actual loopback/transport checks separately from scripted outcomes.

**Migration/configuration and handoff.** Effective C03 fields are consumed unchanged. Persist attempt/cooldown state through agreed ports. Any extension for retry metadata/transport capability is owned and versioned by the shared/provider owner before this story's production acceptance.

### INGEST-01-S05 — Traverse pages and checkpoint safe resumption

**Objective/references.** Finish only on explicit trustworthy exhaustion and resume without losing evidence. R02/R09/R16; C03–C05 and `Continuation`; blueprint §§4–6; SOURCE-02 D03, SOURCE-03 pagination boundary.

**Dependencies.** S02–S04; atomic page/checkpoint support and D04 prefix/freshness agreement.

**Owned files.** Proposed `ingestion/pagination.py`, `ingestion/checkpoints.py`; `tests/ingestion/test_pagination.py`, `test_resume.py`, `test_crash_boundaries.py`; scripted page sequences under `tests/fixtures/ingestion/pages/`.

**Inputs → outputs.** Source/adapter snapshot, optional validated checkpoint and bounded page executor → durable ordered page history, next continuation and explicit exhaustion/stop facts.

**Tasks.**

1. Start at `None` unless resuming an explicit stored traversal. Validate supported continuation version/kind/source/scope/adapter and required manual input/options hashes before fetching. Existing helpers allow some missing hashes; enforce the agreed boundary rather than assuming decoding grants authority.
2. Validate returned `continuation_in` against the requested input and `continuation_out` against the same binding. Detect missing progress, immediate repeats and longer cycles with a bounded visited-token set. Token values are opaque; no numeric ordering assumptions outside provider adapters.
3. Continue through empty/short intermediate pages. Stop on explicit exhaustion only after error/truncation checks; non-exhausted/no-next is a visible contract failure. Enforce page, request, byte and elapsed budgets without synthesizing a terminal page.
4. Persist every safe page before advancing. On page-2 failure retain page 1 and retry page 2's input, never skip to its purported output. Invalid/cyclic next tokens are not safe resume cursors. Preserve references/errors even when there is no safe continuation.
5. Validate checkpoint schema/config/scope/adapter/input/mapping compatibility and all referenced evidence on reopen. Restore consumed attempts/pages and visited tokens. Replaying after an ambiguous page commit uses stable IDs and reconciles before re-execution.
6. Expose restartable source work to RUN-01. Do not implement global startup recovery or worker locks. A changed manual snapshot requires a new traversal; a mutable feed prefix lacking freshness evidence must restart or remain partial under D04.

**Acceptance examples.** Page 1 has two records/`p2`, page 2 has zero/`p3`, page 3 has one/exhausted: three records and three pages. Stop at page cap 2: retain two records and `p3`, never complete. `p1→p2→p1` stops with a cycle error. Crash after page commit/before return resumes from the committed next token with no duplicate logical observations. Starting at `p3` without prefix evidence cannot yield complete inventory.

**Tests.** Empty start/terminal/intermediate; exact-cap terminal versus cap with next; truncated page; exhausted+error; missing/mismatched token; long cycle; repeated records; changed source/options/input; malformed/oversized token; failure before/after commit; fresh process reload. Fault tests assert actual durable rows/files/checkpoints, not just call order.

**Native Windows.** Use a child native Python process to simulate interruption after a committed checkpoint, reopen with a new connection, and verify SQLite/file handles release. Keep subprocesses noninteractive; no WSL, Unix signals or global process killing.

**Migration/configuration and handoff.** Version checkpoint payloads separately from C04 cursor encoding. Define behavior for unsupported/legacy checkpoint versions; do not silently resume them. Schema/storage changes remain DATA-01 dependencies.

### INGEST-01-S06 — Cache captured pages without fabricating fresh inventory

**Objective/references.** Avoid unnecessary requests while keeping provenance, access policy and completeness honest. R02/R09/R16; supporting R15; C03–C05; blueprint §§4–6; Arbeitnow U03/U06 and D04/D06 below.

**Dependencies.** S02–S05; DATA-01 durable cache metadata; S01 freshness/key/version decisions. Conditional HTTP support is not present and is not assumed.

**Owned files.** Proposed `ingestion/cache.py`; `tests/ingestion/test_cache.py`, `test_cache_invalidation.py`, `test_cache_completeness.py`; synthetic cached receipt fixtures. No provider parser or C03 policy redesign.

**Inputs → outputs.** Checked source/request/input fingerprints, cache policy, current time and committed receipts → verified reusable page/draft evidence or a cache miss followed by bounded acquisition.

**Tasks.**

1. Implement disabled and bounded TTL-reuse modes; default disabled. TTL is a local reuse policy, not proof of current provider inventory. Never cache an error/truncated/incomplete page as a successful reusable page; never treat an absent cache file as empty results.
2. Key by version, exact provider/board, source/config and scope, adapter/mapping version, full request/page token and representation-affecting parameters/options. Include manual byte/input metadata hashes and safe authorization partition identifiers where relevant. `scope_id` alone omits pagination/page-size/transport details and is insufficient. Do not write secrets into keys/logs.
3. Store references/hashes, capture and validation times, provenance, page results and persisted draft results/issues. Check all references/hashes and source readiness before reuse. Cache hits require no network or retry wait and consume logical traversal budget but zero network-request budget.
4. Invalidate on expiry, missing/corrupt evidence, changed request/input/adapter/mapping/access restrictions or incompatible schema. Keep prior evidence for audit; cache invalidation is not retention deletion. Report cache miss reason safely.
5. Preserve original fetch/observation timestamps and cache origin; project prior-run reuse as partial under C04 v1 even if TTL-valid. No stale-on-error fallback to complete. Mixed fresh/cached traversal also remains partial absent an approved freshness contract.
6. Do not send conditional requests unless a later SOURCE-03 capability supports validator-aware response replay. Under the initial plan an unexpected 304 is explicit unsupported/error, never empty success. Future conditional support must bind a validator to the exact cached representation and count the validation request; it cannot make a page validator into whole-board snapshot evidence.

**Acceptance examples.** A second identical request within TTL uses verified bytes/drafts with zero adapter/network calls, original timestamps and a cache-origin result. Changing page size or CSV bytes misses the cache even when scope is unchanged. A cached page with next token remains nonterminal. A cached empty complete-board page does not provide a new disappearance observation. A failed request cannot turn an expired cache entry into a successful fresh fetch.

**Tests.** Hit/miss/disabled/expiry boundaries with fake time; key isolation across sources/boards/filters/pages/versions/authorization partitions; body tampering; forbidden access after caching; stale-on-error; mixed freshness; restart persistence; no real networking. Test 304 rejection explicitly; mark future conditional cases pending until the provider capability exists.

**Native Windows.** Reopen cache after process exit under a Unicode data root, preserve raw bytes, verify atomic publication/handle release via DATA-01, and test changed CWD. Cache paths are filesystem paths; URLs are never path-normalized.

**Migration/configuration and handoff.** Controller cache options remain separate from current C03. Required durable cache tables/indexes belong to DATA-01. Cache retention and source copying restrictions remain explicit dependencies; cache enablement cannot override them.

### INGEST-01-S07 — Produce honest, idempotent C04 manifests

**Objective/references.** Make completeness an auditable result of committed evidence. R02/R09/R16; supporting R04; C03/C04/C05; blueprint §§4–6/INGEST-01 and IDENTITY-02 boundary; SOURCE-01 D07 and SOURCE-02 D03.

**Dependencies.** S01–S06; D04/D07 agreement on projection and stable manifest finalization. No availability service implementation.

**Owned files.** Proposed `ingestion/manifests.py`; `tests/ingestion/test_manifests.py`, `test_manifest_finalization.py`, `test_inventory_boundary.py`; golden C04 examples under `tests/fixtures/ingestion/manifests/`. Existing shared fixture/schema corrections are FND-01-owned prerequisites, not silently edited here.

**Inputs → outputs.** Committed page/attempt/cache/record evidence and source snapshot → validated terminal C04 plus linked detailed fetch result, persisted once per authoritative traversal.

**Tasks.**

1. Implement the outcome/identity/count rules above as pure projection plus explicit persistence. Initialize incomplete state; never initialize the traversal to complete and rely on every error path remembering to undo it.
2. Populate every C04 field from evidence: caller run ID, exact source/scope, UTC start/end, encoded safe cursors, page units, parent response references, unique exact posting IDs, preserved inventory semantics and terminal error. Validate ordering/time/reference consistency in the controller even where the schema does not.
3. Preserve blocking record errors and exhaustion separately. Choose one deterministic terminal/summary `ClassifiedError` with a safe reason code; retain the full attempt/issue history in linked receipts. Recovered transient errors do not force failure if a coherent fresh traversal ultimately succeeds within bounds.
4. Make finalization retry-safe through DATA-01's stable operation. Reconcile an ambiguous commit by reading authoritative state before writing again. No duplicate or contradictory authoritative manifests for a run/source/scope.
5. Expose complete execution versus inventory semantics clearly to downstream readers. Provide examples for complete search/feed, partial complete-board, cache reuse and unsupported resume. Do not update last-seen/closed fields or implement miss/grace rules.
6. If manifest persistence fails, return a durable-state failure to the caller and retain the checkpoint for reconciliation; do not return a fictitious stored C04 or hide the problem behind an in-memory success.

**Acceptance examples.** Fresh empty terminal inventory is complete; timeout before the first usable response is failed; success then timeout is partial with prior IDs/refs retained. Exhausted+truncated remains partial/failed. A completed ranked search remains `search_results`. Two retries of finalization return the same authoritative record. Two issues on one rejected record count once, and identified rejected records still appear among observed source IDs.

**Tests.** Table-driven outcome matrix including all rows above; safe cursor selection; schema/serialization round trip; page/attempt/cache count distinctions; duplicate IDs/leading zeros/board isolation; finalization crash/retry; legacy C04 acceptance constraints. Include downstream boundary assertions that partial/failed/feed/search/cache-only results cannot authorize disappearance; do not implement IDENTITY-02.

**Native Windows.** Serialize/read golden manifests as UTF-8 with UTC offsets, reopen the database after finalization and compare exact identity strings and continuation encodings across process restarts.

**Migration/configuration and handoff.** C04 stays schema 1.0 only if the agreed conservative projection is compatible; otherwise stop at the FND-01 decision gate. Record how older manifests are distinguished and how DATA-01 enforces finalization identity. Publish the exact reader contract for IDENTITY-02/RUN-01.

### INGEST-01-S08 — Isolate independent source failures

**Objective/references.** Preserve successful sources when another fails, without bypassing selection or global storage safety. R02/R09/R16; C03/C04/C05 and fetch-stage result; blueprint §6/INGEST-01 completion criterion.

**Dependencies.** S03–S07; caller-owned run entry and single-worker serialization. No RUN-01 implementation required; tests create a run through DATA-01 setup.

**Owned files.** Proposed `ingestion/controller.py`, public callable exports; `tests/ingestion/test_source_isolation.py`, `test_fetch_stage_results.py`, `test_controller_integration.py`. No production CLI or C15 finalization changes.

**Inputs → outputs.** Valid selected sources/factories and a run UUID → independent durable source manifests/C05 outputs, safe failed/pending source results and documented fetch-stage counters.

**Tasks.**

1. Execute sequentially initially, with per-source contexts, deadlines, cursors, counters and transactions. Keep shared provider rate controls where required. No all-sources database transaction that rolls back prior successes.
2. On ordinary source network/auth/schema/mapping/adapter failure, finalize that source honestly and continue other independently runnable sources. A deferred cooldown ends that source's current work rather than sleeping beyond its deadline; unrelated quota domains may proceed.
3. Keep registry preflight atomic: an invalid requested selection yields zero executions. Distinguish this from a factory/runtime failure after valid selection. Do not fabricate C04 scopes for unconfigured sources.
4. Distinguish source-local failure from shared disk/database failure or caller cancellation. Stop new acquisitions when evidence cannot be persisted; retain committed successes and expose unstarted sources as pending/not attempted. Never pretend a manifest persisted while the database is unavailable.
5. Return deterministic per-source ordering and explicitly labelled fetch-stage counts, including attempted/completed/partial/failed/not-attempted sources, raw observations, unique scoped identities, drafts/issues and requests. RUN-01 owns the whole-run status and C15 canonical counts.
6. Keep production factories free of test imports. No fallback to another provider, scraping, paid endpoint or model after an error.

**Acceptance examples.** Sources A/B/C pass preflight; A stores two pages, B fails on 403, C stores an empty terminal page. A/C results survive, B is failed and the caller sees mixed fetch-stage results. If A fails on its second page, its first page survives and C still runs. If the shared disk fails after A commits, A remains, later work is pending and no successful durable manifests are invented.

**Tests.** Fail first/middle/last source; one source with partial pagination; provider-shared cooldown versus independent origin; source initialization exception; all fail; empty selection; atomic preflight rejection; shared storage failure; cancellation and restart. Use real SOURCE-01 and DATA-01 with several fake adapters, plus manual adapters; fail closed on real network access.

**Native Windows.** Run the multi-source service against a temporary absolute data directory, close/reopen it and verify each source's manifest and payloads independently. Show no runtime artifacts enter the repository and no background worker survives the call.

**Migration/configuration and handoff.** Caller supplies the existing run ID/entry. No new run CLI, global recovery loop or scheduler. Publish the result API and pending-source semantics for RUN-01.

### INGEST-01-S09 — Verify the component and publish its handoff

**Objective/references.** Demonstrate declared controller acceptance and distinguish offline/durable/live evidence. R02/R09/R16 and R14/R15; blueprint §§6/INGEST-01, 7–9.

**Dependencies.** S01–S08 and required prerequisite decisions closed for production paths. SOURCE-03 is required only for the separate live lane; its absence does not block fake-adapter verification.

**Owned files.** `tests/ingestion/test_windows_paths.py`, `test_windows_restart.py`, focused integration additions; proposed `tests/manual/ingest_smoke.py`; fixture README; final `docs/components/INGEST-01.md`; concise callable/verification documentation in `README.md` if needed.

**Inputs → outputs.** Implemented controller and dependency versions → separate unit/contract, fake-adapter, real-storage/manual, native Windows and live-source evidence, limitations and downstream handoff.

**Tasks.**

1. Run the verification matrix/recipe below. Record actual interpreter/dependency/OS versions and command outcomes. If environment setup is broken, record pending verification and route setup repair appropriately; do not copy historical counts into new results.
2. Verify controller fixtures have resolvable bytes/hashes and explicit drafts; keep network denied by default. Real DATA-01 persistence and actual manual adapters are separate evidence from a fake storage port or fake adapter.
3. Exercise process interruption, page/manifest commit ambiguity, cache integrity, late-page failure, bounded attempts and independent sources. Run affected existing contract/source/storage tests and one full regression run after focused checks pass.
4. If shared contracts were changed by their owner, export schemas to a temporary directory and compare semantically; document version/reader migrations. JSON parse success alone is not contract parity.
5. Run the separate bounded live lane only after an actual adapter handoff and reviewed local source configuration exist. Keep live calls out of pytest/default imports; report pending honestly when dependencies/access are unavailable.
6. Publish the handoff checklist and the actual declared acceptance status. VERIFIED requires the claimed component behavior to be demonstrated, including real durable integration; fake-only storage or unproven timeout enforcement stays pending. Live pending does not imply fake failure or G1 completion.

**Acceptance examples.** The handoff shows capped pagination is partial and A's success survives B's failure, with files/manifests readable after restart. It separately names offline results, Windows results and provider smoke status. No G1, Salesforce, closure or overall Phase 0 claim follows from controller tests.

**Tests/native Windows.** Run the explicit recipe and case matrix below after proposed files exist. Manual import tests use no external service. Native transport timeout tests, if implemented, are labelled loopback rather than live-provider evidence.

**Migration/configuration and handoff.** Document exact owner migration/contract versions, chosen defaults, remaining decisions, callable API and ownership. No live source is enabled in tracked configuration and no prerequisite repair is bundled into this story.

## Verification matrix: offline and live evidence are separate

All examples above are synthetic. Use `.invalid` source/listing URLs, non-sensitive text and fake time in default tests. Real-looking URLs in allowlist tests must be intercepted. No test relies on real provider quotas, response ordering or current internet availability.

| Lane | Evidence required | Main stories |
|---|---|---|
| Unit/contract, no I/O | Option/result versions, page/count/outcome tables, cursor/cache key semantics, retry schedule and safe diagnostics | S01, S04–S07 |
| Fake-adapter integration | Actual controller with scripted pages/failures, real selection, captured fixture bytes and explicit draft results; zero network | S03–S08 |
| Durable local integration | Real DATA-01 sink/repositories, immutable bytes, repeated identities, atomic page commit, idempotent manifest, fresh-process reopen | S02, S05–S08 |
| Actual manual adapters | Text and CSV through the controller, malformed neighbors, BOM/CRLF, changed snapshots, no URL fetching | S03, S05, S08 |
| Native Windows | Explicit interpreter, paths with spaces/non-ASCII, changed CWD, closed handles, process restart, actual timeout capability where available | S02–S09 |
| Live-source verification | An implemented SOURCE-03 adapter through the real controller, permitted bounded fetch and durable evidence; actual result recorded | S09 only |

Passing a fake request executor proves retry decisions, not real timeout cancellation or provider compatibility. Passing a fake storage port proves orchestration decisions, not durable commit/recovery. Keep those distinctions in test names and the handoff.

### Native PowerShell recipe

These are **future implementation checks**, not commands/results from this planning task. Run from the repository root after the named tests and prerequisite capabilities exist. Runtime/test destinations are temporary and outside tracked source. Do not assume an activated shell, WSL, Docker, Bash, Word or any paid service.

```powershell
$ingest01Repo = (Get-Location).Path
$ingest01Python = Join-Path $ingest01Repo '.venv\Scripts\python.exe'
$ingest01Tests = Join-Path $ingest01Repo 'tests'
$ingest01ComponentTests = Join-Path $ingest01Tests 'ingestion'
$ingest01Contracts = Join-Path $ingest01Tests 'contracts'
$ingest01Sources = Join-Path $ingest01Tests 'sources'
$ingest01Storage = Join-Path $ingest01Tests 'storage'
$ingest01WindowsPaths = Join-Path $ingest01ComponentTests 'test_windows_paths.py'
$ingest01WindowsRestart = Join-Path $ingest01ComponentTests 'test_windows_restart.py'
$ingest01TempRoot = Join-Path $env:TEMP ('Job Automation Prüfung ä INGEST-01 ' + [guid]::NewGuid().ToString())

if (-not (Test-Path -LiteralPath $ingest01Python)) { throw 'Native Python environment is missing.' }
& $ingest01Python -c "import platform, sys; from zoneinfo import ZoneInfo; print(platform.platform()); print(sys.version); print(ZoneInfo('Europe/Berlin'))"
if ($LASTEXITCODE -ne 0) { throw 'Native Python environment is not usable.' }
& $ingest01Python -m pip show pydantic pytest tzdata
if ($LASTEXITCODE -ne 0) { throw 'Required package inspection failed.' }

& $ingest01Python -m pytest $ingest01ComponentTests $ingest01Contracts $ingest01Sources $ingest01Storage
if ($LASTEXITCODE -ne 0) { throw 'Focused checks failed; investigate before continuing.' }

New-Item -ItemType Directory -Path $ingest01TempRoot | Out-Null
$ingest01WindowsExit = $null
Push-Location $ingest01TempRoot
try {
    & $ingest01Python -m pytest $ingest01WindowsPaths $ingest01WindowsRestart --basetemp (Join-Path $ingest01TempRoot 'Daten Größe')
    $ingest01WindowsExit = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($ingest01WindowsExit -ne 0) { throw 'Native Windows path/restart checks failed.' }

& $ingest01Python -m pytest $ingest01Tests
if ($LASTEXITCODE -ne 0) { throw 'Regression checks failed.' }
```

The Windows tests must invoke actual controller/storage APIs using absolute configured paths, not merely assert that a path string contains an umlaut. Include bytes/hash checks after close/reopen, source IDs unsafe as filenames, changed CWD, missing/corrupt cached files, simulated permissions/capacity failures, interruption after commit and resume through a new process. Use native UTC timestamps with monotonic deadlines independent of display timezone. Keep tokens, bodies and credentials out of captured logs. Record added transport-package versions if any; dependency declarations presently contain ranges, not a lock file.

### Live-source verification plan — independent, optional until prerequisites exist

Live verification is **pending in this repository snapshot** because there is no implemented SOURCE-03 adapter/handoff. This planning task does not fetch any feed or authorize ongoing collection.

1. Read the eventual provider handoff and current SOURCE-01 review for the intended capture/retention use. Require an explicitly enabled local source, supported adapter/transport, reviewed attribution, absolute runtime destination, usable native interpreter and real durable sink. Keep tracked examples disabled. If any gate is missing, record the reason and leave live pending; do not implement prerequisites or switch to scraping.
2. Invoke the controller through an opt-in smoke helper with explicit source/registry/data paths and finite page/request/elapsed/body limits. No default pytest discovery, background polling, Salesforce writes or normalization. Prove request limits apply to the actual transport, not just the number of controller calls.
3. If Arbeitnow is the eventual source, use the more restrictive of its then-current handoff/review and the existing planning smoke envelope: one GET by default, at most two total HTTP requests including redirects, one attempt per page, sequential requests at least 60 seconds apart, 30-second request bound and 10 MiB response cap. These are proposed local smoke limits from the plan, not current provider quotas. Stop on a longer server wait, denial, challenge, schema drift or unsafe redirect. Reconfirm the plan with the implemented adapter before use.
4. Record UTC time, source/scope/versions, real request count, safe status/hint metadata, byte hashes/references, raw/draft/issue counts, continuation, effective limits and the durable C04. If another next page remains at the cap, the manifest is partial. For Arbeitnow preserve `filtered_feed`; two pages never establish complete-board coverage.
5. Close/reopen storage and resolve the captured evidence. If cache verification is included, reuse the same permitted response without another request, prove original timestamps and cache-origin partial semantics. Do not force real throttling/timeouts or deliberately break a provider to test failure paths; those belong to fakes/loopback tests.
6. Report live result as passed within the stated bounded scope, failed with evidence, or pending. No live success establishes disappearance, exhaustive German-market coverage, Salesforce integration or G1/G2 completion.

## Unresolved decisions and closure owners

| ID | Decision / gap | Proposed direction and owner gate |
|---|---|---|
| D01 | Adapter protocol has no request accounting, transport deadline or typed retry-hint capability | SOURCE-02/FND-01 with SOURCE-03 owners agree an injected executor/attempt receipt boundary before S04 production wiring. Keep current page/draft interface if compatible. No thread-only timeout claim. |
| D02 | No durable immutable exact-byte `RawCaptureSink` backend | DATA-01 supplies/verifies byte storage; INGEST-01 S02 bridges it. Specify reference format, safe publication, hash verification and file/DB failure behavior. Existing overwriting filestore is insufficient. |
| D03 | Current unique raw table cannot retain repeated observations; repository calls may commit inside outer transactions | DATA-01 owns observation/receipt persistence and an actually atomic page/checkpoint operation. S02 consumes it and proves faults/replays against real storage. No silent duplicate suppression or direct SQL workaround. |
| D04 | C04 lacks freshness/prefix/record-loss fields and has weak semantic validation | INGEST-01 S01/S07 with FND-01/IDENTITY-02 agree conservative v1 partial semantics, count units and legacy-reader treatment, or request an explicit contract version change. Finalize before S05–S07 acceptance. |
| D05 | Finite source elapsed/request/body defaults and rate-sharing key are not defined by C03 | INGEST-01 S01 selects documented technical defaults/caps and typed options; SOURCE-01 owns any later configuration vocabulary extension. SOURCE-03 supplies actual transport and reviewed restrictions. Never infer provider quotas. |
| D06 | Cache key/TTL/permission/freshness policy and conditional revalidation | INGEST-01 S01/S06: disabled default, explicit TTL reuse, strict key/integrity checks, no fresh-complete projection for unrevalidated cache. Initial 304 is unsupported; conditional support waits for an owner capability, not invented provider behavior. OPS/source owners resolve retention constraints. |
| D07 | Current manifest insert allocates a new ID on every save; no authoritative traversal uniqueness | DATA-01 supplies stable finalization identity/reconciliation and any migration. INGEST-01 S01/S07 agree one traversal per run/source/scope and a new run ID for deliberate restart. |
| D08 | Manual error taxonomy, continuation validation and replay context have gaps despite VERIFIED handoff | SOURCE-02 owns corrections. INGEST-01 S03 defensively classifies exceptions, persists input/draft context and records blocked manual acceptance cases. Do not edit manual adapters as part of these stories. |
| D09 | Provider implementation, live access/attribution and native transport enforcement unavailable | SOURCE-03 instance/SOURCE-01 own delivery/review; S09 records live pending until available. Arbeitnow stories are planning evidence, not a handoff or current service guarantee. |
| D10 | Runtime CLI/lock/recovery, retention and precise downstream consumption | RUN-01 owns caller run lifecycle, process lock, commands and recovery scheduling; OPS-01 owns cleanup/backup; IDENTITY-02 owns availability. INGEST-01 supplies versioned results/checkpoints and conservative manifests, without implementing those components. |

S01 must close internal defaults/semantics and identify exact prerequisite versions before dependent stories start. Owner gaps can be exercised through fakes but cannot be labelled production-ready. Each unresolved item must retain an owner, affected acceptance and next action; do not expand the component to eliminate another owner's backlog.

## Implementation handoff checklist

- Component ID/status/objective; R02/R09/R16 and supporting requirements; exact blueprint, prerequisite handoff, schema, adapter and migration versions used.
- Owned files changed; public callable signatures; local receipt/options/cache/checkpoint/result versions; any separately approved shared contract changes and old-record reader behavior.
- C03 selection/config snapshot and inventory scope; source/provider/board identity; adapter/factory binding and supported manual descriptors; actual request/timeout capability.
- Immutable parent/derived evidence reference format and byte boundaries; hashes, locators, attribution and original timestamps; repeat observation versus replay identities; real transaction/finalization guarantees and failure limits.
- Limit defaults/units/precedence, attempts/request/page counts, provider rate-sharing/cooldown behavior, retry eligibility/hints, deadline/cancellation semantics, cache invalidation/freshness and 304 policy.
- C04 outcome table, page count and observed-ID encoding, safe continuation rules, record errors, cache/prefix completeness restrictions; no availability mutation or canonical count claims.
- Separate unit/contract, fake-adapter, actual manual, real-storage, native Windows and live-source results with commands/environment/outcomes. Record unavailable capabilities and failures instead of inheriting historical passes.
- Open D01–D10 decisions, owner handoffs, production/live pending work, and next consumers INGEST-02, IDENTITY-02 and RUN-01. No pipeline, Salesforce, G1/G2 or Phase 2 completion claim.

[blueprint]: ../../IMPLEMENTATION_BLUEPRINT.md
[fnd]: ../components/FND-01.md
[data]: ../components/DATA-01.md
[source01]: ../components/SOURCE-01.md
[source02]: ../components/SOURCE-02.md
[arbeitnow]: SOURCE-03-arbeitnow.md
[interfaces]: ../../src/job_automation/contracts/interfaces.py
[results]: ../../src/job_automation/contracts/adapter_results.py
[postings]: ../../src/job_automation/contracts/postings.py
[selection]: ../../src/job_automation/sources/service.py
[policy-code]: ../../src/job_automation/sources/request_policy.py
[raw]: ../../src/job_automation/sources/adapters/raw.py
[filestore]: ../../src/job_automation/storage/filestore.py
[raw-repository]: ../../src/job_automation/storage/repositories/raw_postings.py
[run-repository]: ../../src/job_automation/storage/repositories/runs.py
[transactions]: ../../src/job_automation/storage/connection.py
[migrations]: ../../src/job_automation/storage/migrations.py
