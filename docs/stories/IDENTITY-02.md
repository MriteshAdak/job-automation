# IDENTITY-02 — Availability tracking

Status: **PLANNED** · Planning date: **28 October 2026** · Phase 0 · Scope: **IDENTITY-02 only**

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), v1.0. References use requirements (§2), contracts (§4), state/ownership rules (§5), component catalog (§6), integration gates (§7), working instructions (§8), and Windows conventions (§9). This is an ordered implementation plan, not an implementation handoff or evidence that the proposed tests passed.

## Objective and boundaries

Consume C04 fetch manifests, trustworthy source observations and IDENTITY-01 source mappings to maintain source-posting availability and the aggregate C07 canonical availability. Record last-seen evidence, apply configurable repeated-miss and grace rules only to comparable complete inventories, and recover safely after replay or interruption.

Direct requirements: **R04** (stable identities and alternate sources), **R08** (machine-owned availability independent of candidate-owned application progress), **R16** (auditability/recovery). Supporting requirements: **R02** (honest source coverage), **R03** (provenance), **R09** (durable compact state), **R14** (native Windows), **R15** (safe handling of external data).

Inputs → outputs: C03/frozen effective inventory scope + authoritative C04 + committed observation evidence + existing IDENTITY-01 mappings/membership versions + availability settings → durable source/scope observations and miss decisions, source availability, C07 availability/last-seen projections, and local inspectable change results for future consumers.

Excluded: identity matching, new canonical IDs, revision hashing, merge/split implementation, source fetching, normalization, eligibility assessment, Salesforce synchronization/outbox operations, Salesforce metadata, candidate status/notes/follow-ups, drafting, scheduling and retention cleanup. Narrow contract/storage and ingestion-boundary corrections below support this component; they do not authorize implementing whole prerequisite components. No Salesforce access is needed.

**Availability is not application progress.** `active`, `not_seen`, `unavailable`, and `unknown` are machine-owned posting states. `Applied`, `Interviewing`, `Rejected`, `Archived`, and other `ApplicationProgress` values belong to the candidate. An unavailable vacancy can still have an application in progress; a fresh sighting cannot reset that progress. Availability changes also do not change C11 eligibility dispositions.

## Repository instructions and dependency evidence

Read [README](../../README.md), blueprint §§8–9, and [schema instructions](../../schemas/README.md). No applicable `AGENTS.md` was found in the checked repository/ancestor directories; the user-level `.codex/AGENTS.md` is empty. Generate shared schemas from typed models; do not edit generated JSON manually. Repository/module paths below use `/`; executable PowerShell examples use Windows paths. All filenames described as proposed are future implementation work.

| Evidence read | Current state and planning consequence |
|---|---|
| [IDENTITY-01 stories](IDENTITY-01.md) | PLANNED; no `docs/components/IDENTITY-01.md` or production `identity/` package exists. Its proposed observation, membership epoch and merge-event APIs are dependencies, not shipped interfaces. Use explicit fixture mappings for isolated work; production integration must wait for its actual handoff. |
| [INGEST-02 handoff](../components/INGEST-02.md), normalization code | Now present and reports VERIFIED. The IDENTITY-01 story text saying normalization/handoff is absent is stale. Normalization derives C06 `observed_at` from draft `fetch_time`; it does not establish fresh inventory on its own. |
| [INGEST-01 handoff](../components/INGEST-01.md) | Reports VERIFIED, including native Windows and bounded live Arbeitnow smoke. It explicitly forbids disappearance inference from partial/failed/search/filtered results. Historical check results are not rerun or extended to IDENTITY-02 by this plan. |
| [SOURCE-01 handoff](../components/SOURCE-01.md), [inventory code](../../src/job_automation/sources/inventory.py) | `EffectiveSource.inventory_scope.scope_id` is `scope-v1:sha256:…`, derived from membership-affecting configuration. Transport/pagination changes are excluded. SOURCE-01 requires this scope to propagate into C04. |
| [manifest builder](../../src/job_automation/ingestion/manifests.py), [pagination](../../src/job_automation/ingestion/pagination.py), [controller](../../src/job_automation/ingestion/controller.py) | Currently construct scope as `provider_board`, including failure paths and checkpoints. This disagrees with SOURCE-01 and loses endpoint/filter distinctions. Treat this as an upstream correctness blocker for negative evidence, not proof that scopes are comparable. |
| [C04/C05/C06](../../src/job_automation/contracts/postings.py), [ingestion models](../../src/job_automation/ingestion/models.py) | C04 stores bare provider posting IDs and manifest start/end times, but no provider/board snapshot, per-ID capture times, cache provenance or finality/version marker. `PageReceipt` has cache/time fields; a receipt's processing time must not replace original capture time on cache reuse. |
| [page persistence](../../src/job_automation/ingestion/persistence.py), [replay tests](../../tests/ingestion/test_observation_replay.py) | `commit_page` accepts a receipt but persists raw rows/checkpoint, not the full receipt. Raw rows are unique per source tuple; repeated or changed sightings do not give a durable per-sighting timeline there. Checkpoints retain cumulative IDs/references but not all prior receipt issues/cache flags. Restart-safe evidence needs an explicit boundary design. |
| [manifest finalization test](../../tests/ingestion/test_manifest_finalization.py) | The same `(run_id, source_key, scope_id)` row can change from partial to complete. A boolean “processed manifest” marker would either lose completion or count multiple misses. Resume must preserve evidence from every segment before complete is trusted. |
| [C07](../../src/job_automation/contracts/identity.py), [enums](../../src/job_automation/contracts/enums.py), [canonical repository](../../src/job_automation/storage/repositories/canonical_jobs.py) | C07 has canonical/revision availability and first/last seen, defaults availability to active, and lacks source/scope miss state. SQL and JSON duplicate these projections. `find_by_source_key` uses a revision join with `LIMIT 1`, not an authoritative unique mapping. Do not use it to adjudicate ownership. |
| [DATA-01 handoff](../components/DATA-01.md), [migrations](../../src/job_automation/storage/migrations.py), [connection](../../src/job_automation/storage/connection.py) | Current migrations are 1–3; allocate the next version after IDENTITY-01 lands. A composable transaction helper exists, but canonical save methods use direct connection contexts and rewrite revisions. Provide a narrow atomic availability update rather than invoking a broad save that can overwrite identity data. |
| [configuration](../../src/job_automation/configuration.py), [schema base](../../src/job_automation/contracts/base.py), [pyproject](../../pyproject.toml) | No availability settings exist. Contracts default to schema 1.0 and forbid extra fields. Additive fields still need an old-reader/version plan. Dependencies are ranges, despite older README language about pins. |

## Required invariants and proposed technical policy

The blueprint requires conservative completeness handling and configurable rules; it does not prescribe numeric thresholds, the grace anchor, or mixed-unknown aggregation. The following are **proposed engineering defaults**, to freeze in S01 with fixture evidence, not user-confirmed preferences.

### Identity, scope and time

- A source posting is the exact `(provider, board_id, source_posting_id)` tuple plus IDENTITY-01's reviewed assignment epoch where applicable. Registry `source_key`, inventory `scope_id`, canonical UUID and content hash are different identifiers. Preserve leading zeros/case and avoid delimiter-based tuple encoding.
- A negative-evidence stream is scoped to the frozen inventory fingerprint, provider/board and source configuration binding. It includes only postings with an established sighting/baseline in that same inventory and assignment epoch. A new scope does not inherit old miss counts or assume old postings belong to it.
- Use the scope snapshot from execution, never today's edited registry to reinterpret historical manifests. Endpoint, board, filter, inventory-semantics or scope-algorithm changes start a new baseline unless an explicit audited compatibility decision exists. Timeout/retry/cursor changes alone do not.
- `last_seen_at` is the maximum trustworthy original capture/observation time, not manifest processing time or current wall clock. Store scope-specific observations as well as source and canonical maxima. First seen remains the earliest known observation. Source publication/deadline dates are unrelated.
- Historical/cached evidence remains auditable at its original time. It cannot fabricate a fresh sighting, reset a later miss streak, or reopen a job made unavailable by newer evidence. Quarantined content does not imply absence when its source identity was reliably observed. Held/recycled-ID conflicts must not reactivate the wrong assignment.

### Manifest decision matrix

| Input | Positive observations | Negative evidence / miss counter |
|---|---|---|
| Authoritative COMPLETE + verified COMPLETE_BOARD + exact compatible scope | Apply validated fresh sightings | One miss per absent eligible source posting per logical inventory, subject to baseline and chronological checks |
| COMPLETE SEARCH_RESULTS or FILTERED_FEED | Apply validated fresh sightings | None, including empty results |
| PARTIAL (limits, errors, cache, incomplete traversal) | Apply individually validated fresh sightings; cached entries retain old times | None; no counter increment or grace-only closure |
| FAILED | No inferred sightings from failure metadata; independently committed valid observations can be consumed separately | None |
| Disabled/unselected/unconfigured source; no manifest | None | None; downtime is not closure |
| Missing/mismatched scope snapshot, invalid chronology, contradictory COMPLETE metadata, uncertain resume provenance | Retain inspectable input; use only independently verified positives | Block negative evidence and report a reason |

An empty complete board is meaningful only after the same evidence checks as a nonempty board. A successful global run is not a substitute for per-source C04 evidence, and failure of source B must not invalidate a valid complete inventory from source A.

### Repeated misses, grace, reopening and canonical aggregation

Proposed settings: `consecutive_complete_misses = 3` and `grace_seconds = 172800` (48 hours), configurable globally with exact source/scope overrides. These values are examples/default proposals, not established user preferences. Require an integer threshold at least 2 (reject booleans), finite nonnegative grace, known override targets and a settings version/fingerprint. Do not put availability rules in candidate C02 search criteria or HTTP request policy.

For a source posting, first qualifying absence sets `not_seen`, `miss_count = 1`, and `missing_since` to that inventory's recorded completion time. Subsequent qualifying inventories increment once each. Transition to `unavailable` only when **both** the threshold is met **and** `inventory_end - missing_since >= grace_seconds`. Evaluate closure only while applying new qualifying negative evidence; time passing, a partial run, or changing settings alone cannot close a job. A newer trustworthy positive sighting resets the streak/anchor and makes that source active. Irrelevant/failed/partial runs without a sighting neither increment nor reset the streak. Zero grace still requires repeated misses.

Freeze the effective settings version for a miss streak. A configuration edit applies to the next streak after a fresh positive baseline; it must not retroactively close jobs. An explicit future policy-recalculation feature is outside this plan. Retain the chosen settings with every decision so this behavior is reproducible.

Proposed aggregate rule over **current effective source memberships**, independent of display/current revision selection:

1. Any source `active` → canonical `active`.
2. Otherwise any source `not_seen` → canonical `not_seen`.
3. Otherwise any source `unknown`, unresolved membership evidence, or no sources → canonical `unknown`.
4. Only when all participating sources are `unavailable` → canonical `unavailable`.

Thus unavailable + unknown does not prove canonical closure; unavailable + active remains active. Disabling/removing configuration does not discard a linked active/unknown source to manufacture closure. No automatic age-based expiry is proposed for search/manual sightings; retain observation age for inspection and record this limitation. Historical source associations remain auditable but are not counted as current memberships after an IDENTITY-01 reassignment. Merge/reversal events trigger recomputation, never matching or source-state copying between opportunities.

## Ordered implementation stories

All stories are IDENTITY-02. Shared-file ownership is limited to the coordinated changes stated below. Production dependency acceptance stays pending where only fakes are available.

| Order | Story | Dependencies | Deliverable |
|---|---|---|---|
| 1 | IDENTITY-02-S01 | FND-01/DATA-01; IDENTITY-01 boundary; INGEST-01/SOURCE-01 | Frozen availability contracts, settings and evidence policy |
| 2 | IDENTITY-02-S02 | S01; coordinated INGEST-01/SOURCE-01 fixes | Comparable, durable manifest/observation input boundary |
| 3 | IDENTITY-02-S03 | S01–S02; actual IDENTITY-01 storage contract | Availability ledger, migration and atomic projection APIs |
| 4 | IDENTITY-02-S04 | S02–S03 | Last-seen ingestion, baseline enrollment and positive reopening |
| 5 | IDENTITY-02-S05 | S01–S04 | Repeated-miss/grace state machine |
| 6 | IDENTITY-02-S06 | S03–S05; IDENTITY-01 memberships/events | Canonical multi-source aggregation and protected-state boundary |
| 7 | IDENTITY-02-S07 | S02–S06 | Replay/recovery service and inspectable local handoff |
| 8 | IDENTITY-02-S08 | S01–S07; real upstream interfaces | Integration, native Windows verification and component handoff |

### IDENTITY-02-S01 — Freeze evidence, availability and configuration contracts

**Objective/references.** Establish one explicit interpretation before business logic. R04/R08/R16, supporting R02/R14; C03/C04/C05/C06/C07, `PostingAvailability`; blueprint §§4–6 and 8.

**Dependencies.** Read the actual IDENTITY-01 handoff when it exists and freeze its source mapping, observation and membership-event signatures. Reuse FND-01 enums and DATA-01 infrastructure. No prerequisite implementation is implied by this story.

**Owned files.** Proposed `src/job_automation/identity/availability/{__init__,models,ports,settings,errors}.py`, `tests/identity/availability/test_contract_boundary.py`, `test_settings.py`, `config/availability.example.json`. Coordinated `configuration.py`, `config/app.example.json`, shared contract/exporter files and their generated schemas/fixtures only as required by the recorded version decision.

**Inputs → outputs.** Existing contracts and policy proposals → versioned settings, observation/inventory evidence envelopes, source-state/decision/change-result records, reader/writer protocols and compatibility plan.

**Tasks.**

1. Freeze the matrix, streak/grace semantics, timestamp ordering, source-state aggregation and settings precedence above. Separate schema version, policy version, scope algorithm and membership epoch.
2. Define a typed evidence envelope linking the C04 logical key and content fingerprint to frozen provider/board/scope metadata, capture identity/time, cache status, authoritative finality and membership version. Reuse durable upstream evidence rather than adding a competing truth store.
3. Define validated source and canonical change results with before/after state, reason, evidence references and decision time. Include ignored/blocked/pending outcomes without fabricated transitions. Keep counts explicitly source postings versus canonical jobs.
4. Decide C07 revision availability semantics with IDENTITY-01: recommended live availability lives in source state and canonical projection; preserve immutable revision evidence and avoid rewriting historical revisions. If an existing revision field is a compatibility projection, document exactly how it is read/updated and version that behavior.
5. Require explicit unknown initialization for evidence-free new source state; never treat C07's current active default as observed evidence. Preserve legacy values as labeled legacy projections until a documented reconciliation path applies.
6. Add a config-relative `availability_policy_ref` or equivalent typed app setting, following existing path resolution. Validate values and overrides before writes; retain resolved settings with decisions. No new service/dependency is required.
7. Record old/new readers, schema fixture changes and migration strategy. `extra='forbid'` means an added field is not automatically backward compatible. Close blocking D01–D04 below before dependent code ships.

**Acceptance examples.** Threshold `true`, threshold 1, negative/infinite grace, unknown override and unsupported policy version fail clearly without database changes. Availability output has no application-status or eligibility fields. Legacy C07 deserializes through the agreed path without turning its default into a fresh sighting.

**Tests/native Windows.** Model/enum/version validation, precedence, relative configuration under a Unicode path from another CWD, deterministic settings fingerprint and old/new fixture compatibility.

**Migration/configuration/handoff.** Freeze contracts and proposed defaults, publish callable signatures and schema/version decisions. Schema changes are generated during implementation, not manually edited.

### IDENTITY-02-S02 — Establish trustworthy scope and durable observation inputs

**Objective/references.** Prevent changed scopes, cached pages or resumed errors from becoming closure evidence. R02/R04/R16, supporting R03/R09; C03–C06; SOURCE-01 scope contract and INGEST-01 handoff §6.

**Dependencies.** S01. Coordinate prerequisite-owned boundary corrections with INGEST-01/SOURCE-01; isolated availability fixtures can proceed while actual ingestion acceptance remains pending.

**Owned files.** Proposed `identity/availability/evidence.py`, `tests/identity/availability/{test_scope_boundary,test_manifest_evidence}.py`. Narrow coordinated changes, if not already fixed upstream: `ingestion/{manifests,pagination,controller,models,persistence}.py`, affected cache/checkpoint key handling, and `tests/ingestion/{test_manifests,test_resume,test_cache_completeness,test_manifest_finalization}.py`. SOURCE-01's scope algorithm is reused, not reimplemented.

**Inputs → outputs.** Effective source snapshot, C04 and committed pages/observations → verified positive evidence and eligible/blocked inventory decisions with durable provenance.

**Tasks.**

1. Propagate the exact effective fingerprint through success/failure manifests, receipts, checkpoints, continuations and cache keys. Assert provider/board/semantics agreement. Persist the execution snapshot or a durable immutable reference to it.
2. Never translate historical `provider_board` IDs using today's registry. Legacy scopes remain ineligible for misses unless their original settings can be proved and an audited migration resolves them. Otherwise establish a fresh scoped baseline.
3. Agree and implement the minimum durable upstream observation/receipt representation: exact source tuple, original capture time/reference, cache/freshness and traversal identity. Recover all resume-prefix blocking issues, cache flags and chronology; current cumulative IDs alone are insufficient. Do not assume the existing raw tuple row or receipt timestamp gives the latest live observation.
4. Freeze finalization rules for partial → complete. Completion must prove a committed traversal from its beginning through terminal exhaustion without missing prefixes, cache reuse or blocking errors. Detect contradictory error/cursor/time/scope data and withhold negative evidence.
5. Join each bare manifest ID to the frozen provider/board before mapping it. Deduplicate IDs without losing exact strings. Unknown IDs remain pending IDENTITY-01 work; this component must not allocate identities. A known trustworthy observation can survive mapping/normalization failure, but an identity conflict remains held.
6. Make consumption independent of today's enabled-source selection. Missing historical evidence produces a visible blocked input, not a guessed empty inventory.

**Acceptance examples.** Changing Berlin to Munich filters with the same provider/board cannot reuse miss history. Timeout changes preserve scope. Cached page 1 followed by fresh terminal page 2 after restart cannot produce trusted complete evidence. `001` from two boards remains two source postings. An empty complete search feed causes zero misses.

**Tests/native Windows.** Real SOURCE-01 → INGEST-01 boundary fixtures, failure paths, malformed complete claims, old scopes, changed configuration, mixed cached/fresh pages, and multi-process resumed-prefix validation.

**Migration/configuration/handoff.** Document checkpoint/cache invalidation for old scope encoding and legacy evidence limitations. Preserve old manifests, do not rewrite applied migrations. Publish coordinated upstream changes and pending integration explicitly.

### IDENTITY-02-S03 — Persist source state, decisions and atomic projections

**Objective/references.** Retain enough compact evidence to explain and safely replay every transition. R04/R09/R16; C04/C07; blueprint §5 persistence rules.

**Dependencies.** S01–S02 and the actual IDENTITY-01 authoritative source/membership store. Fakes prove repository isolation only.

**Owned files.** Proposed `storage/repositories/availability.py`, minimal `storage/{migrations,engine}.py` and repository export changes, narrow `canonical_jobs.py` update API; `tests/identity/availability/{test_repository,test_migrations,test_transactions}.py`.

**Inputs → outputs.** Existing database plus typed evidence/state → durable observation references, scoped baselines/streaks, manifest consumption versions, source projections, canonical decisions and pending reconciliation records.

**Tasks.**

1. Allocate the next forward migration after prerequisites; preserve existing canonical/revision UUIDs, source associations and downstream foreign keys. No schema version number is reserved by this plan.
2. Persist unique logical inventory identity, evidence fingerprint/finality, per-source decision uniqueness, assignment epoch, scope baseline, last seen, missing-since/count, settings version and current availability. Keep an append-only decision/evidence history.
3. Enforce one miss per qualifying logical inventory per source/epoch, regardless of pages, retries, replay calls or registry aliases of the same inventory. Alias executions in one run must not multiply misses; S01/S02 define the authoritative inventory key.
4. Add narrow updates that keep C07 SQL and JSON availability/last-seen consistent while preserving revision content, company mappings, URLs and unrelated fields. Use one composable transaction for consumption markers, counters, source and canonical projections, audit and local change records.
5. Backfill only provable observations/baselines. Preserve legacy timestamps/state with provenance labels; never invent past misses, capture times, grace anchors or scope membership. Ambiguous legacy data becomes an inspectable migration issue.

**Acceptance examples.** Replaying one inventory leaves one decision/count increment. A fault after counter update rolls back its marker and canonical update. Migration preserves seeded assessments, sync rows, generation requests and artifacts. Reopening the database returns the same JSON and SQL state.

**Tests/native Windows.** Populated database upgrade, rollback/fault injection, unique/FK constraints, two-connection stale-version checks and handle release on Unicode/spaced paths.

**Migration/configuration/handoff.** Record final tables/indexes/version, backfill limitations and atomic boundary. Compact decision records must be protected by future OPS-01 retention; implementing cleanup is excluded.

### IDENTITY-02-S04 — Record sightings and reopen only from newer evidence

**Objective/references.** Maintain truthful first/last-seen observations independently of content revisions or successful full fetches. R04/R16, supporting R03; C04–C07; blueprint §§4–5.

**Dependencies.** S02 evidence and S03 persistence; IDENTITY-01 source/epoch mapping and observation ownership.

**Owned files.** Proposed `identity/availability/observations.py`, repository extensions, `tests/identity/availability/{test_observations,test_reopening,test_baselines}.py` and timestamp/cache/quarantine fixtures.

**Inputs → outputs.** Trusted mapped observations → idempotent source/scope sightings, monotonic last-seen projections, scoped baseline enrollment, active/reset decisions and affected canonical IDs.

**Tasks.**

1. Reuse IDENTITY-01 observation references; do not emit content revisions for repeated sightings. Update earliest/latest known times using original UTC event times, never ingestion/replay wall clock.
2. Apply fresh positives from complete, partial, search and filtered inventories. Independently committed positives from an ultimately failed traversal can count only through the verified observation boundary, not by assuming every FAILED manifest ID is fresh.
3. Enroll a posting in a new scope only with provable membership/sighting in that scope. Do not enroll all canonical jobs in every board's missing set. A positive in another scope can establish that the exact source posting is active and invalidate older negative streaks, but cannot establish absence coverage in that other scope.
4. Reset counters/anchor on a newer positive and reopen unavailable sources. Cached or delayed positives older than the decision timeline cannot reopen or erase later misses. Duplicate observation delivery is a no-op; conflicting capture metadata is inspectable.
5. For held source-ID reuse, retain evidence pending identity review and suppress absence for the visibly present opaque ID without assigning it to the wrong opportunity. Unknown IDs wait for mapping; resolve them later using historical membership/epoch evidence.

**Acceptance examples.** An unchanged post seen on 28 October advances last seen without a revision. Replaying a 25 October cache on 29 October does not reopen a posting closed on 28 October. A fresh partial-run observation does reopen it. A malformed title with a verified existing source ID is not treated as disappearance.

**Tests/native Windows.** Out-of-order and duplicate observations, mixed fresh/cache receipts, normalization quarantine, held assignments, leading-zero IDs, UTC offset normalization and DST boundary fixtures. No real sleeps.

**Migration/configuration/handoff.** Use S03 state; no new user settings. Document exactly which IDENTITY-01 versus IDENTITY-02 writer owns each timestamp projection to avoid competing updates.

### IDENTITY-02-S05 — Apply repeated-miss and grace rules to comparable inventories

**Objective/references.** Infer disappearance conservatively and reproducibly. R04/R08/R16; C03/C04/C07; blueprint §6 IDENTITY-02 and §5 availability rules.

**Dependencies.** S01 settings, S02 evidence eligibility, S03 state and S04 positives/baselines. Process positives before absence decisions for the same logical inventory.

**Owned files.** Proposed `identity/availability/rules.py`, `tests/identity/availability/{test_miss_rules,test_grace,test_manifest_matrix,test_policy_changes}.py`, synthetic timeline fixtures.

**Inputs → outputs.** Verified complete-board inventory + scoped baseline/state + frozen settings → unchanged/not-seen/unavailable source decisions with exact supporting inventory IDs and reasons.

**Tasks.**

1. Implement the decision matrix and conjunction of threshold plus grace. Deduplicate logical inventories, not pages/attempts. Count only comparable complete negative observations since the last newer positive.
2. Treat incomplete/failed/search/filtered/disabled/unselected inputs as no negative evidence even if the grace period has elapsed. Preserve existing state/count/anchor unless a verified positive resets them.
3. Exclude postings first seen after inventory start from its absence set. Reject ambiguous overlapping/out-of-order negative inventories for pending ordered reconciliation; an older completion cannot override a newer sighting. Use explicit event ordering and deterministic tie handling from S01.
4. Keep miss histories separate across scopes and assignment epochs. Never add two different scopes' counts to reach a threshold. Define one authoritative comparable stream per posting for disappearance; contradictory/newer positive evidence takes precedence.
5. Apply the frozen per-streak policy. Expose its version and next unmet condition for inspection without inventing a vacancy deadline. No wall-clock timer or background job is added.

**Acceptance examples.** With threshold 3/grace 48 hours: sighting at 28 October 08:00Z; misses at 29 October 08:00Z and 30 October 08:00Z yield `not_seen`; the third at 31 October 08:00Z yields `unavailable`. Three misses within one hour remain `not_seen`; a later qualifying miss after 48 hours permits closure. One miss followed by a month of failures does not close. A fresh sighting starts the next streak from zero.

**Tests/native Windows.** Exhaustive outcome × inventory-semantics matrix; exact grace boundary, zero grace, threshold boundary, repeated empty complete boards, interrupted streaks, policy changes, duplicate aliases, changed scopes, positive-after-inventory-start and clock skew. Inject event times; compare UTC durations across Berlin DST changes.

**Migration/configuration/handoff.** No additional schema change expected. Record accepted settings, reason codes and counter units with transition-table evidence.

### IDENTITY-02-S06 — Aggregate canonical availability without changing candidate state

**Objective/references.** Keep a canonical vacancy active while any current source remains active. R04/R08/R16; C07; blueprint §5 ownership and alternate-source rule.

**Dependencies.** S03–S05 and IDENTITY-01 current effective memberships plus merge/reversal/reassignment events.

**Owned files.** Proposed `identity/availability/aggregate.py`, narrow projection repository calls, `tests/identity/availability/{test_multi_source,test_membership_changes,test_protected_state}.py`.

**Inputs → outputs.** Current source states + versioned identity membership → deterministic C07 availability and last-seen projection, explanation and local change result.

**Tasks.**

1. Implement S01's aggregation precedence. Read every current source membership, not only the source of `current_revision_id`. Preserve alternate URLs/revisions and original canonical UUIDs.
2. Recompute affected canonical groups after identity merge/reversal; use originating source/epoch evidence to restore separate projections. Do not duplicate counters or inherit the survivor's availability into another source. Stale membership versions require retry/reconciliation before a projection write.
3. Define canonical first/last seen as the min/max trustworthy observations over effective membership, preserving original per-canonical/source audit history. Reversal can change an aggregate maximum by removing a membership; this is a labeled membership recomputation, not timestamp loss.
4. Keep source disable/removal, rejected eligibility and candidate application progress out of aggregate rules. Emit local machine-owned deltas only. Do not enqueue C12, modify sync sequencing, or access Salesforce.
5. Prove C11 results, C12 rows, C13/C14 frozen references, identity decisions, notes/follow-up backups and candidate-owned values remain unchanged wherever those records exist. Use explicit fake consumer sentinels where candidate-state persistence is not implemented.

**Acceptance examples.** A unavailable + B active → active, even if A supplied the display revision. A unavailable + B unknown → unknown. A unavailable + B not_seen → not_seen. All current sources unavailable → unavailable. Reappearance at either source → active. Merge then reverse jobs with different source states restores appropriate availability and leaves an `Interviewing` application untouched.

**Tests/native Windows.** Permutations/order independence of source sets, no sources, stale membership versions, disabled sources, two postings on one provider, separate providers with equal IDs, merge/reversal replay and protected-record snapshots with real SQLite.

**Migration/configuration/handoff.** Reuse authoritative membership events, no new merge implementation. Document C07 compatibility projection behavior and downstream local change shape; SYNC-01 owns eventual external publication.

### IDENTITY-02-S07 — Compose idempotent application, recovery and inspection

**Objective/references.** Provide one recoverable local service boundary for future RUN-01. R04/R09/R16, supporting R15; C04/C07 and future C15 count consumers; blueprint §§5, 7–8.

**Dependencies.** S02–S06. RUN-01/SYNC-01 are consumers, not components to implement here.

**Owned files.** Proposed `identity/availability/{service,inspection}.py`, public exports and `tests/identity/availability/{test_service,test_replay,test_recovery,test_safe_diagnostics}.py`.

**Inputs → outputs.** Durable evidence identity/version + expected membership version → atomic decisions/projections and inspectable applied/no-op/blocked/pending result with source/canonical counts.

**Tasks.**

1. Compose evidence validation, positive ingestion, scoped miss evaluation and canonical aggregation within the agreed atomic boundary. A crash before commit leaves no consumption marker; retry after commit returns the recorded outcome without new counters/events.
2. Separate positive-observation deduplication from inventory negative-decision deduplication. Partial → complete can add one valid miss decision after completion; replaying either version cannot add another. Resume does not count as another inventory/run.
3. Snapshot authoritative manifest content/finality on consumption. A changed already-consumed COMPLETE inventory is a conflict: record it and block further negative processing for affected streams until a deterministic reconciliation/rebuild from retained evidence is performed. Never silently apply a second miss or erase the conflict.
4. Define and test bounded local reconciliation for late evidence and changed membership: replay the retained ordered evidence with its recorded policy versions and replace projections atomically, retaining superseded decisions. If evidence is insufficient, keep a visible pending state and do not guess closure. No generic scheduler/retry framework is added.
5. Expose a read-only Python inspection API showing last positive evidence, inventory eligibility, miss count/anchor, policy, source states and canonical explanation. Include safe reason codes and pending work for RUN-01; do not log raw job text, credentials or sensitive URL parameters.

**Acceptance examples.** Partial R1 → complete R1 → repeated complete R1 yields at most one miss. A process killed after commit returns the same change ID on restart. Applying an old inventory after a newer sighting cannot close the job. Mutating a consumed complete manifest becomes an inspectable reconciliation case rather than another miss.

**Tests/native Windows.** Fault injection before/after each durable boundary, separate-process restart, stale-write conflicts, deterministic reconciliation with late positives/negatives, blocked legacy inputs and diagnostic redaction. Preserve INGEST-01 source-failure isolation.

**Migration/configuration/handoff.** Reuse S03 ledger or add an explicit forward migration if reconciliation needs additional state. Publish service/inspection examples; no invented current availability CLI or Salesforce operation.

### IDENTITY-02-S08 — Verify integration on native Windows and publish the handoff

**Objective/references.** Demonstrate the component's catalog acceptance and record dependency limits honestly. R04/R08/R16/R14; C03–C07; blueprint §§6–9.

**Dependencies.** S01–S07, actual IDENTITY-01 handoff/code and corrected INGEST-01 evidence boundary. Fixture-only success cannot close those integration dependencies.

**Owned files.** `tests/identity/availability/{test_integration,test_windows_paths,test_windows_restart}.py`, `tests/fixtures/identity/availability/README.md` and synthetic scenarios, future `docs/components/IDENTITY-02.md`, minimal README usage documentation.

**Inputs → outputs.** Implemented service/contracts/migrations → recorded offline integration and native Windows evidence, limitations and handoff for RUN-01/SYNC-01/GEN-02/OPS-01.

**Tasks.**

1. Exercise production source-scope validation, fetch controller with scripted adapters, normalizer and actual identity resolver into availability: two linked sources, repeated unchanged sightings, partial/failed/empty search runs, complete-board misses, reappearance, changed scope, cache/resume, merge/reversal and process restart.
2. Verify every acceptance example above and preservation of candidate progress using seeded local records or clearly labeled fake consumers. No remote state is read or changed; this does not verify Salesforce synchronization.
3. Run focused tests, affected contract/storage/source/ingestion/configuration checks and one full regression. Record actual commands, exit codes, Python/dependency/SQLite/platform versions and fixture provenance, not historical test counts.
4. Demonstrate migration from a populated pre-availability database, unchanged old references, SQL/JSON projection consistency and restart without relying on in-memory receipts.
5. Publish status using blueprint definitions: implemented if code exists with required checks pending; verified only if declared component acceptance is demonstrated. Separate unit, fake adapter, real local upstream, SQLite/restart, Windows and live service status. No G1 or full-pipeline completion claim.

**Acceptance examples.** The handoff proves incomplete/failed/search-only runs never close jobs; one active source keeps the canonical vacancy active; repeated comparable complete misses plus grace can close and newer positives reopen. All changes are traceable and candidate state stays unchanged.

**Tests/native Windows.** Run the recipe below after its proposed tests exist. Test actual Windows process termination/reopen and file-handle release, not only mocked paths.

**Migration/configuration/handoff.** Record final policy/schema/migration/scope versions, owned/coordinated files, baseline/backfill limitations, all decision resolutions and exact consumer interfaces. Live provider access is unnecessary for deterministic availability acceptance; external verification remains separately labeled.

## Native Windows verification recipe for implementation

These are **future checks**, not commands executed during story planning. Start in the repository root in native PowerShell; use the existing environment and absolute paths before changing CWD. Runtime data uses a unique external temporary directory. Do not install paid services, require WSL, or use production data.

```powershell
$identity02Repo = (Resolve-Path '.').Path
$identity02Python = Join-Path $identity02Repo '.venv\Scripts\python.exe'
$identity02Config = Join-Path $identity02Repo 'config\app.example.json'
$identity02Tests = Join-Path $identity02Repo 'tests\identity\availability'
$identity02Temp = Join-Path $env:TEMP ('Job Automation Verfügbarkeit Prüfung ' + [guid]::NewGuid().ToString())
$identity02Data = Join-Path $identity02Temp 'Daten Größe'

& $identity02Python -c "import platform, sys, sqlite3; from zoneinfo import ZoneInfo; print(platform.platform()); print(sys.version); print(sqlite3.sqlite_version); print(ZoneInfo('Europe/Berlin'))"
$identity02EnvironmentExit = $LASTEXITCODE
& $identity02Python -m pip show pydantic pytest tzdata
$identity02VersionsExit = $LASTEXITCODE
& $identity02Python -m pytest $identity02Tests
$identity02FocusedExit = $LASTEXITCODE
& $identity02Python -m pytest (Join-Path $identity02Repo 'tests\contracts') (Join-Path $identity02Repo 'tests\storage') (Join-Path $identity02Repo 'tests\sources') (Join-Path $identity02Repo 'tests\ingestion') (Join-Path $identity02Repo 'tests\test_configuration.py') (Join-Path $identity02Repo 'tests\test_cli_storage.py')
$identity02BoundaryExit = $LASTEXITCODE

New-Item -ItemType Directory -Path $identity02Temp | Out-Null
Push-Location $identity02Temp
try {
    & $identity02Python -m job_automation storage migrate --config $identity02Config --data-root $identity02Data
    $identity02MigrationExit = $LASTEXITCODE
    & $identity02Python -m job_automation storage status --config $identity02Config --data-root $identity02Data
    $identity02StatusExit = $LASTEXITCODE
    & $identity02Python -m pytest (Join-Path $identity02Tests 'test_windows_paths.py') (Join-Path $identity02Tests 'test_windows_restart.py') --basetemp (Join-Path $identity02Temp 'Test Daten ä')
    $identity02WindowsExit = $LASTEXITCODE
} finally {
    Pop-Location
}

& $identity02Python -m pytest (Join-Path $identity02Repo 'tests')
$identity02RegressionExit = $LASTEXITCODE
[pscustomobject]@{
    EnvironmentExit = $identity02EnvironmentExit
    VersionsExit = $identity02VersionsExit
    FocusedExit = $identity02FocusedExit
    BoundaryExit = $identity02BoundaryExit
    MigrationExit = $identity02MigrationExit
    StatusExit = $identity02StatusExit
    WindowsExit = $identity02WindowsExit
    RegressionExit = $identity02RegressionExit
}
```

Require zero exit codes and record failures, not just command invocation. Windows tests use `pathlib.Path`, explicit configuration bases, and `sys.executable` for child processes. Include checkout/config/data paths with spaces and non-ASCII characters, different CWD, UTC/DST fixtures, database migration/reopen, termination before/after commit and released SQLite/file handles. The acceptance fixture drives the service directly; no current availability CLI is assumed. If shared models change, run the existing schema exporter during implementation and review generated changes against S01's version decision.

## Unresolved decisions and closure owners

These are bounded implementation/dependency decisions, not an automatic request for user approval. Close blocking representation choices before dependent stories; continue independent fixture work where an upstream component is missing.

| ID | Decision/gap | Owner and closure evidence |
|---|---|---|
| D01 | IDENTITY-01 is planned; exact mappings, observation ownership, assignment epochs and membership events are not shipped | IDENTITY-01 + S01/S03/S06. Read its actual handoff, bind to real interfaces, prove held/recycled-ID and merge/reversal cases. Do not implement matching here. |
| D02 | Ingestion uses `provider_board` instead of the validated fingerprint | INGEST-01/SOURCE-01 + S02. Correct all relevant paths and prove scope continuity/change tests. Old scopes without original evidence remain ineligible for negative inference. |
| D03 | C04 lacks durable capture/scope/finality detail; receipts and resume-prefix safety metadata are not fully persisted | INGEST-01/DATA-01/FND-01 + S01–S03. Choose durable sidecar versus versioned contract additions; demonstrate original-time cache handling and restart-safe prefix validation. Negative inference stays blocked on insufficient evidence. |
| D04 | Source-state versus C07 revision availability; legacy default-active records | FND-01/IDENTITY-01 + S01/S03. Freeze live/historical semantics, explicit initialization and migration/consumer behavior. Do not rewrite immutable revision evidence or silently reinterpret legacy active as proven live. |
| D05 | Threshold/grace/defaults, overrides and policy edits | S01/S05. Proposed 3 misses AND 48 hours from first miss, per-streak frozen settings; document final values and boundary tests as engineering choices. |
| D06 | Multiple configurations/scopes for one board, alias duplicate inventories and source rename | SOURCE-01/INGEST-01 + S01/S02/S05. Define authoritative comparable inventory identity, scope baseline enrollment and alias deduplication. Never combine unrelated scope misses; registry rename alone is not new source identity. |
| D07 | Mutable finalized manifests, late/overlapping observations and timestamp ties | INGEST-01 + S01/S07. Define finality/version checks and ordered reconciliation, with deterministic equal-time handling favoring valid positive evidence over ambiguous absence. Retain conflicts; no silent second miss. |
| D08 | Mixed unknown aggregation and long-lived search/manual positives | S01/S06. Confirm proposed conservative precedence and no automatic expiry; expose observation age. A freshness-expiry feature needs its own explicit policy decision, not a hidden grace rule. |
| D09 | Canonical recomputation after merge/reversal and downstream publication | IDENTITY-01 + S06/S07; RUN-01/SYNC-01 as consumers. Version membership reads and local change results; preserve candidate data. External synchronization and reconciliation remain outside IDENTITY-02. |
| D10 | Legacy evidence retention, migration ambiguity and missing raw material | DATA-01/OPS-01 + S03/S08. Retain compact evidence/policy/scope/decision references needed for audit and replay; report what cannot be reconstructed. No fabricated observations or cleanup implementation. |

## Implementation handoff checklist

- Component ID/status/objective, requirement/contract references and exact dependency versions; missing IDENTITY-01 or ingestion-boundary integration explicitly pending.
- Owned/coordinated files, generated schemas, forward migrations, legacy baseline/backfill behavior and rollback evidence.
- Final settings/defaults/override precedence, grace anchor, threshold conjunction, policy-change behavior and scope algorithm/fingerprint provenance.
- Source identity versus registry/scope/canonical identifiers; observation and inventory deduplication keys; timestamp ordering and capture freshness.
- Complete/partial/failed/search/filtered decision matrix, cache/resume evidence and reason codes for blocked inference.
- Source and canonical transition examples, multi-source truth table, unknown/disabled/manual behavior and membership-change recomputation.
- Atomicity, replay/partial-to-complete, late-evidence reconciliation, process restart and SQL/JSON consistency evidence.
- Proof availability stays separate from candidate progress and eligibility; no Salesforce calls, outbox writes or code outside the agreed component boundary.
- Commands/environment/versions/exit codes/results separated into unit, fake, actual local integration, SQLite, native Windows and live-service lanes.
- Resolved/open D01–D10, protected compact records for OPS-01, local API/result examples and next steps for RUN-01, SYNC-01 and GEN-02.
