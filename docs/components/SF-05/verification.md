# SF-05 Verification Evidence & Live Gap Register

Document Reference: `docs/components/SF-05/verification.md`  
Parent Component: [SF-05](../SF-05.md)  
Associated Tests: `tests/salesforce/metadata/test_sf05_metadata.py`, `tests/salesforce/metadata/test_sf05_scenarios.py`  
Version: `1.0`  
Date: **01 November 2026**  

---

## 1. Executive Summary

This document presents the complete verification evidence for **SF-05** (`Generation_Request__c` metadata, field mapping, permissions, validation rules, and contract C13 integration). All verification scenarios were executed against local metadata parsers, contract models, and simulated Salesforce environments.

### 1.1 Test Suite Summary
- **SF-05 Scenario Suite (`test_sf05_scenarios.py`)**: 12/12 passed (100%) in 0.88s.
- **SF-05 Metadata Suite (`test_sf05_metadata.py`)**: 13/13 passed (100%) in 0.71s.
- **Generation Subsystem Unit Suite (`tests/generation/`)**: 17/17 passed (100%) in 0.93s.
- **Salesforce Subsystem Full Regression Suite (`tests/salesforce/`)**: 182/182 passed (100%) in 3.47s.
- **Total Verification Coverage**: 212 tests executed; 0 failures; 0 regressions.

---

## 2. Scenario Verification Matrix (V01 – V12)

| Scenario ID | Test Method | Covered Requirement | Verification Outcome | Pass/Fail |
|---|---|---|---|---|
| **V01** | `test_v01_offline_creation_and_admission_pending` | Blueprint §4, C13, R10 | UI record inserted while worker is offline admits cleanly into durable storage as `Pending` C13 record with correct deterministic UUIDv5 identity. | **PASS** |
| **V02** | `test_v02_creation_input_immutability` | SF-05-S02, C13 | Metadata validation rule `Immutable_Creation_Inputs` and client key rules prohibit modifying inputs after insert. | **PASS** |
| **V03** | `test_v03_unavailable_job_default_and_preflight_failure` | Blueprint §6, R10 | `Allow_Unavailable_Job__c` defaults to `false`. When job is closed/expired, worker fails preflight immediately to `Failed` (`job_unavailable`) without claiming or writing frozen versions. | **PASS** |
| **V04** | `test_v04_external_client_key_replay_and_conflict` | Blueprint §5, C13, R10 | Exact replay of existing client key returns same request idempotently. Conflicting client key across differing Salesforce record IDs is rejected with `VALIDATION` error and quarantined. | **PASS** |
| **V05** | `test_v05_deliberate_regeneration_vs_retry` | Blueprint §7, C13 | Deliberate regeneration produces fresh C13 identity linked to predecessor ID, while retry of failed request preserves original request identity. | **PASS** |
| **V06** | `test_v06_worker_lifecycle_advancement_and_frozen_snapshots` | Blueprint §6, C13 | Worker advances lifecycle (`Pending` $\rightarrow$ `Running` $\rightarrow$ `Upload_Pending` $\rightarrow$ `Ready_for_Review`), writing frozen versions that become immutable. | **PASS** |
| **V07** | `test_v07_processing_vs_approval_separation` | Blueprint §8, R12 | Delivery of artifacts (`Ready_for_Review`) points to `Result_Artifact_Ref__c` but does not approve document or modify `Application_Progress__c` on `Job__c`. | **PASS** |
| **V08** | `test_v08_sanitized_error_and_diagnostic_visibility` | Blueprint §6, R10 | Diagnostics on `Failed` state populate `Error_Reason__c`, sanitized `Error_Message__c` (stripped of tokens/paths), and `Error_Ref__c` visible in Salesforce. | **PASS** |
| **V09** | `test_v09_restrict_delete_and_lineage_protection` | Blueprint §4, R10 | Lookups to `Job__c` and `Predecessor_Request__c` specify `deleteConstraint="Restrict"`. Validation rule `No_Self_Predecessor` prohibits self-parenting. | **PASS** |
| **V10** | `test_v10_requester_least_privilege_permissions` | Blueprint §5, R10, R15 | `Job_Generation_Requester` permission set grants Read/Create on `Generation_Request__c`, Read on `Job__c`/`Company__c`, writable creation inputs, read-only worker fields, and zero admin permissions. | **PASS** |
| **V11** | `test_v11_worker_least_privilege_permissions` | Blueprint §5, R10, R15 | `Job_Automation_Worker` permission set grants Read/Edit on `Generation_Request__c`, read-only creation inputs, read-write operational fields, and preserves candidate fields on `Job__c` as read-only. | **PASS** |
| **V12** | `test_v12_manifest_and_ownership_completeness` | Blueprint §9, R10 | All 35+ components registered in `salesforce/metadata-ownership.json`, explicit allowlist in `salesforce/manifest/sf05.xml`, and non-destructive inclusion in `package.xml`. | **PASS** |

---

## 3. Metadata Validation Suite Evidence

The metadata parser test suite `tests/salesforce/metadata/test_sf05_metadata.py` verified all syntactic and structural requirements:

1. `test_generation_request_object_metadata`:
   - Validates `sharingModel = Private`, `nameField` pattern `GR-{000000}`, and deployment status `Deployed`.
2. `test_generation_request_custom_fields_presence`:
   - Validates existence and correct type for all 23 custom fields.
3. `test_restrict_delete_lookups`:
   - Enforces `deleteConstraint="Restrict"` on `Job__c` and `Predecessor_Request__c`.
4. `test_client_request_key_field_properties`:
   - Enforces `unique="true"`, `caseSensitive="true"`, `externalId="true"`, and length `255`.
5. `test_field_lengths_and_precisions`:
   - Enforces C13 length bounds: `Contract_Schema_Version__c` (16), `Frozen_*_Version__c` (64), `Local_Artifact_Ref__c` (255), `Error_Message__c` (2000), etc.
6. `test_all_thirteen_validation_rules_present`:
   - Verifies all 13 rules are active (`active="true"`) and contain non-empty formulas and error messages.
7. `test_list_views_metadata`:
   - Verifies all 4 list views specify `filterScope="Everything"` and reference valid columns.
8. `test_custom_tab_metadata`:
   - Verifies tab motif `Custom20: Fax` and custom object reference.
9. `test_page_layout_sections_and_fields`:
   - Verifies layout sections: Overview, Status, Frozen Versions, Delivered Artifacts, Diagnostics, Technical Identity.
10. `test_job_layout_includes_generation_requests_related_list`:
    - Verifies `Job__c-JA Candidate Tracking.layout-meta.xml` contains `Generation_Request__c.Job__c` related list.
11. `test_job_tracker_app_includes_generation_request_tab`:
    - Verifies `Job_Tracker.app-meta.xml` contains `<tabs>Generation_Request__c</tabs>`.
12. `test_manifest_sf05_xml_completeness`:
    - Validates zero wildcards in `sf05.xml` and complete enumeration of members.
13. `test_package_xml_includes_sf05_components`:
    - Validates additive, non-destructive presence in master `package.xml`.

---

## 4. Live Org Gap Register & Acceptance Checklist

Because live org mutations and deployments are deferred until interactive user sign-in and authorization target confirmation, the following live checks remain scheduled for deployment acceptance:

| Check ID | Scope / Action | Expected Live Org Behavior | Verification Command / Step |
|---|---|---|---|
| **LIVE-01** | Deploy `sf05.xml` via Salesforce CLI | Deployment succeeds with status `Succeeded` without Apex or schema errors. | `sf project deploy start --manifest salesforce/manifest/sf05.xml --target-org dev-main` |
| **LIVE-02** | UI Creation While Worker Offline | Candidate creates `Generation_Request__c` record in Lightning Experience. Status defaults to `Pending`. | Navigate to `Generation Requests` tab $\rightarrow$ New $\rightarrow$ Select Job $\rightarrow$ Save. |
| **LIVE-03** | UI Immutability Enforcement | Candidate attempts to edit `Job__c` or `Document_Type__c` on existing record. | Platform validation rule `Immutable_Creation_Inputs` displays error banner preventing save. |
| **LIVE-04** | UI Client Key Whitespace Rejection | External caller or user inputs client key with whitespace (`"key 123"`). | Platform validation rule `Client_Request_Key_No_Whitespace` blocks insert. |
| **LIVE-05** | UI Parent Delete Restriction | Candidate attempts to delete `Job__c` that has an associated `Generation_Request__c`. | Salesforce blocks deletion with `DELETE_FAILED: Your attempt to delete ... could not be completed because it is referenced by: Generation Requests`. |
| **LIVE-06** | Worker Startup & Claim | Worker process is started locally. Worker polls pending request, transitions state to `Running`, and writes `Worker_Claimed_At__c` and `Frozen_*`. | Run worker poll command; observe Salesforce record update. |
| **LIVE-07** | Delivery Visibility | Worker finishes generation and uploads artifact. Record updates to `Ready_for_Review` with `Result_Artifact_Ref__c` populated. | Refresh Lightning record page; verify delivered artifact reference and status. |

