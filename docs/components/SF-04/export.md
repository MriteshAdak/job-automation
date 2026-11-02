# SF-04 — Candidate-Owned Data Export Service and Formats

Component ID: **SF-04 / Export Service**  
Requirement References: **R08, R09, R16**  
Planning Reference: [`docs/stories/SF-04.md`](file:///c:/Users/mrite/Projects/job-search/docs/stories/SF-04.md#sf-04-s04--capture-candidate-owned-data-and-relationships)  
Implementation: [`src/job_automation/salesforce/export_service.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/salesforce/export_service.py), [`src/job_automation/salesforce/portability_records.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/salesforce/portability_records.py)

---

## 1. Export Package Structure & Artifacts

All exported candidate data and relationships are written into a versioned, portable package directory outside source control (`local_data/exports/export_<uuid>_<scan_id>/`):

```
export_<export_uuid>_<scan_id>/
├── manifest.json       # Top-level signed export manifest with hashes and status
├── companies.jsonl     # Exported Company__c parent records
├── jobs.jsonl          # Exported Job__c records with candidate fields and lookups
├── snapshots.jsonl     # Local historical candidate snapshots from SQLite
├── history.jsonl       # Salesforce Job__History change records (if enabled)
└── issues.jsonl        # Actionable gaps, missing parents, or malformed UUIDs
```

All data files use UTF-8 JSON Lines (`.jsonl`), preserving raw multi-line candidate notes and German characters (`ä, ö, ü, ß`) without Unicode escape sequences.

---

## 2. Keyset Pagination & Coverage Completeness

### 2.1 Keyset Pagination Architecture
To guarantee full-scope coverage across large record sets:
- The exporter sorts records by `Id ASC` and iterates using `WHERE Id > '{last_seen_id}' LIMIT {batch_size}`.
- Unlike single-page queries, **the exporter does not terminate when a query returns `done = true`** if `len(records) == batch_size`. Keyset iteration continues until a query returns fewer records than the requested batch size.
- Query failures on subsequent pages record explicit issues, preserving previously captured pages and flagging the manifest completeness as `partial`.

### 2.2 Selected Columns
- **`Company__c`**: `Id`, `Canonical_Company_Id__c`, `Name`, `Company_Name__c`, `SystemModstamp`.
- **`Job__c`**: `Id`, `Canonical_Job_Id__c`, `Company__c` (lookup), `Name`, `Job_Title__c`, `Availability__c`, `Assessment_Disposition__c`, `SystemModstamp`, and all 5 candidate fields:
  - `Application_Progress__c`
  - `Candidate_Notes__c`
  - `Candidate_Decision__c`
  - `Follow_Up_Date__c`
  - `Interview_Date__c`

---

## 3. Relationship Closure & Identity Preservation

1. **Separation of Identifiers**:
   - `Canonical_Job_Id__c` and `Canonical_Company_Id__c` (UUID Text 36) remain the authoritative stable keys.
   - Remote `Id` and `Company__c` lookup IDs are recorded strictly as provenance.
2. **Company Lookup Resolution**:
   - During export, the remote `Company__c` lookup ID is remapped to the parent's `Canonical_Company_Id__c`.
   - If a referenced parent company is missing from the org or scope, an actionable `missing_parent_company` gap is recorded in `issues.jsonl`, and completeness is marked `partial`.
3. **Candidate Field Nulls vs Missing Fields**:
   - Explicit `None` in the source record is serialized as JSON `null`.
   - A field omitted from the Salesforce response payload is flagged in `manifest.missing_fields`.

---

## 4. Local Snapshot & Field History Preservation

- **Durable Local Snapshots**: Historical snapshots stored in SQLite `candidate_snapshots` table are exported to `snapshots.jsonl` to ensure that intermediate notes and progress transitions that predate the export scan remain recoverable.
- **Remote Field History**: If `Job__History` is queryable on the org, historical field tracking entries are exported to `history.jsonl`. If history tracking is disabled or permission is denied, an explicit omission note is added to `manifest.omissions` without failing the export.

