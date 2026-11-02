/**
 * @description Invocable Apex action for atomic generation request submission,
 *              active request reuse, idempotency replay, and unavailable job gating (SF-06).
 */
public with sharing class JA_GenerationSubmit {

    public class SubmitRequest {
        @InvocableVariable(required=true label='Job ID' description='Salesforce ID of the target Job__c record')
        public Id jobId;

        @InvocableVariable(required=true label='Document Type' description='cv or cover_letter')
        public String documentType;

        @InvocableVariable(label='Language' description='Target language code (de or en, default: de)')
        public String language;

        @InvocableVariable(required=true label='Template ID' description='Layout template ID, e.g. layout-cv-basic-a4')
        public String templateId;

        @InvocableVariable(label='Context Strategy' description='Context strategy: json or rag (default: json)')
        public String contextStrategy;

        @InvocableVariable(label='Allow Unavailable Job' description='Explicit consent to generate even if job is unavailable')
        public Boolean allowUnavailableJob;

        @InvocableVariable(label='Creation Mode' description='reuse_or_create or regenerate (default: reuse_or_create)')
        public String creationMode;

        @InvocableVariable(label='Predecessor Request ID' description='Optional predecessor request for deliberate regeneration')
        public Id predecessorRequestId;

        @InvocableVariable(required=true label='Submission Token' description='Unique client token for idempotent submission')
        public String submissionToken;

        @InvocableVariable(label='Catalog Version' description='Catalog version snapshot (default: 1.0.0)')
        public String catalogVersion;
    }

    public class SubmitResult {
        @InvocableVariable(label='Outcome' description='created, reused_active, replayed, confirmation_required, rejected, retryable_conflict')
        public String outcome;

        @InvocableVariable(label='Request ID' description='Salesforce ID of the Generation_Request__c record')
        public Id requestId;

        @InvocableVariable(label='Request Name' description='AutoNumber of the request, e.g. GR-000001')
        public String requestName;

        @InvocableVariable(label='Processing State' description='Pending, Running, Upload_Pending, Ready_for_Review, Failed')
        public String processingState;

        @InvocableVariable(label='Message' description='User-facing status or diagnostic message')
        public String message;

        @InvocableVariable(label='Record URL' description='Relative URL to view the Generation Request record')
        public String recordUrl;

        @InvocableVariable(label='Is Success' description='True if request was created, reused, or replayed')
        public Boolean isSuccess;
    }

    @InvocableMethod(label='Submit Generation Request' description='Atomically enqueue, reuse active, or replay generation request')
    public static List<SubmitResult> submitRequests(List<SubmitRequest> requests) {
        List<SubmitResult> results = new List<SubmitResult>();
        if (requests == null || requests.isEmpty()) {
            return results;
        }

        for (SubmitRequest req : requests) {
            results.add(processSingleRequest(req));
        }
        return results;
    }

    private static SubmitResult processSingleRequest(SubmitRequest req) {
        SubmitResult res = new SubmitResult();
        res.isSuccess = false;

        // 1. Basic Parameter Validation
        if (req == null || req.jobId == null) {
            res.outcome = 'rejected';
            res.message = 'Target Job ID is required.';
            return res;
        }

        if (String.isBlank(req.submissionToken)) {
            res.outcome = 'rejected';
            res.message = 'Submission token is required for idempotent submission.';
            return res;
        }

        String docType = String.isNotBlank(req.documentType) ? req.documentType.trim().toLowerCase() : '';
        if (docType != 'cv' && docType != 'cover_letter') {
            res.outcome = 'rejected';
            res.message = 'Invalid document type: must be cv or cover_letter.';
            return res;
        }

        String lang = String.isNotBlank(req.language) ? req.language.trim().toLowerCase() : 'de';
        if (lang != 'de' && lang != 'en') {
            res.outcome = 'rejected';
            res.message = 'Invalid language: must be de or en.';
            return res;
        }

        String strat = String.isNotBlank(req.contextStrategy) ? req.contextStrategy.trim().toLowerCase() : 'json';
        if (strat != 'json' && strat != 'rag') {
            res.outcome = 'rejected';
            res.message = 'Invalid context strategy: must be json or rag.';
            return res;
        }

        String tmpl = String.isNotBlank(req.templateId) ? req.templateId.trim() : '';
        if (String.isBlank(tmpl)) {
            res.outcome = 'rejected';
            res.message = 'Template ID is required.';
            return res;
        }

        Boolean allowUnavail = (req.allowUnavailableJob == true);
        String mode = String.isNotBlank(req.creationMode) ? req.creationMode.trim().toLowerCase() : 'reuse_or_create';
        if (mode != 'reuse_or_create' && mode != 'regenerate') {
            res.outcome = 'rejected';
            res.message = 'Invalid creation mode: must be reuse_or_create or regenerate.';
            return res;
        }

        // 2. FLS & CRUD Security Checks
        if (!Schema.sObjectType.Job__c.isAccessible() ||
            !Schema.sObjectType.Generation_Request__c.isAccessible() ||
            !Schema.sObjectType.Generation_Request__c.isCreateable() ||
            !Schema.sObjectType.JA_Generation_Submission__c.isAccessible() ||
            !Schema.sObjectType.JA_Generation_Submission__c.isCreateable()) {
            res.outcome = 'rejected';
            res.message = 'Insufficient permissions to create generation requests or submission receipts.';
            return res;
        }

        // 3. Validate Template against JA_Generation_Option__mdt Catalog
        List<JA_Generation_Option__mdt> options = [
            SELECT Id, Template_Id__c, Document_Type__c, Allowed_Languages__c, Is_Enabled__c, Catalog_Version__c
            FROM JA_Generation_Option__mdt
            WHERE Template_Id__c = :tmpl
            LIMIT 1
        ];

        if (options.isEmpty()) {
            res.outcome = 'rejected';
            res.message = 'Unknown template ID: ' + tmpl + '. Please select a valid template from the catalog.';
            return res;
        }

        JA_Generation_Option__mdt opt = options[0];
        if (!opt.Is_Enabled__c) {
            res.outcome = 'rejected';
            res.message = 'Template ' + tmpl + ' is currently disabled.';
            return res;
        }

        if (opt.Document_Type__c != docType) {
            res.outcome = 'rejected';
            res.message = 'Template ' + tmpl + ' does not support document type ' + docType + '.';
            return res;
        }

        List<String> allowedLangs = opt.Allowed_Languages__c != null ? opt.Allowed_Languages__c.split(',') : new List<String>();
        Boolean langSupported = false;
        for (String al : allowedLangs) {
            if (al.trim().equalsIgnoreCase(lang)) {
                langSupported = true;
                break;
            }
        }
        if (!langSupported) {
            res.outcome = 'rejected';
            res.message = 'Template ' + tmpl + ' does not support language ' + lang + '.';
            return res;
        }

        // 4. Construct Deterministic Submission Key & Canonical Payload
        String submissionKey = UserInfo.getUserId() + ':' + req.submissionToken.trim();
        Map<String, Object> payloadMap = new Map<String, Object>{
            'jobId' => String.valueOf(req.jobId),
            'documentType' => docType,
            'language' => lang,
            'templateId' => tmpl,
            'contextStrategy' => strat,
            'allowUnavailableJob' => allowUnavail,
            'creationMode' => mode,
            'predecessorRequestId' => req.predecessorRequestId != null ? String.valueOf(req.predecessorRequestId) : null
        };
        String canonicalPayload = JSON.serialize(payloadMap);

        // 5. Replay Check via JA_Generation_Submission__c
        List<JA_Generation_Submission__c> existingReceipts = [
            SELECT Id, Submission_Key__c, Intent_Payload__c, Request__c, Outcome__c
            FROM JA_Generation_Submission__c
            WHERE Submission_Key__c = :submissionKey
            LIMIT 1
        ];

        if (!existingReceipts.isEmpty()) {
            JA_Generation_Submission__c receipt = existingReceipts[0];
            if (receipt.Intent_Payload__c == canonicalPayload) {
                // Exact replay
                List<Generation_Request__c> linkedReqs = [
                    SELECT Id, Name, Status__c
                    FROM Generation_Request__c
                    WHERE Id = :receipt.Request__c
                    LIMIT 1
                ];
                if (!linkedReqs.isEmpty()) {
                    Generation_Request__c lr = linkedReqs[0];
                    res.outcome = 'replayed';
                    res.requestId = lr.Id;
                    res.requestName = lr.Name;
                    res.processingState = lr.Status__c;
                    res.recordUrl = '/' + lr.Id;
                    res.message = 'Request ' + lr.Name + ' was previously submitted. Current state: ' + lr.Status__c + '.';
                    res.isSuccess = true;
                    return res;
                }
            } else {
                // Conflict: same token with different intent parameters
                res.outcome = 'rejected';
                res.message = 'Submission token conflict: this token was previously used with different parameters.';
                return res;
            }
        }

        // 6. Transaction & Parent Row Lock
        Savepoint sp = Database.setSavepoint();
        try {
            List<Job__c> jobs = [
                SELECT Id, Name, Job_Title__c, Availability__c, Canonical_Job_Id__c
                FROM Job__c
                WHERE Id = :req.jobId
                LIMIT 1
                FOR UPDATE
            ];

            if (jobs.isEmpty()) {
                res.outcome = 'rejected';
                res.message = 'Target Job record not found or inaccessible.';
                return res;
            }

            Job__c targetJob = jobs[0];
            if (String.isBlank(targetJob.Canonical_Job_Id__c)) {
                res.outcome = 'rejected';
                res.message = 'Target Job record lacks a valid Canonical Job ID.';
                return res;
            }

            // 7. Unavailable Job & Failure History Gating
            Boolean isJobUnavailable = 'Unavailable'.equalsIgnoreCase(targetJob.Availability__c);
            if (isJobUnavailable && !allowUnavail) {
                res.outcome = 'confirmation_required';
                res.message = 'This job is marked as Unavailable. Explicit consent is required to generate documents for unavailable jobs.';
                return res;
            }

            // Inspect failure history on this Job for job_unavailable error
            List<Generation_Request__c> unavailFailures = [
                SELECT Id, Name, Status__c, Error_Reason__c
                FROM Generation_Request__c
                WHERE Job__c = :req.jobId
                  AND Document_Type__c = :docType
                  AND Status__c = 'Failed'
                  AND Error_Reason__c = 'job_unavailable'
                  AND CreatedById = :UserInfo.getUserId()
                LIMIT 1
            ];

            if (!unavailFailures.isEmpty() && !allowUnavail) {
                res.outcome = 'confirmation_required';
                res.requestId = unavailFailures[0].Id;
                res.requestName = unavailFailures[0].Name;
                res.processingState = 'Failed';
                res.message = 'A previous request (' + unavailFailures[0].Name + ') failed because this job was unavailable. Explicit override consent is required to retry.';
                return res;
            }

            // 8. Branch: Ordinary Submission (reuse_or_create)
            if (mode == 'reuse_or_create') {
                // Check for matching active requests: Pending, Running, Upload_Pending
                List<Generation_Request__c> activeReqs = [
                    SELECT Id, Name, Status__c, Document_Type__c, Language__c, Template_Id__c,
                           Context_Strategy__c, Allow_Unavailable_Job__c, CreatedDate
                    FROM Generation_Request__c
                    WHERE Job__c = :req.jobId
                      AND Document_Type__c = :docType
                      AND Status__c IN ('Pending', 'Running', 'Upload_Pending')
                      AND CreatedById = :UserInfo.getUserId()
                    ORDER BY CreatedDate ASC, Id ASC
                ];

                Generation_Request__c matchingActive = null;
                for (Generation_Request__c ar : activeReqs) {
                    if (ar.Language__c == lang &&
                        ar.Template_Id__c == tmpl &&
                        ar.Context_Strategy__c == strat &&
                        ar.Allow_Unavailable_Job__c == allowUnavail) {
                        matchingActive = ar;
                        break;
                    }
                }

                if (matchingActive != null) {
                    // Lock matching active request
                    List<Generation_Request__c> lockedActive = [
                        SELECT Id, Name, Status__c
                        FROM Generation_Request__c
                        WHERE Id = :matchingActive.Id
                        LIMIT 1
                        FOR UPDATE
                    ];
                    Generation_Request__c currActive = lockedActive.isEmpty() ? matchingActive : lockedActive[0];

                    // Insert receipt linking this submission token to the existing active request
                    JA_Generation_Submission__c subReceipt = new JA_Generation_Submission__c(
                        Submission_Key__c = submissionKey,
                        Payload_Version__c = '1.0',
                        Intent_Payload__c = canonicalPayload,
                        Request__c = currActive.Id,
                        Outcome__c = 'reused_active'
                    );
                    insert subReceipt;

                    res.outcome = 'reused_active';
                    res.requestId = currActive.Id;
                    res.requestName = currActive.Name;
                    res.processingState = currActive.Status__c;
                    res.recordUrl = '/' + currActive.Id;
                    res.message = 'An identical active request already exists: ' + currActive.Name + ' (' + currActive.Status__c + '). No additional request was created.';
                    res.isSuccess = true;
                    return res;
                }

                // Check if matching terminal history exists
                List<Generation_Request__c> terminalReqs = [
                    SELECT Id, Name, Status__c, Completed_At__c
                    FROM Generation_Request__c
                    WHERE Job__c = :req.jobId
                      AND Document_Type__c = :docType
                      AND Status__c IN ('Ready_for_Review', 'Failed')
                      AND CreatedById = :UserInfo.getUserId()
                      AND Language__c = :lang
                      AND Template_Id__c = :tmpl
                      AND Context_Strategy__c = :strat
                    ORDER BY CreatedDate DESC
                    LIMIT 1
                ];

                if (!terminalReqs.isEmpty()) {
                    Generation_Request__c term = terminalReqs[0];
                    res.outcome = 'confirmation_required';
                    res.requestId = term.Id;
                    res.requestName = term.Name;
                    res.processingState = term.Status__c;
                    res.recordUrl = '/' + term.Id;
                    res.message = 'A previous request (' + term.Name + ' - ' + term.Status__c + ') exists with identical options. Confirm deliberate regeneration to generate another draft.';
                    return res;
                }

                // No active match and no terminal history conflict -> Create fresh Pending request
                Generation_Request__c newReq = new Generation_Request__c(
                    Job__c = req.jobId,
                    Document_Type__c = docType,
                    Language__c = lang,
                    Template_Id__c = tmpl,
                    Context_Strategy__c = strat,
                    Allow_Unavailable_Job__c = allowUnavail,
                    Status__c = 'Pending',
                    Contract_Schema_Version__c = '1.0',
                    Client_Request_Key__c = null
                );
                insert newReq;

                JA_Generation_Submission__c subReceipt = new JA_Generation_Submission__c(
                    Submission_Key__c = submissionKey,
                    Payload_Version__c = '1.0',
                    Intent_Payload__c = canonicalPayload,
                    Request__c = newReq.Id,
                    Outcome__c = 'created'
                );
                insert subReceipt;

                // Re-query AutoNumber Name
                Generation_Request__c createdReq = [SELECT Id, Name, Status__c FROM Generation_Request__c WHERE Id = :newReq.Id LIMIT 1];

                String docLabel = docType == 'cv' ? 'CV' : 'Cover letter';
                res.outcome = 'created';
                res.requestId = createdReq.Id;
                res.requestName = createdReq.Name;
                res.processingState = createdReq.Status__c;
                res.recordUrl = '/' + createdReq.Id;
                res.message = docLabel + ' request ' + createdReq.Name + ' queued. It will be processed when the local worker runs. You can close this window.';
                res.isSuccess = true;
                return res;
            }

            // 9. Branch: Deliberate Regeneration (regenerate)
            if (mode == 'regenerate') {
                if (req.predecessorRequestId == null) {
                    res.outcome = 'rejected';
                    res.message = 'Predecessor request ID is required for deliberate regeneration.';
                    return res;
                }

                List<Generation_Request__c> preds = [
                    SELECT Id, Name, Job__c, Document_Type__c, Status__c, Error_Reason__c
                    FROM Generation_Request__c
                    WHERE Id = :req.predecessorRequestId
                    LIMIT 1
                ];

                if (preds.isEmpty()) {
                    res.outcome = 'rejected';
                    res.message = 'Predecessor request not found or inaccessible.';
                    return res;
                }

                Generation_Request__c pred = preds[0];
                if (pred.Job__c != req.jobId) {
                    res.outcome = 'rejected';
                    res.message = 'Predecessor request belongs to a different Job.';
                    return res;
                }

                if (pred.Document_Type__c != docType) {
                    res.outcome = 'rejected';
                    res.message = 'Predecessor request document type does not match.';
                    return res;
                }

                if (pred.Error_Reason__c == 'job_unavailable' && !allowUnavail) {
                    res.outcome = 'confirmation_required';
                    res.requestId = pred.Id;
                    res.requestName = pred.Name;
                    res.processingState = pred.Status__c;
                    res.message = 'The predecessor request failed because this job was unavailable. Explicit override consent is required.';
                    return res;
                }

                // Insert fresh request with predecessor lineage
                Generation_Request__c newReq = new Generation_Request__c(
                    Job__c = req.jobId,
                    Predecessor_Request__c = pred.Id,
                    Document_Type__c = docType,
                    Language__c = lang,
                    Template_Id__c = tmpl,
                    Context_Strategy__c = strat,
                    Allow_Unavailable_Job__c = allowUnavail,
                    Status__c = 'Pending',
                    Contract_Schema_Version__c = '1.0',
                    Client_Request_Key__c = null
                );
                insert newReq;

                JA_Generation_Submission__c subReceipt = new JA_Generation_Submission__c(
                    Submission_Key__c = submissionKey,
                    Payload_Version__c = '1.0',
                    Intent_Payload__c = canonicalPayload,
                    Request__c = newReq.Id,
                    Outcome__c = 'created'
                );
                insert subReceipt;

                Generation_Request__c createdReq = [SELECT Id, Name, Status__c FROM Generation_Request__c WHERE Id = :newReq.Id LIMIT 1];

                String docLabel = docType == 'cv' ? 'CV' : 'Cover letter';
                res.outcome = 'created';
                res.requestId = createdReq.Id;
                res.requestName = createdReq.Name;
                res.processingState = createdReq.Status__c;
                res.recordUrl = '/' + createdReq.Id;
                res.message = docLabel + ' draft ' + createdReq.Name + ' queued as deliberate regeneration from ' + pred.Name + '. It will be processed when the local worker runs.';
                res.isSuccess = true;
                return res;
            }

        } catch (QueryException qe) {
            Database.rollback(sp);
            res.outcome = 'retryable_conflict';
            res.message = 'Concurrency contention detected while locking records. Please retry submission.';
            return res;
        } catch (DmlException de) {
            Database.rollback(sp);
            if (de.getMessage().contains('UNABLE_TO_LOCK_ROW')) {
                res.outcome = 'retryable_conflict';
                res.message = 'Row lock contention detected. Please retry submission.';
            } else {
                res.outcome = 'rejected';
                res.message = 'Failed to submit generation request: ' + de.getDmlMessage(0);
            }
            return res;
        } catch (Exception ex) {
            Database.rollback(sp);
            res.outcome = 'rejected';
            res.message = 'Unexpected error processing submission: ' + ex.getMessage();
            return res;
        }

        res.outcome = 'rejected';
        res.message = 'Unrecognized submission state.';
        return res;
    }
}

