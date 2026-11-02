/**
 * @description Comprehensive unit tests for JA_GenerationSubmit invocable Apex action (SF-06).
 */
@IsTest
private class JA_GenerationSubmitTest {

    @TestSetup
    static void setupTestData() {
        // Create parent Company
        Company__c comp = new Company__c(
            Company_Name__c = 'Acme Corp GmbH',
            Canonical_Company_Id__c = 'b308e9ea-d57b-4d43-9818-f2dbf84fbe71'
        );
        insert comp;

        // Create active Job
        Job__c activeJob = new Job__c(
            Job_Title__c = 'Senior Python Engineer',
            Company__c = comp.Id,
            Canonical_Job_Id__c = '5f49df16-4191-4cf1-8378-c875d6913e61',
            Availability__c = 'Active'
        );
        insert activeJob;

        // Create unavailable Job
        Job__c unavailJob = new Job__c(
            Job_Title__c = 'Closed Legacy Engineer',
            Company__c = comp.Id,
            Canonical_Job_Id__c = '9a13b48f-6bdf-4a94-82a1-12c8b7f8c92a',
            Availability__c = 'Unavailable'
        );
        insert unavailJob;
    }

    @IsTest
    static void testSubmitCV_Success_Created() {
        Job__c job = [SELECT Id FROM Job__c WHERE Availability__c = 'Active' LIMIT 1];

        JA_GenerationSubmit.SubmitRequest req = new JA_GenerationSubmit.SubmitRequest();
        req.jobId = job.Id;
        req.documentType = 'cv';
        req.language = 'de';
        req.templateId = 'layout-cv-basic-a4';
        req.contextStrategy = 'json';
        req.allowUnavailableJob = false;
        req.creationMode = 'reuse_or_create';
        req.submissionToken = 'token-cv-001';

        Test.startTest();
        List<JA_GenerationSubmit.SubmitResult> results = JA_GenerationSubmit.submitRequests(
            new List<JA_GenerationSubmit.SubmitRequest>{ req }
        );
        Test.stopTest();

        System.assertEquals(1, results.size());
        JA_GenerationSubmit.SubmitResult res = results[0];
        System.assertEquals('created', res.outcome);
        System.assertEquals(true, res.isSuccess);
        System.assertNotEquals(null, res.requestId);
        System.assertEquals('Pending', res.processingState);
        System.assert(res.message.contains('queued'));

        // Verify request inserted
        Generation_Request__c createdReq = [
            SELECT Id, Status__c, Document_Type__c, Language__c, Template_Id__c, Allow_Unavailable_Job__c
            FROM Generation_Request__c
            WHERE Id = :res.requestId
        ];
        System.assertEquals('Pending', createdReq.Status__c);
        System.assertEquals('cv', createdReq.Document_Type__c);
        System.assertEquals('de', createdReq.Language__c);
        System.assertEquals('layout-cv-basic-a4', createdReq.Template_Id__c);
        System.assertEquals(false, createdReq.Allow_Unavailable_Job__c);

        // Verify submission receipt inserted
        List<JA_Generation_Submission__c> receipts = [
            SELECT Id, Submission_Key__c, Outcome__c, Request__c
            FROM JA_Generation_Submission__c
            WHERE Request__c = :res.requestId
        ];
        System.assertEquals(1, receipts.size());
        System.assertEquals('created', receipts[0].Outcome__c);
    }

    @IsTest
    static void testSubmitCoverLetter_Success_Created() {
        Job__c job = [SELECT Id FROM Job__c WHERE Availability__c = 'Active' LIMIT 1];

        JA_GenerationSubmit.SubmitRequest req = new JA_GenerationSubmit.SubmitRequest();
        req.jobId = job.Id;
        req.documentType = 'cover_letter';
        req.language = 'en';
        req.templateId = 'layout-letter-basic-a4';
        req.contextStrategy = 'rag';
        req.allowUnavailableJob = false;
        req.creationMode = 'reuse_or_create';
        req.submissionToken = 'token-letter-001';

        Test.startTest();
        List<JA_GenerationSubmit.SubmitResult> results = JA_GenerationSubmit.submitRequests(
            new List<JA_GenerationSubmit.SubmitRequest>{ req }
        );
        Test.stopTest();

        System.assertEquals(1, results.size());
        JA_GenerationSubmit.SubmitResult res = results[0];
        System.assertEquals('created', res.outcome);
        System.assertEquals(true, res.isSuccess);
        System.assertNotEquals(null, res.requestId);

        Generation_Request__c createdReq = [
            SELECT Id, Status__c, Document_Type__c, Language__c, Context_Strategy__c
            FROM Generation_Request__c
            WHERE Id = :res.requestId
        ];
        System.assertEquals('cover_letter', createdReq.Document_Type__c);
        System.assertEquals('en', createdReq.Language__c);
        System.assertEquals('rag', createdReq.Context_Strategy__c);
    }

    @IsTest
    static void testSubmit_ActiveReuse_Pending() {
        Job__c job = [SELECT Id FROM Job__c WHERE Availability__c = 'Active' LIMIT 1];

        // Create initial request
        Generation_Request__c activeReq = new Generation_Request__c(
            Job__c = job.Id,
            Document_Type__c = 'cv',
            Language__c = 'de',
            Template_Id__c = 'layout-cv-basic-a4',
            Context_Strategy__c = 'json',
            Allow_Unavailable_Job__c = false,
            Status__c = 'Pending',
            Contract_Schema_Version__c = '1.0'
        );
        insert activeReq;

        JA_GenerationSubmit.SubmitRequest req = new JA_GenerationSubmit.SubmitRequest();
        req.jobId = job.Id;
        req.documentType = 'cv';
        req.language = 'de';
        req.templateId = 'layout-cv-basic-a4';
        req.contextStrategy = 'json';
        req.allowUnavailableJob = false;
        req.creationMode = 'reuse_or_create';
        req.submissionToken = 'different-token-002';

        Test.startTest();
        List<JA_GenerationSubmit.SubmitResult> results = JA_GenerationSubmit.submitRequests(
            new List<JA_GenerationSubmit.SubmitRequest>{ req }
        );
        Test.stopTest();

        System.assertEquals(1, results.size());
        JA_GenerationSubmit.SubmitResult res = results[0];
        System.assertEquals('reused_active', res.outcome);
        System.assertEquals(activeReq.Id, res.requestId);
        System.assertEquals(true, res.isSuccess);
        System.assert(res.message.contains('already exists'));

        // Confirm only 1 Generation_Request__c exists in DB
        Integer count = [SELECT COUNT() FROM Generation_Request__c WHERE Job__c = :job.Id];
        System.assertEquals(1, count);
    }

    @IsTest
    static void testSubmit_ActiveReuse_Running() {
        Job__c job = [SELECT Id FROM Job__c WHERE Availability__c = 'Active' LIMIT 1];

        Generation_Request__c runningReq = new Generation_Request__c(
            Job__c = job.Id,
            Document_Type__c = 'cv',
            Language__c = 'de',
            Template_Id__c = 'layout-cv-basic-a4',
            Context_Strategy__c = 'json',
            Allow_Unavailable_Job__c = false,
            Status__c = 'Running',
            Worker_Claimed_At__c = Datetime.now(),
            Frozen_Posting_Revision__c = 'rev1',
            Frozen_Profile_Version__c = 'prof1',
            Frozen_Policy_Version__c = 'pol1',
            Frozen_Template_Version__c = 'tmpl1',
            Contract_Schema_Version__c = '1.0'
        );
        insert runningReq;

        JA_GenerationSubmit.SubmitRequest req = new JA_GenerationSubmit.SubmitRequest();
        req.jobId = job.Id;
        req.documentType = 'cv';
        req.language = 'de';
        req.templateId = 'layout-cv-basic-a4';
        req.contextStrategy = 'json';
        req.allowUnavailableJob = false;
        req.creationMode = 'reuse_or_create';
        req.submissionToken = 'token-running-003';

        Test.startTest();
        List<JA_GenerationSubmit.SubmitResult> results = JA_GenerationSubmit.submitRequests(
            new List<JA_GenerationSubmit.SubmitRequest>{ req }
        );
        Test.stopTest();

        System.assertEquals(1, results.size());
        JA_GenerationSubmit.SubmitResult res = results[0];
        System.assertEquals('reused_active', res.outcome);
        System.assertEquals(runningReq.Id, res.requestId);
        System.assertEquals('Running', res.processingState);
    }

    @IsTest
    static void testSubmit_Replay_SameToken() {
        Job__c job = [SELECT Id FROM Job__c WHERE Availability__c = 'Active' LIMIT 1];

        JA_GenerationSubmit.SubmitRequest req = new JA_GenerationSubmit.SubmitRequest();
        req.jobId = job.Id;
        req.documentType = 'cv';
        req.language = 'de';
        req.templateId = 'layout-cv-basic-a4';
        req.contextStrategy = 'json';
        req.allowUnavailableJob = false;
        req.creationMode = 'reuse_or_create';
        req.submissionToken = 'replay-token-100';

        // First submit: created
        List<JA_GenerationSubmit.SubmitResult> results1 = JA_GenerationSubmit.submitRequests(
            new List<JA_GenerationSubmit.SubmitRequest>{ req }
        );
        System.assertEquals('created', results1[0].outcome);
        Id origId = results1[0].requestId;

        // Second submit with exact same token & parameters: replayed
        Test.startTest();
        List<JA_GenerationSubmit.SubmitResult> results2 = JA_GenerationSubmit.submitRequests(
            new List<JA_GenerationSubmit.SubmitRequest>{ req }
        );
        Test.stopTest();

        System.assertEquals(1, results2.size());
        JA_GenerationSubmit.SubmitResult res2 = results2[0];
        System.assertEquals('replayed', res2.outcome);
        System.assertEquals(origId, res2.requestId);
        System.assertEquals(true, res2.isSuccess);
        System.assert(res2.message.contains('previously submitted'));
    }

    @IsTest
    static void testSubmit_Replay_Conflict_DifferentPayload() {
        Job__c job = [SELECT Id FROM Job__c WHERE Availability__c = 'Active' LIMIT 1];

        JA_GenerationSubmit.SubmitRequest req1 = new JA_GenerationSubmit.SubmitRequest();
        req1.jobId = job.Id;
        req1.documentType = 'cv';
        req1.language = 'de';
        req1.templateId = 'layout-cv-basic-a4';
        req1.submissionToken = 'conflict-token-200';

        JA_GenerationSubmit.submitRequests(new List<JA_GenerationSubmit.SubmitRequest>{ req1 });

        // Second submit with SAME token but DIFFERENT language
        JA_GenerationSubmit.SubmitRequest req2 = new JA_GenerationSubmit.SubmitRequest();
        req2.jobId = job.Id;
        req2.documentType = 'cv';
        req2.language = 'en'; // Changed
        req2.templateId = 'layout-cv-basic-a4';
        req2.submissionToken = 'conflict-token-200'; // Same token

        Test.startTest();
        List<JA_GenerationSubmit.SubmitResult> results2 = JA_GenerationSubmit.submitRequests(
            new List<JA_GenerationSubmit.SubmitRequest>{ req2 }
        );
        Test.stopTest();

        System.assertEquals(1, results2.size());
        System.assertEquals('rejected', results2[0].outcome);
        System.assertEquals(false, results2[0].isSuccess);
        System.assert(results2[0].message.contains('conflict'));
    }

    @IsTest
    static void testSubmit_UnavailableJob_RequiresConsent() {
        Job__c unavailJob = [SELECT Id FROM Job__c WHERE Availability__c = 'Unavailable' LIMIT 1];

        JA_GenerationSubmit.SubmitRequest req = new JA_GenerationSubmit.SubmitRequest();
        req.jobId = unavailJob.Id;
        req.documentType = 'cv';
        req.language = 'de';
        req.templateId = 'layout-cv-basic-a4';
        req.allowUnavailableJob = false; // False by default
        req.submissionToken = 'unavail-token-001';

        Test.startTest();
        List<JA_GenerationSubmit.SubmitResult> results = JA_GenerationSubmit.submitRequests(
            new List<JA_GenerationSubmit.SubmitRequest>{ req }
        );
        Test.stopTest();

        System.assertEquals(1, results.size());
        System.assertEquals('confirmation_required', results[0].outcome);
        System.assertEquals(false, results[0].isSuccess);
        System.assert(results[0].message.contains('Unavailable'));
    }

    @IsTest
    static void testSubmit_UnavailableJob_WithConsent_Succeeds() {
        Job__c unavailJob = [SELECT Id FROM Job__c WHERE Availability__c = 'Unavailable' LIMIT 1];

        JA_GenerationSubmit.SubmitRequest req = new JA_GenerationSubmit.SubmitRequest();
        req.jobId = unavailJob.Id;
        req.documentType = 'cv';
        req.language = 'de';
        req.templateId = 'layout-cv-basic-a4';
        req.allowUnavailableJob = true; // Explicit consent true
        req.submissionToken = 'unavail-token-002';

        Test.startTest();
        List<JA_GenerationSubmit.SubmitResult> results = JA_GenerationSubmit.submitRequests(
            new List<JA_GenerationSubmit.SubmitRequest>{ req }
        );
        Test.stopTest();

        System.assertEquals(1, results.size());
        System.assertEquals('created', results[0].outcome);
        System.assertEquals(true, results[0].isSuccess);
    }

    @IsTest
    static void testSubmit_FailedUnavailableHistory_RequiresConsent() {
        Job__c job = [SELECT Id FROM Job__c WHERE Availability__c = 'Active' LIMIT 1];

        // Seed a previous failed request with job_unavailable
        Generation_Request__c failedReq = new Generation_Request__c(
            Job__c = job.Id,
            Document_Type__c = 'cv',
            Language__c = 'de',
            Template_Id__c = 'layout-cv-basic-a4',
            Status__c = 'Failed',
            Completed_At__c = Datetime.now(),
            Error_Reason__c = 'job_unavailable',
            Error_Category__c = 'validation',
            Contract_Schema_Version__c = '1.0'
        );
        insert failedReq;

        JA_GenerationSubmit.SubmitRequest req = new JA_GenerationSubmit.SubmitRequest();
        req.jobId = job.Id;
        req.documentType = 'cv';
        req.language = 'de';
        req.templateId = 'layout-cv-basic-a4';
        req.allowUnavailableJob = false;
        req.submissionToken = 'failed-history-token-001';

        Test.startTest();
        List<JA_GenerationSubmit.SubmitResult> results = JA_GenerationSubmit.submitRequests(
            new List<JA_GenerationSubmit.SubmitRequest>{ req }
        );
        Test.stopTest();

        System.assertEquals(1, results.size());
        System.assertEquals('confirmation_required', results[0].outcome);
        System.assert(results[0].message.contains('failed because this job was unavailable'));
    }

    @IsTest
    static void testSubmit_DeliberateRegeneration_Success() {
        Job__c job = [SELECT Id FROM Job__c WHERE Availability__c = 'Active' LIMIT 1];

        // Initial completed draft
        Generation_Request__c readyReq = new Generation_Request__c(
            Job__c = job.Id,
            Document_Type__c = 'cv',
            Language__c = 'de',
            Template_Id__c = 'layout-cv-basic-a4',
            Status__c = 'Ready_for_Review',
            Worker_Claimed_At__c = Datetime.now().addMinutes(-10),
            Completed_At__c = Datetime.now(),
            Result_Artifact_Ref__c = '068000000000001AAA',
            Frozen_Posting_Revision__c = 'rev1',
            Frozen_Profile_Version__c = 'prof1',
            Frozen_Policy_Version__c = 'pol1',
            Frozen_Template_Version__c = 'tmpl1',
            Contract_Schema_Version__c = '1.0'
        );
        insert readyReq;

        JA_GenerationSubmit.SubmitRequest req = new JA_GenerationSubmit.SubmitRequest();
        req.jobId = job.Id;
        req.documentType = 'cv';
        req.language = 'en'; // Deliberately change language
        req.templateId = 'layout-cv-compact-a4'; // Deliberately change template
        req.creationMode = 'regenerate';
        req.predecessorRequestId = readyReq.Id;
        req.submissionToken = 'regen-token-001';

        Test.startTest();
        List<JA_GenerationSubmit.SubmitResult> results = JA_GenerationSubmit.submitRequests(
            new List<JA_GenerationSubmit.SubmitRequest>{ req }
        );
        Test.stopTest();

        System.assertEquals(1, results.size());
        JA_GenerationSubmit.SubmitResult res = results[0];
        System.assertEquals('created', res.outcome);
        System.assertNotEquals(readyReq.Id, res.requestId);

        Generation_Request__c regenReq = [
            SELECT Id, Predecessor_Request__c, Document_Type__c, Language__c, Template_Id__c, Status__c
            FROM Generation_Request__c
            WHERE Id = :res.requestId
        ];
        System.assertEquals(readyReq.Id, regenReq.Predecessor_Request__c);
        System.assertEquals('en', regenReq.Language__c);
        System.assertEquals('layout-cv-compact-a4', regenReq.Template_Id__c);
        System.assertEquals('Pending', regenReq.Status__c);
    }

    @IsTest
    static void testSubmit_InvalidTemplate_Fails() {
        Job__c job = [SELECT Id FROM Job__c WHERE Availability__c = 'Active' LIMIT 1];

        JA_GenerationSubmit.SubmitRequest req = new JA_GenerationSubmit.SubmitRequest();
        req.jobId = job.Id;
        req.documentType = 'cv';
        req.templateId = 'non_existent_template_xyz';
        req.submissionToken = 'invalid-tmpl-token';

        Test.startTest();
        List<JA_GenerationSubmit.SubmitResult> results = JA_GenerationSubmit.submitRequests(
            new List<JA_GenerationSubmit.SubmitRequest>{ req }
        );
        Test.stopTest();

        System.assertEquals(1, results.size());
        System.assertEquals('rejected', results[0].outcome);
        System.assert(results[0].message.contains('Unknown template ID'));
    }
}

