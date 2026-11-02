# SF-06 Scoped Deployment, Manifest & Recovery Plan

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../../IMPLEMENTATION_BLUEPRINT.md) §6 (SF-06), §7 (Gate G3)  
Planning Reference: [docs/stories/SF-06.md](../../stories/SF-06.md) §S06  
Scoped Manifest: [salesforce/manifest/sf06.xml](../../../salesforce/manifest/sf06.xml)

---

## 1. Deployment Inventory & Metadata Ownership

All SF-06 components reside in `salesforce/force-app/main/default/` and are registered in `salesforce/metadata-ownership.json`:

```
salesforce/force-app/main/default/
├── classes/
│   ├── JA_GenerationSubmit.cls
│   ├── JA_GenerationSubmit.cls-meta.xml
│   ├── JA_GenerationSubmitTest.cls
│   └── JA_GenerationSubmitTest.cls-meta.xml
├── customMetadata/
│   ├── JA_Generation_Option.CV_Basic_A4.md-meta.xml
│   ├── JA_Generation_Option.CV_Compact_A4.md-meta.xml
│   ├── JA_Generation_Option.Letter_Basic_A4.md-meta.xml
│   └── JA_Generation_Option.Letter_Compact_A4.md-meta.xml
├── flows/
│   ├── JA_Generate_CV.flow-meta.xml
│   └── JA_Generate_Cover_Letter.flow-meta.xml
├── layouts/
│   └── Job__c-JA Candidate Tracking.layout-meta.xml    (Added platformActionList for QuickActions)
├── objects/
│   ├── JA_Generation_Option__mdt/                     (Custom Metadata object & 6 fields)
│   └── JA_Generation_Submission__c/                   (Custom Object & 5 fields)
├── permissionsets/
│   └── Job_Generation_Actions.permissionset-meta.xml  (Candidate action, flow, and receipt permissions)
└── quickActions/
    ├── Job__c.JA_Generate_CV.quickAction-meta.xml
    └── Job__c.JA_Generate_Cover_Letter.quickAction-meta.xml
```

---

## 2. Scoped Manifest (`salesforce/manifest/sf06.xml`)

Deployments are strictly scoped using `salesforce/manifest/sf06.xml`, avoiding bulk repository pushes and preventing accidental overwrites of existing assets:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Package xmlns="http://soap.sforce.com/2006/04/metadata">
    <types>
        <members>JA_Generation_Submission__c</members>
        <members>JA_Generation_Option__mdt</members>
        <name>CustomObject</name>
    </types>
    <types>
        <members>JA_Generation_Submission__c.Submission_Key__c</members>
        <members>JA_Generation_Submission__c.Payload_Version__c</members>
        <members>JA_Generation_Submission__c.Intent_Payload__c</members>
        <members>JA_Generation_Submission__c.Request__c</members>
        <members>JA_Generation_Submission__c.Outcome__c</members>
        <members>JA_Generation_Option__mdt.Template_Id__c</members>
        <members>JA_Generation_Option__mdt.Document_Type__c</members>
        <members>JA_Generation_Option__mdt.Allowed_Languages__c</members>
        <members>JA_Generation_Option__mdt.Is_Enabled__c</members>
        <members>JA_Generation_Option__mdt.Catalog_Version__c</members>
        <members>JA_Generation_Option__mdt.Sort_Order__c</members>
        <name>CustomField</name>
    </types>
    <types>
        <members>JA_Generation_Option.CV_Basic_A4</members>
        <members>JA_Generation_Option.CV_Compact_A4</members>
        <members>JA_Generation_Option.Letter_Basic_A4</members>
        <members>JA_Generation_Option.Letter_Compact_A4</members>
        <name>CustomMetadata</name>
    </types>
    <types>
        <members>JA_GenerationSubmit</members>
        <members>JA_GenerationSubmitTest</members>
        <name>ApexClass</name>
    </types>
    <types>
        <members>JA_Generate_CV</members>
        <members>JA_Generate_Cover_Letter</members>
        <name>Flow</name>
    </types>
    <types>
        <members>Job__c.JA_Generate_CV</members>
        <members>Job__c.JA_Generate_Cover_Letter</members>
        <name>QuickAction</name>
    </types>
    <types>
        <members>Job__c-JA Candidate Tracking</members>
        <name>Layout</name>
    </types>
    <types>
        <members>Job_Generation_Actions</members>
        <name>PermissionSet</name>
    </types>
    <version>60.0</version>
</Package>
```

---

## 3. Deployment Sequence & Activation Protocol

When interactive deployment to the target Developer Org is authorized by the user:

1. **Verify Prerequisite SF-05 Deployment**:
   Ensure `Generation_Request__c` custom object and `Job_Generation_Requester` permission set are present in the target org.
2. **Execute Scoped Deployment**:
   ```powershell
   sf project deploy start --manifest salesforce/manifest/sf06.xml --target-org <target-alias>
   ```
3. **Execute Remote Apex Test Suite**:
   ```powershell
   sf apex run test --class-names JA_GenerationSubmitTest --target-org <target-alias> --result-format human --code-coverage
   ```
4. **Assign Permission Set**:
   Assign `Job_Generation_Actions` to the candidate user:
   ```powershell
   sf org assign permset --name Job_Generation_Actions --target-org <target-alias>
   ```
5. **Verify UI Quick Action Placement**:
   Open a `Job__c` record in Lightning Experience and confirm the "Generate CV" and "Generate Cover Letter" buttons appear in the highlights/action panel.

---

## 4. Rollback & Emergency Deactivation

If deactivation or rollback is required:
1. **Disable Quick Actions via Layout**:
   Remove `Job__c.JA_Generate_CV` and `Job__c.JA_Generate_Cover_Letter` from `Job__c-JA Candidate Tracking.layout-meta.xml` and redeploy layout. Actions immediately disappear from candidate UI.
2. **Deactivate Flows**:
   Deactivate `JA_Generate_CV` and `JA_Generate_Cover_Letter` in Flow Builder.
3. **Preserve Data Integrity**:
   - **Never delete** existing `Generation_Request__c` or `JA_Generation_Submission__c` records during rollback.
   - Queued and completed requests remain fully inspectable by the local worker and candidate.

