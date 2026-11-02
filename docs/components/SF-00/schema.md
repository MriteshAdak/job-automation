# SF-00 Supporting Document: Object, Field, and Semantic Ownership Inventory

Document ID: **SF-00-SCHEMA**  
Status: **PLANNED BASELINE (Live Describe Pending Authorization)**  
Observation Date: **01 November 2026**  
Scope: **SF-00-S02 (Inventory Relevant Objects, Fields, and Ownership)**  
Direct Requirements: **R04, R08, R16** (with **R15** credential privacy constraint)

---

## 1. Mapping Baseline & Required Field Specifications

The tracking architecture established in [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (§§4–5) and implemented in [SYNC-01](../components/SYNC-01.md) defines a decoupled, configurable mapping layer (`SyncMappingConfig`, loaded from `config/sync.example.json`).

The following table specifies the target physical schema requirements to support all Phase 0/1 sync operations:

### 1.1 `Company__c` Object Specification

| Field API Name | Data Type | Properties & Constraints | Semantic Ownership | Usage in Pipeline |
|---|---|---|---|---|
| `Canonical_Company_Id__c` | Text(255) | **External ID, Unique** (Case-Insensitive), Required | Machine | Stable UUID identifying the company. Target for REST upsert. |
| `Name` | Text(255) | Standard Name field, Required | Machine | Company legal/trade name. |
| `Sync_Operation_Marker__c` | Text(255) | Indexed Text | Machine | Operation UUID used for lost-response reconciliation. |
| `Machine_Sync_Version__c` | Number(18, 0) | Integer | Machine | Monotonic entity sequence counter preventing stale updates. |

### 1.2 `Job__c` Object Specification

| Field API Name | Data Type | Properties & Constraints | Semantic Ownership | Usage in Pipeline |
|---|---|---|---|---|
| `Canonical_Job_Id__c` | Text(255) | **External ID, Unique** (Case-Insensitive), Required | Machine | Stable UUID identifying the canonical vacancy. Target for REST upsert. |
| `Name` | Text(255) | Standard Name field, Required | Machine | Job vacancy title (unless Autonumber; see §3). |
| `Company__c` | Lookup(`Company__c`) | `deleteConstraint="SetNull"`, Clear on delete | Machine | Parent company link. Dynamically injected after Company upsert. |
| `Availability__c` | Picklist | Active, Not Seen, Unavailable, Unknown | Machine | Source observation availability. |
| `Assessment_Disposition__c` | Picklist | Eligible, Review, Rejected | Machine | Overall assessment outcome. |
| `Assessment_Reasons__c` | Long Text Area(32768) | Multi-line text | Machine | Human-readable bulleted criteria breakdown and evidence. |
| `Relevance_Score__c` | Number(5, 2) | Nullable, Decimal | Machine | Fit score from LLM assessment (null for rules-only). |
| `Score_Scale__c` | Text(50) | Nullable, Text | Machine | Scale identifier (e.g. "0-100"; null for rules-only). |
| `Last_Evaluated_At__c` | DateTime | UTC ISO-8601 | Machine | Timestamp of the most recent evaluation. |
| `Source_URLs__c` | Long Text Area(32768) | Multi-line text / URLs | Machine | Primary and alternate posting URLs. |
| `Sync_Operation_Marker__c` | Text(255) | Indexed Text | Machine | Operation UUID used for lost-response reconciliation. |
| `Machine_Sync_Version__c` | Number(18, 0) | Integer | Machine | Monotonic entity sequence counter preventing stale updates. |

### 1.3 Candidate-Owned Fields on `Job__c` (Protected Against Overwrite)

| Field API Name | Data Type | Default on Creation | Semantic Ownership | Protection Behavior |
|---|---|---|---|---|
| `Application_Progress__c` | Picklist | `New` (Configured in Org Metadata) | **Candidate** | Allowed values: `New`, `Review`, `Shortlisted`, `Applied`, `Interviewing`, `Offer`, `Rejected`, `Withdrawn`, `Archived`. Machine NEVER overwrites. |
| `Candidate_Notes__c` | Long Text Area(32768) | `null` | **Candidate** | Personal notes, interview prep, contacts. Protected. |
| `Candidate_Decision__c` | Picklist / Text(100) | `null` | **Candidate** | Manual override/decision. Protected. |
| `Follow_Up_Date__c` | Date | `null` | **Candidate** | Scheduled follow-up reminder. Protected. |
| `Interview_Date__c` | DateTime | `null` | **Candidate** | Scheduled interview date/time. Protected. |

---

## 2. Field Ownership Architecture and Preservation Rules

As mandated by blueprint §5 and verified in `SYNC-01`:

1. **Initial Publication Rule**:
   - Initial sync is triggered only for jobs evaluated as `Eligible` or `Review`. Confirmed `Rejected` jobs are stored locally in SQLite and are not published to Salesforce initially.
   - On initial creation, Salesforce object defaults populate `Application_Progress__c = 'New'`. The machine payload does NOT supply this default.
2. **Tracked Refresh Rule**:
   - When an existing tracked job is re-evaluated (including transitions to `Rejected` or `Unavailable`), machine-owned fields (`Availability__c`, `Assessment_Disposition__c`, `Assessment_Reasons__c`, `Last_Evaluated_At__c`, `Machine_Sync_Version__c`) are updated.
   - **Candidate-owned fields are never modified, nulled, or reset by machine updates.**
3. **Multi-Layer Protection in Application Code**:
   - `assert_no_candidate_fields(payload)`: Hard assertion before HTTP serialization.
   - `CandidateBackupService`: Scans remote jobs via `query_page` and takes durable SQLite snapshots of candidate fields before updates (Transaction T5).

---

## 3. Potential Collision Risks and Mapping Adaptations

Because the target environment is an existing Developer Org rather than a newly provisioned empty org, the following collision scenarios must be verified during live inspection:

| Scenario | Collision Risk | Diagnostic Check | Recommended Resolution |
|---|---|---|---|
| **Standard Name Field is Autonumber** | If an existing `Job__c` object has `Name` defined as Autonumber (`JOB-{0000}`), passing the job title string in `{"Name": "Senior Software Engineer"}` will fail with `CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY` or `INVALID_FIELD_FOR_INSERT_UPDATE`. | Inspect `Name.dataType` in Describe. | Map a dedicated custom field `Title__c` (Text 255) on `Job__c`, and update `config/sync.json` (`title_field: "Title__c"`). |
| **Existing Unrelated `Job__c` or `Company__c`** | The org may contain an existing custom object from a Trailhead module (e.g. Recruiting app, Project Management). Reusing an unrelated object could cause field type mismatches, missing required fields, or data pollution. | Inspect all fields, triggers, and validation rules on the existing object. | If unrelated, adopt a distinct project prefix: `JS_Job__c` and `JS_Company__c`. Update `config/sync.json` without modifying the unrelated object. |
| **External ID Uniqueness Constraints** | If `Canonical_Job_Id__c` or `Canonical_Company_Id__c` exists but is not marked `unique`, Salesforce REST upsert by external ID will fail if duplicates exist. | Check `field.externalId` and `field.unique` in Describe. | Ensure `unique=true` (case-insensitive). If duplicates exist in legacy data, a data cleanup step is required prior to applying the constraint. |
| **Restricted Picklists** | If `Availability__c` or `Assessment_Disposition__c` is marked as a restricted picklist and values differ in casing or spelling, upsert will fail with `INVALID_OR_NULL_FOR_RESTRICTED_PICKLIST`. | Inspect `picklistValues` and `restrictedPicklist` in Describe. | Ensure picklist values in org match `SYNC-01` mappings exactly: `Eligible`, `Review`, `Rejected`; `Active`, `Not Seen`, `Unavailable`, `Unknown`. |
| **Existing Automation Side Effects** | Existing Apex Triggers, Record-Triggered Flows, or Validation Rules on `Job__c` could enforce custom validation or overwrite fields during upsert. | Query `ToolingAPI` for `ApexTrigger` and `Flow` with `TriggerType='RecordAfterSave'`. | Exempt integration user via custom permission, or update validation rules to ignore machine sync payloads. |

---

## 4. Live Schema Describe Inspection Procedure

Once connection credentials are authenticated, the inspector must execute the following read-only API calls:

```http
# 1. Inspect global sObject list to verify object existence
GET /services/data/v60.0/sobjects/
Authorization: Bearer <token>

# 2. Describe Company__c (if present)
GET /services/data/v60.0/sobjects/Company__c/describe/
Authorization: Bearer <token>

# 3. Describe Job__c (if present)
GET /services/data/v60.0/sobjects/Job__c/describe/
Authorization: Bearer <token>
```

The output must be evaluated against the checklist in §1. If the objects do not exist, they are confirmed absent and clean deployment can proceed per SF-01.

