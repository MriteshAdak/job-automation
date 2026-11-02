/**
 * @description Server-side guard and admission service for Run_Summary__c records (SF-09).
 *              Enforces monotonic revisions, payload hash verification, immutable first-completion
 *              snapshots, and single notification entitlement per logical run.
 */
public with sharing class JA_RunSummaryGuard {

    public class AdmissionException extends Exception {}

    /**
     * @description Validates and prepares Run_Summary__c records for insert or update.
     * @param summaries List of Run_Summary__c records being processed.
     * @param existingMap Map of existing records keyed by Id (null on insert).
     */
    public static void guardRunSummaries(List<Run_Summary__c> summaries, Map<Id, Run_Summary__c> existingMap) {
        if (summaries == null || summaries.isEmpty()) {
            return;
        }

        // Query singleton notification configuration
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

        String orgId = String.valueOf(UserInfo.getOrganizationId());
        String canonicalOrgId = orgId.length() >= 15 ? orgId.substring(0, 15) : orgId;

        for (Run_Summary__c rec : summaries) {
            // 1. Validate Run_Id__c presence and format
            if (String.isBlank(rec.Run_Id__c)) {
                throw new AdmissionException('Run_Id__c is required.');
            }
            rec.Run_Id__c = rec.Run_Id__c.toLowerCase().trim();

            Run_Summary__c oldRec = (existingMap != null && rec.Id != null) ? existingMap.get(rec.Id) : null;

            if (oldRec != null) {
                // Update Path: Enforce revision monotonicity and collision checks
                Decimal oldRev = oldRec.Revision__c != null ? oldRec.Revision__c : 1;
                Decimal newRev = rec.Revision__c != null ? rec.Revision__c : 1;

                if (newRev < oldRev) {
                    throw new AdmissionException('Stale revision rejected: received revision ' + newRev + ' < existing ' + oldRev);
                }

                if (newRev == oldRev) {
                    // Same revision: verify payload hash
                    if (oldRec.Payload_Hash__c != null && rec.Payload_Hash__c != null && oldRec.Payload_Hash__c != rec.Payload_Hash__c) {
                        throw new AdmissionException('Revision conflict: identical revision ' + newRev + ' with differing payload hash.');
                    }
                    // Replay of identical revision: preserve server-managed markers and do not rearm
                    rec.Completion_Recorded_At__c = oldRec.Completion_Recorded_At__c;
                    rec.First_Completed_At__c = oldRec.First_Completed_At__c;
                    rec.First_Status__c = oldRec.First_Status__c;
                    rec.First_Headline__c = oldRec.First_Headline__c;
                    rec.First_Summary_Text__c = oldRec.First_Summary_Text__c;
                    rec.First_Payload_Hash__c = oldRec.First_Payload_Hash__c;
                    rec.First_Completion_Key__c = oldRec.First_Completion_Key__c;
                    rec.Notification_Status__c = oldRec.Notification_Status__c;
                    rec.Notification_Recipient__c = oldRec.Notification_Recipient__c;
                    rec.Notification_Receipt_Id__c = oldRec.Notification_Receipt_Id__c;
                    rec.Notification_Accepted_At__c = oldRec.Notification_Accepted_At__c;
                    rec.Notification_Claim_Id__c = oldRec.Notification_Claim_Id__c;
                    rec.Notification_Attempt_Count__c = oldRec.Notification_Attempt_Count__c;
                    rec.Notification_Error_Code__c = oldRec.Notification_Error_Code__c;
                    continue;
                }

                // Higher revision (resumed run):
                // Latest result fields update, but FIRST-completion snapshot and markers remain FROZEN.
                rec.Completion_Recorded_At__c = oldRec.Completion_Recorded_At__c;
                rec.First_Completed_At__c = oldRec.First_Completed_At__c;
                rec.First_Status__c = oldRec.First_Status__c;
                rec.First_Headline__c = oldRec.First_Headline__c;
                rec.First_Summary_Text__c = oldRec.First_Summary_Text__c;
                rec.First_Payload_Hash__c = oldRec.First_Payload_Hash__c;
                rec.First_Completion_Key__c = oldRec.First_Completion_Key__c;

                // Invariant: Higher revision never resets an already confirmed, dispatching, or completed notification
                rec.Notification_Status__c = oldRec.Notification_Status__c;
                rec.Notification_Recipient__c = oldRec.Notification_Recipient__c;
                rec.Notification_Receipt_Id__c = oldRec.Notification_Receipt_Id__c;
                rec.Notification_Accepted_At__c = oldRec.Notification_Accepted_At__c;
                rec.Notification_Claim_Id__c = oldRec.Notification_Claim_Id__c;
                rec.Notification_Attempt_Count__c = oldRec.Notification_Attempt_Count__c;
                rec.Notification_Error_Code__c = oldRec.Notification_Error_Code__c;
            } else {
                // Insert Path: Evaluate first completion admission
                Boolean isTerminal = (rec.Pipeline_Status__c == 'success' ||
                                      rec.Pipeline_Status__c == 'partial' ||
                                      rec.Pipeline_Status__c == 'failed');

                String expectedKey = canonicalOrgId + ':' + rec.Run_Id__c;
                rec.First_Completion_Key__c = expectedKey;

                if (isTerminal) {
                    rec.Completion_Recorded_At__c = System.now();
                    rec.First_Completed_At__c = (rec.End_Time__c != null) ? rec.End_Time__c : System.now();
                    rec.First_Status__c = rec.Pipeline_Status__c;
                    rec.First_Headline__c = rec.Headline__c;
                    rec.First_Summary_Text__c = rec.Summary_Text__c;
                    rec.First_Payload_Hash__c = rec.Payload_Hash__c;

                    // Resolve notification entitlement from config
                    if (config != null && config.Is_Enabled__c == true && config.Candidate_User__c != null) {
                        // Check historical watermark
                        if (config.Activation_Watermark__c != null && rec.First_Completed_At__c < config.Activation_Watermark__c) {
                            rec.Notification_Status__c = 'suppressed';
                            rec.Notification_Error_Code__c = 'HISTORICAL_PRIOR_TO_WATERMARK';
                            rec.Notification_Recipient__c = config.Candidate_User__c;
                        } else {
                            rec.Notification_Status__c = 'pending';
                            rec.Notification_Recipient__c = config.Candidate_User__c;
                            rec.Notification_Attempt_Count__c = 0;
                        }
                    } else {
                        rec.Notification_Status__c = 'none';
                    }
                } else {
                    rec.Notification_Status__c = 'none';
                }
            }
        }
    }
}

