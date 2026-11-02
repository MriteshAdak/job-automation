# Disaster Recovery and Restoration Procedure (OPS-01)

This document establishes the verified operational procedure for restoring a Job Automation deployment from a verified backup set into an isolated environment on native Windows.

---

## 1. Safety and Isolation Principles

1. **Isolation First**: A backup is **never** restored directly over an active, populated runtime data root. Restorations are performed into a clean, dedicated target directory.
2. **Pre-flight Integrity Verification**: Before any file is restored, the backup set's manifest (`manifest.json`), completion marker (`backup.complete`), file checksums (SHA-256), and SQLite database integrity are verified.
3. **Inert Restoration**: Restoration performs **no outbound network requests**, Salesforce synchronization, or LLM inference. All sync outbox states, generation requests, and artifacts remain preserved in their restored state.
4. **Deterministic Path Relocation**: Any absolute filesystem paths recorded in database records (e.g. `raw_postings.raw_payload_ref`, `artifacts.local_path`, `context_index_generations.generation_dir`) are safely relocated to the target directory. Content hashes, semantic IDs, and URLs remain immutable.
5. **No Credential Portability**: Backups intentionally exclude OAuth tokens and credentials. Credentials must be re-established after activation.

---

## 2. Pre-Restore Checklist

1. **Identify the Backup**:
   Locate the desired backup directory (e.g. `D:\Backups\JobAutomation\backup_<uuid>_<timestamp>`).
2. **Verify Backup Health**:
   Execute the verification command:
   ```powershell
   python -m job_automation ops backup verify --backup-dir "D:\Backups\JobAutomation\backup_<uuid>_<timestamp>"
   ```
   Ensure the output reports `Integrity: OK`.
3. **Select Empty Target Data Root**:
   Choose an empty folder outside the source repository, e.g.:
   `C:\Users\Example\Job Automation Restored\Bewerbungen`

---

## 3. Step-by-Step Restoration Procedure

### Step 1: Generate and Review Restore Plan

Run the preflight planning command to verify target capacity and path mapping:

```powershell
python -m job_automation ops restore plan `
    --backup-dir "D:\Backups\JobAutomation\backup_<uuid>_<timestamp>" `
    --target "C:\Users\Example\Job Automation Restored\Bewerbungen"
```

Expected output:
```text
Restore Plan: VALID
  Backup ID:        34fef80f-c742-4d93-8bdd-d26fcefbeaff
  Source Data Root: C:\Users\Example\Job Automation Daten\Bewerbungen
  Target Data Root: C:\Users\Example\Job Automation Restored\Bewerbungen
  Files to Restore: 142
  Total Bytes:      48,291,042
  Capacity Status:  OK
```

### Step 2: Apply Restore

Execute the restore to copy files, update database paths, and verify constraints:

```powershell
python -m job_automation ops restore apply `
    --backup-dir "D:\Backups\JobAutomation\backup_<uuid>_<timestamp>" `
    --target "C:\Users\Example\Job Automation Restored\Bewerbungen"
```

During this step:
- The target directory acquires an exclusive `OwnerKind.MAINTENANCE` lock (`.deployment.lock`).
- All managed files are copied and byte-verified.
- Database records are updated to reference the new paths.
- `PRAGMA integrity_check` and `PRAGMA foreign_key_check` are executed.

### Step 3: Post-Restore Verification

Verify that all contracts, historical profiles, and artifacts are readable:

```powershell
# 1. Check configuration against restored root
python -m job_automation config check --data-root "C:\Users\Example\Job Automation Restored\Bewerbungen"

# 2. Inspect storage migration status
python -m job_automation storage status --data-root "C:\Users\Example\Job Automation Restored\Bewerbungen"

# 3. Verify profiles and facts
python -m job_automation profile list --data-root "C:\Users\Example\Job Automation Restored\Bewerbungen"
```

---

## 4. Salesforce Candidate Recovery Procedure (SF-04)

Restoring the local database does **not** push changes to Salesforce. To reconcile candidate-owned data:

### Same-Org Recovery
If restoring to the same Salesforce organization:
1. Candidate snapshots in the restored database contain the candidate's notes, progress, and interview dates as of the backup cut.
2. The recovery comparator compares `source_modification_token` (`SystemModstamp`):
   - If candidate notes were edited in Salesforce **after** the backup cut, the newer Salesforce edit is **retained** by default.
   - If records were deleted or need restoration, review the candidate recovery package generated during restore.

### Replacement-Org Recovery
If restoring to a fresh or replacement Salesforce organization:
1. Deploy custom objects (`Company__c`, `Job__c`) and fields (SF-01).
2. Upsert Companies by `Canonical_Company_Id__c`.
3. Upsert Jobs by `Canonical_Job_Id__c`.
4. Import candidate-owned fields using the candidate recovery package.
5. Re-map Salesforce record IDs in the local `sync_remote_mappings` table.

---

## 5. Deployment Activation and Rollback

### Activation
To switch active execution to the restored environment:
1. Ensure the prior worker process on the old data root is stopped.
2. Update the `data_root` field in your active `config/app.json`:
   ```json
   {
     "data_root": "C:\\Users\\Example\\Job Automation Restored\\Bewerbungen"
   }
   ```
3. Restart the background worker or scheduled task.

### Rollback
If any verification check fails:
1. Do **not** point `config/app.json` to the target directory.
2. Delete the target directory `C:\Users\Example\Job Automation Restored\Bewerbungen`.
3. Your original data root remains completely untouched and unaffected.

