# SF-04 — Compact Data Conventions and Capacity Failure Matrix

Component ID: **SF-04 / Compact Data**  
Requirement References: **R08, R09, R16**  
Planning Reference: [`docs/stories/SF-04.md`](file:///c:/Users/mrite/Projects/job-search/docs/stories/SF-04.md#sf-04-s02--define-compact-data-conventions-and-capacity-failure-behavior)

---

## 1. Domain Separation: Salesforce vs Local Data

To prevent consuming the org's 5 MB storage quota while preserving forensic auditability and provenance, data placement is strictly partitioned:

| Data Class | Storage Location | Retention & Projection Rules |
|---|---|---|
| **Raw HTML / JSON Payloads** | Local Filesystem (`local_data/raw/`) | Full unmodified web content; SHA-256 hashed; never pushed to Salesforce. |
| **Normalized Descriptions** | Local SQLite (`normalized_postings`) | Complete multi-page vacancy text, requirements, qualifications. |
| **Model Prompts & Traces** | Local SQLite (`model_calls`, `model_results`) | Full LLM completion transcripts, token usage, extraction reasoning. |
| **Document Artifacts** | Local Filesystem (`local_data/artifacts/`) | Full generated CV and Cover Letter PDF/DOCX binaries, version history. |
| **Candidate Workspace Projection** | Salesforce (`Job__c`, `Company__c`) | Compact entity representation for tracking, review, and application workflows. |

### 1.1 Compact Salesforce Projection Schema

The fields synchronized to Salesforce comprise:
- **Canonical External IDs**: `Canonical_Job_Id__c` and `Canonical_Company_Id__c` (`Text(36)` UUIDs).
- **Display Names / Titles**: Standard `Name` (Text 80) and optional extended `Job_Title__c` / `Company_Name__c` (Text 255).
- **Parent Lookup**: `Company__c` relationship (`deleteConstraint="Restrict"`).
- **Availability**: Picklist (`Active`, `Not Seen`, `Unavailable`, `Unknown`).
- **Assessment Disposition**: Picklist (`Eligible`, `Review`, `Rejected`).
- **Concise Assessment Reasons**: Long Text Area (`Assessment_Reasons__c`, 32,768 chars) containing high-level criteria breakdown.
- **Score and Scale**: Numeric `Relevance_Score__c` and scale string (nullable).
- **Evaluation Timestamp**: UTC DateTime (`Last_Evaluated_At__c`).
- **Source URLs**: Observed posting URLs (`Source_URLs__c`, Long Text Area).
- **Reconciliation Tokens**: `Sync_Operation_Marker__c` and `Machine_Sync_Version__c`.
- **Candidate Workflow Fields**:
  - `Application_Progress__c` (Picklist, creation default `New`)
  - `Candidate_Notes__c` (Long Text Area, default blank)
  - `Candidate_Decision__c` (Text 255, default blank)
  - `Follow_Up_Date__c` (Date, default blank)
  - `Interview_Date__c` (DateTime, default blank)

---

## 2. Length Enforcement and Candidate Preservation

1. **No Silent Truncation**:
   - Machine fields exceeding metadata limits trigger visible validation errors rather than silent slicing.
   - Candidate notes, decisions, and dates are strictly preserved byte-for-byte.
2. **Preservation of Deliberate Clears**:
   - If the candidate deliberately clears notes or dates in Salesforce, those fields remain `None` / `null`. They are never defaulted back to `'New'` or repopulated by background synchronization.
3. **Continuous Tracking for Rejected Vacancies**:
   - Vacancies rejected by machine rules or candidate decision continue to receive machine availability updates (e.g. marking `Unavailable` when delisted). Capacity limits never archive or discard tracked jobs.

---

## 3. Capacity Failure Contract

When capacity thresholds are exceeded, the worker enforces non-destructive failure handling:

| Capacity Condition | Action Taken | Work Preservation Guarantee |
|---|---|---|
| **Warning Threshold Reached** | Logs diagnostic warnings; operations continue if passing individual headroom checks. | No records or files deleted; retention settings remain untouched. |
| **Data Storage Exhausted / Blocked** | Defers new publication steps in sync pipeline. Updates require validated budget. | Pending sync outbox steps remain queued; local normalized postings and assessments preserved. |
| **File Storage Exhausted / Blocked** | Generation worker pauses file delivery; leaves local artifacts in `upload_pending`. | Prior remote versions preserved; local artifact PDF/DOCX files remain intact. |
| **API Daily Quota Exhausted** | Halts outbound REST calls; sets backoff sleep timer (`recheck_delay_seconds = 300`). | Sync outbox and export scan checkpoints preserved; resumes when quota resets. |
| **Local Export Disk Space Low** | Halts export packaging before writing staging files; keeps previous verified export. | Last verified recovery export remains valid; no corrupted package committed. |
| **Server Rejection (403 / 500)** | Classifies error; applies bounded exponential backoff with jitter; halts on fatal errors. | Operations state preserved; no blind retry loops. |

