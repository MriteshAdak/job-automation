# SYNC-01 — Field mapping and persistent outbox

Status: **PLANNED — stories only**  
Date: **29 October 2026**  
Phase: **0 / P0**  
Requirements: **R04, R08, R09, R16**, with **R14/R15** constraints  
Direct dependencies: **DATA-01, SFCLIENT-01, SF-01, MATCH-01**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially §§4–6 and §§8–10.

Consume a complete, selected C11 Assessment from either assessment method, map canonical entities into the configured Salesforce schema, and durably publish machine-owned changes. Initial publication accepts eligible/review jobs. Already tracked jobs continue receiving assessment and availability updates after rejection or closure. Preserve candidate-owned status, notes, decisions and follow-ups, and retain local snapshots of those fields.

The delivery model is **recoverable at-least-once processing**. SQLite commits and Salesforce writes are separate transactions. Stable External IDs prevent duplicate logical entities; operation identities, ordered writes and reconciliation make interruptions recoverable. Neither an External ID nor an outbox provides exactly-once HTTP delivery or exactly-once Flow side effects.

## Repository evidence and prerequisite status

Read for this plan: the blueprint and [README](../../README.md); [DATA-01](../components/DATA-01.md) and [MATCH-01](../components/MATCH-01.md) handoffs; the [SFCLIENT-01 story plan](SFCLIENT-01.md); current C07/C11/C12 contracts, gateway protocol, assessment composition and consumer tests; storage engine, transaction helper, migrations, assessment/outbox repositories and storage transaction tests; identity company storage and application configuration. No applicable `AGENTS.md` was found in the checked ancestors or repository. The README directs planning to the blueprint and subsequent handoffs.

| Evidence in the repository | Consequence |
|---|---|
| DATA-01 handoff is VERIFIED and includes `atomic_commit_assessment_and_sync(assessment, sync_op)`. | Reuse and extend this storage boundary. Its current implementation inserts one C11 and one C12 in one connection transaction; it does not implement a complete delivery protocol. Historical checks are not SYNC-01 acceptance evidence. |
| Current [outbox repository](../../src/job_automation/storage/repositories/sync_outbox.py) uses operation-ID uniqueness, `created_at` ordering and unconditional state updates. | Add semantic deduplication, numeric per-entity ordering, compare-and-set claims, durable deadlines and acknowledgment evidence. A `payload_version` string alone does not enforce order. |
| `recover_stale_running()` changes all running operations to retry-wait without determining whether a write reached Salesforce. | SYNC-01 recovery must classify these as potentially transmitted and reconcile before replay. Do not use the DATA-01 startup recipe as authorization for blind retry. |
| Repositories use `with self.conn`; the shared `transaction()` helper tracks only its own nesting. | Do not wrap self-committing repository calls and assume the whole plan is atomic. Introduce transaction-participating writes and test failures after inner calls return. |
| Current migrations are 001–006, despite DATA-01 documenting the earlier 001–002 baseline. `sync_operations.reconciliation_marker` exists but is not used by the repository. | Append the next available migration, preserving existing checksums. Define and persist marker semantics rather than assuming the column supplies recovery. |
| [C12](../../src/job_automation/contracts/sync.py) v1 contains a job-only `SyncPayload`, string version, fingerprint, attempt limits, state and remote acknowledgment fields. | Preserve this contract; add versioned companion records for company steps, mapping snapshots, ordering and recovery. Do not silently turn its job payload into an arbitrary Salesforce field dictionary. |
| [C11](../../src/job_automation/contracts/assessment.py) supports rules and LLM metadata, but has no evaluation timestamp, primary/comparison selection flag or ordering generation. | Add a caller envelope around C11. Do not infer publication authority from arrival time, method, score or `get_latest_assessment()`. |
| MATCH-01 produces complete rules-only C11 records with null score/model metadata. Its sync test constructs C12 manually. | Consume the record without recomputing assessment. That test is compatibility evidence, not a production mapper, publication selector or dispatcher. |
| `CanonicalJob.canonical_company_id` is nullable; IDENTITY-01 stores stable company UUIDs separately. | Read canonical company identity; never derive External IDs from company names, titles, URLs or content hashes. Missing required identity is a visible dependency error. |
| No `docs/components/SFCLIENT-01.md` or `docs/components/SF-01.md` exists; `src/job_automation/salesforce/` and org metadata are absent. | These requested handoffs could not be read. The SFCLIENT story plan is provisional input, not an implemented gateway. Actual org mappings and gateway integration remain prerequisites. This does not establish that the user's org lacks configured assets. |
| The legacy gateway exposes only `execute_sync(C12) -> (record_id, error)`. SFCLIENT-01 plans a typed V2 transport boundary. | Use the eventual V2 read/describe/upsert outcomes, including unknown outcomes and attempt budgets. The legacy tuple cannot serve as the authoritative acknowledgment/reconciliation contract. |

### Inputs required from prerequisite owners

- **SF-01:** resolved Company/Job object names; unique External ID fields and encodings; relationship field; machine/candidate field ownership; type, length, nullability and picklist mappings; creation defaults; readable/writable integration fields; and any automation that mutates those fields on update. Supply machine-owned operation/version/fingerprint marker fields if used by reconciliation. `Company__c` and `Job__c` are blueprint defaults, not verified names.
- **SFCLIENT-01:** completed handoff with actual typed signatures, explicit not-found/permission/duplicate-match results, mutation acknowledgment and unknown-outcome semantics, selected API version, request budgets and guarantees about hidden retries. Its SF-02 dependency supplies existing authorization. SYNC-01 neither chooses OAuth nor creates permissions.
- **MATCH-01 / later MATCH-02 and RUN-01:** complete C11, resolvable C07/revision/C06 bindings, evaluation time and an explicit selected-final input generation. Comparison and intermediate records are retained locally without independent publication. LLM fixtures can prove method compatibility before MATCH-02 exists.
- **IDENTITY-01/02:** existing canonical/company identities and authoritative availability snapshots. SYNC-01 consumes these; it does not infer closure from missing source results or decide merges.

Missing external prerequisites do not block writing these stories or offline implementation against clearly synthetic ports. They block production mapping/authentication and live acceptance. Do not implement prerequisite components inside SYNC-01.

## Contracts and design decisions

The following names, tables, sequencing rules and limits are **proposed implementation decisions**, to freeze in S01. The scope and ownership requirements above come from the request and blueprint.

### Public boundary and compatibility

| Proposed boundary/record | Required behavior |
|---|---|
| `SyncSubmission` | Complete C11 plus canonical/revision references, stable evaluation timestamp, selected input-generation token, run/selection identity and publication purpose (`primary_final`, `intermediate`, `comparison`). Carries immutable source bindings, not model clients. |
| `commit_assessment_and_plan(submission)` | Validate bindings, persist the complete C11 and selection decision, and atomically persist zero or one job C12 with all required write-step/dependency records. Return assessment/operation IDs or a classified failure. Zero writes is explicit for local-only/no-change results. |
| `queue_tracked_refresh(job_id, change_token, assessment_id)` | Reuse a complete persisted selected C11 with a newer canonical availability/source snapshot. Atomically record the linkage and pending C12. Do not manufacture a new assessment or change its evaluation time to represent closure. |
| `SyncMappingConfig` | Versioned, non-secret org binding, objects, External IDs, relationships, field ownership, value mappings and serialization rules. Freeze its version/hash into each plan. |
| `SyncPlan` / `SyncWriteStep` | Versioned companions to C12: input/selection references, mapping version, immutable machine projection, company/job dependencies, numeric entity sequence, stable step UUID, step fingerprint, transmission evidence and retry/reconciliation schedule. |
| `RemoteEntityMapping` | Org + object + canonical entity UUID → External ID and Salesforce record ID, last confirmed sequence/marker and acknowledgment evidence. Separate company and job namespaces. |
| `CandidateFieldSnapshot` | Org/job/remote-ID binding, mapping version, explicit readable field set, typed values including null/empty, source modification token if available, observation time and snapshot identity/hash. Never an outbound patch. |
| `drain_due_work(budget, ownership)` / `reconcile_due_work(...)` | Bounded service calls through the gateway; return typed counts, safe errors and remaining work for RUN-01. No scheduler or unbounded background loop. |

Retain C07/C11/C12 v1 meanings and `SyncOperationState` values. Use new companion schemas at version 1.0 and explicit foreign keys. C12 `payload_fingerprint` continues to hash its canonical serialized `SyncPayload`; a separate plan/step fingerprint covers supplemental fields, mapping version, target identity and the full logical write projection, excluding the fingerprint marker itself and mutable delivery metadata. Keep `payload_version` as the serialized per-job numeric sequence for new operations; compare its separately stored integer, never strings or timestamps. Legacy arbitrary tokens such as `v1` remain readable and require migration classification before dispatch.

If implementation proves a shared model change necessary, record compatibility, schema/fixture changes and consumer migration first; incompatible changes require the blueprint decision discipline. Preserve legacy fakes/protocol consumers. A compatibility facade may delegate to the durable service, but must not offer an untracked direct-write path or collapse an unknown outcome into success.

### Mapping and ownership

| Local information | Configured remote destination | Rule |
|---|---|---|
| Canonical company UUID and canonical company record | Company External ID and mapped machine name fields | Upsert the stable identity; company rename keeps its key. Obtain current company data from its owner, not an older job's display name. |
| Canonical job UUID | Job External ID | Stable across content changes, assessment methods, retries and restarts. Salesforce record ID remains a separate mapping. |
| Company mapping | Job company lookup | Company acknowledgment/reconciliation precedes the dependent job write. Never guess a Salesforce ID. |
| C07/revision/C06 source facts | Configured title, source/application links, availability and other supported machine fields | Map only explicitly configured fields with resolvable provenance. Preserve unknown values and distinguish source dates from observed/evaluation times. |
| C11 disposition, reason, score/scale | Separate machine assessment fields | Use `final_disposition`; retain review as review. Rules-only null score/scale must explicitly clear an old LLM score where the mapped field permits null. Never convert a null score to zero. |
| Assessment method, versions, gaps/unknowns and permitted summary metadata | Configured compact machine fields, when supplied by SF-01 | Keep complete C11/evidence locally. Do not upload the full profile, raw evidence or verbose model output. Required unsupported fields fail mapping visibly; optional omissions are explicit. |
| Selected evaluation time and immutable plan identity | Evaluation timestamp and configured machine markers | Freeze once. Retry does not recalculate timestamps or create a new operation identity. Marker fields are written with the associated machine data. |
| Application progress, notes, decisions/overrides, follow-up/interview fields | Read-only candidate snapshot projection | Never include these fields in create, update, retry, reconciliation or repair patches, including as null/default. Creation defaults are SF-01's responsibility. |

Validate an allowlist at the final API-name level as well as the domain level. Reject configuration that aliases a machine property onto a candidate-owned field, duplicates destination ownership, or attempts to write a read-only field. No read-modify-write of entire remote records. Reject invalid/oversized values with a safe error unless SF-01 specifies a deterministic, visibly marked compact summary rule; do not silently truncate identifiers, URLs or reasons.

### Publication decisions

| Selected input and tracking evidence | Local result | Outbound result |
|---|---|---|
| New eligible or review job, no prior/uncertain publication | Complete C11 and selected-plan linkage | Queue initial External ID publication; review remains visibly distinct. Availability is mapped independently and never rewritten to active. |
| New rejected job, definitive evidence it has never been published | Complete C11 and local-only reason | No Company/Job publication solely for this rejected job. |
| Already tracked job, any disposition or availability | Complete C11 and new machine version if changed | Update even if rejected/unavailable; do not delete the application or reset candidate progress. |
| Availability/source change for a tracked job without a new assessment | Reference the complete selected C11 plus new canonical snapshot | Queue changed machine fields without invoking a model or fabricating an assessment. |
| Earlier initial write may have reached Salesforce, latest input is rejected | Persist both history and latest desired state | Reconcile the earlier key. If tracked, publish the rejection; if definitively never transmitted/committed, suppress creation. Absence of a local record ID is not proof of absence remotely. |
| Intermediate rules or JSON/RAG comparison result | Retain full C11 and non-publication purpose | No independently publishable C12. The chosen final result alone drives the machine projection. |
| Same selected input and same projection submitted again | Return existing linkage/operation | No new sequence or retry identity, even after an acknowledgment response was lost locally. |

“Tracked” requires durable acknowledged mapping or a verified remote match for that canonical External ID; pending/uncertain creation is a third state, not “untracked.” Validate/adopt a recovered mapping only for the expected org/object/key. Remote read failures, permissions, duplicate matches and partial query pages cannot establish absence. Missing/deleted previously mapped records require explicit repair; never silently recreate a known missing application with new candidate defaults. Document the deletion-race policy with SF-01 before live operation.

## Transaction and ordering model

| Boundary | Atomic local changes | Network behavior |
|---|---|---|
| T0 — selection registration | Register/update current input generation and expected canonical snapshot using compare-and-set. | None. RUN-01 invokes this before assessment; SYNC-01 owns validation/storage of the token, not pipeline selection. |
| T1 — assessment/plan commit | C11 or byte-equivalent existing C11; selection/linkage; publication decision; sequence allocation; C12; all company/job step dependencies and frozen payloads. | None. Failure leaves no partially published local plan. |
| T2 — claim/send intent | Compare-and-set due head/step, ownership token, attempt counters, immutable request/marker and `may_have_been_sent` evidence. | Commit before sending. Never hold a SQLite transaction open over HTTP, backoff or model work. |
| T3 — acknowledgment | Step acknowledgment/evidence, remote mapping, confirmed version, dependency release and, when all steps are confirmed, C12 success. | None. A crash before T3 means reconciliation, even if HTTP returned success. |
| T4 — retry/failure/reconciliation decision | Classified outcome, durable due time/budget, ambiguity barrier, terminal reason and any verified reconciliation evidence/mappings. | Reads/writes occur outside this transaction. |
| T5 — candidate backup | Validated field snapshot and checkpoint for that record/page together. | Read first; persist only complete validated results. Later page failure never marks a scan complete. |

Use transaction-participating repository methods and explicit locking for sequence allocation/claims. A single worker is the deployment default, not a substitute for durable ordering: reject overlapping dispatchers, require RUN-01's shared ownership boundary, and compare-and-set every claim/acknowledgment. A stale worker may not send after ownership loss or finalize another worker's claim. An expired local lease does not prove its HTTP request has stopped.

Maintain ordered lanes for both canonical jobs and shared canonical companies. A later job operation must not resend an older company snapshot after a different job advanced that company's state. Reuse an acknowledged same-version company step, or link to the required newer company step. Never use mutable names for either lane.

An uncertain transmitted step holds its entity lane and affected dependencies. Do not dispatch a newer mutation or replay that step while an older request may still commit. A remote operation marker is evidence, **not a server-enforced version condition**. A missing marker/record or elapsed timeout cannot prove a delayed request will never commit. With one mutation transmission outstanding, read-back of its exact marker and expected fields can confirm that write. Otherwise retain the barrier until a definite terminal outcome is established, or explicit recovery supplies verified server-side conditional-write/quiescence evidence. Such capability belongs to SF-01/SFCLIENT-01; do not assume it exists or implement an Apex endpoint here. If proof remains unavailable, stop bounded automation with inspectable unresolved work rather than risk a stale overwrite.

## Ordered stories

All stories belong to **SYNC-01**. Paths beginning `salesforce/`, `storage/` or `contracts/` below are relative to `src/job_automation/`; root `salesforce/` metadata is not owned here. Shared-file changes are narrow integration work, not ownership transfers.

| Order | Story | Dependencies | Result |
|---|---|---|---|
| 1 | SYNC-01-S01 | DATA-01, MATCH-01; SF-01/SFCLIENT-01 prerequisite inventory | Frozen contracts, ownership and compatibility decisions |
| 2 | SYNC-01-S02 | S01; SF-01 mapping specification, synthetic for offline tests | Validated mapping and immutable projections |
| 3 | SYNC-01-S03 | S01–S02, DATA-01 | Transactional storage for plans, ordering, mappings and backups |
| 4 | SYNC-01-S04 | S02–S03, MATCH-01; selection contract with RUN-01 | Atomic assessment publication and tracked refresh service |
| 5 | SYNC-01-S05 | S02–S03; SFCLIENT typed reads | Candidate-owned field preservation and local backup |
| 6 | SYNC-01-S06 | S04–S05; SFCLIENT typed mutations | Ordered External ID delivery with durable acknowledgments |
| 7 | SYNC-01-S07 | S06; SF-01 marker/read capabilities | Lost-response reconciliation and stale-write prevention |
| 8 | SYNC-01-S08 | S06–S07; SFCLIENT failure/budget contract | Bounded retries, recovery and safe operational results |
| 9 | SYNC-01-S09 | S01–S08; actual SF-01/SFCLIENT for live gate | Crash matrix, Windows verification and component handoff |

### SYNC-01-S01 — Freeze submission, mapping and recovery contracts

**Objective / requirements.** Establish one method-independent C11-to-C12 boundary with explicit publication authority, ownership and recovery semantics. R04/R08/R09/R16.

**Inputs → outputs.** Current contracts, dependency evidence and the design tables above → versioned companion records/ports, schema fixtures, compatibility table and explicit missing-prerequisite report.

**Dependencies.** DATA-01 and MATCH-01; inspect actual SF-01/SFCLIENT handoffs when available. Do not substitute the client story plan for implementation evidence.

**Owned files.** Proposed `salesforce/{sync_records,sync_ports,sync_errors}.py`; narrow `contracts/export_schemas.py` registration and `contracts/interfaces.py` documentation if needed; new companion schemas under `schemas/v1/`; `tests/salesforce/sync/test_contracts.py`, `tests/fixtures/salesforce/sync/`.

**Tasks.**

1. Freeze `SyncSubmission`, selection registration, immutable plan/step, remote mapping, candidate snapshot and result contracts. Define explicit publication authority; evaluation method does not select the winner.
2. Resolve C11 posting revision strings through existing owner-provided bindings (UUID/hash representations where supported). Validate job/revision/profile/policy linkage and reject mismatched snapshots. Do not assume all revision strings are UUIDs or compare different hash meanings.
3. Define stable selection/input fingerprints and service idempotency keys independent of transport attempts. Register the active generation before evaluation; an older late completion cannot become current merely by committing last. Persist stale/comparison results locally without promoting them.
4. Specify required gateway outcomes and exact SF-01 mapping/marker evidence. Use explicit fake ports until available; preserve C12 v1 and legacy consumers.

**Transaction boundary.** Contract validation is pure. T0 owns selection registration; later stories implement T1–T5. Construction/import performs no storage or network work.

**Acceptance criteria.** Rules-only C11 with null metadata and valid LLM JSON/RAG C11 use the same submission API. Intermediate/comparison submissions cannot request independent publication. Extra candidate-write fields, ambiguous selection, invalid bindings and unsupported contract versions fail before enqueue/send.

**Crash/lost-response tests.** Round-trip a submission/plan across restart and prove identities survive; repeat a selection-registration request after its local reply is lost and recover the same token. Validation failure creates no outbox row. Test a late old-generation result after a newer generation is registered.

**Migration/configuration/handoff.** No database migration yet. Publish schema versions, ownership matrix, required dependency evidence and consumer guidance. Numerical defaults in S08 remain configurable proposals.

### SYNC-01-S02 — Map canonical entities and enforce machine-field ownership

**Objective / requirements.** Produce deterministic, schema-valid Company/Job projections for the configured org. R04/R08/R15.

**Inputs → outputs.** Complete selected C11, C07/company/source snapshots and versioned mapping → immutable C12 payload plus company/job write projections or a classified mapping error.

**Dependencies.** S01 and SF-01 schema contract; synthetic renamed objects/fields are sufficient for offline tests.

**Owned files.** `salesforce/{sync_mapping,sync_settings,sync_serialization}.py`; `config/sync.example.json`; narrow optional configuration integration in `configuration.py`; `tests/salesforce/sync/{test_mapping,test_ownership,test_settings}.py` and mapping fixtures.

**Tasks.**

1. Implement the mapping/ownership table, including enum/picklist conversion, null versus omitted fields, score/scale clearing, URL ordering and timezone/date precision. Use canonical company data and stable UUID keys; no fallback name-derived identities.
2. Validate required External ID uniqueness, lookup and marker field capabilities against SF-01 evidence and explicit gateway describe results. Cache/version that evidence; no live calls during config loading. Reject changed org bindings or mapping drift before a send.
3. Make company identity absence explicit: permit an omitted relationship only if SF-01 permits it, otherwise retain the assessment with a visible planning failure. Do not invent an employer or create a Company keyed by name.
4. Freeze all values and mapping hashes. Keep C12 and full-plan fingerprints distinct. Exclude attempt times, retry counters and unrelated candidate backups from semantic deduplication.
5. Validate the final API field set against ownership on every dispatch/repair path. Config changes require a new explicit machine version; they cannot silently remap an existing queued payload.

**Transaction boundary.** Pure mapping before T1; T1 revalidates the expected source generation. Runtime mapping validation never performs a remote mutation.

**Acceptance criteria.** Default and renamed synthetic schemas yield equivalent logical data. Company renames retain keys. Review/rejected/availability values remain independent from application progress. LLM-to-rules transitions clear stale scores/model summary fields where configured. Unknown salary/deadline values stay unknown.

**Crash/lost-response tests.** Serialize/reload a plan after configuration changes and verify it retains its original projection and identity or is explicitly blocked for repair. Repeat mapping with identical inputs and compare bytes/hashes. Rejection of an ownership collision produces zero gateway calls, including on replay.

**Migration/configuration/handoff.** Add optional non-secret sync settings without requiring Salesforce for unrelated commands. Record mapped fields, compacting rules and required capability evidence; create no org metadata.

### SYNC-01-S03 — Extend durable storage and atomic transaction participation

**Objective / requirements.** Persist the complete local protocol without partial commits or sequence races. R04/R09/R16.

**Inputs → outputs.** Existing schema and C11/C12 records → migrated storage with selection heads, immutable plans/steps, entity sequences, remote mappings, attempt/reconciliation evidence and candidate snapshots.

**Dependencies.** S01–S02 and DATA-01.

**Owned files.** `storage/migrations.py`, `storage/repositories/{sync_outbox,assessments}.py`; proposed `storage/repositories/{sync_state,candidate_snapshots}.py`; narrow engine/repository exports and `storage/connection.py` integration; `tests/storage/{test_sync_migrations,test_sync_transactions,test_sync_claims}.py`.

**Tasks.**

1. Append the next migration after current 006 (recheck numbering at implementation). Add companion tables with schema versions and foreign keys for C11/C12 links, frozen plans/steps, selected generations, entity heads/mappings, durable retry/ambiguity evidence and snapshots/checkpoints. Keep existing migration checksums unchanged.
2. Enforce uniqueness of org/object/canonical identity, entity sequence and selected-intent idempotency key. Store integer sequences and confirmed high-water marks; allocate atomically under a write lock. Shared company steps have their own sequence and dependencies.
3. Extend the existing atomic helper or delegate it to one transaction-participating implementation. Preserve its public compatibility. All plan inserts, sequence updates and linkages participate in the caller transaction; nested `with self.conn` must not commit early.
4. Add bounded due queries, compare-and-set claims/completions, append-only attempt evidence and backup persistence. An acknowledgment must identify its claim, operation, step, target and expected version.
5. Classify legacy rows. Preserve payloads/IDs and acknowledgments. Do not infer ordering from arbitrary old tokens or assume legacy running/retry-wait rows were never sent. Hold ambiguous legacy work for reconciliation; do not erase it to satisfy new constraints.

**Transaction boundary.** Implement T0–T5 primitives. Plan allocation and deduplication share T1. No repository invokes the gateway.

**Acceptance criteria.** Two connections cannot allocate the same entity version or claim the same step. Rollback leaves neither a new C11 nor any partial plan/sequence advance. A standalone local-only assessment is supported. Repeated identical identity returns existing data; same identity with different content is an explicit conflict.

**Crash/lost-response tests.** Interrupt migration and reopen; inject failure after C11, after C12, after a company dependency and after an inner repository returns. Observe from another connection that nothing leaked. Lose the T1 response after commit and recover the existing plan. Crash during T3: either all mapping/ack/head changes commit or none do. Test legacy-row migration and failed uniqueness preflight without data loss.

**Migration/configuration/handoff.** Document upgrade classification and rollback/recovery procedures, current schema number and touched consumers. Process-crash tests do not prove power-loss durability; record the existing WAL/`synchronous=NORMAL` limit and coordinate stronger durability policy with DATA-01/OPS-01 if required.

### SYNC-01-S04 — Commit selected assessments and publication plans atomically

**Objective / requirements.** Implement publication eligibility and continued tracked-job updates through one durable boundary. R04/R08/R09/R16.

**Inputs → outputs.** `SyncSubmission`, authoritative tracking evidence and current selection head → complete persisted C11 plus queued C12, explicit local-only result, no-change linkage or safe planning failure.

**Dependencies.** S02–S03, MATCH-01 and the S01 selection contract for RUN-01. MATCH-02 implementation is not required for contract fixtures.

**Owned files.** `salesforce/{sync_service,sync_publication,sync_identity}.py`; narrow storage service wiring; `tests/salesforce/sync/{test_publication,test_atomic_submission,test_refresh,test_selection}.py`; affected `tests/assessment/test_consumer_boundary.py`.

**Tasks.**

1. Implement the publication table, using complete C11 from either method. Retain assessment evidence/gaps/unknowns locally; never reevaluate or silently change disposition in sync.
2. In T1, validate current selection/canonical snapshots, persist C11, allocate plan versions and record all dependencies. If C11 already exists, require identical content before attaching a plan. Do not call `save_assessment()` first and enqueue later on the normal primary path.
3. Record recoverable planning failures and stale/non-primary decisions locally with no misleading pending-success promise. Eligible/review inputs lacking configuration remain visibly unpublished and can be planned later by the same idempotent service.
4. Support authoritative availability/source changes for tracked jobs using their selected complete C11. Freeze assessment evaluation time separately from projection/change time. Reject attempts to relabel a prior assessment as evaluating a different revision.
5. Suppress unsent obsolete initial publications when the latest selected result is rejected. If any job step may have been sent, retain the uncertainty barrier and latest desired state; reconciliation decides whether a tracked update is required. Never discard candidate tracking because the record ID has not yet been saved.

**Transaction boundary.** T1 for each selection and for each tracked refresh. No network call inside it. Any external tracking lookup is done outside and bound to durable evidence; unresolved identity yields a blocked planning result, not a guessed absence.

**Acceptance criteria.** New eligible/review jobs enqueue; new confirmed rejects stay local. Tracked eligible → rejected, active → unavailable and unavailable → active queue changed machine data. No-change resubmission produces one logical operation. Rules and LLM results obey identical publication rules; comparison results cannot win by being saved last.

**Crash/lost-response tests.** Crash between each T1 statement; reopen and verify all-or-nothing. Lose the caller response after commit and resubmit with the same intent. Queue eligible v1, accept rejected v2 before v1 is sent, and verify no initial job creation; repeat with v1 uncertain and verify reconciliation precedes any decision to suppress/update. Submit stale revision/profile/policy selections and assert no newer projection is replaced.

**Migration/configuration/handoff.** No new schema beyond S03. Document the service RUN-01 must call, replacing the MATCH-01 handoff's standalone-save recipe for publishable primary results. RUN-01 pipeline/CLI implementation remains outside scope.

### SYNC-01-S05 — Preserve and back up candidate-owned fields

**Objective / requirements.** Keep candidate edits authoritative in Salesforce and durably readable locally. R08/R09/R15/R16.

**Inputs → outputs.** Verified tracked mappings and explicit field-read projections → versioned local candidate snapshots, per-record/page checkpoints and backup freshness/error status.

**Dependencies.** S02–S03 and SFCLIENT typed reads; SF-01 ownership/read permissions.

**Owned files.** `salesforce/{candidate_backup,sync_read_projection}.py`; S03 snapshot repository integration; `tests/salesforce/sync/{test_candidate_backup,test_candidate_preservation}.py` and synthetic candidate-field fixtures.

**Tasks.**

1. Read configured status, notes, decisions/overrides and follow-up/interview values for tracked jobs before their machine update; commit the validated snapshot before dispatch. For newly created rows, read back creation defaults after acknowledgment. Failure of that read leaves backup work pending without replaying the acknowledged write.
2. Offer a bounded backup pass for all tracked jobs, including unchanged/rejected/unavailable jobs. RUN-01 can invoke it independently of outbound changes; no scheduler belongs here.
3. Preserve field presence, explicit null/empty, source modification token and observation timestamp. Missing permission/field is an incomplete read, not a null value. Deduplicate identical observations without losing latest-observed metadata; retain distinguishable versions of candidate changes locally.
4. Persist each validated snapshot and its scan checkpoint in T5. A later-page failure retains earlier snapshots but marks the scan incomplete. Preserve the last good snapshot on not-found/read/validation failure.
5. Keep snapshot values out of outbound mapping and normal logs. Backups are observations, not a bidirectional sync or automatic restore. Candidate edits after a read are preserved because outbound writes exclude those fields; a future backup observes them.

**Transaction boundary.** Read outside SQLite; T5 commits snapshots/checkpoints. Backup freshness and C12 acknowledgment are separate states. A required pre-write read failure defers that tracked write with a visible reason.

**Acceptance criteria.** Candidate can change status, notes, overrides and follow-ups between read and patch; every value survives. A later backup records those changes. Known empty and unknown remain distinct. No machine update is needed to refresh candidate backups.

**Crash/lost-response tests.** Crash after read/before snapshot commit and repeat safely; crash after snapshot/before checkpoint and prove atomicity; fail page two without marking full completion. Lose the response to an acknowledged create, reconcile it, then capture defaults without recreating. Inject a backup failure after an acknowledged update and verify no mutation is repeated for that reason.

**Migration/configuration/handoff.** Snapshot fields/storage are introduced by S03. Document local privacy, freshness and retention requirements for OPS-01, including that a snapshot can lag live edits and a same-disk backup does not protect against disk loss. No automatic Salesforce restore or deletion tooling.

### SYNC-01-S06 — Dispatch ordered External ID writes and commit acknowledgments

**Objective / requirements.** Deliver company/job plans in dependency order through SFCLIENT with durable progress. R04/R08/R16.

**Inputs → outputs.** Due validated C12 plans and worker ownership → typed gateway requests, committed step acknowledgments/mappings and terminal or pending C12 outcomes.

**Dependencies.** S04–S05 and SFCLIENT's actual V2 contract. Offline integration uses a stateful gateway fake implementing that contract.

**Owned files.** `salesforce/{sync_dispatch,sync_acknowledgment}.py`; narrow `salesforce/__init__.py` composition; `tests/salesforce/sync/{test_dispatch,test_dependencies,test_acknowledgments,test_consumer_boundary}.py`; `tests/fakes/salesforce_sync.py`.

**Tasks.**

1. Claim only the eligible head of an entity lane with current ownership, due time and remaining budget. Commit T2 send intent before each physical mutation; mark the step potentially sent even if a crash happens before the call begins.
2. Upsert Company by its stable External ID first, persist its ID/evidence in T3, then bind the Job lookup and upsert Job by its stable External ID. Persist resolved request bytes before send; retry reuses them. Never generate a new entity/step/operation UUID because a response was lost.
3. Handle shared companies by entity sequence and durable dependency reuse. An old job plan cannot overwrite a newer company name. A valid acknowledgment of a newer company version can satisfy an older relationship-only dependency without replaying old company values.
4. Accept only acknowledgments for the expected org/object/External ID, step and version. Commit mapping, acknowledgment and confirmed head together. C12 succeeds only after all required writes are confirmed; backup completion remains separately visible.
5. Recheck ownership, lane and immutable plan immediately before send. Prevent overlapping dispatcher use and late callbacks from finalizing another claim. Do not replace this with an in-memory sort or assume one CLI process excludes another.

**Transaction boundary.** T2 → network → T3/T4 for each step. The company and job writes are not one Salesforce transaction; a committed company with a pending job is a valid recoverable intermediate state. Do not compensate by deleting the company.

**Acceptance criteria.** Company acknowledgment precedes job lookup use. Two jobs share one logical company. Restart after a company acknowledgment resumes the job step without unnecessarily resending company data. Repeated attempts preserve External IDs and candidate-owned fields. Permanent failure is not represented as success.

**Crash/lost-response tests.** Crash before/after T2, after Company commit but before response, between Company T3 and Job T2, and after Job response but before T3. A second worker cannot claim/send the same lane. A stale callback cannot lower a confirmed version. Count logical records and physical sends separately.

**Migration/configuration/handoff.** Use S03 storage and S08 budgets. Record real gateway signatures and response semantics in the eventual handoff; do not implement authentication, raw HTTP or org automation here.

### SYNC-01-S07 — Reconcile uncertain outcomes and prevent stale overwrites

**Objective / requirements.** Recover lost responses without duplicates or older machine data overtaking newer values. R04/R08/R16.

**Inputs → outputs.** Unfinished/ambiguous steps, immutable fingerprints, known mappings and read-back evidence → verified acknowledgments, continued barriers, safe retry eligibility or explicit conflicts.

**Dependencies.** S06, SFCLIENT read/outcome semantics and SF-01 reconciliation-field capabilities.

**Owned files.** `salesforce/{sync_reconciliation,sync_ordering}.py`; guarded outbox recovery integration; `tests/salesforce/sync/{test_reconciliation,test_stale_writes,test_restart}.py`.

**Tasks.**

1. Treat interrupted running/send-intent steps and post-transmission timeout/5xx/malformed acknowledgments as unknown. Read by the immutable External ID, validating remote ID, marker/version and expected machine fields. A record's mere existence is not acknowledgment of the current version.
2. Matching operation/step marker and projection confirms the outstanding write; save evidence, mapping, head and C12/step transition in one T3. Same-version different fingerprint, duplicate key matches, wrong org/object/key or unexpected newer remote version is a conflict, not permission to overwrite.
3. If a newer remote version is verified against known local history, advance/adopt only that validated evidence and classify the older unsent work as superseded. Preserve C12 state compatibility: use `failed` with a nonretryable `superseded` terminal reason in companion metadata, not `succeeded` for a write never delivered. Do not introduce a hidden sixth C12 state.
4. Enforce the uncertainty barrier described above. A not-found read, older remote marker or local deadline expiry cannot authorize replay or release a newer write while the old request may still execute. Keep repair-required work visible after bounded reconciliation exhaustion. Unrelated entity lanes may continue.
5. Before every retry and repair action, compare selected desired version, confirmed head, mapping version and dependency state. Never requeue a known obsolete machine payload. A terminal unsent/definitely rejected version can be superseded; an uncertain transmitted version cannot be discarded to unblock a newer version.
6. On startup and after restoring an older local database, reconcile remote identity/version evidence before dispatch. Unknown remote versions/newer remote state require repair/adoption evidence, not resetting remote markers to the restored counter. Preserve candidate backups and merge lineage; do not merge/delete remote applications automatically.

**Transaction boundary.** Read outside transactions; commit evidence and barrier/head changes in T3/T4. Startup recovery must not expose unknown work as ordinary due retry-wait without its barrier metadata.

**Acceptance criteria.** A committed write with a lost response produces one logical Job and can be acknowledged from read-back. Once v2 is confirmed, v1 never sends again. If v1 is still in flight, v2 cannot send. Remote version fields are not claimed to be an atomic compare-and-set unless the prerequisite owners actually provide and verify that capability.

**Crash/lost-response tests.** Simulate v1 committing after client timeout and after a read initially returns absent; assert v2 stays unsent until v1 is confirmed. Lose the reconciliation response and repeat read-only. Crash after reconciliation read/before T3 and reopen. Inject delayed old acknowledgments after v2, restored counters below remote versions, conflicting fingerprints and two remote matches. For unresolvable ambiguity, assert bounded reads, retained barrier and no stale replay.

**Migration/configuration/handoff.** Reuse S03 evidence/barriers. Document exact reconciliation proof requirements, the conservative blocked case and the prerequisite escalation path. No promise of automatic convergence during permanent ambiguity, missing access or exhausted capacity.

### SYNC-01-S08 — Bound retries and expose safe recovery results

**Objective / requirements.** Keep transient work recoverable without unbounded retries, duplicate sends or hidden failures. R09/R14/R15/R16.

**Inputs → outputs.** Typed gateway outcome, durable attempts/due times and drain budget → scheduled retry, reconciliation, succeeded operation or inspectable terminal repair result.

**Dependencies.** S06–S07 and SFCLIENT error classification/budget contract.

**Owned files.** `salesforce/{sync_retry,sync_recovery,sync_diagnostics}.py`; settings/service integration; `tests/salesforce/sync/{test_retry,test_budgets,test_recovery,test_safe_diagnostics}.py`.

**Tasks.**

1. Keep the five C12 states. Pending → running happens on claim; confirmed completion → succeeded; safely retryable failure → retry_wait with due time; permanent/exhausted → failed with a durable reason. Unknown outcomes carry a reconciliation barrier even when retry-wait/failed. Terminal exhaustion never removes that barrier by itself.
2. Propose `max_attempts=3` delivery rounds per C12, at most one Company and one Job mutation per round; each step has persisted send counts, including requests rejected by auth. Thus no more than `2 * max_attempts` mutation transmissions for an unshared two-step plan. Reused company steps retain their own budget and are not reset by new dependent jobs. Freeze exact accounting in S01/S08 and expose both round and physical-send counts.
3. Ask SFCLIENT for at most one mutation resource send per call, with automatic mutation replay disabled. Its finite auth/read budget is further constrained by the drain deadline. If the actual gateway cannot enforce this cap, resolve that prerequisite before dispatch; do not multiply its internal retry loop by C12 attempts.
4. Proposed retry delay: exponential 5-second base, 300-second cap and injected jitter; persist UTC `next_attempt_at`. Honor a later gateway retry-not-before value without shortening it. Use monotonic call deadlines and injected clocks. Proposed drain ceiling: 100 operations or 60 seconds, whichever arrives first, with no new call beyond the remaining budget.
5. Bound reconciliation separately (proposed six reads per uncertain step before repair-required) and backup pages/records per invocation. A restart does not reset attempts or create a new operation. Explicit repair authorization records a new bounded recovery allowance and evidence while retaining original identity/history; it cannot bypass ordering.
6. Retry only definite safe pre-send/rejected transient failures. Permission, invalid mapping/validation and ambiguous duplicate identity require repair; auth repair stays with SFCLIENT/SF-02. Quota returns deferred work, capacity remains inspectable, and unknown transmission enters S07. No automatic delete, permission expansion or credential fallback.
7. Return operation/step counts, backup freshness, pending/failed/ambiguous work and classified safe errors to RUN-01. Diagnostics include IDs, versions, bounded codes and timings; omit credentials, candidate values, raw job/profile text and remote response bodies.

**Transaction boundary.** Commit T2 counters before send and T4 due times/errors before returning. No sleeps in a database transaction. Waiting for a future due time ends the bounded service invocation.

**Acceptance criteria.** Retry schedule/counters survive restart and exact-limit tests. Authentication/read helpers cannot defeat the aggregate budget. Failure of logging or backup reporting after T3 never triggers another mutation. Reconciliation exhaustion stops automation while preserving the lane barrier and latest desired state.

**Crash/lost-response tests.** Crash after failed send/before T4, after due-time commit/before return and at the final attempt. Restart before/after due time; test Retry-After beyond the drain deadline and clock rollback. Combine renewal, quota, transient service failures and unknown mutation outcome without resetting budgets. Inject logging failures and secret/candidate sentinels.

**Migration/configuration/handoff.** Use S03 scheduling columns; document retry units/defaults, operator-visible repair reasons and RUN-01 recovery hooks. Do not build RUN-01 CLI, OPS backup commands, scheduling or notifications.

### SYNC-01-S09 — Verify recovery on Windows and hand off

**Objective / requirements.** Demonstrate the specified guarantees with real storage and a stateful remote fake, then distinguish native Windows/live evidence from offline checks. R04/R08/R09/R14/R15/R16.

**Inputs → outputs.** Completed S01–S08, dependency handoffs and test evidence → `docs/components/SYNC-01.md` with exact contracts, migration, limits, verification and pending gates.

**Dependencies.** S01–S08; actual SF-01/SFCLIENT/SF-02 evidence for live verification only.

**Owned files.** `tests/salesforce/sync/{test_end_to_end,test_crash_matrix,test_windows_paths,test_windows_restart}.py`; `tests/manual/sync_smoke.py`; `docs/components/SYNC-01.md`; narrow README verification notes if useful.

**Tasks.**

1. Run production mapper/storage/dispatcher/reconciler composition against a stateful fake with independent remote storage, explicit commit timing, delayed responses, candidate edits and physical-send counters. Restart by reopening SQLite and, for crash tests, terminating a child process at controlled boundaries; an exception-only rollback test is insufficient.
2. Cover every crash case below with rules and representative LLM fixtures. Assert remote rows, field values, local C11/C12/linkages, versions, attempts, barriers and snapshots rather than only return codes.
3. Verify native Windows paths with spaces/non-ASCII characters, different working directory, interrupted SQLite connections and handle release. Keep runtime data outside source files, use `pathlib.Path` and finite service calls. Logged-out scheduling remains Phase 2.
4. Provide a separate opt-in smoke path, read-only by default. Live mutation requires the existing authorized org/configuration and an explicitly scoped synthetic Company/Job fixture with exact allowed fields and call/runtime limits. Inspect keys first, stop on collisions or unexpected automation, and follow the existing authorization. This planning document authorizes no org changes.
5. With a permitted fixture, demonstrate stable-key rerun, changed machine fields, review → rejected and active → unavailable while candidate test values survive; verify local snapshots and remote read-back. Inject lost responses, permission failures and quota errors in fakes rather than damaging the live org. Fixture cleanup is only within its explicit authorization.
6. Record offline, native Windows and live statuses separately. Missing prerequisite handoffs remain named gates. Hand off to RUN-01 for integration and OPS-01 for backup/restore/retention, with MATCH-02 as a future producer of the same C11 boundary.

**Transaction boundary.** Verify T0–T5 and the absence of a distributed transaction. Live reads do not establish local atomicity; local tests do not establish actual org permissions or automation behavior.

**Acceptance criteria.** Required recovery cases pass with one logical remote row per canonical key, correct latest machine data and intact candidate fields. No exactly-once network/automation claim. The component is marked VERIFIED only for demonstrated acceptance, with live gaps explicitly stated; fake-only completion is not G1 end-to-end completion.

**Crash/lost-response tests.** Execute the matrix below through the production service composition with a separately persistent fake remote and controlled process termination. Keep the remote state alive across local restarts; verify the final field values, operation identities, acknowledgment evidence and physical-send counts for each case. Do not induce crashes or lost responses against the live org.

**Migration/configuration/handoff.** Record every owned file, final contract/schema version, migration number, gateway/API mapping evidence, actual commands/results, configured budgets, unresolved limitations and next consumer. No application code or component handoff is created by this story-planning task.

## Required crash and lost-response matrix

| Failure point / scenario | Required recovery assertion |
|---|---|
| Before T1; after C11 insert; after any dependent plan insert | No partial C11/C12 plan or sequence advance; explicit local-only outcomes are distinguishable. |
| T1 committed, caller response lost | Same submission returns the same persisted IDs; no second logical intent. |
| T2 committed, process dies before invoking gateway | Conservatively unknown send intent; no blind replay. Recovery may require proof/repair because the database alone cannot locate the crash within that interval. |
| Company commits, response lost | Job waits; Company External ID/marker reconciliation saves the mapping; one logical company. |
| Company acknowledged, job not yet sent | Resume the job dependency; do not roll back/delete company or replay stale company fields. |
| Job commits, response lost or malformed | Read exact key/marker/projection, atomically acknowledge existing row; no new key or candidate default reset. |
| HTTP acknowledgment received, T3 fails | Treat local completion as unknown; reconcile, then commit mapping/head/state together. |
| v1 delayed after timeout; v2 queued | v2 cannot send while v1 may still execute. An absent/older read does not release the barrier. |
| v2 confirmed; old retry/late callback surfaces | No v1 transmission and no lowering of local/remote confirmed version. |
| New initial eligible v1 becomes rejected before send | Suppress unsent publication; keep C11 history. If v1 was uncertain, reconcile first and update rejection if remotely tracked. |
| Shared company updated by another job | Old job step cannot regress company data; dependent relationship resolves to verified mapping. |
| Candidate changes all owned fields during machine update | Remote edits survive; later backup observes them. No entire-record write or candidate field nulling. |
| Backup read succeeds, T5 fails; later page fails | Retry read safely; preserve last good snapshots and resumable incomplete checkpoint. |
| Retry/reconciliation limit reached; process restarts | Attempts remain exhausted; work/error/barrier remain inspectable; no automatic counter reset. |
| Restore older local DB or encounter newer remote marker | Reconcile/adopt only verified history or require repair; never send an older payload to overwrite newer remote data. |
| Missing record, permission error, partial page or duplicate External ID | Distinct outcomes; none becomes proof to create a replacement application. |

## Planned verification and completion checklist

These commands are **future implementation checks**, not tests run or passed during story planning. Proposed files must exist before invoking their checks from native PowerShell:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests\salesforce\sync tests\storage tests\contracts tests\assessment\test_consumer_boundary.py tests\test_configuration.py
& ".\.venv\Scripts\python.exe" -m pytest tests\salesforce\sync\test_windows_paths.py tests\salesforce\sync\test_windows_restart.py

# Proposed smoke entry point; read-only default, after prerequisite configuration exists.
$syncSmokeConfig = Join-Path $env:LOCALAPPDATA "Job Automation Prüfung ä\app.json"
& ".\.venv\Scripts\python.exe" ".\tests\manual\sync_smoke.py" --config $syncSmokeConfig
```

Freeze the actual smoke arguments during implementation. Never put credentials or real candidate values on the command line. Regenerate only affected companion schemas and confirm existing C11/C12 fixtures remain compatible.

- [ ] Complete C11 from rules and LLM enters one selected-final boundary; comparisons/intermediate results do not race publication.
- [ ] Required mappings come from SF-01; defaults are not mistaken for verified org metadata.
- [ ] C11, C12, sequence allocation and dependencies commit atomically; nested repository writes cannot commit early.
- [ ] Initial eligible/review publication and subsequent rejected/unavailable updates pass independently.
- [ ] Candidate fields are excluded from every outbound path and locally backed up even for unchanged tracked jobs.
- [ ] Stable UUID/External ID identities, company-before-job dependencies and shared-company ordering survive restart.
- [ ] Unknown outcomes retain barriers; stale retries cannot overwrite newer machine data.
- [ ] Attempts, deadlines, reconciliation and scan sizes are bounded and persist across restart.
- [ ] Actual native Windows and live service evidence are distinguished from fake integration.
- [ ] Missing SF-01/SFCLIENT handoffs, unresolved ambiguity and operational limits remain explicit.
- [ ] No OAuth setup, metadata deployment, assessment implementation, full pipeline, scheduling, generation or automatic application submission enters SYNC-01.

Planning result: this document defines implementation work only. No application code, credentials, live Salesforce records or metadata were changed, and no implementation verification is claimed.
