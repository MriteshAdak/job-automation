# SF-04 — Scoped Salesforce Metadata Retrieval and Versioning

Component ID: **SF-04 / Metadata**  
Requirement References: **R08, R14, R15, R16**  
Planning Reference: [`docs/stories/SF-04.md`](file:///c:/Users/mrite/Projects/job-search/docs/stories/SF-04.md#sf-04-s03--retrieve-and-version-project-metadata-safely)

---

## 1. Retrieval Allowlist Manifest (`salesforce/manifest/sf04-retrieve.xml`)

To prevent collecting unrelated org configuration, standard objects, or administrative profiles, metadata retrieval is strictly governed by an explicit package manifest:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Package xmlns="http://soap.sforce.com/2006/04/metadata">
    <!-- Project Application -->
    <types><members>Job_Tracker</members><name>CustomApplication</name></types>
    <!-- External Client App (OAuth 2.0 PKCE) -->
    <types><members>Job_Automation_Client</members><name>ExternalClientApplication</name></types>
    <types><members>Job_Automation_Client</members><name>ExtlClntAppOauthSettings</name></types>
    <types><members>Job_Automation_Client</members><name>ExtlClntAppOauthConfigurablePolicies</name></types>
    <!-- Custom Objects -->
    <types><members>Company__c</members><members>Job__c</members><name>CustomObject</name></types>
    <!-- Mapped Custom Fields (4 Company, 17 Job = 21 Total) -->
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
    <!-- Validation Rules -->
    <types>
        <members>Company__c.Canonical_Company_Id_Format</members>
        <members>Company__c.Canonical_Company_Id_Immutable</members>
        <members>Job__c.Canonical_Job_Id_Format</members>
        <members>Job__c.Canonical_Job_Id_Immutable</members>
        <name>ValidationRule</name>
    </types>
    <!-- Candidate Tracking UI Components (SF-03) -->
    <types><members>Job__c.JA_Tracking</members><name>CompactLayout</name></types>
    <types>
        <members>Job__c.JA_Eligible_Jobs</members>
        <members>Job__c.JA_Review_Jobs</members>
        <members>Job__c.JA_Shortlist</members>
        <members>Job__c.JA_Applications</members>
        <members>Job__c.JA_Follow_Ups_Due</members>
        <members>Job__c.JA_Follow_Ups_Upcoming</members>
        <members>Job__c.JA_Tracked_History</members>
        <name>ListView</name>
    </types>
    <types>
        <members>Job__c-JA Candidate Tracking</members>
        <members>Company__c-JA Company Overview</members>
        <name>Layout</name>
    </types>
    <types><members>JA_Job_Tracking</members><name>FlexiPage</name></types>
    <types><members>Company__c</members><members>Job__c</members><name>CustomTab</name></types>
    <types><members>JA_Jobs</members><name>ReportType</name></types>
    <types><members>Job_Tracker</members><name>ReportFolder</name></types>
    <types>
        <members>Job_Tracker/JA_Eligible_Review</members>
        <members>Job_Tracker/JA_Shortlist</members>
        <members>Job_Tracker/JA_Applications</members>
        <members>Job_Tracker/JA_Follow_Ups</members>
        <name>Report</name>
    </types>
    <!-- Worker Permission Set -->
    <types><members>Job_Automation_Worker</members><name>PermissionSet</name></types>
    <version>60.0</version>
</Package>
```

---

## 2. Ownership Classification & Policy (`metadata-ownership.json`)

Metadata members are categorized into strict ownership classes:
- **`project-owned`**: Authored tracking objects, custom fields, validation rules, worker permission set, ECA configuration, and SF-03 UI components.
- **`shared-dependency`**: Platform dependencies such as the standard `User` entity (referenced read-only).
- **`unrelated-protected`**: Standard objects (`Account`, `Contact`, `Lead`, `Opportunity`), broad administrative profiles (`System Administrator`, `Admin`, `Standard User`), unrelated Connected Apps, and certificates.
- **`unknown`**: Any file or member not explicitly registered.

---

## 3. Retrieval Staging & Security Audit

Retrieval is performed into an isolated staging root (`tmp/metadata_staging/`) via PowerShell:
```powershell
.\scripts\windows\retrieve_salesforce_metadata.ps1 -TargetOrg "dev-main"
```

The staging workflow enforces:
1. **CLI Presence Verification**: Checks whether `sf` or `sfdx` is installed. If absent, reports `PENDING` safely without crashing.
2. **Quarantine of Unowned Children**: Object containers frequently pull extra nested fields or unrelated components. The audit engine identifies any component not in `metadata-ownership.json` and moves it to quarantine.
3. **Secret Scanning**: Scans text payloads for client secrets, private keys, session tokens, or passwords (`SECRET_PATTERNS`).
4. **Broad Profile Rejection**: Traps and quarantines any standard or administrative profile files.
5. **Deterministic Digest**: Computes a repeatable SHA-256 digest of all project-owned files for change tracking.
6. **Zero Blind Overwriting**: Does not automatically replace `salesforce/force-app/main/default`. All promotions require explicit operator review.

