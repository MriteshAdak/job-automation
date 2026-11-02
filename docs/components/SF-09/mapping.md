# SF-09 Schema Mapping, Field Ownership & Projection Contract

Component ID: **SF-09**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../../IMPLEMENTATION_BLUEPRINT.md), C15 and §§5–10, R17  
Handoff Reference: [docs/components/SF-09.md](../SF-09.md)  
Planning Reference: [docs/stories/SF-09.md](../../stories/SF-09.md)

---

## 1. Overview & Data Architecture

SF-09 provides the Salesforce custom schema and ingestion boundary for search pipeline run summaries (`Run_Summary__c`).

It guarantees:
1. **Single Completion Entitlement**: Each logical run UUID receives exactly one notification entitlement, keyed canonically by `{org_id}:{run_id}`.
2. **Decoupled Mutable/Immutable Fields**: First-completion snapshots (`First_*`) freeze initial results upon admission, while latest-result fields update silently on resumed revisions.
3. **Strict Machine vs Server Ownership**: Summary delivery workers write only delivery projection fields; server-managed completion, claim, attempt, and receipt markers are strictly read-only for worker identities.
4. **Local Diagnostic Privacy**: Verbose stack traces, local paths, and bearer tokens stay local in SQLite; only bounded, sanitized plain text is projected to Salesforce.

---

## 2. Detailed Field Specification & Ownership Matrix

All 47 custom fields on `Run_Summary__c`:

| Field API Name | Data Type | Properties & Bounds | Write Owner | Purpose & Semantics |
|---|---|---|---|---|
| `Run_Id__c` | `Text(36)` | **External ID, Unique (CI)**, Required | Worker (Insert) | Normalized lowercase UUID identifying the logical run. |
| `Contract_Schema_Version__c` | `Text(16)` | Max 16 chars | Worker | C15 contract schema version (e.g. `1.0`). |
| `Mapping_Version__c` | `Text(16)` | Max 16 chars | Worker | Projection mapping version (`1.0` or `1.1`). |
| `Start_Time__c` | `DateTime` | UTC ISO-8601 | Worker | UTC timestamp when the pipeline run started. |
| `End_Time__c` | `DateTime` | UTC ISO-8601 | Worker | UTC timestamp when the pipeline run ended. |
| `Duration_Seconds__c` | `Number(18, 3)` | Precision 18, Scale 3, >= 0 | Worker | Total elapsed execution time in seconds. |
| `Pipeline_Status__c` | `Picklist` | Restricted: `success`, `partial`, `failed` | Worker | Authoritative terminal outcome of the search run. |
| `Headline__c` | `Text(255)` | App bound 255 chars | Worker | Sanitized human-readable outcome headline. |
| `Summary_Text__c` | `LongTextArea(32768)` | App bound 2,000 chars | Worker | Sanitized narrative summary text. |
| `Source_Postings_Count__c` | `Number(18, 0)` | Integer, >= 0 | Worker | Total observed source postings (not canonical jobs). |
| `Canonical_Jobs_New__c` | `Number(18, 0)` | Integer, >= 0 | Worker | Count of newly discovered canonical vacancies. |
| `Canonical_Jobs_Updated__c` | `Number(18, 0)` | Integer, >= 0 | Worker | Count of existing jobs updated with revisions. |
| `Canonical_Jobs_Duplicate__c`| `Number(18, 0)` | Integer, >= 0 | Worker | Duplicate observations matched to known jobs. |
| `Eligible_Count__c` | `Number(18, 0)` | Integer, >= 0 | Worker | Canonical jobs evaluated with Eligible disposition. |
| `Review_Count__c` | `Number(18, 0)` | Integer, >= 0 | Worker | Canonical jobs evaluated with Review disposition. |
| `Rejected_Count__c` | `Number(18, 0)` | Integer, >= 0 | Worker | Canonical jobs evaluated with Rejected disposition. |
| `Sync_Succeeded__c` | `Number(18, 0)` | Integer, >= 0 | Worker | Logical C12 job sync operations succeeded. |
| `Sync_Failed__c` | `Number(18, 0)` | Integer, >= 0 | Worker | Logical C12 job sync operations failed. |
| `Quarantined_Count__c` | `Number(18, 0)` | Integer, >= 0 | Worker | Raw source records quarantined due to schema errors. |
| `Sources_Attempted__c` | `LongTextArea(32768)` | App bound 1,000 chars | Worker | Comma-separated list of safe source keys attempted. |
| `Sources_Succeeded__c` | `LongTextArea(32768)` | App bound 1,000 chars | Worker | Comma-separated list of safe source keys succeeded. |
| `Sources_Failed__c` | `LongTextArea(32768)` | App bound 1,000 chars | Worker | Comma-separated list of safe source keys failed. |
| `Source_Counts__c` | `LongTextArea(32768)` | App bound 2,000 chars | Worker | JSON dictionary of source keys to posting counts. |
| `Stage_Counts__c` | `LongTextArea(32768)` | App bound 2,000 chars | Worker | JSON dictionary of pipeline stages, counts, units. |
| `Coverage_Status__c` | `Picklist` | Restricted: `complete`, `partial`, `unavailable` | Worker | Configured source scope coverage assessment. |
| `Projection_Truncated__c` | `Checkbox` | Default: `false` | Worker | Flag indicating if source/stage lists were truncated. |
| `Error_Summary__c` | `LongTextArea(32768)` | App bound 500 chars, Nullable | Worker | Sanitized actionable error digest; nullable on recovery. |
| `Pending_Work_Summary__c` | `LongTextArea(32768)` | App bound 500 chars, Nullable | Worker | Bounded pending work summary for partial runs. |
| `Revision__c` | `Number(18, 0)` | Monotonic positive integer | Worker | Monotonic revision counter preventing stale overwrites. |
| `Payload_Hash__c` | `Text(64)` | SHA-256 hex string | Worker | Canonical SHA-256 over delivery projection fields. |
| `Is_First_Completion__c` | `Checkbox` | Default: `false` | Worker (Hint) | Optional client hint; server admission remains authoritative. |
| `First_Completion_Key__c` | `Text(80)` | **External ID, Unique (CI)**, Required | **Server** | `{org_id}:{run_id}` canonical entitlement key. |
| `First_Payload_Hash__c` | `Text(64)` | SHA-256 hex string | **Server** | Immutable SHA-256 fingerprint of first completion payload. |
| `First_Completed_At__c` | `DateTime` | UTC ISO-8601 | **Server** | UTC timestamp of first completed terminal execution. |
| `First_Status__c` | `Picklist` | Restricted: `success`, `partial`, `failed` | **Server** | Immutable terminal status snapshot. |
| `First_Headline__c` | `Text(255)` | Max 255 chars | **Server** | Immutable headline snapshot. |
| `First_Summary_Text__c` | `LongTextArea(32768)` | Max 2,000 chars | **Server** | Immutable narrative summary snapshot. |
| `Completion_Recorded_At__c`| `DateTime` | UTC ISO-8601 | **Server** | Timestamp when first completion was admitted into Salesforce. |
| `Notification_Recipient__c`| `Lookup(User)` | `deleteConstraint="SetNull"` | **Server** | Resolved candidate user from `JA_Notification_Config__c`. |
| `Notification_Status__c` | `Picklist` | Restricted: `none`, `pending`, `dispatching`, `confirmed`, `failed`, `unknown`, `suppressed` | **Server** | Dispatch state machine lifecycle status. |
| `Notification_Claim_Id__c` | `Text(80)` | Max 80 chars | **Server** | Unique serialized pre-send claim token. |
| `Notification_Attempt_Count__c`| `Number(18, 0)` | Integer, >= 0 | **Server** | Count of dispatch attempts executed. |
| `Notification_Last_Attempt_At__c`| `DateTime`| UTC ISO-8601 | **Server** | Timestamp of most recent dispatch attempt. |
| `Notification_Next_Attempt_At__c`| `DateTime`| UTC ISO-8601 | **Server** | Scheduled retry timestamp for pre-send failures. |
| `Notification_Receipt_Id__c`| `Text(80)` | Max 80 chars | **Server** | Platform delivery confirmation receipt ID. |
| `Notification_Accepted_At__c`| `DateTime`| UTC ISO-8601 | **Server** | Timestamp when notification was accepted. |
| `Notification_Error_Code__c`| `Text(80)` | Max 80 chars | **Server** | Allowlisted error classification code. |

---

## 3. Mapping Versions: 1.0 vs 1.1 Reconciliation

SF-09 supports both AUTO-03 1.0 delivery projections and extended 1.1 projections:

1. **Mapping 1.0 Baseline**:
   - Sends core counters, headline, summary text, status, start/end times, and revision hash.
   - Sets `Notification_Status__c = 'pending'` on first completion hint.
   - SF-09 server guard validates 1.0 payloads, canonicalizes completion key, and freezes first snapshot.
2. **Mapping 1.1 Extensions**:
   - Adds `Contract_Schema_Version__c`, `Mapping_Version__c`, `Coverage_Status__c`, `Projection_Truncated__c`.
   - Sends structured `Source_Counts__c` and `Stage_Counts__c` JSON blocks.
   - Sends explicit `null` to clear `Error_Summary__c` and `Pending_Work_Summary__c` when a previously failed run resumes successfully.

