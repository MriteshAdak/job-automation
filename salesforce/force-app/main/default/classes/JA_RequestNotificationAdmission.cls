/**
 * @description Invocable admission service evaluating request readiness and failure eligibility
 *              for durable notification dispatch (SF-08).
 */
public with sharing class JA_RequestNotificationAdmission {

    public class AdmissionInput {
        @InvocableVariable(label='Generation Request ID' required=true)
        public Id requestId;

        @InvocableVariable(label='Trigger Status' required=false)
        public String triggerStatus;

        @InvocableVariable(label='Failure Episode ID' required=false)
        public String failureEpisodeId;

        @InvocableVariable(label='Action Code' required=false)
        public String actionCode;
    }

    public class AdmissionOutput {
        @InvocableVariable(label='Admission Outcome')
        public String outcome;

        @InvocableVariable(label='Alert Key')
        public String alertKey;

        @InvocableVariable(label='Notification Record ID')
        public Id notificationId;

        @InvocableVariable(label='Reason Code')
        public String reasonCode;

        @InvocableVariable(label='Message')
        public String message;
    }

    @InvocableMethod(label='Admit Request Notification' description='Evaluates transition eligibility and writes durable ledger record')
    public static List<AdmissionOutput> admitNotifications(List<AdmissionInput> inputs) {
        List<AdmissionOutput> outputs = new List<AdmissionOutput>();
        if (inputs == null || inputs.isEmpty()) {
            return outputs;
        }

        // 1. Load org-level singleton configuration
        JA_Notification_Config__c config = null;
        List<JA_Notification_Config__c> configs = [
            SELECT Id, Is_Enabled__c, Candidate_User__c, Preferred_Language__c,
                   Enable_Mobile__c, Max_Retry_Attempts__c, Initial_Retry_Delay_Minutes__c,
                   Activation_Watermark__c
            FROM JA_Notification_Config__c
            WHERE Org_Key__c = 'default'
            LIMIT 1
        ];
        if (!configs.isEmpty()) {
            config = configs[0];
        }

        Id currentOrgId = UserInfo.getOrganizationId();

        for (AdmissionInput inp : inputs) {
            AdmissionOutput out = new AdmissionOutput();
            if (inp.requestId == null) {
                out.outcome = 'not_eligible';
                out.reasonCode = 'NULL_REQUEST_ID';
                out.message = 'Request ID is null.';
                outputs.add(out);
                continue;
            }

            // 2. Query target request
            List<Generation_Request__c> reqs = [
                SELECT Id, Name, Status__c, Error_Category__c, Error_Reason__c,
                       Completed_At__c, CreatedDate
                FROM Generation_Request__c
                WHERE Id = :inp.requestId
                LIMIT 1
                FOR UPDATE
            ];
            if (reqs.isEmpty()) {
                out.outcome = 'not_eligible';
                out.reasonCode = 'REQUEST_NOT_FOUND';
                out.message = 'Generation request not found.';
                outputs.add(out);
                continue;
            }

            Generation_Request__c req = reqs[0];
            String status = req.Status__c;

            // Invariant: Pending / Running -> zero alert
            if (status == 'Pending' || status == 'Running') {
                out.outcome = 'not_eligible';
                out.reasonCode = 'INTERMEDIATE_PROCESSING_STATE';
                out.message = 'Request in progress; not eligible.';
                outputs.add(out);
                continue;
            }

            // Invariant: Upload_Pending without explicit intervention -> zero alert
            Boolean isIntervention = (status == 'Upload_Pending' && (
                req.Error_Category__c == 'CAPACITY' ||
                req.Error_Category__c == 'PERMISSION' ||
                req.Error_Category__c == 'RATE_LIMIT' ||
                inp.actionCode == 'upload_intervention_required'
            ));
            if (status == 'Upload_Pending' && !isIntervention) {
                out.outcome = 'not_eligible';
                out.reasonCode = 'UPLOAD_PENDING_NORMAL';
                out.message = 'Upload pending without intervention required.';
                outputs.add(out);
                continue;
            }

            // Check config
            if (config == null || !config.Is_Enabled__c || config.Candidate_User__c == null) {
                out.outcome = 'blocked';
                out.reasonCode = (config != null && config.Candidate_User__c == null) ?
                    'RECIPIENT_NOT_CONFIGURED' : 'CONFIG_DISABLED';
                out.message = 'Notification config is missing, disabled, or recipient is not configured.';
                outputs.add(out);
                continue;
            }

            Id candidateUserId = config.Candidate_User__c;
            String lang = (config.Preferred_Language__c == 'de') ? 'de' : 'en';

            String eventKind;
            String sourceEventKey;
            String payloadFingerprint;
            String title;
            String body;
            String actionCodeVal = null;
            String artifactSetId = null;
            Decimal artifactSetVersion = null;
            String failureEpisodeId = null;

            if (status == 'Ready_for_Review') {
                eventKind = 'ready';

                // Check complete formats: docx and pdf
                List<JA_Artifact_Review__c> reviews = [
                    SELECT Id, Format__c, Artifact_Set_Id__c, Artifact_Id__c, Artifact_Version__c,
                           Content_Hash__c, Content_Document_Id__c, Content_Version_Id__c
                    FROM JA_Artifact_Review__c
                    WHERE Generation_Request__c = :req.Id
                ];

                JA_Artifact_Review__c docxRev = null;
                JA_Artifact_Review__c pdfRev = null;
                for (JA_Artifact_Review__c rev : reviews) {
                    if (rev.Format__c == 'docx') docxRev = rev;
                    if (rev.Format__c == 'pdf') pdfRev = rev;
                }

                if (docxRev == null || pdfRev == null) {
                    out.outcome = 'blocked';
                    out.reasonCode = 'INCOMPLETE_FORMATS';
                    out.message = 'Both DOCX and PDF must be delivered before readiness alert.';
                    outputs.add(out);
                    continue;
                }

                // Check candidate file accessibility
                Set<Id> docIds = new Set<Id>{ docxRev.Content_Document_Id__c, pdfRev.Content_Document_Id__c };
                List<ContentDocumentLink> links = [
                    SELECT ContentDocumentId, LinkedEntityId, ShareType, Visibility
                    FROM ContentDocumentLink
                    WHERE ContentDocumentId IN :docIds
                ];

                Boolean docxAccessible = false;
                Boolean pdfAccessible = false;
                for (ContentDocumentLink cdl : links) {
                    Boolean isCandidateAccess = (cdl.LinkedEntityId == candidateUserId ||
                        cdl.LinkedEntityId == req.Id ||
                        cdl.Visibility == 'AllUsers');
                    if (isCandidateAccess && (cdl.ShareType == 'V' || cdl.ShareType == 'C' || cdl.ShareType == 'I')) {
                        if (cdl.ContentDocumentId == docxRev.Content_Document_Id__c) docxAccessible = true;
                        if (cdl.ContentDocumentId == pdfRev.Content_Document_Id__c) pdfAccessible = true;
                    }
                }

                if (!docxAccessible || !pdfAccessible) {
                    out.outcome = 'blocked';
                    out.reasonCode = 'RECIPIENT_ACCESS_DENIED';
                    out.message = 'Candidate recipient does not have verified access to delivered files.';
                    outputs.add(out);
                    continue;
                }

                artifactSetId = docxRev.Artifact_Set_Id__c;
                artifactSetVersion = docxRev.Artifact_Version__c;
                String bindingSummary = docxRev.Content_Hash__c + ':' + docxRev.Content_Version_Id__c + '|' +
                                        pdfRev.Content_Hash__c + ':' + pdfRev.Content_Version_Id__c;
                String setHash = EncodingUtil.convertToHex(
                    Crypto.generateDigest('SHA-256', Blob.valueOf(bindingSummary))
                ).substring(0, 16);

                sourceEventKey = 'ready:' + currentOrgId + ':' + req.Id + ':' + artifactSetId + ':' + artifactSetVersion + ':' + setHash;
                payloadFingerprint = EncodingUtil.convertToHex(
                    Crypto.generateDigest('SHA-256', Blob.valueOf('ready|' + sourceEventKey))
                );

                if (lang == 'de') {
                    title = 'Entwurf bereit zur Prüfung';
                    body = 'Anfrage ' + req.Name + ': DOCX- und PDF-Entwürfe stehen zur Verfügung. Öffnen Sie die Anfrage zur Prüfung.';
                } else {
                    title = 'Draft ready for review';
                    body = 'Request ' + req.Name + ': DOCX and PDF drafts are available. Open the request to review them.';
                }

            } else {
                // Action required (Terminal Failed or Upload Intervention)
                eventKind = 'action_required';
                failureEpisodeId = (inp.failureEpisodeId != null) ? inp.failureEpisodeId :
                    EncodingUtil.convertToHex(Crypto.generateDigest('MD5', Blob.valueOf(String.valueOf(req.Id) + ':' + req.Error_Category__c)));
                actionCodeVal = isIntervention ? 'upload_intervention_required' : 'terminal_failure';

                sourceEventKey = 'failure:' + currentOrgId + ':' + req.Id + ':' + failureEpisodeId;
                payloadFingerprint = EncodingUtil.convertToHex(
                    Crypto.generateDigest('SHA-256', Blob.valueOf('action_required|' + sourceEventKey + '|' + actionCodeVal))
                );

                if (isIntervention) {
                    if (lang == 'de') {
                        title = 'Entwurfslieferung erfordert Aufmerksamkeit';
                        body = 'Anfrage ' + req.Name + ': Dateiauslieferung ist blockiert. Öffnen Sie die Anfrage für den nächsten Schritt.';
                    } else {
                        title = 'Draft delivery needs attention';
                        body = 'Request ' + req.Name + ': file delivery is blocked. Open the request for the next step.';
                    }
                } else {
                    if (lang == 'de') {
                        title = 'Entwurfsanfrage erfordert Aufmerksamkeit';
                        body = 'Anfrage ' + req.Name + ': konnte nicht abgeschlossen werden. Öffnen Sie die Anfrage für den nächsten Schritt.';
                    } else {
                        title = 'Draft request needs attention';
                        body = 'Request ' + req.Name + ' could not complete. Open the request for the next step.';
                    }
                }
            }

            // Deterministic AlertKey
            String rawAlertTuple = sourceEventKey + ':' + candidateUserId + ':salesforce_custom_notification';
            String alertKey = EncodingUtil.convertToHex(
                Crypto.generateDigest('SHA-256', Blob.valueOf(rawAlertTuple))
            );

            // Deduplication & Conflict check
            List<JA_Request_Notification__c> existing = [
                SELECT Id, Status__c, Payload_Fingerprint__c, Attempts__c
                FROM JA_Request_Notification__c
                WHERE Alert_Key__c = :alertKey
                LIMIT 1
                FOR UPDATE
            ];

            if (!existing.isEmpty()) {
                JA_Request_Notification__c exist = existing[0];
                if (exist.Payload_Fingerprint__c != payloadFingerprint) {
                    out.outcome = 'conflict';
                    out.alertKey = alertKey;
                    out.notificationId = exist.Id;
                    out.reasonCode = 'PAYLOAD_FINGERPRINT_CONFLICT';
                    out.message = 'Alert key collision with conflicting payload.';
                    outputs.add(out);
                    continue;
                }

                if (exist.Status__c == 'Accepted') {
                    out.outcome = 'replayed';
                    out.alertKey = alertKey;
                    out.notificationId = exist.Id;
                    out.reasonCode = 'ALREADY_ACCEPTED';
                    out.message = 'Notification was already accepted.';
                    outputs.add(out);
                    continue;
                } else if (exist.Status__c == 'Blocked') {
                    // Unblock
                    exist.Status__c = 'Pending';
                    exist.Safe_Error_Code__c = null;
                    update exist;
                    out.outcome = 'admitted';
                    out.alertKey = alertKey;
                    out.notificationId = exist.Id;
                    out.reasonCode = 'BLOCKED_RELEASED';
                    out.message = 'Previously blocked alert released to Pending.';
                    outputs.add(out);
                    continue;
                } else {
                    out.outcome = 'replayed';
                    out.alertKey = alertKey;
                    out.notificationId = exist.Id;
                    out.reasonCode = exist.Status__c;
                    out.message = 'Alert exists with status ' + exist.Status__c;
                    outputs.add(out);
                    continue;
                }
            }

            // Watermark check
            Boolean isSuppressed = false;
            String suppressionReason = null;
            if (config.Activation_Watermark__c != null) {
                DateTime reqTime = (req.Completed_At__c != null) ? req.Completed_At__c : req.CreatedDate;
                if (reqTime < config.Activation_Watermark__c) {
                    isSuppressed = true;
                    suppressionReason = 'WATERMARK_SUPPRESSED';
                }
            }

            // Insert new ledger record
            JA_Request_Notification__c notif = new JA_Request_Notification__c(
                Alert_Key__c = alertKey,
                Source_Event_Key__c = sourceEventKey,
                Event_Kind__c = eventKind,
                Generation_Request__c = req.Id,
                Recipient_User__c = candidateUserId,
                Channel__c = 'salesforce_custom_notification',
                Status__c = isSuppressed ? 'Suppressed' : 'Pending',
                Payload_Fingerprint__c = payloadFingerprint,
                Source_Revision__c = 1,
                Artifact_Set_Id__c = artifactSetId,
                Artifact_Set_Version__c = artifactSetVersion,
                Failure_Episode_Id__c = failureEpisodeId,
                Action_Code__c = actionCodeVal,
                Attempts__c = 0,
                Max_Attempts__c = (config.Max_Retry_Attempts__c != null) ? config.Max_Retry_Attempts__c : 3,
                Target_Record_Id__c = req.Id,
                Notification_Title__c = title,
                Notification_Body__c = body,
                Safe_Error_Code__c = suppressionReason
            );

            insert notif;

            out.outcome = isSuppressed ? 'suppressed' : 'admitted';
            out.alertKey = alertKey;
            out.notificationId = notif.Id;
            out.reasonCode = (suppressionReason != null) ? suppressionReason : 'SUCCESS';
            out.message = isSuppressed ? 'Suppressed by watermark.' : 'Notification admitted.';
            outputs.add(out);
        }

        return outputs;
    }
}

