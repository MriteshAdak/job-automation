# SF-06 Contracts, Options Catalog & Invocable Action Specification

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../../IMPLEMENTATION_BLUEPRINT.md) §4 (Contracts C13, C14), §6 (SF-06)  
Planning Reference: [docs/stories/SF-06.md](../../stories/SF-06.md)  
Prerequisite Handoff: [SF-05](../SF-05.md) (`Generation_Request__c` Schema & Permissions)

---

## 1. Action Surface & Flow Definitions

SF-06 provides two primary QuickActions on the `Job__c` Lightning record page:

| QuickAction API Name | Label | Action Type | Target Flow | Context Record |
|---|---|---|---|---|
| `Job__c.JA_Generate_CV` | Generate CV | Flow | `JA_Generate_CV` | `recordId` (`Job__c` Id) |
| `Job__c.JA_Generate_Cover_Letter` | Generate Cover Letter | Flow | `JA_Generate_Cover_Letter` | `recordId` (`Job__c` Id) |

### 1.1 Screen Flow Architecture
Both Screen Flows share an identical structural pattern:
1. **Input Variable**: `recordId` (String, Input, `Job__c` record ID).
2. **Options Screen**:
   - `Language_Input`: Radio buttons (`de` [default: German], `en` [English]).
   - `Template_Input`: Radio buttons populated from compatible enabled choices.
   - `Context_Strategy_Input`: Radio buttons (`json` [default: Full JSON context], `rag` [RAG evidence chunks]).
   - `Allow_Unavailable_Job_Input`: Checkbox, defaults strictly to `false`.
3. **Invocable Action Call**: Invokes Apex class `JA_GenerationSubmit`.
4. **Feedback Screen**: Displays truthful processing outcome, AutoNumber request name (`GR-{000000}`), and guidance reminding candidate that drafts remain safely queued while the Windows local worker is offline.

---

## 2. Generation Options Catalog (`JA_Generation_Option__mdt`)

Options are managed as Salesforce Custom Metadata (`JA_Generation_Option__mdt`), enabling declarative configuration of approved template layouts without code modifications:

| Field API Name | Type | Properties | Description |
|---|---|---|---|
| `Template_Id__c` | Text(80) | Required | Canonical layout identifier matching local generation engine. |
| `Document_Type__c` | Text(50) | Required | Supported document type (`cv` or `cover_letter`). |
| `Allowed_Languages__c` | Text(255) | Required | Comma-separated ISO language codes (e.g. `de,en`). |
| `Is_Enabled__c` | Checkbox | Default `true` | Whether this template is active for candidate selection. |
| `Catalog_Version__c` | Text(50) | Required | Local catalog snapshot version (e.g. `1.0.0`). |
| `Sort_Order__c` | Number(4,0) | Optional | Order of appearance in UI selectors. |

### Baseline Approved Template Records
- `JA_Generation_Option.CV_Basic_A4`: `layout-cv-basic-a4`, doc: `cv`, langs: `de,en`, sort: 1
- `JA_Generation_Option.CV_Compact_A4`: `layout-cv-compact-a4`, doc: `cv`, langs: `de,en`, sort: 2
- `JA_Generation_Option.Letter_Basic_A4`: `layout-letter-basic-a4`, doc: `cover_letter`, langs: `de,en`, sort: 1
- `JA_Generation_Option.Letter_Compact_A4`: `layout-letter-compact-a4`, doc: `cover_letter`, langs: `de,en`, sort: 2

---

## 3. Invocable Submission Service (`JA_GenerationSubmit.cls`)

### 3.1 Input Contract (`SubmitRequest`)
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `jobId` | Id | Yes | - | Salesforce ID of target `Job__c`. |
| `documentType` | String | Yes | - | `cv` or `cover_letter`. |
| `language` | String | No | `'de'` | Target document language (`de` or `en`). |
| `templateId` | String | Yes | - | Approved layout template ID. |
| `contextStrategy` | String | No | `'json'` | Context construction strategy (`json` or `rag`). |
| `allowUnavailableJob` | Boolean | No | `false` | Explicit consent to draft for unavailable job. |
| `creationMode` | String | No | `'reuse_or_create'` | Submission mode: `'reuse_or_create'` or `'regenerate'`. |
| `predecessorRequestId` | Id | No (Yes for regen) | `null` | Predecessor request ID for deliberate regeneration. |
| `submissionToken` | String | Yes | - | Client-side idempotency token. |
| `catalogVersion` | String | No | `'1.0.0'` | Catalog version snapshot. |

### 3.2 Output Contract (`SubmitResult`)
| Property | Type | Description |
|---|---|---|
| `outcome` | String | `created`, `reused_active`, `replayed`, `confirmation_required`, `rejected`, `retryable_conflict`. |
| `requestId` | Id | Salesforce record ID of the resulting `Generation_Request__c`. |
| `requestName` | String | AutoNumber display name (e.g. `GR-000042`). |
| `processingState` | String | Observed processing status (`Pending`, `Running`, `Upload_Pending`, `Ready_for_Review`, `Failed`). |
| `message` | String | User-facing status and actionable guidance. |
| `recordUrl` | String | Relative URL to inspect the request record. |
| `isSuccess` | Boolean | `true` if request was created, reused, or replayed. |

---

## 4. Submission Receipts (`JA_Generation_Submission__c`)

Submission receipts provide durable, client-scoped deduplication and replay coordination without relying on browser cache or external databases:

| Field API Name | Type | Attributes | Description |
|---|---|---|---|
| `Submission_Key__c` | Text(255) | External ID, Unique, Case-Sensitive, Required | Deterministic key: `UserId:Token`. |
| `Payload_Version__c` | Text(50) | Required | Schema version (`"1.0"`). |
| `Intent_Payload__c` | LongTextArea(32768) | Required | Canonical JSON serialization of submitted parameters. |
| `Request__c` | Lookup(`Generation_Request__c`) | `deleteConstraint="Restrict"`, Required | Linked generation request. |
| `Outcome__c` | Text(50) | Required | Outcome: `created`, `reused_active`, `replayed`. |

---

## 5. Behavioral Invariants & Decision Rules

1. **Active Duplicate Reuse**:
   - An active request has status in `['Pending', 'Running', 'Upload_Pending']`.
   - If an active request exists with identical candidate scope (`CreatedById`), `Job__c`, `Document_Type__c`, `Language__c`, `Template_Id__c`, `Context_Strategy__c`, and `Allow_Unavailable_Job__c`, the service **reuses** the existing request and binds the submission receipt to it.
   - Deterministic tie-breaking: selects the oldest active request by `CreatedDate ASC, Id ASC`.
   - Status, timestamps, and frozen inputs are **never mutated**.
2. **Terminal History Gate**:
   - If only terminal matching requests exist (`Ready_for_Review` or `Failed`), ordinary submission returns `confirmation_required`.
   - Candidate must confirm deliberate regeneration with a designated predecessor request.
3. **Deliberate Regeneration**:
   - Requires `creationMode = "regenerate"` and valid `predecessorRequestId`.
   - Links `Predecessor_Request__c` to predecessor request; generates a brand new request record with separate AutoNumber identity.
   - Options (language, template, strategy) may deliberately differ.
4. **Unavailable Job Consent Gating**:
   - `Allow_Unavailable_Job__c` defaults strictly to `false`.
   - If target `Job__c.Availability__c == 'Unavailable'` and override is `false`, returns `confirmation_required`.
   - If target job has prior `job_unavailable` failure history, ordinary submission is gated with `confirmation_required`. Explicit candidate override and deliberate regeneration are required.
5. **Atomic Compound Transaction**:
   - Row lock on parent `Job__c` via `SELECT ... FOR UPDATE` serializes concurrent submissions.
   - Both `Generation_Request__c` and `JA_Generation_Submission__c` persist atomically in the same database transaction; any failure triggers full rollback via `Database.rollback(sp)`.
   - Row lock timeouts return `retryable_conflict`.
6. **Zero Localhost / Decoupled Worker Invariant**:
   - No Flow, Apex, or QuickAction performs HTTP callouts or connects to localhost.
   - Requests are queued as `Pending` in Salesforce, awaiting pull-based discovery by the local Windows worker process.

