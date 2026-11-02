# SF-04 — Recovery Procedures, Conflict Reconciliation, and Verification

Component ID: **SF-04 / Recovery and Verification**  
Requirement References: **R08, R09, R16**  
Planning Reference: [`docs/stories/SF-04.md`](file:///c:/Users/mrite/Projects/job-search/docs/stories/SF-04.md#sf-04-s05--verify-exports-through-ops-01-backup-and-recovery)  
Implementation: [`src/job_automation/salesforce/export_verification.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/salesforce/export_verification.py), [`src/job_automation/operations/remote_recovery.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/operations/remote_recovery.py)

---

## 1. Independent Offline Verification (`verify_export_package`)

The export verifier validates packaged artifacts completely independently of exporter runtime memory:

1. **Manifest Integrity**: Verifies `manifest.json` schema, export UUID, org binding, and mapping version.
2. **Containment & Path Traversal Prevention**: Rejects relative paths containing `..`, absolute drive paths, or symlink escapes.
3. **Cryptographic Integrity**: Recomputes SHA-256 digests and checks exact byte lengths for all declared package files.
4. **JSONL Syntax & Record Integrity**: Reads every line of `.jsonl` files and validates row-level contracts.
5. **UUID Uniqueness**: Validates that all canonical Company and Job UUIDs are valid and unique within the export package.
6. **Parent Company Relationship Closure**: Verifies that every Job referencing a Company lookup has its parent Company present in `companies.jsonl`.
7. **Issue Ledger Evaluation**: Checks `issues.jsonl`. If fatal issues exist (`invalid_job_uuid`, `missing_parent_company`), the package cannot be promoted to `complete`.

---

## 2. Recovery Procedures: Same-Org vs Replacement-Org

### 2.1 Same-Org Disaster Recovery
When restoring candidate data back into the same Salesforce org:
1. Target org ID matches `source_org_id`.
2. Existing Salesforce `Id` references are valid.
3. **Conflict Detection**:
   - Compares the `SystemModstamp` token of live Salesforce records against the export package tokens (parsed accurately as UTC datetime instants).
   - If the remote token is chronologically newer than the package snapshot: **the newer candidate edit in Salesforce takes precedence by default** (`resolution = "retain_newer_remote_edit"`).
   - If tokens match but field values diverge: flagged as `requires_review_diverging_fields`.
   - If record is missing in Salesforce: marked for restoration.

### 2.2 Replacement-Org Disaster Recovery
When migrating to a new Developer Edition or Production org:
1. Deploy project metadata first via reviewed DX deployment (`salesforce/manifest/package.xml`).
2. Generate recovery package with `target_org_id = "<new_org_id>"`.
3. In this package:
   - Remote Salesforce record IDs (`Id`) are cleared (`remote_record_id = None`).
   - `Canonical_Company_Id__c` and `Canonical_Job_Id__c` UUIDs are preserved.
   - Company parent records are upserted first using `Canonical_Company_Id__c`.
   - Job records are upserted using `Canonical_Job_Id__c`, re-linking the `Company__c` lookup via the new org's Company record ID.

---

## 3. OPS-01 Integration & Native Windows Verification Drill

SF-04 seamlessly integrates with OPS-01's backup and disaster recovery architecture:

1. **Packaging**: `create_backup` accepts `export_dir`, copies export artifacts into `remote_export/` in the backup staging tree, and records file hashes in `BackupManifest.files`.
2. **Verification**: `verify_backup` validates SQLite committed WAL snapshots (`PRAGMA integrity_check`, `PRAGMA foreign_key_check`) and verifies `remote_export` files byte-for-byte.
3. **Isolated Restoration Drill**:
   - The backup set was restored into an isolated Windows target path with spaces and German umlauts:  
     `...\Wiederherstellung Prüfung\Drill 2026 Restore\`
   - Result:
     - SQLite database verified clean (`status = "succeeded"`, `integrity_check_passed = True`, `foreign_key_check_passed = True`).
     - Restored `remote_export/manifest.json`, `companies.jsonl`, and `jobs.jsonl` verified byte-for-byte.
     - Entire restored dataset remained completely inert (zero outbound network requests, zero sync mutations).

