# Component Handoff: OPS-01 — Operations, Retention, Backup, and Disaster Recovery

Component ID: **OPS-01**  
Status: **VERIFIED (LOCAL RECOVERY); REMOTE DRILL PENDING SF-04**  
Phase: **Phase 0 / Phase 1 Operations Foundation**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Planning Reference: [docs/stories/OPS-01.md](../stories/OPS-01.md)  
Date Completed: 29 October 2026  
Direct Covered Requirements: [R09](../../IMPLEMENTATION_BLUEPRINT.md#r09), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15)  
Supporting Requirements: [R03](../../IMPLEMENTATION_BLUEPRINT.md#r03), [R04](../../IMPLEMENTATION_BLUEPRINT.md#r04), [R08](../../IMPLEMENTATION_BLUEPRINT.md#r08), [R11](../../IMPLEMENTATION_BLUEPRINT.md#r11), [R12](../../IMPLEMENTATION_BLUEPRINT.md#r12)  

---

## 1. Executive Summary & Objective

OPS-01 establishes the production maintenance, storage capacity monitoring, retention cleanup, point-in-time backup, and disaster recovery isolation capabilities for the job search automation system.

It guarantees that:
1. **Retention is inspectable and non-destructive by default**: Cleanup candidates must be explicitly generated into an immutable, fingerprint-bound, cryptographically hashed `CleanupPlan`. Deletion cannot proceed without quoting the plan UUID and hash.
2. **Provenance & unfinished work are strictly protected**: All active and historical jobs, citations, profile facts, generation requests, unfinished runs, sync outbox items, quarantine records, and pinned indexes are immune to retention cleanup.
3. **Backups are atomic and mutually consistent**: SQLite committed WAL snapshots (`sqlite3.Connection.backup()`) and physical filesystem assets (`raw`, `artifacts`, `indexes`, `profiles`) are captured under an exclusive maintenance lock (`WindowsWorkerLock`) with byte-for-byte SHA-256 verification and atomic completion markers (`backup.complete`).
4. **Restoration operates strictly in isolation**: Backups can only be restored into a new, completely empty directory root (`RestorePlan` refuses populated targets), relocating all database path references while preserving semantic IDs, content hashes, and external URLs. Restored systems remain completely inert (no outbound model calls, uploads, or sync mutations).
5. **SF-04 handoff absence is safely handled**: The missing SF-04 Salesforce export component is explicitly reported as `LOCAL_ONLY_ABSENT_SF04` / `unknown`. Local backups and capacity checks remain fully operational in local-only mode, with clear diagnostics and exit code 1 (degraded/partial).

---

## 2. Traceability & Contracts

### 2.1 Contracts Implemented (`job_automation.operations.records`)

| Contract Record | Version | Status | Purpose |
|---|---|---|---|
| `OperationsSettings` | 1.0 | **VERIFIED** | Retention thresholds, capacity reserve rules, timeout bounds, and backup limits. |
| `RetentionInventory` | 1.0 | **VERIFIED** | Complete catalog of disk items, database references, and protection closures. |
| `CapacityReport` | 1.0 | **VERIFIED** | Storage volume headroom (source, destination, staging) and remote limits. |
| `CleanupPlan` | 1.0 | **VERIFIED** | Immutable preview containing exact candidate items, fingerprints, and plan hash. |
| `CleanupResult` | 1.0 | **VERIFIED** | Execution result recording removed items, actual reclaimed bytes, and issues. |
| `BackupManifest` | 1.0 | **VERIFIED** | Portable point-in-time backup manifest with migration checksums and file hashes. |
| `RestorePlan` | 1.0 | **VERIFIED** | Restore preflight validating target emptiness, capacity, and path mappings. |
| `RestoreResult` | 1.0 | **VERIFIED** | Execution result verifying SQLite integrity, foreign keys, and relocated paths. |
| `MaintenanceReport` | 1.0 | **VERIFIED** | Durable audit report persisted in `ops_maintenance_reports`. |
| `RemoteRecoveryExport`| 1.0 | **VERIFIED** | Candidate snapshot export contract; marks SF-04 status. |

JSON schemas for all operational records have been exported and validated in `schemas/v1/`.

### 2.2 Storage Migration 009 (`MIGRATION_009_OPERATIONS_JOURNAL_AND_PLANS`)

Applied to `schema_migrations` with checksum verification:
- `ops_cleanup_plans`: Persists previewed plans with expiry and fingerprints.
- `ops_cleanup_journals`: Transaction-participating journal tracking item-by-item staging and deletion.
- `ops_maintenance_reports`: Durable operational history for backup, cleanup, and capacity runs.
- `ops_backups`: Catalog of local backups with completeness, verification, and pin flags.

---

## 3. Configuration & Policy Defaults

Configured via optional `operations_settings_ref` in `config/app.json`, pointing to an operations JSON file (e.g. `config/operations.example.json`):

```json
{
  "$schema": "../schemas/v1/operations_settings.schema.json",
  "schema_version": "1.0",
  "retention": {
    "enabled": false,
    "raw_payloads_days": 90,
    "logs_days": 30,
    "staging_days": 7,
    "backups_days": 180,
    "source_overrides": {
      "arbeitsagentur": 180
    }
  },
  "capacity": {
    "reserve_bytes": 1073741824,
    "reserve_percent": 10.0,
    "warning_multiplier": 2.0
  },
  "backup": {
    "destination": null,
    "keep_generations": 5,
    "compress": false
  },
  "limits": {
    "max_cleanup_items": 1000,
    "timeout_seconds": 300
  }
}
```

### Protection Rules
1. **Disabled Retention**: When `retention.enabled` is `false`, all items are strictly protected (`ProtectionReason.RETENTION_DISABLED`).
2. **Provenance Closure**: Any raw posting referenced by `raw_postings`, `normalized_postings`, `posting_bindings`, or `quarantine_records` is protected (`ProtectionReason.REFERENCED_IN_DATABASE`).
3. **Unfinished Work**: Unfinished runs (`pending`, `running`, `paused`), active stage work, unacknowledged sync outbox operations, and open generation requests (`pending`, `running`, `upload_pending`) protect all associated files.
4. **Documents & Artifacts**: Physical PDFs and DOCX files referenced by `artifacts` are permanently protected from automated unlinking.
5. **Index Generations**: Active or pinned vector/BM25 generations (`context_index_activations`, `context_index_pins`) are permanently protected.

---

## 4. CLI Interface & Exit Codes

Integrated into the primary CLI runner (`python -m job_automation ops ...`):

| Command | Arguments | Exit Codes | Description |
|---|---|---|---|
| `ops capacity` | `[--config] [--data-root] [--destination] [--json]` | `0`: Normal<br>`1`: Warning or SF-04 unknown<br>`2`: Config error<br>`3`: Blocked | Measures volume free space against required reserves. Deduplicates same physical disks. |
| `ops cleanup preview` | `[--config] [--data-root] [--cutoff-days] [--json]` | `0`: Plan generated<br>`2`: Config error<br>`3`: Preflight failure | Generates immutable `CleanupPlan` with candidate hashes and store/policy fingerprints. |
| `ops cleanup apply` | `--plan <uuid> --plan-hash <hash> [--config] [--data-root] [--json]` | `0`: Success<br>`1`: Partial<br>`2`: Stale/invalidated/expired<br>`3`: IO/operational error | Executes reviewed plan under exclusive maintenance lock with reversible staging. |
| `ops backup create` | `[--config] [--data-root] [--destination] [--local-only] [--json]` | `0`: Complete (local + remote)<br>`1`: Local-only degraded<br>`2`: Missing destination<br>`3`: Backup failed | Creates atomic SQLite snapshot + file copies under writer lock. |
| `ops backup verify` | `--backup-dir <path> [--json]` | `0`: Valid<br>`2`: Dir not found<br>`3`: Checksum/integrity fail | Independently verifies `backup.complete`, PRAGMAs, and all SHA-256 hashes. |
| `ops restore plan` | `--backup-dir <path> --target <path> [--config] [--json]` | `0`: Valid plan<br>`2`: Non-empty target / config<br>`3`: Corrupt backup | Pre-flights restore into target, verifying containment and target emptiness. |
| `ops restore apply` | `--backup-dir <path> --target <path> [--config] [--json]` | `0`: Restored & relocated<br>`1`: Partial<br>`2`: Invalid target<br>`3`: Restore error | Restores database, copies files, and updates all internal path references. |

---

## 5. Disaster Recovery & Restoration Procedure

Full operator guidelines are documented in [`docs/operations/restore.md`](../operations/restore.md).

### Verification Evidence & Smoke Drill
The restore engine was verified via `tests/manual/operations_restore_smoke.py`, which:
1. Created an isolated synthetic source root and migrated database through v9.
2. Seeded canonical jobs, revisions, raw posting HTML files, CV generation requests, rendered PDF artifacts, context index directories, and pending sync outbox records.
3. Created a point-in-time backup and verified all SHA-256 hashes and SQLite integrity.
4. Restored the backup into a target root with native Windows spaces and German umlauts:  
   `C:\...\Wiederherstellung Prüfung\Target Restore 2026`
5. Proved that:
   - Database passed `PRAGMA integrity_check` and `PRAGMA foreign_key_check`.
   - `artifacts.local_path` and `artifacts.artifact_json` were rewritten to the new root.
   - `raw_postings.raw_payload_ref` and `context_index_generations.generation_dir` were rewritten to the new root.
   - Restored files matched their original SHA-256 hashes byte-for-byte.
   - Restored sync outbox and generation requests remained inert (no background network or model traffic).

---

## 6. Verification Summary & Test Suite

### Operations Test Suite (`tests/operations/` & `tests/test_cli_operations.py`)
- **49 unit & integration tests** in `tests/operations/`: **PASSED** (1.66s)
- **5 CLI tests** in `tests/test_cli_operations.py`: **PASSED** (0.93s)
- **1 manual disaster recovery smoke test** (`tests/manual/operations_restore_smoke.py`): **PASSED** (0.42s)

### Full Regression Suite
- Total repository test suite: **1365 tests passed** (49 new operations tests + 5 new CLI tests + 1311 existing tests across storage, contracts, identity, profile, policy, sources, evaluation, orchestration, and sync).

---

## 7. Verification Gaps & Remote Limitations

1. **SF-04 Export Handoff Missing**:
   - The Salesforce Developer Org metadata and candidate history export component (SF-04) is not yet implemented.
   - As designed, OPS-01 treats remote coverage as `LOCAL_ONLY_ABSENT_SF04` / `unknown`.
   - Backups created in this state have `completeness_status = "complete_local"` and report `exit code 1` (degraded/partial).
   - Remote capacity is reported as `unknown`, which logs an advisory note without blocking read-only local capacity inspection.
2. **Live Remote Import Gated**:
   - Full live disaster recovery of the Salesforce org (importing candidate notes, application history, and custom field overrides) requires the future SF-04 recovery procedure.
   - Restoration creates a candidate recovery package (`candidate_recovery_package.json`) and reconciliation diff, but does not perform live mutations on the remote org.
3. **Backup Physical Destination**:
   - Backup creation requires an explicit destination (`--destination` or `settings.backup.destination`).
   - If the backup destination is on the same physical volume as the data root, `failure_domain_evidence` explicitly records `is_same_disk = true` with warnings that a physical drive failure would destroy both source and backup.

