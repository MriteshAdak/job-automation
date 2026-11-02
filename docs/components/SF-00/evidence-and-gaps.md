# SF-00 Supporting Document: Evidence Index, Call Ledger, and Gap Register

Document ID: **SF-00-EVIDENCE**  
Status: **SANIZED EVIDENCE BASELINE & GAP AUDIT**  
Observation Date: **01 November 2026**  
Scope: **SF-00-S07 (Reconcile Evidence and Publish Component Handoff)**  
Direct Requirements: **R08, R14, R15, R16**

---

## 1. Sanitized Evidence Index

The findings and recommendations of SF-00 are grounded strictly in the following audited evidence items:

| Evidence ID | Source / Artifact | Inspection Method | Key Observations (Sanitized) |
|---|---|---|---|
| **E01** | `%USERPROFILE%\.sfdx\alias.json` | Local PowerShell JSON property read (no secrets printed) | Found 6 aliases: `dev-main`, `another`, `test_files`, `ReportOnFiles`, `dev-hub-main`, `searchFiles`. |
| **E02** | `%USERPROFILE%\.sfdx\*.json` | Local PowerShell property projection | Found 5 connection files. Filtered all tokens/keys. Identified 2 Developer Edition orgs (`00DWU...` Dev Hub; `00DQy...` Trailblaze) and 3 scratch orgs. |
| **E03** | `%USERPROFILE%\.sf\deploy-cache.json` | Local PowerShell read | Recorded historical deployments in May 2026 to scratch org `test-pcawx38wjf6q@example.com` (`searchFiles`). |
| **E04** | Windows Environment & PATH | PowerShell `Get-Command` & PATH string split | `sf`, `sfdx`, `git`, `node` are absent from active PATH. Dead paths `S:\installations\sf\bin` and `C:\Program Files\sf\bin` detected. Python 3.12.10 available. |
| **E05** | Repository `config/*.json` | `read_file` tool | `salesforce.example.json` and `sync.example.json` contain placeholder org ID `00D000000000001` and instance URL `example-dev-ed.develop.my.salesforce.com`. No active target configuration in `config/` or `local_data/`. |
| **E06** | Repository Codebase | Static code analysis & module inspection | Python gateway `SalesforceGatewayV2Client` and DPAPI store `WindowsDpapiCredentialStore` are fully implemented in `src/job_automation/salesforce/`. |
| **E07** | Repository Test Suite | Native Windows execution (`pytest --import-mode=importlib`) | **1,855 / 1,855 tests passed** in 81.75s, confirming contract models, storage migrations, sync logic, and Windows path compliance. |
| **E08** | Manual Smoke Script | `tests/manual/salesforce_smoke.py` execution inspection | Read-only default returns status 0 with `[PREREQUISITE STATUS] PENDING: No configuration file provided. (SF-02 handoff absent)`. |

---

## 2. Bounded Network Call Ledger

Per blueprint §5 and `docs/stories/SF-00.md`, network operations during inspection must be strictly bounded and monitored:

| Ledger Entry # | Target Endpoint | Operation | Payload / Query | Response / Result | Security Audit |
|---|---|---|---|---|---|
| **L01** | N/A | None | N/A | **0 Network Calls Made** | Halted at target selection gate to prevent accidental transmission to ambiguous orgs. |

- Total Remote HTTP Calls: **0**
- Total Remote Mutations: **0**
- Total Records Created/Modified/Deleted: **0**
- Total Metadata Components Deployed: **0**

---

## 3. Comprehensive Gap and Prerequisite Register

Every blocked item or unknown org state is recorded with its affected decision, responsible owner, smallest necessary action, and exact recheck condition:

| Gap ID | Condition / Missing Evidence | Affected Decision / Output | Responsible Owner | Smallest Necessary Next Action | Exact Recheck Condition |
|---|---|---|---|---|---|
| **GAP-01** | **Target Org Ambiguity**: Two Developer Edition orgs exist in cache (`00DWU...` vs `00DQy...`); none bound in project config. | Blocks all live remote inspection calls (Describe, Limits, SOQL). | **User** | Confirm intended target org: specify either `dev-main` (`00DWU...`) or `ReportOnFiles` (`00DQy...`). | User provides target My Domain URL or updates `config/salesforce.json`. |
| **GAP-02** | **CLI Tooling Absent**: `sf` executable is not installed or not on system PATH. | Prevents running CLI-based inspection commands (`sf org display`, `sf limits api display`). | **User / Environment** | Install `@salesforce/cli` via npm or standalone installer, or use Python gateway for inspection. | `Get-Command sf` exits with code 0 in PowerShell. |
| **GAP-03** | **Gateway Credentials Unconfigured**: No DPAPI credentials exist in `%LOCALAPPDATA%\JobAutomation\credentials\`. | Prevents Python gateway (`SalesforceGatewayV2Client`) from issuing authenticated REST requests. | **SF-02** | Implement SF-02 OAuth bootstrap script to capture refresh token into DPAPI store. | DPAPI file `salesforce/refresh_token` exists and decrypts successfully. |
| **GAP-04** | **Live Schema Unverified**: Object existence, Name field type (Text vs Autonumber), and External ID uniqueness on `Job__c` and `Company__c` are unverified. | Holds final confirmation of `config/sync.json` mapping. | **SF-00 (Post-Bootstrap)** | Execute `describe_object("Job__c")` and `describe_object("Company__c")` via gateway or Setup UI. | Authoritative Describe JSON response received with field metadata. |
| **GAP-05** | **Live Storage Limits Unverified**: Exact remaining MB in `DataStorageMB` and `FileStorageMB` is unmeasured. | Holds final retention sizing and safe headroom calculation. | **SF-00 (Post-Bootstrap)** | Query `/services/data/v60.0/limits` or check Setup Storage Usage. | Authoritative limits JSON response captured with remaining storage values. |

---

## 4. Verification Gate Summary

- **Local Repository & Windows Environment Audit**: **VERIFIED**
- **Schema Mapping & Collision Planning**: **VERIFIED (BASELINE ARCHITECTURE)**
- **Authentication & Licensing Analysis**: **VERIFIED (NO-NEW-COST ECA EVALUATION)**
- **Live Remote Org Inventory**: **INCOMPLETE / PENDING USER TARGET CONFIRMATION AND SF-02 CREDENTIALS**

