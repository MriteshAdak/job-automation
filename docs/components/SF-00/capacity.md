# SF-00 Supporting Document: Org Capacity, Storage, and API Allowances

Document ID: **SF-00-CAPACITY**  
Status: **PLANNED BASELINE & ZERO-BUDGET ARCHITECTURAL PROJECTIONS (Live Limits Pending Authorization)**  
Observation Date: **01 November 2026**  
Scope: **SF-00-S04 (Measure API, Storage, and Relevant Org Allowances)**  
Direct Requirements: **R14, R16** (with **R15** credential privacy constraint)

---

## 1. Developer Edition Published Baseline Allowances

Salesforce Developer Edition is a free, single-user environment provided for development and testing. It features tightly bounded storage and API quotas.

Per official Salesforce documentation (*Salesforce Developer Edition Limits* and *REST API Developer Guide: Limits*):

| Resource / Allowance Category | Published Developer Edition Maximum | Standard Allocation Unit | Measurement Method |
|---|---|---|---|
| **Daily API Requests (`DailyApiRequests`)** | 15,000 calls | Rolling 24-hour window | `/services/data/vXX.X/limits` or `Sforce-Limit-Info` header |
| **Data Storage (`DataStorageMB`)** | 5.0 MB | Megabytes (~2,560 standard records at 2 KB each) | Setup Storage Usage / Tooling API |
| **File Storage (`FileStorageMB`)** | 20.0 MB | Megabytes | Setup Storage Usage / Tooling API |
| **Custom Objects** | 400 | Custom Objects | Setup Object Manager / Limits |
| **Custom Fields per Custom Object** | 500 | Custom Fields | Setup Object Manager / Limits |
| **Streaming API Events** | 50,000 | 24-hour window | `/limits` |

> [!WARNING]
> Published edition defaults are baseline references, not verified measurements of the user's specific org. An existing org may already have consumed storage or custom objects from previous Trailhead modules, scratch org definitions, or file reporting applications. A live limits reading must be performed once authenticated.

---

## 2. Zero-Budget Capacity Analysis & Architectural Implications

The blueprint establishes that the monetary budget for this personal automation is **zero** ([R14](../../IMPLEMENTATION_BLUEPRINT.md#r14), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16)). Purchasing additional Salesforce storage or API packs is strictly out of scope.

This constraint dictates the following data placement rules:

### 2.1 Data Storage (5.0 MB Limit)
1. **The 2 KB Record Reality**:
   - Salesforce calculates custom object storage usage using a flat 2 KB per record convention, regardless of actual string length (except for very large rich text).
   - $5.0 \text{ MB} = 5,120 \text{ KB} \div 2 \text{ KB/record} = \mathbf{2,560 \text{ records total}}$ across all standard and custom objects in the entire org.
   - If existing apps (e.g. `ReportOnFiles` or Trailhead modules) already consume 1,500 records, only ~1,000 records remain.
2. **Architectural Enforcement**:
   - **Local Storage is the Authority for Bulk Data**: Raw job posting HTML, unstructured descriptions, full candidate profile snapshots, RAG vector embeddings, model evaluation benchmarks, and detailed execution logs **must remain in local SQLite** (`%LOCALAPPDATA%\JobAutomation\storage\job_search.db`).
   - **Selective Tracking Only**: Only jobs evaluated as `Eligible` or `Review` are synchronized to Salesforce. Confirmed `Rejected` jobs remain purely local.
   - **Storage Consumption Projection**:
     - Tracking 200 jobs + 100 companies = 300 records = **600 KB** (~11.7% of total org storage).
     - Tracking 500 jobs + 250 companies = 750 records = **1.5 MB** (~29.3% of total org storage).
   - This footprint is viable within a 5 MB Developer Org, provided older closed/archived applications are periodically purged or compacted (SF-04 / OPS-01).

### 2.2 File Storage (20.0 MB Limit)
1. **Phase 1 Document Drafting (GEN-06)**:
   - Generated CV and cover letter drafts are uploaded to Salesforce as `ContentVersion` / `ContentDocumentLink` for human review in Lightning Experience.
   - Typical rendered file sizes (DOCX + PDF):
     - Single tailored CV PDF: ~150 KB – 300 KB.
     - Single cover letter PDF: ~80 KB – 150 KB.
     - Combined pair per application: ~250 KB – 450 KB.
2. **Capacity Projection**:
   - 20 MB accommodates approximately **45 to 80 generated document pairs** before file storage is exhausted.
3. **Architectural Enforcement**:
   - The primary permanent repository for generated artifacts is the local Windows filesystem (`%LOCALAPPDATA%\JobAutomation\artifacts\`).
   - If Salesforce file storage reaches 85% capacity, the upload worker must mark drafts as `upload_pending` and alert the candidate to archive/prune older remote drafts, rather than failing silently or buying storage.

### 2.3 Daily API Requests (15,000 / 24 Hours)
1. **Pipeline Call Volume**:
   - Typical search run (50 new eligible/review jobs): ~50 Company upserts + 50 Job upserts = **100 calls**.
   - Tracked availability/status update run: ~50 update calls.
   - Candidate field backup scan (T5): ~1–5 SOQL query calls.
   - Total daily API consumption: **< 200 calls (< 1.5% of the 15,000 daily limit)**.
2. **Protection Against Quota Exhaustion**:
   - The Python gateway (`SFCLIENT-01`) enforces strict call budgets (`CallBudget`: max 6 total sends per operation, max 3 resource sends, 60s timeout).
   - Exponential backoff with jitter and respect for `Retry-After` headers prevent API hammer loops.

---

## 3. Live Capacity Inspection Procedure

To capture authoritative capacity figures once access is configured, execute the following procedure:

### 3.1 Via REST Limits Endpoint
```http
GET /services/data/v60.0/limits/
Authorization: Bearer <token>
```

Key fields to extract and record in `capacity.md`:
- `DailyApiRequests`: `Max`, `Remaining`
- `DataStorageMB`: `Max`, `Remaining`
- `FileStorageMB`: `Max`, `Remaining`
- `HourlyTimeBasedWorkflow`: `Max`, `Remaining`
- `MassEmail`: `Max`, `Remaining`

### 3.2 Via Salesforce Setup UI
1. Navigate to **Setup** $\rightarrow$ **Company Settings** $\rightarrow$ **Storage Usage**.
2. Capture:
   - Overall Data Storage: Limit, Used, % Used.
   - Overall File Storage: Limit, Used, % Used.
   - Top 5 Custom/Standard Objects by record count and storage consumed.
   - Verify available headroom before creating `Job__c` and `Company__c`.

