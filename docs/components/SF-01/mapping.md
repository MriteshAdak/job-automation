# SF-01 Supporting Document: Schema Mapping and Ownership Contract

Document ID: **SF-01-MAPPING**  
Status: **IMPLEMENTED BASELINE (Live Describe Pending Target Org Binding)**  
Date: **01 November 2026**  
Scope: **SF-01-S01 (Resolve the Schema and Ownership Contract)**  
Direct Requirements: **R04, R08, R16** (with **R15** credential privacy constraint)  

---

## 1. Executive Summary & Purpose

This document establishes the authoritative logical-to-physical schema mapping, ownership classification, and naming collision strategy for synchronizing personal job search vacancies into Salesforce.

### Org Target & Inspection Baseline
- **Intended Org Alias**: `dev-main` (Developer Edition with Dev Hub enabled; discovered in `%USERPROFILE%\.sfdx\alias.json`).
- **Live Inventory Prerequisite Status**: Incomplete / Pending live target confirmation and SF-02 credential provisioning. In accordance with SF-00 boundary rules and blueprint §5, no remote org mutation or live probing was performed.
- **Org-dependent TODO**: The configuration and settings modules carry the designated warning comment:
  ```python
  # TODO(SF-01/SF-00): Verify the selected org (currently alias dev-main).
  # Resolve its org ID, endpoint and supported API version; inspect object/field
  # names, External IDs, lookup targets, picklists, required fields and defaults.
  # Supply verified values through SalesforceSettings and SyncMappingConfig.
  # Revalidate mappings and migration needs whenever the target org changes.
  ```

---

## 2. Ownership Classification Framework

All metadata assets and database fields are classified into strict tiers to ensure that pipeline sync never overwrites human input or collides with existing assets:

| Asset / Role | API Name | Ownership Tier | Mutation Authority | Inbound Sync / Recovery Policy |
|---|---|---|---|---|
| **Company Object** | `Company__c` | Project-Owned | Pipeline Worker | Created/updated via REST upsert on external ID. |
| **Job Object** | `Job__c` | Project-Owned | Pipeline Worker & Candidate | Partitioned field ownership (machine vs candidate). |
| **Canonical Company ID** | `Canonical_Company_Id__c` | Project-Owned (Machine) | Pipeline Worker | Immutable once set; validated by regex rule. |
| **Canonical Job ID** | `Canonical_Job_Id__c` | Project-Owned (Machine) | Pipeline Worker | Immutable once set; validated by regex rule. |
| **Company Parent Link** | `Company__c` (Lookup) | Project-Owned (Machine) | Pipeline Worker | Injected after parent Company upsert; delete restricted. |
| **Job Title** | `Name` / `Job_Title__c` | Project-Owned (Machine) | Pipeline Worker | Written on insert and updated on revision refresh. |
| **Assessment Machine State** | `Availability__c`, `Assessment_Disposition__c`, `Assessment_Reasons__c`, `Relevance_Score__c`, `Score_Scale__c`, `Last_Evaluated_At__c`, `Source_URLs__c` | Project-Owned (Machine) | Pipeline Worker | Replaced on evaluation refresh; nulls cleared cleanly. |
| **Reconciliation State** | `Sync_Operation_Marker__c`, `Machine_Sync_Version__c` | Project-Owned (Machine) | Pipeline Worker | Monotonic sequence counters preventing stale overwrites. |
| **Application Progress** | `Application_Progress__c` | Project-Owned (**Candidate**) | **Candidate Only** | Defaulted to `New` by Salesforce on insert; **never** overwritten by machine sync. |
| **Candidate Notes & Decision** | `Candidate_Notes__c`, `Candidate_Decision__c` | Project-Owned (**Candidate**) | **Candidate Only** | Strictly excluded from outbound writes; backed up locally. |
| **Candidate Schedules** | `Follow_Up_Date__c`, `Interview_Date__c` | Project-Owned (**Candidate**) | **Candidate Only** | Strictly excluded from outbound writes; backed up locally. |

---

## 3. Logical-to-Physical Mappings

### 3.1 Company Object Mapping (`Company__c`)

| Logical Contract Property | Physical Field API Name | Field Type | Constraints & Flags | Notes |
|---|---|---|---|---|
| `company_external_id_field` | `Canonical_Company_Id__c` | `Text(36)` | External ID, Unique (Case-Insensitive), Required | Hyphenated lowercase UUID string (`uuid.UUID`). |
| `company_name_field` | `Name` | `Text(80/255)` | Standard Name field, Required | Standard Name field for baseline configuration. |
| *(Alternative)* | `Company_Name__c` | `Text(255)` | Optional Custom Field | Used when standard `Name` is Autonumber (`CMP-{000000}`). |
| `sync_marker_field` | `Sync_Operation_Marker__c` | `Text(255)` | Nullable, Indexed | Operation UUID token for lost-response recovery. |
| `sync_version_field` | `Machine_Sync_Version__c` | `Number(18, 0)` | Integer, Nullable | Monotonic sequence counter. |

### 3.2 Job Object Mapping (`Job__c`)

| Logical Contract Property | Physical Field API Name | Field Type | Constraints & Flags | Notes |
|---|---|---|---|---|
| `job_external_id_field` | `Canonical_Job_Id__c` | `Text(36)` | External ID, Unique (Case-Insensitive), Required | Hyphenated lowercase UUID string (`uuid.UUID`). |
| `title_field` | `Name` | `Text(80/255)` | Standard Name field, Required | Job posting title. |
| *(Alternative)* | `Job_Title__c` | `Text(255)` | Optional Custom Field | Used when standard `Name` is Autonumber (`JOB-{000000}`). |
| `job_company_lookup_field` | `Company__c` | `Lookup(Company__c)` | `deleteConstraint="Restrict"`, Relationship: `Jobs` | Ordinary lookup; prevents cascade deletion of jobs. |
| `availability_field` | `Availability__c` | `Picklist` (Restricted) | Values: `Active`, `Not Seen`, `Unavailable`, `Unknown` | No default value. Missing observation never defaults to Active. |
| `disposition_field` | `Assessment_Disposition__c` | `Picklist` (Restricted) | Values: `Eligible`, `Review`, `Rejected` | No default value. |
| `reason_field` | `Assessment_Reasons__c` | `LongTextArea(32768)` | Multi-line text | Formatted criteria summary from C11 Assessment. |
| `score_field` | `Relevance_Score__c` | `Number(18, 6)` | Nullable | Null for rules-only assessments; explicit null clears old score. |
| `score_scale_field` | `Score_Scale__c` | `Text(255)` | Nullable | Null for rules-only assessments; explicit null clears old scale. |
| `last_evaluated_field` | `Last_Evaluated_At__c` | `DateTime` | UTC ISO-8601 | Evaluated event time preserved in UTC. |
| `source_urls_field` | `Source_URLs__c` | `LongTextArea(32768)` | Nullable | Newline-separated URLs. Empty collection clears old URLs. |
| `sync_marker_field` | `Sync_Operation_Marker__c` | `Text(255)` | Nullable, Indexed | Operation UUID token. |
| `sync_version_field` | `Machine_Sync_Version__c` | `Number(18, 0)` | Integer, Nullable | Monotonic sequence counter. |

### 3.3 Candidate-Owned Fields (`candidate_fields`)

| Physical Field API Name | Field Type | Creation Default | Edit Authority | Sync Payload Rule |
|---|---|---|---|---|
| `Application_Progress__c` | `Picklist` (Restricted) | `New` (Configured in Org Metadata) | Candidate Only | Strictly excluded from writes. Values: `New`, `Review`, `Shortlisted`, `Applied`, `Interviewing`, `Offer`, `Rejected`, `Withdrawn`, `Archived`. |
| `Candidate_Notes__c` | `LongTextArea(32768)` | Blank (`null`) | Candidate Only | Strictly excluded from writes; backed up locally. |
| `Candidate_Decision__c` | `Text(255)` | Blank (`null`) | Candidate Only | Strictly excluded from writes; manual candidate override. |
| `Follow_Up_Date__c` | `Date` | Blank (`null`) | Candidate Only | Strictly excluded from writes; date-only precision. |
| `Interview_Date__c` | `Date` | Blank (`null`) | Candidate Only | Strictly excluded from writes; date-only precision. |

---

## 4. Collision and Resolution Register

| Collision Risk | Detection Mechanism | Resolution Policy | Verified In Tests |
|---|---|---|---|
| **Standard Name is Autonumber** | `metadata_parser` inspects `nameField.type == "AutoNumber"`. | Switch mapping to `config/sync.autonumber.example.json` (`title_field: "Job_Title__c"`, `company_name_field: "Company_Name__c"`). | `test_v02_autonumber_and_text_name_handling` |
| **Unrelated Object Name Conflict** | Object already in org with conflicting schema/purpose. | Adopt project prefix: `JA_Company__c` and `JA_Job__c` (`config/sync.prefixed.example.json`). | `test_v01_alternative_checked_mapping_for_prefixed_objects` |
| **Candidate Field Aliases Machine Field** | `SyncMappingConfig._validate_ownership_separation` catches intersections. | Immediate validation error prior to any write attempt. | `test_v03_ownership_and_semantic_collision_rejections` |
| **Candidate Field Aliases External ID / Lookup** | `SyncMappingConfig` validator checks External ID and Lookup fields. | Immediate validation error prior to any write attempt. | `test_v03_ownership_and_semantic_collision_rejections` |
| **Intra-Entity Machine Roles Alias Same Field** | `SyncMappingConfig` checks duplicate values in machine field map. | Immediate validation error prior to any write attempt. | `test_v03_ownership_and_semantic_collision_rejections` |
| **Parent Company Deleted** | `Lookup` deleteConstraint is `Restrict`. | Prevents deleting a Company that has active child Jobs. | `test_v07_lookup_relationship_and_restrict_delete` |
| **Stale Overwrite on Network Retry** | `Machine_Sync_Version__c` monotonic integer check. | Old payloads cannot overwrite newer state. | `test_v09_null_clearing_and_utc_eval_time` |

---

## 5. Configuration Deltas & Consumer Impacts

1. **Mapping Configuration Delta (`config/sync.example.json`)**:
   - Retained schema 1.0, mapping version `1.0`.
   - Dedicated examples added for autonumber (`config/sync.autonumber.example.json`) and prefixed isolation (`config/sync.prefixed.example.json`).
2. **Permission Requirements for SF-02**:
   - `Job_Automation_Worker` permission set must grant:
     - Read/Create/Edit on `Company__c` and all its custom fields.
     - Read/Create/Edit on `Job__c` machine fields.
     - **Read-Only** on candidate fields (`Application_Progress__c`, `Candidate_Notes__c`, `Candidate_Decision__c`, `Follow_Up_Date__c`, `Interview_Date__c`) for local backup.
     - **No Delete** permissions on either object.
3. **Consumer Obligations for SYNC-01**:
   - SYNC-01 must continue enforcing `assert_no_candidate_fields` before HTTP submission.
   - Company upsert must precede Job upsert; the returned Salesforce Company ID is passed as `company_salesforce_id` to `build_job_payload`.

