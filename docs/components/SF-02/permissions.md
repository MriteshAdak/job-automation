# SF-02 Supporting Document: Worker Permission Set and Least-Privilege Access Matrix

Document ID: **SF-02-PERMISSIONS**  
Status: **IMPLEMENTED (Metadata Authored & Verified Offline)**  
Observation Date: **01 November 2026**  
Scope: **SF-02-S03 (Prepare and Verify Worker Object, Field and Row Permissions)**  
Direct Requirements: **R08, R15**

---

## 1. Least-Privilege Permission Architecture

The integration worker requires access to create and update company and job tracking records, while being strictly prevented from modifying user-owned candidate progress decisions or accessing unrelated standard business objects.

```
+-------------------------------------------------------------------------------+
|                        Salesforce Developer Edition Org                       |
|                                                                               |
|  +-----------------------------+         +---------------------------------+  |
|  |     Job_Automation_Worker   |         |        Candidate Identity       |  |
|  |       (Permission Set)      |         |     (Candidate / Admin UI)      |  |
|  +-----------------------------+         +---------------------------------+  |
|                 |                                         |                   |
|                 v                                         v                   |
|  +-----------------------------+         +---------------------------------+  |
|  |         Company__c          |         |              Job__c             |  |
|  |  * Read, Create, Edit       |         |  * Read, Create, Edit           |  |
|  |  * Canonical_Company_Id__c  |         |  * Canonical_Job_Id__c (R/W)    |  |
|  |  * Company_Name__c (R/W)    |         |  * Machine Fields (R/W)         |  |
|  |  * Marker & Version (R/W)   |         |  * Candidate Fields (READ-ONLY) |  |
|  +-----------------------------+         +---------------------------------+  |
|                                                                               |
|  [DENIED / STRICTLY EXCLUDED]                                                 |
|  * Record Deletion (allowDelete=false on all objects)                         |
|  * Unrelated Objects: Account, Contact, Lead, Opportunity, Case, User         |
|  * System Privileges: ModifyAllData, ViewAllData, CustomizeApplication        |
+-------------------------------------------------------------------------------+
```

---

## 2. Object-Level Access Matrix

| Object Name | API Name | allowRead | allowCreate | allowEdit | allowDelete | viewAllRecords | modifyAllRecords | Justification / Boundary |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **Company** | `Company__c` | **True** | **True** | **True** | **False** | **False** | **False** | Upsert and read back employer records. Deletion strictly forbidden. |
| **Job** | `Job__c` | **True** | **True** | **True** | **False** | **False** | **False** | Upsert and read back vacancy records. Deletion strictly forbidden. |
| **Account** | `Account` | False | False | False | False | False | False | Unrelated standard CRM object; excluded. |
| **Contact** | `Contact` | False | False | False | False | False | False | Unrelated standard CRM object; excluded. |
| **Lead** | `Lead` | False | False | False | False | False | False | Unrelated standard CRM object; excluded. |
| **Opportunity** | `Opportunity` | False | False | False | False | False | False | Unrelated standard CRM object; excluded. |
| **Case** | `Case` | False | False | False | False | False | False | Unrelated standard CRM object; excluded. |

---

## 3. Field-Level Security (FLS) Allowlist

### 3.1 `Company__c` Fields

| Field API Name | Data Type | Readable | Editable | Purpose & Restriction |
|---|---|:---:|:---:|---|
| `Canonical_Company_Id__c` | Text(36) | **True** | **True** | External ID upsert key; immutability enforced by validation rule. |
| `Company_Name__c` | Text(255) | **True** | **True** | Extended employer name (when Name is autonumber). |
| `Machine_Sync_Version__c` | Number(18, 0) | **True** | **True** | Monotonic entity sequence counter preventing stale updates. |
| `Sync_Operation_Marker__c` | Text(255) | **True** | **True** | Operation UUID for lost-response reconciliation. |
| `Name` | Standard Name | *Governed by Object* | Standard Name field; no FLS required in permission set. |

### 3.2 `Job__c` Machine Fields (Read-Write)

| Field API Name | Data Type | Readable | Editable | Purpose & Restriction |
|---|---|:---:|:---:|---|
| `Canonical_Job_Id__c` | Text(36) | **True** | **True** | External ID upsert key; immutability enforced by validation rule. |
| `Job_Title__c` | Text(255) | **True** | **True** | Extended job title (when Name is autonumber). |
| `Company__c` | Lookup(Company__c) | **True** | **True** | Parent employer relationship. |
| `Availability__c` | Picklist | **True** | **True** | Machine posting availability (`Active`, `Unavailable`, etc.). |
| `Assessment_Disposition__c` | Picklist | **True** | **True** | Machine fit evaluation (`Eligible`, `Review`, `Rejected`). |
| `Assessment_Reasons__c` | LongTextArea | **True** | **True** | Machine criteria evaluation summary. |
| `Relevance_Score__c` | Number(18, 6) | **True** | **True** | Machine relevance score (nullable for clean clearing). |
| `Score_Scale__c` | Text(255) | **True** | **True** | Relevance scoring scale (e.g. "0-100"). |
| `Last_Evaluated_At__c` | DateTime | **True** | **True** | UTC evaluation timestamp. |
| `Source_URLs__c` | LongTextArea | **True** | **True** | Newline-separated posting source URLs. |
| `Sync_Operation_Marker__c` | Text(255) | **True** | **True** | Operation UUID for lost-response reconciliation. |
| `Machine_Sync_Version__c` | Number(18, 0) | **True** | **True** | Monotonic entity sequence counter. |
| `Name` | Standard Name | *Governed by Object* | Standard Job Title field. |

### 3.3 `Job__c` Candidate-Owned Fields (STRICTLY READ-ONLY)

Per requirement **R08** and the candidate preservation contract:
- The worker must be able to **read** candidate fields during pre-update queries to back up candidate notes and decisions locally.
- The worker must **never be able to modify** candidate fields through REST API calls.

| Field API Name | Data Type | Readable | Editable | Enforced Restriction |
|---|---|:---:|:---:|---|
| `Application_Progress__c` | Picklist | **True** | **FALSE** | Defaults to `New` via SF-01 metadata on insert; worker cannot edit. |
| `Candidate_Notes__c` | LongTextArea | **True** | **FALSE** | Candidate reflections; worker cannot edit or clear. |
| `Candidate_Decision__c` | Text(255) | **True** | **FALSE** | Candidate manual override; worker cannot edit or clear. |
| `Follow_Up_Date__c` | Date | **True** | **FALSE** | Scheduled candidate follow-up; worker cannot edit or clear. |
| `Interview_Date__c` | Date | **True** | **FALSE** | Scheduled candidate interview; worker cannot edit or clear. |

---

## 4. Administrative and System Permissions

| Permission Name | Granted in Permission Set | Reason & Security Analysis |
|---|:---:|---|
| `ViewSetup` ("View Setup and Configuration") | **True** | Required by official Salesforce REST documentation to access `/services/data/vXX.X/limits`. Allows reading daily API call consumption. |
| `ModifyAllData` | **False** | Blanket administrative mutation privilege; strictly denied. |
| `ViewAllData` | **False** | Blanket administrative visibility privilege; strictly denied. |
| `CustomizeApplication` | **False** | Schema and metadata authoring privilege; strictly denied. |
| `ManageUsers` | **False** | User administration privilege; strictly denied. (Storage usage metrics requiring ManageUsers remain unavailable to worker). |

