/**
 * @description Unit tests for JA_RunSummaryDispatcher (SF-09).
 */
@IsTest
private class JA_RunSummaryDispatcherTest {

    @TestSetup
    static void setupTestData() {
        JA_Notification_Config__c cfg = new JA_Notification_Config__c(
            Org_Key__c = 'default',
            Is_Enabled__c = true,
            Candidate_User__c = UserInfo.getUserId(),
            Preferred_Language__c = 'en',
            Max_Retry_Attempts__c = 3,
            Initial_Retry_Delay_Minutes__c = 1
        );
        insert cfg;

        Run_Summary__c sum = new Run_Summary__c(
            Run_Id__c = '55555555-6666-7777-8888-999999999999',
            Name = 'Successful Run',
            Pipeline_Status__c = 'success',
            Start_Time__c = System.now().addMinutes(-10),
            End_Time__c = System.now(),
            Duration_Seconds__c = 600.0,
            Headline__c = '10 postings observed',
            Source_Postings_Count__c = 10,
            Canonical_Jobs_New__c = 5,
            Canonical_Jobs_Updated__c = 2,
            Canonical_Jobs_Duplicate__c = 3,
            Notification_Recipient__c = UserInfo.getUserId(),
            Notification_Status__c = 'pending',
            First_Completion_Key__c = 'org:55555555-6666-7777-8888-999999999999',
            Revision__c = 1
        );
        insert sum;
    }

    @IsTest
    static void testDispatchPendingNotification() {
        Run_Summary__c sum = [SELECT Id FROM Run_Summary__c LIMIT 1];

        Test.startTest();
        JA_RunSummaryDispatcher.dispatchRunSummaries(new List<Id>{ sum.Id });
        Test.stopTest();

        Run_Summary__c updated = [
            SELECT Id, Notification_Status__c, Notification_Claim_Id__c,
                   Notification_Attempt_Count__c, Notification_Receipt_Id__c,
                   Notification_Accepted_At__c
            FROM Run_Summary__c
            WHERE Id = :sum.Id
        ];

        System.assertEquals('confirmed', updated.Notification_Status__c, 'Status should be confirmed.');
        System.assertNotEquals(null, updated.Notification_Claim_Id__c, 'Claim ID must be generated.');
        System.assertEquals(1, updated.Notification_Attempt_Count__c, 'Attempt count must be 1.');
        System.assertNotEquals(null, updated.Notification_Receipt_Id__c, 'Receipt ID must be populated.');
        System.assertNotEquals(null, updated.Notification_Accepted_At__c, 'Accepted timestamp must be populated.');
    }

    @IsTest
    static void testAlreadyConfirmedDoesNotResend() {
        Run_Summary__c sum = [SELECT Id FROM Run_Summary__c LIMIT 1];
        sum.Notification_Status__c = 'confirmed';
        sum.Notification_Receipt_Id__c = 'confirmed-receipt';
        sum.Notification_Accepted_At__c = System.now();
        update sum;

        Test.startTest();
        JA_RunSummaryDispatcher.dispatchRunSummaries(new List<Id>{ sum.Id });
        Test.stopTest();

        Run_Summary__c updated = [
            SELECT Id, Notification_Status__c, Notification_Receipt_Id__c
            FROM Run_Summary__c
            WHERE Id = :sum.Id
        ];
        System.assertEquals('confirmed', updated.Notification_Status__c);
        System.assertEquals('confirmed-receipt', updated.Notification_Receipt_Id__c);
    }
}

