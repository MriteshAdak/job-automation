# SF-07 Verification Evidence, Scenario Matrix & Acceptance Protocol

Component ID: **SF-07**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026), §§5–9, R11, R12  
Planning Reference: [docs/stories/SF-07.md](../../stories/SF-07.md)  
Handoff Reference: [docs/components/SF-07.md](../SF-07.md)

---

## 1. Automated Verification Suite Execution

Verification for SF-07 was conducted through offline automated suites validating metadata structure, Apex service behavior, domain constraints, file access rules, concurrency, and end-to-end review scenarios.

### 1.1 Test Suite Summary

```powershell
# 1. Structural Metadata & DX Packaging Suite
.\.venv\Scripts\python.exe -m pytest tests/salesforce/metadata/test_sf07_metadata.py -v
# Outcome: 11 passed in 0.73s

# 2. Comprehensive Scenarios & Invariant Verification Suite (V01–V20)
.\.venv\Scripts\python.exe -m pytest tests/salesforce/metadata/test_sf07_scenarios.py -v
# Outcome: 20 passed in 0.73s

# 3. Full Salesforce Regression Suite (SF-01 to SF-07)
.\.venv\Scripts\python.exe -m pytest tests/salesforce/
# Outcome: 302 passed in 4.62s

# 4. GEN-06 Delivery Integration Regression Suite
.\.venv\Scripts\python.exe -m pytest tests/generation/ -k "delivery"
# Outcome: 28 passed in 1.54s
```

---

## 2. Verification Scenario Matrix (V01–V20)

| ID | Category | Scenario Description | Tested Invariant / Behavioral Rule | Outcome |
|---|---|---|---|---|
| **V01** | Structural | XML parsing, manifest, and ownership registry validation | Objects, fields, layout, flexipage, LWC, custom permission, and permission set schemas are valid API 60.0 XML. Manifest `sf07.xml` and `metadata-ownership.json` are fully synchronized. | **PASSED** |
| **V02** | Progress | Durable request progress display across 5 states | Truthfully maps `Pending`, `Running`, `Upload_Pending`, `Ready_for_Review`, and `Failed`. Shows offline-worker notice and statutory warning; zero invented progress percentages. | **PASSED** |
| **V03** | Delivery | Partial delivery and upload-pending handling | Incomplete delivery set (missing PDF or DOCX) is rejected. Under `Upload_Pending`, UI displays cards as upload pending with zero approval affordances. | **PASSED** |
| **V04** | Delivery | Complete delivery registration validation | Validates that worker delivery registration records both DOCX and PDF as immutable bindings starting in `draft` status with correct parent request binding. | **PASSED** |
| **V05** | Permissions | Candidate file access verification vs worker/admin access | Verifies that candidate with `Job_Document_Reviewer` has valid `Viewer` file access, while unrelated users or users without request access are rejected with `insufficient_user_privilege`. | **PASSED** |
| **V06** | Resilience | Inaccessible-file handling preserves history | When a ContentDocumentLink is revoked or a file deleted, the UI displays `unavailable` and disables approval, but **preserves** earlier recorded approval state and history without rewriting. | **PASSED** |
| **V07** | RBAC | Role separation: worker cannot approve, candidate cannot forge delivery | Worker caller attempting `approve` is rejected (`worker_cannot_approve`). Candidate caller attempting delivery registration is rejected with `PermissionError`. | **PASSED** |
| **V08** | Invariants | Exact-version approval and format isolation | Approving DOCX marks DOCX `approved`, while PDF remains strictly `draft`. Request status remains `Ready_for_Review` (never mutated to 'Approved'). | **PASSED** |
| **V09** | Regeneration | Regeneration without inherited approval | Successor Request B generated via SF-06 delivers drafts that start in `draft` status. Predecessor Request A retains its approved status independently. | **PASSED** |
| **V10** | Replacement | Atomic approval and replacement | Candidate executes `approve_and_replace` on B replacing A: B becomes `approved`, A becomes `superseded` (`Superseded_By__c` linked), and two audit events are recorded in a single transaction. | **PASSED** |
| **V11** | Resolution | Exact-version resolution on open/download | Direct download URL resolves to the exact stored `ContentVersionId`, even if newer, unrelated versions are uploaded to the same ContentDocument. | **PASSED** |
| **V12** | Concurrency | Stale screen concurrency conflict | Submission with mismatched `expected_review_revision` is rejected with `stale_revision` (HTTP 409 equivalent), preventing overwriting concurrent human actions. | **PASSED** |
| **V13** | Concurrency | Concurrent approval protection and parent job locking | Concurrent threads racing to approve the same review record result in exactly one recorded approval and one conflict/replay rejection. | **PASSED** |
| **V14** | Idempotency | Submission token replay and conflict detection | Resubmitting the same intent token with identical payload returns `REPLAYED` with original `eventId`. Conflicting payload with same token returns `CONFLICT`. | **PASSED** |
| **V15** | Idempotency | Worker registration replay preserves human approval | Retrying delivery registration with identical receipt and mappings preserves existing `approved` or `superseded` state without resetting records to draft. | **PASSED** |
| **V16** | Security | Platform race: access revocation between load and approval | Re-checking candidate access at the exact moment of approval rejection prevents approving a file if access was revoked after page load. | **PASSED** |
| **V17** | Regeneration | SF-06 regeneration entry and consent invariants | Triggering regeneration via `request_regeneration` passes `predecessor_request_id` and resets `allow_unavailable_job` strictly to `false`. | **PASSED** |
| **V18** | Integration | GEN-06 integration checks & SF-08 boundary | Validates integration with GEN-06 delivery contracts (`DeliverySetReceipt`, `ReviewProjection`). Verifies approval action does **not** dispatch spurious readiness events. | **PASSED** |
| **V19** | Audit | Export / restore audit preservation | Serialized audit events (`JA_Artifact_Review_Event__c`) retain exact version ID, SHA-256 hash, actor ID, and timestamps for OPS-01 backup/restore. | **PASSED** |
| **V20** | Formatting | Timezone formatting (Europe/Berlin), statutory warning, and unicode notes | Formats delivery and approval timestamps in `Europe/Berlin` (CET/CEST). Displays statutory notice. Preserves German umlauts and special characters (`ä, ö, ü, ß`) in candidate notes. | **PASSED** |

---

## 3. Live Org Deployment & Acceptance Protocol (Pending Authorization)

Per user instructions, live changes to external orgs are executed strictly within current authorization. Because the target Salesforce org credentials and CLI connection are pending user configuration, live deployment steps are formalized below for execution upon grant:

### Step 1: Pre-Deployment Validation & Authorization
1. Confirm target org alias and identity:
   ```powershell
   sf org display --target-org <target-org-alias>
   ```
2. Verify API version is `60.0`.
3. Check available storage capacity in target org (R09 / SF-04).

### Step 2: Deployment of Scoped Manifest (`sf07.xml`)
```powershell
sf project deploy start --manifest salesforce/manifest/sf07.xml --target-org <target-org-alias> --wait 10
```

### Step 3: Run Apex Test Suite in Target Org
```powershell
sf apex run test --class-names JA_ArtifactRegistrationTest JA_ArtifactReviewServiceTest --result-format human --target-org <target-org-alias> --wait 10
```
Expected: 100% test pass rate, code coverage $\ge 85\%$.

### Step 4: Permission Set Assignment & Smoke Verification
1. Assign `Job_Document_Reviewer` to candidate user:
   ```powershell
   sf org assign permset --name Job_Document_Reviewer --target-org <target-org-alias>
   ```
2. Assign `Job_Automation_Worker` to integration user:
   ```powershell
   sf org assign permset --name Job_Automation_Worker --target-org <target-org-alias>
   ```
3. Navigate to a `Generation_Request__c` record in Lightning Experience, verify `JA_Generation_Request_Review` FlexiPage renders `jaArtifactReview` LWC with truthful offline worker notice.

---

## 4. Gap Register & Upstream/Downstream Alignment

| Item | Owning Component | Description | Current Status / Remediation |
|---|---|---|---|
| **Live Flow Notifications** | **SF-08** | Automated notifications upon transition to `Ready_for_Review`. | Out of SF-07 scope. SF-07 cleanly emits stable readiness keys for SF-08 consumption. |
| **Physical File Upload & Reconciliation** | **GEN-06** | ContentDocumentLink creation, chunked file upload, and retry loops. | Owned exclusively by GEN-06. SF-07 provides delivery registration contract; zero browser uploads in UI. |
| **Live Org Authorization** | **User / Admin** | Connection and authorization of target Salesforce org for live deployment. | Offline validation complete (302/302 passed). Live org deployment documented in §3 pending user trigger. |

