/**
 * @description Unit tests for JA_RunSummaryGuard (SF-09).
 */
@IsTest
private class JA_RunSummaryGuardTest {

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
    }

    @IsTest
    static void testFirstCompletionAdmission() {
        Run_Summary__c sum = new Run_Summary__c(
            Run_Id__c = '11111111-2222-3333-4444-555555555555',
            Name = 'Successful Run',
            Pipeline_Status__c = 'success',
            Start_Time__c = System.now().addMinutes(-10),
            End_Time__c = System.now(),
            Duration_Seconds__c = 600.0,
            Headline__c = '10 postings observed',
            Summary_Text__c = 'Full details of execution',
            Source_Postings_Count__c = 10,
            Canonical_Jobs_New__c = 5,
            Revision__c = 1,
            Payload_Hash__c = 'hash-rev-1'
        );

        Test.startTest();
        JA_RunSummaryGuard.guardRunSummaries(new List<Run_Summary__c>{ sum }, null);
        insert sum;
        Test.stopTest();

        Run_Summary__c inserted = [
            SELECT Id, Completion_Recorded_At__c, First_Status__c, First_Headline__c,
                   First_Completion_Key__c, Notification_Status__c, Notification_Recipient__c
            FROM Run_Summary__c
            WHERE Id = :sum.Id
        ];

        System.assertNotEquals(null, inserted.Completion_Recorded_At__c, 'Completion timestamp should be recorded.');
        System.assertEquals('success', inserted.First_Status__c, 'First status should be frozen.');
        System.assertEquals('10 postings observed', inserted.First_Headline__c, 'First headline frozen.');
        System.assertEquals('pending', inserted.Notification_Status__c, 'Notification should be pending.');
        System.assertEquals(UserInfo.getUserId(), inserted.Notification_Recipient__c, 'Candidate user resolved.');
    }

    @IsTest
    static void testReplaySameRevisionNoOp() {
        Run_Summary__c sum = new Run_Summary__c(
            Run_Id__c = '22222222-3333-4444-5555-666666666666',
            Name = 'Successful Run 2',
            Pipeline_Status__c = 'success',
            Start_Time__c = System.now().addMinutes(-5),
            End_Time__c = System.now(),
            Duration_Seconds__c = 300.0,
            Headline__c = 'Headline 2',
            Revision__c = 1,
            Payload_Hash__c = 'hash-rev-2'
        );
        JA_RunSummaryGuard.guardRunSummaries(new List<Run_Summary__c>{ sum }, null);
        insert sum;

        // Simulate confirmed notification
        sum.Notification_Status__c = 'confirmed';
        sum.Notification_Receipt_Id__c = 'receipt-123';
        sum.Notification_Accepted_At__c = System.now();
        update sum;

        // Replay exact same revision
        Run_Summary__c replay = new Run_Summary__c(
            Id = sum.Id,
            Run_Id__c = sum.Run_Id__c,
            Name = sum.Name,
            Pipeline_Status__c = sum.Pipeline_Status__c,
            Revision__c = 1,
            Payload_Hash__c = 'hash-rev-2'
        );

        Test.startTest();
        JA_RunSummaryGuard.guardRunSummaries(
            new List<Run_Summary__c>{ replay },
            new Map<Id, Run_Summary__c>{ sum.Id => sum }
        );
        Test.stopTest();

        System.assertEquals('confirmed', replay.Notification_Status__c, 'Confirmed status must not be reset on replay.');
        System.assertEquals('receipt-123', replay.Notification_Receipt_Id__c, 'Receipt ID preserved.');
    }

    @IsTest
    static void testResumeHigherRevisionPreservesFirstSnapshot() {
        Run_Summary__c sum = new Run_Summary__c(
            Run_Id__c = '33333333-4444-5555-6666-777777777777',
            Name = 'Initial Failed Run',
            Pipeline_Status__c = 'failed',
            Start_Time__c = System.now().addMinutes(-15),
            End_Time__c = System.now().addMinutes(-10),
            Headline__c = 'Failure snapshot',
            Revision__c = 1,
            Payload_Hash__c = 'hash-rev-1'
        );
        JA_RunSummaryGuard.guardRunSummaries(new List<Run_Summary__c>{ sum }, null);
        insert sum;

        // Resumed run arrives as revision 2 with success
        Run_Summary__c resume = new Run_Summary__c(
            Id = sum.Id,
            Run_Id__c = sum.Run_Id__c,
            Name = 'Resumed Success',
            Pipeline_Status__c = 'success',
            Headline__c = 'Resumed Success Headline',
            Revision__c = 2,
            Payload_Hash__c = 'hash-rev-2'
        );

        Test.startTest();
        JA_RunSummaryGuard.guardRunSummaries(
            new List<Run_Summary__c>{ resume },
            new Map<Id, Run_Summary__c>{ sum.Id => sum }
        );
        Test.stopTest();

        System.assertEquals('success', resume.Pipeline_Status__c, 'Latest pipeline status should update.');
        System.assertEquals('failed', resume.First_Status__c, 'First status snapshot must remain failed.');
        System.assertEquals('Failure snapshot', resume.First_Headline__c, 'First headline snapshot must remain frozen.');
    }

    @IsTest
    static void testStaleRevisionRejected() {
        Run_Summary__c sum = new Run_Summary__c(
            Run_Id__c = '44444444-5555-6666-7777-888888888888',
            Name = 'Run Rev 2',
            Pipeline_Status__c = 'success',
            Revision__c = 2,
            Payload_Hash__c = 'hash-rev-2'
        );
        JA_RunSummaryGuard.guardRunSummaries(new List<Run_Summary__c>{ sum }, null);
        insert sum;

        Run_Summary__c stale = new Run_Summary__c(
            Id = sum.Id,
            Run_Id__c = sum.Run_Id__c,
            Revision__c = 1,
            Payload_Hash__c = 'hash-rev-1'
        );

        Boolean threw = false;
        try {
            JA_RunSummaryGuard.guardRunSummaries(
                new List<Run_Summary__c>{ stale },
                new Map<Id, Run_Summary__c>{ sum.Id => sum }
            );
        } catch (JA_RunSummaryGuard.AdmissionException ex) {
            threw = true;
            System.assert(ex.getMessage().contains('Stale revision rejected'), 'Error message should mention stale revision.');
        }
        System.assert(threw, 'Stale revision must throw an exception.');
    }
}

