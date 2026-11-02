# GEN-01 — Generation request worker implementation stories

Status: **PLANNED — documentation only; no implementation or verification claimed**  
Date: 29 October 2026  
Phase: **1**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially §§4–8, G3 and G4  
Direct requirements: **R10, R12, R16**; supporting constraints: R06, R09, R11, R14, R15  
Repository guidance: [README.md](../../README.md) and blueprint §§8–9. No applicable `AGENTS.md` was found in the repository or its checked ancestor directories.

## Outcome and scope

Implement a manually started Windows worker that polls Salesforce outbound, admits durable C13 requests, invokes GEN-02 to freeze inputs, commits the request and snapshot references atomically, and only then projects Running remotely. Coordinate later component calls through durable checkpoints. Restart must reconcile both incomplete local work and stale remote Running requests while retaining the same request, frozen inputs, and logical output identities.

GEN-01 owns polling, remote request mapping, request identity, attempts, checkpoint transitions, request-state reconciliation, bounded retries, and worker CLI composition. Minimal shared contract, storage, and RUN-01 entry-point wiring needed to enforce these guarantees is included. All new names and defaults below are proposed implementation decisions, not existing APIs or separately confirmed user preferences.

GEN-02 owns availability checks, snapshot contents, inclusion/authorization rules, and JSON/RAG context construction. GEN-03 owns prompts and draft content; GEN-04 factual/document validation; GEN-05 rendering and artifact versions; GEN-06 upload reconciliation, delivery, and readiness integration. Define and call their ports; implement none of their business logic. SF-05/06 own org metadata and request actions. SF-07/08 own review UI and notifications. No scheduler, startup service, automatic drafting policy, application submission, new org, paid service, or inbound localhost endpoint is included.

## Repository evidence and dependency gates

Read the available [DATA-01](../components/DATA-01.md), [SFCLIENT-01](../components/SFCLIENT-01.md), and [RUN-01](../components/RUN-01.md) handoffs against current code. **SF-05, SF-06, and GEN-02 handoff files are absent**, as are their story files and the `src/job_automation/generation/` package. Their blueprint descriptions establish required responsibilities, not verified implementations. Do not silently implement those dependencies to unblock GEN-01.

| Dependency / evidence | Current state and consequence |
|---|---|
| DATA-01; `contracts/generation.py` | C13 v1 has UUID identity, separate Salesforce ID/client key, predecessor, options, state, frozen versions and one artifact reference. `FrozenInputVersions` contains posting/profile/policy/template version strings only. It is not a complete immutable snapshot manifest. |
| `storage/repositories/generation_requests.py` | CRUD, `claim_request`, and unfinished enumeration exist. Claim lacks a pending-state guard and can overwrite an existing freeze. Only the local UUID is unique; remote/client identity lookup and uniqueness are missing. There are no per-stage receipts, retry schedules, or request-state write intents. |
| DATA-01 atomicity guidance versus code | Generation repository writes use `with self.conn`, which can commit inside an outer `StorageEngine.transaction()`. The shared transaction helper's depth tracking does not intercept raw connection context managers. Wrapping current `create_request`/`claim_request` calls is insufficient proof of atomic admission. Plan a transaction-aware repository operation and rollback tests. |
| Legacy generation recovery | `recover_interrupted_requests()` changes running and upload_pending to failed. `get_unfinished_requests()` omits failed and ready_for_review rows. GEN-01 must use targeted checkpoint reconciliation, including pending remote updates for locally terminal rows, rather than invoke blanket failure recovery. |
| DATA-01 migrations / C14 | Current migrations end at 008. Artifacts have IDs, versions, file hashes and reconciliation markers, but no unique logical output slot. C14 has one ambiguous `remote_file_id`; typed multi-format delivery receipts need GEN-06 agreement. Allocate the next migration at implementation time, after any GEN-02 migration. |
| SFCLIENT-01 | `SalesforceGatewayV2` supports typed `query_page`, `get_record`, `describe_object`, and `update_record`. Failures expose remote outcome, recovery action, retry-not-before and physical attempts. Updates do not replay uncertain transmission. No conditional-update/compare-and-set parameter exists on `UpdateRequest`. No request object mappings or Files delivery implementation exist. Live authorization remains gated on SF-02. |
| RUN-01 lock | Actual API is `WindowsWorkerLock(paths.data_root).acquire(owner_kind=OwnerKind.GENERATION, attempt_id=...)`, raising `LockContentionError`. It uses `normalize_lock_target`, `.deployment.lock`, and separate `.deployment.lock.diag`. The handoff's `acquire_worker_lock` and `DeploymentBusyError` names do not exist. Reuse code, not those illustrative signatures. |
| RUN-01 entry-point ordering | `PipelineRunner._get_engine_and_paths()` calls `initialize_schema()` before `start_run`/`resume_run` acquire the lock. A narrow shared wiring correction is needed to guarantee zero database writes by a losing search worker; the handoff's contention claim alone does not establish this. |
| Existing generation ports | `Generator.generate_draft(request, context)` exists. `RendererDelivery` combines rendering/delivery and accepts the legacy Salesforce gateway. No GEN-02 freeze port or GEN-04 validation port exists. Preserve legacy consumers and agree additive adapters/typed ports rather than silently replacing interfaces. |

Paths in that table are relative to `src/job_automation/`, unless stated otherwise. Relevant existing tests include `tests/storage/test_recovery.py`, `test_transactions.py`, `test_repositories.py`, `tests/contracts/test_work_records.py`, `test_interfaces.py`, `tests/salesforce/test_reads.py`, `test_mutations.py`, `test_retry_and_budgets.py`, and `tests/orchestration/test_windows_lock_processes.py`.

| Gate | Owner and required evidence | Effect on GEN-01 |
|---|---|---|
| DG1 — Remote request contract | SF-05: actual object/field names, job lookup, org identity, stable key, option/state labels, timestamps, frozen metadata, result/error fields, field permissions and ownership. | Fake mappings can test the adapter. Live polling/updates remain pending until the mapping and access are verified. Do not assume `Generation_Request__c` is deployed. |
| DG2 — Enqueue and mutation semantics | SF-06 with SF-05: active-identical request reuse, deliberate regeneration, predecessor link, immutable accepted options, worker-only processing fields, retry intent, and transition/notification behavior. | No safe live claim until races are resolved. A read followed by PATCH is not compare-and-set. If field ownership/immutability cannot enforce the single-writer contract, require a verified guarded-update capability from the owning components. |
| DG3 — Frozen inputs/context | GEN-02: worker-independent prepare/reopen/context interfaces, exact immutable refs and hashes, atomic reference registration, failure/warning envelope, authorization policy, index pins, and retention obligations. | Real freeze/context integration is blocked. Synthetic ports demonstrate GEN-01 coordination only; no latest-profile fallback or miniature GEN-02 inside this worker. |
| DG4 — Local storage and exclusion | GEN-01 with DATA-01/RUN-01: transaction-safe admission, identity constraints, stage receipts, shared lock and corrected search lock ordering. | Required before crash safety or shared exclusion acceptance. |
| DG5 — Downstream receipts | GEN-03–06: stage operation identities, reopening outputs, validation result, artifact-set and delivery acknowledgment contracts. | Coordination is testable with explicit fakes. Real drafting/rendering/upload acceptance belongs to G4, not GEN-01's G3 gate. |

## Identity, interfaces, and persistence decisions

### Identity and retry invariants

1. Scope every remote identity by the verified Salesforce org ID. Normalize Salesforce 15/18-character representations through a tested, case-preserving canonical representation. Never lowercase record IDs. Persist a unique `(org_id, salesforce_request_id)` mapping to one C13 UUID. A supplied client key is separately unique within its agreed org/client namespace; a disagreement between client and remote mappings is a visible conflict, not an overwrite.
2. For UI-created requests without a local UUID, propose a documented UUIDv5 namespace over the canonical org/request identity, persisted on first observation. This gives a stable local ID on replay; it does not recover lost snapshots after a database restore. Prefer a verified existing local UUID from the agreed remote contract when present. Store the identity scheme version. A content hash, job ID, or options fingerprint is never the request ID.
3. SF-06 may return an already active identical request. Polling the same remote row repeatedly returns the same C13. Two distinct remote request IDs remain distinct even with identical job/options. A deliberate regeneration has a new UUID and new remote request, with `predecessor_request_id` when supplied; it can freeze newer inputs. GEN-01 never creates regeneration requests automatically.
4. A retry/resume retains request UUID, remote ID, client key, accepted options, freeze identity, draft version and artifact slots. Each execution attempt and physical gateway/model call has its own audit identity. Already committed output is reopened and verified. Unsaved inference may repeat after a crash; committed logical output must not multiply.
5. Changing language, template, strategy, job, or unavailable-job override is not a retry. In particular, retrying a `job_unavailable` failure with `allow_unavailable_job=true` requires a **new** request deliberately created through SF-06. Do not mutate the failed request or inherit an override implicitly.

### Proposed ports

Freeze final signatures and versioned schemas in S01 with the dependency owners. Keep pure domain services usable without the worker.

| Boundary | Input → output and ownership |
|---|---|
| `GenerationRequestSource` (GEN-01 adapter) | Bounded poll scan or exact org/request identity → typed remote observations, safe record issues, continuation and scan completeness. Uses SFCLIENT-01 only; no custom HTTP/auth stack. |
| `GenerationInputService.prepare_freeze` (GEN-02) | Validated C13 options, stable request/freeze operation identity → immutable snapshot manifest or classified preflight failure plus warnings. Contains exact approved C01, canonical/revision identity and bound posting content, policy/template/options and their hashes. No remote state mutation. |
| GEN-02 snapshot registration/reopen | Prepared manifest + caller transaction → registered immutable references/pins; manifest ID → verified frozen inputs. Registration must join the caller's unit of work, or GEN-02 must provide already durable immutable objects whose request association can be committed atomically. Files are finalized before their refs are committed. |
| `GenerationInputService.build_context` (GEN-02) | Committed freeze manifest + stable context operation identity → C09, exact payload/audit references and warnings. Uses pinned JSON/RAG settings, model/prompt/budget identity and index generation where applicable. Retry never selects latest versions. |
| `GenerationWorkflowStore` (GEN-01/DATA-01) | Admit, commit freeze, start/complete step, append attempt, schedule retry, enqueue/ack request projection → validated durable receipts. Expected state/revision checks and idempotent readback are part of the interface. |
| `GenerationCoordinator` (GEN-01) | One request identity, held lock token, dependency ports, clock and budgets → next checkpoint / pending reason / terminal outcome. No hidden daemon, polling inside GEN-02, or business logic in the CLI. |
| `RequestStateProjector` (GEN-01) | Durable state-write intent with stable operation ID and expected remote identity → acknowledgment or reconciliation obligation through SFCLIENT-01. Writes only agreed worker-owned request fields. |

The manifest supplements C13's four version strings with exact IDs, content hashes, schema versions, snapshot locations, candidate identity, inclusion-purpose/rules, options digest and a workflow binding fingerprint. GEN-02 owns which data constitutes a valid freeze. Pin model/digest, prompt/schema, context settings and budget, template bytes/version, and RAG index/embedding/chunk settings before their first dependent operation. If those are resolved after the base freeze, atomically seal a versioned execution binding once; never recompute it from mutable defaults during recovery. The `posting_revision` string's current hash meaning must not silently become a revision UUID; record both explicitly in the companion manifest.

### Durable companion records

Prefer versioned companion records to inventing new C13 state enum values. Proposed additions, with exact names finalized in S01/S02:

| Record | Required contents / constraints |
|---|---|
| Request observation and identity | Org/remote/client identity, local UUID if admitted, observed options digest/version, remote state/time and safe issue. Retain invalid or unmapped requests even when C13's canonical-job foreign key cannot yet be satisfied. |
| Freeze association | One sealed manifest per request, exact snapshot refs/hashes/pins, availability warning/override evidence, frozen timestamp and accepted request digest. Request and association are committed together; conflicting re-freeze is rejected. |
| Request attempts / stage receipts | Request UUID, attempt UUID/sequence, stage operation ID, input fingerprint, checkpoint revision, status, timestamps, output refs/hashes, error, retry count and next due time. Logical stages are keyed by request/stage/binding, not by each process attempt. |
| Remote projection intents | Request UUID, monotonically ordered projection revision, stable operation marker, desired state and allowed fields, expected observed state/marker, attempts, due time, acknowledgment and uncertainty. Persist before any send, including preflight failures and terminal transitions. |
| Artifact-set references | Request/frozen binding, stable draft/output version, per-format artifact IDs and delivery receipts. C13's single `result_artifact_ref` has an explicitly agreed primary-artifact mapping; the companion set preserves DOCX/PDF independently. Do not change its meaning silently. |
| Poll/worker report | Worker attempt, bounded scan cursor/completeness, due backlog, admission/reuse/failure counts, gateway attempts and safe errors. Counts distinguish requests, stages, artifacts and physical sends. Do not put generation counts into C15 search counters. |

Retain referenced inputs and unfinished records for OPS-01. Do not cascade-delete request history when a job is merged/removed; audit the current canonical-job `ON DELETE CASCADE` relationship and add protection/migration where necessary. Snapshot file publication and SQLite are not a distributed transaction: verified immutable files may be orphaned before commit, but no committed claim may reference missing/unfinalized files. Cleanup of orphans belongs to OPS-01 after reference checks. Process-crash tests do not establish power-loss durability for SQLite `synchronous=NORMAL`; record that limit rather than claim it.

## State and recovery protocol

### Ordered workflow

1. Resolve and validate local configuration without opening/migrating writable storage. Acquire the existing RUN-01 deployment lock with `OwnerKind.GENERATION`. Only then open/migrate storage, create attempts, perform recovery, or make Salesforce/model calls.
2. Reconcile due local work and pending remote intents, including locally failed/ready rows; scan stale remote Running and relevant Upload pending requests as well as Pending. Bound each lane so recovery backlog cannot indefinitely starve new work or vice versa.
3. Admit an observation idempotently. Validate remote identity, job mapping, language/type/template/strategy and explicit override. Retain safe failed observations instead of inventing job/profile data. Re-read the request before freezing and apply DG2's immutable-option/ownership contract.
4. Call GEN-02 to prepare the freeze. In **one local transaction**, write/update C13 with frozen versions and claimed timestamp, register the manifest/snapshot associations and pins, complete the freeze checkpoint, and enqueue the Running projection intent. Validate state and digest again at commit. Commit must precede **every** remote Running send.
5. Send the Running projection. If the outcome is uncertain, block subsequent state writes and expensive downstream work for that request until reconciled. Acknowledged Running, or matching readback of the same operation marker and freeze identity, permits continuation. No SQLite transaction stays open during network or model calls.
6. Build/reopen context through GEN-02, then coordinate GEN-03 draft → GEN-04 validation → GEN-05 artifact set → GEN-06 delivery. Commit each stage receipt and its output references before advancing. Save operation identities before calls; adopt a dependency's already committed matching output after a lost response.
7. Once local artifacts are complete, persist Upload pending and delegate delivery/reconciliation. Project Ready for review only after GEN-06 supplies durable evidence that all advertised required artifacts are accessible. Candidate approval remains draft unless changed by the candidate through its owner. Terminal remote projection can remain pending independently of completed local work.

| C13 state | Worker behavior |
|---|---|
| `pending` | Admitted but not frozen, or awaiting preflight repair/retry. No remote Running without a committed freeze. |
| `running` | Immutable freeze committed; companion checkpoint says whether remote claim, context, drafting, validation or rendering is next. A retry wait or dependency block is companion metadata, not a new processing enum. |
| `upload_pending` | Saved artifact set exists; delivery/reconciliation is incomplete. Delivery quota/network failures retain this state and local files. |
| `ready_for_review` | Required delivery receipts are verified; retain pending remote projection if its acknowledgment is lost. No automatic approval or redrafting. |
| `failed` | Explicit preflight/permanent failure or exhausted processing retry policy, with inspectable history. An authorized same-input retry can resume a recoverable failure without changing identity; do not automatically reopen every Failed row. |

Preflight `job_unavailable` maps to a safe `ClassifiedError` reason code, not a new generic error enum. It is recorded and projected Failed without passing through Running. Unknown availability retains GEN-02's visible warning. GEN-01 does not reinterpret unavailable as unknown, switch JSON to RAG on overflow, or waive revoked evidence permission. Permission revalidation of frozen work is owned by GEN-02; a denial blocks progress without silently changing the snapshot.

### Recovery decisions

Staleness is a candidate-selection criterion, not permission to take over another worker. Use the agreed remote worker timestamp, with a configured threshold and clock-skew allowance; a missing/invalid timestamp is an explicit anomaly. The local OS lock establishes exclusion for this deployment only. Multiple computers or separately configured roots targeting the same request stream require a remote lease/fencing design outside the initial single-computer assumption and must not be enabled implicitly.

| Observation | Required reconciliation |
|---|---|
| Local freeze committed, remote Pending | Resolve any ambiguous earlier Running write first. Reuse the freeze and same intent; mark Running when safe. Never call freeze against latest again. |
| Local unfinished, remote Running with matching marker/binding | Recover interrupted attempt, verify output receipts and resume the first incomplete stage. A matching local request need not wait for the stale threshold after the OS lock proves the prior local worker ended. |
| Stale remote Running, no local C13/manifest | Recover identity and exact frozen references only if verified remote metadata plus surviving local snapshots/backups can reconstruct them. Otherwise persist an orphan/recovery issue and, when ownership is established, project actionable failure. Never reset to Pending and freeze current inputs under the old ID. |
| Legacy local Failed produced by blanket recovery | Inspect original recovery reason and preserved freeze/artifact receipts; recover only provably interrupted work under the migration/retry policy. Genuine permanent failure remains failed. |
| Local artifact saved, stage receipt absent | Ask GEN-05 to resolve the preassigned request/version/format operation identity, verify hash/binding, and adopt its receipt. Never allocate a new version merely because a response was lost. |
| Upload outcome uncertain or remote Upload pending | Delegate lookup/reconciliation to GEN-06 before any new upload. Continue from saved artifacts, preserving request and file markers. |
| Local Ready/Failed, remote earlier state | Reconcile/finish the pending state projection without redoing successful stages. Keep the terminal row discoverable through the intent table. |
| Remote already Ready/terminal ahead of local state, including restored older DB | Verify its marker, binding and GEN-06 delivery evidence; adopt recoverable receipts or block for repair. Never send old Running, downgrade remote state, or regenerate to fill missing history. |
| Remote missing, inaccessible, changed options, foreign marker, or conflicting identity | Classify deletion versus permission failure where evidence allows, retain local work, stop automatic writes for that identity, and expose repair. No replacement request, guessed fields, or overwrite. |
| A recently active remote Running request has no matching local history | Defer ownership takeover and record the anomaly; elapsed time alone is insufficient proof of ownership. |

An uncertain remote mutation is a per-request ordering barrier. A read that still shows the old state alone does not prove a timed-out write cannot arrive later. DG2 must establish marker-aware transition guards or another verified resolution policy before replay or a later state is sent. Keep unresolved writes inspectable; do not advertise exactly-once network delivery or notifications. SF-08 owns deduplicated readiness transitions.

## Implementation stories

### GEN-01-S01 — Freeze contracts, ownership, and dependency gates

**Objective / requirements.** Establish one implementable request lifecycle and dependency boundary before writing worker logic. R10/R12/R16, C13/C14 and blueprint G3.

**Inputs → outputs.** Blueprint, current contracts/code and available handoffs → versioned request observation, freeze association, attempt/checkpoint, projection intent and result envelopes; DG1–DG5 decisions with owner/evidence.

**Dependencies.** DATA-01, SFCLIENT-01, RUN-01; SF-05/06 and GEN-02 for real integration. Missing handoffs stay explicitly pending.

**Owned modules.** Proposed `generation/{records,ports,errors}.py`; narrowly coordinated `contracts/generation.py`, `contracts/interfaces.py`, schema exporter and synthetic fixtures. No metadata deployment.

**Tasks.** Agree identity normalization/namespace, option immutability, state ownership, retry versus regeneration, manifest contents and stage idempotency. Specify tagged success/pending/failure outcomes, exact error reasons and allowed transitions. Resolve DG2's lack of gateway conditional writes; do not assert a nonexistent CAS API. Define context/draft/validation/artifact/delivery references and compatibility adapters for existing ports. Publish a prerequisite report usable by the implementation chat.

**Acceptance criteria.** Fixtures reject Running without frozen versions, conflicting identities, mixed request/binding outputs, changed retry options, and successful envelopes without outputs. A new deliberate regeneration remains distinct even when its options match its predecessor. Each missing service produces a named gate, not a fake production success.

**Tests / failure cases.** Contract round trips, unknown schema versions, invalid transitions, 15/18-character ID equivalence and case sensitivity, client-key conflicts, both document types/strategies and explicit override. Schema/fixture parity and existing interface compatibility checks.

**Migration/configuration and handoff.** Prefer companion v1 contracts; document any C13/C14 change with version/consumer migration. Finalize mapping requirements before S04. Shared changes require updated schemas/fixtures rather than arbitrary JSON fields.

### GEN-01-S02 — Persist request identities, freeze associations, and resumable checkpoints

**Objective / requirements.** Make request admission and progress transactionally recoverable. R09/R10/R12/R16.

**Inputs → outputs.** S01 records, validated observation and GEN-02 manifest → one C13 and a consistent durable workflow graph.

**Dependencies.** S01, DATA-01, GEN-02 snapshot registration agreement (DG3/DG4).

**Owned modules.** `storage/repositories/generation_requests.py`, proposed `generation_work.py`, `storage/{engine,migrations}.py`; `tests/storage/test_generation_*.py`.

**Tasks.** Add unique org/remote and scoped client-key bindings, lookup methods, expected-revision updates, freeze-once checks, logical step receipts, attempts, retry schedules and ordered projection intents. Add observation quarantine for missing canonical mappings. Implement a transaction-aware `commit_frozen_request` that does not call prematurely committing repository methods. Validate immutable manifest references and synchronize C13 JSON with indexed columns. Protect history from cascade deletion and keep terminal rows with unacknowledged intents discoverable.

**Acceptance criteria.** Fault at any statement in freeze admission leaves either the old unclaimed request or the complete claimed request + snapshot associations/pins + checkpoint + Running intent. Replaying after lost commit acknowledgment returns exactly those records. A second freeze with a different digest fails. Duplicate remote identity cannot create a second C13. No incomplete checkpoint is treated as completed solely because a timestamp exists.

**Tests / failure cases.** Real SQLite rollback after each insert/update, outer transaction composition, concurrent identity collision, lost commit return, FK protection, JSON/indexed-column parity and fresh-process reopen. Upgrade existing pending/running/upload_pending/ready/failed records; legacy rows without verifiable snapshots become repair work, not invented manifests.

**Migration/configuration and handoff.** Add the next migration after current 008 and any dependency migrations; preserve old checksums. Report preexisting duplicate remote/client mappings for explicit reconciliation before creating uniqueness constraints; never merge/delete histories automatically. Preserve legacy method behavior for existing callers or migrate them explicitly, while GEN-01 uses the new guarded path.

### GEN-01-S03 — Reuse the RUN-01 lock across all mutating entry points

**Objective / requirements.** Serialize search and generation on the same physical deployment. R14/R16.

**Inputs → outputs.** Resolved data root and worker attempt ID → held RUN-01 `LockToken` or lock-busy result with no worker effects.

**Dependencies.** S01, RUN-01; DG4.

**Owned modules.** Proposed `generation/{worker,composition}.py`, `generation/cli.py`; narrow ordering correction in `orchestration/runner.py`; shared lock regression tests. Reuse `WindowsWorkerLock`; create no second lock implementation.

**Tasks.** Acquire with `OwnerKind.GENERATION` before schema initialization, local recovery, durable writes or external calls. Move search start/resume schema initialization behind the same lock, preserving search behavior. Require a held token in coordinator composition. Hold it throughout a bounded poll/recovery/work cycle, including model/render/upload callbacks. Foreground watch mode may release it between fully checkpointed cycles and idle waits; reacquire and reconcile every cycle. Never release while a mutating callback remains active. Stop after bounded calls on Ctrl+C and release handles in `finally`.

**Acceptance criteria.** Search/search, generation/generation, search/generation and generation/search collisions have one owner; loser exits 3 without DB/migration/recovery/model/Salesforce effects. Aliased paths converge on the same existing lock. A dead process's OS lock is released; an old PID/diagnostic file neither grants ownership nor requires deleting the lock file.

**Tests / failure cases.** Separate native Windows processes, forced owner termination, spaces/umlauts/case/junction aliases where available, first-run unmigrated database, injected startup failure, Ctrl+C during an injected bounded dependency call. Test real CLI order as well as the lock primitive.

**Migration/configuration and handoff.** No new lock path or PID-file protocol. Record the handoff/code discrepancy and corrected call order; keep broader RUN-01 redesign outside scope. One approved data root/request stream is an explicit operational assumption.

### GEN-01-S04 — Poll and admit requests through the existing Salesforce gateway

**Objective / requirements.** Discover queued and interrupted remote requests without skipped pages or duplicate admission. R10/R15/R16.

**Inputs → outputs.** Verified mapping/settings and bounded scan → persisted observations/C13 identities, safe issues and scan progress.

**Dependencies.** S01–S03, SFCLIENT-01; DG1/DG2 for live operation.

**Owned modules.** Proposed `generation/{polling,request_mapping,settings}.py`; `tests/generation/{test_polling,test_mapping,test_admission}.py`.

**Tasks.** Build allowlisted field projections and safe SOQL from validated identifiers/values. Use `QueryPageRequest` with either SOQL or opaque continuation, preserving gateway continuation protections. Poll separate Pending and stale Running lanes, plus Upload pending recovery where mapped; exact-read local backlog regardless of remote query state. Use deterministic ordering and bounded pages/items/time. Persist admission or issue receipts before advancing the page cursor. Restart expired cursors with overlapping scans and identity deduplication; do not rely on a CreatedDate high-water mark that excludes old Running records. Revisit incomplete scans fairly. Revalidate a request before claim. Do not write candidate application status, notes, approval or request options.

**Acceptance criteria.** Requests created while the worker is offline are admitted later. Repeated/overlapping pages create one C13 per remote request. A failure on page 2 preserves page 1 and an incomplete scan. Malformed/unmapped rows remain inspectable and do not prevent valid neighbors. No localhost connection from Salesforce is required. Unsupported configuration fails before sending an arbitrary query.

**Tests / failure cases.** Empty/multi-page responses, duplicate pages, row updates during pagination, expired/hostile cursor, same key in another org, unknown state label, missing job mapping, permission denial, quota exhaustion and one bad row among valid requests. Assert no cursor advancement past unpersisted observations.

**Migration/configuration and handoff.** Introduce a versioned request mapping distinct from SYNC-01 job mappings. Obtain actual names/labels/ownership from SF-05/06; examples use visibly synthetic values. No org changes or Flow implementation in GEN-01.

### GEN-01-S05 — Freeze through GEN-02 before projecting Running

**Objective / requirements.** Ensure every remote Running request has a committed, inspectable local input binding. R06/R10/R12/R16.

**Inputs → outputs.** Accepted C13 options and remote observation → frozen C13/manifest/claim intent, or retained preflight failure/warning.

**Dependencies.** S02–S04; real GEN-02 and DG2/DG3 for integration.

**Owned modules.** Proposed `generation/{admission,coordinator,projection}.py`; tests with an injected GEN-02 port, later actual-service integration. No availability calculation, profile selection, retrieval implementation or snapshot serialization in GEN-01.

**Tasks.** Call GEN-02 with stable request/freeze identity. Verify returned identity and manifest, then use S02's single transaction. Project Running only from its committed intent. Persist gateway acknowledgment, or uncertainty for reconciliation, before context/drafting. Record `job_unavailable` and other preflight failures without a Running transition. Preserve unknown-availability warnings and explicit candidate override evidence. On recovery use GEN-02 reopen/verification, never its current-input selection path for a sealed request.

**Acceptance criteria.** A remote observer never sees a worker-generated Running update before all local freeze references are committed. Job/profile/template edits after freeze do not change the request's inputs. Unknown availability is visible; unavailable without override fails; override is false by default. An option change during admission cannot yield mixed options/snapshots. GEN-02 absence gives a missing-component result with zero fabricated context.

**Tests / failure cases.** Kill before/after freeze preparation, during local commit, after commit before PATCH, after server commit before response, and after acknowledgment before local receipt. Assert exact snapshot hashes and IDs across restart. Test unavailable/unknown/override, revoked permission, missing snapshot file, and option-edit conflicts.

**Migration/configuration and handoff.** Snapshot/pin schema belongs to GEN-02; request association and Running intent belong to GEN-01. Document the resolved atomic integration, option immutability policy and power-loss limits. No mutable default may reinterpret an already frozen request.

### GEN-01-S06 — Coordinate context, draft, validation, rendering, and delivery ports

**Objective / requirements.** Resume the first incomplete step without duplicating logical output or crossing component ownership. R11/R12/R16.

**Inputs → outputs.** Claimed request and verified snapshot binding → durable step/output references and next-step status.

**Dependencies.** S05, GEN-02; DG5 contracts for GEN-03–06. Test fakes are permitted only as explicit test composition.

**Owned modules.** Proposed `generation/{coordinator,steps,composition}.py`; `tests/generation/test_workflow.py` and contract consumer tests.

**Tasks.** Preassign a stable operation identity for each stage/input binding. Call one owner at a time and validate returned request, freeze, strategy and output versions. Persist/reopen C09 and its exact payload, structured draft, validation report, artifact set and delivery receipt. Reconcile owner-committed output when the worker checkpoint is missing. Fatal validation stops rendering; warnings carry forward to review. Retain per-format progress so a failed PDF or upload does not redraft/re-render completed DOCX. If a port is unavailable, retain a named dependency block; do not synthesize a draft, accept validation, or mark ready.

**Acceptance criteria.** Re-running a completed checkpoint performs zero duplicate owner calls. A saved draft resumes validation; validated draft resumes rendering; saved artifacts resume delivery. Output for another request/binding is rejected. Ready requires all advertised required formats delivered; delivery never changes approval. A G3-only explicit `--through context` run stops with a durable continuation and reports G4 pending; it cannot claim complete document delivery.

**Tests / failure cases.** Strict spies/fakes for stage order and call counts; lost return after each owner's commit; fatal versus warning validation; one of two formats complete; missing renderer/delivery port; JSON overflow propagated without strategy switch; artifact hash mismatch; quota failure; approval remains candidate-owned.

**Migration/configuration and handoff.** C13 retains existing state values. A companion output-set mapping handles multiple formats; coordinate any C14 extension with GEN-05/06 and keep legacy ports compatible. Model prompts, file conversion, upload lookup and notification implementations remain with their owners.

### GEN-01-S07 — Reconcile local work and stale remote Running requests

**Objective / requirements.** Recover every admitted request without unsafe re-freezing, state regression, or blind mutation retries. R10/R12/R16.

**Inputs → outputs.** Local attempts/checkpoints/intents plus exact remote observations → reuse/replay/reconcile/repair decisions and durable next actions.

**Dependencies.** S02–S06, SFCLIENT-01; DG2 and GEN-02 reopen/verification; GEN-06 only for delivery reconciliation.

**Owned modules.** Proposed `generation/{recovery,projection,retry}.py`; tests for local/remote reconciliation and restore divergence.

**Tasks.** Implement the recovery table above. Reconcile local history before acting on remote staleness. Recover only this deployment/request stream and selected request IDs; do not invoke blanket run/outbox/generation failure routines. Keep ordered projection intents separate from job C12 sync operations. Query marker/state/binding after uncertain mutations, block superseding writes while uncertain, and adopt acknowledged outcomes. Include terminal rows with pending intents and legacy interruption failures. Retain all attempt errors and decisions.

**Acceptance criteria.** Remote Running with local history resumes the same UUID/snapshots. Remote Running without exact recoverable inputs becomes explicit repair/failure and never freezes latest. A restored older DB cannot regress remote Ready to Running. A late Running response cannot overwrite a newer terminal projection. Polling only Pending is insufficient and rejected by tests. Recovering an upload does not create another draft/version.

**Tests / failure cases.** Exercise each recovery-table row, including a delayed server commit after timeout, stale/fresh/missing timestamps, mismatched markers, permission versus deletion, unavailable backup files, legacy failed rows and remote-ahead-of-local delivery. Fake server state must outlive killed workers.

**Migration/configuration and handoff.** Document the actual SF-05/06 resolution for guarded transitions. Until resolved, ambiguous outcomes stay blocked, never optimistically retried. Staleness configuration controls scanning, not authority or lock stealing. Record restored-state limitations for OPS-01.

### GEN-01-S08 — Bound retries and expose a manual Windows worker CLI

**Objective / requirements.** Make progress and failures operable without unattended Phase 2 machinery. R10/R12/R14/R15/R16.

**Inputs → outputs.** Validated settings and manual invocation → bounded worker cycle/watch loop, durable retry schedule and safe text/JSON report.

**Dependencies.** S03–S07, existing CLI/configuration and SFCLIENT-01 error/budget envelopes.

**Owned modules.** Proposed `generation/{cli,settings,reporting,retry}.py`, root CLI registration, optional `AppConfig` reference/path extension, synthetic configuration examples and `tests/generation/test_cli.py`.

**Tasks.** Proposed commands: `generation work --once` (default bounded cycle), explicit `--watch` foreground polling, `generation show --request-id`, and `generation retry --request-id`. Retry requires a classified retryable/repaired condition and unchanged binding; it is not regeneration. Show is read-only and does not migrate/recover. Exit meanings follow RUN-01: 0 completed bounded scope/empty scan, 1 fatal, 2 invalid configuration/dependency, 3 lock busy, 4 partial/pending, 130 controlled interruption. Request-level pending/failed counts remain explicit even if other work succeeds.

Persist stage attempts/due time/backoff before dispatch and consume finite budgets across restarts. Distinguish logical stage retry from SFCLIENT-01's internal physical sends; honor `retry_not_before` and use the later of server and local backoff. Retry only recoverable categories; auth/permission/configuration/validation issues require repair, not a tight loop. Uncertain mutations go to reconciliation regardless of generic retryability. Upload capacity exhaustion stays Upload pending with a repair reason even when automatic delivery attempts stop. A manual retry records authorization and new attempt budget without erasing history or resetting identity.

**Acceptance criteria.** Repeated restarts cannot bypass attempt limits or cooldown. Rate-limited watch mode sleeps and releases the lock between completed cycles. Missing production dependencies fail explicitly; there are no silent fake adapters. Output contains IDs, stages, counts, warnings and actionable safe reason codes, but no raw candidate facts, prompts, documents, credentials, queries or provider exception bodies.

**Tests / failure cases.** Fake clock/jitter, retry exhaustion, Retry-After, physical-send accounting, interruption during backoff, invalid config precedence, broken stdout after commit, read-only inspection and Unicode paths from a different CWD. Stop/restart retains pending work and attempts.

**Migration/configuration and handoff.** Apply the configuration table below; no new external service/dependency required. Defer Task Scheduler/service installation and automatic request creation. Treat human-readable Europe/Berlin display separately from UTC persisted timestamps.

### GEN-01-S09 — Prove crash behavior and publish the component handoff

**Objective / requirements.** Establish measured GEN-01 acceptance, with G3 and G4 evidence kept distinct. R10/R12/R14/R16.

**Inputs → outputs.** S01–S08 and dependency gates → reproducible offline/native/integration results and future `docs/components/GEN-01.md`.

**Dependencies.** All prior stories; SF-05/06 and real GEN-02 for live G3. GEN-03–06 and SF-07/08 only for later G4 acceptance.

**Owned modules.** `tests/generation/test_crash_matrix.py`, `test_windows_restart.py`, `test_windows_paths.py`, native process harness and synthetic fixtures; future handoff and narrow README instructions.

**Tasks.** Implement the matrix below using real SQLite/repositories/lock/worker, explicit GEN owner fakes and a scripted SFCLIENT transport. Keep fake remote state in an independent process/store. Kill the worker at deterministic barriers around each transaction/send/receipt, reopen with a new process and assert record counts, UUIDs, hashes, state and call counts. Add real GEN-02 integration when its handoff exists. Separately demonstrate an authorized SF-06 action queued while offline, freeze-before-Running, restart and deliberate regeneration in the existing org once access exists.

**Acceptance criteria.** All required offline cases have explicit state/identity/count oracles. Native Windows subprocess tests establish exclusion and handle release. Live prerequisite failures are recorded pending, never passed skips. Test results do not claim semantic draft quality, renderer correctness, real upload deduplication or notification delivery on behalf of GEN-03–06/SF-08.

**Migration/configuration and handoff.** Record actual migration/contract versions, API signatures, dependency gate status, native commands/results, retry accounting, retention pins, power-loss/restoration limitations and next owners. This story plan itself runs none of these implementation checks.

## GEN-03–06 integration contracts only

| Owner | Worker handoff / durable return | GEN-01 responsibility and boundary |
|---|---|---|
| GEN-03 | Frozen C13, C09/payload binding, document language/type and stable draft operation ID → C14 structured draft plus model audit reference. | Persist/reopen result and verify identity. No prompts, inference policy, claim creation or content edits. |
| GEN-04 | Exact draft and frozen source refs → versioned report with fatal errors, review warnings and validated draft hash. | Block on fatal outcome; retain warnings and report ref. No factual/semantic validator implementation or automatic approval. |
| GEN-05 | Validated draft/report hash, pinned template, required formats and stable output slots → durable artifacts/versions/hashes plus reopen lookup. | Check receipt binding and resume missing slots. GEN-05 assigns/resolves artifact versions and publishes files; worker never runs LibreOffice or manufactures bytes. |
| GEN-06 | Durable artifacts and preassigned request/artifact/version reconciliation identities → pending/reconciled delivery and typed file/version/access receipts. | Delegate uncertain upload recovery; project status from durable evidence. No Files upload/search logic or direct notification sending. Agree one owner of each request-state write so GEN-01 and GEN-06 never race. |

Proposed state-write ownership: GEN-06 persists authoritative delivery outcomes; GEN-01 alone dispatches C13 processing-state projections, including Ready. SF-08 reacts to agreed delivered transitions. If GEN-06's eventual handoff chooses a different publisher, adapt the port and retain a single ordered writer with the same durable intent rules. Never have both components PATCH status independently.

## Configuration impact

All values below are proposed starting defaults for tests/implementation, subject to capacity checks and the missing owner contracts. They are not measurements of this org or hardware.

| Setting / reference | Proposed behavior |
|---|---|
| `generation_settings_ref` and resolved path | Optional additive AppConfig reference; absence preserves existing search configuration. Required for production generation commands. Resolve relative refs against the config directory, runtime data outside the checkout. |
| `request_mapping_ref` / mapping version | Explicit object/field/state mappings, org scope, identity/marker/frozen-ref/error/result fields and worker-owned allowlist. No assumed deployed names or inline secrets. |
| Poll mode / interval | Bounded `--once` default; explicitly requested foreground watch, proposed 60-second interval with bounded jitter. No automatic startup. |
| Work limits | Proposed 20 requests and 10 query pages per cycle, one active request and one model call at a time; finite cycle admission deadline. A currently active bounded owner call may finish/checkpoint before exit. Reserve scan/work capacity for both recovery and new requests. |
| Remote Running staleness | Proposed 30 minutes and 2-minute clock-skew allowance, using the agreed worker timestamp. Validate against actual stage timeouts/heartbeat behavior; never use age as ownership proof. No timestamp/owner mapping means explicit recovery gate. |
| Retry policy | Proposed 5 durable stage attempts, exponential backoff starting at 30 seconds capped at 15 minutes, finite reconciliation attempt budget, server Retry-After respected. Per-stage overrides require validation; exhausted uncertainty remains repair work. No reset on process restart. |
| Gateway settings | Reuse `salesforce_settings_ref`, protected credential refs, API version, timeouts/send limits and approved origins. Do not create independent OAuth settings or multiply gateway internal retries. |
| Input/execution settings | Resolve profile/policy/template/language/context/model/index choices through owner interfaces and seal their binding. Initially accept de/en, cv/cover_letter and json/rag as configured capabilities; language is not candidate proficiency. No invented production model/template choice. |
| Required artifact formats | Proposed DOCX + PDF through GEN-05/06; requested/advertised set is frozen. No Ready after only one required format is delivered. |
| Paths, reporting and time | Existing absolute data root, database/artifact/index directories and RUN-01 lock path. UTC machine times, Europe/Berlin display, safe text/JSON reporting. No sensitive payloads in diagnostic logs. |

Validate limits/types, mapping/state completeness, required dependency capabilities, supported schema versions and positive timeouts before admission. Capacity errors remain visible and preserve durable work. OPS-01 owns cleanup/backups; expose references and pins rather than adding retention execution to GEN-01.

## Required crash and recovery matrix

| ID | Fault / scenario | Required oracle |
|---|---|---|
| GEN-T01 | All search/generation lock pairings, aliased roots, unmigrated DB, owner killed | One holder; losing worker has zero DB/recovery/network/model effects. Next holder recovers after kernel release. |
| GEN-T02 | Poll offline backlog, duplicate/overlapping pages, crash before cursor commit | One C13 per org/request; no skipped unpersisted row; scan completion remains honest. |
| GEN-T03 | Every statement of freeze transaction fails | Request, manifest refs/pins, freeze receipt and Running intent commit together or roll back; zero remote Running on failure. |
| GEN-T04 | Freeze files prepared but transaction never commits | No claimed C13 references incomplete files; safe orphan references retained for later cleanup; restart admits once. |
| GEN-T05 | Local freeze commits, process dies before Running send | Same UUID, options and hashes used; zero re-freeze from latest; original intent sent. |
| GEN-T06 | Server commits Running, response/local acknowledgment lost | Readback of matching marker/binding acknowledges same intent; no new request, no blind PATCH retry. |
| GEN-T07 | Timed-out Running write executes late; newer terminal intent exists | Ordering barrier prevents stale Running overwrite and duplicate state-transition events; unresolved outcome stays pending repair. |
| GEN-T08 | Job/profile/policy/template/index defaults change after freeze | Same sealed snapshots/settings used on resume; explicit permission revocation blocks through GEN-02 without substituting newer inputs. |
| GEN-T09 | Unavailable, unknown, explicit override, override added to failed request | Correct failure/warning; zero Running for rejected preflight; changed override requires new linked request. |
| GEN-T10 | Kill before/after context, draft and validation result commits | Adopt verified owner output or retry only unsaved work; stable logical draft/version, no completed step replay. |
| GEN-T11 | DOCX saved, PDF incomplete; worker dies after artifact commit | Reuse DOCX ID/hash/version; resume missing format through GEN-05; no redraft. |
| GEN-T12 | Upload succeeds but response lost; capacity failure | GEN-06 reconciliation invoked before resend; same markers; local files retained and Upload pending; no false Ready. |
| GEN-T13 | Ready/Failed local commit, remote projection acknowledgment lost | Terminal rows remain recoverable; only projection reconciled; no model/render/upload replay or approval mutation. |
| GEN-T14 | Stale remote Running with no local row or missing/corrupt snapshots | Reconstruct only from exact verified evidence; otherwise inspectable repair/failure with same remote identity, never latest-input refreeze. |
| GEN-T15 | Remote Ready ahead of restored DB; foreign marker; deleted/inaccessible record | No state regression/replacement request; receipt reconciliation or explicit blocked repair. |
| GEN-T16 | Retry, repeated restart, duplicate active UI action, deliberate regeneration | Retries keep IDs/snapshots/counters; reused active row has one C13; new action ID/predecessor yields separate C13/output slots. |
| GEN-T17 | Auth/permission/quota/transient error, Retry-After, budget exhaustion | Correct classification/due time; bounded physical/logical attempts; no restart budget reset or false success. |
| GEN-T18 | Missing GEN-02/03–06 port; wrong request/binding returned | Named dependency/error and preserved checkpoint; no fabricated context, validation, artifacts or delivery. |
| GEN-T19 | Legacy recovery-failed row, duplicate identity during migration, cascade delete | Recover only proved interruption; no destructive deduplication; referenced history protected; migration rollback preserves original DB. |
| GEN-T20 | Ctrl+C, storage-full, broken stdout, Unicode paths and different CWD | Durable last checkpoint, explicit pending/failure, released handles; repeat run preserves identity; diagnostics contain no sensitive payloads. |

## Future verification and handoff

These commands are for the future implementation, after the proposed test modules exist. They were not run for this Markdown-only task. Start in the repository root with native PowerShell; tests own synthetic data outside the checkout.

```powershell
$genRepo = (Resolve-Path '.').Path
$genPython = Join-Path $genRepo '.venv\Scripts\python.exe'
$genTemp = Join-Path $env:TEMP ('Job Automation GEN Prüfung ä ' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $genTemp | Out-Null

& $genPython -m pytest (Join-Path $genRepo 'tests\generation') (Join-Path $genRepo 'tests\storage') (Join-Path $genRepo 'tests\contracts') (Join-Path $genRepo 'tests\orchestration') (Join-Path $genRepo 'tests\salesforce') (Join-Path $genRepo 'tests\test_configuration.py') (Join-Path $genRepo 'tests\test_cli.py')
if ($LASTEXITCODE -ne 0) { throw 'Generation or affected boundary checks failed' }

Push-Location -LiteralPath $genTemp
try {
    & $genPython -m pytest (Join-Path $genRepo 'tests\generation\test_windows_paths.py') (Join-Path $genRepo 'tests\generation\test_windows_restart.py') (Join-Path $genRepo 'tests\orchestration\test_windows_lock_processes.py') --basetemp (Join-Path $genTemp 'Test Daten ö')
    if ($LASTEXITCODE -ne 0) { throw 'Native generation checks failed' }
} finally {
    Pop-Location
}
```

Later manual command shape, after settings, real GEN-02 and SF-05/06 are available:

```powershell
$genAppConfig = Join-Path $env:LOCALAPPDATA 'JobAutomation\app.json'
& $genPython -m job_automation generation work --config $genAppConfig --once --through context
# Inspect the emitted request UUID; no new request is created by show or retry.
$genRequestId = 'REPLACE-WITH-EMITTED-REQUEST-UUID'
& $genPython -m job_automation generation show --config $genAppConfig --request-id $genRequestId --json
```

An explicitly context-limited G3 run reports its saved continuation and pending G4 stages; it does not report Ready. Full workflow commands require real GEN-03–06 composition. Final CLI syntax is frozen in S08 and recorded in the implementation handoff.

Completion checklist:

- All nine stories have explicit implementation/verification status and DG1–DG5 evidence or named pending owners.
- C13 identity, retry/regeneration distinction, atomic freeze association and remote Running ordering are proved with database and remote-state assertions.
- Native shared-lock tests cover the actual search and generation entry points, including schema initialization and process death.
- Recovery covers local incomplete work, terminal projection backlog, stale remote Running, orphan requests, legacy rows and restored databases; no latest-input substitution.
- GEN-02 and GEN-03–06 signatures, output identity rules and single status publisher are documented without moving their business logic into GEN-01.
- Migration, schema, mapping, configuration, retry budget, retention pin and compatibility changes are listed with exact versions.
- Unit/contract, fake transport, actual GEN-02 integration, native Windows and live Salesforce G3 results are reported separately. G4 document/delivery/review/notification acceptance remains with its owners.
- The future `docs/components/GEN-01.md` records commands/results, limitations, safe diagnostics and next steps. This planning change adds only `docs/stories/GEN-01.md`.
