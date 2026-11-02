/**
 * @description Guarded dispatcher service executing pre-send fence checks, serialized attempt claims,
 *              platform custom notification delivery, and durable post-send acknowledgment (SF-08).
 */
public with sharing class JA_RequestNotificationDispatcher {

    @InvocableMethod(label='Dispatch Request Notification' description='Dispatches admitted notifications with serialized locking and platform acknowledgment')
    public static void dispatchNotifications(List<Id> notificationIds) {
        if (notificationIds == null || notificationIds.isEmpty()) {
            return;
        }

        List<JA_Request_Notification__c> notifs = [
            SELECT Id, Alert_Key__c, Event_Kind__c, Generation_Request__c, Recipient_User__c,
                   Status__c, Attempts__c, Max_Attempts__c, Next_Retry_At__c,
                   Notification_Title__c, Notification_Body__c, Target_Record_Id__c
            FROM JA_Request_Notification__c
            WHERE Id IN :notificationIds
            FOR UPDATE
        ];

        // Cache custom notification type IDs
        Map<String, Id> typeMap = new Map<String, Id>();
        for (CustomNotificationType cnt : [
            SELECT Id, DeveloperName
            FROM CustomNotificationType
            WHERE DeveloperName IN ('JA_Draft_Ready', 'JA_Request_Action_Required')
        ]) {
            typeMap.put(cnt.DeveloperName, cnt.Id);
        }

        List<JA_Request_Notification__c> toUpdate = new List<JA_Request_Notification__c>();

        for (JA_Request_Notification__c notif : notifs) {
            // Check status eligibility
            if (notif.Status__c != 'Pending' && notif.Status__c != 'Retry_Wait') {
                continue;
            }
            if (notif.Status__c == 'Retry_Wait' && notif.Next_Retry_At__c != null && notif.Next_Retry_At__c > System.now()) {
                continue;
            }

            // Verify parent request still exists
            List<Generation_Request__c> reqs = [
                SELECT Id, Status__c FROM Generation_Request__c WHERE Id = :notif.Generation_Request__c LIMIT 1
            ];
            if (reqs.isEmpty()) {
                notif.Status__c = 'Blocked';
                notif.Safe_Error_Code__c = 'REQUEST_DELETED';
                toUpdate.add(notif);
                continue;
            }
            Generation_Request__c req = reqs[0];

            // Pre-send fence: Ready
            if (notif.Event_Kind__c == 'ready') {
                // Verify candidate still has access to all delivered review formats
                List<JA_Artifact_Review__c> reviews = [
                    SELECT Id, Content_Document_Id__c, Format__c
                    FROM JA_Artifact_Review__c
                    WHERE Generation_Request__c = :req.Id
                ];
                Set<Id> docIds = new Set<Id>();
                for (JA_Artifact_Review__c rev : reviews) {
                    if (rev.Content_Document_Id__c != null) docIds.add(rev.Content_Document_Id__c);
                }

                List<ContentDocumentLink> links = [
                    SELECT ContentDocumentId, LinkedEntityId, ShareType, Visibility
                    FROM ContentDocumentLink
                    WHERE ContentDocumentId IN :docIds
                ];

                Set<Id> accessibleDocs = new Set<Id>();
                for (ContentDocumentLink cdl : links) {
                    Boolean isCandidateAccess = (cdl.LinkedEntityId == notif.Recipient_User__c ||
                        cdl.LinkedEntityId == req.Id ||
                        cdl.Visibility == 'AllUsers');
                    if (isCandidateAccess && (cdl.ShareType == 'V' || cdl.ShareType == 'C' || cdl.ShareType == 'I')) {
                        accessibleDocs.add(cdl.ContentDocumentId);
                    }
                }

                if (accessibleDocs.size() < 2 || !accessibleDocs.containsAll(docIds)) {
                    notif.Status__c = 'Blocked';
                    notif.Safe_Error_Code__c = 'RECIPIENT_ACCESS_REVOKED';
                    toUpdate.add(notif);
                    continue;
                }
            } else if (notif.Event_Kind__c == 'action_required') {
                // If request resolved to Ready_for_Review, suppress stale failure alert
                if (req.Status__c == 'Ready_for_Review') {
                    notif.Status__c = 'Suppressed';
                    notif.Safe_Error_Code__c = 'SUPERSEDED_BY_READY';
                    toUpdate.add(notif);
                    continue;
                }
            }

            // Serialized attempt claim
            notif.Status__c = 'Dispatching';
            notif.Attempt_Identifier__c = EncodingUtil.convertToHex(Crypto.generateDigest('MD5', Blob.valueOf(String.valueOf(Math.random()))));
            notif.Attempts__c = (notif.Attempts__c != null ? notif.Attempts__c : 0) + 1;
            notif.Dispatched_At__c = System.now();

            String typeDevName = (notif.Event_Kind__c == 'ready') ? 'JA_Draft_Ready' : 'JA_Request_Action_Required';
            Id notifTypeId = typeMap.get(typeDevName);

            try {
                if (notifTypeId != null) {
                    Messaging.CustomNotification customNotif = new Messaging.CustomNotification();
                    customNotif.setTitle(notif.Notification_Title__c);
                    customNotif.setBody(notif.Notification_Body__c);
                    customNotif.setNotificationTypeId(notifTypeId);
                    customNotif.setTargetId(notif.Target_Record_Id__c);
                    customNotif.send(new Set<String>{ String.valueOf(notif.Recipient_User__c) });
                }

                // Invariant: Acceptance does not mutate Generation_Request__c or approve document
                notif.Status__c = 'Accepted';
                notif.Accepted_At__c = System.now();
                notif.Safe_Error_Code__c = null;
                notif.Uncertainty_Reason__c = null;
            } catch (Exception ex) {
                String exMsg = ex.getMessage();
                if (exMsg != null && (exMsg.contains('timeout') || exMsg.contains('unconfirmed') || exMsg.contains('IO'))) {
                    // Fence in Uncertain
                    notif.Status__c = 'Uncertain';
                    notif.Uncertainty_Reason__c = 'Send response unconfirmed; possible network delivery';
                    notif.Safe_Error_Code__c = 'AMBIGUOUS_SEND';
                } else if (notif.Attempts__c < notif.Max_Attempts__c) {
                    notif.Status__c = 'Retry_Wait';
                    Integer delayMins = 1 * (Integer)Math.pow(2, (Double)(notif.Attempts__c - 1));
                    notif.Next_Retry_At__c = System.now().addMinutes(delayMins);
                    notif.Safe_Error_Code__c = 'SEND_FAILED';
                } else {
                    notif.Status__c = 'Dead_Letter';
                    notif.Safe_Error_Code__c = 'MAX_RETRIES_EXCEEDED';
                }
            }

            toUpdate.add(notif);
        }

        if (!toUpdate.isEmpty()) {
            update toUpdate;
        }
    }
}

