/**
 * @description Operational recovery service providing backlog inspection, retry processing,
 *              and operator reconciliation for ambiguous/uncertain notification outcomes (SF-08).
 */
public with sharing class JA_RequestNotificationRecovery {

    public class BacklogSummary {
        @AuraEnabled public Integer pendingCount { get; set; }
        @AuraEnabled public Integer blockedCount { get; set; }
        @AuraEnabled public Integer dispatchingCount { get; set; }
        @AuraEnabled public Integer retryWaitCount { get; set; }
        @AuraEnabled public Integer uncertainCount { get; set; }
        @AuraEnabled public Integer acceptedCount { get; set; }
        @AuraEnabled public Integer deadLetterCount { get; set; }
        @AuraEnabled public Integer suppressedCount { get; set; }
    }

    @AuraEnabled(cacheable=true)
    public static BacklogSummary getBacklogSummary() {
        BacklogSummary summary = new BacklogSummary();
        summary.pendingCount = 0;
        summary.blockedCount = 0;
        summary.dispatchingCount = 0;
        summary.retryWaitCount = 0;
        summary.uncertainCount = 0;
        summary.acceptedCount = 0;
        summary.deadLetterCount = 0;
        summary.suppressedCount = 0;

        for (AggregateResult ar : [
            SELECT Status__c, COUNT(Id) cnt
            FROM JA_Request_Notification__c
            GROUP BY Status__c
        ]) {
            String status = (String)ar.get('Status__c');
            Integer count = (Integer)ar.get('cnt');
            if (status == 'Pending') summary.pendingCount = count;
            else if (status == 'Blocked') summary.blockedCount = count;
            else if (status == 'Dispatching') summary.dispatchingCount = count;
            else if (status == 'Retry_Wait') summary.retryWaitCount = count;
            else if (status == 'Uncertain') summary.uncertainCount = count;
            else if (status == 'Accepted') summary.acceptedCount = count;
            else if (status == 'Dead_Letter') summary.deadLetterCount = count;
            else if (status == 'Suppressed') summary.suppressedCount = count;
        }

        return summary;
    }

    @AuraEnabled
    public static Integer retryDueNotifications() {
        List<JA_Request_Notification__c> due = [
            SELECT Id
            FROM JA_Request_Notification__c
            WHERE Status__c = 'Retry_Wait'
              AND (Next_Retry_At__c = null OR Next_Retry_At__c <= :System.now())
            LIMIT 50
        ];

        if (due.isEmpty()) {
            return 0;
        }

        List<Id> ids = new List<Id>();
        for (JA_Request_Notification__c n : due) {
            ids.add(n.Id);
        }

        JA_RequestNotificationDispatcher.dispatchNotifications(ids);
        return ids.size();
    }

    @AuraEnabled
    public static void reconcileUncertainNotification(Id notificationId, String resolution) {
        if (notificationId == null || String.isBlank(resolution)) {
            throw new AuraHandledException('Notification ID and resolution are required.');
        }

        List<JA_Request_Notification__c> notifs = [
            SELECT Id, Status__c, Uncertainty_Reason__c, Accepted_At__c
            FROM JA_Request_Notification__c
            WHERE Id = :notificationId
            LIMIT 1
            FOR UPDATE
        ];

        if (notifs.isEmpty()) {
            throw new AuraHandledException('Notification record not found.');
        }

        JA_Request_Notification__c n = notifs[0];
        if (n.Status__c != 'Uncertain') {
            throw new AuraHandledException('Notification is not in Uncertain status.');
        }

        if (resolution == 'confirm_accepted') {
            n.Status__c = 'Accepted';
            n.Accepted_At__c = System.now();
            n.Uncertainty_Reason__c = 'Manually confirmed accepted by operator';
        } else if (resolution == 'suppress') {
            n.Status__c = 'Suppressed';
            n.Uncertainty_Reason__c = 'Manually suppressed by operator';
        } else if (resolution == 'force_retry') {
            n.Status__c = 'Pending';
            n.Uncertainty_Reason__c = 'Operator authorized retry after verified non-delivery';
        } else {
            throw new AuraHandledException('Invalid resolution: ' + resolution);
        }

        update n;
    }
}

