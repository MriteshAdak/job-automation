# SF-05 Architecture Specification: C13 Field Mapping & Ownership Dictionary

Document Reference: `docs/components/SF-05/mapping.md`  
Parent Component: [SF-05](../SF-05.md)  
Associated Contract: `C13` (`GenerationRequest`, `GenerationRequestObservation`, `RequestFieldMapping`)  
Version: `1.0`  
Date: **01 November 2026**  

---

## 1. Executive Overview

This document specifies the exact contract mapping, field dictionary, ownership classification, collision register, and compatibility gap ledger between the local job-automation worker's `C13` contract (`GenerationRequest` / `GenerationRequestObservation`) and the Salesforce DX `Generation_Request__c` custom object metadata.

The object model satisfies five strict architectural principles:
1. **Contract C13 Fidelity**: All fields defined in `C13` are represented directly or derived deterministically.
2. **Offline Worker Inspectability**: Requests can be created via standard Salesforce UI while the local worker process is offline without errors or dangling lookups.
3. **Candidate vs. Worker Privilege Separation**: A candidate creating a request has zero edit authority over worker operational or diagnostic fields; a worker servicing a request has zero edit authority over candidate creation inputs or candidate application progress on `Job__c`.
4. **Processing vs. Approval Semantics**: Request completion (`Ready_for_Review`) delivers generated artifacts (`Result_Artifact_Ref__c`) but does **not** constitute candidate approval of documents or advance application progress.
5. **Safe Failures & Error Visibility**: Preflight and operational failures record clear, sanitized diagnostic reasons, messages, and references visible in standard Salesforce layouts without exposing sensitive credentials or file system tokens.

---

## 2. Field Dictionary & Contract C13 Mapping

The custom object `Generation_Request__c` comprises 23 custom fields, an AutoNumber primary key `Name`, and standard platform audit fields.

| Salesforce API Name | Data Type & Length | Required / Nullable | Default Value | Contract C13 Property | Direction | Ownership & Modifiability | Description |
|---|---|---|---|---|---|---|---|
| `Name` | AutoNumber (`GR-{000000}`) | System Required | Auto | `None` (UI label) | SF $\rightarrow$ Local | Platform | Human-readable request identifier visible on page layouts and list views. |
| `Contract_Schema_Version__c` | Text(16) | Required | `"1.0"` | `schema_version` | SF $\rightarrow$ Local | Platform / Immutable | C13 schema compatibility marker. Immutable after creation. |
| `Client_Request_Key__c` | Text(255), Unique, CaseSensitive, External ID | Optional / Blank for UI | `None` | `client_request_key` | SF $\leftrightarrow$ Local | Producer / Immutable | External idempotency key. Optional in UI; immutable once populated. |
| `Job__c` | Lookup(`Job__c`, `deleteConstraint="Restrict"`) | Required | `None` | `canonical_job_id` | SF $\rightarrow$ Local | Candidate / Immutable | Restrict-delete lookup to target Job. Deletion of parent job is blocked while request exists. |
| `Document_Type__c` | Picklist (`cv`, `cover_letter`) | Required | `"cv"` | `document_type` | SF $\rightarrow$ Local | Candidate / Immutable | Explicit document category to generate. Immutable after insert. |
| `Language__c` | Picklist (`de`, `en`) | Required | `"de"` | `target_language` | SF $\rightarrow$ Local | Candidate / Immutable | Target natural language for generated document. Immutable after insert. |
| `Template_Id__c` | Text(80) | Required | `"default"` | `template_id` | SF $\rightarrow$ Local | Candidate / Immutable | Identifier of presentation template. Immutable after insert. |
| `Context_Strategy__c` | Picklist (`json`, `markdown`, `hybrid`) | Required | `"json"` | `context_strategy` | SF $\rightarrow$ Local | Candidate / Immutable | Context ingestion and prompt formatting strategy. Immutable after insert. |
| `Allow_Unavailable_Job__c` | Checkbox | Required | `false` | `allow_unavailable_job` | SF $\rightarrow$ Local | Candidate / Immutable | Strict false-by-default override allowing generation for closed/expired jobs. Immutable after insert. |
| `Predecessor_Request__c` | Lookup(`Generation_Request__c`, `deleteConstraint="Restrict"`) | Optional / Nullable | `None` | `predecessor_request_id` | SF $\rightarrow$ Local | Candidate / Immutable | Self-lookup linking deliberate regeneration to prior request. Self-reference prohibited. |
| `Status__c` | Picklist (`Pending`, `Running`, `Upload_Pending`, `Ready_for_Review`, `Failed`) | Required | `"Pending"` | `state` | SF $\leftrightarrow$ Local | Worker Controlled | Lifecycle state machine. Moves from `Pending` $\rightarrow$ `Running` $\rightarrow$ `Upload_Pending` $\rightarrow$ `Ready_for_Review` or directly to `Failed`. |
| `Worker_Claimed_At__c` | DateTime | Optional / Nullable | `None` | `claimed_at` | Local $\rightarrow$ SF | Worker Controlled | UTC timestamp when local worker claimed request. Required for `Running`, `Upload_Pending`, `Ready_for_Review`. |
| `Completed_At__c` | DateTime | Optional / Nullable | `None` | `completed_at` | Local $\rightarrow$ SF | Worker Controlled | UTC timestamp when worker finished processing. Required for `Ready_for_Review` and `Failed`. |
| `Frozen_Posting_Revision__c` | Text(64) | Optional / Nullable | `None` | `frozen_input_versions.posting_revision_id` | Local $\rightarrow$ SF | Worker / Immutable | Hash or UUID of the posting revision snapshot used during generation. |
| `Frozen_Profile_Version__c` | Text(64) | Optional / Nullable | `None` | `frozen_input_versions.profile_version_id` | Local $\rightarrow$ SF | Worker / Immutable | Version identifier of candidate profile snapshot used. |
| `Frozen_Policy_Version__c` | Text(64) | Optional / Nullable | `None` | `frozen_input_versions.policy_version_id` | Local $\rightarrow$ SF | Worker / Immutable | Version identifier of governance/tailoring policy used. |
| `Frozen_Template_Version__c` | Text(64) | Optional / Nullable | `None` | `frozen_input_versions.template_version_id` | Local $\rightarrow$ SF | Worker / Immutable | Version identifier of template snapshot used. |
| `Local_Artifact_Ref__c` | Text(255) | Optional / Nullable | `None` | `local_artifact_ref` | Local $\rightarrow$ SF | Worker Controlled | Opaque local file storage bundle or artifact locator. |
| `Result_Artifact_Ref__c` | Text(255) | Optional / Nullable | `None` | `result_artifact_ref` | Local $\rightarrow$ SF | Worker Controlled | Salesforce ContentVersion ID or document storage locator for delivered artifact. Required for `Ready_for_Review`. |
| `Error_Category__c` | Text(64) | Optional / Nullable | `None` | `error.category` | Local $\rightarrow$ SF | Worker Controlled | High-level taxonomy category (`validation`, `job_unavailable`, `rate_limit`, etc.). |
| `Error_Reason__c` | Text(255) | Optional / Nullable | `None` | `error.reason` | Local $\rightarrow$ SF | Worker Controlled | Short machine-readable reason code for failure. Required for `Failed`. |
| `Error_Message__c` | LongTextArea(2000) | Optional / Nullable | `None` | `error.message` | Local $\rightarrow$ SF | Worker Controlled | Sanitized human-readable diagnostic message. Stripped of paths and credentials. |
| `Error_Ref__c` | Text(255) | Optional / Nullable | `None` | `error.error_ref` | Local $\rightarrow$ SF | Worker Controlled | Opaque local diagnostic log correlation ID or incident reference. |
| `Operation_Marker__c` | Text(64) | Optional / Nullable | `None` | `None` (Sync metadata) | Local $\rightarrow$ SF | Worker Controlled | Idempotency token for worker update writes. |

---

## 3. Ownership & Privilege Classification

Field authority is strictly partitioned into three non-overlapping groups enforced both by Salesforce Field-Level Security (FLS) in Permission Sets and by Salesforce Validation Rules:

```
+-----------------------------------------------------------------------------------------+
|                                    GENERATION REQUEST                                   |
+------------------------------------+----------------------------------------------------+
| CANDIDATE / CREATOR OWNED          | WORKER OWNED                                       |
| (Job_Generation_Requester)         | (Job_Automation_Worker)                            |
|                                    |                                                    |
|  - Job__c (Lookup)                 |  - Status__c                                       |
|  - Document_Type__c                |  - Worker_Claimed_At__c                            |
|  - Language__c                     |  - Completed_At__c                                 |
|  - Template_Id__c                  |  - Frozen_Posting_Revision__c                      |
|  - Context_Strategy__c             |  - Frozen_Profile_Version__c                       |
|  - Allow_Unavailable_Job__c        |  - Frozen_Policy_Version__c                        |
|  - Predecessor_Request__c          |  - Frozen_Template_Version__c                      |
|  - Client_Request_Key__c (Optional)|  - Local_Artifact_Ref__c                           |
|                                    |  - Result_Artifact_Ref__c                          |
|                                    |  - Error_Category__c                               |
|                                    |  - Error_Reason__c                                 |
|                                    |  - Error_Message__c                                |
|                                    |  - Error_Ref__c                                    |
|                                    |  - Operation_Marker__c                             |
|                                    |                                                    |
| Rules: Read/Create, Writable on    | Rules: Read/Edit, Candidate fields Read-Only,      |
| insert, Read-Only after insert.    | Operational fields Read-Write.                     |
+------------------------------------+----------------------------------------------------+
| IMMUTABLE TECHNICAL IDENTITY                                                            |
|  - Contract_Schema_Version__c (Default "1.0", Immutable)                                |
|  - Client_Request_Key__c (Unique, External ID, Immutable once set)                      |
|  - Frozen_*_Version__c (Immutable once populated by worker)                             |
+-----------------------------------------------------------------------------------------+
```

### 3.1 Candidate Boundary Rules
1. Candidates have `Read` and `Create` object-level permissions on `Generation_Request__c`.
2. Candidates **do not** have `Edit` or `Delete` permissions on `Generation_Request__c`.
3. Candidate-owned fields are editable during `Create` (insert) only.
4. Validation Rule `Immutable_Creation_Inputs` rejects any subsequent update to creation inputs once the record exists:
   ```salesforce
   NOT(ISNEW()) && (
       ISCHANGED(Job__c) ||
       ISCHANGED(Document_Type__c) ||
       ISCHANGED(Language__c) ||
       ISCHANGED(Template_Id__c) ||
       ISCHANGED(Context_Strategy__c) ||
       ISCHANGED(Allow_Unavailable_Job__c) ||
       ISCHANGED(Predecessor_Request__c)
   )
   ```

### 3.2 Worker Boundary Rules
1. Worker has `Read` and `Edit` object-level permissions on `Generation_Request__c`.
2. Worker **does not** have `Create` or `Delete` permissions on `Generation_Request__c`.
3. Worker has FLS `read-only` on candidate creation fields (`Job__c`, `Document_Type__c`, `Language__c`, etc.) and candidate tracking fields on `Job__c` (`Application_Progress__c`, `Candidate_Notes__c`, etc.).
4. Worker has FLS `read-write` on operational and diagnostic fields (`Status__c`, `Worker_Claimed_At__c`, `Completed_At__c`, `Frozen_*`, `Result_Artifact_Ref__c`, `Error_*`).
5. Validation Rule `Frozen_Versions_Immutable` ensures that once the worker writes frozen snapshot IDs during claim, they cannot be modified.

---

## 4. Collision Register & Resolution Semantics

| Collision / Race Scenario | Detection Mechanism | Resolution Behavior | Architectural Invariant |
|---|---|---|---|
| **External Client Key Replay** | Observation presents identical `Client_Request_Key__c` and matching `salesforce_request_id` or job/options. | Admitter returns the existing `GenerationRequest` idempotently. No duplicate processing. | Exactly-once admission per unique external intent. |
| **External Client Key Conflict** | Observation presents identical `Client_Request_Key__c` with a differing remote Salesforce record ID or differing `canonical_job_id`. | Admitter rejects with `ClassifiedError.validation("already mapped")`. Observation is quarantined. | Two different Salesforce records can never reuse the same nonblank client key. |
| **Salesforce Duplicate Key Insert** | External caller attempts to insert a record with an existing `Client_Request_Key__c`. | Salesforce database blocks transaction natively via `unique="true"` and `caseSensitive="true"`. | Uniqueness enforced at platform database layer. |
| **Self-Referential Predecessor** | Record created with `Predecessor_Request__c` pointing to its own ID. | Validation rule `No_Self_Predecessor` evaluates `Id == Predecessor_Request__c` and rejects insert/update. | A generation cannot be its own lineage ancestor. |
| **Cascade Delete Hazard** | User deletes parent `Job__c` or predecessor `Generation_Request__c`. | Lookups specify `deleteConstraint="Restrict"`. Salesforce blocks deletion with `DELETE_FAILED`. | Parent deletion cannot cascade or leave orphaned generation audit trails. |
| **Preflight Job Unavailable** | Target `Job__c` is `CLOSED`, `EXPIRED`, or `UNAVAILABLE`, and `Allow_Unavailable_Job__c == false`. | Admitter / Poller moves request directly from `Pending` $\rightarrow$ `Failed` with `Error_Reason__c = "job_unavailable"`. `Worker_Claimed_At__c` and `Frozen_*` remain null. | Ineligible work is never claimed or marked `Running`. |
| **Malformed Boolean Override** | User inputs string `"false"`, `"0"`, or malformed value for `Allow_Unavailable_Job__c`. | Admitter applies `_parse_bool_strict`. Only explicit boolean `True` or string `"true"` enables override. | String `"false"` is strictly false, never truthy. |

---

## 5. Compatibility Gap Ledger

| Contract C13 Item | Salesforce Metadata Item | Gap / Difference Analysis | Remediation & Handling |
|---|---|---|---|
| UUID format (`request_id`) | AutoNumber `Name` (`GR-{000000}`) + Salesforce 18-char `Id` | Salesforce custom objects require either AutoNumber or Text for `Name`. Local storage requires UUID. | Local `request_id` is derived deterministically via UUIDv5 from `(org_id, canonical_salesforce_id)` or passed via `local_request_id`. |
| Enum picklists (`document_type`, `context_strategy`, `language`) | Standard Restricted Picklist fields | Salesforce picklists are validated against restricted value sets. | Picklist definitions match C13 enum strings exactly (`cv`, `cover_letter`; `json`, `markdown`, `hybrid`; `de`, `en`). |
| Local file paths in errors | `Error_Message__c` Text(2000) | Local Windows file paths (e.g. `C:\Users\...`) and tokens must not leak into Salesforce. | `RequestFieldMapping.sanitize_error_message()` strips bearer tokens, credentials, and Windows absolute paths prior to projection. |
| Opaque artifact bundles | `Local_Artifact_Ref__c` Text(255) | Local bundle storage paths should remain opaque identifiers rather than absolute host paths. | Uses bundle IDs or content hash references rather than raw host file system paths. |

