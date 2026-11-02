# SF-00 Supporting Document: Metadata Ownership, Boundaries, and Dependency Analysis

Document ID: **SF-00-METADATA**  
Status: **PLANNED BASELINE (Repository Gap Recorded; Remote Audit Pending)**  
Observation Date: **01 November 2026**  
Scope: **SF-00-S03 (Establish Metadata Ownership and Dependency Boundaries)**  
Direct Requirements: **R08, R16** (with **R15** credential privacy constraint)

---

## 1. Metadata Classification Framework

To ensure that the job search automation cleanly coexists with any existing assets in the user's Developer Org without accidental clobbering, metadata assets are classified into five strict ownership tiers:

| Classification | Definition | Project Policy |
|---|---|---|
| **Project-Owned** | Metadata components authored, deployed, and version-controlled specifically for this project (e.g. `Company__c`, `Job__c`, `Job_Automation_Worker` permission set). | Managed in repository; deployed through standard CI/CD or metadata deploy; subject to recovery backups. |
| **Shared Dependency** | Platform features and shared objects utilized by the project (e.g. `User` object, standard System Administrator profile, org daily API limits). | Read and referenced; never altered or redeployed by project metadata packages. |
| **Unrelated / Protected** | Pre-existing custom objects, Apex classes, flows, and tabs belonging to other applications or Trailhead exercises. | Strictly protected. Never overwritten, modified, or deleted. In the event of a name collision, project adapts its names. |
| **Managed-Package Controlled** | Components belonging to an installed third-party package (identified by namespace prefix, e.g. `sf_chttr__`, `trailhead__`). | Read-only. Schema and triggers cannot be altered by project deployments. |
| **Ownership Unknown** | Unnamespaced custom components found in the org without explicit provenance linking them to this project or repository. | Held in quarantine. Must be audited before any deployment touching their scope. |

---

## 2. Inventory of Candidate Project Metadata Assets

The following metadata members represent the full planned surface across Phases 0 and 1, categorized by the owning component:

| Component Owner | Metadata Type | Proposed Member Name | Ownership Category | Intended Function |
|---|---|---|---|---|
| **SF-01** | `CustomObject` | `Company__c` | Project-Owned | Stores employer/company entities and canonical IDs. |
| **SF-01** | `CustomObject` | `Job__c` | Project-Owned | Stores vacancy details, assessment outcomes, and application progress. |
| **SF-01** | `CustomField` | `Company__c.*`, `Job__c.*` | Project-Owned | Mapped machine fields and candidate-owned fields (see `schema.md`). |
| **SF-02** | `PermissionSet` | `Job_Automation_Worker` | Project-Owned | Grants least-privilege CRUD/FLS for the Python integration worker. |
| **SF-02** | `ExternalClientApp` | `Job_Automation_Client` | Project-Owned | OAuth 2.0 endpoint enabling secure token exchange. |
| **SF-03** | `CustomTab` | `Job__c` | Project-Owned | Navigation tab for candidate application tracking in Lightning Experience. |
| **SF-03** | `CustomApplication` | `Job_Tracker` | Project-Owned | Lightning App grouping Job and Company tabs. |
| **SF-03** | `ListView` | `Job__c.Eligible_Jobs`, `Job__c.Review_Queue` | Project-Owned | Pre-filtered views for candidate review. |
| **SF-03** | `Layout` / `FlexiPage` | `Job_Record_Page` | Project-Owned | Lightning record page displaying machine fit summaries and candidate inputs. |
| **SF-05 (Phase 1)** | `CustomObject` | `Generation_Request__c` | Project-Owned | Tracks CV/cover letter generation requests (C13). |
| **SF-06 (Phase 1)** | `QuickAction` / `Flow` | `Generate_CV`, `Generate_Cover_Letter` | Project-Owned | Screen Flows on `Job__c` allowing human-initiated drafting. |
| **SF-07 (Phase 1)** | `ContentDocumentLink` | *(Standard Attachment)* | Shared Dependency | Salesforce Files linking generated artifacts to `Job__c`. |
| **SF-08 (Phase 1)** | `CustomNotificationType` | `Draft_Ready_Notification` | Project-Owned | In-app notification alerting candidate when a generated document is ready. |

---

## 3. Repository Drift Analysis and Local Metadata Gap

An inspection of the local repository sources yielded the following baseline observations:

1. **Local Metadata Absence**:
   - There is no `salesforce/` directory in the repository root.
   - No `sfdx-project.json` configuration file exists.
   - No `package.xml` manifest or individual `*-meta.xml` files exist in source control.
2. **Planning Consequence**:
   - The absence of local metadata files represents a local project artifact gap, **not evidence that the remote org is empty**.
   - Before deploying any new metadata in SF-01, an authoritative baseline must be retrieved or verified against the target org.
3. **Downstream Responsibility (SF-04 & SF-01)**:
   - SF-04 owns establishing a scoped retrieval manifest (`package.xml`) containing strictly the allowlisted project members.
   - Wildcard retrievals (e.g. `<members>*</members>`) are strictly prohibited to prevent committing unrelated org assets or broad profile definitions into git.

---

## 4. Automation and Side-Effect Inspection Procedure

When live access is established, the inspector must check for active automation that could interfere with sync operations:

```soql
-- 1. Check for active Apex Triggers on candidate objects
SELECT Id, Name, TableEnumOrId, Status, UsageBeforeInsert, UsageAfterInsert, UsageBeforeUpdate, UsageAfterUpdate 
FROM ApexTrigger 
WHERE TableEnumOrId IN ('Job__c', 'Company__c')

-- 2. Check for active Record-Triggered Flows
SELECT Id, MasterLabel, DeveloperName, TriggerType, ProcessType, Status 
FROM FlowDefinitionView 
WHERE TriggerType IN ('RecordBeforeSave', 'RecordAfterSave') 
  AND ProcessType = 'AutoLaunchedFlow'

-- 3. Check for active Validation Rules
SELECT Id, ValidationName, Active, EntityDefinition.QualifiedApiName, ErrorMessage 
FROM ValidationRule 
WHERE EntityDefinition.QualifiedApiName IN ('Job__c', 'Company__c') AND Active = True
```

Any active automation discovered must be documented in `schema.md` to ensure the sync dispatcher does not trigger unintended validation failures or workflow loops.

