/**
 * @description Operational recovery and reconciliation service for Run_Summary__c notifications (SF-09).
 */
public with sharing class JA_RunSummaryRecovery {

    /**
     * @description Safely retries a failed pre-send notification under the exact same completion key.
     */
    public static void retryFailed(Id runSummaryId) {
        List<Run_Summary__c> summaries = [
            SELECT Id, Notification_Status__c, Notification_Error_Code__c
            FROM Run_Summary__c
            WHERE Id = :runSummaryId
            FOR UPDATE
        ];
        if (summaries.isEmpty()) return;

        Run_Summary__c rec = summaries[0];
        if (rec.Notification_Status__c == 'failed') {
            rec.Notification_Status__c = 'retry_wait';
            rec.Notification_Next_Attempt_At__c = System.now();
            rec.Notification_Error_Code__c = 'OPERATOR_RETRY_SCHEDULED';
            update rec;
        }
    }

    /**
     * @description Reconciles an ambiguous unknown notification state based on operator investigation.
     */
    public static void reconcileUnknown(Id runSummaryId, Boolean wasDelivered, String receiptId) {
        List<Run_Summary__c> summaries = [
            SELECT Id, Notification_Status__c, Notification_Receipt_Id__c, Notification_Accepted_At__c
            FROM Run_Summary__c
            WHERE Id = :runSummaryId
            FOR UPDATE
        ];
        if (summaries.isEmpty()) return;

        Run_Summary__c rec = summaries[0];
        if (rec.Notification_Status__c != 'unknown') return;

        if (wasDelivered) {
            rec.Notification_Status__c = 'confirmed';
            rec.Notification_Accepted_At__c = System.now();
            rec.Notification_Receipt_Id__c = String.isNotBlank(receiptId) ? receiptId : 'MANUAL_RECONCILED';
            rec.Notification_Error_Code__c = null;
        } else {
            // Proven non-send: return to retry_wait for safe re-dispatch under same key
            rec.Notification_Status__c = 'retry_wait';
            rec.Notification_Next_Attempt_At__c = System.now();
            rec.Notification_Error_Code__c = 'RECONCILED_NON_SEND';
        }
        update rec;
    }

    /**
     * @description Marks older un-notified records prior to watermark as suppressed.
     */
    public static Integer suppressHistoricalRuns(DateTime watermark) {
        if (watermark == null) return 0;

        List<Run_Summary__c> summaries = [
            SELECT Id, Notification_Status__c, Notification_Error_Code__c
            FROM Run_Summary__c
            WHERE Completion_Recorded_At__c < :watermark
              AND Notification_Status__c IN ('none', 'pending')
            LIMIT 200
        ];

        for (Run_Summary__c rec : summaries) {
            rec.Notification_Status__c = 'suppressed';
            rec.Notification_Error_Code__c = 'HISTORICAL_PRIOR_TO_WATERMARK';
        }

        if (!summaries.isEmpty()) {
            update summaries;
        }
        return summaries.size();
    }
}

