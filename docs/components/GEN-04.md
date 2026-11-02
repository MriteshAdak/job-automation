# Component Handoff: GEN-04 — Factual & Structural Document Validation

Component ID: **GEN-04**  
Status: **IMPLEMENTED & VERIFIED (Unit / Integration / Subprocess / Restart Crash Matrix / Windows Native / Offline Real SQLite) — Downstream physical rendering and human review delivery pending GEN-05 and GEN-06**  
Phase: **Phase 1 / P1 (S01–S07 Implemented)**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) §§5–9, G4; [docs/stories/GEN-04.md](../stories/GEN-04.md)  
Prerequisite Handoffs:
- [GEN-01](GEN-01.md) (**VERIFIED**)
- [GEN-02 stories](../stories/GEN-02.md) (**IMPLEMENTED / VERIFIED in `src/job_automation/generation/input_service.py`**)
- [GEN-03](GEN-03.md) (**IMPLEMENTED / VERIFIED**)
- [PROFILE-01](PROFILE-01.md) (**VERIFIED**)  
Date Completed: 31 October 2026  
Direct Covered Requirement: [R11](../../IMPLEMENTATION_BLUEPRINT.md#r11)  
Supporting Constraints: [R06](../../IMPLEMENTATION_BLUEPRINT.md#r06), [R12](../../IMPLEMENTATION_BLUEPRINT.md#r12), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16)

---

## 1. Executive Summary & Component Scope

`GEN-04` implements deterministic, factual, and structural validation for generated C14 draft documents (CVs and Cover Letters). It evaluates structured drafts against their exact frozen source evidence (`GEN-02` seal and context receipt) and supplemental content specifications. It produces an inspectable, durable validation report (`DocumentValidationReport`) that strictly separates fatal validation errors from human-review warnings and governs the gate permitting or blocking rendering for review (`GEN-05`).

### Core Architecture & Behavioral Invariants

1. **Separation of Document Content and Validation Ownership**:
   - The C14 draft payload (`DraftDocumentV2`, schema 2.0) is immutable once generated and committed by `GEN-03`. Its `validation_status` field remains literal `"pending_gen04"`.
   - The validation outcome is owned exclusively by the durable `DocumentValidationReport` (schema 1.0) persisted in `document_validation_attempts` and `document_validation_results`.
   - Legacy C14 `DraftDocument` v1.0 remains inspectable but cannot obtain rendering authorization from the v2 validator without native v2 provenance.

2. **Deterministic Render Gate**:
   - The render decision is computed strictly as:
     $$\text{render\_decision} = \begin{cases} \text{"allowed\_for\_review"} & \text{if } \text{fatal\_count} = 0 \land \text{evaluation\_status} = \text{"complete"} \land \text{required\_checks\_passed} \\ \text{"blocked"} & \text{otherwise} \end{cases}$$
   - Any fatal issue, corrupted binding, or missing required check immediately sets `render_decision = "blocked"`.
   - Warnings do not block rendering for review, but rendering is only authorized for human review; no draft is approved automatically.

3. **Conservative Source-Extractive Verification (`gen04-extractive-v1`)**:
   - Every candidate factual claim must cite an approved, purpose-authorized fact from the frozen profile snapshot and admitted context bundle.
   - Factual excerpts must match the approved source text exactly. Paraphrasing, alterations, ungrounded expansions, or translations of protected source values are fatal.
   - Job claims must cite nonblank, exact substrings in frozen posting text fields (`description_clean`, `title`, `company_name_hint`) with zero-based, in-bounds Unicode spans.
   - Candidate and job claims are strictly isolated; candidate facts can never be proven from job descriptions, and job requirements can never be asserted as candidate achievements.

4. **Review Obligations & Documented Semantic Limitations**:
   - `requires_human_review: Literal[True]` is hardcoded on every validation report.
   - Every report embeds the mandatory `semantic_limits_notice`: code checks only verify traceability to supplied inputs, never real-world truth, factual completeness, or semantic entailment.
   - Upstream warnings from GEN-03 receipts and context bundles are inherited and deduplicated into the final report.

5. **Exclusions**:
   - GEN-04 does **not** regenerate, rewrite, or repair drafts (no model calls or automated repair loops).
   - GEN-04 does **not** render DOCX or PDF files (GEN-05 ownership).
   - GEN-04 does **not** deliver files or update Salesforce records (GEN-06 ownership).
   - GEN-04 does **not** grant candidate approval or certified truth status.

---

## 2. Architecture & Component Interfaces

### Module Overview

| Module | Purpose |
|---|---|
| `src/job_automation/generation/validation_records.py` | Core contracts: `ValidationInputBinding`, `ValidationContentRequirements`, `DocumentValidationIssue`, `RuleOutcome`, `DocumentValidationReport`, `DocumentValidationSettings`, `ValidatedDraftForRendering`, `ValidationRunResult`. |
| `src/job_automation/generation/validation_ports.py` | Protocol interfaces for `DocumentValidationServicePort` and `DraftValidatorPort`. |
| `src/job_automation/generation/validation_inputs.py` | `verify_validation_binding`: verifies frozen seal, context receipt, prompt recipe, manifest, and provenance metadata. |
| `src/job_automation/generation/validation_references.py` | Candidate and job citation resolution, allowed fields/paths, Unicode spans, quote verification, parent privacy rules. |
| `src/job_automation/generation/validation_dates.py` | Calendar date checks (including leap years), precision preservation, null end date handling, uncertainty intervals. |
| `src/job_automation/generation/validation_values.py` | Title and employer equality, degree versus role distinction, candidate/target identity swap checks. |
| `src/job_automation/generation/validation_metrics.py` | Candidate metric exact extraction, quantitative scanning (`QUANTITATIVE_PATTERN`), metric transplantation detection. |
| `src/job_automation/generation/validation_sections.py` | Required sections per template policy, ordering, catalog headings check, approved subjective phrases check. |
| `src/job_automation/generation/validation_consistency.py` | Entry attribution consistency, cross-entry value conflicts. |
| `src/job_automation/generation/validation_review.py` | Upstream warning inheritance, issue deduplication, deterministic rule outcomes, report assembly. |
| `src/job_automation/generation/validation_service.py` | `DocumentValidationService`: validation orchestration, persistence, reopen, and render input preparation. |
| `src/job_automation/generation/validation_adapter.py` | `DraftValidatorV2`: adapter implementing the `DraftValidator` protocol for `GenerationCoordinator` (GEN-01). |
| `src/job_automation/storage/repositories/document_validations.py` | `DocumentValidationRepository`: SQLite repository managing `document_validation_attempts` and `document_validation_results`. |
| `src/job_automation/storage/migrations.py` | Migration 013 (`MIGRATION_013_DOCUMENT_VALIDATION`): validation attempts and logical results tables. |

### Storage Schema (Migration 013)

```sql
CREATE TABLE document_validation_attempts (
    attempt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    logical_key TEXT NOT NULL,
    binding_hash TEXT NOT NULL,
    draft_receipt_id TEXT NOT NULL,
    draft_hash TEXT NOT NULL,
    rule_set_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    report_json TEXT,
    report_hash TEXT,
    fatal_count INTEGER,
    warning_count INTEGER,
    render_decision TEXT
);

CREATE TABLE document_validation_results (
    request_id TEXT PRIMARY KEY REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    logical_key TEXT NOT NULL,
    attempt_id TEXT NOT NULL UNIQUE REFERENCES document_validation_attempts(attempt_id) ON DELETE RESTRICT,
    report_hash TEXT NOT NULL,
    render_decision TEXT NOT NULL
);
```

---

## 3. Validation Rules & Severity Policy

The following deterministic rules are executed across validation domains under the `gen04-extractive-v1` ruleset:

| Domain | Rule / Code | Severity | Trigger Condition / Description |
|---|---|---|---|
| **Binding** | `frozen_binding_corrupt` | `fatal` | Frozen seal, context receipt, or recipe verification failure in storage. |
| | `provenance_binding_mismatch` | `fatal` | Draft provenance (seal ID/hash, binding hash, recipe hash, prompt version) differs from frozen resources. |
| | `draft_receipt_corrupt` | `fatal` | Draft generation receipt lookup error or corruption in storage. |
| **References** | `claim_subject_mismatch` | `fatal` | Candidate claim citing job evidence, or job claim citing candidate evidence. |
| | `wrong_profile_version` | `fatal` | Candidate reference profile version does not match frozen profile version. |
| | `fact_not_found` | `fatal` | Candidate fact ID does not exist in the frozen profile snapshot. |
| | `profile_unapproved` | `fatal` | Frozen snapshot approval metadata indicates candidate profile is not approved. |
| | `fact_not_admitted` | `fatal` | Fact was not admitted into the frozen context bundle for this request. |
| | `fact_purpose_unauthorized` | `fatal` | Fact's allowed uses do not permit the generation request's purpose. |
| | `parent_privacy_violation` | `fatal` | Child fact claim leaks restricted parent entity information (title/organization). |
| | `invalid_source_field` | `fatal` | Candidate claim cites an unauthorized source field name. |
| | `missing_source_index` | `fatal` | List field (`claims`, `skills`, `metrics`) cited without a source index. |
| | `source_index_out_of_bounds` | `fatal` | Source index is out of bounds for the frozen source list. |
| | `unexpected_source_index` | `fatal` | Scalar field cited with a source index. |
| | `protected_value_missing` | `fatal` | Claim lacks an accompanying `ProtectedSourceValue` record. |
| | `protected_value_mismatch` | `fatal` | Protected source value reference or field disagrees with claim. |
| | `protected_original_value_mismatch` | `fatal` | Protected original value does not match the full frozen source field. |
| | `claim_text_mismatch` | `fatal` | Extracted claim text does not match the exact source string or span excerpt. |
| | `unsafe_claim_characters` | `fatal` | Prohibited markup (`<`, `>`) or null bytes in claim text. |
| **Job Excerpts** | `wrong_posting_revision` | `fatal` | Job reference specifies a revision differing from the frozen posting revision hash. |
| | `quote_not_found` | `fatal` | Quotation string is not present in the specified posting field. |
| | `whitespace_quotation` | `fatal` | Quotation string consists entirely of whitespace. |
| | `job_span_out_of_bounds` | `fatal` | Zero-based Unicode code-point span is out of bounds for the posting field. |
| | `whitespace_job_span` | `fatal` | Posting text within span consists entirely of whitespace. |
| | `quote_span_mismatch` | `fatal` | Quoted string disagrees with the slice extracted by the span. |
| | `ambiguous_quotation` | `warning` | Quotation occurs multiple times in posting text without a specifying span. |
| **Dates** | `invalid_calendar_date` | `fatal` | Calendar date is invalid (e.g. Feb 29 on non-leap years, month 13, day 32). |
| | `date_text_altered` | `fatal` | Date claim text alters precision date string (e.g. `2021-03` to `März 2021`). |
| | `null_date_converted` | `fatal` | Null end date converted to an asserted date or "Present" / "heute". |
| | `reversed_date_range` | `fatal` | Earliest start date interval is strictly after latest end date interval. |
| | `uncertain_date_order` | `warning` | Partial date precision results in overlapping uncertainty intervals. |
| **Values & Titles** | `title_altered` | `fatal` | Candidate title string does not match frozen source title exactly. |
| | `organization_altered` | `fatal` | Candidate employer string does not match frozen source organization. |
| | `credential_role_confusion` | `fatal` | Education fact asserted as employment title, or vice-versa. |
| | `target_identity_swap` | `fatal` | Target job title or company confused with candidate's former employer. |
| **Metrics** | `metric_index_invalid` | `fatal` | Candidate metric index out of bounds for fact's `metrics` list. |
| | `metric_value_altered` | `fatal` | Metric text, unit, currency, sign, or qualifier altered from approved string. |
| | `metric_transplanted` | `fatal` | Metric transplanted to an entry belonging to a different employment role. |
| | `metric_binding_missing` | `fatal` | Confidently identified quantitative metric in non-metric claim or subjective block. |
| **Sections & Policy** | `section_missing` | `fatal` | Missing required section according to template policy. |
| | `duplicate_section` | `fatal` | Duplicate section heading key in document. |
| | `non_catalog_heading` | `fatal` | Section heading does not match recipe catalog for requested language. |
| | `empty_section` | `fatal` | Section contains no entries and no direct claims. |
| | `missing_candidate_evidence` | `fatal` | Experience section contains no candidate factual claims. |
| | `non_catalog_subjective_phrase` | `fatal` | Subjective block uses phrases outside the approved recipe catalog. |
| | `disguised_factual_assertion` | `fatal` | Subjective block contains dates, metrics, or factual claims. |
| **Consistency** | `entry_attribution_inconsistent` | `fatal` | Single entry mixes claims from multiple distinct employment roles. |
| | `cross_entry_value_conflict` | `fatal` | Different claims for the same fact assert contradictory protected values. |
| **Review & Limits** | `upstream_warnings_present` | `warning` | Upstream review warnings inherited from generation receipts. |
| | `unadmitted_evidence_omitted` | `warning` | Admitted facts omitted from draft; omissions do not prove lack of skill. |

### Required Content Policy (`gen04-extractive-v1`)

| Template / Document Type | Required Sections | Allowed Optional Sections (in fixed order) |
|---|---|---|
| `content-basic` 1.0 / CV | `experience` | `summary`, `education`, `skills` |
| `content-compact` 1.0 / CV | `experience` | `skills` |
| `content-basic` 1.0 / Cover Letter | `experience`, `closing` | `opening`, `motivation` |
| `content-compact` 1.0 / Cover Letter | `experience`, `closing` | None |

---

## 4. Documented Semantic Limitations

> [!IMPORTANT]
> **Deterministic Code Checks vs. Semantic Entailment**:
> Validation strictly verifies traceability to supplied inputs. It does not certify real-world truth, factual completeness, or that generated sentences are entailed by their sources.

1. **Traceability is Not Real-World Truth**:
   - A passing validation report certifies that every claim matches an approved record in the candidate's profile snapshot or the employer's posting.
   - It cannot verify whether the candidate actually performed the work or whether the employer's job posting contains accurate statements.

2. **Paraphrasing Requires Human Judgment**:
   - In conservative extractive recipes (`gen04-extractive-v1`), rewrites such as changing "contributed to" to "led" or altering numbers fail automated checks.
   - However, even when claims match their sources verbatim, excerpt placement, juxtaposition, or surrounding sentence structure can imply unintended causality, false seniority, or misleading context. Human review remains mandatory for all drafts.

3. **Retrieval Omission Does Not Prove Negative**:
   - The absence of a skill or experience in the admitted context bundle or the generated draft does not indicate the candidate lacks that qualification.
   - Omissions from RAG context are tagged with warnings and require human evaluator judgment.

4. **No Automated Approval**:
   - The validator produces `render_decision = "allowed_for_review"`, never `"approved"`.
   - Automated approval is prohibited by design. Human candidate review and sign-off are required prior to delivery or external submission.

---

## 5. Verification Evidence & Test Results

The component has been verified using native Windows SQLite execution, offline fixtures, synthetic mutation suites, subprocess execution, and crash recovery tests.

### Test Suites (`tests/generation/validation/`)

| Test File | Cases | Status | Scope |
|---|---|---|---|
| `test_contracts.py` | 5 | PASSED | Pydantic contract instantiation, strict validation, schema export round-trips. |
| `test_compatibility.py` | 2 | PASSED | C14 v1 rejection by v2 validator; unsupported schema versions raise errors. |
| `test_frozen_binding.py` | 5 | PASSED | Seal and context receipt binding; tampering with seal hash, binding hash, or profile version blocks validation. |
| `test_candidate_references.py` | 6 | PASSED | Nonexistent fact ID, wrong profile version, unadmitted facts, purpose restriction, parent privacy leaks, index bounds. |
| `test_job_references.py` | 5 | PASSED | Wrong revision hash, false quotations, whitespace quotes, span mismatches, ambiguous quotes emit review warnings. |
| `test_evidence_confusion.py` | 2 | PASSED | Candidate claims citing job evidence and job claims citing candidate evidence are blocked. |
| `test_dates.py` | 4 | PASSED | Calendar checks (leap years), precision preservation, null end date handling, reversed interval detection. |
| `test_titles.py` | 2 | PASSED | Altered job titles and credential/role confusion (education vs employment) are blocked. |
| `test_metrics.py` | 3 | PASSED | Altered metric strings, ungrounded quantitative figures in claims, and quantitative text in subjective blocks. |
| `test_sections.py` | 5 | PASSED | Missing required sections, duplicate sections, empty sections, non-catalog headings, missing candidate evidence. |
| `test_consistency.py` | 2 | PASSED | Inconsistent entry attribution across roles and cross-entry protected value contradictions. |
| `test_review_warnings.py` | 2 | PASSED | Upstream review warnings inherited; warning-only reports allow rendering for review without approval. |
| `test_semantic_limits.py` | 3 | PASSED | Structurally valid paraphrases require human review; conservative extraction blocks rewrites; no auto-approval. |
| `test_storage.py` | 4 | PASSED | SQLite persistence, tamper detection on reopen, idempotent revalidation reusing committed reports. |
| `test_render_gate.py` | 4 | PASSED | `prepare_render_input` succeeds on valid reports, blocks on fatal errors, and blocks on draft hash mismatches. |
| `test_coordinator.py` | 4 | PASSED | Coordinator integration, checkpoint repair from committed reports, render blocking on unvalidated drafts. |
| `test_windows_paths.py` | 3 | PASSED | Paths with German umlauts (`äöüß`), spaces, and deep folder hierarchies on Windows. |
| `test_windows_restart.py` | 1 | PASSED | Subprocess validation report reopening across fresh Python interpreter processes. |

**Validation Test Summary**: 62 collected, **62 passed**, 0 failed in 5.85s (Exit Code: 0).  
**Repository Regression Summary**: 1608 collected, **1608 passed**, 0 failed in 45.95s (Exit Code: 0).

---

## 6. Downstream Handoff Instructions

### For GEN-05 (Document Rendering)
- Consume `ValidatedDraftForRendering` produced by `DocumentValidationService.prepare_render_input(report_id, draft)`.
- Verify `validated_draft_hash == compute_sha256_digest(draft)` before initiating physical DOCX or PDF layout rendering.
- Render physical artifacts with status `approval_status="draft"` and `delivery_status="local_only"`.
- Do not render any document whose validation report has `render_decision == "blocked"`.

### For GEN-06 (Delivery & Salesforce Integration)
- Display all `DocumentValidationIssue` records with severity `warning` prominently in the candidate review UI.
- Display the mandatory `semantic_limits_notice` before requesting human approval.
- Ensure human approval is recorded out-of-band before setting artifact status to approved.

