# SF-02 Supporting Document: Target Org Capabilities and No-Cost Restricted Identity Analysis

Document ID: **SF-02-CAPABILITIES**  
Status: **PLANNED / ARCHITECTURE ESTABLISHED (Live Inspection Pending Interactive Session)**  
Observation Date: **01 November 2026**  
Scope: **SF-02-S01 (Resolve Target Capabilities and No-Cost Restricted Identity)**  
Direct Requirements: **R08, R14, R15, R16**

---

## 1. Intended Target Org Binding and Resolution

Per `docs/stories/SF-02.md`, on **01 November 2026**, the target org selection was explicitly resolved by user confirmation:
- **Target Alias**: `dev-main` / `dev-hub-main`
- **Instance My Domain**: `https://mritesh-adak-dev-ed.develop.my.salesforce.com`
- **Org ID**: `00DWU000008bLor***` (Developer Edition with Dev Hub enabled)
- **User Identity**: `mriteshadak@outlook.com`
- **Source API Version**: `v60.0` (Spring '24) / `v61.0` (Summer '24)

### 1.1 Resolution of Target Selection Ambiguity
In component handoff **SF-00**, remote access was halted due to ambiguity between two cached Developer Edition orgs (`dev-main` vs `ReportOnFiles`). With the user's explicit confirmation of `dev-main`, that gate is closed. `dev-main` is the sole authorized environment for this integration. Ephemeral scratch orgs (`searchFiles`, `test_files`, `another`) remain strictly excluded.

### 1.2 Current Live Remote Org Inspection Status
- **Browser Navigation**: When navigating to the instance My Domain, the browser returns **Login | Salesforce**, confirming the My Domain is active and reachable.
- **Interactive Session Status**: No authenticated session is currently active.
- **Salesforce CLI Status**: Executable `sf` / `sfdx` is not available on PATH.
- **Inspection Principle**: No credentials were artificially created, borrowed from unrelated tools, or forged. Live capability inspection requiring authenticated org calls remains explicitly cataloged as **PENDING LIVE SESSION**.

---

## 2. No-Additional-Cost Licensing Evaluation

Per blueprint §1 and §9, the personal automation system must incur **zero software licensing costs**.

### 2.1 Developer Edition Allocation Constraints
Official Salesforce Developer Edition license entitlements:
1. **Full Salesforce User Licenses**: Exactly **2 seats** (typically assigned to System Administrator profiles).
2. **Integration User Licenses**: Dedicated "Salesforce Integration" user licenses (introduced in Enterprise / Unlimited editions) are **not provisioned in standard free Developer Edition orgs**.
3. **Platform / Community / Chatter Licenses**: Various standard limited licenses exist, but generally lack REST API access to custom objects `Company__c` and `Job__c`.

### 2.2 Separation of Privileges: Administrator vs Worker Identity
In SF-00, it was preliminarily noted that the integration worker might operate under the user's System Administrator account. In **SF-02**, this assumption was critically re-evaluated:

| Aspect | System Administrator Identity | Dedicated Restricted Worker Identity |
|---|---|---|
| **License Cost** | Incurred already (Seat 1 of 2). | Uses Seat 2 of 2 (if available at $0) OR a restricted Standard User profile. |
| **Least Privilege (R15)** | **NON-CONFORMING**: Admin possesses `Modify All Data`, `View All Data`, and bypasses Field-Level Security. | **CONFORMING**: Base profile has no admin rights; access is strictly scoped via `Job_Automation_Worker` permission set. |
| **Negative Denial Enforcement** | Server-side negative tests fail: admin token can write candidate fields despite permission set restrictions. | Server-side negative tests succeed: unauthorized field/object writes are blocked by Salesforce API. |
| **Operational Recommendation** | Acceptable **only** during initial deployment/setup. | **Mandatory** for verified runtime operation if Seat 2 is unassigned. |

### 2.3 Licensing Resolution Protocol
1. **Preflight License Audit**: Upon first authenticated connection, inspect `UserLicense` and `User` records:
   ```soql
   SELECT TotalLicenses, UsedLicenses, Name FROM UserLicense WHERE Name = 'Salesforce'
   ```
2. **If Seat 2 is Free**: Provision a dedicated restricted user (`job-worker@<my-domain>`) with a standard/restricted user profile, assign the `Job_Automation_Worker` permission set, and enroll the ECA under that identity.
3. **If Seat 2 is Occupied**: Keep the worker token scoped to the primary user, but strictly enforce least-privilege boundary at the application layer (`assert_no_candidate_fields` in `SYNC-01`), documenting that server-side field-level negative denial cannot be enforced against an administrator identity.

---

## 3. Platform API Version Discovery

- **Configured Target**: `v60.0` (Spring '24).
- **Metadata API Compatibility**: Both `v60.0` and `v61.0` support `ExternalClientApplication`, `ExtlClntAppOauthSettings`, `ExtlClntAppOauthConfigurablePolicies`, and `PermissionSet`.
- **Live Version Validation**: To be performed during first live preflight via `/services/data/`:
  ```http
  GET /services/data HTTP/1.1
  Host: mritesh-adak-dev-ed.develop.my.salesforce.com
  ```
  The highest mutually supported version will be bound to `config/salesforce.json`.

---

## 4. Capability Gap & Release Gate Register

| Capability Item | Expected State | Current Observed State | Release Gate Status | Action Required |
|---|---|---|---|---|
| **Target Binding** | `dev-main` | Confirmed by user on 01 Nov 2026 | **RESOLVED** | Bound to project configuration. |
| **My Domain Endpoint** | Active HTTPS | Reachable (`mritesh-adak-dev-ed`) | **VERIFIED** | Ready for OAuth endpoints. |
| **ECA Feature Support** | Supported in org | Supported by platform (Spring '26 baseline) | **READY FOR SETUP** | Deploy ECA metadata via Setup / API. |
| **License Headroom** | 1 free Salesforce seat | Unchecked live in org | **PENDING LIVE SESSION** | Query `UserLicense` upon first connection. |
| **Live User Profile** | Restricted / Standard | Unchecked live in org | **PENDING LIVE SESSION** | Check assigned profile for worker identity. |
| **Live Schema Verification** | `Company__c`, `Job__c` | Source metadata defined in `salesforce/` | **PENDING SF-01 DEPLOYMENT** | Deploy `sf01.xml` before permission set. |

