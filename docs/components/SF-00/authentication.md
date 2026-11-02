# SF-00 Supporting Document: Authentication Architecture and No-New-Cost Options

Document ID: **SF-00-AUTH**  
Status: **ARCHITECTURE BASELINE & DOWNSTREAM EVALUATION FOR SF-02**  
Observation Date: **01 November 2026**  
Scope: **SF-00-S05 (Assess Existing Authentication and No-New-Cost Options)**  
Direct Requirements: **R08, R14, R15, R16**

---

## 1. Platform Policy Baseline & Licensing Constraints

Per blueprint §1 and §9, the automation must incur **zero software licensing costs**. The target environment is the user's existing Developer Edition Org.

Key platform constraints from current official Salesforce documentation (*Salesforce Help: Remote Access OAuth*, *External Client Apps Guide*, *Developer Edition Allocations*):

1. **User License Allocation**:
   - A standard Developer Edition includes **2 Full Salesforce User licenses** (System Administrator profile) and several Chatter/Community licenses.
   - Dedicated "Salesforce Integration" user licenses (introduced in Enterprise/Unlimited editions) are generally not provisioned in free Developer Edition orgs.
   - **Consequence**: The integration worker must operate under the credentials of the user's existing System Administrator account. We must not require purchasing or provisioning a third user seat.
2. **Connected Apps vs. External Client Apps (ECAs)**:
   - Beginning in Spring '26, Salesforce enforces the deprecation of new Connected App creation in favor of **External Client Apps (ECAs)**.
   - While existing Connected Apps continue to function, any newly configured integration should use External Client Apps to remain forward-compatible and supported.
3. **Local Credential Protection on Windows (R14, R15)**:
   - As implemented in [SFCLIENT-01](../components/SFCLIENT-01.md), all credentials (refresh tokens, client secrets) are encrypted on disk using native Windows DPAPI (`CryptProtectData` via `ctypes.windll.crypt32`).
   - Plaintext secrets are strictly prohibited from appearing in `salesforce.json`, `app.json`, environment variables, diagnostic logs, or git commits.

---

## 2. Evaluation of Candidate OAuth 2.0 Flows

| OAuth Flow Candidate | Technical Mechanism | Feasibility in Dev Org | Codebase Readiness (`SFCLIENT-01`) | Cost | Recommendation / Verdict |
|---|---|---|---|---|---|
| **1. Authorization Code with PKCE + Refresh Token** | User performs one-time interactive browser consent. Salesforce issues a `refresh_token`. The Python worker exchanges the refresh token non-interactively for short-lived access tokens via `POST /services/oauth2/token`. | **HIGH**: Supported natively by Developer Edition and External Client Apps. Runs under user's existing admin identity. | **100% READY**: Implemented in `OAuthTokenProvider` (`src/job_automation/salesforce/auth.py`) and verified with native DPAPI. | **Free** | **PRIMARY RECOMMENDED FLOW (SF-02)** |
| **2. JWT Bearer Token (`urn:ietf:params:oauth:grant-type:jwt-bearer`)** | Uses an X.509 digital certificate (.crt) uploaded to Salesforce. Client signs a JWT with a private key (.key) and exchanges it directly for an access token without browser interaction. | **FEASIBLE**: Supported in Dev Org via pre-authorized user profile or permission set. | **CODE GAP**: `OAuthTokenProvider` currently only implements `refresh_token` exchange. Supporting JWT requires adding `cryptography`/`PyJWT` and refactoring `SFCLIENT-01`. | **Free** | **VIABLE ALTERNATIVE** (Deferred: requires client code changes). |
| **3. OAuth 2.0 Client Credentials Flow** | Server-to-server grant without human user context (`POST /services/oauth2/token?grant_type=client_credentials`). | **PROBLEMATIC**: In standard Salesforce editions, ECAs using client credentials require assigning an execution user. Consuming one of the 2 admin seats for a headless user is restrictive. | **CODE GAP**: Not supported in `OAuthTokenProvider`. | **Free (if seats allow)** | **NOT RECOMMENDED** |
| **4. CLI Session Token Hijacking (Reusing `.sfdx/*.json`)** | Reading cached access tokens or refresh tokens from `%USERPROFILE%\.sfdx\*.json` into Python runtime. | **INCOMPATIBLE**: Violates R15 credential isolation and blueprint security rules. CLI session files rotate unpredictably and are not application-managed credentials. | **STRICTLY REJECTED** by architecture. | **Free** | **PROHIBITED** |

---

## 3. Recommended Authorization Architecture for SF-02

The recommended path for **SF-02** is the **OAuth 2.0 Authorization Code Flow with Refresh Token**, backed by an **External Client App (ECA)**:

```mermaid
sequenceDiagram
    autonumber
    actor Admin as User (Admin)
    participant Setup as Salesforce Setup (ECA)
    participant CLI_Script as SF-02 Bootstrap Script
    participant DPAPI as Windows DPAPI Store
    participant Worker as Python Sync Worker (SYNC-01)
    participant SF_OAuth as Salesforce Token Endpoint

    Note over Admin, Setup: One-Time Bootstrap (SF-02)
    Admin->>Setup: Create External Client App ("Job_Automation_Client")
    Setup-->>Admin: Consumer Key (Client ID) & Client Secret
    Admin->>CLI_Script: Run one-time bootstrap with Client ID
    CLI_Script->>Admin: Open browser to Salesforce login & consent
    Admin->>Setup: Approve OAuth scopes (api, refresh_token, offline_access)
    Setup-->>CLI_Script: OAuth Authorization Code
    CLI_Script->>SF_OAuth: Exchange Auth Code for Refresh Token
    SF_OAuth-->>CLI_Script: Refresh Token
    CLI_Script->>DPAPI: Encrypt & save refresh token (CryptProtectData)
    CLI_Script-->>Admin: Bootstrap complete; credentials protected in local_data/credentials

    Note over Worker, SF_OAuth: Automated Execution (Phases 0 & 1)
    Worker->>DPAPI: Decrypt refresh token in-memory
    Worker->>SF_OAuth: POST /services/oauth2/token (grant_type=refresh_token)
    SF_OAuth-->>Worker: Short-lived Access Token (Bearer)
    Worker->>Setup: Execute REST API Calls (Upsert, Describe, Limits)
```

### 3.1 External Client App Configuration Requirements
In the target Developer Org, the External Client App should be configured with:
- **Connected App / ECA Name**: `Job_Automation_Client`
- **OAuth Scopes**:
  - `Access and manage your data (api)`
  - `Perform requests at any time (refresh_token, offline_access)`
- **Callback URL**: `http://localhost:8080/callback` (or `https://login.salesforce.com/services/oauth2/success`)
- **Refresh Token Policy**: *Refresh token is valid until revoked*
- **IP Relaxation**: *Relax IP restrictions* (or enforce based on user preference)

### 3.2 Security and Credential Protection Baseline
- In `config/salesforce.json`:
  ```json
  {
    "schema_version": "1.0",
    "instance_url": "https://<my-domain>.develop.my.salesforce.com",
    "api_version": "v60.0",
    "auth_flow": "refresh_token",
    "client_id_ref": "salesforce/client_id",
    "credential_ref": "salesforce/refresh_token",
    "token_url": "https://login.salesforce.com/services/oauth2/token",
    "expected_org_id": "<15-character-org-id>"
  }
  ```
- The actual values of `salesforce/client_id` and `salesforce/refresh_token` are stored in encrypted binary files beneath `%LOCALAPPDATA%\JobAutomation\credentials\` and decrypted only in-process by `WindowsDpapiCredentialStore`.

