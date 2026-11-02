/**
 * @description Unit test suite for JA_RequestNotificationDispatcher service (SF-08).
 */
@IsTest
private class JA_RequestNotificationDispatcherTest {

    @TestSetup
    static void setupTestData() {
        Company__c comp = new Company__c(
            Company_Name__c = 'Acme Corp',
            Canonical_Company_Id__c = '11111111-2222-3333-4444-555555555555'
        );
        insert comp;

        Job__c job = new Job__c(
            Job_Title__c = 'Lead Engineer',
            Company__c = comp.Id,
            Canonical_Job_Id__c = '22222222-3333-4444-5555-666666666666',
            Availability__c = 'Active'
        );
        insert job;

        Generation_Request__c req = new Generation_Request__c(
            Job__c = job.Id,
            Document_Type__c = 'cv',
            Language__c = 'en',
            Template_Id__c = 'layout-cv-basic-a4',
            Context_Strategy__c = 'json',
            Status__c = 'Failed',
            Completed_At__c = System.now(),
            Error_Reason__c = 'Failure test',
            Contract_Schema_Version__c = '1.0'
        );
        insert req;

        JA_Request_Notification__c notif = new JA_Request_Notification__c(
            Alert_Key__c = 'test-alert-key-1234567890abcdef1234567890abcdef1234567890abcdef12345678',
            Source_Event_Key__c = 'failure:org:req:ep-1',
            Event_Kind__c = 'action_required',
            Generation_Request__c = req.Id,
            Recipient_User__c = UserInfo.getUserId(),
            Channel__c = 'salesforce_custom_notification',
            Status__c = 'Pending',
            Payload_Fingerprint__c = 'fingerprint-123',
            Attempts__c = 0,
            Max_Attempts__c = 3,
            Notification_Title__c = 'Draft request needs attention',
            Notification_Body__c = 'Request ' + req.Name + ' could not complete.',
            Target_Record_Id__c = req.Id
        );
        insert notif;
    }

    @IsTest
    static void testDispatchActionRequiredNotification() {
        JA_Request_Notification__c notif = [SELECT Id FROM JA_Request_Notification__c LIMIT 1];

        Test.startTest();
        JA_RequestNotificationDispatcher.dispatchNotifications(new List<Id>{ notif.Id });
        Test.stopTest();

        JA_Request_Notification__c updated = [
            SELECT Id, Status__c, Attempts__c, Dispatched_At__c
            FROM JA_Request_Notification__c
            WHERE Id = :notif.Id
        ];

        // Should have attempted dispatch and transitioned to Accepted (or Uncertain/Retry depending on mock)
        Assert.isTrue(updated.Attempts__c >= 1);
        Assert.isNotNull(updated.Dispatched_At__c);
    }

    @IsTest
    static void testSupersededFailureSuppressesDispatch() {
        JA_Request_Notification__c notif = [SELECT Id, Generation_Request__c FROM JA_Request_Notification__c LIMIT 1];
        Generation_Request__c req = [SELECT Id, Status__c, Result_Artifact_Ref__c FROM Generation_Request__c WHERE Id = :notif.Generation_Request__c];
        req.Status__c = 'Ready_for_Review';
        req.Result_Artifact_Ref__c = 'art-ref-123';
        update req;

        Test.startTest();
        JA_RequestNotificationDispatcher.dispatchNotifications(new List<Id>{ notif.Id });
        Test.stopTest();

        JA_Request_Notification__c updated = [
            SELECT Id, Status__c, Safe_Error_Code__c
            FROM JA_Request_Notification__c
            WHERE Id = :notif.Id
        ];
        Assert.areEqual('Suppressed', updated.Status__c);
        Assert.areEqual('SUPERSEDED_BY_READY', updated.Safe_Error_Code__c);
    }
}

