# GEN-06 — Artifact delivery and review integration implementation stories

Status: **PLANNED — documentation only; implementation and verification pending**  
Date: 31 October 2026  
Component: **GEN-06 only**, Phase 1  
Direct requirements: **R12, R16**; supporting constraints: R09, R11, R14, R15  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), C13/C14, §§5–10, gate G4  
Repository instructions: [README.md](../../README.md) and blueprint §§8–9. No applicable `AGENTS.md` was found in the repository or checked ancestor directories.

## Objective and ownership

Deliver already saved, validated DOCX/PDF artifacts to the existing Salesforce org, preserve exact local-to-remote version mappings, and expose accurate request progress and review/regeneration links. Recover interrupted delivery without redrafting, rendering again, or blindly repeating a potentially successful upload.

GEN-06 owns the local delivery ledger, Files adapter, reconciliation, remote acknowledgments, accessibility evidence and the delivery/review payload handed to GEN-01. Minimal changes to shared contracts, storage, worker wiring and operations are in scope where necessary for these guarantees. GEN-01 remains the single ordered writer of request processing-state projections. SF-07 owns Salesforce file visibility/linking permissions, review UI, human approval actions and regeneration access. SF-08 owns notification types, Flows, recipients, channels and notification deduplication. GEN-06 supplies durable state/version/transition references; it sends no notifications.

No rendering, factual rewriting, new request-action implementation, authorization setup, Salesforce metadata deployment, automatic approval, automatic application submission, scheduling or Phase 2 work belongs here. A draft must be delivered to the candidate for review before it can be approved. Human approval is required before use, not before delivery into the candidate's review interface.

The story decomposition, companion-record names, default upload encoding and remote document grouping below are proposed engineering choices. The user's explicit requirements—persist the marker before upload, reconcile uncertain results before resend, retain artifacts and `upload_pending` on quota failure, and require accessible delivery before readiness—are mandatory.

## Repository evidence and dependencies

Source paths abbreviated as `generation/`, `salesforce/`, `contracts/`, `storage/` and `operations/` are beneath `src/job_automation/`.

| Dependency / evidence read | Current state and consequence |
|---|---|
| **GEN-05**, direct prerequisite | [GEN-05 stories](GEN-05.md) exist; `docs/components/GEN-05.md` and a concrete renderer are absent. The proposed `RenderedArtifactReceipt`, `ArtifactSet`, trusted reopen service, review package and immutable version reservation are **planned contracts**, not available production guarantees. Freeze final interface names against the eventual handoff. Use explicit saved-artifact fixtures meanwhile; do not implement GEN-05 here. |
| **SFCLIENT-01**, direct prerequisite | [Gateway handoff](../components/SFCLIENT-01.md) records offline/fake/native-Windows checks, with live acceptance pending SF-02. `SalesforceGatewayV2` offers typed reads, queries, upsert and update, but no Files create, link-create or binary-download operation. Add a narrow Files capability reusing authentication, approved origins, error classification and budgets; never pretend record upsert makes Files creation idempotent. |
| **SF-07**, direct prerequisite | No story or component handoff and no `salesforce/` metadata directory were found. Read the blueprint SF-07 catalog entry as the ownership baseline. Actual marker fields, result/version fields, sharing policy, candidate identity, access verification and review routes remain a named integration dependency. Proposed API names are not deployed metadata. |
| **SF-08**, live notification dependency | No story/component handoff was found. The blueprint assigns readiness/failure notifications to SF-08. Define its input transition contract and fake observer tests here; keep live notification acceptance pending its handoff. Do not create notification Flows or a local notification service. |
| **GEN-01**, coordinator/projection | [Worker handoff](../components/GEN-01.md), `ports.py`, `records.py`, `coordinator.py`, `projection.py`, `recovery.py`, `request_mapping.py` provide delivery slots and durable projection intents. Current delivery trusts a nonempty `remote_file_id`, does not call `reconcile_delivery`, and marks ready without access proof. Completed checkpoints bypass delivery checks. The ready projection contains only status, omitting result and operation-marker fields. Fix these narrowly through a versioned adapter. |
| Projection ordering gap | `projection.py:reconcile_intent` acknowledges either marker match or status match without verifying result/version payload. `generation_work.py:save_projection_intent` can replace a revision's payload on conflict; the coordinator uses fixed revision numbers. Delivery projections need immutable payloads, monotonic revisions and complete readback. A stale Upload pending retry must never overwrite a later Ready result. |
| Existing C13/C14 and persistence | `GenerationRequest` 1.0 carries predecessor request and local result references. `Artifact` 1.0 has hash, path, integer version, nullable marker and an ambiguous `remote_file_id` described as either ContentVersion or ContentDocument. `ArtifactDeliveryRecord` 1.0 lacks typed version/access proof. Migration 010 enforces one active slot per `(request_id, artifact_format)`; it is not immutable delivery history. Preserve legacy readers and introduce typed companion mappings. |
| **GEN-04**, validation/review prerequisite | [GEN-04 handoff](../components/GEN-04.md) and `validation_records.py` now exist. This supersedes the older GEN-05 story's statement that GEN-04 is absent. `DocumentValidationReport` and `ValidatedDraftForRendering` 1.0 bind C14 `DraftDocumentV2` 2.0, report hashes and review warnings. Reopen through the trusted service; preserve every warning and the report's semantic-limits notice. The handoff's broad approval-before-delivery wording must not block candidate review delivery: the blueprint and current user instruction keep delivery and human approval separate. |
| **DATA-01 / OPS-01** | [Storage](../components/DATA-01.md) and [operations](../components/OPS-01.md) handoffs plus current repositories/inventory/relocation code provide the foundation. Current migration head is **013 (`013_document_validation`)**, superseding GEN-05's earlier head-012 observation. Reinspect after GEN-05 implementation and append migrations. Protect pending delivery artifacts, markers and references through retention, backup and restore. |
| **GEN-02/03, RUN-01**, supporting | Consume frozen format/options and content/report provenance; do not refreeze inputs on delivery retry. Reuse the single search/generation worker lock and existing retry policy. `GenerationRetryPolicy` settings and attempt tables exist, but current delivery code does not enforce a durable delivery retry budget. |
| **SF-00/02/04/05/06**, live prerequisites | Actual org identity/capacity, authorization, request metadata/actions and approved mappings must come from their owners. SFCLIENT-01 records missing SF-02 evidence. Defaults such as `Generation_Request__c` and the example org ID are not evidence of live configuration. Do not inspect secrets or invent org capabilities to fill these gaps. |

## Contracts to establish before delivery logic

Use strict versioned records, UTC event timestamps, UUID local identities, canonical Salesforce IDs scoped by org, exact-byte SHA-256 hashes and exported synthetic schema fixtures. Schema names below are proposals. Every delivery input is detached from mutable configuration once its intent is committed.

| Contract / boundary | Required logical contents and invariants |
|---|---|
| GEN-05 saved-set input | Request/set/version IDs; frozen required formats; exact artifact UUIDs, format, managed local path, positive size and hash; receipt/set hashes; draft, render and validation bindings; durable review-package reference. Reopen files and trusted upstream bindings before dispatch. Bare Artifact metadata, an arbitrary path or a Boolean checkpoint cannot authorize upload. |
| `DeliveryIntent` 1.0 | Delivery UUID; expected org and Salesforce request/job mappings; request/set/artifact/version/format; byte hash/size; immutable reconciliation marker; marker/mapping/policy versions; exact initial-create metadata fingerprint; intended record links and sharing policy; review refs; created time. Unique logical key `(org_id, request_id, artifact_id, artifact_version)` and unique `(org_id, marker)`. Existing GEN-05 marker is reused, never replaced during retry. |
| `DeliveryAttempt` 1.0 | Stable intent reference, physical attempt ID/sequence, operation kind (upload/query/link/access), persisted phase, start/end, classified error, remote outcome, next retry time, remaining budget and bounded reconciliation evidence. Suggested phases: prepared, sending, uncertain, uploaded, linking, checking_access, delivered, blocked. These are internal phases, not new C13 states. |
| `RemoteArtifactMapping` 1.0 | Org/request/artifact/version/format/hash binding; separate `content_document_id`, `content_version_id`, provider version label where available, link IDs/target record IDs, marker and upload acknowledgment time. Never equate local artifact version with Salesforce's version label. A local path is never a remote review URL. |
| `AccessibilityReceipt` 1.0 | Exact mapping/version, candidate principal or SF-07-approved access-policy evidence, request/review route, required record links, verification method/version, observed time, successful metadata/content checks and byte identity evidence. Integration-user access alone does not prove candidate access when identities differ. Missing/unknown access is not success. |
| `DeliverySetReceipt` 1.0 | Verified saved-set hash, each required member's mapping/access receipt, candidate-accessible review information, completeness and stable receipt hash. All advertised formats and review requirements must be accessible. No hidden DOCX-only downgrade when PDF was required. |
| `ReviewProjection` 1.0 | Request/local set/version identity; exact remote version references and approved UI routes; safe progress counts/reason codes; warning records and semantic-limits notice; predecessor request/version references; mapping version and payload fingerprint. Carries no approval mutation. Do not send raw profile evidence, full prompts or private local paths. |
| Readiness/projection intent | C13 state plus monotonic projection revision, stable operation/transition marker, immutable complete payload, delivery-set receipt ref/hash and desired-state fingerprint. Readiness identity is bound to the delivered set and request, not wall-clock retry time. GEN-01 persists/dispatches it through one ordered path. SF-08 consumes its agreed remote representation. |
| Versioned delivery port | Proposed `deliver_or_reconcile(saved_set_ref)` and `reopen_delivery(delivery_intent_id)` return a complete receipt or typed pending/blocked/failure result. Reconciliation keys include artifact/version, not only request/format. Inject a typed Files gateway directly; remove dependence on `self.projector.gateway` and permissive legacy `RendererDelivery.deliver` fallback for production delivery. |

Keep C13 1.0, C14 Artifact 1.0 and legacy receipts readable. A new companion mapping is authoritative for separate remote IDs. For new writes, define the compatibility `remote_file_id` as the ContentVersion ID and update its documentation/adapters explicitly; never reinterpret unknown legacy IDs without remote verification. Preserve old approval fields and original payloads. Any incompatible shared-contract change requires a version, schema/fixture updates, consumer migration and recorded blueprint decision during implementation.

## Salesforce delivery and identity decisions

Salesforce separates the file entity (`ContentDocument`) from individual revisions (`ContentVersion`). A new revision of an existing file targets its ContentDocument; `FirstPublishLocationId` is for the initial version only. This plan uses exact version IDs for review and approval binding. [Salesforce Files/version guidance](https://help.salesforce.com/s/articleView?id=000385651&language=en_US&type=1)

Proposed first-release policy: create a separate ContentDocument for each immutable local artifact/version; DOCX and PDF are distinct files joined by the local artifact-set identity and request. Deliberate regeneration creates new request/artifact identities and separate files with predecessor links. This avoids changing the bytes behind an already reviewed request. Do not append to an unrelated or predecessor document by filename. A later append-version policy needs an explicit compatibility decision; the typed mapping already distinguishes document from version.

Proposed upload encoding is bounded JSON/base64 for these small documents, with a configurable local byte ceiling and encoded-request ceiling below the endpoint's supported limits. Salesforce also supports multipart blob upload; no large-file uploader is required for this component. Verify the configured API version, encoding and actual org capacity during implementation instead of treating documented endpoint maxima as available org storage. [Salesforce blob upload reference](https://developer.salesforce.com/docs/platform/api-rest/guide/dome-sobject-insert-update-blob.html)

The gateway must support only the needed typed operations: create one ContentVersion with bytes and marker metadata; read exact version/document metadata; query exact markers with bounded pagination; read/check/create the specific ContentDocumentLink relationships required by SF-07; and retrieve bounded exact-version bytes for integrity verification when needed. Reuse SFCLIENT-01's session, TLS/origin controls, safe diagnostics and operation budgets. No generic raw-HTTP escape hatch, file-upsert replay flag, public distribution link or expanded permission grant.

### Persist-before-send and reconcile-before-resend protocol

1. Acquire the existing worker lock and reopen the complete GEN-05 saved set and GEN-04 review authorization. Verify contained native paths, exact byte hashes/sizes and request bindings. Loading delivery must not require the renderer/model to be installed. Freeze the file bytes used by the actual send, or stream with an equivalent verified immutable-file guarantee; prevent a hash-check/send race.
2. In a single SQLite transaction, commit the intent, request/artifact/version marker, target mapping, exact payload fingerprint, pending artifact/slot state and attempt eligibility **before any upload**. If marker or intent persistence fails, send zero requests. GEN-05 may have already assigned a marker; bind and preserve it. A proposed marker is `gen06:v1:<request_uuid>:<artifact_uuid>:<artifact_version>`, scoped by the persisted org ID; it contains no candidate text or paths. Validate actual remote field length before dispatch.
3. Require SF-07's contract to provide an exact-queryable ContentVersion marker field (and request/artifact/hash metadata as agreed) writable **in the same create operation as the bytes**. Field names and permissions are not assumed. A later metadata PATCH or a local-only marker leaves an unsafe crash window and is unacceptable. If this capability is absent, block before upload and report the dependency. A queryable marker is not itself a server-enforced idempotency guarantee.
4. Commit `sending` and attempt accounting before the physical call; perform network work outside SQLite write transactions. Pass immutable identity and remaining budget to the Files gateway. Initial upload may include the approved first-publish request target; still verify the actual link afterward. Persist returned ContentVersion ID immediately; resolve and persist ContentDocument ID without creating another file if that read fails.
5. A timeout after send, connection loss after transmission, malformed/missing acknowledgment, uncertain 5xx, or a process restart with `sending` is an **unknown outcome**. Persist `uncertain` and reconcile before any new POST. First read a known returned ID; otherwise query by the exact marker in the expected org, covering all versions and the configured query scope. Never search only linked files: upload may have succeeded before linking. Do not match by title, filename, latest version, hash alone or timestamp alone.
6. Reconciliation returns one of: **one exact match**, **proven absent**, **inconclusive**, or **conflict**. An exact match must bind request/artifact/version/format/size and byte identity; verify SHA-256 by bounded download when remote checksum semantics do not establish the same hash. A custom hash field alone describes a claim about bytes. Adopt the IDs and continue linking/access checks without upload. Wrong bindings or multiple matches block with conflict evidence; do not pick the newest or delete duplicates automatically.
7. Empty first page, truncated pagination, denied query, missing permissions, delayed visibility or failed lookup is not proof of absence. Persist read progress/evidence and recheck with bounded backoff. Resend only after a complete lookup **and** a documented SF-07/API visibility or server-enforced uniqueness guarantee establish absence, or an explicit audited recovery decision resolves uncertainty. No elapsed-time-only inference. If absence cannot be established, remain `upload_pending` with `reconciliation_inconclusive`; do not trade correctness for automatic progress. A definitely not-sent or definitely rejected create may retry under the classified policy using the same intent/marker/bytes.
8. Reconcile links separately by `(content_document_id, linked_entity_id)` and approved sharing values. A lost link-create response requires readback before repeating it. Uploaded bytes with a missing/denied link remain pending; retry only the unfinished link/access step. No new ContentVersion is needed to repair visibility. SF-07 defines whether request-only or request-plus-job linking is required.
9. Commit authoritative mappings, access receipts, delivery status and per-format progress together. When the complete required set and review information pass the access gate, atomically commit the set receipt, C13 readiness, delivery checkpoint and ordered Ready projection intent. Failure of this transaction leaves recoverable evidence; it must not leave a completed checkpoint without a queued projection. Remote acknowledgment is a separate durable fact.

This is recoverable at-least-once processing, not a claim of exactly-once network delivery. On restore, surviving remote effects may be newer than the backup: reconcile all pending/sending/uncertain intents before any mutation, even if the restored row says prepared. Bind restored data to the expected org; a different org requires explicit remapping, not reuse of old IDs.

### Progress, readiness, approval and regeneration

| Situation | C13 / candidate-visible result | Required behavior |
|---|---|---|
| Draft/render work ongoing | `running` / Running | GEN-01 retains ownership of upstream progress. GEN-06 does not invent percentage estimates. |
| Complete local set; upload, link, access or review information incomplete | `upload_pending` / Upload pending | Project completed-format counts, current delivery phase and safe actionable reason. Do not advertise inaccessible links as ready. Partial remote files may be shown explicitly as incomplete by SF-07. |
| Quota or API capacity failure | `upload_pending` | Retain every local artifact, receipt, marker and any successful remote mapping. Record the capacity/rate-limit distinction and remedy/retry eligibility; no auto-delete or paid fallback. |
| Required files, exact-version links and review information accessible | `ready_for_review` / Ready for review | Persist and project complete result/version/review references and stable transition marker. New artifact approval remains `draft`. |
| Invalid binding, corrupt/missing local bytes, ambiguous identity | Blocked delivery with safe reason; normally retain `upload_pending` for saved output | Require exact-byte restoration or explicit resolution/new request. Never rerender silently, inherit approval or advertise readiness. A deliberate terminal processing failure must be explicit, preserve artifacts and use GEN-01's failure projection. |
| Human approves a specific delivered version | Processing state remains distinct from approval | SF-07 records actor/time and exact version/hash binding. GEN-06 may mirror verified human approval history; it never manufactures approval or changes approved/superseded states as an upload side effect. |
| Candidate deliberately regenerates | New C13 request with predecessor | SF-06/07 create the request/action; GEN-01 admits/freezes it. GEN-06 exposes old/new request and exact artifact/version links without changing the predecessor's bytes, approval or request result. |

Readiness requires access as the candidate, not merely an HTTP 201, a nonempty file ID or a successful admin read. SF-07 must supply an implementable access-verification contract: the same authenticated candidate identity, or approved candidate-scoped evidence plus a validated sharing policy. If the integration identity differs and no adequate verification method is available, readiness remains blocked. Do not create an impersonation mechanism or grant broader access within GEN-06. Native/live acceptance includes opening the exact advertised files as the candidate.

Deliver review warnings and the semantic-limits notice through SF-07's private request/review surface before enabling human approval. Use a compact allowlisted review projection; preserve all obligations and claim/section references. If field limits require a separate review record/file, freeze that SF-07 contract first, apply the same durable delivery/reconciliation guarantees, and require it to be accessible. Never truncate warnings or upload the raw validation database/profile evidence as a shortcut.

Use approved request and version-specific review routes; never use a “latest file” shortcut as the approval target. Keep local C13 result/set references distinct from Salesforce UI references. Validate predecessor links against the same org and mapped job, reject self-links/cycles, and preserve unresolved predecessor evidence until repaired. Identical bytes in two deliberate requests still represent different review histories. A technical retry preserves request, artifact, marker and version identities.

The Ready projection must include the operation marker, revision/set binding, exact remote result/version references and review payload, with status published only after its dependencies exist. Prefer one atomic record update where SF-07's mapping permits it. If review data requires multiple records, commit/read back those first and publish Ready last. Reconciliation verifies the full intended payload; equal status alone is insufficient. Serialize revisions, discard/supersede stale unsent progress intents, and resolve an older in-flight intent before a newer update. Preserve candidate-owned approval, application progress, notes and follow-ups.

SF-08 receives the request identity, committed processing transition, stable readiness identity, exact result/review links and actionable failure reason through the agreed remote schema. Repeated upload/status reconciliation must not generate a new readiness identity. SF-08 decides when/how to notify and deduplicates once per readiness transition. Upload pending never becomes a draft-ready event. If access is later revoked/deleted, record the loss, preserve approval/history, suspend repair-time readiness claims and recover through SF-07's policy; no immediate replacement upload. Any renewed readiness is an explicit new transition agreed with SF-08, not an accidental replay.

## Implementation stories

All stories below are **PLANNED** and owned by GEN-06. Execute S01 → S02 → S03 → S04 → S05 → S06 → S07. New file names are proposed; inspect the actual GEN-05 contracts and migration head before implementation.

### GEN-06-S01 — Freeze delivery contracts and integration prerequisites

**Objective / requirements:** Establish exact identities, dependency gates and owner boundaries before remote side effects. R12/R16; supporting R11/R15.  
**Dependencies:** GEN-05, SFCLIENT-01, SF-07; GEN-01/04, FND-01; SF-08 for notification contract agreement.  
**Owned files:** proposed `generation/delivery_records.py`, `delivery_ports.py`, `delivery_settings.py`, `salesforce/file_records.py`; narrow port/schema export additions and fixtures.  
**Inputs → outputs:** saved-set/report contracts and owner mappings → versioned intent/mapping/access/set/projection contracts and explicit missing-prerequisite results.

Tasks:

- Finalize the contract table, marker grammar, immutable logical keys, exact-byte hash semantics and candidate-access evidence. Validate unsupported formats, incomplete sets, unknown orgs and invalid mappings before network work.
- Record SF-07's marker field, create/query permissions, query visibility guarantees, target records, sharing values, review/version routes, warning surface and approval ownership. Record SF-08's consumed transition fields without implementing its behavior.
- Specify the legacy compatibility reader and explicit new Files/delivery capability; production must reject old receipts without the required proof. Do not fabricate missing GEN-05 provenance or interpret a placeholder org as configured.
- Export schemas/fixtures and document proposed versus accepted technical choices. Keep imports/config validation free of credential/network side effects.

**Acceptance:** Synthetic valid contracts round-trip; cross-org/request/artifact mismatch, zero-byte input, duplicate members, incomplete required sets and an approval mutation in a delivery payload fail. Missing SF-07/GEN-05 capabilities block before upload. No request for notification configuration is added to the local Files adapter.

**Tests:** `tests/generation/delivery/test_contracts.py`, `test_compatibility.py`, `test_prerequisites.py`; affected schema/interface tests.  
**Configuration/migration impact:** Versioned non-secret delivery mapping/settings and schemas; no org metadata or database changes yet. Record downstream consumer changes before incompatible port migration.

### GEN-06-S02 — Persist upload intents, version mappings and recovery state

**Objective / requirements:** Make every file mutation recoverable from durable identity and preserve local artifacts. R12/R16; supporting R09/R14.  
**Dependencies:** S01, DATA-01, GEN-05, OPS-01; RUN-01 locking.  
**Owned files:** proposed `storage/repositories/artifact_deliveries.py`, `generation/delivery_store.py`; narrow migrations, engine, artifact/generation-work repositories and operations hooks.  
**Inputs → outputs:** verified saved set and target mapping → committed intent/marker, attempt ledger, protected dependency chain and detached reopen results.

Tasks:

- Append a forward migration after the actual head for immutable intents, attempts, typed remote mappings, link/access receipts and delivery sets. Enforce logical-key/marker uniqueness and referential integrity. Keep existing request/format slots as active pointers, with history separately keyed by artifact/version.
- Commit marker/pending states atomically before dispatch, and persist `sending`/attempt sequence before I/O. Use transaction-aware composite repository methods; existing methods that commit internally must not split compound operations.
- Atomically update both Artifact metadata/JSON and delivery records. Do not overwrite an active dispatched/uncertain slot with a newly rendered artifact. Conflicting hashes under the same intent are errors, not upserts.
- Register all pending files, review refs, marker history and mappings with inventory/backup/restore. Restore paths using `pathlib.Path` and existing relocation conventions without changing hashes/identities. Retain local files after delivery as governed by OPS-01, and always protect unfinished/quota-blocked artifacts.

**Acceptance:** The fake transport sees a committed marker before its first send. Marker-commit failure causes zero sends. A crash at each local commit boundary reopens the same IDs/version/bytes. Populated legacy data and human approvals survive migration; unsupported legacy mappings remain unresolved rather than guessed.

**Tests:** Real SQLite `test_delivery_store.py`, `test_migrations.py`, `test_marker_before_send.py`, `test_retention_restore.py`; process-restart fixtures and rollback injection.  
**Configuration/migration impact:** New forward migration(s), schema version records and managed receipt references; no modifications to applied migration checksums or runtime data in Git.

### GEN-06-S03 — Add bounded Salesforce Files operations

**Objective / requirements:** Upload exact saved bytes and obtain typed remote file/version/link evidence. R12/R16; supporting R14/R15.  
**Dependencies:** S01–S02, SFCLIENT-01; SF-07 capabilities and SF-02 access for live use.  
**Owned files:** proposed `salesforce/files_gateway.py`, `files_serialization.py`, `files_errors.py`; minimal shared gateway/transport/budget extension and contract fixtures.  
**Inputs → outputs:** committed intent and verified bytes → typed create/read/query/link/download result or `GatewayFailure`-compatible outcome.

Tasks:

- Implement the narrowly scoped operations described above. Include the marker in initial ContentVersion creation, safe UUID-based filename with correct extension, expected media type and approved publication target. Do not send a full Windows path in `PathOnClient` or personal text in titles/markers.
- Reuse protected credentials, configured API version, approved origin checks, bounded responses and one shared call budget. Add request/encoded-body/download limits appropriate for Files without globally relaxing unrelated gateway limits. Document memory bounds for the existing byte-buffer transport.
- Validate create acknowledgments and resolve document/version IDs explicitly. Never retry uncertain ContentVersion/link creation inside the gateway. Treat missing/malformed successful responses as unknown remote outcomes. A bounded auth renewal is permitted only for a definite authentication rejection under SFCLIENT-01 policy.
- Classify storage-limit errors as capacity, API quota/rate-limit errors separately, and permission/auth failures as repair conditions. Parse safe provider codes; no document bytes, base64, SOQL, raw provider errors or credential values in diagnostics.

**Acceptance:** Wire fixtures prove exact bytes and marker arrive together. A committed create followed by response loss is sent once and returns reconcile-required. Known version read failure cannot trigger another upload. Oversized files, disallowed routes and unsupported mappings fail before send.

**Tests:** `tests/salesforce/test_files_gateway.py`, `test_files_wire.py`, `test_files_limits.py`, `test_files_diagnostics.py`; shared gateway regression checks.  
**Configuration/migration impact:** Explicit Files capability/API mapping and finite byte ceilings; no new auth flow, permissions deployment, paid SDK or mandatory service.

### GEN-06-S04 — Reconcile uploads and resume only unfinished delivery steps

**Objective / requirements:** Recover ambiguous remote effects without duplicate files or lost progress. R12/R16; supporting R09.  
**Dependencies:** S01–S03, GEN-05 trusted reopen, SF-07 query/link contract.  
**Owned files:** proposed `generation/delivery_service.py`, `delivery_reconciliation.py`, `delivery_retry.py`, `delivery_adapter.py`; narrow recovery wiring.  
**Inputs → outputs:** pending/uncertain intent → adopted or newly acknowledged mapping, remaining link/access work, or explicit blocked result.

Tasks:

- Implement the complete persist/reconcile protocol, including restart interpretation of `sending`, unlinked-upload lookup, all-version marker matching, full pagination and exact byte verification.
- Persist the distinction among exact match, proven absent, inconclusive and conflicting results. Keep absence evidence and any audited manual resolution. Query timeout or zero accessible matches must never become unconditional create permission.
- Reconcile link mutations independently and retain the successful DOCX mapping if PDF fails. Never allocate a new artifact/version or invoke generation/rendering for delivery repair.
- Enforce persisted retry counts, next eligibility and shared deadlines across uploads, reads, links and projections. Reuse existing policy defaults (currently five stage attempts, 30-second initial and 900-second maximum backoff) as a starting point, explicitly defining delivery attempt units. Polling/restart must not reset budgets or multiply them by format. Quota blocks suspend automatic sends until eligible/remediated; budget exhaustion leaves visible `upload_pending` work for explicit retry, not a discard or infinite loop.
- Provide safe inspection/resume inputs through the existing manual worker boundary; no scheduler or generic “force resend” bypass. Recovery after an older backup always reconciles before mutation.

**Acceptance:** Commit-then-timeout produces one adopted remote version with zero second upload calls. Duplicate or mismatched markers block. Quota failure after one format succeeds preserves both local files and the first remote mapping; after remediation, only missing work resumes with the same identities.

**Tests:** Stateful fake-server `test_upload_reconciliation.py`, `test_link_reconciliation.py`, `test_partial_delivery.py`, `test_retry_budget.py`, `test_restore_reconciliation.py`; persisted/restarted crash matrix below.  
**Configuration/migration impact:** Durable retry/reconciliation fields and bounded query settings. No automatic remote/local cleanup or inferred visibility guarantee.

### GEN-06-S05 — Gate readiness and project complete request progress

**Objective / requirements:** Report Ready only for accessible delivered results and recover status updates without stale writes. R12/R16; supporting R11/R15.  
**Dependencies:** S01–S04, GEN-01, GEN-04/05 and SF-07; SF-08 transition contract only.  
**Owned files:** proposed `generation/delivery_access.py`, `delivery_projection.py`; narrow `coordinator.py`, `projection.py`, `recovery.py`, mapping and repository changes.  
**Inputs → outputs:** typed per-format receipts, review obligations and access evidence → complete delivery-set receipt and ordered progress/Ready projection.

Tasks:

- Implement candidate-access verification and complete-set checking using the frozen requested formats. Reopen old checkpoints/receipts before completion; mutable worker defaults cannot shrink the requested set.
- Publish safe Upload pending progress and actionable errors, then exact result/version/review refs with Ready only after all dependencies are accessible. Keep human approval fields out of every machine-owned payload.
- Atomically persist readiness, checkpoint and projection intent. Allocate immutable increasing revisions; persist operation marker in the actual remote payload. Reconcile status **and** marker **and** result/set/version/review fields. Prevent stale progress replay and conflicting same-revision replacement.
- Resume unacknowledged projections even when local C13 already says ready. Status-update loss must not re-upload files or manufacture another readiness transition. Failed progress projection leaves local pending work inspectable.
- Expose a stable transition identity for SF-08. Test with a passive observer only; local code does not send messages or own notification retry/deduplication.

**Acceptance:** Uploaded but inaccessible files remain `upload_pending`. The candidate can open every advertised exact version and the review information before Ready is published. An ambiguous Ready update is read back and acknowledged without repeated upload or new transition identity. Same status with a wrong result version is not an acknowledgment.

**Tests:** `test_accessibility_gate.py`, `test_ready_transaction.py`, `test_projection_reconciliation.py`, `test_projection_ordering.py`, `test_notification_boundary.py`; affected GEN-01 recovery tests.  
**Configuration/migration impact:** Versioned SF-07 field/status/route mapping and projection revision/payload preservation. Notification configuration and metadata remain SF-08-owned.

### GEN-06-S06 — Preserve review obligations and regeneration/version history

**Objective / requirements:** Make the delivered version and its review history unambiguous. R12/R16; supporting R11/R15.  
**Dependencies:** S01–S05, C13 predecessor contract, GEN-04/05, SF-07; SF-06 actions and GEN-01 admission remain external owners.  
**Owned files:** proposed `generation/delivery_review.py`, `delivery_lineage.py`; narrow mapping/projection and human-approval readback adapter if required by SF-07.  
**Inputs → outputs:** report warnings, exact version mappings and predecessor request → bounded review projection and verified lineage links.

Tasks:

- Carry all GEN-04 warning obligations and the semantic-limits notice to the candidate review surface. Bind review content to the delivered set/report hash and keep private source evidence local. If the agreed surface cannot hold the complete content, block completion until its alternate contract is available.
- Show request ID, artifact-set version, format and exact Salesforce version target; preserve prior request/artifact history and predecessor links. Validate unresolved/cross-org/cyclic mappings without guessing.
- Keep new output `draft`, even when predecessor bytes are identical or the predecessor was approved. A human approval applies only to the exact target/version and records authoritative actor/time evidence through SF-07. Readback may mirror it locally, without worker-generated approval/supersession.
- Verify retries and status projections do not overwrite candidate-owned approval, notes, application state or predecessor decisions. Regeneration access uses existing SF-06/07 actions; this component creates no new action or request workflow.

**Acceptance:** Request B deliberately regenerating approved request A has new IDs/markers and visible A/B links; A remains intact and B remains draft. A retry of B uses its original identities. Wrong-version approval cannot approve B. Missing review warnings/access prevents complete review readiness.

**Tests:** `test_review_projection.py`, `test_version_links.py`, `test_regeneration_lineage.py`, `test_approval_separation.py`; SF-07 adapter fixtures.  
**Configuration/migration impact:** Version-specific route/field mapping and lineage/approval observation references; no new document approval enum or automatic supersession policy.

### GEN-06-S07 — Verify recovery, native Windows and owner handoffs

**Objective / requirements:** Demonstrate delivery guarantees at their actual verification level. R12/R16; supporting R09/R11/R14/R15.  
**Dependencies:** S01–S06; real GEN-05 and SF-07 for full delivery acceptance; SF-02/live org access and SF-08 for live notification integration.  
**Owned files:** `tests/generation/delivery/`, synthetic fixtures, proposed `tests/manual/gen06_delivery_smoke.py`, non-secret example settings, future `docs/components/GEN-06.md`.  
**Inputs → outputs:** stateful fault fixtures and scoped native/live checks → recorded evidence, operating/recovery instructions and dependency handoff.

Tasks:

- Run the matrix below with actual SQLite and a remote fake whose committed files survive local worker termination. Assert byte hashes, identities, POST counts, mapping counts, request/projection state and unchanged approval—not just returned success flags.
- Exercise the real upstream reopen path once GEN-05 exists; until then label saved-set fixtures as fakes. Use renderer/model spies asserting zero calls during every delivery retry.
- Run native Windows subprocess restarts, lock contention and data-root/restore paths with spaces and non-ASCII text. Confirm config and file resolution from a different working directory. Do not claim native support from mocked paths alone.
- Make live smoke read-only by default. Only under separate explicit authorization use a named synthetic request/file set in the verified existing org, within a finite call/storage budget. Confirm marker query capability, exact upload/readback, required links and candidate opening of every advertised version/review surface. No quota exhaustion, duplicate creation, permission changes or destructive cleanup to simulate failures; inject those offline. Agree fixture disposition and record only safe references.
- Coordinate SF-07's candidate-review/approval evidence and SF-08's once-per-transition readiness and actionable-failure notification checks. If their handoffs are absent, mark those gates pending. No fake observer test establishes live notification behavior.

**Acceptance:** Each required case has passed/pending/failed evidence with reasons. Missing live prerequisites cannot produce a VERIFIED live/G4 claim. Record implementation status separately from unit/contract, fake transport, real storage, native Windows, real GEN-05, live Files/candidate access and live SF-08 verification.

**Tests:** Component suite, affected generation/Salesforce/contracts/storage/operations tests and bounded native/live smoke.  
**Configuration/migration impact:** Tested versions, recovery instructions and final schema/mapping/migration versions in the handoff; no live changes authorized by this planning document.

## Required recovery and acceptance matrix

| Failure injection / example | Observable result |
|---|---|
| Crash before marker commit; SQLite write failure | No upload. Saved artifacts remain unchanged. |
| Crash after prepared intent or after `sending`, before acknowledgment | Restart reopens the same intent/marker and reconciles any possible remote side effect before resend. |
| Remote ContentVersion committed, response lost or malformed | Exact marker lookup finds/adopts one version; no second POST; returned IDs eventually persist. |
| Returned version ID saved, document-ID lookup fails | Resume lookup by known version; no new file. |
| Upload committed before linking; query only on request would be empty | Search by version marker independently of record links; adopt and repair link. |
| Marker query first page empty, next page fails, permissions denied, visibility delayed | Inconclusive, `upload_pending`, no create. Persist reason and bounded retry eligibility. |
| Complete query proves absence under verified capability | Retry same bytes/marker under remaining budget; retain the proof and attempt audit. |
| Zero matches without an absence guarantee | Bounded recheck then actionable blocked uncertainty; no blind resend. |
| Two matches; wrong request/version/hash; matching metadata but altered remote bytes | Conflict, no adoption/ready/automatic deletion or new upload. |
| Link create committed, response lost | Read exact document/target relationship and adopt; no duplicate link or file. |
| Upload succeeds; link/access denied or review information inaccessible | Mapping retained, `upload_pending`; repair only remaining work. Admin access alone cannot set Ready. |
| DOCX delivered; PDF hits storage quota or API quota | Both local files retained, DOCX mapping intact, `upload_pending`; distinct capacity/rate-limit reason and bounded retry. No Ready event. |
| Capacity restored; worker restarted | Same intent/version/hash; no duplicate DOCX, only unfinished PDF/link/access work. |
| Retry budget exhausted or Retry-After exceeds cycle budget | No tight loop or reset on restart; durable pending work and explicit next action. |
| Local file missing/tampered or report/set mismatch before resend | Integrity block, zero sends; exact-byte restore or deliberate new request required. |
| Crash after access receipts, before ready transaction; transaction rollback | Reuse evidence with required freshness recheck; atomically repair set/checkpoint/intent without upload. |
| Crash after local Ready commit, before remote projection | Recover queued projection even though request is locally ready; no lost remote completion. |
| Ready PATCH committed, response lost | Full marker/result/version/review readback acknowledges one transition. Same-state wrong-version readback is rejected. |
| Older Upload pending intent retries after Ready | Revision ordering suppresses stale mutation; candidate status and delivered result do not regress. |
| Required formats change in worker defaults after freezing | Original required set remains authoritative; partial set cannot become Ready. |
| Candidate approves A; deliberately regenerates B | A remains approved/intact; B has new identities, predecessor links and draft approval. Retry B does not create C. |
| External file edit/new remote version or access revocation | Exact original version remains the review target; wrong/new version cannot inherit approval. Missing access blocks repair-time readiness and is visible. |
| Restore old database into new Unicode data root with remote uploads still present | Markers/IDs/hash bindings survive; remote reconciliation precedes mutation; local paths relocate without changing identity. |
| Retention/backup during uncertain or quota-blocked delivery | All referenced artifacts/review data and reconciliation history remain protected and recoverable. |
| Concurrent search/generation or two delivery entry points | Existing worker lock excludes overlapping work; DB uniqueness is an additional guard, not a network exactly-once claim. |
| Sentinel credentials, candidate text or local paths in errors/responses | Public diagnostics and remote reason fields contain only approved safe codes/IDs/counts. |
| Repeated readiness/progress replay observed by SF-08 fake consumer | Stable transition identity, accessible links only, no local notification calls; live once-only notification remains SF-08 acceptance. |

## Configuration and migration impact

Proposed `DeliverySettings` references the existing Salesforce settings and a versioned SF-07 mapping. Include expected org, marker/hash/request field mappings, required link targets/sharing policy, approved review routes, candidate-access verification method, file and encoded-body/download byte ceilings, bounded query pages/candidates, access-evidence freshness and delivery retry/reconciliation limits. Define whether each setting is frozen in the intent or operationally adjustable; changing org/marker identity/payload is not a retry. Required formats come from the sealed request/set, never mutable defaults. No credentials, candidate text, notification recipients, automatic approval or unsafe reconciliation bypass switches belong in example settings.

Reuse the current Python/native Windows stack and gateway transport unless a measured requirement demands a narrowly justified dependency. No mandatory hosted service, paid library, WSL, Docker or browser automation for production delivery. Secrets remain in SFCLIENT-01's protected store. Store runtime databases/artifacts outside source control. Use `pathlib.Path`, explicit config/data bases, JSON-escaped Windows paths and quoted PowerShell commands; Markdown links use `/`.

Migration must preserve C13/C14 legacy payloads, immutable GEN-05 history, human approval and active delivery pointers. Verify upgrade from populated migration 013 and the actual later GEN-05 head, repeated application, checksum preservation and rollback on injected failure. Do not backfill fake access proofs or declare legacy `delivered` rows verified merely because an ID is present. Keep unresolved legacy rows inspectable and reconcile before reuse. Add retention/backup/relocation consumers in the same implementation, with no automatic remote deletion to free quota.

The following are **planned implementation checks**, not tests executed during story planning. Proposed paths will exist only after implementation:

```powershell
$gen06Repo = (Resolve-Path '.').Path
$gen06Python = Join-Path $gen06Repo '.venv\Scripts\python.exe'
& $gen06Python -m pytest (Join-Path $gen06Repo 'tests\generation\delivery') (Join-Path $gen06Repo 'tests\salesforce')
if ($LASTEXITCODE -ne 0) { throw 'GEN-06 component checks failed' }
& $gen06Python -m pytest (Join-Path $gen06Repo 'tests\generation') (Join-Path $gen06Repo 'tests\contracts') (Join-Path $gen06Repo 'tests\storage') (Join-Path $gen06Repo 'tests\operations')
if ($LASTEXITCODE -ne 0) { throw 'Affected integration checks failed' }
$gen06Temp = Join-Path $env:TEMP ('GEN-06 Prüfung ä ' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $gen06Temp | Out-Null
Push-Location -LiteralPath $gen06Temp
try {
    & $gen06Python -m pytest (Join-Path $gen06Repo 'tests\generation\delivery\test_windows_restart.py') --basetemp (Join-Path $gen06Temp 'Daten Größe')
    if ($LASTEXITCODE -ne 0) { throw 'Native delivery restart checks failed' }
} finally {
    Pop-Location
}
```

S07 records the actual read-only/live smoke syntax after implementation and its explicitly authorized synthetic fixture scope. Never pass tokens on the command line. Native Windows and live Salesforce checks are separate; Phase 2 logged-out startup is deferred.

## Implementation handoff checklist

- [ ] State GEN-06 status, R12/R16 acceptance and actual prerequisite gaps; distinguish proposed GEN-05 contracts and absent SF-07/08 handoffs from implemented code.
- [ ] Record final files, schema/port versions, migration numbers, configuration fields and legacy compatibility behavior.
- [ ] Document marker persistence before initial upload, marker placement in the same remote create, remote query/visibility guarantees, absence/conflict handling and recovery limitations.
- [ ] Record exact local artifact/set/version to ContentDocument/ContentVersion/link mappings and candidate-access evidence, without real document content or secrets.
- [ ] Demonstrate quota retention, persisted retry budgets, partial-format recovery, restore reconciliation and zero renderer/model calls during delivery recovery.
- [ ] Demonstrate complete-set/access/review gating, atomic Ready intent creation, full-payload readback and stale-projection prevention.
- [ ] Demonstrate version-specific review, preserved warnings/semantic limits, regeneration lineage and unchanged human approval/candidate-owned fields.
- [ ] Supply SF-07 the final review/result/progress/access contract; supply SF-08 stable readiness/failure transition inputs and pending live notification checks. Notification implementation remains SF-08-owned.
- [ ] Report unit/contract, stateful fake, real SQLite, native Windows, real GEN-05, live candidate Files access and SF-08 evidence separately; do not claim G4 from isolated tests.

Planning result: only this story document is created. No code, schemas, migrations, configuration, Salesforce metadata or live org records are implemented or changed by this task.
