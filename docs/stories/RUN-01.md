# RUN-01 — Manual Windows pipeline and recovery

Status: **PLANNED — implementation stories only**  
Date: **29 October 2026**  
Phase: **0 / P0**  
Scope: **RUN-01 only**  
Requirements: **R02–R09, R16**, with **R14/R15** constraints  
Dependencies: **DATA-01, INGEST-01, INGEST-02, IDENTITY-01, IDENTITY-02, MATCH-01, SYNC-01**; **MATCH-02** for LLM-enabled execution.

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially §§3–9. Wire existing components into one manually invoked, bounded Windows pipeline: fetch and preserve raw input → normalize or quarantine → resolve identities/revisions → reconcile availability → assess → synchronize → persist C15. Deliver the deterministic route first, then use the same run, selection and publication boundaries for LLM assessment.

RUN-01 owns orchestration, process ownership, stage checkpoints, restart reconciliation, input-version invalidation and summaries. It does not replace source adapters, normalization rules, identity/availability policy, assessment composition, context retrieval, model transport, Salesforce mapping or the outbox protocol. Preserve a callable entry point, stable IDs and a summary-reader boundary for future automation. Scheduling, notifications, automatic drafting, generation workers and Salesforce metadata deployment remain outside this component.

## Repository evidence, refreshed after implementation updates

Read the blueprint, [README](../../README.md), [schema instructions](../../schemas/README.md), prerequisite handoffs and their current implementations. No applicable `AGENTS.md` was found in the checked ancestors or repository; the user-level `.codex/AGENTS.md` was empty. Documentation paths use `/`; runnable commands use native PowerShell paths. Generate shared schemas from their typed models, never by hand-editing generated JSON.

The repository was checked again after the user's update. **MATCH-02, SFCLIENT-01 and SYNC-01 now exist as code and handoffs.** Earlier story-plan statements that these implementations are absent are superseded by the evidence below. Historical test totals in handoffs are not checks executed by this planning task.

| Dependency / current evidence | RUN-01 consequence |
|---|---|
| [DATA-01 handoff](../components/DATA-01.md), `storage/engine.py`, `storage/repositories/runs.py`, `storage/connection.py`, `storage/migrations.py` | Reuse the storage engine and ledger. Migrations now run through **007**, including SYNC-01 tables. Append the next available migration after rechecking; preserve existing checksums. `get_run()` synthesizes a failed terminal-looking C15 for an unfinished row; use explicit execution-state reads for running work. C15 is a terminal summary, not a running-state record. |
| [INGEST-01 handoff](../components/INGEST-01.md), `ingestion/{controller,pagination,persistence,models}.py` | Call `FetchController.run_fetch(run_id, source_keys, resume)` or its checked per-source entry point. `SourceFetchResult.receipts` contains mapped drafts, but `commit_page()` currently persists raw rows and a cursor checkpoint, not the full receipt/draft history. A repeated source key with changed raw hash is skipped in `raw_postings`; do not use that table as the authoritative current observation stream. Durable replay needs the gate below. |
| [INGEST-02 handoff](../components/INGEST-02.md), `ingestion/normalization/{service,ports,models,quarantine}.py` | `DefaultNormalizer.normalize(draft)` returns `(posting_or_none, issues)`. Persist versioned successful outputs and `QuarantineHandoff` records through a RUN-owned work repository; normalization itself does not provide a durable queue. Use verified raw provenance, including when replaying. |
| [IDENTITY-01 handoff](../components/IDENTITY-01.md), `identity/{service,hashing,revisions}.py`, canonical and identity repositories | `IdentityService.resolve_and_commit(C06)` returns `IdentityResolutionResult`. Canonical/revision identity is reusable, but each call allocates a fresh observation UUID. C07 contains revision metadata, not the full description/compensation snapshot. `normalized_postings` is source-key unique and inserts rather than maintaining revision snapshots. RUN must preserve exact C06-to-revision bindings and close the observation/checkpoint crash gap. |
| [IDENTITY-02 handoff](../components/IDENTITY-02.md), `identity/availability/{service,evidence}.py` | Actual signature is `AvailabilityService.process_manifest(FetchManifest, source_config=None)`. Actual enums are `FetchOutcome` and `InventorySemantics`; handoff references to `RunManifest`, `ManifestStatus` and `FeedType` are stale. Pass the frozen actual `SourceConfig`. Consumption is keyed by run/source/scope; same-outcome partial replays can return early. Process only a sealed traversal for availability, after its identity work is settled. |
| [MATCH-01 handoff](../components/MATCH-01.md), `assessment/{service,inputs,composition}.py` | Use fully bound `AssessmentService.evaluate_posting(...)` or `evaluate_deterministic_with_trace(...)`. Supply a durable execution/assessment ID. Do not use the legacy evaluator's synthetic posting/profile fallback. Preserve the complete rejection decision, including exclusions and eligibility checks outside `rule_outcomes`. |
| [MATCH-02 handoff](../components/MATCH-02.md), `assessment/{llm_service,llm_records,llm_inputs,context_bridge}.py` | Implemented. Use `LLMAssessmentService.assess(AssessmentRequest) -> AssessmentRunResult`; success carries C11, pending carries no completed assessment. The legacy adapter intentionally fails without full bindings. The handoff retains live acceptance as pending despite recording a local smoke run; do not equate that smoke with production/model-quality verification. |
| [CONTEXT-04 handoff](../components/CONTEXT-04.md), `context/{selector,selector_records}.py`; [LLM-01](../components/LLM-01.md) | Shared JSON/RAG selector exists. Bind the real selector and model provider through MATCH-02. Validate exact job binding, whole-prompt admission and index/model versions at the integration gate; do not implement a second selector or prompt renderer in RUN. |
| [SYNC-01 handoff](../components/SYNC-01.md), `salesforce/{sync_ports,sync_records,sync_service,sync_dispatch,sync_reconciliation,candidate_backup}.py`, `storage/repositories/sync_state.py` | Implemented with selection registration, atomic C11/plan storage, dispatcher, reconciler and candidate snapshots. Use these APIs. The handoff's Phase 1 label does not move SYNC/RUN out of blueprint Phase 0; its background/scheduled backup wording does not authorize scheduling. |
| [SFCLIENT-01 handoff](../components/SFCLIENT-01.md), `salesforce/{gateway,budget,configuration}.py` | Typed gateway and protected credential access exist. Actual SF-01/SF-02 handoffs and live org acceptance remain pending. Absence of repository metadata is not proof that the existing org lacks assets. No org changes are authorized by this plan. |
| Current package tree and CLI | No `orchestration/` package or manual end-to-end run command exists at this inspection. The existing commands are component commands. Production dependencies must be constructed explicitly; test fakes stay under `tests/`. |

### Concrete integration gates

These gates describe evidence needed to integrate existing components, not stories to reimplement those components. RUN owns adapters, orchestration records and integration tests. A failed owner guarantee is recorded against that owner; only narrow, agreed boundary changes belong in RUN's shared-file footprint. Do not mark a blocked integration verified because a fake bypasses the defect.

| Gate | Owner / required evidence | Blocks |
|---|---|---|
| **DG1 — durable acquisition** | INGEST-01/DATA-01: reopen committed page receipts, drafts, raw record locators and hashes after a crash, including changed payloads for an existing source key. Commit these before advancing the cursor. Preserve cumulative page/request budgets, cache/error history, original traversal start and terminal-exhaustion evidence across resume. Current checkpoint fields and in-memory receipts do not establish all of these guarantees. | S04 crash/replay acceptance. |
| **DG2 — scope and sealed availability evidence** | SOURCE-01/INGEST-01/IDENTITY-02: agree a stable inventory scope based on provider/board plus effective query/filter/config semantics. Current pagination builds `scope_id` from provider/board alone, and availability fingerprints cannot recover omitted query identity. Prove distinct scopes cannot share miss baselines. Seal C04 before consumption; a continued traversal must not mutate an already-consumed partial inventory. | S05 negative inference and complete-inventory acceptance. |
| **DG3 — revision binding and transaction participation** | DATA-01/IDENTITY-01: exact immutable C06 snapshots keyed to revision IDs and material hashes; replay-safe observation identity or an atomic identity-result/checkpoint transaction. Current random observation IDs, source-key-only normalized storage and mixed `with conn`/transaction-helper use require proof. Do not swallow persistence errors as presumed duplicates. | S03/S05/S06 restart correctness. |
| **DG4 — sync selection, refresh and reconciliation** | SYNC-01: preserve selected-final authority and exact title/URLs/evaluation time on refresh; distinguish never-published from possibly-published creation; suppress obsolete unsent plans; retain uncertain lanes before any new drain. Current `queue_tracked_refresh()` reads latest C11 and supplies placeholder title/empty URLs; use a fully populated `SyncSubmission` adapter until an owner-supported selected-assessment refresh exists. Current sequence allocation precedes plan commit, acknowledgment and mapping saves are separate, and reconciliation accepts a Company merely by existence or a higher remote number without full lineage/projection proof. Require owner fixes/explicit evidence for these crash guarantees, not an alternative RUN dispatcher. | S07 atomic publication, stale-write and remote restart acceptance. |
| **DG5 — complete model input identity and admission** | MATCH-02/CONTEXT-04/LLM-01: verify revision UUID/hash binding against the exact C06, actual transmitted prompt admission, immutable model identity and output-affecting versions. Current MATCH-02 fingerprint is useful but is computed before context selection and does not enumerate every index/embedding/provider-setting input; RUN supplies a complete dependency manifest. Coordinate any missing prompt/binder guarantees with their owners. | S09 LLM acceptance/cache reuse. |
| **DG6 — live services** | SF-01/SF-02/SFCLIENT-01 supply verified org mapping/authentication; permitted source configuration and approved candidate/policy inputs are available. MODEL-01/02 supply usable measured local configurations for live LLM checks. | Live G1/G2 evidence only; offline development remains possible. |

## Contracts and execution decisions

The names and CLI choices below are **proposed RUN-01 engineering decisions**, to freeze in S01. They are not new user facts, configured source choices, candidate facts or claims about existing APIs.

| Boundary / record | Required contract |
|---|---|
| `RunRequest` / `RunInputManifest` | Versioned immutable configuration snapshot: logical run UUID, source selections and effective scopes, manual input references/hashes, approved candidate/profile and effective policy snapshots, availability policy, assessment mode, primary strategy, implementation/settings versions and finite budgets. No credentials or mutable-path-only input identity. |
| `RunExecution` / `RunAttempt` | A logical run has one UUID and one frozen request. Explicit resume keeps that UUID and creates an attempt UUID; a new discovery run gets a new run UUID. Execution state is separate from terminal C15. Preserve attempt history, original start and previous terminal summary snapshots. |
| `WorkerLock.acquire(resource, owner_kind)` | OS-held exclusive handle covering all mutation/recovery work for one resolved local deployment/data store. Return an ownership context/token; fail promptly and visibly on contention. `owner_kind` can identify search or a future generation caller without importing generation. |
| `StageWorkRecord` / `StageReceipt` | Schema version, stage and work key, frozen input fingerprint, output IDs/hashes, owner attempt, state, persisted attempt budget/due time, safe error and checkpoint. Reuse only a validated committed receipt. Work identity excludes the current run/attempt ID where cross-run reuse is intended. |
| `PostingBinding` | Canonical UUID, revision UUID, normalized material hash, full immutable C06 snapshot reference/hash, source tuple, mapper/normalizer version and raw provenance references. Raw hash and normalized revision hash are distinct. Old revision lookup must not resolve to today's source-key row. |
| `AssessmentSelection` | Canonical job + candidate + purpose + full input fingerprint → stable C11 ID, original evaluation time, selected-final status and monotonically advancing local selection generation. Register the opaque generation token through `SyncService.register_selection_token` before assessment. Never select by insertion time, score or model method. |
| Existing sync boundary | `commit_assessment_and_plan(SyncSubmission, SyncMappingConfig) -> SyncPlanResult`; `drain_due_work(gateway, config, budget, worker_id, max_operations)`; `reconcile_due_work(gateway, config, budget, max_reconciliations)`; `backup_candidate_fields(gateway, config, batch_size)`. RUN owns call order and aggregate budgets; SYNC owns C12/steps, remote mapping, candidate snapshots and uncertain transmission decisions. |
| Existing model boundary | `AssessmentRequest` carries exact posting/profile/policy, baseline/trace, strategy, limits, model binding and index/embedding settings. `AssessmentRunResult` is persisted as success or pending; pending is execution state, never a fourth assessment disposition or fabricated LLM result. |
| `RunReport` / C15 | C15 remains the persisted terminal summary. Versioned companion details hold stage/source outcomes, attempt history, reused work, pending IDs, selected results and summary revision. Provide read-only access by run ID for future consumers; no notification send or delivery outbox here. |

Default stage order: `preflight → recovery → fetch → normalize → identity → availability → assess → sync_plan → sync_reconcile → sync_drain → candidate_backup → summarize`. Recovery may make bounded reconciliation reads before discovery; it must not dispatch obsolete work before the current desired state is established. Independent source/job failures do not cancel valid neighbors. Unavailable services leave durable pending work. No database transaction spans network/model calls, sleeps or an entire run.

Preflight resolves paths and validates the whole requested source selection before acquisition. Acquire the shared lock before migration, ledger recovery or any component mutation. Register the run before side effects. Validate the selected profile/policy/settings without approving or inventing facts. Source selection precedence is explicit CLI selection, then nonempty `AppConfig.active_sources`, then the checked enabled-source set; disabled/unpermitted explicit choices fail atomically. A valid source returning zero jobs is an empty successful fetch, not a configuration error.

Resume accepts only the frozen request, still-permitted inputs and compatible checkpoint versions. Recheck permissions/approval before using protected inputs; freeze does not override later revocation. Configuration or input changes require a new run/selection generation, with unchanged upstream receipts reusable. Do not silently resume with the current contents of an edited file. A sealed partial run's unfinished acquisition starts a new traversal/run; processing its already-captured downstream work may resume without changing the consumed C04. A crashed unsealed traversal may continue only when DG1/DG2 prove its prefix and budgets; otherwise retain it as partial and start a new inventory.

### Input-version invalidation and reuse

Persist both input versions and content fingerprints. Same version label with different content is a conflict or a new explicitly recorded generation; never a cache hit. Validate output existence, hash, schema and referential bindings before reuse. Keep raw/provenance availability explicit; a missing required file is inspectable work, not permission to fabricate content or mark a cursor complete.

| Change | Reuse / invalidate |
|---|---|
| New fetch time/run UUID, same source record content and effective mapping/normalizer inputs | Record the genuine new sighting and C04. Reuse normalized content, revision and assessment; refresh observation metadata through the owner. Do not replay an old sighting as fresh or issue a new C11 solely for time passing. |
| Raw record content or mapper/normalizer/options/schema version | Reprocess affected records and quarantine decisions from preserved raw evidence. Re-resolve identity; only a material normalized change creates a new revision. A changed unrelated record in a parent page must not invalidate every assessment. |
| Source access, query, scope, manual input hash or adapter identity | Invalidate affected acquisition continuation/cache compatibility. Never compare absence across incompatible scopes. Preserve unrelated source receipts. |
| Canonical membership/current revision changes, merge or reversal | Rebind affected jobs and recompute availability through IDENTITY-02. Invalidate affected assessment selections and sync intent; retain historical lineage. Do not automatically merge/delete remote applications. |
| Approved profile content/version, candidate ID, allowed uses or effective policy/rule/evaluator version | Reassess affected stored jobs even when no new source record was fetched, including locally retained rejects. Reuse acquisition/normalization/identity. Revoke stale completion authority before publishing; do not erase previous evidence. |
| Availability state, source URL projection, canonical company data or sync mapping version only | Reuse the selected C11 and its evaluation time when assessment inputs are unchanged. Queue a changed machine projection through SYNC without a model call. Unknown/not_seen/unavailable are not eligibility rejection. |
| Rules → LLM, JSON ↔ RAG, extraction/prompt/schema/composer/settings/model digest change | Invalidate affected final assessments and downstream publication selection; reuse compatible baseline rules. Strategy is explicit. No silent JSON overflow → RAG or outage → eligible fallback. |
| Profile/chunk/index generation, embedding digest/dimensions/prefix, query/retrieval/inclusion/mandatory/budget/serialization versions | Invalidate dependent RAG/context/model work. JSON does not invalidate merely because an unused RAG index changed. Index construction and compatibility decisions stay with CONTEXT-02/03/04. |
| Retry timestamp/attempt UUID, log formatting, candidate-owned remote notes/status | Do not invalidate assessment or create another machine publication. Refresh candidate backups independently. Actual mapped machine changes may still create an ordered C12 through SYNC. |

An unchanged rerun may fetch fresh observations and read remote candidate fields. It must create **zero duplicate normalization results, revisions, selected assessments, publication intents or logical remote entities**. Count these separately from physical HTTP calls. Crash recovery is at-least-once execution with durable reuse; a model call whose result was never durably saved may need repeating. Do not promise exactly-once inference, HTTP delivery or Salesforce Flow effects.

## Ordered implementation stories

All stories are **PLANNED** and belong to **RUN-01**. Paths beginning `orchestration/`, `storage/` or `contracts/` below are relative to `src/job_automation/`. Shared files require narrow coordinated edits, not ownership transfer.

| Order | Story | Dependency gate | Deliverable |
|---|---|---|---|
| 1 | RUN-01-S01 | Blueprint, current prerequisite APIs | Frozen run/work/selection contracts and dependency acceptance cases |
| 2 | RUN-01-S02 | S01; native Windows | Reusable exclusive worker lock |
| 3 | RUN-01-S03 | S01–S02; DATA-01, DG3 | Durable run attempts, work receipts, snapshots and recovery plan |
| 4 | RUN-01-S04 | S03; SOURCE/INGEST-01/02, DG1 | Recoverable acquisition, normalization and quarantine |
| 5 | RUN-01-S05 | S04; IDENTITY-01/02, DG2/DG3 | Revision bindings and safe availability reconciliation |
| 6 | RUN-01-S06 | S03/S05; MATCH-01, PROFILE/POLICY | Deterministic selection, reuse and input invalidation |
| 7 | RUN-01-S07 | S06; existing SYNC/SFCLIENT, DG4 | Atomic publication handoff and bounded sync/recovery |
| 8 | RUN-01-S08 | S02–S07 | Manual CLI, C15 and deterministic integration milestone |
| 9 | RUN-01-S09 | S08; existing MATCH-02/CONTEXT/LLM, DG5 | LLM mode through the same durable contracts |
| 10 | RUN-01-S10 | S01–S09; DG6 for live lanes | Full failure matrix, native verification and RUN handoff |

### RUN-01-S01 — Freeze run, stage and dependency contracts

**Objective / requirements.** Make execution identity, component authority and resumability explicit before wiring business calls. R02–R09/R16.

**Inputs → outputs.** Current C01–C12/C15, prerequisite ports and configuration → versioned RUN records/ports, stage graph, input-identity specification and DG1–DG6 acceptance register.

**Owned files.** New `orchestration/{__init__,records,ports,errors,settings}.py`; `tests/orchestration/test_contracts.py`; synthetic `tests/fixtures/orchestration/README.md`. Narrow shared schema registration only if RUN records are exported.

**Tasks.** Freeze the tables above, success/pending/error representations, source/job isolation, run-versus-attempt identity, summary versioning and source-selection precedence. Bind to current `SyncSubmission` and `AssessmentRequest` rather than creating competing assessment/outbox contracts. Define complete configuration snapshots, safe references and finite stage/run budgets. Add contract tests that expose the concrete owner gaps; record owners and required resolutions.

**Acceptance criteria.** Rules and LLM results use the same selected-final handoff. A pending model result cannot masquerade as C11 success. A run request round-trips without secrets or mutable input drift. Invalid selection/configuration performs zero fetch/model/Salesforce calls. Importing modules creates no files or workers.

**Failure/restart tests.** Unknown record/checkpoint versions fail visibly; corrupt fingerprints, changed file contents under the same version, missing profile approval and mismatched job/revision bindings fail before work. Serialization/reopen retains logical IDs and dependency gates.

**Migration/configuration and handoff.** No database migration yet. Publish final serialized versions and CLI proposal. Model/threshold/source choices remain explicit configuration. No prerequisite is declared missing merely because an older story said so.

### RUN-01-S02 — Provide reusable native Windows process ownership

**Objective / requirements.** Allow one active pipeline/request worker per configured deployment and prevent recovery from interfering with a live owner. R14/R16; future GEN-01 dependency only.

**Inputs → outputs.** Resolved data-store identity and owner kind → exclusive ownership context or a safe busy error.

**Owned files.** `orchestration/{locking,windows_lock}.py`; `tests/orchestration/{test_locking,test_windows_lock_processes}.py`; test-only child worker under `tests/fakes/`.

**Tasks.** Use a native OS-held mutex or file-lock handle, chosen and documented here, with standard-library Windows support where practical. Normalize the physical data-store identity so relative paths, case aliases and supported junction aliases cannot obtain different locks for the same store. Keep the handle until all local mutations and in-flight calls have settled. Owner metadata (PID, process-start identity, attempt UUID) is diagnostic; PID existence or timestamp expiry alone cannot authorize takeover. Do not unlink a live lock file or use SQLite busy timeout as the worker lock.

**Acceptance criteria.** Two native Python processes targeting the same deployment cannot both mutate it. Search and a test-only future-generation caller contend through the same API. Independent stores follow an explicit isolation policy. Lock is acquired before migration/recovery; normal return, exception and process death release OS ownership. Read-only inspection remains available.

**Failure/restart tests.** Kill the owner; a new process acquires and reconciles unfinished work. Test active owner, stale diagnostic file, PID reuse, different CWD, path aliases, Unicode/spaces and an exception during initialization. A second process performs no ledger recovery, model work or outbox drain while blocked. No claim of cross-process ownership from a threading lock alone.

**Migration/configuration and handoff.** No generation worker, scheduling service or lock-stealing CLI. Document resource naming, supported local filesystem scope and the reusable context-manager contract for GEN-01. Preserve LLM-01's internal inference serialization.

### RUN-01-S03 — Persist run attempts, work receipts and restart decisions

**Objective / requirements.** Resume from verified committed outputs without losing or duplicating work. R04/R09/R16.

**Inputs → outputs.** Frozen run request, component receipts and interrupted execution → durable work records and a bounded reconciliation plan.

**Owned files.** `orchestration/{ledger,checkpoints,recovery,fingerprints}.py`; new `storage/repositories/pipeline_work.py`; narrow `storage/{migrations,engine}.py` and repository exports; narrowly coordinated `storage/repositories/runs.py`; `tests/orchestration/{test_checkpoints,test_recovery,test_migrations}.py`.

**Tasks.** Append the next migration after 007, adding versioned run/attempt manifests, immutable normalization/quarantine outputs, revision bindings, work/result links, selection manifests, retry accounting and report snapshots. Enforce semantic work-key uniqueness and same-key/different-output conflicts. Use transaction-participating methods or verified component-output reconciliation; never assume wrapping a self-committing method creates atomicity. Preserve old ledger rows and mark unprovable legacy checkpoints non-reusable without deleting them.

Under the lock, inspect interrupted attempts, verify outputs and classify each work item as reuse, replay, pending repair, stale input or remote reconciliation. Replace the DATA-01 blanket startup recipe with targeted handling; do not blindly call `recover_stale_running()` or fail generation requests from the search runner. Save recovery decisions and retain prior errors/attempts.

**Acceptance criteria.** A committed output with a missing RUN receipt is recovered from stable owner evidence; an uncommitted output never advances a checkpoint. Stage success is never evidence by itself. Retries preserve IDs, attempts and due times. No transaction is held while waiting on a source/model/gateway.

**Failure/restart tests.** Kill between output commit and checkpoint acknowledgment; reopen with missing/corrupt files, old schema and mismatched hashes. Inject failures after nested repository calls and observe from a second connection. Interrupt migration, verify rollback and preserved checksums/data. DG3 must pass before identity effects can share a receipt transaction.

**Migration/configuration and handoff.** Record actual migration number, legacy classification and retention references for OPS-01. Process-crash evidence does not establish power-loss durability under existing WAL/`synchronous=NORMAL` settings.

### RUN-01-S04 — Wire acquisition, normalization and quarantine

**Objective / requirements.** Preserve every usable observation and isolate bad sources/records while retaining replayable evidence. R02/R03/R09/R16.

**Inputs → outputs.** Checked source configuration/manual inputs → durable C04/C05/page receipts → C06 or persisted quarantine, with per-source progress.

**Dependencies.** S03, existing source registry/adapters, INGEST-01/02; DG1 for real restart acceptance.

**Owned files.** `orchestration/{composition,fetch_stage,normalize_stage,observation_reader}.py`; S03 repository integration; `tests/orchestration/{test_fetch_normalize,test_source_isolation,test_fetch_restart}.py`; synthetic fixtures under `tests/fixtures/orchestration/`.

**Tasks.** Construct configured real adapters and call the fetch controller with the pipeline run ID and explicit selected source keys. Reopen the durable page/draft stream through the owner-approved reader, not the mutable/source-key-only raw table or only returned receipts. Reuse verified normalized content when mapper/normalizer inputs match, while preserving each genuine new sighting separately. Persist all blocking issues and provenance in quarantine; warnings accompany usable records. Seal source outcomes only after durable capture/finalization.

**Acceptance criteria.** Source B failing after page one leaves A/C and B's committed records processable; malformed record two does not lose records one/three. Changed raw content for an existing source key reaches normalization. Replaying the same committed page does not duplicate quarantine or normalized results. No configured source is silently omitted; actual coverage and limits are reported.

**Failure/restart tests.** Raw file written before page commit; page committed before return; terminal page committed before C04 finalization; crash during normalization output/quarantine save; corrupt raw hash; changed manual CSV; cumulative request/page cap across repeated resumes. Cached pages remain partial inventory. Expired/invalid continuation preserves the partial prefix and starts a separately identified traversal rather than falsely completing it.

**Migration/configuration and handoff.** Use S03 storage and existing `ControllerOptions`; no new HTTP retry loop or scraper. DG1 changes inside ingestion/storage stay owner-coordinated. Publish observation units and adapter/raw/mapping version references for S05.

### RUN-01-S05 — Bind identities/revisions and reconcile availability safely

**Objective / requirements.** Preserve stable identities and exact historical assessment inputs while preventing false closure. R03/R04/R08/R16.

**Inputs → outputs.** Valid C06 observation receipts plus sealed C04/configuration → C07/bindings, identity decisions and availability transitions.

**Dependencies.** S04, IDENTITY-01/02, DG2/DG3.

**Owned files.** `orchestration/{identity_stage,posting_bindings,availability_stage}.py`; S03 binding/receipt storage; `tests/orchestration/{test_identity_bindings,test_availability,test_identity_restart}.py`.

**Tasks.** Resolve each unprocessed observation through `IdentityService.resolve_and_commit`; commit/reconcile its stable observation identity and receipt without duplicating sightings after a crash. Save the full C06 snapshot with its resulting revision UUID/material hash. Finish valid identity work for a traversal before `process_manifest(manifest, source_config)`. Keep quarantined but observed source IDs in C04; dropping them can manufacture disappearance. Recompute affected canonical availability after membership changes through the availability service.

Only the owner-qualified complete inventory of the same effective scope supports negative evidence. Partial, failed, cached, filtered and search-only runs support positive sightings but no misses. A source not attempted is not an empty successful inventory. A sealed C04 is consumed once; never repeatedly apply miss/grace policy on each restart. A blocked identity/storage item defers that traversal's availability stage with a visible reason.

**Acceptance criteria.** Repeated/changed posts retain canonical identity; material edits retain old C06/revision evidence. Multi-source jobs stay active while any source is active. Distinct scopes/boards cannot share closure evidence. Valid complete empty inventory can advance the owner's miss policy; it is not forced to failed merely for having no records.

**Failure/restart tests.** Crash after identity commit, after availability commit and before RUN receipt; assert one observation/transition per logical event and no double miss. Replay partial then attempt to extend consumed inventory; require a new traversal. Test filtered query change, missing page, malformed observed record, reopening, merge/reversal, and current revision pointing to an older source snapshot.

**Migration/configuration and handoff.** Reuse availability settings and frozen policy fingerprints; RUN adds no closure threshold. Confirm C06 snapshot retention and the exact revision-string representation accepted by assessment/context consumers.

### RUN-01-S06 — Select deterministic assessments and invalidate stale inputs

**Objective / requirements.** Evaluate each affected logical job/input once and select one authoritative complete C11. R04/R05/R09/R16.

**Inputs → outputs.** Exact posting binding, approved profile, effective policy and dependency manifest → persisted deterministic work result plus selected C11 publication handoff or classified pending input failure.

**Dependencies.** S03/S05; MATCH-01/PROFILE-01/POLICY-01; SYNC token registration contract.

**Owned files.** `orchestration/{selection,invalidation,assessment_stage}.py`; work/selection repository integration; `tests/orchestration/{test_deterministic_pipeline,test_invalidation,test_assessment_reuse}.py`.

**Tasks.** Implement the invalidation table and bounded enumeration of stored affected jobs, including rejected jobs not seen in this fetch. Freeze profile/policy contents and a stable evaluation time/assessment UUID before evaluation. Register the current selection token before work and validate it again before offering a result to SYNC. Invoke the real bound evaluator; retain complete deterministic evidence/trace for S09. Store computed-result/checkpoint data durably so a publication retry does not reevaluate.

Separate discovery candidates, affected assessment work and tracked refresh work. An availability-only closure does not need reassessment; an explicit policy/profile change can reassess retained jobs irrespective of active status. Do not implement the IDENTITY-02 handoff's broad active-only filter as a gate that suppresses tracked updates or retained-reject reassessment. Availability remains an independent field.

**Acceptance criteria.** Same input reuses the C11 ID/evaluation time with zero evaluator calls. A material job/profile/policy change produces new selected work; changed observation time alone does not. Missing data follows MATCH-01, not orchestration guesses. Old completed/comparison/intermediate work cannot replace a newer primary selection.

**Failure/restart tests.** Kill before evaluation, after computation save, and after token registration. Change policy without a new fetch; change profile under the same label; revoke evidence permission; complete an old input late. Assert unchanged upstream reuse and no stale publication. Missing historical C06 fails visibly rather than constructing a synthetic posting.

**Migration/configuration and handoff.** Selection/work storage is S03-owned. Persist protected computed results without separately committing publishable C11 then queuing C12; S07 delegates the atomic primary commit to SYNC. Document the scope and fingerprint algorithm for reuse.

### RUN-01-S07 — Integrate atomic sync planning, reconciliation and candidate backup

**Objective / requirements.** Deliver selected machine updates through the existing outbox and survive ambiguous remote outcomes. R04/R08/R09/R16.

**Inputs → outputs.** Selected C11 or tracked availability/source change → existing `SyncPlanResult`, reconciliation/drain/backup results and durable pending work.

**Dependencies.** S06, existing SYNC-01/SFCLIENT-01, DG4; DG6 for live use.

**Owned files.** `orchestration/{sync_stage,sync_bridge,recovery}.py`; `tests/orchestration/{test_sync_integration,test_sync_restart,test_candidate_backup}.py`; use the existing SYNC fake or a test-only durable gateway fixture. No alternate `salesforce/` implementation.

**Tasks.** Build complete `SyncSubmission` values from frozen selection and canonical snapshots; never accept placeholder title, empty-by-default URLs or a new evaluation timestamp on replay. Use the same assessment ID/generation on lost local replies. Reuse plan links and unchanged projections; do not register a new generation simply because a new run started. For refresh, pass the explicit selected C11 and updated canonical projection through the owner-supported boundary, addressing DG4 rather than selecting latest C11.

Reconcile possibly-sent steps before dispatch, establish uncertainty barriers for interrupted send intents, and preserve them across restarts. Plan the latest desired state before draining old work. Pass a unique worker identity under S02 ownership. Share bounded operation/deadline accounting across gateway reads, authentication, dispatch and candidate backup; prove actual physical sends consume it. Invoke candidate backup for unchanged tracked jobs as a bounded manual stage. Backup failure after a confirmed write is pending backup, not reason to resend the write.

**Acceptance criteria.** New eligible/review jobs publish; definitive new rejects stay local. Tracked rejected/unavailable jobs receive updates without losing candidate status, notes or follow-ups. A lost response creates one logical remote job. Same selected C11/projection causes no new plan. Late older writes cannot overtake the current machine version. No RUN code sets remote creation defaults or changes C12 state directly.

**Failure/restart tests.** Interrupt C11/plan commit; lose its response; kill after Company acknowledgment, Job transmission and local acknowledgment before mapping save. Delay v1 after timeout while v2 is selected; retain the lane barrier. Test rejected v2 after uncertain initial v1, candidate edits between read/patch, refresh with a later comparison C11, changed mapping/target org, exhausted quotas and backup page failure. Use independent durable fake remote state across child-process restarts.

**Migration/configuration and handoff.** SYNC owns its transaction/mapping/reconciliation corrections and migration needs. No hardcoded org names/credentials. Record unresolved DG4 behavior explicitly; offline integration cannot certify live org permissions or automation.

### RUN-01-S08 — Expose the manual CLI and honest C15 summaries

**Objective / requirements.** Provide a usable deterministic Windows run with inspectable progress, resume and reliable terminal reporting. R02–R09/R14/R15/R16.

**Inputs → outputs.** Valid CLI/configuration → bounded `PipelineRunner` invocation, durable C15 plus detailed report, exit status and safe diagnostics.

**Dependencies.** S02–S07. This is the deterministic integration milestone before adding LLM mode.

**Owned files.** `orchestration/{runner,cli,summary,reporting}.py`; narrow root `cli.py` registration and `configuration.py`; `config/run.example.json`; `tests/orchestration/{test_cli,test_summaries,test_cancellation,test_deterministic_end_to_end}.py`; README command documentation.

**Tasks.** Proposed commands: `run start`, `run resume --run-id`, `run show --run-id --json`. `start` selects `--assessment-mode rules` by default; S09 enables `llm`. `--run-config` supplies versioned settings; resume reads frozen settings and does not accept silent overrides. Share callable runner behavior with CLI. Use explicit configuration/data roots, resolve relative references against their configured base and allow another working directory. Do not start watchers, tasks, notifications or hidden infinite retry loops.

Persist the report before printing. In `finally`, finalize recoverable errors/cancellation when storage is usable, release handles and preserve unfinished work. Forced termination is finalized/reconciled by the next lock owner. Read-only `show` reports actual execution state, not the ledger's synthesized failed C15. If data/config is unusable before a run can be admitted, return a safe error and do not fabricate a persisted summary; if admitted, summarize empty, partial and failed runs as well as success.

**Acceptance criteria.** Native manual command executes the deterministic sequence and resumes a failed attempt. Empty complete fetch yields success with zero discovery counts. Some usable progress plus source/item/sync failure yields partial; fatal preflight/storage failure or no usable result from wholly failed required work yields failed. Pending required work prevents success. Explicitly out-of-scope optional stages are skipped with reasons. Proposed exit codes: `0` success, `2` invalid invocation/preflight, `3` lock busy, `4` partial/pending, `1` failed, `130` controlled interruption; document that terminal C15 still uses only success/partial/failed.

**Failure/restart tests.** Fail every stage, cancel during an injected bounded call, lose stdout after summary commit, restart after all work but before summary. Rebuild counters from durable unique receipts, not summed attempts. Show ongoing state without mutating it; validate JSON output/redaction and stable run IDs.

**Migration/configuration and handoff.** Use the C15 rules below and S03 companion report. Prefer additive companion fields over changing C15 v1. Any C15 change requires typed models, regenerated schemas/fixtures and version-aware reader evidence. Preserve a read-only summary boundary for AUTO-03/SF-09; implement no delivery behavior.

### RUN-01-S09 — Add LLM mode using the same selection and publication path

**Objective / requirements.** Enrich selected assessments through MATCH-02 while preserving deterministic authority, recoverability and unchanged-input reuse. R05/R06/R07/R09/R16.

**Inputs → outputs.** Frozen rules baseline/trace and selected JSON/RAG configuration → persisted MATCH-02 success/pending result, then the same S07 C11 handoff for selected success.

**Dependencies.** S08; implemented MATCH-02, CONTEXT-01–04 and LLM-01; DG5; MODEL-01/02 for live evidence.

**Owned files.** `orchestration/{llm_stage,assessment_stage,composition,invalidation}.py`; run settings extension; `tests/orchestration/{test_llm_pipeline,test_llm_restart,test_llm_invalidation}.py`. No assessment prompts, extraction/retrieval logic or HTTP model client in RUN.

**Tasks.** Call `evaluate_deterministic_with_trace` on the exact binding. Ordinary deterministic rejection completes through rules without model work. For configured LLM work construct the actual `AssessmentRequest` with one primary strategy, shared approved snapshot, explicit model/settings/budgets and pinned compatible index/embedding request for RAG. Inject the same input resolver into MATCH-02 and provider. Let MATCH-02 prepare requirements and call the shared selector/inference.

Persist success/pending envelopes and immutable audit references. RUN's reuse manifest supplements the component fingerprint with full profile/policy content, model/provider settings, index/chunk/query/builder versions and payload/budget identities. Validate returned identity before selection. Durable retries reuse frozen logical work, retain attempts/due times and use a fresh correlated transport call where needed; do not multiply LLM-01's internal retries. Nonretryable validation/configuration failures stay inspectable until repaired.

Proposed default outage behavior is **pending without new publication**, retaining the existing selected/remote state with a stale/pending diagnostic. An explicitly configured rules-review fallback must be a separately identified, unscored rules C11 linked to pending work, preserve any existing rejection, and be superseded through a new ordered selection when LLM succeeds. It must never compete with the eventual result. Comparison-purpose inputs have no primary token or publication authority; EVAL-01 owns comparison execution.

**Acceptance criteria.** JSON and RAG manual runs use the same C11/C12 path and candidate evidence rules. Same complete inputs reuse model results with zero new extraction, embedding, context or generation work. Hard failures remain failures; outages, retrieval omissions and budget errors do not become invented rejections. JSON overflow remains visible and never changes strategy automatically. A mutable/unverified model binding cannot qualify for reproducible cache reuse.

**Failure/restart tests.** Context overflow, unavailable model, malformed output, missing evidence and audit failure; kill after saved model result before sync commit; old completion after profile/policy change; index or embedding change only; unchanged input after completed assessment. Count actual model/selector calls and test both strategies through real services with scripted local transport. Lost unsaved inference may repeat but cannot create duplicate selected C11/C12.

**Migration/configuration and handoff.** Extend versioned RUN settings without assuming a production model from illustrative handoff defaults. Record exact dependency versions and unresolved DG5 issues. Live local smoke evidence and measured quality/hardware suitability remain separate.

### RUN-01-S10 — Prove failure recovery on Windows and publish the handoff

**Objective / requirements.** Demonstrate the manual pipeline guarantees with actual component composition and distinguish offline, native and live acceptance. R02–R09/R14/R15/R16.

**Inputs → outputs.** S01–S09, test fixtures and prerequisite evidence → reproducible verification records and `docs/components/RUN-01.md`.

**Owned files.** `tests/orchestration/{test_restart_matrix,test_windows_paths,test_windows_restart,test_end_to_end}.py`; `tests/manual/run_smoke.py`; synthetic fixture catalog; future `docs/components/RUN-01.md`; narrow README verification notes.

**Tasks.** Implement the matrix below using actual storage, ingestion, normalizer, identity, availability, assessment and SYNC services. Only network/model transports and time are faked. Keep fake remote state outside the killed worker so lost responses remain real recovery cases. Use controlled process-termination barriers, not arbitrary sleeps. The offline smoke creates synthetic configuration/profile/source fixtures in its supplied external data directory; fakes must not be available as silent production defaults.

After offline acceptance, run an explicitly configured permitted source through the deterministic manual pipeline to the existing authorized Salesforce target. Demonstrate stable-key rerun, material edit and candidate-field preservation. Keep failure injection in fakes. Separately verify local LLM JSON/RAG execution with configured measured models. Missing access/input/owner gates are pending, never successful skips. This plan itself makes no external changes.

**Acceptance criteria.** Every required failure case has an observable state/identity/count oracle. Native paths with spaces/non-ASCII characters, a different CWD, child-process ownership and file-handle release pass. No application services are required for offline verification. G1 is reported only with real deterministic source-to-Salesforce evidence; RUN's completion does not imply all G2 components/EVAL/OPS are complete.

**Failure/restart tests.** Execute the full matrix and shared-consumer regressions. Record command, platform, dependency versions, result and any excluded cases. Failed gates remain listed with owner and next action.

**Migration/configuration and handoff.** Publish story statuses, owned files, actual migration/schema/contract versions, CLI/exit behavior, lock contract for GEN-01, count units, recovery limits, invalidation rules, retry accounting and separate unit/fake/native/live status. Preserve Phase 2 hooks as data/API contracts only.

## C15 count and status rules

Project counts from committed logical receipts; retries/restarts do not increment completed-work totals again. Store attempt/physical-call totals separately. A resumed run can publish a newer report snapshot under the same run UUID; preserve the earlier report and its revision, and do not create a notification event. A new run has its own summary, including reuse counts.

| C15 field / companion detail | Unit and rule |
|---|---|
| `source_counts`, `source_postings_count` | Raw source-record observations accepted into durable page evidence for this logical run, including records later quarantined. Replayed page receipt contributes zero additional observations. Repeated occurrences on genuinely distinct pages remain observations; companion distinct-source-tuple count is separate. Sum per-source counts equals total. |
| `canonical_jobs_new` | Distinct canonical UUIDs first created by this run's identity work. |
| `canonical_jobs_updated` | Distinct preexisting canonical UUIDs receiving at least one material new revision; multiple source edits count once. Availability-only changes have a separate companion counter. |
| `canonical_jobs_duplicate` | Existing v1 field description says **postings** identified as duplicates, despite its name/header. Preserve that meaning: distinct processed observation receipts matched to an existing unchanged opportunity or alternate-source duplicate, excluding a material update. Label this as posting observations in output; do not present it as distinct jobs or add it to canonical totals. Freeze exact outcome mapping in S01. |
| `eligible_count`, `review_count`, `rejected_count` | Distinct canonical jobs with a completed selected assessment newly evaluated in this logical run, counted once using the final selected disposition. Reused assessments, intermediate rules and comparisons have companion counts. Pending inference without selected fallback contributes to pending work, not rejection. |
| `sync_operations_succeeded`, `sync_operations_failed` | Distinct C12 operations whose completion/failure is attributed to this run, including explicitly claimed prior pending work. Do not copy dispatcher step counts here: Company and Job steps are not two C12 operations. Superseded undelivered operations are not successes; record terminal reasons separately. |
| Stage/source details | Versioned companion report: attempted/completed/partial/failed/not-attempted sources, stage status/counts, reused work, quarantine, availability changes, model attempts, sync steps/physical sends and backup freshness. Units are explicit per counter. |
| `errors`, `pending_work` | Classified safe errors plus stable referenced work IDs and actionable reasons. Distinguish current-run pending items from prior backlog; retain retry due/repair details in companion records. No raw prompts, candidate facts, tokens, credentials or full provider exceptions in terminal output. |

`PipelineStage` retains pending/running/succeeded/failed/skipped. A reused unit is skipped with a reuse reason/output reference. A stage that processed a partial source result may have completed its orchestration work; its detailed outcome and C15 still show partial coverage. Do not introduce new enum values by storing arbitrary strings in shared records. An expected unknown eligibility review is a successful assessment, not a failed pipeline stage.

## Required failure/restart matrix

| ID | Scenario | Required oracle |
|---|---|---|
| RUN-T01 | Search/search and search/future-generation lock contention; owner killed | One owner, zero second-worker effects; OS release followed by targeted recovery. |
| RUN-T02 | Crash before/after page/cursor commit, repeated resume at budget limit | No lost drafts/changed payloads, no skipped page or reset budgets, no fabricated complete inventory. |
| RUN-T03 | A succeeds, B partially fails, C succeeds; malformed record in A | Valid records proceed, quarantine is durable, C15 partial, B absence never closes jobs. |
| RUN-T04 | Cached/filtered/search/failed/disabled/not-attempted source; changed scope | Zero negative inference; positive observations remain usable; independent baselines. |
| RUN-T05 | Complete same-scope empty inventories, configured miss/grace rules, replay | Owner policy controls closure; one miss per inventory; one active alternate source keeps canonical active; reappearance reopens. |
| RUN-T06 | Identity committed before RUN receipt; two sources share a job; material edit | No duplicate observation on replay, stable canonical IDs, exact old/new C06 snapshots, no duplicate revision. |
| RUN-T07 | Unchanged new run and unchanged resume | Fresh observation evidence permitted; zero duplicate derived records/model calls/plans/logical remote records; original assessment timestamp retained. |
| RUN-T08 | Change one input/version at a time, including retained rejected job and no fetched rows | Only affected downstream work invalidates; immutable historical inputs retained; no latest-source substitution. |
| RUN-T09 | C11/plan atomic fault or commit response lost | No partial primary publication; same C11/plan/C12 recovered without another assessment. |
| RUN-T10 | Company/Job remote commit with lost response; local ack/mapping crash | Same External IDs, no duplicate logical record; verified reconciliation before retry, complete local links. |
| RUN-T11 | v1 uncertain/delayed, v2 rejected or updated; stale result/callback | No stale overwrite or untracked-assumption creation; barriers retained until owner-verified resolution. |
| RUN-T12 | Availability-only refresh with later comparison C11; candidate edits; backup fails | Explicit selected assessment reused, title/URLs intact, no inference, candidate edits survive, no resend for backup-only failure. |
| RUN-T13 | LLM unavailable/invalid/context overflow; both JSON/RAG; saved result then kill | Durable pending or same validated result reused; no fabricated LLM success/rejection, no silent strategy switch or intermediate publication. |
| RUN-T14 | Same version label/different bytes; missing raw/C06/model audit; revoked permission | No unsafe reuse; precise pending/repair reason; unaffected items continue where possible. |
| RUN-T15 | Cancel, fatal storage failure, empty success, partial source, pending sync; stdout fails | Correct terminal status/exit behavior, durable counters and stable run ID; recovery finishes missing summary without replaying completed work. |
| RUN-T16 | Migration failure, old ledger, restored local DB behind remote, Unicode/CWD/process restart | Data/checksums retained, unknown legacy outputs not trusted, no remote version regression, handles released. |

## Native PowerShell verification recipe

These are **future implementation checks**, not commands run or passes claimed by this Markdown task. Proposed files/CLI must exist first. Start in the repository root; use an absolute interpreter and unique test-owned directories outside the checkout. No Bash, activation, WSL, Docker or Task Scheduler is required.

```powershell
$runRepo = (Resolve-Path '.').Path
$runPython = Join-Path $runRepo '.venv\Scripts\python.exe'
$runTests = Join-Path $runRepo 'tests\orchestration'
$runTemp = Join-Path $env:TEMP ('Job Automation RUN Prüfung ä ' + [guid]::NewGuid().ToString())
$runData = Join-Path $runTemp 'Daten Größe'
$runSmoke = Join-Path $runRepo 'tests\manual\run_smoke.py'

New-Item -ItemType Directory -Path $runTemp | Out-Null
& $runPython -c "import platform, sys, sqlite3; from zoneinfo import ZoneInfo; print(platform.platform()); print(sys.version); print(sqlite3.sqlite_version); print(ZoneInfo('Europe/Berlin'))"
if ($LASTEXITCODE -ne 0) { throw 'Environment check failed' }

& $runPython -m pytest $runTests
if ($LASTEXITCODE -ne 0) { throw 'RUN-01 checks failed' }
& $runPython -m pytest (Join-Path $runRepo 'tests\storage') (Join-Path $runRepo 'tests\contracts') (Join-Path $runRepo 'tests\ingestion') (Join-Path $runRepo 'tests\identity') (Join-Path $runRepo 'tests\assessment') (Join-Path $runRepo 'tests\salesforce') (Join-Path $runRepo 'tests\test_configuration.py') (Join-Path $runRepo 'tests\test_cli.py')
if ($LASTEXITCODE -ne 0) { throw 'Affected boundary checks failed' }

Push-Location -LiteralPath $runTemp
try {
    & $runPython -m pytest (Join-Path $runTests 'test_windows_paths.py') (Join-Path $runTests 'test_windows_lock_processes.py') (Join-Path $runTests 'test_windows_restart.py') --basetemp (Join-Path $runTemp 'Pytest Daten ü')
    if ($LASTEXITCODE -ne 0) { throw 'Native Windows checks failed' }

    # Proposed S10 harness: real components, test-only transports, synthetic data.
    & $runPython $runSmoke --data-root $runData --scenario deterministic-rerun
    if ($LASTEXITCODE -ne 0) { throw 'Deterministic rerun smoke failed' }
    & $runPython $runSmoke --data-root (Join-Path $runTemp 'Restart Daten ö') --scenario crash-recovery
    if ($LASTEXITCODE -ne 0) { throw 'Crash recovery smoke failed' }
    & $runPython $runSmoke --data-root (Join-Path $runTemp 'LLM Daten ä') --scenario llm-json-rag
    if ($LASTEXITCODE -ne 0) { throw 'LLM integration smoke failed' }
} finally {
    Pop-Location
}

& $runPython -m pytest (Join-Path $runRepo 'tests')
if ($LASTEXITCODE -ne 0) { throw 'Repository regression failed' }
```

The smoke harness must assert SQLite record identities/counts, model-call counts, independently persistent fake remote records, protected candidate values and C15 units; printing success alone is insufficient. Freeze these proposed arguments in S10 and record actual results. Regenerate affected schemas through the existing exporter only when contracts changed, then verify fixture/schema parity.

After live prerequisites and the intended run configuration exist, the proposed manual CLI is:

```powershell
$runAppConfig = Join-Path $env:LOCALAPPDATA 'Job Automation\app.json'
$runSettings = Join-Path $env:LOCALAPPDATA 'Job Automation\run.json'
& $runPython -m job_automation run start --config $runAppConfig --run-config $runSettings --assessment-mode rules
# Copy the emitted logical run UUID; inspect or resume only that intended run.
$runId = 'REPLACE-WITH-EMITTED-RUN-UUID'
& $runPython -m job_automation run show --config $runAppConfig --run-id $runId --json
& $runPython -m job_automation run resume --config $runAppConfig --run-id $runId
```

Use the configured primary strategy for a later `--assessment-mode llm` invocation. Credentials and candidate facts belong in protected stores, not CLI arguments. Record live source fetch, Salesforce writes, local model execution and native subprocess verification separately. These illustrative commands are not authorization to configure the org or install models during planning.

## Completion and handoff checklist

- All ten RUN stories have explicit status and DG1–DG6 resolution/evidence; actual code/handoff updates supersede older plans.
- Deterministic manual run passes before LLM integration; both methods share selection, C11/C12 publication and C15 reporting.
- The shared OS-held lock is reusable by GEN-01; process death and contention are verified in separate native processes.
- Durable acquisition, exact revision snapshots, identity observations and availability consumption survive every crash boundary without false closure.
- Unchanged reruns reuse derived work; input changes invalidate only affected work, including retained local rejects and pending old results.
- SYNC owns remote recovery and field ownership; uncertain writes never become blind retries or stale overwrites. Candidate backups remain independent of machine changes.
- Empty, partial, failed, cancelled and successful runs produce honest summaries when admitted; source-posting, canonical-job, C12 and physical-call units remain distinct.
- Actual schema/migration versions, retry budgets, safe diagnostics, native commands/results and remaining live gates are recorded in `docs/components/RUN-01.md`.
- Future scheduling, notification and generation consumers receive stable IDs/ports only. No Phase 2 behavior, generation worker, org metadata or application implementation is added by this planning task.
