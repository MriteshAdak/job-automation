# SF-00 Supporting Document: Scoped Deployment Plan, Naming Resolutions, and Member Allowlist

Document ID: **SF-00-DEPLOYMENT-PLAN**  
Status: **PROPOSAL & DEPLOYMENT GATEWAY SPECIFICATION**  
Observation Date: **01 November 2026**  
Scope: **SF-00-S06 (Resolve Naming Risks and Propose Deployment Scope)**  
Direct Requirements: **R08, R16** (with **R15** credential privacy constraint)

---

## 1. Naming Collision Register and Resolution Strategy

To protect the user's existing Developer Org from accidental corruption, data loss, or namespace clobbering, every proposed object and field is evaluated against a strict disposition matrix:

| Proposed Logical Asset | Proposed API Name | Decision if Confirmed Absent | Decision if Compatible & Project-Owned | Decision if Incompatible or Unrelated | Downstream Owner |
|---|---|---|---|---|---|
| **Company Entity** | `Company__c` | Deploy clean custom object with External ID and sync markers. | Reuse existing `Company__c`; deploy only missing fields. | **Rename / Isolate**: Deploy as `JS_Company__c`. Update `config/sync.json` (`company_object: "JS_Company__c"`). Protect unrelated object. | **SF-01** |
| **Job Vacancy** | `Job__c` | Deploy clean custom object with External ID, lookup, and mapped fields. | Reuse existing `Job__c`; deploy only missing fields. | **Rename / Isolate**: Deploy as `JS_Job__c`. Update `config/sync.json` (`job_object: "JS_Job__c"`). Protect unrelated object. | **SF-01** |
| **Job Title Field** | `Name` | Standard Name field (Text 255). | Standard Name field. | If `Name` is Autonumber, deploy custom field `Title__c` (Text 255) and configure `config/sync.json` (`title_field: "Title__c"`). | **SF-01** |
| **External IDs** | `Canonical_Company_Id__c`, `Canonical_Job_Id__c` | Deploy Text(255), External ID, Unique. | Verify uniqueness. If not unique, run data deduplication before enforcing. | Deploy with project prefix if collision exists. | **SF-01** |
| **Reconciliation Markers** | `Sync_Operation_Marker__c`, `Machine_Sync_Version__c` | Deploy on **both** `Company__c` and `Job__c`. | Reuse or deploy if missing. | Add missing fields without touching existing fields. | **SF-01** |
| **Integration Permission Set** | `Job_Automation_Worker` | Deploy clean permission set with minimal CRUD/FLS. | Inspect assignments; update permissions. | Rename to `Job_Automation_Worker_v2`. | **SF-02** |
| **External Client App** | `Job_Automation_Client` | Register clean ECA with OAuth refresh token flow. | Reuse existing ECA if client ID is accessible. | Create new dedicated ECA. | **SF-02** |

---

## 2. Logical-to-Physical Mapping Proposal (`config/sync.json`)

The following physical configuration is recommended for `config/sync.json` (conforming to `SyncMappingConfig` schema 1.0):

```json
{
  "schema_version": "1.0",
  "mapping_version": "1.0",
  "expected_org_id": "<CONFIRMED_ORG_ID>",
  "company_object": "Company__c",
  "company_external_id_field": "Canonical_Company_Id__c",
  "company_name_field": "Name",
  "job_object": "Job__c",
  "job_external_id_field": "Canonical_Job_Id__c",
  "job_company_lookup_field": "Company__c",
  "title_field": "Name",
  "availability_field": "Availability__c",
  "disposition_field": "Assessment_Disposition__c",
  "reason_field": "Assessment_Reasons__c",
  "score_field": "Relevance_Score__c",
  "score_scale_field": "Score_Scale__c",
  "last_evaluated_field": "Last_Evaluated_At__c",
  "source_urls_field": "Source_URLs__c",
  "sync_marker_field": "Sync_Operation_Marker__c",
  "sync_version_field": "Machine_Sync_Version__c",
  "disposition_mapping": {
    "eligible": "Eligible",
    "review": "Review",
    "rejected": "Rejected"
  },
  "availability_mapping": {
    "active": "Active",
    "not_seen": "Not Seen",
    "unavailable": "Unavailable",
    "unknown": "Unknown"
  },
  "candidate_fields": [
    "Application_Progress__c",
    "Candidate_Notes__c",
    "Candidate_Decision__c",
    "Follow_Up_Date__c",
    "Interview_Date__c"
  ]
}
```

*Note: If the live schema describe reveals that `Name` on `Job__c` is an Autonumber, `"title_field"` will be switched to `"Title__c"`.*

---

## 3. Scoped Deployment Member Allowlist

Future deployment packages authored by downstream components must strictly adhere to this member allowlist:

### 3.1 SF-01 Schema Package (`salesforce/main/default/objects/`)
- `objects/Company__c/Company__c.object-meta.xml`
- `objects/Company__c/fields/Canonical_Company_Id__c.field-meta.xml`
- `objects/Company__c/fields/Sync_Operation_Marker__c.field-meta.xml`
- `objects/Company__c/fields/Machine_Sync_Version__c.field-meta.xml`
- `objects/Job__c/Job__c.object-meta.xml`
- `objects/Job__c/fields/Canonical_Job_Id__c.field-meta.xml`
- `objects/Job__c/fields/Company__c.field-meta.xml`
- `objects/Job__c/fields/Availability__c.field-meta.xml`
- `objects/Job__c/fields/Assessment_Disposition__c.field-meta.xml`
- `objects/Job__c/fields/Assessment_Reasons__c.field-meta.xml`
- `objects/Job__c/fields/Relevance_Score__c.field-meta.xml`
- `objects/Job__c/fields/Score_Scale__c.field-meta.xml`
- `objects/Job__c/fields/Last_Evaluated_At__c.field-meta.xml`
- `objects/Job__c/fields/Source_URLs__c.field-meta.xml`
- `objects/Job__c/fields/Sync_Operation_Marker__c.field-meta.xml`
- `objects/Job__c/fields/Machine_Sync_Version__c.field-meta.xml`
- `objects/Job__c/fields/Application_Progress__c.field-meta.xml`
- `objects/Job__c/fields/Candidate_Notes__c.field-meta.xml`
- `objects/Job__c/fields/Candidate_Decision__c.field-meta.xml`
- `objects/Job__c/fields/Follow_Up_Date__c.field-meta.xml`
- `objects/Job__c/fields/Interview_Date__c.field-meta.xml`

### 3.2 SF-02 Security & Integration Package (`salesforce/main/default/permissionsets/`)
- `permissionsets/Job_Automation_Worker.permissionset-meta.xml`
- `externalclientapps/Job_Automation_Client.eca-meta.xml`

### 3.3 SF-03 User Interface Package (`salesforce/main/default/`)
- `tabs/Job__c.tab-meta.xml`
- `tabs/Company__c.tab-meta.xml`
- `applications/Job_Tracker.app-meta.xml`
- `layouts/Job__c-Job Layout.layout-meta.xml`
- `layouts/Company__c-Company Layout.layout-meta.xml`
- `flexipages/Job_Record_Page.flexipage-meta.xml`
- `listViews/Job__c.Eligible_Jobs.listView-meta.xml`
- `listViews/Job__c.Review_Queue.listView-meta.xml`

---

## 4. Strict Deployment Exclusions

The following assets are **explicitly excluded** from project metadata packages:
- **System Administrator Profile (`profiles/Admin.profile-meta.xml`)**: Modifying or deploying the standard Admin profile risks clobbering unrelated user permissions, password policies, and login IP ranges in the org. All integration permissions must be packaged in permission sets.
- **Unrelated Objects and Settings**: Standard objects (`Account`, `Contact`, `Lead`, `Opportunity`, `Case`) and unrelated custom objects must not be included.
- **Destructive Changes (`destructiveChanges.xml`)**: No automated deletion of existing metadata is permitted.
- **Wildcard Manifests**: `<members>*</members>` is strictly forbidden in `package.xml`.

---

## 5. Deployment Preflight Verification Gate

Before SF-01 or SF-02 deploys any metadata to the live org, the following preflight checklist must be verified:
1. **Target Org Binding Confirmed**: User has confirmed the intended My Domain URL.
2. **Authoritative Describe Completed**: Live describe confirms absence of name collisions (or confirms compatibility).
3. **Capacity Verified**: Live limits confirm sufficient data storage (> 1.0 MB available) and custom object slots (> 2 available).
4. **Pre-Deployment Backup Captured**: Any existing metadata sharing these object names has been backed up locally via SF-04.
5. **No Mutation Flag in SF-00**: SF-00 does not deploy metadata or create records.

