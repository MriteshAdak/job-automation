# SF-08 Deployment, Rollback & Operational Runbook

Component ID: **SF-08**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026), §§5–9, R12  
Planning Reference: [docs/stories/SF-08.md](../../stories/SF-08.md)  
Handoff Reference: [docs/components/SF-08.md](../SF-08.md)

---

## 1. Release Manifest & Packaging

SF-08 metadata is packaged cleanly in `salesforce/manifest/sf08.xml` targeting Salesforce API version 60.0.

### 1.1 Manifest Definition (`sf08.xml`)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Package xmlns="http://soap.sforce.com/2006/04/metadata">
    <types>
        <members>JA_Draft_Ready</members>
        <members>JA_Request_Action_Required</members>
        <name>CustomNotificationType</name>
    </types>
    <types>
        <members>JA_Notification_Config__c</members>
        <members>JA_Request_Notification__c</members>
        <name>CustomObject</name>
    </types>
    <types>
        <members>JA_Notification_Config__c.Is_Enabled__c</members>
        <members>JA_Notification_Config__c.Candidate_User__c</members>
        <members>JA_Notification_Config__c.Permitted_Event_Kinds__c</members>
        <members>JA_Notification_Config__c.Preferred_Language__c</members>
        <members>JA_Notification_Config__c.Enable_Mobile__c</members>
        <members>JA_Notification_Config__c.Max_Retry_Attempts__c</members>
        <members>JA_Notification_Config__c.Initial_Retry_Delay_Minutes__c</members>
        <members>JA_Notification_Config__c.Activation_Watermark__c</members>
        <members>JA_Notification_Config__c.Org_Key__c</members>
        <members>JA_Request_Notification__c.Alert_Key__c</members>
        <members>JA_Request_Notification__c.Source_Event_Key__c</members>
        <members>JA_Request_Notification__c.Event_Kind__c</members>
        <members>JA_Request_Notification__c.Generation_Request__c</members>
        <members>JA_Request_Notification__c.Recipient_User__c</members>
        <members>JA_Request_Notification__c.Channel__c</members>
        <members>JA_Request_Notification__c.Status__c</members>
        <members>JA_Request_Notification__c.Payload_Fingerprint__c</members>
        <members>JA_Request_Notification__c.Source_Revision__c</members>
        <members>JA_Request_Notification__c.Artifact_Set_Id__c</members>
        <members>JA_Request_Notification__c.Artifact_Set_Version__c</members>
        <members>JA_Request_Notification__c.Failure_Episode_Id__c</members>
        <members>JA_Request_Notification__c.Action_Code__c</members>
        <members>JA_Request_Notification__c.Attempts__c</members>
        <members>JA_Request_Notification__c.Max_Attempts__c</members>
        <members>JA_Request_Notification__c.Next_Retry_At__c</members>
        <members>JA_Request_Notification__c.Attempt_Identifier__c</members>
        <members>JA_Request_Notification__c.Dispatched_At__c</members>
        <members>JA_Request_Notification__c.Accepted_At__c</members>
        <members>JA_Request_Notification__c.Safe_Error_Code__c</members>
        <members>JA_Request_Notification__c.Uncertainty_Reason__c</members>
        <members>JA_Request_Notification__c.Target_Record_Id__c</members>
        <members>JA_Request_Notification__c.Notification_Title__c</members>
        <members>JA_Request_Notification__c.Notification_Body__c</members>
        <name>CustomField</name>
    </types>
    <types>
        <members>JA_Notification_Config__c.Enabled_Requires_Candidate</members>
        <members>JA_Request_Notification__c.Immutable_Alert_Key</members>
        <members>JA_Request_Notification__c.Accepted_Requires_Timestamp</members>
        <members>JA_Request_Notification__c.Uncertain_Requires_Reason</members>
        <name>ValidationRule</name>
    </types>
    <types>
        <members>JA_Notification_Config__c-JA Notification Config Detail</members>
        <members>JA_Request_Notification__c-JA Request Notification Detail</members>
        <members>Generation_Request__c-JA Generation Request Detail</members>
        <name>Layout</name>
    </types>
    <types>
        <members>JA_Administer_Notifications</members>
        <name>CustomPermission</name>
    </types>
    <types>
        <members>Job_Notification_Administrator</members>
        <members>Job_Document_Reviewer</members>
        <name>PermissionSet</name>
    </types>
    <types>
        <members>JA_RequestNotificationAdmission</members>
        <members>JA_RequestNotificationAdmissionTest</members>
        <members>JA_RequestNotificationDispatcher</members>
        <members>JA_RequestNotificationDispatcherTest</members>
        <members>JA_RequestNotificationRecovery</members>
        <name>ApexClass</name>
    </types>
    <types>
        <members>JA_Request_Notification_Observe</members>
        <members>JA_Request_Notification_Dispatch</members>
        <name>Flow</name>
    </types>
    <version>60.0</version>
</Package>
```

---

## 2. Pre-Deployment Dependencies & Verification Checklist

Before deploying SF-08 to a live environment, verify that prerequisites are satisfied:
- [x] **SF-05 / SF-06 Core Metadata Deployed**: `Generation_Request__c` custom object and fields exist.
- [x] **SF-07 Review Interface Deployed**: `JA_Artifact_Review__c` and `JA_ArtifactReviewService` exist.
- [x] **Permission Boundaries Enforced**: Requester, Worker, and Reviewer permission sets are provisioned.
- [x] **Zero Collisions**: Ensure no existing CustomNotificationTypes share names `JA_Draft_Ready` or `JA_Request_Action_Required`.

---

## 3. Deployment Sequence

To deploy SF-08 into a target Salesforce org without risking premature notification firing:

### Step 1: Deploy Metadata
```powershell
sf project deploy start --manifest salesforce/manifest/sf08.xml --target-org <TargetOrgAlias> --test-level RunLocalTests
```
*Note*: The Flows `JA_Request_Notification_Observe` and `JA_Request_Notification_Dispatch` are deployed with `status = Draft` (inactive).

### Step 2: Assign Notification Administrator Permission Set
```powershell
sf org assign permset --name Job_Notification_Administrator --target-org <TargetOrgAlias>
```

### Step 3: Seed Notification Configuration (Disabled by Default)
Insert the singleton configuration row in disabled state:
```sql
INSERT INTO JA_Notification_Config__c (
    Org_Key__c,
    Is_Enabled__c,
    Candidate_User__c,
    Permitted_Event_Kinds__c,
    Preferred_Language__c,
    Enable_Mobile__c,
    Max_Retry_Attempts__c,
    Initial_Retry_Delay_Minutes__c,
    Activation_Watermark__c
) VALUES (
    '<OrgId>',
    false,
    null,
    'ready;action_required',
    'en',
    false,
    3,
    1,
    NOW()
);
```

### Step 4: Configure Authorized Recipient & Enable
1. Update `Candidate_User__c` to the authorized candidate user ID.
2. Set `Activation_Watermark__c = NOW()` (ensures pre-existing requests created before this timestamp are suppressed).
3. Set `Is_Enabled__c = true`.

### Step 5: Activate Notification Flows
In Salesforce Setup $\to$ Flows, activate:
1. `JA_Request_Notification_Observe` (RecordAfterSave on `Generation_Request__c`).
2. `JA_Request_Notification_Dispatch` (RecordAfterSave on `JA_Request_Notification__c`).

---

## 4. Rollback & Emergency Kill-Switch Procedure

If notification behavior must be halted immediately:

### 4.1 Instant Kill-Switch (No Deployment Required)
Update the singleton config:
```sql
UPDATE JA_Notification_Config__c 
SET Is_Enabled__c = false 
WHERE Org_Key__c = '<OrgId>';
```
- Effect: All incoming admissions immediately fail closed (`outcome = BLOCKED`, code `CONFIG_DISABLED`).
- Dispatcher checks the config before every platform send; pending and retry items are halted immediately.

### 4.2 Deactivate Flows
Deactivate both `JA_Request_Notification_Observe` and `JA_Request_Notification_Dispatch` via Setup or metadata deployment.

### 4.3 Data Preservation Invariant
- **Never delete records from `JA_Request_Notification__c`**.
- Deleting ledger records destroys unique `Alert_Key__c` deduplication tokens and can cause a flood of duplicate notifications when re-activated.
- Historical `Accepted` and `Suppressed` records must remain permanently in the database.

---

## 5. Operations & Backlog Recovery Runbook

### 5.1 Monitoring Backlog & Operational Health
Use `JA_RequestNotificationRecovery` or SOQL to inspect pending or uncertain work:

```sql
SELECT Status__c, COUNT(Id)
FROM JA_Request_Notification__c
GROUP BY Status__c
```

### 5.2 Reconciling `Uncertain` Records
When an ambiguous network timeout occurs, records enter `Status__c = 'Uncertain'`.
1. Check the candidate's notification bell in the Salesforce UI to verify whether the notification was received.
2. If received:
   - Call `JA_RequestNotificationRecovery.confirmAccepted(notificationId)`.
   - Transitions record to `Accepted` with `Accepted_At__c = NOW()`.
3. If not received and still relevant:
   - Call `JA_RequestNotificationRecovery.forceRetry(notificationId)`.
   - Transitions record to `Pending` to allow a single controlled re-dispatch.
4. If obsolete:
   - Call `JA_RequestNotificationRecovery.suppress(notificationId, 'MANUALLY_SUPPRESSED')`.
   - Transitions record to `Suppressed`.

