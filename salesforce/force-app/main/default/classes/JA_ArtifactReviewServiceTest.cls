/**
 * @description Unit test suite for JA_ArtifactReviewService (SF-07).
 */
@IsTest
private class JA_ArtifactReviewServiceTest {

    @TestSetup
    static void setupTestData() {
        Company__c comp = new Company__c(
            Company_Name__c = 'Tech Innovators',
            Canonical_Company_Id__c = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        );
        insert comp;

        Job__c job = new Job__c(
            Job_Title__c = 'Principal Engineer',
            Company__c = comp.Id,
            Canonical_Job_Id__c = 'ffffffff-0000-1111-2222-333333333333',
            Availability__c = 'Active'
        );
        insert job;

        Generation_Request__c req = new Generation_Request__c(
            Job__c = job.Id,
            Document_Type__c = 'cv',
            Language__c = 'de',
            Template_Id__c = 'layout-cv-basic-a4',
            Context_Strategy__c = 'json',
            Status__c = 'Ready_for_Review',
            Contract_Schema_Version__c = '1.0'
        );
        insert req;

        JA_Artifact_Review__c docxRev = new JA_Artifact_Review__c(
            Binding_Key__c = UserInfo.getOrganizationId() + ':' + req.Id + ':art1:1:docx',
            Generation_Request__c = req.Id,
            Org_Id__c = UserInfo.getOrganizationId(),
            Artifact_Set_Id__c = 'set-1',
            Artifact_Id__c = 'art1',
            Artifact_Version__c = 1,
            Format__c = 'docx',
            Content_Hash__c = 'sha256:hash-docx-1',
            Size_Bytes__c = 1000,
            Content_Document_Id__c = '069000000000001AAA',
            Content_Version_Id__c = '068000000000001AAA',
            Reconciliation_Marker__c = 'marker-docx-1',
            Delivered_At__c = Datetime.now(),
            Approval_Status__c = 'draft',
            Review_Revision__c = 1,
            Contract_Schema_Version__c = '1.0'
        );
        insert docxRev;

        JA_Artifact_Review__c pdfRev = new JA_Artifact_Review__c(
            Binding_Key__c = UserInfo.getOrganizationId() + ':' + req.Id + ':art2:1:pdf',
            Generation_Request__c = req.Id,
            Org_Id__c = UserInfo.getOrganizationId(),
            Artifact_Set_Id__c = 'set-1',
            Artifact_Id__c = 'art2',
            Artifact_Version__c = 1,
            Format__c = 'pdf',
            Content_Hash__c = 'sha256:hash-pdf-1',
            Size_Bytes__c = 2000,
            Content_Document_Id__c = '069000000000002AAA',
            Content_Version_Id__c = '068000000000002AAA',
            Reconciliation_Marker__c = 'marker-pdf-1',
            Delivered_At__c = Datetime.now(),
            Approval_Status__c = 'draft',
            Review_Revision__c = 1,
            Contract_Schema_Version__c = '1.0'
        );
        insert pdfRev;
    }

    @IsTest
    static void testGetReviewUIState() {
        Generation_Request__c req = [SELECT Id FROM Generation_Request__c LIMIT 1];

        Test.startTest();
        JA_ArtifactReviewService.ReviewUIStateDTO state = JA_ArtifactReviewService.getReviewUIState(req.Id);
        Test.stopTest();

        System.assertNotEquals(null, state);
        System.assertEquals(req.Id, state.requestId);
        System.assertEquals('Ready_for_Review', state.requestStatus);
        System.assertEquals(true, state.allFormatsDelivered);
        System.assertEquals(2, state.formatCards.size());
    }

    @IsTest
    static void testApproveDocxLeavesPdfDraft() {
        Generation_Request__c req = [SELECT Id FROM Generation_Request__c LIMIT 1];
        JA_Artifact_Review__c docxRev = [SELECT Id, Content_Version_Id__c, Content_Hash__c, Review_Revision__c FROM JA_Artifact_Review__c WHERE Generation_Request__c = :req.Id AND Format__c = 'docx' LIMIT 1];
        JA_Artifact_Review__c pdfRev = [SELECT Id, Approval_Status__c FROM JA_Artifact_Review__c WHERE Generation_Request__c = :req.Id AND Format__c = 'pdf' LIMIT 1];

        JA_ArtifactReviewService.ReviewCommandInput input = new JA_ArtifactReviewService.ReviewCommandInput();
        input.action = 'approve';
        input.selectedReviewId = docxRev.Id;
        input.expectedVersionId = docxRev.Content_Version_Id__c;
        input.expectedContentHash = docxRev.Content_Hash__c;
        input.expectedReviewRevision = (Integer) docxRev.Review_Revision__c;
        input.intentToken = 'token-approve-1';
        input.explicitAcknowledgment = true;
        input.candidateNotes = 'Looks great!';

        Test.startTest();
        JA_ArtifactReviewService.ReviewCommandResult res = JA_ArtifactReviewService.executeReviewCommand(input);
        Test.stopTest();

        System.assertEquals(true, res.isSuccess);
        System.assertEquals('recorded', res.outcome);
        System.assertEquals('approved', res.currentStatus);

        // Verify docx is approved, pdf remains draft
        JA_Artifact_Review__c checkDocx = [SELECT Approval_Status__c, Approved_By__c, Approved_At__c FROM JA_Artifact_Review__c WHERE Id = :docxRev.Id];
        System.assertEquals('approved', checkDocx.Approval_Status__c);
        System.assertNotEquals(null, checkDocx.Approved_By__c);
        System.assertNotEquals(null, checkDocx.Approved_At__c);

        JA_Artifact_Review__c checkPdf = [SELECT Approval_Status__c FROM JA_Artifact_Review__c WHERE Id = :pdfRev.Id];
        System.assertEquals('draft', checkPdf.Approval_Status__c, 'Approving DOCX must NOT approve PDF');

        // Check event logged
        List<JA_Artifact_Review_Event__c> events = [SELECT Id, Action__c, Actor__c FROM JA_Artifact_Review_Event__c WHERE Artifact_Review__c = :docxRev.Id];
        System.assertEquals(1, events.size());
        System.assertEquals('approve', events[0].Action__c);
    }

    @IsTest
    static void testDuplicateApprovalRequiresReplace() {
        Generation_Request__c req = [SELECT Id, Job__c FROM Generation_Request__c LIMIT 1];
        JA_Artifact_Review__c docxRev = [SELECT Id, Content_Version_Id__c, Content_Hash__c, Review_Revision__c FROM JA_Artifact_Review__c WHERE Generation_Request__c = :req.Id AND Format__c = 'docx' LIMIT 1];

        // First approval
        JA_ArtifactReviewService.ReviewCommandInput input1 = new JA_ArtifactReviewService.ReviewCommandInput();
        input1.action = 'approve';
        input1.selectedReviewId = docxRev.Id;
        input1.expectedVersionId = docxRev.Content_Version_Id__c;
        input1.expectedContentHash = docxRev.Content_Hash__c;
        input1.expectedReviewRevision = (Integer) docxRev.Review_Revision__c;
        input1.intentToken = 'token-first-1';
        input1.explicitAcknowledgment = true;
        JA_ArtifactReviewService.executeReviewCommand(input1);

        // Create second request and docx review record
        Generation_Request__c req2 = new Generation_Request__c(
            Job__c = req.Job__c,
            Document_Type__c = 'cv',
            Language__c = 'de',
            Template_Id__c = 'layout-cv-basic-a4',
            Context_Strategy__c = 'json',
            Status__c = 'Ready_for_Review',
            Contract_Schema_Version__c = '1.0'
        );
        insert req2;

        JA_Artifact_Review__c docxRev2 = new JA_Artifact_Review__c(
            Binding_Key__c = UserInfo.getOrganizationId() + ':' + req2.Id + ':art1:2:docx',
            Generation_Request__c = req2.Id,
            Org_Id__c = UserInfo.getOrganizationId(),
            Artifact_Set_Id__c = 'set-2',
            Artifact_Id__c = 'art1',
            Artifact_Version__c = 2,
            Format__c = 'docx',
            Content_Hash__c = 'sha256:hash-docx-2',
            Size_Bytes__c = 1500,
            Content_Document_Id__c = '069000000000003AAA',
            Content_Version_Id__c = '068000000000003AAA',
            Reconciliation_Marker__c = 'marker-docx-2',
            Delivered_At__c = Datetime.now(),
            Approval_Status__c = 'draft',
            Review_Revision__c = 1,
            Contract_Schema_Version__c = '1.0'
        );
        insert docxRev2;

        // Trying 'approve' on docxRev2 must fail because docxRev is already approved
        JA_ArtifactReviewService.ReviewCommandInput input2 = new JA_ArtifactReviewService.ReviewCommandInput();
        input2.action = 'approve';
        input2.selectedReviewId = docxRev2.Id;
        input2.expectedVersionId = docxRev2.Content_Version_Id__c;
        input2.expectedContentHash = docxRev2.Content_Hash__c;
        input2.expectedReviewRevision = 1;
        input2.intentToken = 'token-second-1';
        input2.explicitAcknowledgment = true;

        Test.startTest();
        JA_ArtifactReviewService.ReviewCommandResult res = JA_ArtifactReviewService.executeReviewCommand(input2);
        Test.stopTest();

        System.assertEquals(false, res.isSuccess);
        System.assertEquals('conflict', res.outcome);
        System.assertEquals('approval_already_exists', res.errorReason);
    }

    @IsTest
    static void testApproveAndReplaceAtomic() {
        Generation_Request__c req = [SELECT Id, Job__c FROM Generation_Request__c LIMIT 1];
        JA_Artifact_Review__c docxRev1 = [SELECT Id, Content_Version_Id__c, Content_Hash__c, Review_Revision__c FROM JA_Artifact_Review__c WHERE Generation_Request__c = :req.Id AND Format__c = 'docx' LIMIT 1];

        // Approve docxRev1
        JA_ArtifactReviewService.ReviewCommandInput input1 = new JA_ArtifactReviewService.ReviewCommandInput();
        input1.action = 'approve';
        input1.selectedReviewId = docxRev1.Id;
        input1.expectedVersionId = docxRev1.Content_Version_Id__c;
        input1.expectedContentHash = docxRev1.Content_Hash__c;
        input1.expectedReviewRevision = (Integer) docxRev1.Review_Revision__c;
        input1.intentToken = 'token-approve-1';
        input1.explicitAcknowledgment = true;
        JA_ArtifactReviewService.executeReviewCommand(input1);

        // Create second request
        Generation_Request__c req2 = new Generation_Request__c(
            Job__c = req.Job__c,
            Document_Type__c = 'cv',
            Language__c = 'de',
            Template_Id__c = 'layout-cv-basic-a4',
            Context_Strategy__c = 'json',
            Status__c = 'Ready_for_Review',
            Contract_Schema_Version__c = '1.0'
        );
        insert req2;

        JA_Artifact_Review__c docxRev2 = new JA_Artifact_Review__c(
            Binding_Key__c = UserInfo.getOrganizationId() + ':' + req2.Id + ':art1:2:docx',
            Generation_Request__c = req2.Id,
            Org_Id__c = UserInfo.getOrganizationId(),
            Artifact_Set_Id__c = 'set-2',
            Artifact_Id__c = 'art1',
            Artifact_Version__c = 2,
            Format__c = 'docx',
            Content_Hash__c = 'sha256:hash-docx-2',
            Size_Bytes__c = 1500,
            Content_Document_Id__c = '069000000000003AAA',
            Content_Version_Id__c = '068000000000003AAA',
            Reconciliation_Marker__c = 'marker-docx-2',
            Delivered_At__c = Datetime.now(),
            Approval_Status__c = 'draft',
            Review_Revision__c = 1,
            Contract_Schema_Version__c = '1.0'
        );
        insert docxRev2;

        // Execute approve_and_replace
        JA_ArtifactReviewService.ReviewCommandInput input2 = new JA_ArtifactReviewService.ReviewCommandInput();
        input2.action = 'approve_and_replace';
        input2.selectedReviewId = docxRev2.Id;
        input2.expectedVersionId = docxRev2.Content_Version_Id__c;
        input2.expectedContentHash = docxRev2.Content_Hash__c;
        input2.expectedReviewRevision = 1;
        input2.replacedReviewId = docxRev1.Id;
        input2.intentToken = 'token-replace-1';
        input2.explicitAcknowledgment = true;

        Test.startTest();
        JA_ArtifactReviewService.ReviewCommandResult res = JA_ArtifactReviewService.executeReviewCommand(input2);
        Test.stopTest();

        System.assertEquals(true, res.isSuccess);
        System.assertEquals('recorded', res.outcome);
        System.assertEquals('approved', res.currentStatus);

        // Verify docxRev1 is superseded and docxRev2 is approved
        JA_Artifact_Review__c check1 = [SELECT Approval_Status__c, Superseded_By__c, Superseded_At__c FROM JA_Artifact_Review__c WHERE Id = :docxRev1.Id];
        System.assertEquals('superseded', check1.Approval_Status__c);
        System.assertEquals(docxRev2.Id, check1.Superseded_By__c);
        System.assertNotEquals(null, check1.Superseded_At__c);

        JA_Artifact_Review__c check2 = [SELECT Approval_Status__c, Approved_By__c, Approved_At__c FROM JA_Artifact_Review__c WHERE Id = :docxRev2.Id];
        System.assertEquals('approved', check2.Approval_Status__c);
    }
}

