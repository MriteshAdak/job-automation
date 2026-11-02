# IDENTITY-01 — Company/job identity and revisions

Status: **PLANNED** · Planning date: **28 October 2026** · Phase 0 · Scope: **IDENTITY-01 only**

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), v1.0. References below use requirements (§2), contracts (§4), correctness rules (§5), component ownership (§6), integration gates (§7), working instructions (§8), and native Windows conventions (§9). This document plans future implementation; it does not report implemented or verified identity behavior.

## Boundary and repository evidence

**Objective:** consume valid C06 postings and existing identity mappings, assign stable company/job identities conservatively, and produce durable C07 revisions plus explicit match/review decisions. Direct requirement: **R04**. Supporting constraints: **R03** (provenance), **R09** (durable compact identities), **R14** (native Windows), **R15** (untrusted input and safe diagnostics), and **R16** (auditability and recovery).

**Inputs → outputs:** versioned C06 `NormalizedPosting`, existing mappings, approved matching/URL/hash rules, and explicit review actions → stable canonical UUID, C07 revision and canonical projection, source/company mappings, observation and URL history, evidence-bearing match decisions, review cases, and reversible merge/split lineage. Company/requisition hints need explicit namespaces and provenance before becoming strong evidence.

**Excluded:** source acquisition, normalization, posting-availability inference, C04 completeness interpretation, miss/grace counters, closure/reopening, eligibility assessment, model/embedding inference, Salesforce mutations or reconciliation, candidate application-state changes, pipeline orchestration, retention cleanup, scheduling, and document generation. IDENTITY-02 alone owns availability transitions. This component records observations and passes through existing availability; proposed initialization for new records is explicitly `unknown`, subject to S01's contract decision. It never relies on C07's current `active` default to infer availability.

Repository instructions read: [README](../../README.md), blueprint §§8–9, and [schema instructions](../../schemas/README.md). No applicable `AGENTS.md` was found in the repository or checked ancestor directories; the user-level `.codex/AGENTS.md` is empty. Shared schemas must be generated from typed models, not edited manually. Technical choices below are proposals within the blueprint's constraints, not additional user-confirmed requirements.

| Inspected evidence | Consequence for this plan |
|---|---|
| [DATA-01 handoff](../components/DATA-01.md) reports VERIFIED, migrations 1/2 and 112 tests | Historical evidence only. Current [migration catalog](../../src/job_automation/storage/migrations.py) also includes migration 3 for profiles. Allocate the next migration at implementation time; do not edit applied SQL or assume version 3 is free. |
| No `docs/components/INGEST-02.md`; [INGEST-02 stories](INGEST-02.md) are PLANNED | Catalog dependency is not complete. No normalization implementation exists under `ingestion/normalization/`. Use explicit synthetic C06 fixtures for independent work; real normalizer integration remains pending until its handoff exists. |
| INGEST-02 S01 and D01–D05 propose changes to provenance, missing company/collections, and mapping vocabulary | Re-read actual contracts when implementation starts. Do not fabricate company names or consume hypothetical new fields as if shipped. Its statements that `ingestion/`, durable capture, and the Arbeitnow handoff are absent are now stale. |
| [FND-01 handoff](../components/FND-01.md), [C06](../../src/job_automation/contracts/postings.py), [C07](../../src/job_automation/contracts/identity.py), [interfaces](../../src/job_automation/contracts/interfaces.py), schema 1.0 | C06 has company-name/provider-company hints but no typed requisition key or explicit employer-ID namespace. C07 has UUIDs, URLs and string `merge_lineage`, but no full immutable normalized snapshot or structured reversal record. |
| Current `IdentityResolver.resolve(normalized, existing)` | Returns `(UUID, PostingRevision, IdentityMatchDecision)`. `ExistingIdentityView` has string-keyed maps; decision type is a free string plus confidence/rationale. No production resolver exists. S01 must make uncertainty, conflicts, evidence and serialization precise. |
| [Canonical repository](../../src/job_automation/storage/repositories/canonical_jobs.py) | `find_by_source_key` joins revisions with `LIMIT 1`; it is not an authoritative unique source-to-canonical map. `normalized_postings` allows one row per source tuple. Revision upsert is unique on `(canonical_job_id, content_hash)` and can replace JSON while keeping the original SQL revision UUID. These are gaps to fix explicitly, not a ready identity engine. |
| Current storage transaction helpers and canonical repository | The shared transaction helper supports nested use, but canonical methods still use direct `with self.conn:` blocks. Calling them inside an outer unit of work can commit prematurely. S02 must demonstrate actual multi-record atomicity. |
| [SOURCE-02 handoff](../components/SOURCE-02.md), [manual identity](../../src/job_automation/sources/adapters/manual_identity.py), [SOURCE-03 Arbeitnow handoff](../components/SOURCE-03-arbeitnow.md) | Manual URL fallback is `url-v1:<hex64>` over the exact URL; Arbeitnow documents `url-v1:sha256:<hex64>`. Preserve both as opaque source IDs. Do not unify them or confuse them with canonical UUIDs/content hashes. Slug recycling is unresolved. |
| [INGEST-01 handoff](../components/INGEST-01.md), [capture](../../src/job_automation/ingestion/capture.py), [page persistence](../../src/job_automation/ingestion/persistence.py) | Durable byte captures and page receipts exist. `raw_postings` still has one row per tuple; a changed-hash collision is logged and skipped in that table. Never recover an edited posting's raw evidence by looking up only that tuple. Confirm exact-reference reachability with upstream owners. |
| Existing contract/storage/source tests and C06/C07 fixtures | Establish shape, basic scoping and storage behavior, not matching correctness or reversible merges. Extend these tests where contracts change, and add labeled identity fixtures. |

## Identity invariants and proposed policies

| Concept | Required meaning / proposed implementation rule |
|---|---|
| Source identity | Exact `(provider, board_id, source_posting_id)` tuple. Preserve case, leading zeros and opaque delimiters. Registry `source_key`, fetch `scope_id`, cursor and run ID are different concepts; a changed search scope cannot create another identity for the same tuple. Use composite columns or an unambiguous versioned encoding, never delimiter concatenation. |
| Permanent job/company identity | Locally allocated UUID persisted once and reused. Neither UUID derives from company name, title, location, description, URL, provider slug or content hash. A rename changes evidence/display data, not the UUID. Unknown company mapping remains null. |
| Raw hash | C05/C06 `raw_content_hash` describes captured bytes and integrity. It is not a canonical ID, source ID, or normalized revision hash. |
| Revision hash | Versioned digest of a specified normalized content projection. Exclude observation time, raw path/hash, generated UUIDs and run metadata. Include material job facts and exact source/application URLs; define all C06 fields and ordering rules in S05. Preserve normalizer/hash versions separately. Equal hashes alone never establish duplicate opportunities. |
| URL fallback hash | A source-adapter identity encoding over a URL when provider ID is absent. It is scoped by provider/board and remains opaque to the resolver. It is not a permanent job/company identity or content digest. |
| Observation | A sighting of one exact C06 input/raw reference at an observed UTC time, linked to its source, revision and decision. Replays reuse the recorded result; new sightings may update first/last seen without making a content revision. |
| Strong company evidence | Namespaced employer identifiers or explicitly reviewed alias mappings. Name similarity, shared domain, corporate parent or ATS hostname alone cannot prove employer equality. Record the scope in which a company ID is valid. |
| Strong job evidence | Existing source mapping, or corroborated employer + scoped requisition key, or a validated job-specific application URL with compatible employer context and no contradictory strong key. Provider posting ID is not automatically an employer requisition number. |
| Uncertain/conflicting evidence | Preserve separate opportunities and open a durable identity review case. Similar text/title/location can propose review only. An arbitrary confidence threshold cannot authorize a merge. Identity review is separate from C11 eligibility review and Salesforce application progress. |
| Alternate sources and links | Retain every source association and exact historical source/application URL, with provenance and observation history. A selected display/current revision does not delete alternatives or their facts. |
| Reversible merges | Retain all original canonical/company UUIDs, revisions, source memberships and link provenance. Represent effective grouping using explicit mappings/events, not destructive row deletion. Reversal restores ownership without changing frozen downstream references or candidate data. |

Default matching order: replay result → existing exact source mapping → strong-key candidates → review candidates → new canonical. At every matching step detect contradictory employer/requisition evidence. Conflicts override automatic linking. A reused source ID with credible identity conflict becomes held review work; it must not overwrite the old opportunity or silently create a second simultaneous active source mapping. Ordinary title/description/location edits retain identity. A new explicit requisition remains separate even when text or a generic application URL is identical. Define reviewed reassignment/history for confirmed ID recycling in S07/S08.

Conservative URL baseline: keep the original string; validate HTTP(S) syntax and reject malformed ports, credentials/userinfo and control characters for matching. Exact comparison is the safe initial rule. Do not fetch URLs, follow redirects, resolve shorteners, strip unknown queries/fragments, reorder duplicate parameters, decode escapes, lowercase paths, collapse trailing slashes, or equate HTTP and HTTPS. Any later host-specific comparison rule needs a version, evidence, positive/negative fixtures and retained original URLs. A generic careers page, ATS root, shared application form or expiring/session URL is not sufficient strong evidence. Suspected tracking-only differences can create review candidates; they do not rewrite upstream fallback identities.

## Ordered implementation stories

All stories belong to IDENTITY-01. Necessary shared contract/storage edits are narrow coordinated changes, not permission to implement missing prerequisites. Each story contributes to S09's native Windows verification. Proposed filenames can be refined within these boundaries and recorded in the handoff.

| Order | Story | Dependencies | Deliverable |
|---|---|---|---|
| 1 | IDENTITY-01-S01 | DATA-01; FND-01 contracts; INGEST-02 boundary decisions | Frozen identity/evidence/result contracts and compatibility plan |
| 2 | IDENTITY-01-S02 | S01; DATA-01 | Durable mappings, observations, snapshots and audit storage |
| 3 | IDENTITY-01-S03 | S01–S02 | Stable company UUIDs and conservative aliases |
| 4 | IDENTITY-01-S04 | S01–S03 | Scoped job keys, URL evidence and strong matching |
| 5 | IDENTITY-01-S05 | S01–S04 | Versioned revision hashes, immutable content and alternate sources |
| 6 | IDENTITY-01-S06 | S02–S05 | Atomic resolver/service integration and replay recovery |
| 7 | IDENTITY-01-S07 | S06 | Durable uncertain-match review and explicit decisions |
| 8 | IDENTITY-01-S08 | S06–S07 | Reversible merge/split operations and reference preservation |
| 9 | IDENTITY-01-S09 | S01–S08; actual INGEST-02 for real boundary verification | Native Windows evidence, regression checks and component handoff |

### IDENTITY-01-S01 — Freeze contracts and compatibility decisions

**Objective/references.** Make identity evidence, result states and historical references implementable before matching logic. R04/R03/R09/R15; C03/C05/C06/C07, `SourceKey`, `ExistingIdentityView`, `IdentityMatchDecision`, `IdentityResolver`; C08/C11–C14 reference compatibility. Blueprint §§4–6, 8.

**Dependencies.** DATA-01 and FND-01 current code/handoffs; INGEST-02 S01 and its pending handoff. Read new upstream decisions before closing shared-boundary work. Independent contract fixtures can proceed without pretending the normalizer exists.

**Owned files.** Proposed `src/job_automation/identity/{__init__,models,ports,errors}.py`, `tests/identity/{__init__,test_contract_boundary}.py`, `tests/fixtures/identity/README.md`; decision sections of future `docs/components/IDENTITY-01.md`. Coordinated: `contracts/{identity,interfaces,postings,export_schemas,__init__}.py`, affected generated schemas, fixture generator/C06/C07 fixtures and contract/fake-consumer tests. Change primitives/evidence contracts only if the recorded compatibility design requires it.

**Inputs → outputs.** Existing contracts and gaps → versioned source/company/job evidence types, observation/review/merge records, result/error protocol, and migration/consumer plan.

**Tasks.**

1. Specify namespaced employer/requisition hints and field provenance. Prefer an explicit additive typed C06 extension coordinated with INGEST-02/FND-01; missing hints stay absent and disable that match route. Do not mine raw provider payloads or parse requisitions from prose here.
2. Replace informal match strings with enumerated outcomes covering new, exact-source, strong-key, uncertain and conflict/held results; include candidate IDs, evidence references, algorithm/rule versions and reasons. Confidence, if retained, has documented non-probabilistic meaning and never overrides evidence rules.
3. Resolve the current mandatory `(UUID, PostingRevision, decision)` return for conflicts: propose a versioned result allowing no applied revision when a source is held. Ordinary uncertain cross-source candidates may receive a separate provisional canonical ID. Do not return a fabricated revision or attach a conflict to the wrong job merely to satisfy the old tuple.
4. Specify immutable C06 snapshot resolution by revision UUID for C08 and frozen C13 inputs, with separate observation/URL metadata. C07 string lineage can remain a compatibility projection but cannot be the sole reversal record. Define original-ID lookup separately from effective merged-ID lookup.
5. Close D01–D04 below before dependent representations ship. Decide C07 missing-company handling if INGEST-02 makes its hint nullable; never introduce an invented company placeholder. Initialize new availability explicitly as unknown and preserve existing values without computing aggregate availability.
6. Record schema versions, old/new readers, serialized fixture compatibility and downstream migration decisions. Additive fields are not automatically compatible with current `extra='forbid'` readers. Incompatible semantics require the blueprint decision and consumer plan prescribed by §8.

**Acceptance examples.** Two source tuples with embedded separators round-trip distinctly. Missing requisition evidence disables requisition matching. A conflict has a typed held outcome with its input retained. A legacy C07 record remains readable through an explicit compatibility path; its string audit trail is not presented as sufficient reversal evidence.

**Tests/Windows.** Contract validation, invalid outcome combinations, unsupported versions, lossless tuple encoding, nested-data copy isolation and protocol consumer tests. Import/construction has no network, model or filesystem side effects on native Windows.

**Migration/configuration/handoff.** No data mutation in this story beyond planned contract migration tooling where necessary. Freeze rule/settings versions independently of record schema versions. Publish signatures and required owner decisions before S02.

### IDENTITY-01-S02 — Persist mappings, snapshots and audit records atomically

**Objective/references.** Supply durable identity state that supports edited posts, alternate sources and reversal. R04/R09/R16; C06/C07; blueprint §§5–6/DATA-01 and IDENTITY-01.

**Dependencies.** S01; DATA-01 migration/transaction facilities and current database version.

**Owned files.** Proposed `storage/repositories/identity.py`; minimal coordinated edits to `storage/{migrations,engine,connection,__init__}.py`, repository exports and `canonical_jobs.py`; `tests/identity/{test_repository,test_migrations,test_transactions}.py`, affected storage/CLI-storage tests. Generic storage remains DATA-01-owned.

**Inputs → outputs.** Legacy database and typed identity records → durable company records/keys, unique source records, historical memberships, normalized snapshots/observations, revision associations, review decisions and append-only merge events.

**Tasks.**

1. Add forward migrations with unique composite source keys, foreign keys, operation/replay uniqueness and indexes for strong-key lookup. Separate source identity from its many sightings and versioned canonical memberships. A source has at most one current applied canonical assignment; held observations need not change it.
2. Replace one-row normalized storage as the historical authority with immutable versioned snapshots/observations. Define the legacy latest/read facade explicitly. Retain raw references/hashes from each exact C06 input; do not depend on the raw repository's first tuple row.
3. Remove the evidence-loss risk of `(canonical_job_id, content_hash)` revision upserts. Proposed revision uniqueness is source identity + reviewed assignment epoch + hash-algorithm version + normalized content hash, with separate canonical associations and observations. An epoch changes only for an explicitly adjudicated source-ID reuse/reassignment, not an ordinary edit or merge. Different sources with equal content retain distinct revision UUIDs and evidence; S05 finalizes this policy.
4. Backfill source mappings from both legacy linked-source lists and revisions. Contradictory historical ownership or mismatched SQL/JSON UUIDs becomes an inspectable migration issue, never arbitrary `LIMIT 1` selection. Do not invent missing snapshots from latest C06 data. Preserve legacy records and mark unavailable historical content explicitly.
5. Ensure SQL columns, C07 JSON projections and current-revision references agree. Use one composable transaction boundary across all identity writes; refactor only required repository paths that currently open independently committing connection contexts.
6. Preserve existing canonical IDs, assessments, pending sync operations, generation requests and artifacts. Never delete canonical rows to merge them: existing foreign keys include cascade deletion. Migration failure must roll back without partial schema/data changes.

**Acceptance examples.** Two sightings of one source create one source identity and two observations. Two sources with identical normalized text retain both keys and URLs. A fault after source assignment but before revision insert leaves neither change committed. Upgrade of a populated v3 database preserves all original UUIDs and downstream records.

**Tests/Windows.** Real SQLite migration/restart tests, unique/FK violations, legacy inconsistencies, SQL/JSON consistency and fault injection at each multi-record boundary. Run on a spaced/Unicode Windows path; verify handle release and reopening. Test existing generic storage behavior remains valid.

**Migration/configuration/handoff.** Allocate the next unused migration number, preserve applied checksums, document table/index ownership and backfill limits. Use the existing configured database/data root; no extra service or database. Record compact identity/snapshot/audit retention requirements for OPS-01 without implementing cleanup.

### IDENTITY-01-S03 — Resolve stable company identities conservatively

**Objective/references.** Reuse durable company UUIDs without conflating similar employers. R04; C06 company hints and C07 company mapping; blueprint §§4–5.

**Dependencies.** S01's namespace/unknown decisions and S02 storage.

**Owned files.** Proposed `identity/companies.py`; extend local models and identity repository; `tests/identity/test_companies.py`, synthetic company/alias cases under `tests/fixtures/identity/`.

**Inputs → outputs.** Company hints, namespaced keys, reviewed aliases and current mappings → existing/new company UUID or unresolved mapping plus evidence/review reason.

**Tasks.**

1. Allocate a UUID only when registering a company entity with defensible evidence. With name-only ambiguity, preserve the hint and return null mapping plus candidates; do not group every occurrence of a normalized name.
2. Scope provider company IDs according to documented provider/tenant semantics; default to provider + board when no broader namespace is established. Leading zeros and case remain significant.
3. Retain display names and alias histories separately from identity. Case/punctuation/legal-suffix normalization can assist review lookup but cannot independently prove equality. Shared domains, staffing agencies and employer parent/subsidiary relationships require explicit evidence.
4. Store approved alias mappings with evidence, actor, timestamp, operation ID and rule version; reject aliases that introduce unresolved collisions. Company correction/reassignment uses audited lineage, not UUID rewriting. Existing company consolidation, if needed, uses S08's reversible event model.

**Acceptance examples.** A provider employer ID survives a rename with the same UUID. Employer ID `0012` in tenants A/B is not assumed identical. “Nordlicht GmbH” and “Nordlicht Services GmbH” with similar adverts remain unresolved/separate unless corroborated. Editing a job's displayed employer name alone never regenerates its canonical job UUID.

**Tests/Windows.** Labeled company positive/negative cases, ambiguous aliases, null evidence, conflicting IDs, repeat registration and restart persistence. Include German characters without treating transliterations as proof of equality.

**Migration/configuration/handoff.** Reuse S02 tables; any new persisted field needs an explicit forward migration. Document supported company-key namespaces and reviewed-alias format; no external company enrichment or network lookup.

### IDENTITY-01-S04 — Match scoped job identities and strong URL/requisition evidence

**Objective/references.** Link only well-supported duplicates while preserving distinct requisitions. R04/R15; C03/C06/C07 and resolver decisions; blueprint §5 identity rules.

**Dependencies.** S01–S03; source adapter identity semantics are evidence inputs, not code to rewrite.

**Owned files.** Proposed `identity/{keys,urls,matching}.py`; `tests/identity/{test_source_keys,test_urls,test_strong_matching}.py`; synthetic URL and requisition cases. Existing source identity tests are regression targets.

**Inputs → outputs.** Exact source tuple, trusted company/requisition hints, URLs and existing mappings → evidence-bearing match proposal, no-match or conflict; persistence occurs through S06.

**Tasks.**

1. Implement the matching order and conflict vetoes above. Use stable exact source mapping for ordinary edits. Allocate new canonical UUIDs independently of mutable facts; persist/reuse them through S06 rather than regenerating on replay.
2. Match employer + namespaced requisition only when both are evidenced and compatible. Distinguish source-posting IDs from requisitions. Explicit differing requisitions block merging despite identical content or a shared application form.
3. Implement conservative URL comparison and classify whether a URL is job-specific. Require documented host/path evidence or supplied trusted metadata before treating it as a strong application key. Preserve original URLs and comparison rule version; unknown host behavior remains conservative.
4. Preserve existing fallback source IDs verbatim. A new URL spelling may create a different upstream fallback key; canonical linking then requires independent strong evidence or review, not reinterpretation of that key.
5. Detect multiple strong candidates, employer/requisition contradictions and suspected source-ID recycling; return held/review results without overwriting mappings. Similarity may propose review candidates but never auto-merge.

**Acceptance examples.** Same ID `0007` on different boards is distinct. Same employer/requisition on two sources links to one opportunity. Different requisitions with identical descriptions remain separate. `?job=17` and `?job=18`, `#job-17` and `#job-18`, and `/Jobs/A` versus `/jobs/a` remain distinct under baseline rules. Shared `/careers/apply` does not prove duplication. A changed title under the same source tuple retains its UUID unless contradictory identity evidence requires review.

**Tests/Windows.** Table-driven positive/negative/collision cases, duplicate query keys, encoded delimiters, Unicode URLs, signed queries, malformed ports, credentials and scheme rejection. Assert zero HTTP/DNS/browser/model calls and redacted errors. Run source fallback/slug regressions unchanged unless an explicit upstream contract decision says otherwise.

**Migration/configuration/handoff.** Persist rule versions and evidence through S02. Prefer explicit local settings to expanding global config. No provider-specific URL rule is enabled without fixtures and a recorded evidence basis; no canonical ID backfill from URL hashes.

### IDENTITY-01-S05 — Retain immutable revisions, observations and alternate sources

**Objective/references.** Separate permanent identity, material content changes and repeated sightings. R04/R03/R09; C05/C06/C07 and C08/C13 historical references; blueprint §§4–5.

**Dependencies.** S01 snapshot/hash contract, S02 storage, S03–S04 identity proposals.

**Owned files.** Proposed `identity/{revisions,hashing,projections}.py`; identity/canonical repositories as needed; `tests/identity/{test_revision_hashes,test_revisions,test_alternate_sources,test_historical_references}.py`; hash golden fixtures and expected histories.

**Inputs → outputs.** C06 input with resolved source/canonical association → immutable revision snapshot and UUID, versioned content hash, linked observation/URL history and deterministic C07 projection.

**Tasks.**

1. Freeze an explicit field-by-field hash projection: title, cleaned description, company hints, exact URLs, locations, workplace/restrictions, employment, compensation and units/provenance, advert language and source dates. Preserve null/unknown distinctions. Sort only semantic sets, serialize decimals/timezones deterministically, and preserve ordered/text data as defined by C06. Store schema, normalizer and hash versions with the snapshot; exclude capture/observation metadata from content equality.
2. Use S02's per-source revision policy within the same assignment epoch: unchanged projected content reuses that source's revision UUID; changed content creates a new UUID under the same job. A→B→A may reuse the original A content revision, while ordered observations preserve both transitions. Confirmed source-ID recycling into another opportunity starts a reviewed epoch so identical content cannot reuse the former opportunity's revision. Make this policy explicit to consumers.
3. Keep full immutable normalized snapshots so old description spans, compensation and URLs remain resolvable. `first_seen`/`last_seen` and URL associations are observation metadata, not edits to historical content. New raw bytes with equal normalized content add evidence without conflating raw and revision hashes.
4. Retain alternate sources independently, including identical content hashes, conflicting fields and old application links. Choose a current display revision by a documented deterministic rule, proposed newest `observed_at` with stable source-key tie-break; do not synthesize a field-by-field blended snapshot. Current does not mean available. Older/out-of-order observations cannot regress last-seen timestamps.
5. A normalizer/hash version change is explicit reprocessing, not a new permanent identity. Preserve old revision lookup; define whether equivalent content reuses a revision or forms a new algorithm-version revision and record the decision once.

**Acceptance examples.** Identical re-fetch retains canonical/revision UUIDs but advances observation metadata. Salary or description edit creates a new revision; old C08 quotations still resolve. Application URL v1→v2 preserves both exact links. Equal text on unrelated jobs creates no match. Two linked sources with identical hashes remain separately inspectable. Replaying yesterday's observation after today's does not select yesterday as current.

**Tests/Windows.** Golden digest tests, material versus metadata-only changes, set ordering/decimals/nulls, timezone normalization, equal-content cross-source cases, A→B→A, out-of-order arrival, and snapshot mutation isolation. Resolve historical C08/C13 fixture references after edits and database reopen; include Unicode descriptions/links.

**Migration/configuration/handoff.** Never silently reinterpret legacy hash values. Record unknown legacy algorithms and missing snapshots; do not claim content can be reconstructed. Document observation versus revision counts for future RUN-01/C15. No availability computation or raw-retention deletion.

### IDENTITY-01-S06 — Compose an atomic, replayable identity service

**Objective/references.** Make the resolver usable with durable results and safe restart behavior. R04/R09/R16; C06→C07, resolver boundary and classified errors; blueprint §§5–6, 8–9.

**Dependencies.** S02–S05; valid C06 fixtures now, real INGEST-02 output when available.

**Owned files.** Proposed `identity/{resolver,service}.py`, public exports and minimal repository integration; `tests/identity/{test_resolution,test_replay,test_crash_recovery,test_consumer_boundary}.py`; scoped fake consumers in `tests/fakes/`.

**Inputs → outputs.** Valid C06 and an explicit processing/replay token or agreed observation key → committed canonical/revision/decision, or retained held/error result with no partial applied mapping.

**Tasks.**

1. Implement the S01 protocol with injected storage, UUID and clock dependencies; business rules consume immutable lookup views. No runtime network/model dependencies. Validate the C06 boundary rather than attempting normalization repair.
2. Define a replay key containing exact source, observation/raw-reference identity, normalization version and resolver rule version as appropriate. It is an operation key, never the permanent job UUID. A same-content new sighting remains distinct from retrying the same input.
3. Commit company/source associations, revision/snapshot, observation, decision, review proposal and C07 projection in one transaction. Persist generated UUIDs and replay outcomes together. Recheck mapping uniqueness/version before commit to reject stale decisions.
4. Keep a committed-but-response-lost replay idempotent. Failures before commit leave no partial identities; held conflicts retain exact input evidence. Report storage/version errors separately from uncertain matching; do not turn operational failure into an identity verdict.
5. Supply original-ID, effective-ID and revision-by-ID reads for consumers. Return new/changed/unchanged/held units explicitly; orchestration, outbox production and run counters remain RUN-01/SYNC-01 work.

**Acceptance examples.** Restart after commit but before response returns the original IDs. Fault before commit produces no orphan company/source/revision rows. A stale lookup cannot overwrite a newly reviewed mapping. Existing unavailable/unknown values remain unchanged after an edited posting; no manifest is consulted.

**Tests/Windows.** Real SQLite fault injection at each write boundary, two-connection uniqueness/stale-write tests, separate-process restart and repeat-call tests. Prove C07 JSON/SQL consistency and unchanged availability. Fake consumers prove protocol compatibility only; label real normalizer integration separately.

**Migration/configuration/handoff.** Use S02 tables and existing external data root. Document transaction/replay boundaries and error codes. No search CLI, process-lock framework or retry scheduler; RUN-01 integrates those later.

### IDENTITY-01-S07 — Make uncertain matches inspectable and decidable

**Objective/references.** Give ambiguity a durable human review path without accidental merging. R04/R15/R16; C06/C07 plus S01 decision/review records; blueprint §5.

**Dependencies.** S06 and S04 evidence/reasons. Merge execution is S08; this story establishes review commands and decisions.

**Owned files.** Proposed `identity/{review,cli}.py`, minimal registration in `src/job_automation/cli.py`, `tests/identity/{test_review,test_review_cli,test_safe_diagnostics}.py`, synthetic review fixtures; README usage added during implementation.

**Inputs → outputs.** Uncertain pair/conflict, evidence snapshots and explicit actor action → deduplicated review case, accept/reject/defer or source-reassignment decision, and an audited operation request.

**Tasks.**

1. Persist candidate IDs, exact relevant revision/source references, supporting and contradictory evidence, reason codes, rule version, timestamps and case state. Deduplicate repeated proposals for the same evidence; new material evidence can reopen/version a case without erasing an earlier rejection.
2. For text/title/company similarity alone, keep separately identified jobs. For an existing source-key conflict, retain held input alongside the unchanged assignment. Bound any similarity proposal work using explicit deterministic local rules; no embeddings or inferred match probability are required.
3. Provide minimal local list/show/decide commands or equivalent inspectable API, with safe CLI output and explicit IDs. Decisions require actor/reason and current expected case version. Repeated action IDs are idempotent; stale approvals fail visibly. Proposed CLI verbs are frozen in this story before documentation is shipped.
4. Accepting a duplicate records intent for S08; rejecting records a durable do-not-link decision for the reviewed evidence; defer retains pending work. A strong-key conflict is not resolved merely by clicking a generic duplicate approval: require explicit evidence/assignment resolution.
5. Keep identity review states separate from C11 dispositions, posting availability and candidate progress. Protected detailed views may show necessary evidence; ordinary logs must not contain raw text, credential-bearing URLs or unfiltered validation dumps.

**Acceptance examples.** Near-identical adverts on two unrelated employers produce review, never an automatic merge. Rejecting A/B prevents repeated identical proposals. New evidence is visible without deleting the rejection. A stale review decision cannot mutate an updated source assignment. A confirmed recycled slug can be explicitly reassigned with its old membership retained.

**Tests/Windows.** Review lifecycle, pair-order deduplication, evidence versioning, stale-action rejection, CLI JSON/exit codes and redaction. Native PowerShell invocation uses absolute config/data paths from another CWD; no browser or Salesforce UI is required.

**Migration/configuration/handoff.** Reuse review/event tables, extending via forward migration only if needed. Freeze local command/API syntax and conflict-resolution semantics. UI/publishing to Salesforce belongs to future owners; local review is sufficient for this component.

### IDENTITY-01-S08 — Merge and reverse without losing links or history

**Objective/references.** Demonstrate reversal of a mistaken duplicate decision while preserving original identities and references. R04/R09/R16; C07 lineage, C08 references and C11–C14 downstream records; blueprint §5.

**Dependencies.** S06 atomic service and S07 reviewed actions. Automatic strong matches that join two already-existing canonical groups must use this same audited mechanism, never a destructive shortcut.

**Owned files.** Proposed `identity/{merges,lineage}.py`; review/service/CLI and repository extensions; `tests/identity/{test_merges,test_merge_reversal,test_reference_preservation}.py` and merge-chain fixtures.

**Inputs → outputs.** Explicit merge/reversal request with operation ID, actor/reason/evidence, participating IDs and expected versions → effective canonical grouping and append-only lineage, or an explicit conflict with no partial change.

**Tasks.**

1. Choose and record a surviving effective canonical ID deterministically, proposed oldest registration with UUID tie-break unless explicitly selected in reviewed input. Preserve all original job/company rows and IDs. Persist predecessor memberships, source/revision ownership, URL associations, current projections and operation dependencies sufficient to reverse exactly.
2. Keep revision UUIDs, immutable snapshots, original canonical provenance, raw references and prior URLs unchanged. Grouping affects effective lookup, not frozen C08/C13 history. Retain separate existing local/remote mapping references; do not delete/rewrite Salesforce records, application status, notes, assessments, requests, artifacts or pending sync payloads.
3. Commit merge plus audit plus projections atomically. Reject cycles, self-merges, stale operations and unresolved strong contradictions; a previously adjudicated correction must be explicit evidence. Repeating a merge operation returns the same result. If evidence is insufficient to undo a legacy merge, block destructive reversal and expose the limitation.
4. Reverse through a new compensating event. Restore original IDs/memberships and all links; never regenerate identities. Observations received during the merged period remain attached to their originating source and revision. Ambiguous post-merge assignments require review rather than guessed ownership.
5. For A→B→C chains, require dependent operations to be reversed in a documented safe order or explicitly adjudicated. Do not silently flatten history. Preserve per-record availability without recomputing it; expose identity changes for IDENTITY-02 to consume later.
6. Provide a local inspectable change/result record for SYNC-01/RUN-01, including both original IDs when both were tracked. External duplicate reconciliation and pending remote write policy remain unresolved consumer work; do not claim a local merge merges Salesforce applications.

**Acceptance examples.** Merge jobs A/B with links A1/A2/B1, observe B2 while merged, then reverse: A and B retain their original UUIDs, A1/A2 and B1/B2 return to their documented memberships, and all revision evidence resolves. An assessment/frozen request referring to B before merge still resolves B's exact original snapshot. Failure midway through merge or reversal commits no partial membership changes. Two existing remote acknowledgments remain preserved and flagged for downstream reconciliation.

**Tests/Windows.** Merge/reverse round trips, post-merge observations, same-content revisions from different sources, multiple application links, cycle/chain/stale rejection, idempotency and crash injection. Seed actual local C11/C12/C13/C14 records to prove preservation; remote behavior uses labeled fakes only. Restart before reversal on native Windows and verify FK integrity.

**Migration/configuration/handoff.** No destructive database merge/delete. Structured events are authoritative; C07 string lineage is a readable projection only. Document reversal boundaries, source recycling and company reassignment support, downstream invalidation/reconciliation needs and protected retention records.

### IDENTITY-01-S09 — Verify the boundary and publish the component handoff

**Objective/references.** Demonstrate IDENTITY-01 acceptance with reproducible native Windows evidence. R04/R14/R15/R16; C06/C07 and affected consumers; blueprint §§6/IDENTITY-01, 7–9.

**Dependencies.** S01–S08. Re-read DATA-01 and the actual INGEST-02 handoff when present. Do not mark actual normalizer integration verified based solely on fixture C06 inputs.

**Owned files.** `tests/identity/{test_integration,test_windows_paths,test_windows_restart}.py`, identity fixture README, affected regressions, README identity commands, and `docs/components/IDENTITY-01.md`. Scope remains identity; no general pipeline implementation.

**Inputs → outputs.** Implemented stories, labeled fixtures, migrations and dependency versions → verification record, known gaps, callable examples and downstream handoff.

**Tasks.**

1. Run a deterministic offline scenario: two sources → strong match → repeated sighting → material edit → alternate application link → uncertain candidate → reviewed merge → reversal → restart. Compare exact IDs, memberships, snapshot content, URL history, first/last seen and decision evidence at each step.
2. Test distinct requisitions with identical text, company names with collisions, delimiter/leading-zero source keys, fallback identities, recycled slug conflict and delayed observations. Validate all public records against their actual typed/schema versions.
3. With actual INGEST-02 available, exercise source/manual fixtures through its production normalizer into identity. Until then report this check pending, document the exact upstream gap and demonstrate only the fixture boundary. Confirm edited raw references remain resolvable through the real capture handoff.
4. Run migration/rollback and affected contract/storage/source/ingestion/CLI checks; then one full regression run. Record dependency versions and commands, not historical test counts. Verify native paths, process restart and handle release with the recipe below.
5. Publish component status based on demonstrated acceptance; distinguish unit, fake-consumer, SQLite, native Windows and actual normalizer integration. No G1/full-pipeline, live Salesforce or posting-availability completion claim.

**Acceptance examples.** The handoff demonstrates all three catalog outcomes: repeated/edited posts retain identity, distinct requisitions remain separate, and a mistaken merge reverses without lost application links. A reviewer can resolve an old description span after edit/merge/reversal. Missing upstream normalization or provenance support remains an explicit integration dependency.

**Tests/Windows.** Execute the focused and regression suites below. Record failures and fixes; a planned test filename is not evidence of a passing check. Ensure every state used in availability boundary tests remains unchanged by identity operations.

**Migration/configuration/handoff.** Record final schema/migration/hash/rule versions, legacy limitations and all coordinated changes. Next consumers: IDENTITY-02, MATCH-01, RUN-01, SYNC-01, GEN-02 and OPS-01. No new runtime behavior beyond acceptance fixes.

## Native Windows verification recipe for implementation

These commands are a **future verification recipe**, not checks executed during story planning. Run after the proposed tests exist in an actual native Windows checkout. Use the existing environment; `pyproject.toml` specifies dependency ranges, despite older documentation describing pins. Record actual versions. Synthetic runtime data must use a unique external temporary root.

```powershell
$identity01Repo = (Resolve-Path '.').Path
$identity01Python = Join-Path $identity01Repo '.venv\Scripts\python.exe'
$identity01Config = Join-Path $identity01Repo 'config\app.example.json'
$identity01Tests = Join-Path $identity01Repo 'tests\identity'
$identity01AllTests = Join-Path $identity01Repo 'tests'
$identity01Temp = Join-Path $env:TEMP ('Job Automation Identität Prüfung ' + [guid]::NewGuid().ToString())
$identity01Data = Join-Path $identity01Temp 'Data Größe'

& $identity01Python -c "import platform, sys, sqlite3; from zoneinfo import ZoneInfo; print(platform.platform()); print(sys.version); print(sqlite3.sqlite_version); print(ZoneInfo('Europe/Berlin'))"
$identity01EnvironmentExit = $LASTEXITCODE
& $identity01Python -m pip show pydantic pytest tzdata
$identity01VersionsExit = $LASTEXITCODE
& $identity01Python -m pytest $identity01Tests
$identity01FocusedExit = $LASTEXITCODE
& $identity01Python -m pytest (Join-Path $identity01Repo 'tests\contracts') (Join-Path $identity01Repo 'tests\storage') (Join-Path $identity01Repo 'tests\sources') (Join-Path $identity01Repo 'tests\ingestion') (Join-Path $identity01Repo 'tests\test_cli_storage.py')
$identity01BoundaryExit = $LASTEXITCODE

New-Item -ItemType Directory -Path $identity01Temp | Out-Null
Push-Location $identity01Temp
try {
    & $identity01Python -m job_automation storage migrate --config $identity01Config --data-root $identity01Data
    $identity01MigrationExit = $LASTEXITCODE
    & $identity01Python -m job_automation storage status --config $identity01Config --data-root $identity01Data
    $identity01StatusExit = $LASTEXITCODE
    & $identity01Python -m pytest (Join-Path $identity01Tests 'test_windows_paths.py') (Join-Path $identity01Tests 'test_windows_restart.py') --basetemp (Join-Path $identity01Temp 'Pytest Daten ä')
    $identity01WindowsExit = $LASTEXITCODE
} finally {
    Pop-Location
}

& $identity01Python -m pytest $identity01AllTests
$identity01RegressionExit = $LASTEXITCODE
[pscustomobject]@{
    EnvironmentExit = $identity01EnvironmentExit
    VersionsExit = $identity01VersionsExit
    FocusedExit = $identity01FocusedExit
    BoundaryExit = $identity01BoundaryExit
    MigrationExit = $identity01MigrationExit
    StatusExit = $identity01StatusExit
    WindowsExit = $identity01WindowsExit
    RegressionExit = $identity01RegressionExit
}
```

The Windows tests must use `pathlib.Path`, explicit bases and `sys.executable` for child processes. Exercise spaced/non-ASCII checkout and data paths, changed CWD, Unicode evidence, database reopen and file-handle release. Include abrupt child-process termination before/after a transaction commit, followed by replay and merge reversal in another process. Record actual Windows results separately from portable tests. Add the final S07 review/merge CLI commands once their syntax exists; do not invent a current runnable identity command here. If shared contracts change, regenerate schemas using the existing exporter and review the diff against the recorded version decision.

## Unresolved decisions and closure owners

| ID | Decision / current gap | Owner and required closure evidence |
|---|---|---|
| D01 | INGEST-02 is planned; C06 may change company/null/provenance semantics | INGEST-02/FND-01 with IDENTITY S01. Read the eventual handoff, freeze consumed versions and compatibility fixtures. No fabricated company value; real integration stays pending until the dependency exists. |
| D02 | No typed employer namespace or requisition hint in C06 | FND-01/INGEST-02/SOURCE owners with S01/S04. Agree typed additive evidence and mapping provenance, or explicitly leave the match route disabled. Strong-key fixture support alone does not prove provider extraction. |
| D03 | Current resolver tuple cannot express held conflict without a revision; result/view models are weakly specified | FND-01 and S01. Version the result and view, update fake/real consumers, and document old-reader behavior. Do not silently change meanings under schema 1.0. |
| D04 | C07 lacks full snapshot/structured lineage; availability defaults to active | FND-01/DATA-01 with S01/S02. Agree immutable snapshot references, audit representation and explicit unknown initialization. Keep existing availability values untouched; all inference remains IDENTITY-02. |
| D05 | Storage uniqueness and legacy SQL/JSON inconsistencies can lose source/revision evidence | DATA-01 with S02/S05. Forward migration, deterministic backfill/conflict report, legacy missing-content policy, real atomicity tests and preservation of all downstream FKs. |
| D06 | Raw tuple lookup cannot retrieve every changed capture | INGEST-01/DATA-01/INGEST-02 with S06/S09. Demonstrate exact raw-reference resolution for successive edits and restart. Identity stores supplied C06 provenance; it does not repair acquisition or infer missing bytes. |
| D07 | URL equivalence, job-specific endpoint evidence and company alias trust | S03/S04. Default exact URL comparison and namespaced company keys; record any provider-specific rules with counterexamples. No broad query stripping, name-only automatic merge or network probing. |
| D08 | Hash field projection, repeated-content history, current revision selection and algorithm upgrades | S05 with INGEST-02/C08/GEN-02 consumers. Freeze golden vectors, source-scoped revision uniqueness and observation ordering; retain legacy references and make algorithm changes explicit. |
| D09 | Source ID/slug recycling and conflicting ownership | S04/S07/S08 with SOURCE-03 evidence. Default held conflict; define reviewed reassignment with historical memberships and per-observation ownership. Never infer a new opportunity from elapsed time or disappearance. |
| D10 | Reversal after dependent merges/new observations; both jobs already tracked externally | S08 with SYNC-01/RUN-01/GEN-02. Demonstrate local restoration and immutable references, define stale/chain conflicts and publish downstream change records. Salesforce application reconciliation remains outside this component. |
| D11 | Review candidate generation/limits and operator workflow | S07. Use deterministic bounded proposals, stable pair/evidence keys and local review API/CLI. Choose thresholds only for proposing review; no automatic merge by similarity score. |

These are implementation decisions and dependency coordination points, not a generic user-approval pause. Close blocking representations in S01; later stories close their algorithm/workflow choices with tests. Continue independent fixture work when upstream integration is unavailable, and keep incomplete acceptance visible.

## Implementation handoff checklist

- Component ID/status/objective, R04 and supporting requirements, scope and explicit availability exclusion.
- Dependency status and exact C06/C07/interface, database, normalizer, hash and matching-rule versions; unresolved upstream integration clearly labeled.
- Owned/coordinated files, generated schemas, migrations/backfills and legacy compatibility limits.
- Callable examples for new, unchanged, edited, strong-match, uncertain, conflicting, reviewed, merged and reversed outcomes.
- Permanent UUID versus source key/raw hash/revision hash/fallback hash distinctions; replay and observation units.
- Strong-key namespaces, URL rule evidence, company alias policy, revision projection and deterministic current selection.
- Atomicity/crash/restart evidence and SQL/JSON consistency; historical C08/C13 reference resolution and all prior application links retained.
- Review/merge/reversal command/API syntax, operation IDs, actor/reason audit, chain/conflict restrictions and downstream reconciliation needs.
- Exact commands/environment/exit codes/results; separate fixture, fake, real SQLite, actual normalizer and native Windows evidence. No live service claims from mocks.
- Outstanding D01–D11 decisions, protected retention records for OPS-01 and next steps for IDENTITY-02, MATCH-01, RUN-01, SYNC-01 and GEN-02.
