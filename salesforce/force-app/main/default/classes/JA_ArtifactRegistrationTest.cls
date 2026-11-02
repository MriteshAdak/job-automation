/**
 * @description Unit test suite for JA_ArtifactRegistration service (SF-07).
 */
@IsTest
private class JA_ArtifactRegistrationTest {

    @TestSetup
    static void setupTestData() {
        Company__c comp = new Company__c(
            Company_Name__c = 'Acme Corp',
            Canonical_Company_Id__c = '11111111-2222-3333-4444-555555555555'
        );
        insert comp;

        Job__c job = new Job__c(
            Job_Title__c = 'Senior Architect',
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
            Status__c = 'Ready_for_Review',
            Contract_Schema_Version__c = '1.0'
        );
        insert req;
    }

    @IsTest
    static void testRegisterCompleteDeliverySet() {
        Generation_Request__c req = [SELECT Id FROM Generation_Request__c LIMIT 1];

        JA_ArtifactRegistration.RegistrationRequest reg = new JA_ArtifactRegistration.RegistrationRequest();
        reg.generationRequestId = req.Id;
        reg.orgId = UserInfo.getOrganizationId();
        reg.artifactSetId = 'set-12345';
        reg.deliveryReceiptRef = 'receipt-12345';
        reg.safeWarnings = 'Safe test warnings';
        reg.formats = new List<JA_ArtifactRegistration.FormatItem>();

        JA_ArtifactRegistration.FormatItem docxItem = new JA_ArtifactRegistration.FormatItem();
        docxItem.format = 'docx';
        docxItem.artifactId = 'art-docx-1';
        docxItem.artifactVersion = 1;
        docxItem.contentHash = 'sha256:aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111';
        docxItem.sizeBytes = 2048;
        docxItem.contentDocumentId = '069000000000001AAA';
        docxItem.contentVersionId = '068000000000001AAA';
        docxItem.reconciliationMarker = 'gen06:v1:req1:art1:1';
        docxItem.deliveredAt = Datetime.now();
        reg.formats.add(docxItem);

        JA_ArtifactRegistration.FormatItem pdfItem = new JA_ArtifactRegistration.FormatItem();
        pdfItem.format = 'pdf';
        pdfItem.artifactId = 'art-pdf-1';
        pdfItem.artifactVersion = 1;
        pdfItem.contentHash = 'sha256:bbbb2222bbbb2222bbbb2222bbbb2222bbbb2222bbbb2222bbbb2222bbbb2222';
        pdfItem.sizeBytes = 4096;
        pdfItem.contentDocumentId = '069000000000002AAA';
        pdfItem.contentVersionId = '068000000000002AAA';
        pdfItem.reconciliationMarker = 'gen06:v1:req1:art2:1';
        pdfItem.deliveredAt = Datetime.now();
        reg.formats.add(pdfItem);

        Test.startTest();
        JA_ArtifactRegistration.RegistrationResult res = JA_ArtifactRegistration.registerDelivery(reg);
        Test.stopTest();

        System.assertEquals(true, res.isSuccess, 'Registration must succeed for complete set');
        System.assertEquals('registered', res.outcome);
        System.assertEquals(2, res.reviews.size(), 'Must insert 2 review bindings');

        List<JA_Artifact_Review__c> reviews = [SELECT Id, Format__c, Approval_Status__c FROM JA_Artifact_Review__c WHERE Generation_Request__c = :req.Id];
        System.assertEquals(2, reviews.size());
        for (JA_Artifact_Review__c r : reviews) {
            System.assertEquals('draft', r.Approval_Status__c);
        }
    }

    @IsTest
    static void testIncompleteDeliverySetRejected() {
        Generation_Request__c req = [SELECT Id FROM Generation_Request__c LIMIT 1];

        JA_ArtifactRegistration.RegistrationRequest reg = new JA_ArtifactRegistration.RegistrationRequest();
        reg.generationRequestId = req.Id;
        reg.formats = new List<JA_ArtifactRegistration.FormatItem>();

        JA_ArtifactRegistration.FormatItem docxItem = new JA_ArtifactRegistration.FormatItem();
        docxItem.format = 'docx';
        docxItem.artifactId = 'art-docx-1';
        docxItem.artifactVersion = 1;
        reg.formats.add(docxItem);

        Test.startTest();
        JA_ArtifactRegistration.RegistrationResult res = JA_ArtifactRegistration.registerDelivery(reg);
        Test.stopTest();

        System.assertEquals(false, res.isSuccess);
        System.assertEquals('rejected', res.outcome);
        System.assert(res.message.contains('Incomplete delivery set'));
    }

    @IsTest
    static void testIdempotentReplayPreservesApproval() {
        Generation_Request__c req = [SELECT Id FROM Generation_Request__c LIMIT 1];

        // Register initial set
        JA_ArtifactRegistration.RegistrationRequest reg = new JA_ArtifactRegistration.RegistrationRequest();
        reg.generationRequestId = req.Id;
        reg.orgId = UserInfo.getOrganizationId();
        reg.formats = new List<JA_ArtifactRegistration.FormatItem>();

        JA_ArtifactRegistration.FormatItem docxItem = new JA_ArtifactRegistration.FormatItem();
        docxItem.format = 'docx';
        docxItem.artifactId = 'art-docx-1';
        docxItem.artifactVersion = 1;
        docxItem.contentHash = 'sha256:hash1';
        docxItem.sizeBytes = 1000;
        docxItem.contentDocumentId = '069000000000001AAA';
        docxItem.contentVersionId = '068000000000001AAA';
        docxItem.reconciliationMarker = 'marker1';
        reg.formats.add(docxItem);

        JA_ArtifactRegistration.FormatItem pdfItem = new JA_ArtifactRegistration.FormatItem();
        pdfItem.format = 'pdf';
        pdfItem.artifactId = 'art-pdf-1';
        pdfItem.artifactVersion = 1;
        pdfItem.contentHash = 'sha256:hash2';
        pdfItem.sizeBytes = 2000;
        pdfItem.contentDocumentId = '069000000000002AAA';
        pdfItem.contentVersionId = '068000000000002AAA';
        pdfItem.reconciliationMarker = 'marker2';
        reg.formats.add(pdfItem);

        JA_ArtifactRegistration.registerDelivery(reg);

        // Manually approve docx record
        JA_Artifact_Review__c docxRev = [SELECT Id, Approval_Status__c FROM JA_Artifact_Review__c WHERE Generation_Request__c = :req.Id AND Format__c = 'docx' LIMIT 1];
        docxRev.Approval_Status__c = 'approved';
        docxRev.Approved_By__c = UserInfo.getUserId();
        docxRev.Approved_At__c = Datetime.now();
        update docxRev;

        // Replay same delivery registration
        Test.startTest();
        JA_ArtifactRegistration.RegistrationResult replayRes = JA_ArtifactRegistration.registerDelivery(reg);
        Test.stopTest();

        System.assertEquals(true, replayRes.isSuccess);
        System.assertEquals('replayed', replayRes.outcome);

        // Verify status remains approved (not reset to draft!)
        JA_Artifact_Review__c checkRev = [SELECT Id, Approval_Status__c FROM JA_Artifact_Review__c WHERE Id = :docxRev.Id];
        System.assertEquals('approved', checkRev.Approval_Status__c, 'Worker replay must NEVER reset human approval status');
    }
}

