# SF-01 Supporting Document: Scoped Deployment, Migration, and Recovery Plan

Document ID: **SF-01-MIGRATION**  
Status: **PROPOSAL & DEPLOYMENT GATEWAY SPECIFICATION**  
Date: **01 November 2026**  
Scope: **SF-01-S06 (Prepare Migration and Scoped Deployment/Recovery Plans)**  
Direct Requirements: **R04, R08, R16** (with **R14** Windows operational discipline and **R15** credential privacy constraint)  

---

## 1. Deployment Overview & Package Boundaries

This deployment plan governs the safe rollout of SF-01 metadata into the target Salesforce Developer Org (`dev-main`) once target identity is confirmed and SF-02 authorization is granted.

### 1.1 Strict Deployment Safeguards
1. **No Wildcard Manifests**: All manifests strictly list explicit member names. `<members>*</members>` is forbidden.
2. **No Standard Profiles**: Modifying or deploying `profiles/Admin.profile-meta.xml` is prohibited to prevent clobbering org-wide policies.
3. **Additive First**: New objects and custom fields are deployed additively. Existing data is audited before applying uniqueness or requiredness constraints.
4. **No Destructive Manifests**: No automated deletion of metadata.
5. **No Direct Overwrite of Populated Candidate Fields**: Candidate notes, progress, and decisions are backed up locally prior to any sync.

---

## 2. Scoped Member Allowlist (`salesforce/manifest/sf01.xml`)

The deployable package is defined in `salesforce/manifest/sf01.xml` (source format in `salesforce/force-app/main/default/`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Package xmlns="http://soap.sforce.com/2006/04/metadata">
    <types>
        <members>Company__c</members>
        <members>Job__c</members>
        <name>CustomObject</name>
    </types>
    <types>
        <members>Company__c.Canonical_Company_Id__c</members>
        <members>Company__c.Company_Name__c</members>
        <members>Company__c.Sync_Operation_Marker__c</members>
        <members>Company__c.Machine_Sync_Version__c</members>
        <members>Job__c.Canonical_Job_Id__c</members>
        <members>Job__c.Job_Title__c</members>
        <members>Job__c.Company__c</members>
        <members>Job__c.Availability__c</members>
        <members>Job__c.Assessment_Disposition__c</members>
        <members>Job__c.Assessment_Reasons__c</members>
        <members>Job__c.Relevance_Score__c</members>
        <members>Job__c.Score_Scale__c</members>
        <members>Job__c.Last_Evaluated_At__c</members>
        <members>Job__c.Source_URLs__c</members>
        <members>Job__c.Sync_Operation_Marker__c</members>
        <members>Job__c.Machine_Sync_Version__c</members>
        <members>Job__c.Application_Progress__c</members>
        <members>Job__c.Candidate_Notes__c</members>
        <members>Job__c.Candidate_Decision__c</members>
        <members>Job__c.Follow_Up_Date__c</members>
        <members>Job__c.Interview_Date__c</members>
        <name>CustomField</name>
    </types>
    <types>
        <members>Company__c.Canonical_Company_Id_Format</members>
        <members>Company__c.Canonical_Company_Id_Immutable</members>
        <members>Job__c.Canonical_Job_Id_Format</members>
        <members>Job__c.Canonical_Job_Id_Immutable</members>
        <name>ValidationRule</name>
    </types>
    <version>60.0</version>
</Package>
```

---

## 3. Phased Deployment & Migration Sequence

### Step 1: Pre-Flight Audit & Backup
1. Confirm target org My Domain URL and verify edition in Developer Org (`dev-main`).
2. Run read-only describe inspection via Python gateway or Salesforce CLI to verify whether `Company__c` or `Job__c` already exist.
3. If objects already exist:
   - Export all existing records (`Id`, `Name`, and any populated fields) to a secure local JSON backup.
   - Run duplicate checks on candidate external IDs.
   - If duplicates or collisions exist, resolve before applying uniqueness.

### Step 2: Additive Metadata Deployment (Company First)
1. Deploy `Company__c` custom object and fields:
   - `Canonical_Company_Id__c`
   - `Company_Name__c`
   - `Sync_Operation_Marker__c`
   - `Machine_Sync_Version__c`
2. Deploy `Company__c` validation rules (`Canonical_Company_Id_Format`, `Canonical_Company_Id_Immutable`).

### Step 3: Additive Metadata Deployment (Job Second)
1. Deploy `Job__c` custom object and fields:
   - `Canonical_Job_Id__c`
   - `Job_Title__c`
   - `Company__c` (Lookup referencing `Company__c`)
   - Machine fields (`Availability__c`, `Assessment_Disposition__c`, etc.)
   - Candidate fields (`Application_Progress__c` with default `New`, `Candidate_Notes__c`, etc.)
2. Deploy `Job__c` validation rules (`Canonical_Job_Id_Format`, `Canonical_Job_Id_Immutable`).

### Step 4: Configuration Validation & Outbox Cutover
1. Validate compatibility of the deployed schema using `metadata_parser`:
   ```powershell
   & ".\.venv\Scripts\python.exe" -m pytest tests\salesforce\metadata\test_metadata_validation.py
   ```
2. Enable sync outbox workers in `SYNC-01`.
3. Monitor initial batch writes to verify that `Application_Progress__c` defaults to `New` and no candidate fields are overwritten.

---

## 4. Rollback and Disaster Recovery Procedures

### 4.1 Abort Conditions
The deployment must be immediately halted and rolled back to offline/paused status if:
- Validation rules fail on existing legacy data during deployment.
- Existing custom triggers or flows in the org produce unintended errors on insert.
- External ID uniqueness constraint fails due to pre-existing duplicate keys.

### 4.2 Recovery Checklist
1. **Halt Publication**: Set `enabled = false` in `config/salesforce.json` to immediately stop outbound HTTP requests.
2. **Preserve Data Integrity**: Never delete custom objects that contain newly synced or candidate-edited records.
3. **Restore Candidate State**: If candidate fields were inadvertently modified, restore values from local SQLite backup snapshots (`CandidateBackupService`).
4. **Reconcile Pending Writes**: Run `sync_reconciliation` to match pending outbox operations against remote markers without replaying duplicate writes.

