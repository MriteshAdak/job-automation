/**
 * @description Guarded dispatcher service executing pre-send fence checks, serialized attempt claims,
 *              platform custom notification delivery, and durable post-send acknowledgment (SF-09).
 */
public with sharing class JA_RunSummaryDispatcher {

    @InvocableMethod(label='Dispatch Run Summary Notification' description='Dispatches run summary completion notifications with serialized locking and pre-send fence')
    public static void dispatchRunSummaries(List<Id> runSummaryIds) {
        if (runSummaryIds == null || runSummaryIds.isEmpty()) {
            return;
        }

        List<Run_Summary__c> summaries = [
            SELECT Id, Name, Run_Id__c, Pipeline_Status__c, Coverage_Status__c,
                   Headline__c, Summary_Text__c, Error_Summary__c, Pending_Work_Summary__c,
                   Source_Postings_Count__c, Canonical_Jobs_New__c, Canonical_Jobs_Updated__c,
                   Canonical_Jobs_Duplicate__c, Eligible_Count__c, Review_Count__c, Rejected_Count__c,
                   First_Status__c, First_Headline__c, First_Summary_Text__c, First_Completed_At__c,
                   First_Completion_Key__c, Notification_Recipient__c, Notification_Status__c,
                   Notification_Claim_Id__c, Notification_Attempt_Count__c, Notification_Next_Attempt_At__c
            FROM Run_Summary__c
            WHERE Id IN :runSummaryIds
            FOR UPDATE
        ];

        // Query notification config
        JA_Notification_Config__c config = null;
        List<JA_Notification_Config__c> configs = [
            SELECT Id, Is_Enabled__c, Candidate_User__c, Preferred_Language__c,
                   Enable_Mobile__c, Max_Retry_Attempts__c, Initial_Retry_Delay_Minutes__c
            FROM JA_Notification_Config__c
            WHERE Org_Key__c = 'default'
            LIMIT 1
        ];
        if (!configs.isEmpty()) {
            config = configs[0];
        }

        // Cache custom notification type ID
        Id notifTypeId = null;
        for (CustomNotificationType cnt : [
            SELECT Id, DeveloperName
            FROM CustomNotificationType
            WHERE DeveloperName = 'JA_Run_Completed'
            LIMIT 1
        ]) {
            notifTypeId = cnt.Id;
        }

        List<Run_Summary__c> toUpdate = new List<Run_Summary__c>();

        for (Run_Summary__c rec : summaries) {
            // Check eligibility: only pending or retry_wait (after retry delay)
            if (rec.Notification_Status__c != 'pending' && rec.Notification_Status__c != 'retry_wait') {
                continue;
            }
            if (rec.Notification_Status__c == 'retry_wait' && rec.Notification_Next_Attempt_At__c != null && rec.Notification_Next_Attempt_At__c > System.now()) {
                continue;
            }

            // Check recipient
            if (rec.Notification_Recipient__c == null) {
                rec.Notification_Status__c = 'failed';
                rec.Notification_Error_Code__c = 'MISSING_RECIPIENT';
                toUpdate.add(rec);
                continue;
            }

            // Verify config is enabled
            if (config == null || config.Is_Enabled__c != true) {
                rec.Notification_Status__c = 'suppressed';
                rec.Notification_Error_Code__c = 'CONFIG_DISABLED';
                toUpdate.add(rec);
                continue;
            }

            // Pre-send fence: Acquire unique attempt claim
            String claimId = EncodingUtil.convertToHex(Crypto.generateDigest('SHA-256', Blob.valueOf(String.valueOf(Math.random()) + String.valueOf(System.now()) + rec.Id)));
            rec.Notification_Claim_Id__c = claimId;
            rec.Notification_Status__c = 'dispatching';
            rec.Notification_Attempt_Count__c = (rec.Notification_Attempt_Count__c != null ? rec.Notification_Attempt_Count__c : 0) + 1;
            rec.Notification_Last_Attempt_At__c = System.now();

            String lang = (config.Preferred_Language__c != null) ? config.Preferred_Language__c : 'en';
            String title;
            String body;

            String status = rec.First_Status__c != null ? rec.First_Status__c : rec.Pipeline_Status__c;
            Decimal obs = rec.Source_Postings_Count__c != null ? rec.Source_Postings_Count__c : 0;
            Decimal newJobs = rec.Canonical_Jobs_New__c != null ? rec.Canonical_Jobs_New__c : 0;
            Decimal updatedJobs = rec.Canonical_Jobs_Updated__c != null ? rec.Canonical_Jobs_Updated__c : 0;
            Decimal dupJobs = rec.Canonical_Jobs_Duplicate__c != null ? rec.Canonical_Jobs_Duplicate__c : 0;
            String headline = rec.First_Headline__c != null ? rec.First_Headline__c : rec.Headline__c;
            String errorSummary = rec.Error_Summary__c != null ? rec.Error_Summary__c : 'None';

            if (lang == 'de') {
                if (status == 'success') {
                    if (obs == 0 && rec.Coverage_Status__c == 'complete') {
                        title = 'Suchlauf abgeschlossen: Keine Ausschreibungen';
                        body = 'Lauf ' + rec.Run_Id__c + ': Keine Ausschreibungen in konfigurierten Quellen gefunden.';
                    } else {
                        title = 'Suchlauf abgeschlossen: Erfolgreich';
                        body = 'Lauf ' + rec.Run_Id__c + ': ' + headline + '\nGefunden: ' + obs + ' | Stellen: +' + newJobs + ' neu, ' + updatedJobs + ' aktualisiert, ' + dupJobs + ' Duplikate.';
                    }
                } else if (status == 'partial') {
                    title = 'Suchlauf unvollständig: Teilweise';
                    body = 'Lauf ' + rec.Run_Id__c + ': Teilweise abgeschlossen. Fehler: ' + errorSummary;
                } else {
                    title = 'Suchlauf fehlgeschlagen: Fehler';
                    body = 'Lauf ' + rec.Run_Id__c + ': Fehlgeschlagen vor Abschluss. Fehler: ' + errorSummary;
                }
            } else {
                if (status == 'success') {
                    if (obs == 0 && rec.Coverage_Status__c == 'complete') {
                        title = 'Run Completed: No postings found';
                        body = 'Run ' + rec.Run_Id__c + ': No postings found across configured sources.';
                    } else {
                        title = 'Run Completed: Success';
                        body = 'Run ' + rec.Run_Id__c + ': ' + headline + '\nObserved: ' + obs + ' postings | Jobs: +' + newJobs + ' new, ' + updatedJobs + ' updated, ' + dupJobs + ' duplicate.';
                    }
                } else if (status == 'partial') {
                    title = 'Run Completed: Partial';
                    body = 'Run ' + rec.Run_Id__c + ': Search partial. Safe error digest: ' + errorSummary;
                } else {
                    title = 'Run Completed: Failed';
                    body = 'Run ' + rec.Run_Id__c + ': Search failed before completion. Safe error digest: ' + errorSummary;
                }
            }

            try {
                if (notifTypeId != null) {
                    Messaging.CustomNotification customNotif = new Messaging.CustomNotification();
                    customNotif.setTitle(title.length() > 250 ? title.substring(0, 250) : title);
                    customNotif.setBody(body.length() > 750 ? body.substring(0, 750) : body);
                    customNotif.setNotificationTypeId(notifTypeId);
                    customNotif.setTargetId(rec.Id);
                    customNotif.send(new Set<String>{ String.valueOf(rec.Notification_Recipient__c) });
                }

                // Successful delivery acceptance
                rec.Notification_Status__c = 'confirmed';
                rec.Notification_Accepted_At__c = System.now();
                rec.Notification_Receipt_Id__c = claimId;
                rec.Notification_Error_Code__c = null;
            } catch (Exception ex) {
                String exMsg = ex.getMessage();
                if (exMsg != null && (exMsg.contains('timeout') || exMsg.contains('unconfirmed') || exMsg.contains('IO'))) {
                    // Fence into ambiguous unknown state
                    rec.Notification_Status__c = 'unknown';
                    rec.Notification_Error_Code__c = 'AMBIGUOUS_SEND';
                } else {
                    Integer maxAtt = config.Max_Retry_Attempts__c != null ? Integer.valueOf(config.Max_Retry_Attempts__c) : 3;
                    if (rec.Notification_Attempt_Count__c < maxAtt) {
                        rec.Notification_Status__c = 'retry_wait';
                        Integer initialDelay = config.Initial_Retry_Delay_Minutes__c != null ? Integer.valueOf(config.Initial_Retry_Delay_Minutes__c) : 1;
                        Integer delayMins = initialDelay * (Integer)Math.pow(2, (Double)(rec.Notification_Attempt_Count__c - 1));
                        rec.Notification_Next_Attempt_At__c = System.now().addMinutes(delayMins);
                        rec.Notification_Error_Code__c = 'PRE_SEND_FAILURE';
                    } else {
                        rec.Notification_Status__c = 'failed';
                        rec.Notification_Error_Code__c = 'MAX_RETRIES_EXCEEDED';
                    }
                }
            }

            toUpdate.add(rec);
        }

        if (!toUpdate.isEmpty()) {
            update toUpdate;
        }
    }
}

