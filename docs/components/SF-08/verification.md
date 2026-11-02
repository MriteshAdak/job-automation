# SF-08 Verification Evidence, Scenario Matrix & Acceptance Protocol

Component ID: **SF-08**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026), §§5–9, R12  
Planning Reference: [docs/stories/SF-08.md](../../stories/SF-08.md)  
Handoff Reference: [docs/components/SF-08.md](../SF-08.md)

---

## 1. Automated Verification Suite Execution

Verification for SF-08 was executed across native Windows offline test suites covering XML metadata structure, domain models, cryptographic deduplication, fail-closed access policies, crash recovery, and end-to-end scenario validation.

### 1.1 Test Suite Summary & Outcomes

```powershell
# 1. Structural Metadata & DX Packaging Suite
.\.venv\Scripts\python.exe -m pytest tests/salesforce/metadata/test_sf08_metadata.py -v
# Outcome: 9 passed in 0.52s

# 2. Comprehensive Scenarios & Invariant Verification Suite (V01–V20)
.\.venv\Scripts\python.exe -m pytest tests/salesforce/metadata/test_sf08_scenarios.py -v
# Outcome: 20 passed in 1.48s

# 3. Full Salesforce Regression Suite (SF-01 through SF-08)
.\.venv\Scripts\python.exe -m pytest tests/salesforce/
# Outcome: 331 passed in 10.86s

# 4. GEN-06 Delivery Integration Regression Suite
.\.venv\Scripts\python.exe -m pytest tests/generation/delivery/ -v
# Outcome: 27 passed in 0.95s
```

---

## 2. Verification Scenario Matrix (V01–V20)

All 20 scenario tests defined in [docs/stories/SF-08.md](../../stories/SF-08.md) §SF-08-S05 were authored and verified in `tests/salesforce/metadata/test_sf08_scenarios.py`:

| ID | Category | Scenario Description | Tested Invariant / Behavioral Rule | Outcome |
|---|---|---|---|---|
| **V01** | Structural | DX metadata parsing, packaging manifest, and ownership registry validation | Validates that `JA_Draft_Ready`, `JA_Request_Action_Required`, `JA_Notification_Config__c`, `JA_Request_Notification__c`, Flows, Apex classes, and `Job_Notification_Administrator` conform to API 60.0 standards and are registered in `sf08.xml` and `metadata-ownership.json`. | **PASSED** |
| **V02** | Eligibility | Intermediate processing states emit zero readiness alerts | In `Pending`, `Running`, or `Upload_Pending` (even when DOCX is uploaded while PDF is pending), zero ready notifications are admitted or dispatched. | **PASSED** |
| **V03** | Eligibility | Complete delivered set with recipient access produces one alert | When both DOCX and PDF are delivered and verified accessible to the candidate user, exactly one notification is admitted and dispatched. Verifies `Generation_Request__c.Status__c` remains `Ready_for_Review` (never marked `Approved`). | **PASSED** |
| **V04** | Idempotency | Repeated Ready updates and registration replays do not duplicate | Replays of the same event key, edits to notes/warnings, or worker restarts consult the unique alert key and return `REPLAYED` without a second notification. | **PASSED** |
| **V05** | Resilience | Status cycling and access repair (`Ready -> Upload_Pending -> Ready`) | Status cycling for an already-accepted alert does not send again. If originally blocked due to access failure, repairing access transitions the blocked record to `Pending` (`BLOCKED_RELEASED`) without creating duplicate ledger records. | **PASSED** |
| **V06** | Isolation | Human approval and supersession do not trigger ready notifications | Candidate approval or supersession in SF-07 does not fire notifications. Genuinely new generation requests or new artifact sets produce separate alerts only after full delivery gates pass. | **PASSED** |
| **V07** | Ordering | Out-of-order arrival convergence | Registration arriving before Ready status and Ready status arriving before registration both converge to exactly one alert. Incomplete or mismatched sets are rejected. | **PASSED** |
| **V08** | Permissions | Candidate file access gate vs worker/admin access | Worker or admin file visibility does not satisfy candidate readiness. Missing file sharing or revoked access blocks admission (`RECIPIENT_ACCESS_DENIED`). | **PASSED** |
| **V09** | Failure | Terminal failure produces safe failure notification | When a request enters `Failed`, an action-required notification is emitted. Same-episode replays (`Failed -> Running -> Failed`) do not repeat the alert. | **PASSED** |
| **V10** | Intervention | Transient retry vs delivery intervention | Transient retry attempts emit no failure alerts. An explicit delivery intervention in `Upload_Pending` (e.g. storage quota exhausted) admits at most one action-required alert. | **PASSED** |
| **V11** | Progression | Resolved failure and successor events | A resolved failure followed by a new explicit episode can alert again. Stale failure alerts arriving after `Ready_for_Review` are suppressed. | **PASSED** |
| **V12** | Concurrency | Concurrent observers and senders coalesce cleanly | Overlapping concurrent admission transactions coalesce to a single record via unique `Alert_Key__c` constraint. | **PASSED** |
| **V13** | Crash Matrix | Crash and recovery across lifecycle stages | Crash before admission, after admission, or during dispatch is tested. Ambiguous outcomes where send acknowledgment is lost transition to `Uncertain` and prohibit automated resends. | **PASSED** |
| **V14** | Recovery | Bounded retry for proven non-send faults | Network disconnects proven to precede send retry with backoff. Exhausting maximum attempts moves record to `Dead_Letter`. | **PASSED** |
| **V15** | Configuration | Recipient fail-closed resolution | Missing config, disabled config, missing `Candidate_User__c`, or inactive user fails closed (`BLOCKED`). No fallback to admin or worker. Configuration changes do not resend accepted history. | **PASSED** |
| **V16** | Privacy | Diagnostic sanitization and privacy leakage prevention | Tokens, Windows paths, email addresses, and HTML tags are sanitized. Notification body contains only safe fixed text and validated request number. | **PASSED** |
| **V17** | Navigation | Target record navigation and file immutability | Notification target link navigates to the authorized `Generation_Request__c` record in Salesforce. Clicking does not mutate data or trigger background generation. | **PASSED** |
| **V18** | Bulk Limits | Bulk updates and governor limits | Bulk updates stay within SOQL and DML bounds. Failure of one alert item does not corrupt sibling ledger items. | **PASSED** |
| **V19** | Portability | Disable/re-enable and migration preservation | Disabling notifications suppresses pending work. Re-enabling does not cause a storm of historical alerts. Exported ledger records preserve unique keys. | **PASSED** |
| **V20** | Localization | Language templates and Windows path handling | Validates German (`de`) and English (`en`) templates, umlauts (`ä, ö, ü, ß`), `Europe/Berlin` timestamps, and native Windows paths with spaces. | **PASSED** |

---

## 3. Live Org Deployment & Verification Protocol

### 3.1 Test Recipient Authorization Requirement
Per project policy and the SF-08 story specification:
> **Authorized Live Notification Checks**: Use an explicitly configured test recipient for live notification checks. If unavailable, validate without sending and report the live check as pending.

### 3.2 Current Live Check Status
- **Status**: **PENDING (Awaiting User Authorization & Target Recipient User ID)**.
- **Offline Readiness**: All metadata, Apex services, and Python integration tests have passed in the local environment.
- **Safety**: No unprompted live notifications have been dispatched to real Salesforce users.

### 3.3 Live Verification Protocol (When Authorized)
When a live target org and candidate test user ID are supplied by the user:
1. **Deploy Metadata Package**:
   ```powershell
   sf project deploy start --manifest salesforce/manifest/sf08.xml --target-org <TargetOrgAlias>
   ```
2. **Assign Permission Set**:
   ```powershell
   sf org assign permset --name Job_Notification_Administrator --target-org <TargetOrgAlias>
   ```
3. **Configure Singleton Recipient**:
   Insert a single `JA_Notification_Config__c` record:
   - `Is_Enabled__c` = `true`
   - `Candidate_User__c` = `<AuthorizedTestUserId>`
   - `Permitted_Event_Kinds__c` = `ready;action_required`
   - `Preferred_Language__c` = `en` (or `de`)
   - `Max_Retry_Attempts__c` = `3`
   - `Org_Key__c` = `<OrgId>`
4. **Trigger Synthetic Event**:
   Deliver a test generation request with complete DOCX/PDF files and transition status to `Ready_for_Review`.
5. **Verify Bell Notification**:
   Log into Salesforce as `<AuthorizedTestUserId>`, verify desktop notification appears in bell, click notification, and confirm navigation to the request review page.

