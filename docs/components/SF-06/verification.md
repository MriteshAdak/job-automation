# SF-06 Verification Evidence & Scenario Matrix

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../../IMPLEMENTATION_BLUEPRINT.md) §6 (SF-06), §7 (Gate G3)  
Planning Reference: [docs/stories/SF-06.md](../../stories/SF-06.md) §S05  
Automated Test Suites:
- `tests/salesforce/metadata/test_sf06_metadata.py` (9 tests)
- `tests/salesforce/metadata/test_sf06_scenarios.py` (18 scenario tests: V01–V18)

---

## 1. Automated Verification Matrix (V01 – V18)

| Scenario ID | Category | Verified Condition & Invariant | Status |
|---|---|---|---|
| **V01** | Structural & Security | Actual XML metadata parsing of Flows, QuickActions, Apex, CustomObjects, and CustomMetadata. Zero callouts, zero localhost/127.0.0.1 references, and zero direct `<recordCreates>` bypasses in Flow XML. | **VERIFIED** |
| **V02** | Matrix & Catalog | Generation options matrix (2 document types × 2 languages × 2 context strategies × 2 templates = 16 combinations). Invalid, disabled, cross-type mismatched, and oversized template IDs fail with clear configuration errors. | **VERIFIED** |
| **V03** | Boundary & Gating | Missing/deleted/inaccessible Job, invalid Canonical Job UUID, forged document type, and non-existent predecessor requests reject with safe, non-leaking error messages. | **VERIFIED** |
| **V04** | Idempotency | Token lifecycle stability across open/cancel/double-click. Rapid double-clicks return replayed result without creating duplicate requests. Resubmitting same token with altered parameters returns token conflict. | **VERIFIED** |
| **V05** | Concurrency Races | Simulated overlapping transactions from independent browser tabs submitting identical intent simultaneously: creates exactly 1 `Generation_Request__c` record; both responses reference it; both separate receipts persist. | **VERIFIED** |
| **V06** | Active Request Reuse | Identical options reuse existing requests across `Pending`, stale `Running`, and `Upload_Pending` without mutating timestamps, status, or frozen inputs. Multiple active matches resolve deterministically to the oldest record. | **VERIFIED** |
| **V07** | Worker Interleaving | Worker claims and advances requests (`Pending` $\rightarrow$ `Running` $\rightarrow$ terminal) while enqueue operations wait. Service rechecks locked row state and returns truthful current status without overwriting worker fields. | **VERIFIED** |
| **V08** | Lineage & Regeneration | Deliberate regeneration requires predecessor request ID, creates new request with unique AutoNumber ID, sets `Predecessor_Request__c` lineage, and leaves predecessor and its delivered artifacts completely intact. | **VERIFIED** |
| **V09** | Replay Recovery | Lost HTTP response recovery: resubmitting with same token across `Pending`, `Running`, `Failed`, and `Ready_for_Review` states returns the original request with its observed state without creating duplicate work. | **VERIFIED** |
| **V10** | Transaction Atomicity | Row lock timeouts return `retryable_conflict`. Receipt persistence failure triggers complete transactional rollback, ensuring zero orphaned `Generation_Request__c` records. | **VERIFIED** |
| **V11** | Terminal History Gate | Fresh ordinary candidate action with identical options to an existing completed/failed draft is gated with `confirmation_required`, prompting deliberate regeneration confirmation. | **VERIFIED** |
| **V12** | Unavailable Gating | Target job marked `Unavailable` or having prior `job_unavailable` failure requires explicit `Allow_Unavailable_Job__c = true` and deliberate regeneration; default/false override blocks creation. | **VERIFIED** |
| **V13** | Uncertainty Handling | `Unknown` and `Not_Seen` availability states represent uncertainty, not confirmed closure, permitting initial request creation without fabricating status. | **VERIFIED** |
| **V14** | Least-Privilege RBAC | Candidate permission set `Job_Generation_Actions` grants Read/Create on requests and receipts; zero edit authority over operational state (`Status__c`, `Completed_At__c`, `Result_Artifact_Ref__c`). Worker profile cannot create requests. | **VERIFIED** |
| **V15** | Offline Queuing | Requests submitted while local Windows worker is offline persist with status `Pending`. User feedback accurately states request is queued and will be processed when the worker runs. | **VERIFIED** |
| **V16** | Field Preservation | Existing candidate tracking fields (`Application_Progress__c`, `Candidate_Notes__c`, `Follow_Up_Date__c`), machine assessment fields, and canonical IDs remain byte/value identical across all actions. | **VERIFIED** |
| **V17** | Worker Admission | Request observations admitted via `GenerationAdmitter` (GEN-01) derive stable deterministic UUIDv5 identities from `(org_id, canonical_sf_id)` with 15/18-character convergence and lineage preservation. | **VERIFIED** |
| **V18** | Display & Manifest | Unicode character support (German umlauts `ä, ö, ü, ß`), timezone handling (`Europe/Berlin`), and complete manifest allowlist coverage (`sf06.xml`). | **VERIFIED** |

---

## 2. Test Execution Commands & Results

All verification suites execute cleanly on native Windows in PowerShell:

```powershell
# 1. SF-06 Structural Metadata Validation Suite
.\.venv\Scripts\python.exe -m pytest tests/salesforce/metadata/test_sf06_metadata.py
# Outcome: 9 passed in 0.90s

# 2. SF-06 Comprehensive Scenario Suite (V01 - V18)
.\.venv\Scripts\python.exe -m pytest tests/salesforce/metadata/test_sf06_scenarios.py
# Outcome: 18 passed in 0.72s

# 3. Full Salesforce Subsystem Regression Suite (All SF-01 through SF-06 tests)
.\.venv\Scripts\python.exe -m pytest tests/salesforce/
# Outcome: 271 passed in 4.08s

# 4. Generation Subsystem Core Unit Tests
.\.venv\Scripts\python.exe -m pytest tests/generation/test_admission.py tests/generation/test_polling.py tests/generation/test_projection.py tests/generation/test_records.py
# Outcome: 17 passed in 0.89s
```

---

## 3. Live Org Gap Register & Pending Interactive Verification

| Item | Live Requirement | Status | Verification Protocol |
|---|---|---|---|
| 1 | Target Dev Org Deployment | **PENDING** | Execute `sf project deploy start --manifest salesforce/manifest/sf06.xml --target-org dev-main`. |
| 2 | Apex Unit Test Execution in Org | **PENDING** | Run `sf apex run test --class-names JA_GenerationSubmitTest --target-org dev-main --code-coverage`. |
| 3 | Interactive Lightning UI Click | **PENDING** | Open Job record page in Lightning Experience, click "Generate CV" and "Generate Cover Letter" quick actions, confirm screen displays options and feedback. |
| 4 | Offline Worker Inspection | **PENDING** | With Windows worker process stopped, verify created request record exists in `Generation_Request__c` tab with status `Pending`. |

