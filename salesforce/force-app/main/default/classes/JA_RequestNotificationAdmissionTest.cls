/**
 * @description Unit test suite for JA_RequestNotificationAdmission service (SF-08).
 */
@IsTest
private class JA_RequestNotificationAdmissionTest {

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
            Language__c = 'de',
            Template_Id__c = 'layout-cv-basic-a4',
            Context_Strategy__c = 'json',
            Status__c = 'Pending',
            Contract_Schema_Version__c = '1.0'
        );
        insert req;

        JA_Notification_Config__c cfg = new JA_Notification_Config__c(
            Org_Key__c = 'default',
            Is_Enabled__c = true,
            Candidate_User__c = UserInfo.getUserId(),
            Preferred_Language__c = 'en'
        );
        insert cfg;
    }

    @IsTest
    static void testPendingStatusNotEligible() {
        Generation_Request__c req = [SELECT Id FROM Generation_Request__c LIMIT 1];

        JA_RequestNotificationAdmission.AdmissionInput inp = new JA_RequestNotificationAdmission.AdmissionInput();
        inp.requestId = req.Id;

        Test.startTest();
        List<JA_RequestNotificationAdmission.AdmissionOutput> results =
            JA_RequestNotificationAdmission.admitNotifications(new List<JA_RequestNotificationAdmission.AdmissionInput>{ inp });
        Test.stopTest();

        Assert.areEqual(1, results.size());
        Assert.areEqual('not_eligible', results[0].outcome);
        Assert.areEqual('INTERMEDIATE_PROCESSING_STATE', results[0].reasonCode);
    }

    @IsTest
    static void testFailedStatusAdmitsActionRequired() {
        Generation_Request__c req = [SELECT Id, Status__c, Completed_At__c, Error_Reason__c FROM Generation_Request__c LIMIT 1];
        req.Status__c = 'Failed';
        req.Completed_At__c = System.now();
        req.Error_Reason__c = 'Inference timeout';
        req.Error_Category__c = 'MODEL_TIMEOUT';
        update req;

        JA_RequestNotificationAdmission.AdmissionInput inp = new JA_RequestNotificationAdmission.AdmissionInput();
        inp.requestId = req.Id;
        inp.failureEpisodeId = 'ep-fail-1';

        Test.startTest();
        List<JA_RequestNotificationAdmission.AdmissionOutput> results =
            JA_RequestNotificationAdmission.admitNotifications(new List<JA_RequestNotificationAdmission.AdmissionInput>{ inp });
        Test.stopTest();

        Assert.areEqual(1, results.size());
        Assert.areEqual('admitted', results[0].outcome);
        Assert.isNotNull(results[0].alertKey);
        Assert.isNotNull(results[0].notificationId);

        JA_Request_Notification__c notif = [
            SELECT Id, Status__c, Event_Kind__c, Notification_Title__c, Action_Code__c
            FROM JA_Request_Notification__c
            WHERE Id = :results[0].notificationId
        ];
        Assert.areEqual('Pending', notif.Status__c);
        Assert.areEqual('action_required', notif.Event_Kind__c);
        Assert.areEqual('terminal_failure', notif.Action_Code__c);
        Assert.isTrue(notif.Notification_Title__c.contains('needs attention'));
    }

    @IsTest
    static void testConfigDisabledBlocksAdmission() {
        JA_Notification_Config__c cfg = [SELECT Id, Is_Enabled__c FROM JA_Notification_Config__c LIMIT 1];
        cfg.Is_Enabled__c = false;
        update cfg;

        Generation_Request__c req = [SELECT Id FROM Generation_Request__c LIMIT 1];
        req.Status__c = 'Failed';
        req.Completed_At__c = System.now();
        req.Error_Reason__c = 'Fatal error';
        update req;

        JA_RequestNotificationAdmission.AdmissionInput inp = new JA_RequestNotificationAdmission.AdmissionInput();
        inp.requestId = req.Id;

        Test.startTest();
        List<JA_RequestNotificationAdmission.AdmissionOutput> results =
            JA_RequestNotificationAdmission.admitNotifications(new List<JA_RequestNotificationAdmission.AdmissionInput>{ inp });
        Test.stopTest();

        Assert.areEqual(1, results.size());
        Assert.areEqual('blocked', results[0].outcome);
        Assert.areEqual('CONFIG_DISABLED', results[0].reasonCode);
    }
}

