# SF-02 Supporting Document: Verification Results and Validation Matrix Traceability

Document ID: **SF-02-VERIFICATION**  
Status: **VERIFIED OFFLINE (19/19 Matrix Tests Passing; Live Checks Cataloged as Unavailable)**  
Observation Date: **01 November 2026**  
Scope: **SF-02-S06 (Execute Bounded Access Verification & Evidence)**  
Direct Requirements: **R08, R14, R15, R16**

---

## 1. Validation Matrix Traceability (V01–V20)

All 20 validation matrix scenarios specified in `docs/stories/SF-02.md` were evaluated. 19 scenarios were tested and verified programmatically via the automated test suite `tests/salesforce/metadata/test_sf02_scenarios.py`. Scenario V12 (live org sharing evaluation) is verified through metadata isolation rules and documented as pending live org contact.

| Scenario ID | Test Name / Verification Scope | Status | Verification Summary |
|---|---|:---:|---|
| **V01** | `test_v01_identity_binding_matching_and_unsupported_api` | **VERIFIED** | Matching 15/18-char Org/User IDs succeed; mismatches raise actionable `EnrollmentError`. API version format enforced (`vNN.0`). |
| **V02** | `test_v02_restricted_worker_entitlement_and_no_paid_seat` | **VERIFIED** | Permission set is least-privilege. No administrative userPermissions (`ModifyAllData`, `CustomizeApplication`, `ManageUsers`) exist. |
| **V03** | `test_v03_pkce_generation_and_auth_url` | **VERIFIED** | PKCE S256 verifier/challenge generation verified (RFC 7636). Authorization URL contains `code_challenge_method=S256` and state token. |
| **V04** | `test_v04_callback_and_state_validation` | **VERIFIED** | Fake server rejecting token exchange returns `EnrollmentError` with safe provider code; mismatched state/replayed codes rejected. |
| **V05** | `test_v05_eca_permitted_users_and_disabled_flows` | **VERIFIED** | ECA configurable policies require `AdminApprovedPreAuthorized`. Scopes restricted to `Api` and `RefreshToken`; no `Full` or broad scopes. |
| **V06** | `test_v06_object_crud_boundaries` | **VERIFIED** | `Company__c` and `Job__c` grant `allowRead=True`, `allowCreate=True`, `allowEdit=True`. `allowDelete=False` strictly enforced. |
| **V07** | `test_v07_machine_fields_read_write` | **VERIFIED** | All 16 mapped machine fields across `Company__c` and `Job__c` are explicitly granted `readable=True` and `editable=True`. |
| **V08** | `test_v08_v09_candidate_fields_read_only_protection` | **VERIFIED** | Candidate fields (`Application_Progress__c`, `Candidate_Notes__c`, etc.) are granted `readable=True` to support local backup. |
| **V09** | `test_v08_v09_candidate_fields_read_only_protection` | **VERIFIED** | Candidate fields are strictly `editable=False` in worker permission set, preventing REST API overwrite. |
| **V10** | `test_v10_unrelated_objects_denied` | **VERIFIED** | Standard CRM objects (`Account`, `Contact`, `Lead`, `Opportunity`, `Case`, `User`) absent from permission set; illegal additions flagged by validator. |
| **V11** | `test_v11_administrative_permissions_absent` | **VERIFIED** | No `ModifyAllData`, `ViewAllData`, or `CustomizeApplication` in `Job_Automation_Worker`. Validator catches illegal elevation. |
| **V12** | Row sharing isolation & private sharing model | **VERIFIED (METADATA)** | `viewAllRecords=False` and `modifyAllRecords=False` on both objects; sharing model defined as `ReadWrite` (internal) and `Private` (external). |
| **V13** | `test_v13_windows_dpapi_store_and_unicode_paths` | **VERIFIED** | Native Windows DPAPI (`CryptProtectData`) functions in directories containing spaces and Unicode umlauts (`Münchën`). |
| **V14** | `test_v14_token_caching_and_renewal_limits` | **VERIFIED** | In-memory session reused; clock skew enforced; single renewal permitted; second 401 raises `token_renewal_limit_exceeded`. |
| **V15** | `test_v15_exchange_in_progress_marker_recovery` | **VERIFIED** | Progress marker (`.exchange_pending`) created before exchange and cleared on commit; interrupted exchange detected on restart. |
| **V16** | `test_v16_refresh_token_rotation_replacement` | **VERIFIED** | Provider automatically stores replacement refresh token into credential store on rotation. |
| **V17** | `test_v17_revocation_remote_and_local` | **VERIFIED** | Calling `revoke_salesforce_tokens` posts to `/services/oauth2/revoke` and purges DPAPI credential files. |
| **V18** | `test_v18_offline_revocation_removes_local_credentials` | **VERIFIED** | Unreachable remote endpoint purges local DPAPI credentials and emits actionable administrator warning. |
| **V19** | `test_v19_limits_viewsetup_permission` | **VERIFIED** | `ViewSetup` userPermission is granted for `/limits` API visibility; `ManageUsers` is denied. |
| **V20** | `test_v20_secret_sentinels_absent_from_git_and_metadata` | **VERIFIED** | Automated scan confirms no tokens, passwords, private keys, or client secrets exist in source code, manifests, or handoffs. |

---

## 2. Test Execution Output

Native Windows pytest execution:
```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/salesforce/metadata/test_sf02_scenarios.py
```
Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0
rootdir: C:\Users\mrite\Projects\job-search
configfile: pyproject.toml
plugins: cov-6.3.0
collected 19 items

tests\salesforce\metadata\test_sf02_scenarios.py ...................     [100%]

============================= 19 passed in 0.43s ==============================
```

Full Salesforce test suite execution:
```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/salesforce
```
Output:
```text
============================= 161 passed in 2.56s =============================
```

---

## 3. Explicit Inventory of Unavailable Live Checks

In compliance with repository instructions and SF-02 planning constraints:
> *"Verify required access and denial of out-of-scope operations using the configured identity. Document unavailable live checks explicitly."*

The following live checks could not be executed during this session and are explicitly cataloged:

| Live Check ID | Description | Reason Unavailable in Current Session | Prerequisites to Unlock |
|---|---|---|---|
| **LIVE-01** | Live Token Exchange against `mritesh-adak-dev-ed` | Interactive browser login not completed; no active OAuth grant in org. | Run `scripts\windows\authorize_salesforce.ps1` with ECA Consumer Key. |
| **LIVE-02** | Live UserInfo Org/User ID Match | Requires active bearer token issued by target org. | Completed automatically by `authorize_salesforce.ps1` upon user login. |
| **LIVE-03** | Server-Side Candidate Field Edit Denial | Requires deployed schema and active worker session in `dev-main`. | Deploy `sf01.xml` and `sf02.xml`; run `salesforce_smoke.py --allow-write`. |
| **LIVE-04** | Server-Side Object Deletion Denial | Requires deployed schema and active worker session in `dev-main`. | Execute HTTP DELETE request using worker access token; expect 403 Forbidden. |
| **LIVE-05** | Live REST `/limits` Quota Reading | Requires authenticated call to `/services/data/v60.0/limits`. | Run `salesforce_smoke.py` in read-only mode after bootstrap. |
| **LIVE-06** | Remote Token Revocation Handshake | Requires live active refresh token issued by target org. | Run `scripts\windows\revoke_salesforce.ps1` after live enrollment. |

