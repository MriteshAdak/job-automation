/**
 * @description Delivery registration service binding GEN-06 delivered artifact sets
 *              to immutable JA_Artifact_Review__c records in Salesforce (SF-07).
 */
public with sharing class JA_ArtifactRegistration {

    public class FormatItem {
        public String format; // 'docx' or 'pdf'
        public String artifactId;
        public Integer artifactVersion;
        public String contentHash;
        public Long sizeBytes;
        public String contentDocumentId;
        public String contentVersionId;
        public String reconciliationMarker;
        public Datetime deliveredAt;
    }

    public class RegistrationRequest {
        public Id generationRequestId;
        public String orgId;
        public String artifactSetId;
        public String deliveryReceiptRef;
        public String safeWarnings;
        public List<FormatItem> formats;
    }

    public class RegistrationResult {
        public Boolean isSuccess;
        public String outcome; // 'registered', 'replayed', 'conflict', 'rejected'
        public String message;
        public List<JA_Artifact_Review__c> reviews;
    }

    public static RegistrationResult registerDelivery(RegistrationRequest req) {
        RegistrationResult res = new RegistrationResult();
        res.isSuccess = false;
        res.reviews = new List<JA_Artifact_Review__c>();

        if (req == null || req.generationRequestId == null) {
            res.outcome = 'rejected';
            res.message = 'Generation Request ID is required.';
            return res;
        }

        if (req.formats == null || req.formats.isEmpty()) {
            res.outcome = 'rejected';
            res.message = 'Delivery formats are required.';
            return res;
        }

        // Validate complete set of required formats (must include both docx and pdf)
        Set<String> declaredFormats = new Set<String>();
        for (FormatItem item : req.formats) {
            if (item != null && String.isNotBlank(item.format)) {
                declaredFormats.add(item.format.trim().toLowerCase());
            }
        }

        if (!declaredFormats.contains('docx') || !declaredFormats.contains('pdf')) {
            res.outcome = 'rejected';
            res.message = 'Incomplete delivery set: both DOCX and PDF formats are strictly required.';
            return res;
        }

        String orgId = String.isNotBlank(req.orgId) ? req.orgId : UserInfo.getOrganizationId();
        Set<String> bindingKeys = new Set<String>();
        Map<String, FormatItem> itemByKey = new Map<String, FormatItem>();

        for (FormatItem item : req.formats) {
            String fmt = item.format.trim().toLowerCase();
            String bKey = orgId + ':' + String.valueOf(req.generationRequestId) + ':' + item.artifactId + ':' + String.valueOf(item.artifactVersion) + ':' + fmt;
            bindingKeys.add(bKey);
            itemByKey.put(bKey, item);
        }

        // Query existing review records by binding keys
        Map<String, JA_Artifact_Review__c> existingByKey = new Map<String, JA_Artifact_Review__c>();
        for (JA_Artifact_Review__c rev : [
            SELECT Id, Name, Binding_Key__c, Approval_Status__c, Content_Hash__c,
                   Content_Version_Id__c, Content_Document_Id__c, Format__c,
                   Review_Revision__c, Approved_By__c, Approved_At__c,
                   Superseded_By__c, Superseded_At__c, Generation_Request__c
            FROM JA_Artifact_Review__c
            WHERE Binding_Key__c IN :bindingKeys
        ]) {
            existingByKey.put(rev.Binding_Key__c, rev);
        }

        List<JA_Artifact_Review__c> toInsert = new List<JA_Artifact_Review__c>();
        Boolean allReplayed = true;

        for (String bKey : bindingKeys) {
            FormatItem item = itemByKey.get(bKey);
            if (existingByKey.containsKey(bKey)) {
                JA_Artifact_Review__c existing = existingByKey.get(bKey);
                // Verify byte and remote ID immutability
                if (existing.Content_Hash__c != item.contentHash ||
                    existing.Content_Version_Id__c != item.contentVersionId ||
                    existing.Content_Document_Id__c != item.contentDocumentId) {
                    res.outcome = 'conflict';
                    res.message = 'Delivery conflict: existing binding ' + bKey + ' has different content hash or remote version IDs.';
                    return res;
                }
                res.reviews.add(existing);
            } else {
                allReplayed = false;
                JA_Artifact_Review__c newRev = new JA_Artifact_Review__c();
                newRev.Binding_Key__c = bKey;
                newRev.Generation_Request__c = req.generationRequestId;
                newRev.Org_Id__c = orgId;
                newRev.Artifact_Set_Id__c = req.artifactSetId;
                newRev.Artifact_Id__c = item.artifactId;
                newRev.Artifact_Version__c = item.artifactVersion;
                newRev.Format__c = item.format.trim().toLowerCase();
                newRev.Content_Hash__c = item.contentHash;
                newRev.Size_Bytes__c = item.sizeBytes != null ? item.sizeBytes : 0;
                newRev.Content_Document_Id__c = item.contentDocumentId;
                newRev.Content_Version_Id__c = item.contentVersionId;
                newRev.Reconciliation_Marker__c = item.reconciliationMarker;
                newRev.Delivery_Receipt_Ref__c = req.deliveryReceiptRef;
                newRev.Delivered_At__c = item.deliveredAt != null ? item.deliveredAt : Datetime.now();
                newRev.Safe_Warnings__c = req.safeWarnings;
                newRev.Approval_Status__c = 'draft';
                newRev.Review_Revision__c = 1;
                newRev.Contract_Schema_Version__c = '1.0';
                toInsert.add(newRev);
            }
        }

        if (!toInsert.isEmpty()) {
            insert toInsert;
            res.reviews.addAll(toInsert);
            res.outcome = 'registered';
            res.isSuccess = true;
            res.message = 'Delivery set registered successfully.';
        } else if (allReplayed) {
            res.outcome = 'replayed';
            res.isSuccess = true;
            res.message = 'Delivery set replayed idempotently; existing human approval state preserved.';
        }

        return res;
    }
}

