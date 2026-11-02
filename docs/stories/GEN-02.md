# GEN-02 — Frozen job/profile inputs and context implementation stories

Status: **PLANNED — documentation only; implementation and verification pending**  
Date: 29 October 2026  
Component: **GEN-02 only**, Phase 1  
Direct requirements: **R06, R10, R11**; supporting constraints: R03, R04, R09, R12, R14, R15, R16  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially §§4–9 and G3  
Repository instructions: [README.md](../../README.md) and blueprint §§8–9. No applicable `AGENTS.md` was found in the repository or checked ancestor directories.

## Objective and boundary

Provide a worker-independent service that rechecks availability, freezes the exact job content, approved profile, generation options and context recipe, and later constructs JSON or RAG context using only those sealed inputs. A failed preflight remains a durable, inspectable request. Confirmed unavailable jobs fail with `job_unavailable` unless the candidate explicitly selected `allow_unavailable_job`; unknown availability proceeds with a visible warning.

GEN-02 owns input resolution, preflight decisions, immutable snapshot storage, request-bound retrieval authorization, reopening, and context receipts. Minimal contract, storage, configuration, inspection and consumer-adapter changes necessary for these guarantees belong here. It must work through an ordinary local Python interface without Salesforce, a polling loop, an acquired worker lease, or a model-generation call. SQLite concurrency checks remain necessary even when GEN-01 normally holds the deployment lock.

GEN-01 continues to own polling, claiming, remote state projection, attempts/backoff and worker recovery. IDENTITY-02 owns availability inference; PROFILE-01 owns approval and inclusion; CONTEXT-01–04 own preparation, retrieval, indexing and budgeting. GEN-03 owns drafting prompts and document content, GEN-04 factual validation, GEN-05 templates/rendering, GEN-06 delivery. Consume their versioned inputs or explicit test fakes; do not implement those components, deploy Salesforce metadata, create documents, add a scheduler, or enable automatic drafting.

## Evidence from current code and handoffs

Read [DATA-01](../components/DATA-01.md), [IDENTITY-02](../components/IDENTITY-02.md), [PROFILE-01](../components/PROFILE-01.md), and [CONTEXT-04](../components/CONTEXT-04.md) against current code. Also inspect the existing [GEN-01 handoff](../components/GEN-01.md) for compatibility. Earlier story files describe historical planning states; current modules and contracts take precedence over their claims that packages are absent.

| Dependency / current implementation | Consequence for GEN-02 |
|---|---|
| DATA-01; `storage/connection.py`, `storage/engine.py` | SQLite, composable transaction bookkeeping and repositories exist. The transaction helper does not explicitly begin a read snapshot before initial SELECTs. Establish a real snapshot/write boundary or compare-and-set validation; a Python context manager alone does not prove consistent reads. |
| `contracts/generation.py` | C13 v1.0 has options and `FrozenInputVersions` with posting/profile/policy/template strings. These labels do not contain full inputs or prove immutability. Failed C13 records may have no frozen versions, which supports preflight rejection. |
| `generation/ports.py`, `generation/records.py` | `GenerationInputService.prepare_freeze`, `reopen_freeze`, and `build_context` already exist as protocols. `FreezeManifest` includes version labels, hashes, `snapshot_refs`, warnings and options digest, but no concrete GEN-02 implementation exists. Its defaults (`availability_status="active"`, empty refs) are insufficient evidence for a real seal. |
| `storage/repositories/generation_work.py` | `commit_frozen_request` atomically writes request state, association, checkpoint and Running intent. Its existing-freeze check is outside the transaction and it does not persist/verify snapshot bodies or request-owned pins. Extend only the commit boundary needed to register and validate a GEN-02 seal. |
| `generation/coordinator.py`, `admission.py` | Coordinator calls the existing input port and emits timestamp-based operation IDs; failures currently write request/checkpoint/projection separately. Admission checks cached availability before GEN-02 and coerces overrides with `bool(...)`. This cannot establish a fresh, explicit candidate override or independent GEN-02 failure durability. Small integration corrections are required; worker redesign is excluded. |
| IDENTITY-02; `identity/availability/`, `storage/repositories/availability.py` | Durable source/scope state, decision ledger and canonical aggregation exist. Any active source keeps a job active; only all unavailable sources close it. `not_seen` and `unknown` remain distinct. There is no general live URL availability probe. |
| C06/C07; `storage/repositories/canonical_jobs.py`, `identity/hashing.py` | `PostingRevision` contains metadata, not the full description. Normalized postings are mutable per source key and revision rows can be updated/reparented. Freeze full C06 content plus canonical/revision binding. `compute_revision_content_hash` hashes normalized material content; it differs from C06 `raw_content_hash`. |
| PROFILE-01; `storage/repositories/profiles.py`, `profile/inclusion.py`, `profile/references.py` | Approved C01 snapshots and exact historical fact resolution exist. Bind candidate identity as well as version. Historical resolution alone does not authorize new use: freeze purpose and permissions at acceptance, then resume that authorized request. |
| CONTEXT-04; `context/selector.py`, `selector_records.py` | `ContextSelectorV2Service.select_context` consumes `ContextSelectionRequest`, returning `ContextSelectionResult` (C09, measured `RenderedPrompt`, trace, fingerprint) or a classified error. JSON and RAG share preparation; neither may silently substitute for the other. Live model verification is still pending in the handoff. |
| `context/binding.py`, `selector_validation.py` | Default job binding compares a `sha256:` revision to the raw hash, not IDENTITY-01's material revision hash. Use a snapshot-aware binding validator; do not alter hashes to make this check pass. Validate the frozen membership without querying current identity mappings. |
| `context/index_reader.py`, `contracts/retrieval_index.py` | `IndexReadRequest.authorization_mode="frozen_use"` and explicit generation IDs exist. The frozen branch checks any active pin and file integrity, but does not enforce all expected candidate/purpose/profile/fingerprint bindings or ownership by this request. GEN-02 must enforce these before returning a handle. |
| `operations/inventory.py`, index pins | OPS protects active/building/pinned indexes. New seal and context dependencies need explicit retention/backup registration, including failed requests with retained inputs. Do not assume existing unfinished-request protection covers every new file. |
| Migrations and tests | Current migration head is 010. Allocate the next version at implementation time, without modifying applied migrations. Existing generation tests use `FakeInputService`; their passing status does not demonstrate real frozen input/context behavior. |

All source paths in this table are relative to `src/job_automation/`. The prerequisite handoffs record historical test results, not tests executed by this planning task.

## Confirmed requirements and proposed decisions

The worker-independent boundary, explicit unavailable override, visible unknown warning, inspectable failures, immutable inputs, and both context strategies are requirements. The following are proposed technical choices for implementing them:

1. **Recheck means a fresh authoritative local read at sealing.** Read IDENTITY-02's canonical state and supporting source/scope evidence again, even if admission previously passed. Record `checked_at` separately from observation times; do not claim a live source check. Source refresh, when requested separately, runs through INGEST/IDENTITY before sealing. GEN-02 does not fetch arbitrary job URLs, invent a manifest, increment miss counts, or infer closure from a timeout, HTTP response, deadline, or old `last_seen_at`.
2. **Seal once per request.** Persist a complete seal before returning a successful `prepare_freeze`. The local request may remain Pending until GEN-01 claims it. A successful seal fixes inputs even if the worker crashes before claim. Repeated calls, including calls with new transport/attempt IDs, reopen the same seal. Changed accepted options require a new request, not replacement of the original seal.
3. **Store compact snapshot bodies and context receipts in SQLite initially.** Use insert-only canonical JSON plus checksums for C01, full C06, binding, options, availability and recipe. Pin existing index directories and content-addressed resources. Large template/resources may use verified staged files under the configured data root; ordinary logs never contain these private payloads.
4. **Require a compatible existing RAG index before sealing.** Resolve it for the chosen candidate/profile/purpose, verify it and acquire a request-owned pin. Missing/incompatible indexes produce an inspectable preflight error with remediation through CONTEXT-03. GEN-02 does not build an index or fall back to JSON. JSON has no index or embedding dependency.
5. **Freeze use authorization at acceptance.** A new request uses the current approved snapshot and purpose-specific permissions, with no user-selected historical-version bypass. An already sealed request resumes those permissions without consulting newer facts or current permission lists. A later correction/removal/permission edit affects new requests. An explicit cancellation/revocation mechanism, if introduced by its owner, may stop an old request without replacing its content; it is not inferred from new profile facts.
6. **Freeze the context recipe before selection.** Prompt/instruction and output-schema inputs are supplied by a versioned caller/configuration boundary owned by GEN-03. GEN-02 validates, snapshots and budgets them; it does not invent production drafting prompts. Missing production recipes remain an explicit dependency/configuration error. Synthetic recipes permit isolated verification.

### Availability decision table

| Authoritative state at freeze | Explicit override | Outcome |
|---|---|---|
| `unavailable` | absent or false | No usable seal/context. Durable failed C13 and preflight receipt; `ClassifiedError(category=validation, recoverable=false, details.reason_code="job_unavailable")`. Never publish Running. |
| `unavailable` | true, bound to candidate choice | Seal and proceed; preserve unavailable state, override provenance and visible `job_unavailable_overridden` warning. |
| `unknown` | either | Seal and proceed with `job_availability_unknown`, observation/check times and safe reason. |
| `not_seen` | either | Proceed with a distinct `job_not_seen` warning. It is not confirmed unavailable. |
| `active` | either | Proceed, preserving the evidence/check time. An unavailable alternate source cannot close an active canonical job. |
| Missing/conflicting evidence | either | Missing canonical job is a validation failure. Unreliable availability evidence is explicitly unknown (warning), unless it represents a storage/integrity failure, which fails visibly. Do not turn a database error into permissive unknown. A recorded authoritative unavailable decision cannot be downgraded merely to bypass the gate. |

No global configuration may turn on `allow_unavailable_job`. Accept a strict boolean from a trusted local caller or validated candidate-owned request observation; strings such as `"false"`, null, scores, notes and job text do not grant an override. Retain the supplied choice and its request/observation identity and timestamp. SF-06 owns the candidate action itself.

## Contracts to establish before business logic

Keep C01, C06, C07, C08, C09 and C13 semantics intact. Proposed companion records below are versioned GEN-02 contracts; exact module names can change within the boundary. Do not silently overload C13's four version strings with serialized inputs.

| Record / interface | Required inputs, outputs and invariants |
|---|---|
| `FrozenGenerationOptions` | Document type and derived purpose (`cv` or `cover_letter`), requested language, template ID/resolved version/content digest, strategy, explicit override and provenance, resolved generation settings, optional output formats when supplied. Canonicalize values and persist full payload plus a versioned digest; exclude worker attempt/timing fields from option identity. |
| `FrozenJobSnapshot` | Canonical ID, company identity/name as frozen, exact revision UUID and material content hash, source key, complete C06, source/application URLs and provenance, observation/raw references and their hashes, normalizer/hash algorithm versions, and a digest over the full stored body. Check revision membership and content consistency before sealing. |
| `FrozenProfileSnapshot` | Full approved C01, candidate ID, profile version, approval metadata, snapshot digest, purpose, inclusion/mandatory rule versions and explicit mandatory fact IDs. Permissions and explicit eligibility are frozen data. Preserve fact IDs, parent links, nulls and date precision. |
| `AvailabilityCheck` | Check ID/time, canonical state, source/scope evidence and decision references, policy fingerprints, observation times, decision outcome, override evidence and safe warning codes. It reports the state at freeze, not perpetual job availability. |
| `FrozenContextRecipe` | Instruction/output-schema bytes or immutable verified refs; requirements and extraction recipe/hash from the frozen job (never a later assessment); model identity/digest and inference settings; context limit/output reserve/safety allowance; measurement method/version and exactness policy; builder, serializer, inclusion, mandatory, prompt/chat-template versions; resolved retrieval settings and embedding config for RAG. Persist values as well as fingerprints. |
| Extended seal / `FreezeManifest` | Request and candidate binding, all existing fields, document purpose, schema/hash versions, typed snapshot descriptors (`kind`, schema, immutable locator, digest), recipe and availability receipt refs, and RAG generation/manifest/chunk/settings/embedding fingerprints plus pin identity when applicable. Hash canonical serialization excluding the hash field itself. Validate redundant manifest fields against bodies. Return detached objects; nested mutable lists/dicts must not mutate persisted truth. |
| `PreflightReceipt` | Request identity, accepted request/options digest, physical attempt/operation ID, start/end UTC timestamps, result (`prepared` or `failed`), optional seal ref, warnings, and classified error/reason code. Unresolved inputs remain null. Store failure history without requiring a fake successful manifest. |
| `FrozenContextReceipt` | Stable context identity bound to manifest hash and recipe hash, full `ContextSelectionResult` including measured prompt/trace, merged preflight/context warnings, result hash and status/error history. Separate physical attempts from one logical context result. |
| Existing `GenerationInputService` | Preserve `prepare_freeze(request, freeze_op_id) -> (FreezeManifest?, ClassifiedError?)`, `reopen_freeze(manifest_id) -> (...)`, and `build_context(manifest, context_op_id) -> (ContextBundle?, ClassifiedError?)`. Exactly one result/error is non-null. Implement it as an adapter over the standalone service. |
| Additive inspection/result access | Provide `inspect_preflight(request_id)` and exact `reopen_context(receipt_id)` access without a worker. The latter returns the complete selection result; the legacy `build_context` adapter returns its C09 projection. GEN-03 must be able to consume the identical measured prompt, not reconstruct it from mutable defaults. |

Use `ClassifiedError.details.reason_code` for stable GEN-02 codes, following existing `job_unavailable` usage. Proposed additional codes include `freeze_conflict`, `profile_unapproved`, `job_snapshot_mismatch`, `frozen_input_missing`, `frozen_input_corrupt`, `frozen_index_mismatch`, `recipe_unavailable` and `preflight_interrupted`. Retain existing error categories, especially `context_budget`, missing configuration, capacity and transient service errors; do not reference a nonexistent `ErrorCategory.CONFLICT` or add a new processing-state enum implicitly. Warnings are structured codes with safe display text, persisted in receipts, exposed through inspection, and copied to C09. Ordinary diagnostic output contains IDs/hashes/codes, not profile facts or prompts.

New companion schemas start at 1.0. Preserve legacy C13 and manifest fixtures; define an explicit additive envelope/version for new fields. Legacy manifests without verified bodies remain readable for audit but cannot authorize context generation. Their remediation is recovery of the original inputs or a new request, never silently filling them from current state. Export schemas and record the compatibility decision in the implementation handoff.

## Transaction and recovery boundaries

| Boundary | Atomic contents and external work | Crash/replay behavior |
|---|---|---|
| T0 — durable admission to preflight | Create/reuse the local C13 identity and accepted-option binding plus a started preflight attempt. Existing requests are checked for matching identity/options. No remote writes. For an unmapped/deleted job that cannot satisfy the current C13 FK, retain an identity-bearing failure receipt/observation; never fabricate a canonical job. | A crash leaves an inspectable Pending request/started attempt. Recovery marks the attempt interrupted and retries preflight only if no successful seal exists. |
| Preparation outside a write transaction | Read immutable resources, verify hashes/index files and resolve configuration; no source fetching, embedding, token measurement or other long operation under a database write lock. Retention coordination protects files being validated. | Unpublished staged resources are not a successful seal. Orphans are reconciled under OPS rules. |
| T1 — seal or preflight failure | Use an explicit SQLite transaction with a write reservation before authoritative SELECTs, or a documented equivalent CAS protocol. Re-read accepted request, current revision, approved profile, availability and RAG generation/bindings. If preparation inputs changed, retry bounded preparation before sealing. Atomically insert snapshot bodies, recipe, availability receipt, successful preflight receipt and request-owned pins/reference edges. A failure instead atomically writes failed C13 (when admissible), error/completion time and failure receipt. | All bodies and refs appear together or none do. First successful seal wins under concurrent callers. T1 success leaves C13 Pending; T1 failure has no claimed time/Running intent. Retries after a sealed success reopen it without resolving mutable inputs again. |
| T2 — claim integration, owned by GEN-01 | `commit_frozen_request` verifies the durable seal/request/options/hash and required pins inside its transaction; atomically registers its association, frozen C13 versions, guarded Pending-to-Running transition, freeze checkpoint and Running intent. Keep existing worker-owned projection behavior. | Failure leaves a reusable prepared seal and Pending C13. A repeated exact claim is idempotent; mismatched options/seal is a conflict. No remote Running may precede this commit. |
| Tfail projection integration | GEN-02 already committed the preflight failure independently. GEN-01 idempotently registers its failed checkpoint and Failed intent from that receipt in a short transaction, then dispatches outside it. Avoid a second competing error/terminal transition. | Failure remains inspectable while the worker or Salesforce is offline. Recovery can recreate/reconcile a missing projection intent from the durable receipt. |
| T3 — context result | Reopen and verify seal; perform selector calls, local query embeddings and measurement outside write transactions. Atomically save complete selection result and stable receipt/ref/hash, or an inspectable context failure. C13's existing seal is untouched. | A saved result is reopened byte-for-byte on retry, even if operation IDs change. Interrupted unsaved selection may rerun on the same inputs. A conflicting second result never overwrites the first. |

Explicitly test nested repository calls: no inner `with self.conn` or helper may prematurely commit T1/T2/T3. Enforce uniqueness and request-state predicates in the database transaction, not only in a preceding read. A worker-independent caller need not own the global process lock; SQLite guards and retention coordination must still protect consistency.

For staged files, write/flush/close and atomically publish verified content-addressed files before committing references. A filesystem rename and SQL commit are not one transaction: tolerate unreferenced published files, never references to partially written files. Keep unresolved/corrupt inputs as visible errors, with no fallback to latest snapshots. A total disk/database failure cannot guarantee a new receipt; preserve any existing T0 record, return a capacity/storage error and report inability to persist rather than claiming the failure was saved.

## Ordered implementation stories

### GEN-02-S01 — Freeze contracts, error semantics and compatibility

**Objective:** Make the service boundary precise before storage or orchestration changes.  
**Requirements:** R06, R10, R11; supporting R15/R16.  
**Dependencies:** FND-01 contracts; DATA-01; current GEN-01 port (compatibility consumer, not a prerequisite worker).  
**Owned modules:** proposed `generation/input_records.py`, `input_ports.py`, `input_errors.py`; additive changes to `generation/records.py`, `ports.py`, schema exports and fixtures.  
**Inputs → outputs:** C13 plus resolved dependency inputs → validated companion contracts, error/warning vocabulary and compatibility adapters.

Tasks:

- Define records and invariants above, stable logical IDs, canonical hash algorithms, strict option validation and candidate choice provenance. Separate manifest identity, material revision hash, raw payload hash and full snapshot hash.
- Specify the existing tuple-return port and additive complete-context/inspection interface. Test protocol conformance without importing worker, Salesforce or CLI construction code.
- Map every preflight outcome to persisted status, reason code, retry eligibility and warning visibility. Preserve C13 processing states and legacy contract meanings.
- Define supported recipe versions and legacy-manifest rejection for executable use; register companion schemas and synthetic fixtures.

Acceptance: a schema round trip preserves every frozen option and binding; omission of the override means false; a string value cannot authorize unavailable generation; an incomplete legacy manifest is inspectable but cannot execute; callers cannot return both a result and an error. The worker adapter remains source-compatible.

Tests: proposed `tests/generation/inputs/test_contracts.py`, `test_options.py`, `test_protocol_boundary.py`; extend affected C13/schema fixtures. Configuration impact: establish the settings schema only; no production defaults or remote mappings change in this story.

### GEN-02-S02 — Durable seals, preflight history and atomic references

**Objective:** Persist complete, verifiable inputs and failures independently of the worker.  
**Requirements:** R10/R11; supporting R09/R12/R16.  
**Dependencies:** S01, DATA-01, current generation/index repositories.  
**Owned modules:** proposed `storage/repositories/generation_inputs.py`, `generation/input_store.py`; narrow additions to engine, migrations, generation claim storage and retention registration.  
**Inputs → outputs:** accepted request and snapshot payloads → insert-only seal/preflight records, dependencies/pins and reopenable receipts.

Tasks:

- Add the next forward migration for preflight attempts/receipts, immutable seals/bodies, request-bound references and context receipts. Specify unique request seal and logical context keys, checksums, foreign-key behavior and insert-only enforcement. Protect failed/pending references as well as Running requests from cascade loss.
- Implement T0/T1/T2/T3 primitives, exact replay and conflict detection. Move commit-time validations inside transactions and synchronize relational columns with C13 JSON.
- Preserve error records when no complete snapshot can be produced. Handle missing jobs through a durable failure envelope where existing FK constraints prevent C13 insertion.
- Add retention roots and backup/restore inventory for new data. Pins belong to request/seal, survive restart and index retirement, and are not released merely because a stage failed or the worker exited. Release only through explicit lifecycle/retention decisions after dependency checks.
- Provide integrity-checked detached reads and staged-file recovery if any input cannot live in SQLite.

Acceptance: fault injection at each write leaves no partial successful seal/claim; a rejected preflight survives close/reopen; concurrent exact calls produce one seal; conflicting calls do not overwrite it; migrating a populated v010 database preserves requests/checkpoints and never manufactures snapshot bodies.

Tests: proposed `test_storage.py`, `test_transactions.py`, `test_migrations.py`, `test_retention.py`; affected storage/operations integration tests. Configuration impact: configurable data-root-relative generation input storage only if files are needed; no new database server or paid dependency.

### GEN-02-S03 — Recheck availability and preserve rejected requests

**Objective:** Apply the availability decision table at the sealing boundary.  
**Requirements:** R10/R11; supporting R04/R15/R16.  
**Dependencies:** S01–S02, IDENTITY-02.  
**Owned modules:** proposed `generation/input_availability.py`, `input_service.py`; minimal admission/coordinator delegation to the service's authoritative decision.  
**Inputs → outputs:** accepted request plus fresh availability evidence → durable `AvailabilityCheck`, warning or classified preflight failure.

Tasks:

- Re-read current canonical/source-scope evidence in T1. Reuse IDENTITY-02 aggregation semantics, including missing linked-source evidence, and record the source of the authoritative decision. Do not run disappearance inference inside GEN-02.
- Enforce explicit override and retain unavailable state on overridden requests. Replace unsafe truthiness conversion at the narrow request adapter boundary; do not infer permission from candidate application status.
- Persist failed requests/receipts before returning `job_unavailable`; no context, claim or Running projection on rejection. Surface unknown/not_seen/override warnings in service results and inspection.
- Remove or delegate any admission shortcut that would bypass the authoritative recheck/receipt. Preserve candidate notes, application progress, assessment scores and approval state.

Acceptance: admission sees active, IDENTITY-02 records unavailable before T1, and preflight fails; all unavailable plus false fails; true proceeds with warning; one active source keeps the canonical active; partial/failed/search-only inventory absence never becomes GEN-02 closure evidence. Unknown proceeds visibly. A new candidate-approved override request leaves the failed predecessor unchanged.

Tests: proposed `test_availability.py`, `test_preflight_failures.py`, `test_override_provenance.py`; real IDENTITY-02 fixtures and generation admission integration. Configuration impact: reuse availability policy; record its fingerprints, do not introduce new miss/grace rules or an override default.

### GEN-02-S04 — Capture exact job, profile, options and recipe

**Objective:** Seal sufficient content to survive every later mutable edit.  
**Requirements:** R06/R10/R11; supporting R03/R15/R16.  
**Dependencies:** S01–S03, PROFILE-01, C06/C07 and CONTEXT-04 request contracts.  
**Owned modules:** proposed `generation/input_resolution.py`, `input_service.py`, `input_binding.py`, `input_settings.py`.  
**Inputs → outputs:** pending request, current approved inputs and configured recipe → complete verified seal.

Tasks:

- Select the canonical current revision and C06 whose source identity and recomputed material hash match it. Copy full C06 and identity metadata in T1. If only newer/different normalized content is available, fail `job_snapshot_mismatch`; never reconstruct an old description from current text or a revision title.
- Resolve exactly one configured candidate and its current approved C01 at acceptance. Snapshot approval and purpose-specific inclusion authorization, eligibility, fact/parent graph and mandatory IDs. Ambiguous/missing/unapproved profiles fail visibly.
- Resolve and snapshot language, document/purpose, template version/resource digest, override, model settings and complete recipe. Validate requirements against frozen job data, and use controlled instructions that treat job text as data. Do not call drafting models.
- Freeze policy version and immutable policy payload/ref when required by existing C13. Keep search preferences separate from candidate facts and do not rerun eligibility as an extra drafting gate.
- Verify redundant bodies/digests and request ownership on reopen. Never refresh current profile/job/template/configuration on an already sealed request, including one still Pending before claim.

Acceptance: after sealing J1/P1/options A, change description, canonical membership, profile facts/permissions, policy, template and config to newer versions. Reopen still yields J1/P1/A with original approval, precision dates and eligible facts. A different request may select newer versions. Missing/corrupt sealed content is an error, not a replacement.

Tests: proposed `test_snapshot_binding.py`, `test_freeze_once.py`, `test_profile_authorization.py`, `test_recipe_freeze.py`; include mutation of returned nested objects and two concurrent seal callers. Configuration impact: validate candidate/recipe/template selections and materialize effective settings in the seal; values cannot be invented from missing prerequisites.

### GEN-02-S05 — Pin and authorize the exact RAG generation

**Objective:** Resume RAG from the same authorized evidence universe after profile/index changes.  
**Requirements:** R06/R11; supporting R09/R15/R16.  
**Dependencies:** S02/S04, CONTEXT-03 reader/pins through CONTEXT-04.  
**Owned modules:** proposed `generation/input_indexes.py`; targeted index repository/reader extension only if a request-bound wrapper cannot enforce the contract.  
**Inputs → outputs:** sealed candidate/profile/purpose and RAG recipe → exact verified generation binding and durable request-owned pin.

Tasks:

- Resolve the compatible generation during preparation and validate again in T1 before pinning. Bind candidate ID, purpose, profile version and snapshot fingerprint, chunk manifest, index manifest/file hashes, settings, embedding model/digest/dimension/normalization/prefixes and generation ID.
- Implement a frozen reader adapter enforcing those bindings and an unreleased pin owned by this request/seal. Another request's pin is not authorization. Verify returned handle metadata even if the generic reader accepted the request.
- Use explicit `authorization_mode="frozen_use"` and `frozen_generation_id` on later selection. Prohibit active-pointer resolution, current profile facts, and automatic index rebuilds after sealing.
- Keep cleanup from racing validation/pinning; verify original chunks and C08 references against the frozen snapshot. Close handles on success and error. Missing or corrupt pinned files and incompatible query embeddings fail visibly.

Acceptance: freeze on P1/index I1; publish P2 and activate I2, with fact text changed under the same fact ID. Old request still reads I1 and P1 only. Wrong candidate, cover-letter index used for CV, mismatched snapshot, other-request pin and missing files are rejected. JSON never opens an index. An unconfigured semantic provider cannot silently pass a required hybrid RAG recipe as keyword-only success.

Tests: proposed `test_frozen_rag.py`, `test_pin_authorization.py`, `test_index_cleanup_race.py`; real index builder/store with deterministic fake embeddings, plus spies that fail on latest-profile or active-index reads during resume. Configuration impact: freeze existing chunk/index/retrieval/embedding settings; no new vector database or tuning project.

### GEN-02-S06 — Assemble, persist and reopen exact context results

**Objective:** Produce both context strategies from sealed inputs and retain the measured prompt.  
**Requirements:** R06/R11; supporting R12/R15/R16.  
**Dependencies:** S04/S05, CONTEXT-04 selector and budget contracts.  
**Owned modules:** proposed `generation/input_context.py`, adapter in `input_service.py`; minimal receipt-reference wiring in the existing coordinator.  
**Inputs → outputs:** valid seal and operation ID → persisted `ContextSelectionResult`, C09 adapter result or inspectable context error.

Tasks:

- Reopen the trusted stored manifest rather than trusting caller-mutated objects. Construct `ContextSelectionRequest` entirely from frozen C01/C06/recipe and request-bound reader. Use a job binding validator that verifies frozen revision UUID/material hash/source membership, without comparing material hash to raw hash.
- Reuse `ProfileContextPreparer` and existing builders with the frozen rule/renderer/counter versions. Reject unavailable implementations of a pinned version rather than quietly using current code/defaults with an old label.
- JSON includes all purpose-eligible facts and mandatory context; overflow returns `context_budget` without truncation or RAG substitution. RAG preserves mandatory eligibility/chronology/parents and retrieval-vs-evidence-gap semantics. Do not synthesize candidate facts from requirements.
- Persist full selection result, rendered prompt, selected/retrieved IDs, budget measurement/exactness, trace and construction fingerprint in T3. Merge preflight warnings into C09 and safe inspection output; if warnings are included in prompt content, include them before measurement.
- Reopen the saved result on repeated `build_context`, even when coordinator supplies a different timestamp-based operation ID. Persist errors with retry metadata and original seal. A successful result is never replaced by an unrecorded recomputation.
- Supply an additive result accessor/reference for GEN-03 and correct the context checkpoint to identify the durable context receipt/hash, rather than only the canonical job ID. No drafting implementation belongs here.

Acceptance: both JSON and RAG produce purpose-correct context for CV and cover letter from the same P1 snapshot. Mandatory-only overflow fails in either strategy. Saved context/prompt bytes and IDs remain identical after restart or defaults/model tags change, with zero selector/model calls during replay. A first unsaved build with a missing pinned model/recipe errors visibly; it does not substitute a newer model or profile.

Tests: proposed `test_json_context.py`, `test_rag_context.py`, `test_context_receipts.py`, `test_no_mutable_reads.py`, `test_warning_visibility.py`; budget, permission, hostile-job-text and fake GEN-03 consumer cases. Configuration impact: existing context/retrieval settings are read at sealing only; ordinary retry timeouts may remain operational settings but cannot change semantic inputs.

### GEN-02-S07 — Verify standalone recovery, consumer integration and handoff

**Objective:** Demonstrate component acceptance with real local persistence and controlled external fakes.  
**Requirements:** R06/R10/R11; supporting R12/R14/R15/R16.  
**Dependencies:** S01–S06; current GEN-01 consumer and OPS inventory integration.  
**Owned modules:** focused tests/fixtures, minimal existing inspection/composition wiring, and `docs/components/GEN-02.md`.  
**Inputs → outputs:** synthetic lifecycle/crash scenarios → reproducible evidence and a precise consumer handoff.

Tasks:

- Exercise standalone prepare/reopen/context/inspection without constructing GEN-01 or Salesforce. Verify rejected preflight remains inspectable without a worker and Pending successful seals resume unchanged.
- Wire the real input service into GEN-01's existing port and verify claim ordering with a fake projector. Keep absent GEN-03–06 visibly blocked; do not fill them with production fakes.
- Expose persisted warnings and failures through `generation show` using a small read-only adapter; no new tracking UI. Remote warning presentation/mapping remains SF-05/07 integration work and must be recorded as pending if unavailable.
- Run the crash matrix below with subprocess termination and database reopen, backup/restore of referenced inputs, and cleanup protection. Verify private facts, signed URL secrets and prompts do not leak through diagnostics.
- Publish the handoff with exact APIs, schemas/migration, defaults, paths, test commands/results, native-Windows status, live dependencies, compatibility changes and follow-up owners.

Acceptance: all component-level gates below pass; live availability refresh, local model runtime and Salesforce checks are reported separately and honestly. Completion of GEN-02 does not assert completed documents or G4 delivery.

Tests: proposed `test_standalone_service.py`, `test_worker_adapter.py`, `test_crash_matrix.py`, `test_windows_paths.py`, `test_windows_restart.py`, `test_backup_restore.py`, `test_safe_diagnostics.py`. Configuration impact: non-secret example input settings and documentation only; no credentials, runtime download, Salesforce deployment or added mandatory dependency.

## Required verification matrix

| Scenario | Observable result |
|---|---|
| Failure before/within T1 | T0 request/attempt remains; no partial seal/pin. Handled preflight rejection commits failed receipt/C13 together. |
| Crash after seal, before T2 | Pending C13 reopens the identical seal, without newer profile/job/config reads. |
| Failure during T2 / crash before remote Running | No partial claim/association/checkpoint/intent. Once committed, fake remote sees Running only after durable snapshot verification succeeds. |
| Crash after preflight failure, before Failed projection | Failure and choice evidence remain inspectable; worker recovery creates/reuses Failed intent; no Running transition. |
| Concurrent seal/claim and profile/index activation | One consistent winning seal or bounded conflict; never a mixed profile/index, duplicated logical result or overwritten options. |
| Failure during context / after T3 before worker checkpoint | Failure retains seal; committed context is reopened and checkpoint can be repaired without selector/model execution. |
| Confirmed unavailable without/with explicit override | Exact `job_unavailable` failure / warning-bearing success; failed predecessor stays intact. |
| Unknown, not_seen, active alternate source | Visible correct warnings/continued processing; no fabricated closure. |
| Publish P2, change same fact ID, retire I1, edit job/template/config | Both old JSON and RAG contexts use P1/J1/options A only; new requests can use P2. |
| Cross-request/candidate/purpose pin or tampered hash/path | Explicit integrity/authorization failure; no fallback to active/latest. |
| JSON full-set or mandatory-context overflow | `context_budget`, no partial bundle, no strategy switch. |
| RAG embedding service missing/incompatible | Classified visible failure; no silent semantic-channel omission for a hybrid recipe. |
| Backup/restore and cleanup | Exact seals, failed receipts, prompts and pins survive; referenced versions/files cannot be deleted. |
| Windows path with spaces/non-ASCII; external working directory | Pathlib/config-base resolution works, handles close, subprocess reopen succeeds. |

Use synthetic profile/job fixtures under proposed `tests/fixtures/generation/inputs/`, with P1/P2 corrections/removal/permission changes, J1/J2 descriptions, unavailable/unknown/multi-source states, CV/cover-letter permissions and JSON/RAG recipes. Use real repositories, real selector and real index reader/builder with deterministic embedding fakes. A fake input service cannot establish GEN-02 acceptance.

Proposed implementation-time PowerShell checks (not executed by this planning task):

```powershell
$gen02Repo = (Resolve-Path '.').Path
$gen02Python = Join-Path $gen02Repo '.venv\Scripts\python.exe'
& $gen02Python -m pytest (Join-Path $gen02Repo 'tests\generation\inputs')
& $gen02Python -m pytest (Join-Path $gen02Repo 'tests\generation') (Join-Path $gen02Repo 'tests\storage') (Join-Path $gen02Repo 'tests\contracts') (Join-Path $gen02Repo 'tests\profile') (Join-Path $gen02Repo 'tests\identity\availability') (Join-Path $gen02Repo 'tests\context') (Join-Path $gen02Repo 'tests\operations')
$gen02Temp = Join-Path $env:TEMP ('GEN-02 Prüfung ä ' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $gen02Temp | Out-Null
Push-Location -LiteralPath $gen02Temp
try {
    & $gen02Python -m pytest (Join-Path $gen02Repo 'tests\generation\inputs\test_windows_paths.py') (Join-Path $gen02Repo 'tests\generation\inputs\test_windows_restart.py') --basetemp (Join-Path $gen02Temp 'Daten Größe')
} finally {
    Pop-Location
}
```

Record exit codes/results and actual environment. Run additional affected configuration/CLI/schema-export checks when their files change, then the normal regression gate required by the implementation. Record live local embedding tests separately; do not infer native Windows or live integration success from fakes.

## Configuration and migration impact

| Area | Planned impact |
|---|---|
| Input service settings | Proposed `GenerationInputSettings` separate from worker polling/retry settings, with an explicit application-config reference and non-secret example file. Validate candidate selection, supported languages/types, template/recipe catalog references and storage limits. No production prompt/model/template is invented if missing. |
| Context and model settings | Reuse `ContextSettings`, `RetrievalSettings`, index/embedding configuration and local model provider settings. Existing example context limits (8192/512/64) are engineering defaults, not a measured drafting guarantee. Resolve effective values and freeze them; changes affect only new seals. Secrets and authentication settings never enter snapshot hashes/prompts. |
| Availability settings | Reuse `availability_policy_ref`; keep existing miss/grace semantics. No new global override or implicit source network fetch. Record check time and evidence age without inventing a closure-age threshold. |
| Storage | New forward migration after current head 010; preserve existing C13/GEN-01 rows. Add insert-only payloads/receipts and explicit retention relationships. Validate migration rollback/idempotency and old-row audit access. Never backfill unknown historical inputs using current data. |
| File paths | Runtime data outside tracked source, rooted in explicit configuration using `pathlib.Path`. Resolve relative refs against their configured base, verify root containment and digests, and preserve proper Windows JSON escaping. No hardcoded CWD or POSIX path assumptions. |
| Retention/backup | Register seal/profile/job/recipe/context resources and request-owned index pins. Protect failed requests and prepared seals, not just active generation states. Cleanup/release requires verified lack of references; restore verifies hashes/bindings before resumption. |
| External services | No new network service, hosted retrieval, paid dependency or remote mutation in GEN-02. Local query embeddings are only needed for first RAG construction; JSON and reopening saved results require none. Salesforce warning display and real prompt/template availability are explicit integration gates. |

## Implementation handoff checklist

- [ ] Record GEN-02 status and direct R06/R10/R11 acceptance; distinguish implemented from verified.
- [ ] List actual owned/changed files, migration number, companion/schema versions and legacy compatibility behavior.
- [ ] Publish prepare/reopen/build/inspect signatures and the complete-context accessor for GEN-03.
- [ ] Document availability evidence source, strict override provenance, warning codes and exact `job_unavailable` error example.
- [ ] Prove atomic preflight failure, snapshot/pin sealing and claim-before-Running ordering with fault injection.
- [ ] Prove JSON/RAG never consult newer mutable profile facts, current indexes or default settings after sealing.
- [ ] Record immutable job binding, raw-versus-material hash handling, permission-at-freeze policy and request-owned pin enforcement.
- [ ] Provide persisted receipt examples, retry/reopen behavior, retention/backup dependencies and storage-failure limits.
- [ ] Record meaningful automated, fake-integration, native-Windows and live-service checks separately; pending services remain pending.
- [ ] Hand GEN-01 the real input adapter and durable receipt references; hand GEN-03/04 exact snapshots, measured prompt and evidence-resolution rules. Rendering, delivery, Salesforce UI and Phase 2 remain with their owning components.
