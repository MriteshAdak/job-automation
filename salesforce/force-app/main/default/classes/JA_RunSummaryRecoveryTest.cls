/**
 * @description Unit tests for JA_RunSummaryRecovery (SF-09).
 */
@IsTest
private class JA_RunSummaryRecoveryTest {

    @TestSetup
    static void setupTestData() {
        Run_Summary__c sum = new Run_Summary__c(
            Run_Id__c = '66666666-7777-8888-9999-000000000000',
            Name = 'Failed Run',
            Pipeline_Status__c = 'failed',
            Notification_Status__c = 'failed',
            Notification_Error_Code__c = 'MAX_RETRIES_EXCEEDED',
            First_Completion_Key__c = 'org:66666666-7777-8888-9999-000000000000',
            Revision__c = 1
        );
        insert sum;

        Run_Summary__c sumUnknown = new Run_Summary__c(
            Run_Id__c = '77777777-8888-9999-0000-111111111111',
            Name = 'Unknown Run',
            Pipeline_Status__c = 'success',
            Notification_Status__c = 'unknown',
            Notification_Error_Code__c = 'AMBIGUOUS_SEND',
            First_Completion_Key__c = 'org:77777777-8888-9999-0000-111111111111',
            Revision__c = 1
        );
        insert sumUnknown;
    }

    @IsTest
    static void testRetryFailed() {
        Run_Summary__c sum = [SELECT Id FROM Run_Summary__c WHERE Notification_Status__c = 'failed' LIMIT 1];

        Test.startTest();
        JA_RunSummaryRecovery.retryFailed(sum.Id);
        Test.stopTest();

        Run_Summary__c updated = [SELECT Id, Notification_Status__c, Notification_Error_Code__c FROM Run_Summary__c WHERE Id = :sum.Id];
        System.assertEquals('retry_wait', updated.Notification_Status__c);
        System.assertEquals('OPERATOR_RETRY_SCHEDULED', updated.Notification_Error_Code__c);
    }

    @IsTest
    static void testReconcileUnknownProvenSend() {
        Run_Summary__c sum = [SELECT Id FROM Run_Summary__c WHERE Notification_Status__c = 'unknown' LIMIT 1];

        Test.startTest();
        JA_RunSummaryRecovery.reconcileUnknown(sum.Id, true, 'manual-receipt-123');
        Test.stopTest();

        Run_Summary__c updated = [SELECT Id, Notification_Status__c, Notification_Receipt_Id__c FROM Run_Summary__c WHERE Id = :sum.Id];
        System.assertEquals('confirmed', updated.Notification_Status__c);
        System.assertEquals('manual-receipt-123', updated.Notification_Receipt_Id__c);
    }

    @IsTest
    static void testReconcileUnknownProvenNonSend() {
        Run_Summary__c sum = [SELECT Id FROM Run_Summary__c WHERE Notification_Status__c = 'unknown' LIMIT 1];

        Test.startTest();
        JA_RunSummaryRecovery.reconcileUnknown(sum.Id, false, null);
        Test.stopTest();

        Run_Summary__c updated = [SELECT Id, Notification_Status__c, Notification_Error_Code__c FROM Run_Summary__c WHERE Id = :sum.Id];
        System.assertEquals('retry_wait', updated.Notification_Status__c);
        System.assertEquals('RECONCILED_NON_SEND', updated.Notification_Error_Code__c);
    }
}

