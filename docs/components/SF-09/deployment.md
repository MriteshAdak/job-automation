# SF-09 Deployment, Migration, Rollback & Operational Runbook

Component ID: **SF-09**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../../IMPLEMENTATION_BLUEPRINT.md), C15 and §§5–10, R17  
Handoff Reference: [docs/components/SF-09.md](../SF-09.md)  
Planning Reference: [docs/stories/SF-09.md](../../stories/SF-09.md)

---

## 1. Deployment Packaging & Scoped Manifest

All SF-09 metadata members are packaged strictly in `salesforce/manifest/sf09.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Package xmlns="http://soap.sforce.com/2006/04/metadata">
    <types>
        <members>JA_Run_Completed</members>
        <name>CustomNotificationType</name>
    </types>
    <types>
        <members>Run_Summary__c</members>
        <name>CustomObject</name>
    </types>
    <types>
        <!-- 47 custom fields on Run_Summary__c -->
        <members>Run_Summary__c.Run_Id__c</members>
        <members>Run_Summary__c.First_Completion_Key__c</members>
        ...
        <name>CustomField</name>
    </types>
    <types>
        <members>Run_Summary__c.Immutable_Run_Id</members>
        <members>Run_Summary__c.Immutable_Completion_Key</members>
        <members>Run_Summary__c.Valid_Duration</members>
        <members>Run_Summary__c.End_Not_Before_Start</members>
        <members>Run_Summary__c.Confirmed_Requires_Receipt</members>
        <members>Run_Summary__c.Unknown_Requires_Code</members>
        <name>ValidationRule</name>
    </types>
    <types>
        <members>Run_Summary__c.All_Run_Summaries</members>
        <members>Run_Summary__c.Failed_Or_Partial_Runs</members>
        <members>Run_Summary__c.Unresolved_Notifications</members>
        <name>ListView</name>
    </types>
    <types>
        <members>Run_Summary__c</members>
        <name>CustomTab</name>
    </types>
    <types>
        <members>Run_Summary__c-Run Summary Layout</members>
        <name>Layout</name>
    </types>
    <types>
        <members>JA_Run_Summary_Completion</members>
        <name>Flow</name>
    </types>
    <types>
        <members>JA_RunSummaryGuard</members>
        <members>JA_RunSummaryGuardTest</members>
        <members>JA_RunSummaryDispatcher</members>
        <members>JA_RunSummaryDispatcherTest</members>
        <members>JA_RunSummaryRecovery</members>
        <members>JA_RunSummaryRecoveryTest</members>
        <name>ApexClass</name>
    </types>
    <types>
        <members>Job_Summary_Worker</members>
        <members>Job_Summary_Reader</members>
        <members>Job_Summary_Administrator</members>
        <name>PermissionSet</name>
    </types>
    <version>60.0</version>
</Package>
```

---

## 2. Controlled Activation Protocol

To prevent notification storms or unverified live dispatches:

1. **Deploy Metadata with Inactive Flow**:
   - The deployed `JA_Run_Summary_Completion` Flow has `<status>Draft</status>` (inactive).
2. **Configure Singleton Recipient**:
   - Set `JA_Notification_Config__c`:
     * `Is_Enabled__c = true`
     * `Candidate_User__c = <Authorized_User_Id>`
     * `Preferred_Language__c = 'en'` or `'de'`
     * `Activation_Watermark__c = System.now()` (suppresses alerts for existing historical runs).
3. **Assign Scoped Permission Sets**:
   - Assign `Job_Summary_Worker` to the External Client App integration user.
   - Assign `Job_Summary_Reader` to the candidate user.
   - Assign `Job_Summary_Administrator` to the operator user.
4. **Activate Flow**:
   - In Salesforce Setup, open `JA_Run_Summary_Completion` Flow and click **Activate**.
5. **Enable Summary Delivery in AUTO-03**:
   - In `config/summary-delivery.json`, set `enabled = true`.

---

## 3. Rollback & Disaster Recovery Runbook

If summary delivery or notification dispatch requires emergency rollback:

### Immediate Kill Switch
1. In Salesforce Setup, open `JA_Notification_Config__c` and set `Is_Enabled__c = false`.
2. Inactive flag takes effect immediately: all pending or retrying notifications transition to `suppressed` with code `CONFIG_DISABLED`.
3. In `JA_Run_Summary_Completion` Flow, click **Deactivate**.

### Metadata Rollback
- Since `Run_Summary__c` has private sharing and independent identity, deactivating the Flow and unassigning `Job_Summary_Worker` halts all automated mutations without affecting `Company__c` or `Job__c`.
- **Never delete historical `Run_Summary__c` records**: Deleting summary rows destroys deduplication evidence (`First_Completion_Key__c`), which could rearm alerts if an old outbox replays.

