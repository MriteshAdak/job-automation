# SF-00 Supporting Document: Access, Target Selection, and Environment Inventory

Document ID: **SF-00-ACCESS**  
Status: **INCOMPLETE (Target Selection Ambiguous; Live Access Blocked)**  
Observation Date: **01 November 2026**  
Scope: **SF-00-S01 (Establish Intended Org and Inspection Access)**  
Direct Requirements: **R08, R14, R16** (with **R15** credential privacy constraint)

---

## 1. Intended Target Org Discovery and Selection Analysis

Per blueprint §1 and §5, the personal automation must track job applications in the user's existing Salesforce Developer Edition Org without provisioning a new replacement org or purchasing paid integration licenses.

Per `docs/stories/SF-00.md` (§§39–48, Task SF-00-S01):
> *"Select exactly one intended existing org before remote access. Use an explicit target, never a default alias merely because it exists. If the target cannot be identified from available context, resolve that ambiguity with the user before connecting... Stop remote access; obtain the target binding from the user. Continue local mapping analysis. Do not probe all cached accounts."*

### 1.1 Local Cache Discovery (`%USERPROFILE%\.sfdx` and `.sf`)

A safe, value-suppressed inspection of the local environment discovered cached connection metadata from previous CLI usage. All tokens, secrets, private keys, passwords, and sensitive URLs were strictly filtered out.

The user-level cache contains **6 alias definitions** and **5 cached connection records**:

| Item # | Redacted Org ID | Instance / My Domain URL | Is Dev Hub | Aliases | Org Type / Classification |
|---|---|---|---|---|---|
| **Org 1** | `00DWU000008bLor***` | `https://mritesh-adak-dev-ed.develop.my.salesforce.com` | `True` | `dev-main`, `dev-hub-main` | **Developer Edition (Dev Hub Enabled)** |
| **Org 2** | `00DQy00000dVnpC***` | `https://resourceful-impala-hqqbdh-dev-ed.trailblaze.my.salesforce.com` | `False` | `ReportOnFiles` | **Developer Edition (Trailblaze My Domain)** |
| **Org 3** | `00DQI00000Lfy2X***` | `https://fun-business-291-dev-ed.scratch.my.salesforce.com` | `False` | `test_files` | **Scratch Org (Ephemeral, 30-day)** |
| **Org 4** | `00DS800000GrKiY***` | `https://efficiency-innovation-2872-dev-ed.scratch.my.salesforce.com` | `False` | `another` | **Scratch Org (Ephemeral, 30-day)** |
| **Org 5** | `00DRR00000QD4iH***` | `https://ruby-energy-487-dev-ed.scratch.my.salesforce.com` | `False` | `searchFiles` | **Scratch Org (Ephemeral, 30-day)** |

### 1.2 Target Ambiguity and Decision Gate

1. **Scratch Orgs Excluded**: Orgs 3, 4, and 5 are ephemeral scratch orgs under `.scratch.my.salesforce.com`. They expire within 30 days and are unsuited for durable personal application tracking. Furthermore, `.sf/deploy-cache.json` shows that Org 5 (`searchFiles`) was last deployed to in May 2026.
2. **Ambiguity Between Developer Edition Orgs**:
   - **Org 1 (`dev-main` / `dev-hub-main`)**: `00DWU...` — Configured as a Developer Edition with Dev Hub enabled (`develop.my.salesforce.com`).
   - **Org 2 (`ReportOnFiles`)**: `00DQy...` — Configured as a standard Developer Edition (`trailblaze.my.salesforce.com`).
3. **Project Repository Context**:
   - The repository configuration (`config/salesforce.example.json` and `config/sync.example.json`) contains only placeholder values (`00D000000000001`, `example-dev-ed.develop.my.salesforce.com`).
   - No project file, documentation, or environment variable designates whether Org 1 (`dev-main`) or Org 2 (`ReportOnFiles`) is the intended tracking environment.
4. **Enforced Gate**:
   - Under the missing-access protocol of SF-00, **remote access was halted immediately**. Probing both orgs or guessing the target is strictly forbidden to prevent accidental modification or leakage of data across unrelated orgs.
   - The user must explicitly confirm which org to bind before live inspection or deployment proceeds.

---

## 2. Tooling and CLI Availability Inventory

An inspection of native Windows tools, executables, and PATH entries was conducted on 01 November 2026:

| Tool | Checked Locations | Status | Notes |
|---|---|---|---|
| **Salesforce CLI (`sf`)** | System/User PATH, `C:\Program Files\sf\bin`, `%LOCALAPPDATA%\Programs\sf\bin`, `%APPDATA%\npm\sf.cmd` | **NOT FOUND / UNAVAILABLE** | Command `sf` is not recognized. PATH contains `S:\installations\sf\bin` and `C:\Program Files\sf\bin`, but neither directory exists on disk. |
| **Legacy SFDX CLI (`sfdx`)** | System/User PATH, `C:\Program Files\Salesforce CLI\bin`, `%APPDATA%\npm\sfdx.cmd` | **NOT FOUND / UNAVAILABLE** | Command `sfdx` is not recognized. |
| **Node.js / npm / npx** | System/User PATH | **NOT FOUND** | Node runtime is not available on PATH. |
| **Git** | System/User PATH | **NOT FOUND** | Git executable is not on this process's PATH. |
| **Python Runtime** | Native Windows PATH | **AVAILABLE** | Python 3.12.10 (64-bit) in virtual environment `c:\Users\mrite\Projects\job-search\.venv`. |
| **Python Gateway (`SalesforceGatewayV2Client`)** | Repository codebase | **AVAILABLE (OFFLINE)** | Fully implemented in `src/job_automation/salesforce/gateway.py`. Tested against fakes (62/62 unit tests passing). Awaits DPAPI credential provisioning. |

---

## 3. Effective Access Matrix

Based on the environment inspection, the effective access rights across key operational surfaces are:

| Surface / Capability | Current Status | Limiting Factor / Cause | Remediation for Live Inspection |
|---|---|---|---|
| **Salesforce Setup (UI)** | **UNVERIFIED** | Requires interactive browser login by the human administrator. | User logs into Setup in web browser. |
| **REST API Access** | **BLOCKED** | No OAuth credentials provisioned in local DPAPI store (`data_root/credentials`); target unconfirmed. | Run one-time bootstrap script (SF-02) or supply target settings. |
| **Metadata API / Tooling API** | **BLOCKED** | CLI unavailable; REST Tooling endpoint unauthenticated. | Provide authenticated CLI or run Python REST Tooling describe queries. |
| **Limits Resource (`/limits`)** | **BLOCKED** | Unauthenticated network endpoint. | Call `/services/data/v60.0/limits` via authenticated gateway. |
| **Object Schema Describe** | **BLOCKED** | Unauthenticated network endpoint. | Call `/services/data/v60.0/sobjects/{object}/describe` via gateway. |
| **Record Data Queries / SOQL** | **BLOCKED** | Unauthenticated network endpoint. | Call `/services/data/v60.0/query` via gateway. |
| **Deployment Permission** | **UNKNOWN** | Cannot check `Modify All Data` / `Customize Application` permissions without an authenticated session. | Inspect User Profile / Permission Sets in Setup or via Tooling API. |

---

## 4. Separation of Privileges: Inspector vs. Worker

To minimize security risk and adhere to the principle of least privilege, inspection privileges must remain strictly segregated from runtime worker privileges:

### 4.1 Inspector Privileges (SF-00 Read-Only)
- **Role**: Read-only discovery and validation.
- **Required Privileges**:
  - `View Setup and Configuration`: Inspect Object Manager, limits, apps, flows, and user licenses.
  - `API Enabled`: Execute read-only REST describe and limits calls.
  - Read access on custom objects `Company__c` and `Job__c` (if they exist).
- **Explicitly Forbidden**:
  - `Modify All Data` or record deletion rights.
  - Deploying metadata packages or modifying profiles.
  - Sampling private candidate text, notes, or non-project business records.

### 4.2 Runtime Worker Privileges (Phase 0 SYNC-01 Worker)
- **Role**: Synchronize machine-evaluated jobs and manage outbox state.
- **Required Privileges**:
  - `API Enabled`: Execute REST upsert and query calls.
  - Read/Create/Edit on `Company__c` and `Job__c`.
  - Field-Level Security (FLS): Read and Edit on all mapped machine fields; Read-only on candidate-owned fields (`Application_Progress__c`, etc.) to support candidate backup (T5).
  - Access to `/services/data/vXX.X/limits`.
- **Explicitly Forbidden**:
  - `Customize Application` or `Modify All Data`.
  - Access to unrelated standard objects (`Lead`, `Opportunity`, `Case`, `Contact`, `Account`).
  - Permission to modify or overwrite candidate-owned fields.

---

## 5. Summary of Gaps and Prerequisite Actions

| Item | Observed Gap | Responsible Component / Actor | Smallest Necessary Next Action |
|---|---|---|---|
| **Target Binding** | Ambiguity between `dev-main` (`00DWU...`) and `ReportOnFiles` (`00DQy...`). | **User** | Confirm which Dev Org My Domain URL should be bound to `config/salesforce.json`. |
| **CLI Tooling** | `sf` executable missing from system PATH. | **User / Environment** | If CLI-based inspection is preferred, install Salesforce CLI (`npm install -g @salesforce/cli` or standalone installer) and add to PATH. |
| **Gateway Auth** | DPAPI credential store empty (`local_data/credentials`). | **SF-02** | Provision External Client App / Connected App OAuth credentials and store refresh token. |
| **Org Limits & Schema** | Actual live limits and object existence unread. | **SF-00 (Post-Bootstrap)** | Execute read-only inspection procedure once connection credentials exist. |

