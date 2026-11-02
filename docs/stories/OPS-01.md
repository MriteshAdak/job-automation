# OPS-01 — Retention, backups, capacity, and restoration

Component: **OPS-01 only** · Priority: **P0** · Status: **PLANNED**  
Planning date: **29 October 2026**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially §§2/R09/R16, 4–5, 6/OPS-01/SF-04, 8–10.  
Direct requirements: **R09, R16**. Supporting constraints: **R03/R04** provenance and identities; **R08** candidate ownership; **R11/R12** retained evidence and artifacts; **R14/R15** native Windows and private data.

This document plans implementation; it does not implement commands, change retention, configure a real destination, delete data, take a backup, or establish restore verification.

## Scope and prerequisite evidence

Provide manually invoked capacity, cleanup-preview/apply, backup, verification, and restore commands, plus a tested recovery procedure. Preserve compact identities, application history, referenced snapshots, unfinished requests and operations, and artifacts. Include Salesforce-owned fields in recovery. A backup is a recovery set spanning the database and required files, with explicit remote export coverage.

Scheduling belongs to **AUTO-01**, not OPS-01. No Task Scheduler jobs, services, timers, periodic loops, automatic drafting, notifications, or application submission belong here. RUN-01 continues to own pipeline execution and reconciliation; SF-04 owns org capacity conventions, metadata retrieval and export support; SYNC-01 owns candidate-field capture and remote write ordering. Normal restore must not dispatch outbox work or write candidate fields through the machine synchronization path.

Repository guidance read: [README.md](../../README.md) and the blueprint, including its story/handoff and Windows conventions. No applicable `AGENTS.md` was found in the repository/ancestor locations inspected or under `docs`, `src`, `tests`, and `config`. Current code takes precedence over old implementation summaries when determining available behavior.

| Dependency / current evidence | Consequence for OPS-01 |
|---|---|
| [DATA-01 handoff](../components/DATA-01.md), marked verified, describes migrations 001–002 and storage recovery. Current [migrations](../../src/job_automation/storage/migrations.py) extend through **008**. | Inventory all current tables and files; do not build a backup around the historical two-migration baseline. Preserve migration checksums. Existing recovery tests are not backup/restore tests. |
| [SYNC-01 handoff](../components/SYNC-01.md), verified offline, with live SF-01/SF-02 acceptance pending. | Preserve C12 plans, steps, mappings, sequence heads, barriers, snapshots and checkpoints. Fake integration cannot establish live Salesforce coverage. Its attribution of scheduling to OPS-01 is superseded by the blueprint and this scope. |
| **SF-04 handoff absent**: `docs/components/SF-04.md` and corresponding org portability assets were not found. SF-01/SF-02 handoffs are also absent. | Required dependency remains pending. Request the owner inputs below; use explicit synthetic fixtures for offline work. Do not invent org limits, metadata, field accessibility, destination hardware, or a verified export/import procedure. This absence says nothing about what exists in the user's org. |
| [StorageEngine](../../src/job_automation/storage/engine.py), [connection](../../src/job_automation/storage/connection.py), [filestore](../../src/job_automation/storage/filestore.py). | SQLite uses WAL; files live separately. Some filestore writes use mutable filenames and return absolute paths. A live directory copy or copying only the main `.db` is insufficient. |
| [Configuration](../../src/job_automation/configuration.py) resolves `backups_dir` beneath `data_root`; it has no independent backup-destination policy. | Add explicit destination configuration. Existing default directory is not evidence of a separate disk or disaster recovery. |
| [CandidateBackupService](../../src/job_automation/salesforce/candidate_backup.py) and [snapshot repository](../../src/job_automation/storage/repositories/candidate_snapshots.py). | Reuse these boundaries, subject to the completeness gaps below. Local candidate snapshots are not automatically a complete Salesforce export. |
| [WindowsWorkerLock](../../src/job_automation/orchestration/windows_lock.py), `OwnerKind.MAINTENANCE`, and RUN-01 code exist; no RUN-01 component handoff was found. | Reuse the shared physical-data-root lock and verify every relevant writer cooperates. A new OPS-only mutex would not exclude existing writers. |
| [IndexCleanupManager](../../src/job_automation/context/index_cleanup.py) already removes retired, unpinned generations; index capacity checks exist. | Coordinate with CONTEXT-03. The current direct deletion API has no OPS preview/plan contract; do not call it and assume a reviewed cleanup plan is enforced. |
| Profile evidence has relative, content-addressed paths; ingestion captures have immutable files; raw/artifact references and index directories can be absolute. Many cross-record links are in JSON/text. | Build typed reference inventory and path relocation; foreign keys alone cannot prove that cleanup or restoration preserves links. |

**Inputs required from SF-04 before live/full acceptance:** org identity; measured API/data/file limits, measurement time and units; field/object ownership and access manifest; application-history and relationship export scope; metadata package/version/hash and retrieval procedure; export completeness and null/missing-field semantics; known inaccessible/deleted records; source/retention constraints; field/relationship import order; same-org and replacement-org ID mapping rules; handling of read-only fields and automation during recovery; and a testable, authorized recovery procedure. Coordinate actual object/field names and credentials with SF-01/SF-02/SFCLIENT-01. OPS consumes these outputs and does not implement those components.

**SYNC-01 integration gaps to resolve or explicitly gate:** the current scanner issues a query with `LIMIT batch_size` and treats that query's `done` as whole-scan completion; that does not prove all jobs were visited. It does not select `SystemModstamp`, can silently skip missing/invalid external identities or missing fields, uses a date-based checkpoint ID, and saves snapshots/checkpoints through separately committing calls. A failed pre-update read can return `None`. Require an owner-provided, tested scan-completeness contract with stable scan ID, pagination/exhaustion, cumulative counts, omission reporting, org/object/mapping scope, and crash-safe checkpoint semantics. Until then OPS may preserve existing snapshots, but must label remote recovery coverage incomplete. Do not silently repair the entire scanner inside OPS-01.

## Confirmed constraints and proposed decisions

The preservation rules, configurable bulky-data retention, visible capacity failures, tested restore, actual destination configuration, same-disk limitation, and exclusion of scheduling are requirements. Names, retention durations, thresholds, manifest layout and CLI syntax below are **proposed engineering defaults**, to freeze in S01/S02 and record in the eventual handoff. They are not claims about user-selected policies or available storage.

### Retention policy and protection precedence

Deletion is disabled until an explicit policy is configured and a saved preview is applied. Age is measured from an owner-defined UTC timestamp at one recorded cutoff; filesystem access time is not authoritative. Missing/invalid timestamps, unknown record versions, unknown files and unresolved references block the affected deletion scope. No age, size cap, low-space emergency, availability state, or assessment rejection overrides protection.

| Data class | Proposed policy | Required protection / deletion condition |
|---|---|---|
| Company/job/source identities, aliases, external IDs, old source/application URLs, revisions, merge/reversal lineage and availability evidence | Keep indefinitely in OPS v1. | Never delete a job because it is rejected, unavailable, archived or old. Preserve inventories/observations needed to explain availability and avoid duplicate identities. |
| Published profile versions, facts, provenance; policy/template/input versions; assessments, context/model provenance | Keep compact records indefinitely; retain referenced bytes. | Follow C08–C14 references transitively, including historical versions and comparison results. Do not replace a frozen reference with the current version. Profile drafts remain protected unless their owner supplies explicit abandonment semantics. |
| Raw payloads, page captures, cache files | Proposed 90-day eligibility for **known unreferenced** payloads only; source-specific overrides. | Protect references from C04–C07, provenance, quarantine, run checkpoints, replay/reprocessing work, assessments and drafts. Preserve compact source identity/hash/attribution. Current required references must continue to resolve; OPS v1 does not expire referenced bytes or rewrite them into broken links. |
| Application history and Salesforce candidate snapshots | Keep indefinitely in OPS v1. | Preserve status, notes, decisions/overrides, follow-ups/interviews, relationship keys, observed timestamps and available historical exports. Latest values do not substitute for application history. |
| Runs, stage/work records, selections, C12 operations/plans/steps, reconciliation evidence, C13 requests | Keep compact records indefinitely. | Protect pending/running/retry-wait/upload-pending work, barriers, unknown remote outcomes, failed retryable or unresolved work, dependencies and frozen inputs. `failed` alone does not authorize cleanup. |
| C14 draft/artifact records and files, originals and edited/superseded versions | Keep indefinitely in OPS v1. | Local-only, upload-pending, delivered, approved and superseded artifacts remain recoverable. A remote file ID does not establish that the local copy is disposable. Preserve separate delivery/approval states and upload markers. |
| Retrieval index generations | Use CONTEXT-03 configured retention count; no second competing count. | Protect active generations, pins, in-progress builds and historical/request references. Eligible retired unreferenced payloads may be removed through a coordinated plan-aware adapter; preserve generation metadata and deletion audit. Default full backups include retained generations. |
| Diagnostic logs | Proposed 30 days for closed logs only. | Protect files needed for unresolved incidents/work. Keep compact run/maintenance summaries and audit records. Log rotation cannot erase recovery evidence. |
| Recognized abandoned temporary/staging files | Proposed 7 days after confirmed abandonment. | Establish no owner, pin, active build, journal or unfinished operation; age alone is insufficient. Unknown orphan files are reported for review, not deleted. |
| Completed backup generations | Proposed eligible after 30 days, keeping at least 3 successful sets. | Also protect pinned sets, the latest complete recovery set and the last successfully restore-tested set. Never prune good backups to make room for a new unverified backup. Partial/staging sets use separate abandonment rules. |

Source-specific maximum-retention or reuse restrictions also apply to backup copies. If a source restriction conflicts with required evidence preservation, report a policy conflict and route it to the source/data owner; do not silently retain prohibited copies or destroy referenced evidence. Require resolution before calling the affected operation compliant/complete. Secure erasure, legal hold administration, remote record deletion and general archival redesign are outside this component.

### Contracts to establish before business logic

Preserve current C01–C15 meanings and existing schema versions. Add versioned OPS companion records, schemas and synthetic fixtures; update the schema export catalog. Shared changes require compatibility and consumer notes. Append the next free migration (currently after 008), never edit an applied migration or reserve a stale number.

| Proposed contract / boundary | Inputs → outputs and invariants |
|---|---|
| `OperationsSettings` | Versioned retention rules, destination, capacity reserves, deadlines/batch bounds, remote-export requirements and freshness → validated resolved policy/fingerprint. No scheduling keys. |
| `RetentionInventory` / owner inventory ports | Consistent store view + owner adapters → object IDs, root-relative paths, sizes/hashes, references, lifecycle/pins, source restrictions, unknowns and protection reasons. Traverse JSON references as well as relational links; unknown schema means no destructive apply. |
| `CapacityReport` / `check_capacity` | Root/destination/staging volume measurements + operation estimate + SF-04 observation → per-resource used/free/required/reserve, timestamp, status `ok/warning/blocked/unknown`, safe issues. Unknown is not zero usage or unlimited capacity. |
| `CleanupPlan` / `plan_cleanup` | Inventory + policy + UTC cutoff → immutable plan ID/hash, store identity/schema, inventory fingerprint, exact candidates, per-item reasons and expected hashes/sizes, protected/blocked totals, estimated reclaim and expiry. Preview performs no cleanup or recovery transitions. |
| `CleanupResult` / `apply_cleanup` | Saved plan ID/hash + maintenance lock + fresh validation → attempted/deleted/skipped/failed items, actual reclaimed bytes, resumable journal and classified issues. Never broaden the plan on replay. |
| `RemoteRecoveryExport` | SYNC capture evidence + SF-04 export/metadata artifacts → org/object/field coverage, scan ID, start/end times, per-record identity/version tokens, expected/read/saved/skipped counts, missing fields, relationships, completeness/freshness and checksums. Distinguish null, empty, absent and unreadable. |
| `BackupManifest` / `create_backup` | Consistent local snapshot + exports + config allowlist → immutable backup UUID, format/application/contract/schema versions and migration checksums, local cut time, remote capture interval, inventory with root-relative paths/hash/size, mapping versions, omissions, completeness, destination/failure-domain evidence and verification results. |
| `RestorePlan` / `RestoreResult` | Verified manifest + explicit empty target + root map → compatibility/capacity checks, path mappings, conflicts, validation results, preserved states, remote recovery package and activation/reconciliation instructions. No automatic live dispatch. |
| `MaintenanceReport` | Operation ID/type, timestamps, status `succeeded/partial/failed`, counts with units, classified errors, pending work, safe next action and artifact references. Keep `integrity_verified` distinct from `restore_tested` and remote coverage status. |

A backup contains a whole consistent SQLite snapshot, required raw/profile/artifact/index files, recovery-relevant sidecars, approved non-secret configuration and available versioned policy/template inputs, plus remote export/metadata artifacts. Exclude credentials/tokens, OS lock files, the backup tree itself, unrelated files, virtual environments and downloaded models. Record excluded model names/digests/runtime requirements; restoring data does not promise that inference or rendering is installed. Use an allowlist for configuration, not a recursive copy of all local settings. Backups contain private data and need access restricted to the configured account; no new paid service or home-grown cryptography is required.

### Consistency, paths and failure domains

Acquire the existing deployment lock as `MAINTENANCE` and exclude all writers for the local snapshot/copy interval, including profile/index/import/storage commands, not just search. Verify lock participation or require those tools stopped; do not promise consistency with uncooperative writers. Acquire any destination lock in a fixed order. Use SQLite's backup API into staging, then verify the resulting database. Do not copy a live main database alone, independently copy WAL/SHM as a recovery set, or call startup recovery to make the backup look clean. Include committed WAL data; exclude uncommitted writes. Hold the lock through file inventory/copy/hash validation because older filestore paths can be overwritten.

The local snapshot and Salesforce export cannot share a distributed transaction. Record separate cut/capture times and per-record modification evidence; a local lock does not stop candidate edits in Salesforce. Report the resulting recovery-point limit and conflicts. An unavailable or stale Salesforce export may yield a valid **local-only/degraded** recovery set with a partial result, never a full-completeness claim.

Use `pathlib.Path`, explicit bases and root-relative manifest paths. Enumerate only managed roots; validate resolved paths and Windows junction/reparse-point escapes before reading, copying, deleting or restoring. Account for shared files and case/path aliases. Never recursively copy an ancestor containing the destination; exclude `backups_dir` and staging explicitly when destination is below the data root. Reject source/destination overlap with managed payload directories. Refuse arbitrary paths supplied by stored JSON or manifests. Restores map known local path fields only; do not globally replace strings, URLs or remote identities. Preserve original evidence and manifest bytes and record relocations separately.

**Same-disk backups:** a separate folder or partition on the same physical disk can help recover accidental deletion or an earlier logical version, provided the copy survives. It does not protect against failure/loss of that disk, and can be lost to ransomware, account compromise or a mistaken broad deletion. Another drive letter does not prove another physical device. A separate device improves disk-failure coverage; if always attached or kept with the computer it still shares other risks. Record physical-device independence as verified/same/unknown, and document actual destination availability, last successful backup/export, and last restore drill. Do not promise off-device protection when it has not been demonstrated. No backup destination or recovery-point objective has yet been supplied by the user.

## Implementation stories

### OPS-01-S01 — Freeze recovery inventory and contracts

**Objective / requirements:** establish deletion and recovery boundaries before business logic. R09/R16; supporting R03/R04/R08/R11/R12/R15.

**Dependencies:** DATA-01, SYNC-01 and SF-04 interface agreement; FND-01 contract discipline. Coordinate PROFILE-01, INGEST-01, IDENTITY-01/02, CONTEXT-03, RUN-01 and future GEN owners for reference semantics. Missing live dependencies permit synthetic contracts, not claimed live completeness.

**Owned files:** proposed `src/job_automation/operations/{__init__,records,ports,inventory}.py`, `schemas/v1/ops_*.schema.json`, `tests/operations/test_contracts.py`, `test_inventory.py`, `tests/fixtures/operations/`. Coordinated additions: contract export catalog, storage migration and `storage/repositories/operations.py` for plans/journals/reports.

**Inputs / outputs:** C01–C15, current database/files and dependency manifests → versioned inventory, contracts, protection graph and compatibility matrix.

**Tasks:**

1. Inventory every table through migration 008, payload JSON, file reference and sidecar. Explicitly cover identity lineage, availability inventories, profile facts/provenance, assessments, outbox plans/steps/heads/mappings, candidate snapshots/checkpoints, requests/artifacts, context generations/pins, run attempts/work/selections/bindings/quarantine/reports.
2. Define typed resolvers for exact-version references and owner-declared optional caches. Keep all compact durable rows in v1; no generic age-based SQL deletion or cascade deletion of parent rows.
3. Define protection closure, unknown-data behavior, deduplicated file accounting, report schemas and manifest version compatibility. Preserve failed/unresolved work, not just nonterminal enum values.
4. Add transaction-participating journal writes: existing repositories using `with self.conn` must not be assumed to participate safely in an outer transaction. Test injected failure after inner writes.
5. Record SF-04 and SYNC scan gaps as owner acceptance gates, with explicit fake fixtures; record all proposed choices and schema impacts before downstream stories.

**Acceptance / tests:** an old profile fact or posting revision referenced only inside C13/C14 JSON remains protected; two references to one file count once; a missing reference or unknown table/schema blocks affected cleanup; failed uncertain sync and upload-pending artifacts remain rooted. Migration upgrade preserves current rows/checksums and rolls back on failure.

**Configuration / handoff:** no destructive defaults. Publish root/edge inventory, version matrix, owner gaps, new schema registrations and migration number. S02–S07 consume these contracts.

### OPS-01-S02 — Configure destinations and measure capacity

**Objective / requirements:** expose capacity and real backup limits before mutation. R09/R16/R14/R15.

**Dependencies:** S01; FND-01 configuration; SF-04 measurements through its export/report boundary; SFCLIENT-01 for any authorized read-only refresh. Reuse CONTEXT-03 estimates without moving index-building ownership.

**Owned files:** proposed `operations/{settings,capacity,paths}.py`, `config/operations.example.json`, `tests/operations/test_settings.py`, `test_capacity.py`, `test_paths.py`. Coordinated `configuration.py`, `schemas/v1/app_config.schema.json`, `config/app.example.json`, and affected configuration tests.

**Inputs / outputs:** settings, managed roots, volume observations and measured remote capacity → validated configuration and `CapacityReport`.

**Tasks:**

1. Add optional `operations_settings_ref`, resolved relative to its configuration file. Existing configurations remain valid; operations needing a destination fail with missing configuration when it is unset. A proposed explicit `backup.destination` can select existing `backups_dir`, an external local volume, or a supported UNC share; never silently fall back from an unavailable destination to the source disk.
2. Configure destination identity, reserve bytes/percent, retention policies, finite copy/lock/network deadlines, batch limits and required remote-export freshness/coverage. Prefer a directory of complete full backup generations initially; no incremental-chain dependency.
3. Measure source, destination and restore/staging volumes independently, deduplicating volumes when shared. Include database/WAL growth, file copies, verification space, journal/quarantine overhead and preserved old restore targets in peak estimates. Do not assume compression savings or that SQLite row deletion immediately frees disk space.
4. Proposed starting reserve: the greater of 1 GiB and 10% of each volume; warn below twice the reserve, block when predicted post-operation free space falls below reserve. Label these tunable examples, not measured requirements. Unreadable/unmounted capacity is `unknown` and blocks required writes, not an assumed pass.
5. Report actual SF-04 API/data/file measurements with units, timestamp and freshness; missing data remains unknown. Never hardcode Developer Org capacity or delete remote objects to resolve pressure. Optional remote unavailability must not prevent read-only local capacity inspection.

**Acceptance / tests:** a same-volume destination includes both copy and source overhead; different drive letters with unknown hardware yield unknown independence; full/unplugged/read-only destinations fail before mutation; disk-full during copying remains a failure despite successful preflight; Windows spaces, Unicode, UNC unavailability, junction escapes and config-relative paths behave deterministically. No host capacity figures are invented in tests.

**Configuration / handoff:** publish example values, precedence, path rules, measured destination/failure-domain evidence and threshold rationale. Capacity is advisory between checks; every write still handles failure. Operators must supply the actual destination before backup readiness is claimed.

### OPS-01-S03 — Produce a reviewable cleanup preview

**Objective / requirements:** make proposed cleanup explicit and prove protected data is excluded. R09/R16; supporting R03/R04/R08/R11/R12.

**Dependencies:** S01/S02; owner reference inventory and CONTEXT-03 retention policy.

**Owned files:** proposed `operations/{retention,preview}.py`, `tests/operations/test_retention.py`, `test_preview.py`, fixture graphs.

**Inputs / outputs:** consistent inventory, policy, cutoff → saved `CleanupPlan` and human-readable/JSON preview. Saving the explicitly requested preview is allowed; preview never deletes, prunes, migrates or transitions work states.

**Tasks:**

1. Apply protection closure before age rules. Show candidate IDs, managed relative paths, class, age basis/cutoff, reasons, size, expected hash, blocked/protected reasons, totals by class and estimated reclaim.
2. Use the retention matrix above, source restrictions and explicit unknown handling. Report zero eligible files honestly when retained provenance protects all raw input.
3. Persist plan schema/store/policy fingerprints, exact item list, inventory generation and expiry. Proposed lifetime: 24 hours; any relevant state change invalidates it sooner. Diagnostics show IDs and counts, not notes, evidence text, raw payloads or credentials.
4. Inventory index candidates without invoking `IndexCleanupManager.cleanup()`. Require an adapter capable of inspecting candidates and later applying the exact reviewed set with pins rechecked.

**Acceptance / tests:** a 200-day-old unreferenced capture is eligible under the 90-day example; an equally old capture referenced by an unfinished run, C08 citation, quarantine record or shared live file is protected. An unavailable/rejected job still retains its identity/history. Preview reports application data/artifacts as protected. Source-policy conflicts and malformed references produce blocked reasons, not hidden omissions. Repeating preview over the same cutoff/state produces the same candidate content/hash.

**Configuration / handoff:** record retention decisions and unresolved source restrictions. Provide one synthetic preview with eligible, protected, unknown and blocked items; pass exact plan semantics to S04.

### OPS-01-S04 — Apply cleanup safely and recover interrupted cleanup

**Objective / requirements:** execute only a current reviewed plan, with durable outcomes. R09/R16/R14/R15.

**Dependencies:** S01–S03; shared RUN-01 maintenance lock; coordinated CONTEXT-03 adapter. S06 supplies a verified backup when deleting non-reconstructible eligible material under the policy.

**Owned files:** proposed `operations/{cleanup,journal}.py`, `tests/operations/test_cleanup.py`, `test_cleanup_recovery.py`, `test_cleanup_concurrency.py`; narrow coordinated plan-aware index cleanup entry point and storage journal repository.

**Inputs / outputs:** plan ID/hash, explicit apply intent, current inventory → `CleanupResult`, journal and safe partial/failure report.

**Tasks:**

1. Acquire maintenance lock, verify store/policy/plan identity and expiry, re-resolve paths and references, then recheck file identity/hash/size and protections. A newly referenced or changed candidate invalidates apply and requires a new preview; never widen selection or accept an edited plan.
2. Journal intent before filesystem mutation. Prefer reversible staging in a managed same-volume quarantine followed by recorded deletion; record each boundary and distinguish bytes moved from bytes actually freed. Update owner metadata without dangling required references.
3. Recover idempotently from interruption before/after move, unlink and journal commit. Recheck eligibility on resume; restore a quarantined file if protection appeared. Missing files need recorded reconciliation, not invented successful deletion. Bound work and preserve retryable failures.
4. Reject traversal, junction swaps and arbitrary external paths. Stop safely on permission/sharing/capacity failure. Ensure safety when the journal cannot be written: perform no unjournaled deletion.
5. Never run automatic broad emergency cleanup, prune the last good backup, vacuum the database implicitly or delete parent identity/request/history records. No generic force flag bypasses these rules.

**Acceptance / tests:** a new C13 reference or index pin after preview prevents deletion; search/profile/index maintenance cannot race apply; Windows locked files remain intact and reported; a crash at every journal boundary resumes without deleting protected data or claiming duplicate reclaimed bytes. Only planned paths change. Mixed success returns partial status with exact failed/pending IDs.

**Configuration / handoff:** document quarantine recovery and space costs, batch bounds, plan invalidation, journal durability and adapter ownership. Supply the crash matrix and actual reclaimed-byte semantics.

### OPS-01-S05 — Assemble Salesforce recovery coverage

**Objective / requirements:** make Salesforce-owned fields and history recoverable without crossing machine/candidate ownership. R09/R16; supporting R08/R15.

**Dependencies:** S01/S02, SYNC-01 completeness contract, SF-04 export/metadata handoff; SF-01/SF-02/SFCLIENT-01 for live verification. Absent handoffs gate live acceptance.

**Owned files:** proposed `operations/{remote_export,remote_recovery}.py`, `tests/operations/test_remote_export.py`, `test_remote_recovery.py`, synthetic export fixtures. No new OAuth, Salesforce metadata retrieval implementation, general remote writer or candidate-field additions to sync payloads.

**Inputs / outputs:** validated scan results, candidate snapshots, remote mappings and SF-04 exports → `RemoteRecoveryExport` and a reviewable recovery/import package.

**Tasks:**

1. Capture/read candidate-owned status, notes, decisions/overrides, follow-ups/interviews and available application history according to the actual field/object manifest. Include org/object/record IDs, canonical External IDs, relationships, mapping version, read fields, explicit nulls, observation/version tokens and export hashes. Preserve both latest and historical snapshots.
2. Check all-page coverage, expected identities, missing/inaccessible fields, skipped records, duplicates, scan freshness and checkpoint completeness. Do not accept a successful bounded query as full export. Preserve last good complete export when a new scan fails or is partial.
3. Include SF-04 metadata/permissions/value mappings needed to interpret and restore data. Record unavailable history/deleted records and any remote-only Files content that is not exported; remote IDs alone do not back up file bytes. Phase 1 assets are inventoried if present, without implementing GEN/SF-05–08.
4. Generate a candidate-data recovery package for the SF-04 procedure, preserving null versus absent values and stable relationship keys. Normal synchronization still rejects all candidate-owned writes. No automatic upload/import occurs from backup or local restore.
5. Define live recovery conflict handling: identify the target org; map company/job External IDs before dependent history; compare export version tokens/current fields; retain newer candidate edits by default and report conflicts. Missing/deleted records require explicit SF-04 repair decisions; a new org requires fresh record/File ID mappings. Read-only/audit fields remain preserved export evidence where they cannot be written back.

**Acceptance / tests:** multiple pages and more than one batch export every eligible record; a second-page failure, omitted candidate field, empty configured field list with required coverage, stale scan or malformed external key produces incomplete coverage. Known-empty exports require verified scope. Nulls, Unicode notes, dates and separate application histories survive package round-trip. A newer remote edit becomes a conflict and is never overwritten automatically. No outbound machine payload contains candidate fields.

**Configuration / handoff:** publish expected field/history coverage, freshness threshold, actual org/mapping binding, limitations and the SF-04 procedure reference. Until upstream gaps close, full remote restore remains pending, with local-only backup explicitly available.

### OPS-01-S06 — Create and verify a consistent backup set

**Objective / requirements:** make a portable recovery set that includes all retained links and bytes. R09/R16/R14/R15.

**Dependencies:** S01/S02/S05 and writer-quiescence contract with RUN-01 and other mutating entry points. S05 can provide declared incomplete coverage for a local-only backup; this cannot satisfy full acceptance.

**Owned files:** proposed `operations/{backup,manifest,verification}.py`, `tests/operations/test_backup.py`, `test_backup_consistency.py`, `test_backup_failures.py`; narrow storage snapshot helper if needed.

**Inputs / outputs:** settings, protected inventory, coherent local state and remote exports → staged then committed backup directory, manifest, integrity report and maintenance result.

**Tasks:**

1. Check capacity and destination identity/access; collect remote export evidence and then acquire local maintenance exclusion. Snapshot SQLite with the backup API without running migrations/recovery on the source; include all committed rows, checkpoints and unresolved work unchanged.
2. Copy managed files required by that snapshot and retained recovery inventory while writes remain excluded. Validate every referenced file/hash/size; capture retained index manifests/chunks/vector/keyword payloads coherently. An unexplained missing file or mismatch fails full local verification.
3. Include allowlisted configuration, exact version inputs, metadata/export manifests and dependency/runtime requirements. Record optional omissions explicitly. Do not include secrets or nested previous backups. Stream copies/hashes with bounded memory on the existing hardware.
4. Verify staged SQLite integrity and foreign keys, application-level reference closure and file hashes; record table/object counts and versions. Write a complete manifest and completion marker only after validation and flush/close. Publish staging as a final generation with same-filesystem rename semantics that are tested on supported destinations; unsupported destinations fail or are documented as limited.
5. A crash, cancellation, disk-full event or lost destination leaves an incomplete set and preserves previous complete backups. Verification must discover sets from their manifests even if the local catalog is lost. Retention is a separate preview/apply action after success, not a hidden backup side effect.

**Acceptance / tests:** committed data still in WAL restores; uncommitted data does not appear; a concurrent writer is excluded; raw overwrite/copy mismatch cannot yield success. An artifact and its request, profile citation and fact, index and manifest, and uncertain outbox operation/barrier remain consistent. Interrupted manifest publication is never listed as complete. No credentials or recursive backups appear. Integrity verification alone is not labeled a passed restore test.

**Configuration / handoff:** record backup format/version, exact includes/excludes, consistency interval, export interval, destination class, maximum working space and observed duration. Report local completeness separately from remote completeness/freshness.

### OPS-01-S07 — Restore into isolation and reconcile recovery

**Objective / requirements:** demonstrate useful restoration with identities and references intact. R09/R16; supporting R04/R08/R11/R12/R14/R15.

**Dependencies:** S01/S02/S05/S06; DATA-01 migrations/repositories; PROFILE/CONTEXT resolvers; SYNC/RUN recovery boundaries; SF-04 for remote recovery procedure. Future GEN recovery remains with GEN owners.

**Owned files:** proposed `operations/{restore,relocation}.py`, `docs/operations/restore.md`, `tests/operations/test_restore.py`, `test_restore_links.py`, `test_restore_reconciliation.py`, `test_restore_failures.py` and synthetic drill fixtures.

**Inputs / outputs:** completed backup, explicit new empty data root and destination org intent → restored isolated store, relocation map, verification report, candidate recovery package and activation checklist.

**Tasks:**

1. Verify manifest format, migration checksums, all file hashes and supported application/schema versions before activation. Refuse unsupported/newer schemas and incomplete backups as full restore inputs. Permit explicitly requested salvage only as isolated partial recovery with missing items listed. Never overwrite an existing runtime store by default.
2. Check target/staging capacity and containment; restore into a new directory and use a target maintenance lock. Do not carry source lock files, active PID ownership or credentials into the restored deployment. Keep processing inert throughout verification.
3. Relocate every declared absolute local path in rows and nested payloads through the root map; retain relative evidence references, semantic IDs, hashes, URLs and immutable payload fingerprints. If relocation would alter a fingerprinted object, use an owner-supported resolver/relocation layer or coordinated versioned migration; never silently rehash frozen payloads. Unknown external references block readiness.
4. Validate SQLite integrity/foreign keys, table counts, typed contract loading, transitive links, file hashes, historical profile resolution, raw/posting provenance and active/pinned index loading. A separately declared rebuildable-index omission must remain unavailable until CONTEXT-03 rebuild/validation; never relabel a different index as the frozen one.
5. Preserve C12/C13/C14 states and identities in the restored data. Before any subsequent live execution, RUN/SYNC must reconcile against current Salesforce: the org may have advanced beyond the backup, including writes after the local cut. Check remote version heads/markers even where the restored local state lacks a barrier; do not blindly replay apparently pending work or reset sequences. Keep ambiguous uploads for GEN-06 reconciliation before resend; do not notify or approve artifacts during restore.
6. Supply a concrete SF-04 recovery sequence: verify target org/metadata/access; inspect the candidate recovery diff; resolve newer-edit/deleted-record conflicts; establish canonical-to-remote mappings; import supported owned fields and related history through the approved recovery procedure; read back values and relationships; record omissions and resulting IDs. Normal OPS restore creates this package and instructions without performing live candidate mutations.
7. Activate only after local verification and explicit operator selection of the new root, preserving the previous root for rollback and stopping the old worker. Reconfigure credential references separately. Document how to return to the old root if activation checks fail, and prevent two restored copies from dispatching to the same org concurrently.

**Acceptance / restore tests:** use the matrix below. A representative full backup restored to a different Windows path resolves exact historical facts, job/source/company mappings, application histories, requests and artifacts without contacting external services. Restoration emits no sync/upload/model calls. Fake remote reconciliation yields no duplicate logical job/file, preserves newer candidate edits and advances machine work only through its owning recovery service. Actual live SF recovery evidence remains pending until its prerequisites and authorization exist.

**Configuration / handoff:** document root relocation, supported versions, migration-before-activation procedure on a copy, rollback, credential re-establishment, remote conflicts, recovery-point gaps and measured recovery time. A local drill does not certify a complete Salesforce-org disaster restore.

### OPS-01-S08 — Expose manual commands and publish verification handoff

**Objective / requirements:** make maintenance reviewable, bounded and diagnosable. R09/R16/R14/R15.

**Dependencies:** S01–S07. No AUTO component is required or implemented.

**Owned files:** proposed `operations/cli.py`, `tests/test_cli_operations.py`, `tests/manual/operations_restore_smoke.py`, `docs/components/OPS-01.md`, `docs/operations/restore.md`; minimal dispatch wiring in `src/job_automation/cli.py` and README command documentation.

**Inputs / outputs:** explicit CLI invocation → typed maintenance reports, safe terminal/JSON output and process exit status. Proposed commands: `ops capacity`, `ops cleanup preview`, `ops cleanup apply --plan ... --plan-hash ...`, `ops backup create`, `ops backup verify`, `ops restore plan`, `ops restore apply --target ...`. Final parser choices are frozen in S01, not already available commands.

**Tasks:**

1. Make default cleanup action preview-only; apply requires the exact saved plan. Separate backup creation from pruning and restore staging from activation. Expose bounded callable services for future AUTO-01 without timers or scheduling configuration.
2. Use existing `ClassifiedError` categories plus stable OPS issue codes. Distinguish capacity, missing configuration, permission/authentication, rate-limit/network/service, unsupported backup/schema, corrupt/missing files, stale plan, lock contention, incomplete export and unavailable destination.
3. Proposed exit mapping: 0 complete requested scope; 1 partial/degraded; 2 invalid/missing configuration or stale/unsupported input; 3 operational/verification failure. Freeze/document this mapping alongside existing CLI conventions. A deliberately local-only request may succeed locally, but must still state remote coverage unavailable; a requested full backup cannot return full success with missing remote data.
4. Persist reports with IDs, timestamps, counts/bytes, safe issue codes, last good backup/export, failed stage, pending items and actionable next steps. If reporting storage itself fails, emit minimal stderr and nonzero exit; never report success because the log write failed. Do not log candidate values, secrets, raw queries/URLs with tokens, full evidence or arbitrary exception dumps.
5. Use bounded retry only for recoverable transport/sharing failures with revalidation. Disk-full and missing destination require remediation; do not spin retrying or delete protected data automatically. Leave unfinished state inspectable.
6. Run component and affected storage/config/contract/context/sync/orchestration checks, native Windows multiprocess/path/crash drills, and an isolated representative restore. Record live checks as passed/pending separately, then publish the handoff checklist below.

**Acceptance / tests:** CLI failures have consistent JSON/exit status, sanitized diagnostics and no hidden mutation; backup success followed by a failed restore drill is visible; capacity failure leaves unfinished requests/artifacts intact; no command creates a scheduled task or starts a background loop. CLI help and documented PowerShell examples match the implemented parser.

**Configuration / handoff:** old app configs load unchanged, examples contain no real destinations/credentials, and all new knobs and operational limits are documented. Mark implementation verified only for acceptance actually demonstrated.

## Required restore and fault-injection matrix

| Scenario | Evidence required |
|---|---|
| Representative full local recovery | Synthetic store includes two profile versions, cited old fact, two posting revisions, aliases/merge history, availability evidence, rules/LLM assessment references, candidate history, queued and uncertain sync, failed unresolved work, pending/running/upload-pending C13, and local/delivered/superseded C14 bytes. Compare semantic IDs, values, links, approval/delivery states and hashes after restore. |
| WAL and database/file boundary | Committed WAL-only transaction survives; uncommitted transaction is absent; attempt a concurrent mutable raw/artifact write; backup either excludes writer or detects change and fails. Never accept a mixed cut. |
| Portable roots | Restore to `C:\Users\Example\Job Automation Prüfung ä\Restored` using test-controlled roots; old root unavailable. Exercise profile relative refs, raw/file-URI refs, nested checkpoint paths and index directories. All required readers use restored files; URLs and hashes stay unchanged. |
| Cleanup protection | All unfinished states, candidate history, application links, current/referenced snapshots, active/pinned indexes and artifacts survive age/size pressure. Newly introduced references invalidate preview. Unknown schema, source-policy conflict or junction escape blocks deletion. |
| Cleanup interruption | Inject failures before/after journal, rename, unlink and metadata update; restart in another process; no loss of protected references and no false reclaim counts. |
| Backup interruption/corruption | Interrupt database snapshot, file copy, hash check, final marker and publication; test truncated DB/file, missing artifact, bad checksum, full disk and detached destination. Previous good set remains usable; incomplete set never becomes full success. |
| Destination isolation | Same-disk report states disk-failure limitation. Test independent removable destination disconnect and unsupported network atomicity. No silent destination fallback or nested backup recursion. |
| Remote export completeness | More than one batch, failed page, skipped IDs, unreadable fields, null/empty distinctions, stale export and concurrent candidate edit; full coverage requires explicit evidence, not `done` on a limited query. |
| Salesforce-owned recovery | Round-trip notes/status/overrides/dates/history through package and fake SF-04 import/read-back with relationships intact. Same-org newer edits become conflicts; new-org IDs are remapped; inaccessible/read-only history limitations are recorded. Live drill is a separate gate. |
| Restored outbox/requests | Remote is ahead of backup, including an acknowledged-after-cut write and unknown file upload. Before resumption, reconcile markers/versions/IDs without duplicate logical records/files, sequence regression or candidate-field overwrite. Restore itself sends nothing. |
| Index recovery | Retained active/pinned generation verifies files and loads with matching model/dimension/chunk/version metadata. Missing required generation fails; deliberate optional omission is explicit and requires owner rebuild before use. |
| Compatibility/rollback | Older supported schema migrates only on restored copy with preserved data; unknown newer schema/checksum fails; nonempty target is refused; failed validation leaves original data/config untouched and no active worker. |
| Reporting/security | Secrets and candidate strings seeded into failures never appear in ordinary logs; report-write failure produces stderr/nonzero status. Destination accessibility is tested under the intended account; do not claim encryption or disk independence without evidence. |

Implementation-time PowerShell verification (planned files; not commands run by this planning task):

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests\operations tests\test_cli_operations.py
& ".\.venv\Scripts\python.exe" -m pytest tests\storage tests\contracts tests\test_configuration.py tests\salesforce\sync tests\orchestration tests\context
& ".\.venv\Scripts\python.exe" tests\manual\operations_restore_smoke.py
```

The smoke script must create isolated synthetic roots using `Join-Path`/`pathlib`, refuse real deployment roots by default, and perform no live org writes. Record exact Windows/Python versions and test results; this plan does not inherit old handoff test counts as new verification.

## Implementation order, configuration impact and completion handoff

Order: **S01 → S02 → S03 → S04**, and **S01/S02 → S05 → S06 → S07**, followed by **S08** integration. S04 can be tested with synthetic backup evidence while S06 is pending; production destructive apply must meet its documented backup preconditions. Only minimal shared wiring/migrations belong to OPS-01; unresolved scanner, org metadata/export or worker semantics stay assigned to their owners.

Configuration changes are additive: an optional app reference to a separate versioned operations file; explicit destination and root resolution; retention enablement/ages and source overrides; capacity reserves; finite operation budgets; remote export coverage/freshness; backup-generation retention and pins. Preserve existing `ResolvedPaths.backups_dir` compatibility. No credentials, actual private paths, scheduling times, DST/missed-run behavior or notification settings belong in committed examples. No retention deletion is activated merely by upgrading.

The final `docs/components/OPS-01.md` must include:

- Component/status/objective, R09/R16 traceability, dependency versions, current schema/migration checksums, owned and coordinated files, and contract versions.
- Confirmed versus proposed decisions; exact policy defaults/cutoffs/protection rules; sample cleanup preview and apply journal; invalidation and crash-recovery behavior.
- Actual configured destination, account access, measured capacity, physical failure-domain evidence, same-disk limits, and destination/last-backup/export/restore freshness. Keep private paths and sensitive values out of the shared handoff; use a local operator record where needed.
- Backup contents/exclusions, local snapshot consistency, remote capture coverage/freshness and uncertainty, manifest format, restore relocation/version support, and unavailable evidence or services.
- Restore procedure and rollback steps; proof that identities, references, history, unfinished work and artifacts survive; explicit Salesforce-owned recovery/read-back evidence or pending owner gate; no blind outbox replay or candidate overwrite.
- Commands/results for unit/contracts, integration against fakes, native Windows process/path/crash tests, representative restore, and live Salesforce/destination checks, each labeled passed/failed/pending with environment and limitations.
- SF-04 and SYNC-01 outstanding acceptance items and accountable owners. Do not mark full OPS-01 acceptance or G2 complete while required live recovery coverage/destination evidence is missing.
- Handoffs to RUN-01 for maintenance exclusion, capacity/report consumption and post-restore reconciliation; CONTEXT-03 for plan-aware retention; GEN owners for frozen request/artifact recovery; SF-04/SYNC for remote recovery; and future AUTO-01 for bounded manual entry points only. Scheduling remains deferred.

OPS-01 is complete when a representative recovery set restores with links and bytes intact, cleanup demonstrably leaves protected/unfinished data untouched, configured capacity failures are visible, and the actual destination and recovery limits are documented. Documentation-only planning establishes none of those runtime claims.
