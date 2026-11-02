# AUTO-02 — Automatic drafting policy

Component: **AUTO-02 only**  
Status: **DEFERRED — Phase 2; planning only; no implementation or automation activation authorized by this document**  
Prepared: **31 October 2026 (Europe/Berlin)**  
Requirements: **R17**; supporting constraints **R05, R06, R09–R12, R14–R16**.  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially §§4–8, AUTO-02 and gate G5.

## Objective and boundary

Optionally create durable draft requests for qualifying jobs through the existing generation workflow. Make eligibility, relevance, volume, document options and repeat-generation decisions explicit and inspectable. Unchanged inputs must not create repeated automatic drafts; failed or uncertain eligibility must never become an implicit authorization. Preserve deliberate manual regeneration and human document approval.

Every story below is **DEFERRED**. This document does not enable a policy, create a request, modify configuration or schemas, deploy Salesforce metadata, invoke inference, or start a worker. Future implementation and subsequent operational activation require their own selected scope and verification.

AUTO-02 owns policy evaluation and automatic request admission, including its decision history, deduplication and budget reservations. It delegates request processing, freezing, content generation, validation, rendering and delivery to GEN-01–06. It does not schedule runs (AUTO-01), send per-run notifications (AUTO-03/SF-09), implement Salesforce actions or review UI (SF-05–08), change matching rules, approve documents, or submit applications. Missing prerequisite capabilities remain explicit dependency gates.

## Repository evidence and dependencies

Reviewed repository guidance: [README.md](../../README.md) and the blueprint. No applicable `AGENTS.md` was found in the workspace, searched parent locations or relevant documentation/source directories. The blueprint and later recorded decisions take precedence over historical planning documents. The table records inspection evidence, not tests executed during this planning task.

| Dependency | Evidence and contract to consume | Implication for AUTO-02 |
|---|---|---|
| MATCH-02, direct | [Handoff](../components/MATCH-02.md), [result contracts](../../src/job_automation/assessment/llm_records.py), [composition](../../src/job_automation/assessment/llm_composition.py), [C11](../../src/job_automation/contracts/assessment.py) | `AssessmentRunResult` is success with C11 or pending with an error and deterministic baseline. Failures, missing-data rejections, required gaps and review conditions precede scores. Live model quality acceptance remains pending in the handoff. |
| RUN-01, selection integration | [SelectionManager](../../src/job_automation/orchestration/selection.py), [assessment stage](../../src/job_automation/orchestration/assessment_stage.py) | Consume the authoritative `AssessmentSelection` for the current candidate/job/input fingerprint and successful production work. A pending LLM result must not fall back to an older eligible assessment or its deterministic baseline. Comparison/evaluation results are not admission candidates. |
| GEN-01, direct | [Handoff](../components/GEN-01.md), [worker](../../src/job_automation/generation/worker.py), [admission](../../src/job_automation/generation/admission.py), [C13](../../src/job_automation/contracts/generation.py) | Reuse polling, admission, coordinator, checkpoints, process lock and recovery. New manual requests retain distinct identity; retries retain the same identity. Handoff claims do not establish live org integration. |
| GEN-02, direct | No `docs/components/GEN-02.md` exists. Read [GEN-02 stories](GEN-02.md), [input service](../../src/job_automation/generation/input_service.py), [resolution](../../src/job_automation/generation/input_resolution.py), [records](../../src/job_automation/generation/input_records.py), and downstream GEN handoff references. | Implementation exists, including durable seals and preflight receipts. Do not invent a standalone verified handoff. Resolve assessed-versus-frozen binding and policy-version gaps below before enabling automatic requests. |
| GEN-03, direct | [Handoff](../components/GEN-03.md), `generation/draft_service.py`, `draft_prompts.py` | C14 `DraftDocumentV2` schema 2.0; immutable content receipts; configured language/content specification and frozen recipe. Extractive factual text retains source language; requested German/English output is not proof of candidate proficiency. Live semantic quality review is pending. |
| GEN-04, direct | [Handoff](../components/GEN-04.md), `generation/validation_service.py`, `validation_records.py` | Only complete validation with no fatal issues permits rendering for review. Mandatory human-review warnings remain; AUTO-02 cannot turn a passing report into approval. |
| GEN-05, direct | [Handoff](../components/GEN-05.md), `generation/render_service.py`, `render_adapter.py` | Reuse immutable artifact versions and approved layouts. DOCX/PDF requirements must survive the adapter boundary. The handoff records native LibreOffice/PDF visual verification as pending. |
| GEN-06, direct | [Handoff](../components/GEN-06.md), `generation/delivery_service.py`, `delivery_lineage.py` | Reuse upload reconciliation and accessibility checks; retain `upload_pending` and local files on failure. Readiness remains separate from approval. SF-08 notification verification is pending; offline tests are not live acceptance. |
| FND-01 / DATA-01 / OPS-01 | Existing versioned contracts, [request repository](../../src/job_automation/storage/repositories/generation_requests.py), [migrations](../../src/job_automation/storage/migrations.py) | Add explicit companion schemas and transactions; retain compact deduplication identities across cleanup, backup and restore. Do not replace C13/C14 state machines. |
| PROFILE-01 / POLICY-01 / IDENTITY-01/02 / CONTEXT-01–04 | Approved C01, effective C02, canonical lineage/revisions and availability, purpose-specific context/index bindings | Assess current approved facts, preserve unknowns, bind generation to permitted evidence, and use existing identity/availability semantics. No profile approval, source closure inference, index rebuilding or context fallback inside AUTO-02. |
| SYNC-01 / SFCLIENT-01 / SF-05–07 | Existing job mappings, typed gateway upsert/query operations, generation request metadata and candidate-owned state | Automatic external requests need a verified unique External ID/client key, real job lookup mapping, candidate-state read access and review visibility. Org deployment/permissions remain prerequisite-owned. |
| AUTO-01 / AUTO-03 / SF-09 | [AUTO-01 deferred stories](AUTO-01.md), blueprint component boundaries | Scheduling is not required for a bounded manual invocation of the future policy service. Only expose results for later summaries/notifications; do not implement those components here. |

### Concrete integration gaps to resolve before activation

1. **Production composition:** `generation/cli.py` constructs `GenerationWorker` without GEN-02–06 service instances. `worker.py` passes those optional instances to the coordinator; absent stages block. Component code and injectable tests alone do not establish a runnable production chain. GEN-01 must supply and verify supported composition, including recipes, validation, rendering, delivery and actual org configuration.
2. **External request admission:** there is no automatic request publisher. `polling.py` currently resolves the job lookup as a local UUID; a normal Salesforce lookup ID is quarantined as unmapped. Resolve through SYNC-01's org-scoped mapping, not by writing a UUID into a Salesforce lookup field. `RequestFieldMapping` names are configurable examples, not inspected org metadata.
3. **Identity and payload integrity:** current local indexes on Salesforce request ID/client key are not unique. `GenerationAdmitter` can reuse an existing client-key match without validating the full payload, and polling/admission use `bool(...)` for the override. Before AUTO-02 uses this boundary, enforce scoped uniqueness, compare immutable options/job/org bindings, reject malformed booleans, and block conflicting remote records. Existing manual history must not be collapsed during migration.
4. **Assessment-to-freeze race:** `InputResolver` reads the current profile and posting; C13 has no automatic-decision provenance or expected assessment binding. `prepare_freeze` resolves outside its seal transaction without an AUTO-02 comparison guard. Add a narrow automatic-request guard at the existing GEN-01/02 boundary. Merely checking eligibility when queuing is insufficient.
5. **Search policy provenance:** `input_service.py` currently populates manifest `policy_version` from `default_template_version`. That cannot prove the actual C02 version used for eligibility. Correct this with the GEN-02 owner and record compatibility for old seals. Store automatic policy version separately; never relabel a template version or automatic policy version as C02.
6. **Options across stages:** C13 has a single `template_id`; GEN-03 treats it as a content specification while GEN-05 resolves a physical layout. Formats are worker settings and also appear in frozen options; the render adapter requests one format at a time. Establish and test explicit content/layout/formats bindings end to end before claiming policy-selected options survive retries. Do not add unsupported keys to current configuration and assume they work.
7. **Current selection and candidate control:** do not use `get_latest_assessment(job)` as the admission API. Verify the selected result against current inputs and pending work, and provide a bounded, fresh candidate-status/opt-out observation through existing Salesforce integration. If those observations cannot be obtained, automatic admission is held visibly.

These are prerequisite corrections or narrow contract integrations, not authorization to implement other components in this planning task. Future implementation must either coordinate them with their owners or report the affected AUTO-02 story blocked.

## Policy: requirements versus configuration decisions

Required behavior is duplicate prevention, existing-workflow reuse, explicit review for failed/uncertain eligibility, deliberate manual regeneration, versioned auditability and human approval. The conservative rules below are **proposed implementation policy**, not additional confirmed user preferences. Thresholds and operating quantities remain unselected configuration decisions. Nothing in existing example configs or worker limits establishes an automatic drafting entitlement.

| Configuration decision | Proposed semantics; values to confirm before activation |
|---|---|
| Activation and scope | Disabled when absent; explicit activation for one candidate and verified org. Require a complete valid policy. Missing/invalid config never means unlimited or eligible. |
| Assessment method | Initially admit only successful, authoritative MATCH-02 LLM results. Rules-only results remain manually actionable but are not assigned a synthetic score. Supporting automatic rules-only admission later requires a separately specified, versioned relevance rule. |
| Relevance threshold | Explicit finite `minimum_relevance_score` on the declared `0-100` scale; equality passes (`score >= threshold`). No numeric threshold selected here. Keep it distinct from C02's matching threshold and never use it to override C11 review/rejection. Resolve with MATCH-02/EVAL-01 evidence. |
| Freshness | Select maximum ages for assessment, availability and candidate-control observations. Compare authoritative UTC event times with a documented clock-skew rule. Unset limits block activation; stale/missing/future-inconsistent observations hold the item. Freshness is separate from material-input equality. |
| Candidate application state | Proposed allowlist: `New` and `Shortlisted`, with explicit opt-out honored. `Review` and unknown state hold for review; other states suppress new automatic work. Final allowlist is a configuration decision; never reset candidate-owned status or interpret a shortlist as an eligibility override. |
| Document selection | Explicit bounded set of document variants: CV and, only when selected, cover letter. No automatic cover letter inferred from job text. Resolve language (`de`/`en`), JSON/RAG strategy, content specification, approved layout/version and required formats for every variant. No selected default language/style in this story. |
| Volume | Required finite nonnegative limits for new requests per logical evaluation run, per rolling time window, per candidate/job across changed inputs, and total outstanding automatic work. Window duration, counts and maximum wait are configuration decisions. Zero pauses admissions; null/unset does not mean unlimited. |
| Repeat generation | Proposed default `first_only` per candidate/job/document variant. Optional `on_material_change` must explicitly allow change classes (posting content, approved profile/purpose permissions, document options or generation recipe). Choose cooldown and per-job/window ceilings before enabling that mode. No timer-only, failure-only or policy-version-only regeneration. |
| Deployment updates | Model/prompt/content/layout/context changes are potentially material but do not authorize bulk regeneration by themselves. Default to review for deployment-driven changes unless that change class is explicitly enabled; apply normal volume limits. |

### Ordered eligibility and review rules

Evaluate all applicable gates, retain structured reasons, and choose the most restrictive outcome. A score never rescues another failed gate. A deferred volume decision is not an eligibility failure.

| Condition | Automatic result and required visibility |
|---|---|
| Policy disabled, invalid or dependency not configured | `disabled` or `blocked`; no new request, remote mutation or model call. Invalid configuration has a classified, inspectable error. |
| Evaluation/comparison run, unselected/intermediate C11, wrong candidate or org | Exclude from admissions; record source/mode reason. Never publish evaluation artifacts. |
| Missing current selection; pending/failed MATCH-02; stale assessment; changed posting/profile/C02/model assessment binding | `review_required` or `blocked` with reason and upstream error/reassessment reference. No fallback to the deterministic baseline, old eligible result, another context strategy or a missing score. |
| Hard fail, missing-information rejection, explicit exclusion, required gap, or C11 `rejected` | `ineligible`, retaining rejection reasons and inspection route. Do not turn technical model failure into this result. Candidate may inspect and deliberately request a manual draft under the existing workflow. |
| Hard unknown, unresolved required/unclear finding, C11 `review`, unresolved eligibility fact, missing required coverage or assessment validation issue | `review_required`, preserving issues and review routing. Proposed initial policy holds any nonempty `identified_unknowns` or `validation_issues`; later relaxation must identify exact non-eligibility warning codes and have reviewed evidence. No generic “ignore warnings” switch. |
| C11 says eligible but rule/trace coverage is missing, inconsistent or unresolvable | `review_required`; do not rely only on the disposition enum. Check effective C02 required criteria and authoritative deterministic trace. A policy with no required criteria must explicitly demonstrate that fact. |
| Missing, NaN/infinite, out-of-range or wrong-scale relevance score | `review_required`/invalid assessment; no implicit zero, normalization or conversion. Valid score below AUTO-02 threshold produces `below_threshold` without changing C11. |
| Availability unavailable | `ineligible`; automatic requests always set `allow_unavailable_job=false`. Unknown/not_seen/conflicting or stale availability produces `review_required`. This conservative automatic gate is stricter than GEN-02's warning-only manual behavior. |
| Unapproved/missing profile or missing purpose permissions; unavailable recipe/layout/index | `blocked` with remediation. Assessment permission does not grant CV/cover-letter permission. JSON budget errors and RAG failures never silently switch strategies. |
| Candidate opted out, application state disallowed, or identical manual work already exists | `suppressed` with reference/reason. Missing or stale candidate-control state produces a visible hold. Never overwrite notes, follow-ups, progress, approval or an override. |
| Eligible, threshold met, current bindings valid, no duplicate, repeat policy permits and budgets available | Reserve and create a request through GEN-01. Output remains a draft requiring GEN-04 validation and candidate review. |

Review decisions must be discoverable in a local policy inspection/report interface even when Salesforce is offline. Link to the existing job/review route where available and preserve SYNC-01's review publication semantics. Do not create a generation request merely to transport an eligibility error or make an untracked rejected job eligible. Technical errors and eligibility uncertainty remain distinct from definite rejection.

### Volume accounting and ordering

- Count **logical document requests**, not jobs, files, polls, model attempts or notifications. A CV plus cover letter uses two request slots; DOCX and PDF of one document use one. A repeated request consumes no additional admission slot.
- Apply all limits together under a transaction. Count reserved, unsent, uncertain remote and admitted work against outstanding capacity. Keep failed unresolved automatic work in the backlog count until an explicit recorded resolution; `ready_for_review` ends processing but never clears duplicate history. Candidate review backlog limits can be added only as an explicit policy decision with an authoritative approval-state source.
- Charge the rolling-window quota at reservation. Retries, lost responses, downstream failures and restarts retain that charge. Only a proven never-sent, never-admitted released reservation can return capacity; ambiguous outcomes cannot. Retain the release history and stable key if the same intent is later reconsidered.
- A logical evaluation run retains its ID and cumulative per-run count on resume. Starting another run cannot evade the rolling-window/per-job limits. Quota scope is candidate/org, independent of policy-version labels; policy reload and rollback never reset counters.
- Rank qualified candidates by descending valid score, then stable canonical job ID and configured document-variant order. Deduplicate canonical aliases before ranking. Proposed behavior reserves the selected document bundle atomically; insufficient capacity defers the bundle, rather than silently dropping a requested letter. Report the ordering and deferral reason.
- Bundle reservation is local admission atomicity, not a distributed all-or-nothing Salesforce transaction. If one request is created and its sibling fails, retain the created request and reconcile/retry only the unresolved sibling under its original key. Do not delete the successful request, reserve the whole bundle again, or claim both documents are ready.
- A deferred item is reevaluated against current selection, candidate control and policy before admission. Persist it with a bounded expiry; select expiry duration during configuration. No model inference is needed merely to retry admission. Component stage/transport budgets remain authoritative after admission.

## Contracts and repeat identity

Establish these **proposed companion contracts** before business logic. Names are implementation proposals; none exists merely because it is described here. Start at schema 1.0 and specify canonical serialization/hash version. Reuse `ClassifiedError` and stable `details.reason_code` values; do not silently add processing states to C13 or C15.

| Record / port | Required contents and invariants |
|---|---|
| `AutomaticDraftPolicy` | Schema, immutable policy ID/version, canonical content hash, enabled/scope, threshold and scale, allowed application states, freshness limits, finite volume/window limits, document variants, repeat mode/change allowlist/cooldown, bounded submission retries and policy engine version. Separate this from C02 and GEN worker settings. |
| `AutomaticDraftCandidate` | Candidate/org/job and lineage, exact selected C11 ID/body hash/input fingerprint, RUN-01 selection/work provenance and run mode, current posting revision/hash, approved profile version/digest/permissions, actual C02 version/hash, availability evidence, fresh candidate-control observation, resolved document/recipe/layout/context bindings. Unknown fields stay unknown. |
| `AutomaticDraftDecision` | Stable decision ID, evaluation run and attempt IDs, policy version/hash, decision-input fingerprint, evaluated time, outcome and reason codes, evidence references, relevant gate values, quota snapshot, optional existing request/intent link and review route. Persist no raw profile text in ordinary diagnostics. |
| `AutomaticDraftIntent` | Stable client key, material generation fingerprint, policy/decision provenance, immutable request payload/digest, candidate/org/job mapping, expected preflight binding, reservation, bounded attempts, submission state and remote/local request IDs. Proposed states: reserved, sending, uncertain, acknowledged, held, released or failed. These are submission states, not C13 states. |
| `AutomaticDraftReservation` | Candidate/org scope, logical evaluation run, charged UTC timestamp/window, document-request units, intent association, outstanding/consumed/released status and release evidence. Atomic uniqueness and quota checks, not a process-memory counter. |
| `AutomaticRequestBinding` | One-to-one local C13 and automatic intent association, original policy provenance, expected/frozen input hashes and revalidation receipt. Trusted origin derived from this durable association, not arbitrary job text or an unverified remote label. An automatic key without its binding fails visibly. |
| Policy evaluator / request publisher | Pure `evaluate(candidate, policy, history, now)` returns decisions/proposals; a separate reserve-and-submit service rechecks authoritative state and uses typed Salesforce gateway plus GEN-01 admission. Neither invokes drafting/model/rendering services directly. |
| `AutomaticDraftEvaluationReport` | Run/policy identity, counts by outcome with documented units (jobs versus requests), reservations, admitted/reused/held/uncertain IDs, failures and pending work. Local inspection plus a future C15/AUTO-03 adapter; no notification transport. |

### Two fingerprints, not one overloaded key

**Decision-input fingerprint** includes the authoritative assessment binding, C02 hash, automatic policy content/engine version, availability and candidate-control evidence. It explains why a job was allowed or held. Reevaluation may create a new decision without creating a new draft.

**Material generation fingerprint** identifies equivalent document work across runs. Include org/candidate/canonical opportunity identity, material posting content and source binding required for factual citations, approved profile content and purpose permissions, document type/language, content specification and approved layout digests, formats, context strategy and output-affecting inclusion/retrieval settings, immutable model/prompt/schema/inference recipe digests. Include a C02-derived value only if the generation owner actually consumes it to affect document content; pure search/admission policy labels are not document inputs.

Exclude run/attempt/request/assessment UUIDs, timestamps, refreshed observation times, scores, automatic policy labels, poll count, temporary paths, index build UUIDs and transport IDs. Use semantic index/chunk/model/settings digests so an equivalent index rebuild cannot cause another draft. Record full evidence/version provenance separately. Changing a genuine source binding needed for citations can be material; merely seeing the same canonical opportunity on another board cannot be treated as a new opportunity. Unresolved merge/split lineage holds for review.

Use a stable namespaced client key derived from scope and the material fingerprint, for example `auto02:v1:<digest>` (proposed grammar, subject to SF-05 field length). Store and compare the full payload as well as its hash; collisions or same-key/different-payload reuse block. The policy version is deliberately excluded from this key. Do not reuse GEN-03's request-specific logical key or a freeze manifest hash containing timestamps as a cross-run key.

| Repeat scenario | Required behavior |
|---|---|
| Same material inputs on another run/day, new assessment UUID or refreshed score | Reuse/reference prior intent/request; no new request or model call. Passage of time never defeats suppression. |
| Existing automatic request pending/running/upload_pending/ready_for_review/failed | Same key remains reserved historically. Resume or inspect the same request; no fresh automatic request to escape failure/retry budgets. Missing artifacts or manual deletion is a recovery issue, not regeneration permission. |
| Existing matching manual request | Suppress automatic duplication when a verified frozen binding or accepted expected binding proves equivalence. If a manual pending request could overlap but equivalence cannot be established, hold until resolved. Never mutate or relabel the manual request. |
| Explicit manual regeneration with identical inputs | New manual client key/remote record and distinct C13 UUID, optional validated predecessor link, fresh draft artifacts. It is not subject to AUTO-02 deduplication, quotas or disabled status; shared worker/resource and existing manual preflight rules still apply. A retry of that request keeps its identity. |
| Changed posting/profile/options/recipe | Fresh successful eligibility is necessary. `first_only` holds for manual choice; `on_material_change` may create one new key only for allowed change classes within cooldown/volume bounds. Link predecessor without changing prior documents/approval. |
| Material inputs revert to an earlier version | Look up all retained fingerprints, not only the latest request. Reuse/suppress the historical equivalent. Intentional repeat still uses manual regeneration. |
| Review/failure becomes successful on the same inputs | A previous decision without a request may be reconsidered. A prior reserved/admitted request remains the same logical request; retry only through its bounded recovery path. |

Compact deduplication records outlive bulky artifacts and completed-run logs. Migration, backup/restore, policy rollback, identity aliases and deletion must not erase them and silently allow repeats. Ambiguous restored history holds for reconciliation with remote client keys.

## Policy-version and freeze behavior

1. Policy versions are immutable: same version with different canonical content is a configuration conflict. Keep schema version, policy version, policy content hash, engine version and fingerprint algorithm version distinct. Unsupported versions block new admission.
2. Threshold, volume, freshness or candidate-state policy changes reevaluate decisions. A previously below-threshold job with no request may qualify, but an equivalent existing draft remains suppressed. Raising limits, renaming a policy, toggling off/on or rolling back never resets history or creates a new key.
3. Search policy C02 changes invalidate the old eligibility result until MATCH-02/RUN-01 supplies a successful current selection. Do not copy an old score under the new C02 label. If document inputs remain equivalent after reassessment, retain suppression.
4. Unsent and unsealed automatic work must pass the currently active policy before send/claim. A tightened/disabled policy or changed inputs hold it visibly; reconcile ambiguous remote creation before releasing reservations. Never rewrite its accepted payload or substitute latest inputs under an old request key. A new material key is considered only through a fresh decision and the repeat policy.
   When a hold is resolved by a new successful assessment or policy reevaluation and the material generation inputs are still identical, append a revalidation receipt and resume the same intent/request through its permitted recovery path. Preserve the original decision as history. Changed assessment/C02 provenance alone does not require a new key, and cannot authorize execution without that fresh receipt. A failed request is not silently reset by the policy evaluator.
5. At GEN-02 seal/GEN-01 claim, atomically verify the automatic binding against authoritative selection, current profile/posting/C02, availability, permitted options and candidate-control freshness. Persist the revalidation receipt with the accepted binding. Concurrent local changes require a bounded reread/CAS retry or hold; stale remote observations require refresh. No network operation belongs inside the SQLite write transaction.
6. Once correctly sealed and claimed, resume the original request and frozen policy/input provenance. A later policy edit does not silently re-freeze, regenerate or alter historical approval. Disabling admission stops new work; pausing already claimed work is an explicit existing-worker operational action, not deletion or an automatic approval/cancellation inferred from this policy. Expose that distinction in inspection.
7. Fingerprint algorithm upgrades need a compatibility lookup/backfill over verifiable history before accepting new keys. Preserve old keys and aliases; missing legacy provenance produces a review hold, not a presumed empty history. No bulk backfill of automatic requests on deployment.

## Existing workflow and transaction boundaries

Proposed route: **selected production assessment → policy decision/reservation → durable request-creation intent → existing typed Salesforce gateway → GEN-01 observation/admission → GEN-02 freeze → GEN-03 content → GEN-04 validation → GEN-05 rendering → GEN-06 delivery/review**.

Choose the remote-request-first route because the existing worker polls Salesforce requests and projects states/delivers files against those records. Do not create an executable local-only C13 and hope a later publisher attaches a remote ID. A local-only mode would require its own explicit compatible workflow design and is not included here.

| Boundary | Durable action and recovery |
|---|---|
| Evaluate / preview | Read existing evidence and return explicit decisions. Preview creates no requests, reservations, model calls or remote writes. A preview is not a future admission authorization. |
| Reserve | Under the existing shared deployment lock, atomically recheck selected inputs, deduplication and all quotas; persist decision, immutable creation intent and reservation together. No new C13 is executable yet. Rollback leaves no partial charge or orphan intent. |
| Create/reconcile request | Outside the database transaction, use the verified SF-05 unique External ID/client key and mapped job lookup with an immutable Pending payload. Before retrying, read by key: matching existing record is adopted without resetting its state; proven absence permits a bounded send; conflicting/multiple/uncertain records hold. Never blindly replay `Status=Pending` over a Running or completed request. |
| Admit | Persist acknowledgment and verified org/job/options mapping; use GEN-01 observation/admission to create or reuse the sole C13. Atomically associate it with automatic provenance/reservation before it can execute. Polling races must converge on the same ID; automatic-key observations lacking valid local provenance remain blocked. Use existing remote-derived UUID conventions, not a competing UUID scheme. |
| Freeze/claim | Execute the automatic guard described above through the existing GEN-01/02 seam. Persist seal and claim/checkpoints using their transaction rules before projecting Running. Unknown/failed/stale eligibility cannot proceed merely because a remote Pending record exists. |
| Process/deliver | GEN-01–06 own retry/checkpoint/artifact identities. On failure, inspect or retry the same request; AUTO-02 never calls the model to “repair” an eligibility or delivery failure. `upload_pending` stays visible, and `ready_for_review` requires accessible required artifacts. Approval remains `draft`. |

If a remote request exists but policy revalidation fails, retain the mapping and held/error receipt and use the established actionable failure/blocked projection; never leave it as an apparently executable success. Do not introduce a C13 `review_required` enum by accident. An eligibility hold with no request remains a policy decision; a worker dependency block uses existing stage status; a terminal preflight failure uses the existing failed-request contract.

Use recoverable at-least-once processing with reconciliation, not a promise of exactly-once network delivery. If storage fails before intent persistence, send nothing. If it fails after a possible remote success, retain/recover the stable key and reconcile before doing more work. Retention and recovery must preserve all referenced evidence, reservations and unresolved sends.

## Ordered implementation stories — all DEFERRED

### AUTO-02-S01 — Versioned policy and admission contracts

**Status:** DEFERRED.  
**Objective:** Define the policy and compatibility boundary before admission logic.  
**Requirements:** R17; supporting R05/R10/R15/R16.  
**Dependencies:** FND-01, DATA-01; MATCH-02 and GEN-01/02 contracts; SF-05 external-key agreement.  
**Owned modules:** proposed `generation/automatic/records.py`, `settings.py`, `ports.py`; companion schema exports/fixtures and a disabled example configuration.  
**Inputs → outputs:** explicit policy choices and current contracts → validated immutable policy, decisions, intents, bindings and reports.

Tasks:

- Formalize the records, decision reasons, origin trust, score validation, configuration-decision register and separate C02/AUTO-02 versions.
- Define canonical fingerprint projection, material-change classes, key grammar and full-payload conflict checks. Identify each field's generation owner.
- Specify additive configuration reference resolution using existing absolute Windows data-root conventions. Omitted configuration means disabled; enabled incomplete policies fail validation.
- Document migrations/consumer compatibility before altering C13 or GEN seams. Register schemas without changing legacy meaning or blessing unverified history.

Acceptance: schema round trips preserve policy/binding identity; invalid score scales, unknown versions, unbounded quotas and string overrides fail clearly. Disabled policies load without enabling anything. No numeric production threshold or cap is invented.

Tests: synthetic contract/configuration tests, fingerprint invariance/mutation cases, legacy C13 readability. Migration/configuration impact: contracts and disabled templates only; schema references are proposals until implemented.

### AUTO-02-S02 — Authoritative eligibility evaluation and review outcomes

**Status:** DEFERRED.  
**Objective:** Produce deterministic, explainable decisions from current selected production results.  
**Requirements:** R17; supporting R05/R06/R11/R15.  
**Dependencies:** S01; MATCH-02, RUN-01 selection, PROFILE-01, POLICY-01, IDENTITY-01/02, candidate-control observation integration.  
**Owned modules:** proposed `generation/automatic/evaluator.py`, `candidate_reader.py`; narrow existing selection/read adapters.  
**Inputs → outputs:** current candidate envelope and policy → decision with reasons, evidence and optional request proposal.

Tasks:

- Implement the ordered eligibility table, required-rule coverage, finite score threshold and freshness checks without new model calls.
- Reject comparison/unselected results and old eligible selections while current assessment is pending. Preserve technical errors, unknowns and definite rejection as different outcomes.
- Resolve document variants against approved purpose permissions and supported recipes/layouts/context settings. Keep advert language separate from candidate proficiency.
- Respect candidate opt-out/state and record safe inspection/review references, including when Salesforce is offline.

Acceptance: score at threshold qualifies only if every other gate passes; maximum score with fail/unknown/missing coverage never creates a proposal. Model outage leaves reviewable work. JSON/RAG and CV/letter variants receive the same eligibility protections.

Tests: full decision-table fixtures, threshold boundaries, time/skew cases, changed profile/C02/posting, pending-over-old-success, stale candidate status, injection text. Configuration impact: consume explicitly selected policy values; no matching-policy edits.

### AUTO-02-S03 — Durable deduplication, quotas and policy history

**Status:** DEFERRED.  
**Objective:** Make repeated and concurrent admission bounded across runs and restarts.  
**Requirements:** R17; supporting R09/R10/R16.  
**Dependencies:** S01–S02, DATA-01, OPS-01 reference retention, canonical lineage.  
**Owned modules:** proposed `storage/repositories/automatic_drafts.py`, `generation/automatic/history.py`, `budgets.py`; next forward migration and minimal backup inventory hooks.  
**Inputs → outputs:** decisions, historical work and limits → atomic reservations/intents or explicit duplicate/deferred outcomes.

Tasks:

- Persist immutable policy snapshots, decisions, unique scoped material keys, request links, quota charges and releases; implement transaction/CAS guards for concurrent admission.
- Apply per-run/window/job/outstanding limits and deterministic bundle ordering. Preserve counts through policy edits, retries and run resume.
- Cross-check existing manual requests; backfill only proven equivalence and hold ambiguous legacy work. Support canonical alias lookup and historical-input reversion.
- Protect compact identities and unresolved work through cleanup/restore. Audit existing conflicting client-key rows before introducing constraints; do not silently merge/delete them.

Acceptance: two concurrent attempts for the final slot admit one bundle; unchanged reruns across days create no new intent; reverting inputs finds the older request. Rollback leaves neither quota charge nor partial intent. Policy rollback cannot reset quota or duplicate history.

Tests: real SQLite transactions, crash injection, window boundaries, multi-document accounting, manual overlap, legacy/migration conflicts, backup/restore and retention. Configuration impact: selected finite limits only; no scheduler or production admission.

### AUTO-02-S04 — Idempotent request publication through GEN-01

**Status:** DEFERRED.  
**Objective:** Turn a reserved intent into one inspectable existing-workflow request.  
**Requirements:** R17; supporting R10/R12/R15/R16.  
**Dependencies:** S03; SFCLIENT-01, SYNC-01 mappings, SF-05 metadata/permissions, GEN-01 admission/polling corrections.  
**Owned modules:** proposed `generation/automatic/request_publisher.py`; minimal adapters at existing gateway/request mapping/admission seams. SF metadata remains with SF-05.  
**Inputs → outputs:** immutable intent → reconciled remote ID and one associated C13, or classified held/failure result.

Tasks:

- Validate org/client-key uniqueness and actual job lookup mappings before mutation. Use typed gateway operations and persist intent before send.
- Implement adopt/proven-absent/conflict/uncertain reconciliation with bounded attempts. Compare payloads and preserve remote processing state on replay.
- Add atomic local acknowledgment/admission/binding association; make polling races converge. Reject untrusted or orphan automatic keys and malformed override values.
- Surface authentication, permission, mapping, capacity and transient failures without losing reservations or creating replacement keys.

Acceptance: a successful remote create with a lost response is adopted once after restart; a conflict holds; the same key never points to two C13 records. Remote Running is never reset to Pending. No content/render/model API is called by publication.

Tests: fake gateway plus real repository, crash before/after send and acknowledgment, duplicate polls, 15/18-character IDs, wrong org/job/options, uncertain absence and permission failure. Live org verification remains a separate recorded gate. Configuration impact: verified request mappings and External ID deployment dependency, no invented org names.

### AUTO-02-S05 — Bind automatic admission to exact frozen inputs

**Status:** DEFERRED.  
**Objective:** Prevent queued requests from drafting changed or no-longer-qualified inputs.  
**Requirements:** R17; supporting R05/R06/R10–R12/R16.  
**Dependencies:** S02–S04; GEN-01/02 owners resolve preflight, policy provenance and production wiring gaps; GEN-03–06 option contracts.  
**Owned modules:** proposed `generation/automatic/preflight.py`; narrow compatible guard integration in existing admission/coordinator/input services.  
**Inputs → outputs:** automatic binding plus current evidence → revalidated freeze/claim or durable visible hold/error.

Tasks:

- Gate all automatic worker entry paths, including local unfinished work and recovery, before first claim. Verify expected bindings inside the authoritative commit boundary, with safe reread/CAS behavior.
- Bind actual C02 and automatic policy provenance separately; validate selected options against the resulting GEN-02 seal and GEN-05 render specification. Never resolve changed defaults under a prior accepted key.
- Revalidate unsealed work after policy change/disable; preserve correctly claimed frozen work. Define held-request retry through existing recovery without bypassing the guard.
- Preserve the manual path, deliberate regeneration and explicit unavailable-job choice. Automatic requests cannot inherit a manual override or predecessor approval.

Acceptance: active/eligible at queue time but unknown, rejected, unavailable or materially changed at freeze produces no content generation. Crash after seal/claim resumes exact original inputs. Disabled AUTO-02 still permits a deliberate manual regeneration with fresh identity and draft approval status.

Tests: queue-to-freeze races, policy changes before/after seal, unknown availability, missing auto binding, restart before claim, changed layout/format defaults, explicit manual override and GEN-01–06 integration. Migration/configuration impact: versioned additive binding/receipt support; old incomplete seals remain inspectable and cannot be fabricated into valid AUTO-02 evidence.

### AUTO-02-S06 — Bounded invocation, inspection and recovery reporting

**Status:** DEFERRED.  
**Objective:** Expose policy evaluation and actionable decisions without an implicit background loop.  
**Requirements:** R17; supporting R14–R16.  
**Dependencies:** S01–S05, RUN-01 locking/report conventions, GEN-01 recovery. AUTO-01/AUTO-03 are downstream consumers only.  
**Owned modules:** proposed `generation/automatic/service.py`, `reporting.py`, `cli.py`; minimal main CLI registration and run-result adapter.  
**Inputs → outputs:** explicit bounded evaluation invocation → policy report and, only when enabled and selected, existing-workflow requests.

Tasks:

- Provide distinct preview, evaluate and inspect operations; exact command spelling is a future interface decision, not an existing command. Preview has zero admission side effects.
- Reuse the deployment lock before mutation and serialize with search/generation; reuse an existing held lock at an in-process run seam rather than deadlocking through a second worker.
- Resume unresolved intents before considering new reservations. Apply all retry/volume bounds and report exhausted/held work with remediation.
- Report zero-candidate, disabled, rejected, review, duplicate, deferred, admitted, uncertain and failed outcomes with stable run/request links. Expose data for later C15/AUTO-03 consumption without sending messages or creating notification Flows.

Acceptance: a bounded run exits with inspectable results and no background process; inspection works offline; preview never reserves or publishes; repeated invocation cannot exhaust capacity through duplicate requests. Diagnostics contain IDs/hashes/codes rather than private prompts or profile facts.

Tests: CLI/port fixtures, lock contention, changed working directory, native Windows spaces/umlauts, disabled mode, empty/partial/failed upstream work, secret redaction and restart. Configuration impact: explicit disabled-by-default entry point; no schedule, startup task or service registration.

### AUTO-02-S07 — Repeat-run acceptance and deferred activation handoff

**Status:** DEFERRED.  
**Objective:** Demonstrate policy behavior and record remaining live gates before any activation.  
**Requirements:** R17 and all supporting invariants above.  
**Dependencies:** S01–S06; verified production composition of MATCH-02 and GEN-01–06; SF-05–08 and runtime/renderer access for applicable live checks.  
**Owned modules:** proposed `tests/generation/automatic/`, synthetic fixtures, bounded manual verification harness; future `docs/components/AUTO-02.md` and policy runbook.  
**Inputs → outputs:** configured synthetic scenarios and authorized integration environment → repeat-run/crash evidence, unresolved decisions and explicit activation readiness.

Tasks:

- Execute the acceptance matrix below with real storage and existing generation services; use declared fakes only for external/model boundaries in offline tests.
- Verify complete CV/letter × DE/EN × JSON/RAG routing and requested DOCX/PDF formats, with review warnings preserved. Keep real rendering/visual and live org evidence separate from fake results.
- Document selected thresholds, caps, freshness/cooldown values, allowed change classes and evidence; identify every unresolved configuration choice.
- Produce the component handoff and rollback procedure: disable new admission, preserve unresolved sends/frozen requests/artifacts, reconcile before resumption. Do not enable automation as a side effect of tests, migration or installation.

Acceptance: every applicable matrix case has observed evidence, prerequisite limitations are explicit, and the policy remains disabled until a later operational activation decision. No test grants document approval or submits an application.

Tests/configuration impact: acceptance evidence only; record actual commands/results and environments rather than copying historical pass counts. Choose component tests plus affected assessment/generation/storage/operations regression checks; no claim of live acceptance from fixture-only tests.

## Required repeat-run and failure acceptance matrix

All cases below are **planned, not executed by this document**. Assert request count, stable client/C13 identities, quota charges, downstream call counts, decision reasons and review visibility—not just final status.

| ID | Scenario | Expected observable result |
|---|---|---|
| A02-T01 | First successful selected eligible result meeting configured threshold | One request per selected document variant, charged once; GEN-01–06 owns execution; draft approval status. |
| A02-T02 | Repeat unchanged search/evaluation/poll after restart and on another day | Same logical requests; zero additional content inference, artifacts or admission charges. |
| A02-T03 | New run/assessment/attempt UUID, refreshed timestamp, same content; equivalent RAG index rebuild | No new material key; no duplicate request. |
| A02-T04 | Score below, equal to, above threshold; null, NaN/infinite or wrong scale | Equality/above may qualify only with all gates; below is explicit suppression; invalid values hold. Numbers in fixtures are test data, not policy requirements. |
| A02-T05 | Maximum score with hard fail, required gap, unknown, missing coverage, C11 review/rejected or conflicting trace | No automatic request; correct rejection/review evidence remains visible. |
| A02-T06 | Current model failure/pending with older eligible C11 or eligible deterministic baseline | No fallback admission; pending/review/error result links to upstream work. |
| A02-T07 | Comparison run or unselected JSON/RAG result | No requests or Salesforce mutations. |
| A02-T08 | Unknown/not_seen/unavailable availability; candidate opt-out or stale control state | No automatic bypass; distinct hold/suppression reasons; manual request behavior preserved. |
| A02-T09 | Changed posting/profile/C02 after queueing but before freeze, including concurrent transaction | Guard blocks stale admission; no latest-input substitution or draft call. A new successful assessment can release the same intent only when its material inputs still match. |
| A02-T10 | Allowed material change versus disallowed change/first-only/cooldown | At most one new request for allowed inputs within limits; otherwise hold; predecessor remains unchanged. |
| A02-T11 | Inputs revert to a previously drafted version | Historical fingerprint suppresses repeat. |
| A02-T12 | Threshold/volume-only policy edit, label-only version bump, rollback, disable/re-enable | Reevaluate decisions; equivalent drafts stay suppressed; quota/history persists. Same-version content mutation rejects. |
| A02-T13 | Lowered threshold qualifies a previously suppressed job with no request | One request if all current gates/limits pass; no blanket backfill bypass. |
| A02-T14 | Policy changes before send/claim versus after valid seal/claim | Unsealed work held/revalidated; claimed request resumes original snapshots and provenance without new output identity. |
| A02-T15 | CV plus letter, each DOCX/PDF; final available quota slot; one sibling remote create fails | Two request units/four potential files; bundle deferred if insufficient quota; partial remote success retained and only unresolved sibling retried; no silent option loss or duplicate bundle. |
| A02-T16 | Concurrent last-slot reservation; repeated logical run resume; rolling-window boundary | Atomic caps hold; stable ordering; charges survive restart and policy edits. |
| A02-T17 | Crash before reserve commit, after reserve, before send, after lost success, before/after local admission | No partial reservation; restart reconciles stable key and converges to one remote record/C13. |
| A02-T18 | Conflicting/multiple remote matches, wrong org/job/options, forged auto key or duplicate polling | Visible hold/conflict; no remote state reset, wrong binding or second request. |
| A02-T19 | Failed generation/validation, missing renderer, quota/permission failure or inaccessible artifact | Existing request stays actionable; upload failures retain files/upload_pending; no replacement request or false readiness. |
| A02-T20 | Exact manual request already present; ambiguous legacy pending manual request | Proven equivalent suppresses automatic work; ambiguity holds; manual record untouched. |
| A02-T21 | Explicit manual regeneration for unchanged inputs with AUTO-02 disabled or quota full | Fresh manual C13 and draft artifacts; predecessor/approval unchanged. Retrying that request preserves its ID. |
| A02-T22 | JSON budget failure or RAG index/context failure; forbidden purpose facts | Visible failure/hold; no strategy fallback or invented candidate eligibility/evidence. |
| A02-T23 | Cleanup, backup/restore, deleted artifact, identity merge/split or fingerprint algorithm upgrade | Compact history protects against repeats; uncertain lineage/provenance requires reconciliation/review. |
| A02-T24 | Preview, absent policy, invalid config, empty or partial run; lock contention | No unauthorized admissions; bounded safe report. Qualified items from partial runs require independently current successful evidence, never inferred completeness. |
| A02-T25 | Native Windows restart and full supported variant/format matrix | Same identities and pinned options; all required accessible outputs before readiness; warnings and human review retained. |

## Handoff and activation gates

- [ ] Record AUTO-02 status, R17 coverage, dependency/contract versions, owned files and exact decisions in the future component handoff.
- [ ] Resolve the missing GEN-02 handoff evidence and listed code gaps with their owners; do not substitute historical status labels for integration checks.
- [ ] Select and justify threshold, score scale, freshness/skew, application-state allowlist, volume/window values, document variants, repeat change classes, cooldown and expiry. Unresolved values keep activation blocked.
- [ ] Verify policy/schema/fingerprint version compatibility, legacy-history migration, uniqueness and atomic quotas with preserved manual history.
- [ ] Demonstrate request reconciliation and assessed-to-frozen binding using actual production composition; separate offline, native Windows, renderer/visual, live model and live Salesforce evidence.
- [ ] Confirm candidate-accessible review/failure paths, retained warnings, and no automatic approval or application submission. Notification acceptance remains with SF-08/AUTO-03/SF-09.
- [ ] Verify backup/restore and disable/resume behavior without losing duplicate history, quota reservations or unfinished requests.
- [ ] Leave configuration disabled and scheduling untouched. This planning file and its future implementation tests do not authorize operational activation.

Planning deliverable: `docs/stories/AUTO-02.md` only. No application implementation, schema/configuration change, request creation or automation enablement is part of this task.
