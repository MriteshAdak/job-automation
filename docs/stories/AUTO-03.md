# AUTO-03 — Per-run summary delivery

Component: **AUTO-03 only**  
Status: **DEFERRED — Phase 2 planning; not implemented or activated**  
Planning date: **31 October 2026**  
Requirement: **R17**, constrained by R09/R14/R15/R16  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially §§4–8 and the AUTO-03/SF-09 catalog entries.

Deliver a compact, truthful C15 summary of every admitted search run through the Salesforce summary target, including successful, empty, partial and failed runs. Persist delivery intent and recovery progress under the original run ID. Retried delivery must not multiply completion alerts. Pipeline outcome, summary-record delivery and Salesforce notification execution are separate facts.

This document authorizes no implementation, configuration change, org mutation or notification. All stories below remain deferred. Proposed contract names and policies require agreement during implementation; they are not existing APIs or confirmed user preferences.

## Evidence, ownership and dependencies

Repository instructions reviewed: root [README.md](../../README.md) and blueprint §8. No applicable `AGENTS.md` was found in the repository or its checked ancestor directories. Current code takes precedence over broad capability statements in older handoffs.

| Dependency | Evidence and current boundary | Required integration |
|---|---|---|
| RUN-01, direct | [Handoff](../components/RUN-01.md); [runner](../../src/job_automation/orchestration/runner.py), [summary builder](../../src/job_automation/orchestration/summary.py), [RunReport](../../src/job_automation/orchestration/reporting.py), [recovery](../../src/job_automation/orchestration/recovery.py) | Owns run identity, attempts, pipeline outcome, counts and completion evidence. Offline/Windows checks are recorded; live prerequisites remain pending. Agree on a durable completion interface and failure-path coverage before AUTO-03 consumes it. |
| SF-09, direct | Blueprint catalog only. Neither `docs/components/SF-09.md` nor an SF-09 story/metadata handoff was found in this checkout. | **Missing prerequisite, not assumed implemented.** SF-09 owns the remote summary object, unique run key, field permissions, notification type/channel/recipients, Flow, notification receipts and remote deduplication. Obtain its schema and tested behavior before live activation. |
| FND-01 / DATA-01 | [C15 model](../../src/job_automation/contracts/runs.py), [versioned C15 schema](../../schemas/v1/C15_run_summary.schema.json), [run ledger](../../src/job_automation/storage/repositories/runs.py), [pipeline repository](../../src/job_automation/storage/repositories/pipeline_work.py) | C15 is schema 1.0; models forbid extra fields. Use versioned companion records for delivery. Coordinate transactions, schema export/fixtures and additive migration. |
| SFCLIENT-01; SF-01/SF-02 prerequisites | [Gateway handoff](../components/SFCLIENT-01.md), [gateway protocol](../../src/job_automation/contracts/interfaces.py), [gateway](../../src/job_automation/salesforce/gateway.py), [retry policy](../../src/job_automation/salesforce/retry.py) | Reuse typed External ID upsert/read, org checks, credentials, classified failures and finite transport budgets. Gateway fake tests do not prove the SF-09 Flow. Actual org schema and authorization remain gates. |
| OPS-01 | [Handoff](../components/OPS-01.md), storage/backup/restore services | Protect unfinished deliveries and compact deduplication receipts. Restore must reconcile remote state before any replay. |
| AUTO-01, integration only | [Handoff](../components/AUTO-01.md), [stories](AUTO-01.md), `operations/scheduling/` | Scheduling code exists. Consume real run IDs and distinguish launch receipts from C15. AUTO-03 supplies a bounded callable/manual delivery entry point; AUTO-01 owns any later schedule wiring. Scheduling is not required for delivery tests. |
| SYNC-01 / AUTO-02 / SF-08 | Existing job sync, deferred [AUTO-02 stories](AUTO-02.md), blueprint ownership | Job writes, automatic drafting and draft-ready alerts remain separate. Do not reuse C12 job counters or draft readiness as summary delivery state. |

AUTO-03 owns local projection, delivery records, retry/reconciliation, inspection and the adapter to the SF-09 target. Proposed owned locations are `orchestration/summary_delivery/`, `salesforce/summary_target.py`, `storage/repositories/run_summary_deliveries.py`, companion schemas, configuration and focused tests. Names are proposals. Changes at RUN-01, DATA-01 and SFCLIENT-01 boundaries must be narrow and agreed with those owners. No Salesforce metadata/Flow implementation, new email/webhook route, scheduler, drafting policy, model inference or application submission belongs to these stories.

### Code gaps that must be resolved before activation

1. `RunLedgerRepository.get_run()` constructs a fallback C15 for rows without `summary_json`, including rows still marked running. `list_runs()` and `run show` therefore are not authoritative completion feeds. AUTO-03 must require an explicit committed terminal receipt, never infer completion from a synthesized status/end time.
2. `PipelineRunner.start_run()` returns some preflight failures without persisting them. Lock rejection returns a report with no admitted run; some failures occur before storage is usable. Unexpected exceptions and abrupt process death do not establish durable finalization. RUN-01 must cover admitted failures and interruption recovery; AUTO-03 cannot treat stdout or a generated UUID as proof of durable admission.
3. Normal execution calls `complete_run()` and saves the final attempt separately, then returns `RunReport`. The inspected path does not persist that complete companion report atomically with C15. Source/stage coverage needed remotely must come from persisted evidence, not an ephemeral report reconstructed with default values.
4. `complete_run()` overwrites the summary for the same UUID. Resume creates another attempt with the same run ID. A notification key based on attempt, timestamp, status or payload hash would produce duplicates; a revision ordering/finalization contract is needed.
5. No AUTO-03 delivery outbox/configuration or SF-09-specific target contract exists. External ID upsert alone is not evidence that a retriggered Flow will suppress duplicate alerts. The gateway can replay uncertain upserts when the caller marks them replay-safe; that flag must remain false until SF-09 side effects are proven safe.

These are dependency work items or minimal integration changes for future implementation, not permission to implement the prerequisite components in this planning task.

## Outcome and completion semantics

RUN-01 remains authoritative for status and counting units. AUTO-03 validates and projects its committed result; it does not turn a pipeline failure into success, repair counts or rerun pipeline stages to deliver a summary.

| Case | Required summary and alert meaning |
|---|---|
| Successful nonempty run | C15 `success`; report source observations, new/changed jobs, duplicate observations, newly evaluated dispositions and job-sync results, with coverage and time range. |
| Empty successful run | C15 `success`, not a new `empty` enum. Say “No postings found” only when completed source coverage proves zero observations. If postings were seen but no jobs were new, say “No new jobs”; preserve duplicate/update/reused-assessment counts. Zero eligible jobs does not mean no postings. |
| Partial run | C15 `partial`; preserve usable work, failed/incomplete sources or stages, quarantines where available, errors and pending work. Do not announce an empty successful search just because all useful counters are zero. |
| Failed run | C15 `failed` from RUN-01, with bounded actionable error categories and known progress. Missing observations/coverage remain unavailable rather than fabricated zeros. A wholly failed required workload must be classified by RUN-01 before delivery; AUTO-03 does not infer success from zero counts. |
| Interrupted/crashed admitted run | Under the shared worker lock, RUN-01 reconstructs a terminal partial/failed receipt from committed evidence, retaining the run ID and identifying interruption. No alert for a still-active attempt. Recovery time is recorded separately if the actual stop time is unknown. |
| No run admitted | Lock-busy, no work due, invalid CLI or launcher failure before admission is a local launch/invocation diagnostic, not a completed search. Preserve AUTO-01 diagnostics without inventing a C15. An admitted run whose profile/source preflight fails does need a persisted failed summary. |

Preserve C15 1.0 units: `source_counts`/`source_postings_count` count source observations; new/updated counts count distinct canonical jobs; `canonical_jobs_duplicate` counts duplicate observations despite its name; eligible/review/rejected count distinct newly evaluated canonical jobs; sync counters count logical C12 job operations. AUTO-03 sends/retries never increment those counters. Reused assessments and stage/source coverage require the persisted companion receipt. Partial coverage is always visible.

**Proposed completion policy:** one completion alert entitlement per `(verified org, run_id)`, independent of attempts. The first durable terminal result freezes the completion payload and key. A later pipeline resume retains the same run ID and may produce a newer summary revision for the same remote record, but never a second completion entitlement. A deliberate new search has a new UUID and its own alert, even if inputs are unchanged. Retry commands never allocate a new run ID.

Retain the first completion snapshot locally and remotely so a delayed alert identifies the result and time it describes. Later revisions update “latest result” fields silently, with their own revision/time, without changing that initial snapshot or rearming the Flow. Order revisions per run; reconcile an uncertain earlier write before advancing. SF-09 must provide a guard against stale revisions overwriting newer data, including after restoring an old backup. If this guard cannot be provided, hold the conflicting update for repair. A payload change under the same revision is an integrity conflict, not a retry.

R17 requires notification after failed runs as well as successful ones; it does not imply that an unavailable disk/network can deliver immediately. Persist admitted failure evidence as soon as durable storage becomes available. If no trustworthy record survives, expose the local recovery limitation; never fabricate a remote success or claim delivery. Agree with RUN-01 on a durable admission point before substantive work and bounded abandoned-run recovery so crashes do not remain silently unreported forever.

## Proposed contracts and persistence

Keep C15 1.0 unchanged. Define companion contracts at schema 1.0 with canonical serialization/hash version and synthetic fixtures. Any incompatible C15 change requires explicit FND-01/RUN-01 migration and consumer agreement.

| Contract / port | Inputs, outputs and invariants |
|---|---|
| `RunCompletionReceipt` — RUN-01 boundary | Stable run UUID, original start time, attempt reference, monotonically increasing revision, committed terminal C15, completion/recovery timestamps, source/stage coverage with availability markers, origin/mode and evidence reference/hash. Distinguish explicit finalization from display fallbacks. Persist original and revised results. |
| `RunSummaryProjection` — AUTO-03 to SF-09 | Contract/mapping version, verified org, run ID, stable completion key, immutable first-completion projection/hash, latest revision/hash, UTC start/end times, pipeline outcome, documented counts, bounded source/stage coverage, sanitized error/pending-work digest and truncation indicators. Full details remain local, addressable by run ID. |
| `SummaryDelivery` — AUTO-03 local | Unique `(org_id, run_id)` lane; immutable delivery identity and completion key; immutable payload bytes/hash per revision; target/mapping version; state; lifetime dispatch/reconcile counters; retry-window start/deadline; next due time; last classified error; pending remote outcome; remote record ID and acknowledged revision/hash; claim ownership; created/updated/ack timestamps. Child attempt receipts record every send/read and outcome. |
| `SummaryTarget` — adapter using SFCLIENT-01 | Publish typed projection by agreed unique run External ID; read back by the same key; return verified org/key, record ID, applied revision/hash, completion key and available Flow receipt. Distinguish acknowledged, definitely not sent/rejected, ambiguous, conflicting and unavailable results. No unkeyed create or direct notification action. |
| `NotificationReceipt` — SF-09-owned, locally observed | Completion key and remote state such as pending/confirmed/failed/unknown, with receipt/error/time where available. Exact API names/enums are SF-09 decisions. A record acknowledgment is not evidence the user received or read an alert. Unknown remains unknown. |

Local delivery states are proposed companion states, not additions to C15: `pending`, `in_flight`, `retry_wait`, `reconcile_required`, `delivered`, `blocked`, `exhausted`. `delivered` means the expected summary revision is verified at the target; Flow outcome is separate. A newer revision creates new revision work in the same lane while retaining earlier acknowledgments and the single completion entitlement.

Persist terminal receipt and delivery intent atomically where a shared transaction is feasible. At minimum, the terminal receipt must be durable first and a bounded scanner must idempotently repair missing intents by unique key after any crash; record the scan cursor and activation scope. Do not send inside the pipeline transaction. Do not allow outbox failure to rewrite a committed pipeline outcome. Current repository methods commit internally, so composition of existing calls alone does not establish atomicity; add a reviewed transaction boundary or demonstrate scanner recovery explicitly.

Use SQLite constraints for lane/revision uniqueness and immutable payload integrity. Use the existing deployment worker lock for mutation/drain/recovery; preserve zero-write/zero-send behavior on lock contention. Claims and attempt records must survive restart, with stale `in_flight` claims becoming reconciliation work. Do not rely on an in-memory mutex, process PID or age alone to prove a worker is dead. Bound lock-holding time by the drain's call/time budgets; no sleeping through long backoffs while holding the lock.

## Salesforce ownership and duplicate prevention agreement

SF-09 must supply a versioned handoff for the existing org covering:

- Actual object/field API names, unique External ID keyed by run UUID, field sizes/types, pipeline status mapping, supported projection revision protocol and machine-owned write allowlist. Org identity scopes local keys; never retarget queued work when configuration points at another org.
- Immutable completion key/first-result fields and mutable latest-result fields, with server-enforced stale/conflicting-write behavior. Mapping changes cannot create a second target record or alter historical retry bytes without an explicit migration.
- A Flow condition and durable notification receipt/claim that allow one completion notification per key. Repeated create/upsert/update processing, status changes on resume and Flow re-entry must not create another completion entitlement. AUTO-03 never writes or clears Flow-owned sent/claim flags.
- Demonstrated behavior if record commit succeeds but the client response is lost, and if Flow execution fails before/after its notification action. The SF-09 owner must establish the transaction/reconciliation semantics; a local “sent” flag or assumed Flow atomicity is insufficient.
- For an uncertain notification side effect, hold for remote reconciliation/operator resolution instead of blindly invoking the notification again. If the platform route cannot reconcile that uncertainty, document the delivery limitation and keep activation gated; do not promise exactly-once physical network delivery.
- Notification type, recipient selection, link to the summary record and notification-state visibility. AUTO-03 exposes a compact record and observes results; SF-09 owns remote notification retries/remediation. A Flow-only failure must not cause AUTO-03 to replay an acknowledged summary to force another alert.

Record uniqueness and alert uniqueness are separate acceptance checks. End-to-end acceptance requires both; a fake target can prove the local protocol only.

## Deferred implementation stories

### AUTO-03-S01 — Freeze completion and target contracts

**Status:** DEFERRED. **Depends on:** RUN-01, FND-01/DATA-01, SF-09 and SFCLIENT-01 agreements.

**Objective / inputs / outputs:** Turn persisted C15 and completion evidence into a versioned compact projection and explicit target acknowledgment contract.

**Tasks:**

1. Resolve the code gaps above with RUN-01; define admission/finalization, crash recovery, original timestamps, resume revisions and coverage evidence. Keep launch-only diagnostics separate.
2. Agree with SF-09 on fields, completion identity, write ownership, revision guards, Flow receipts and duplicate suppression. Mark absent capabilities as gates, not working defaults.
3. Define schemas, typed ports, canonical hashes, field bounds and synthetic fixtures for all four outcomes, interrupted runs, unchanged reruns and silent resume revisions.
4. Define a remote allowlist. Omit credentials, raw job text, candidate evidence, local absolute paths, stack traces and arbitrary `ClassifiedError.details`. Truncate only descriptive detail deterministically, with omitted counts/flags; never truncate IDs or critical numeric/status fields silently.

**Acceptance:** C15 1.0 fixtures still validate unchanged; projection fixtures preserve units and zero-versus-unavailable distinctions. A fallback `get_run()` value is rejected as completion evidence. Same run/different attempt yields the same completion key; a new run yields a different key. SF-09 contract gaps remain explicit activation blockers.

**Tests / impact:** T01–T04, T12. New companion schemas/mapping specification only; no remote deployment or channel selection by AUTO-03.

### AUTO-03-S02 — Persist delivery intent and completion recovery

**Status:** DEFERRED. **Depends on:** S01; RUN-01/DATA-01 finalization boundary; OPS-01 retention contract.

**Objective / inputs / outputs:** Convert committed completion receipts into durable, unique delivery work that survives process death.

**Tasks:**

1. Add an additive migration/repository with lane and revision uniqueness, immutable payload snapshots, attempt history, acknowledgments and durable retry budgets.
2. Wire minimal RUN-01 terminal handoff for normal, partial, controlled interruption and admitted failure paths. Repair admitted crashes through RUN-01 recovery; do not synthesize an alert directly from a running ledger row.
3. Implement atomic handoff or the explicit receipt-first bounded repair scanner. Recover intent after finalization/enqueue crashes without reexecuting acquisition, assessment or C12 sync.
4. Use the shared worker lock and restart-safe claims. Handle database/disk failure visibly without attempting an untracked remote send.
5. Protect unfinished state and deduplication identities through OPS-01 cleanup/backup/restore. Retain org binding and activation cutoff; default migration must not enqueue all historical runs.

**Acceptance:** Faults before/after each persistence boundary converge to one delivery lane and one completion entitlement. Restart and concurrent invocations do not duplicate intent or lose budgets. In-progress runs never alert. Missing outbox state can be repaired from retained receipts without changing C15. Backfilled historical delivery requires an explicit bounded selection and reconciliation.

**Tests / impact:** T03–T06, T10–T11, T14. Additive tables/indexes and backup inventory; disabling the feature preserves all receipts and existing pipeline behavior.

### AUTO-03-S03 — Deliver to the SF-09 summary target

**Status:** DEFERRED. **Depends on:** S01–S02; SFCLIENT-01, SF-09/SF-01/SF-02 readiness for live use.

**Objective / inputs / outputs:** Deliver a persisted projection to one remote summary record and retain verifiable acknowledgment.

**Tasks:**

1. Implement an injectable target adapter using existing typed gateway methods, protected credential references and expected-org verification. Validate target metadata, permissions and field sizes before enabling dispatch.
2. Upsert only the agreed machine-owned fields using the original run key. Persist `in_flight` intent before network I/O and save returned record/revision/hash evidence before marking delivered.
3. Keep uncertain mutation replay disabled at the gateway until the full SF-09 contract justifies it; let AUTO-03 reconcile first. Account for gateway-internal sends within the enclosing budget.
4. Read the target by key after ambiguous responses, lost local acknowledgments or restore. A matching acknowledgment resolves delivery without another write. A mismatched key/hash or unexpected newer revision is held for reconciliation/repair, never overwritten blindly.
5. Expose Flow receipt separately. Do not directly send alerts, reset sent markers or re-upsert to retrigger failed Flow execution.

**Acceptance:** A remote commit with a dropped response leaves one record and one completion alert after retry/restart. An acknowledged target record with failed/unknown Flow execution remains summary-delivered and notification-failed/unknown. All four outcomes produce appropriate projections, including successful emptiness. Candidate-owned fields remain untouched.

**Tests / impact:** T01–T02, T06–T09, T12–T13. Adds target mapping/settings and API usage; Salesforce object/Flow/permissions remain SF-09-owned, with live verification pending that handoff.

### AUTO-03-S04 — Bound retries and ambiguous-outcome recovery

**Status:** DEFERRED. **Depends on:** S02–S03; SFCLIENT-01 error/outcome contract.

**Objective / inputs / outputs:** Advance due delivery work to acknowledgment or an inspectable hold within finite persisted limits.

**Tasks:**

1. Persist dispatch and reconciliation counters separately, a maximum automatic recovery age and next due time. Configure finite attempt, query, batch, response-size and wall-time budgets. Every physical HTTP send, including token refresh and transport retry, must fit the enclosing invocation cap.
2. Retry definite transient/no-commit failures with capped exponential backoff/jitter and persisted UTC due times. Respect a server retry delay by deferring, not by retrying earlier to fit a local cap. Stop automatic work at attempt/age limits; never reset them on restart/config reload.
3. Route timeouts, connection loss after transmission and stale `in_flight` records to `reconcile_required`. Resolve by run key, completion key, revision and hash. Only an authoritative absence plus the SF-09 idempotency guarantees permits resending the same payload/key. Missing read permission, lookup timeout or incomplete query is not proof of absence.
4. Block invalid mapping/payload, org mismatch, permission failure and exhausted authentication recovery. Defer capacity/rate-limit/transient outages within finite policy; retain pending work on quota exhaustion. Preserve whether an exhausted operation might already have committed.
5. Offer a bounded manual reconciliation/retry operation after remediation. Preserve identity, lifetime counters and audit history; record any explicit additional retry allowance. Uncertain outcomes must reconcile before another mutation, even after manual reset.
6. Stop promptly at invocation limits and leave remaining work due. Use a fake clock for tests; do not install a daemon, scheduler or recursive failure-notification mechanism.

**Acceptance:** Offline operation terminates within bounds with durable `retry_wait`, `blocked` or `exhausted` state. Repeated invocations cannot evade lifetime limits. Recovery never turns an uncertain send into a new run/record/alert. Delivery failure does not alter C15 status, errors, pending pipeline work, counters or pipeline exit code.

**Tests / impact:** T06–T11, T14. Retry policy and drain limits become explicit configuration; no unbounded defaults or hidden network loop.

### AUTO-03-S05 — Inspection, configuration and activation evidence

**Status:** DEFERRED. **Depends on:** S01–S04; SF-09 live verification; OPS-01 and AUTO-01 interfaces as applicable.

**Objective / inputs / outputs:** Make pipeline, summary delivery and Flow state independently inspectable and provide a safe disabled-by-default rollout.

**Tasks:**

1. Add local text/JSON inspection by run ID and bounded pending/blocked listings: pipeline result, summary revision/delivery state, attempt totals, next due time, last safe error, remote record reference and observed notification status. Read-only inspection must never enqueue, refresh authentication or send.
2. Add a manually invoked bounded drain/reconcile boundary and explicit retry/backfill selection. A future AUTO-01 caller may invoke it; installing or changing tasks is outside AUTO-03.
3. Preserve RUN-01 exit behavior: successful pipeline plus unavailable Salesforce summary target still reports pipeline success, with delivery pending/blocked as a separate result. A delivery-only command has its own documented exit/result codes. Do not make launchers rerun a successful search because an alert failed.
4. Validate disabled-by-default settings, org binding, payload limits, recovery budgets and activation cutoff. Provide PowerShell instructions with absolute executable/config/data paths, spaces/non-ASCII path coverage and UTC storage/Europe/Berlin display.
5. Document rollback, backup reconciliation, manual remediation and observability when Salesforce itself is unavailable. Run the planned suites and record actual evidence by unit/fake/live/native-Windows category.

**Acceptance:** Users can distinguish “pipeline partial,” “summary awaiting delivery” and “Flow notification failed” without inspecting raw logs. Feature absence/disablement causes zero new summary network calls and no historical flood. A future handoff marks local implementation separately from live acceptance; G5 remains pending unrelated Phase 2 owners.

**Tests / impact:** T01–T14. New local configuration/runbook and companion report output; existing config remains valid and existing pipeline status semantics remain intact.

## Recovery and acceptance test matrix

All tests are **planned, not executed by this story-writing task**. Use synthetic records, temporary SQLite databases, injected time and a scripted SFCLIENT-01 transport. Count local intents, physical sends, remote records and Flow completion actions separately.

| ID | Scenario / fault | Required evidence |
|---|---|---|
| T01 | Success, truly empty success, duplicate-only success, zero eligible jobs | Correct status/text/units and source coverage; one completion per distinct run; no invented `empty` enum. |
| T02 | One failed source, quarantines, pending C12 work, all required work failed, admitted preflight failure | Partial/failed C15 preserved; concise actionable diagnosis; unavailable coverage explicit; one summary per admitted run. |
| T03 | Running ledger fallback, lock busy, no work due, pre-admission failure, killed admitted process | No false completion alert. RUN-01 recovery finalizes only the admitted abandoned run under lock; original UUID and evidence survive. |
| T04 | Repeated notification retries, same-run pipeline resume partial-to-success, new run with unchanged inputs | Same-run completion key never changes; latest revision updates silently; first-result snapshot retained; genuinely new run has its own entitlement. |
| T05 | Crash before/after completion commit, before/after intent commit and repair-scan cursor commit | No send without durable intent; one repaired intent; no missing terminal receipt after the agreed finalization boundary; no pipeline stage rerun for delivery. |
| T06 | Crash after claim/before send; server commit plus timeout; acknowledgment received then local commit crash | Restart reconciles ambiguous work; matching remote key/hash completes locally without another alert or unkeyed create. |
| T07 | Authoritative absent record versus lookup timeout/permission denial; hash conflict, duplicate lookup matches, newer remote revision | Resend only when proven safe; uncertain/conflicting cases held; stale local payload cannot regress remote latest result. |
| T08 | Offline network, 429 with long retry delay, transient 5xx, exhausted API/storage capacity, token failure | Bounded invocation and lifetime budgets; persisted due times survive restart; no tight loop, unlimited refresh or lost summary. |
| T09 | Repeated upserts, Flow re-entry, Flow failure before action and ambiguous failure after action | SF-09 fake contract plus later live evidence prove one completion entitlement; unknown action outcome held; no AUTO-03 reset/retrigger. Record success alone never passes this test. |
| T10 | Simultaneous manual/scheduled delivery, pipeline/generation lock owner, worker death | Existing lock excludes competing mutations; busy caller sends/writes nothing; next owner reconciles stale claims without resetting counts. |
| T11 | Retry/age/batch/time budget exhaustion, process restart, clock jump, manual repair allowance | Counters/deadlines remain durable; no early retry under clock skew; explicit bounded repair audit preserves original identity and uncertain outcome. |
| T12 | Overlong/malicious error strings, private paths/tokens in details, invalid schema/counts, missing companion data | Allowlisted bounded projection, deterministic truncation markers, no leaked evidence/secrets, no fabricated coverage or silent count coercion. |
| T13 | Wrong org/mapping/permissions, notification Flow disabled/failed, feature disabled/absent | Visible independent delivery/Flow state; zero unsafe writes; pipeline result/exit unchanged; no replay to force a Flow alert. |
| T14 | Old backup restored after remote delivery, cleanup, repeated migration, explicit bounded backfill; native Windows paths/credentials | Deduplication identity retained; remote reconciliation before replay; no replay of all history; correct lock/path behavior and execution identity. Remote receipt deletion is held as a repair case, not permission to notify again. |

Run targeted AUTO-03 contract/repository/service/adapter tests plus affected orchestration, storage, Salesforce and operations regressions. Test process-kill boundaries with separate native Windows processes, not only exception injection. A later authorized live check in the existing Developer Org must exercise SF-09 record/Flow behavior and verify notification counts using synthetic runs. No live calls or test alerts are part of this planning task. Record any untestable Flow uncertainty honestly as a remaining gate.

## Migration and configuration impact

Proposed configuration is a dedicated versioned summary-delivery settings file referenced from `AppConfig` (for example, `summary_delivery_settings_ref`); that key does not currently exist and must not be added to runtime files before implementation. Reuse `salesforce_settings_ref` for credentials/expected org. Keep summary target mapping distinct from job `sync_mapping_ref` and generation notification settings.

Required settings are explicit enablement, verified target/mapping contract version, activation cutoff, finite maximum dispatch/reconcile attempts and recovery age, capped backoff/jitter, per-invocation record/query/send/time limits, payload/detail bounds and diagnostic retention. Select numerical values with SFCLIENT-01/OPS-01 and actual org capacity during implementation; no unlimited or guessed production values are selected here. Channel/recipients and Flow retry policy are SF-09-owned. Existing `run.example.json` contains no AUTO-03 configuration.

Add tables without rewriting historical C15 or C12 records. Preserve original payloads, compact keys, acknowledgments and unresolved work even when verbose attempts expire. Coordinate remote receipt retention with SF-09: deleting the remote record/claim must not allow an old backup or backfill to recreate an already-notified completion. Restore starts in reconciliation/hold mode for previously exposed keys. Cross-org migration is explicit and never automatic.

Disabling delivery stops drains and new activation-scoped enqueueing without modifying pipeline outcomes or deleting state. Preserve committed completion receipts so a later explicit bounded catch-up can recover eligible runs. Rollback keeps the additive data and deduplication history readable; never truncate the outbox or reset remote notification flags. A configuration reload must not reset attempts, change queued org binding or silently reserialize an uncertain payload.

## Future handoff checklist

- [ ] Status remains deferred until a separate implementation request; record exactly which AUTO-03 stories were implemented later.
- [ ] RUN-01 admission/finalization gaps resolved with durable evidence, original IDs and explicit crash/resume semantics.
- [ ] SF-09 handoff obtained: actual fields, unique run key, revision guard, notification receipt/Flow semantics, permissions and ownership verified.
- [ ] Contract versions, schemas, migrations, owned files, projection units, truncation and compatibility decisions recorded.
- [ ] All four outcome examples and T01–T14 results recorded with commands/environment; pending checks clearly identified.
- [ ] Summary acknowledgment and notification confirmation distinguished; duplicate completion suppression verified beyond record uniqueness.
- [ ] Native Windows process/restart/credential/path verification separated from fake transport and live org evidence.
- [ ] Retry limits, repair procedure, activation cutoff, rollback, cleanup and restore reconciliation documented and tested.
- [ ] No changes to scheduling, automatic drafting, candidate workflow or application submission; next dependent owners are SF-09 for remote acceptance and AUTO-01 for optional invocation wiring.

Planning validation: inspected blueprint/repository instructions, RUN-01 handoff and current contracts/orchestration/storage/gateway code; checked for SF-09 handoff and recorded its absence. This change creates only this deferred story document. No implementation tests, migrations, pipeline runs, org writes or notifications were performed.
