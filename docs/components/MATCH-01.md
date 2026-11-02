# Component Handoff: MATCH-01 — Deterministic Eligibility and Keyword Matching

Component ID: **MATCH-01**  
Status: **VERIFIED**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Prerequisite Handoffs: [docs/components/POLICY-01.md](POLICY-01.md), [docs/components/PROFILE-01.md](PROFILE-01.md), [docs/components/INGEST-02.md](INGEST-02.md), [docs/components/IDENTITY-01.md](IDENTITY-01.md), [docs/components/IDENTITY-02.md](IDENTITY-02.md)  
Planning Reference: [docs/stories/MATCH-01.md](../stories/MATCH-01.md)  
Date Completed: 28 October 2026  
Direct Covered Requirements: [R02](../../IMPLEMENTATION_BLUEPRINT.md#r02), [R04](../../IMPLEMENTATION_BLUEPRINT.md#r04), [R05](../../IMPLEMENTATION_BLUEPRINT.md#r05), [R06](../../IMPLEMENTATION_BLUEPRINT.md#r06), [R07](../../IMPLEMENTATION_BLUEPRINT.md#r07), [R08](../../IMPLEMENTATION_BLUEPRINT.md#r08), [R09](../../IMPLEMENTATION_BLUEPRINT.md#r09), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16)  

---

## 1. Prerequisites and Upstream Dependencies Verification

Before implementing MATCH-01, all prerequisite contracts and services from **POLICY-01**, **PROFILE-01**, **INGEST-02**, **IDENTITY-01**, and **IDENTITY-02** were inspected and verified:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **C02 SearchPolicy & EffectivePolicy** | POLICY-01 | **VERIFIED** | `job_automation.contracts.policy` (`SearchPolicy`, `HardCriterion`, `PreferenceRule`, `RelevanceConfig`) and `job_automation.policy.models` (`EffectivePolicy`, `EffectiveMissingAction`). |
| **C01 ProfileSnapshot & Evidence** | PROFILE-01 | **VERIFIED** | `job_automation.contracts.profile` (`ProfileSnapshot`, `CandidateEligibility`, `CandidateFact`, `ProfileApproval`) and `job_automation.profile.inclusion` (`InclusionRules`). |
| **C06 NormalizedPosting** | INGEST-02 | **VERIFIED** | `job_automation.contracts.postings` (`NormalizedPosting`, `JobCompensation`, `StructuredLocation`). |
| **C07 CanonicalJob & PostingRevision** | IDENTITY-01 / 02 | **VERIFIED** | `job_automation.contracts.identity` (`CanonicalJob`, `PostingRevision`). |
| **C11 Assessment Contracts** | FND-01 | **VERIFIED** | `job_automation.contracts.assessment` (`Assessment`, `RuleOutcome`, `LLMAssessmentMetadata`). |
| **C12 SyncOperation & Outbox** | FND-01 | **VERIFIED** | `job_automation.contracts.sync` (`SyncPayload`, `SyncOperation`). |
| **RuleEvaluator Protocol** | FND-01 | **VERIFIED** | `job_automation.contracts.interfaces.RuleEvaluator` protocol (`evaluate_rules(revision, policy, eligibility) -> Assessment`). |
| **AssessmentRepository** | DATA-01 | **VERIFIED** | `job_automation.storage.repositories.assessments.AssessmentRepository` (`save_assessment`, `get_assessment`, `get_assessments_for_job`, `get_latest_assessment`). |

### Missing Prerequisite Report
1. **PostingRevision to NormalizedPosting Decoupling**: In `PostingRevision` (C07), full normalized fields (`compensation`, `locations`, `workplace_type`, `description_clean`) are not embedded directly on the revision model, but rather on `NormalizedPosting` (C06) keyed by `SourceKey`. MATCH-01 provides `PostingReader` port and `AssessmentService` resolving C06 postings, with an automatic fallback in `DeterministicRuleEvaluator` for standalone revision evaluation.
2. **Absence of Typed Visa/Sponsorship Fields in C06**: C06 `NormalizedPosting` currently captures `workplace_type`, `locations`, `remote_eligibility_restrictions`, and `advert_language`, but lacks dedicated boolean fields for `visa_sponsorship_offered`. Per D04, candidate work authorization checks verify against posting countries and remote restrictions without fabricating sponsorship inferences.
3. **Absence of Typed Language Fluency Requirements in C06**: C06 captures `advert_language`, which MATCH-01 checks against candidate language facts. Unstructured description mentions of language proficiencies remain for model-assisted assessment (MATCH-02).
4. **Synthetic Onboarding Fixtures**: Until live candidate profiles and production search policies are configured, tests use verified synthetic profiles and policies (`tests/fixtures/policy/valid_tech.json`).

---

## 2. Implementation Summary by Story

All eight planned stories from `docs/stories/MATCH-01.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **MATCH-01-S01** | Rule Evaluator Contract & Precedence | **VERIFIED** | `DeterministicRuleEvaluator`, `AssessmentService`, `composition.py`. Strict precedence: Hard Fail (`REJECTED`) > Missing Review (`REVIEW`) > Eligible (`ELIGIBLE`). Enforces `model_metadata=None` and `relevance_score=None`. |
| **MATCH-01-S02** | Bounded Operator Engine & Accessors | **VERIFIED** | `operators.py`, `fields.py`. Evaluates all allowlisted operators (`equals`, `not_equals`, `in`, `not_in`, `contains`, `not_contains`, `gte`, `lte`, `between`). Implements multi-location alternative logic (existential for positive, universal for negative). |
| **MATCH-01-S03** | Decimal Compensation Comparator | **VERIFIED** | `compensation.py`. Compares monetary values via `Decimal`. Enforces currency match, period match, interval intersection semantics, and explicit unit validation (rejecting bare numbers/missing currency/period). Incompatible units yield `UNKNOWN`. |
| **MATCH-01-S04** | Missing-Information Evaluator | **VERIFIED** | `hard_rules.py`. Implements D03 precedence (`explicit_rule` > `field_default` > `global_default unknown`). Missing facts are never fabricated. Evaluates all hard criteria without short-circuiting to capture complete diagnostic gaps. |
| **MATCH-01-S05** | Candidate Eligibility & Fact Separation | **VERIFIED** | `eligibility.py`, `evidence.py`. Validates candidate work authorization against DE/posting countries and remote restrictions. Produces traceable `JobEvidenceReference` and `CandidateEvidenceReference`. Enforces human profile approval and purpose filtering. |
| **MATCH-01-S06** | Exclusions, Keywords & Soft Preferences | **VERIFIED** | `exclusions.py`, `keywords.py`, `preferences.py`, `literal_matching.py`. Word-boundary token matching preserving `C++`, `C#`, `.NET`, `Go`. Excluded employer/title causes rejection; incidental description hits propose review. Preferences influence score/reasons without causing hard rejection. Routes to `REVIEW` when `min_score_threshold` is configured without model inference. |
| **MATCH-01-S07** | Pure Function Determinism & Sync Outbox | **VERIFIED** | `service.py`, `test_reproducibility.py`, `test_consumer_boundary.py`. Bit-for-bit identical outputs across identical inputs, criterion order permutations, and restarts. Clean mapping into `SyncPayload` excluding candidate-owned fields. |
| **MATCH-01-S08** | Windows Hardening, Test Corpus & Handoff | **VERIFIED** | `test_windows_paths.py`, `test_windows_restart.py`, `test_integration.py`, `tests/fixtures/assessment/` with `README.md`. Verified clean file-handle releases, path resilience with German umlauts/spaces, and regression-free test suite. |

---

## 3. Files Created and Modified

### Source Files (`src/job_automation/assessment/`)
- [`src/job_automation/assessment/__init__.py`](../../src/job_automation/assessment/__init__.py): Public exports for domain models, service, evaluator, and ports.
- [`src/job_automation/assessment/errors.py`](../../src/job_automation/assessment/errors.py): Domain exceptions (`AssessmentError`, `AssessmentInputError`, `AssessmentConfigurationError`, `FieldEvaluationError`).
- [`src/job_automation/assessment/models.py`](../../src/job_automation/assessment/models.py): Domain models (`FactualOutcome`, `CriterionEvaluation`, `PreferenceOutcome`, `ExclusionOutcome`, `RelevanceAssessmentResult`, `AssessmentInput`).
- [`src/job_automation/assessment/ports.py`](../../src/job_automation/assessment/ports.py): Protocols for decoupling (`PostingReader`, `ProfileReader`, `AssessmentRepositoryPort`).
- [`src/job_automation/assessment/fields.py`](../../src/job_automation/assessment/fields.py): C06 field accessor (`get_posting_field_value`).
- [`src/job_automation/assessment/evidence.py`](../../src/job_automation/assessment/evidence.py): C08 evidence builders (`build_job_evidence`, `build_candidate_evidence`).
- [`src/job_automation/assessment/literal_matching.py`](../../src/job_automation/assessment/literal_matching.py): Token/boundary matcher preserving technology symbols (`C++`, `C#`, `.NET`, `Go`).
- [`src/job_automation/assessment/compensation.py`](../../src/job_automation/assessment/compensation.py): Decimal compensation comparator with interval semantics and unit compatibility checks.
- [`src/job_automation/assessment/operators.py`](../../src/job_automation/assessment/operators.py): Bounded operator evaluator supporting multi-location alternatives and enum normalization.
- [`src/job_automation/assessment/hard_rules.py`](../../src/job_automation/assessment/hard_rules.py): Hard criteria evaluator enforcing D03 missing-information precedence and comprehensive evaluation.
- [`src/job_automation/assessment/eligibility.py`](../../src/job_automation/assessment/eligibility.py): Explicit candidate eligibility evaluator (work authorization, remote work, remote restrictions).
- [`src/job_automation/assessment/preferences.py`](../../src/job_automation/assessment/preferences.py): Soft preferences evaluator.
- [`src/job_automation/assessment/exclusions.py`](../../src/job_automation/assessment/exclusions.py): Employer and title exclusions with description incidental mention detection.
- [`src/job_automation/assessment/keywords.py`](../../src/job_automation/assessment/keywords.py): Broad keyword search with vocabulary alias expansion.
- [`src/job_automation/assessment/relevance.py`](../../src/job_automation/assessment/relevance.py): Relevance synthesis coordinator.
- [`src/job_automation/assessment/inputs.py`](../../src/job_automation/assessment/inputs.py): Input binding enforcing profile approval and inclusion filtering.
- [`src/job_automation/assessment/composition.py`](../../src/job_automation/assessment/composition.py): C11 `Assessment` record composer enforcing strict precedence and null model metadata.
- [`src/job_automation/assessment/service.py`](../../src/job_automation/assessment/service.py): `AssessmentService`, `evaluate_deterministic`, and `DeterministicRuleEvaluator` (implementing `RuleEvaluator` Protocol).

### Tests and Fixtures (`tests/assessment/` and `tests/fixtures/assessment/`)
- [`tests/assessment/conftest.py`](../../tests/assessment/conftest.py): Fixtures `make_posting`, `make_profile`, `make_policy`.
- [`tests/assessment/test_candidate_eligibility.py`](../../tests/assessment/test_candidate_eligibility.py): Candidate truth and work authorization tests.
- [`tests/assessment/test_compensation.py`](../../tests/assessment/test_compensation.py): Decimal salary, intervals, and incompatible unit tests.
- [`tests/assessment/test_consumer_boundary.py`](../../tests/assessment/test_consumer_boundary.py): C11 persistence round-trip and C12 SyncPayload mapping tests.
- [`tests/assessment/test_contract_boundary.py`](../../tests/assessment/test_contract_boundary.py): C11 contract validation tests.
- [`tests/assessment/test_exclusions.py`](../../tests/assessment/test_exclusions.py): Employer, title, and description negative keyword tests.
- [`tests/assessment/test_hard_rules.py`](../../tests/assessment/test_hard_rules.py): Hard rule outcomes and missing precedence tests.
- [`tests/assessment/test_inputs.py`](../../tests/assessment/test_inputs.py): Input binding, unapproved profile rejection, and inclusion filtering tests.
- [`tests/assessment/test_integration.py`](../../tests/assessment/test_integration.py): End-to-end integration with PolicyService, DefaultNormalizer, and scenario matrix.
- [`tests/assessment/test_keywords.py`](../../tests/assessment/test_keywords.py): Keyword matching, punctuation preservation, and alias tests.
- [`tests/assessment/test_operators.py`](../../tests/assessment/test_operators.py): Bounded operator engine and multi-location tests.
- [`tests/assessment/test_preferences.py`](../../tests/assessment/test_preferences.py): Soft preference scoring tests.
- [`tests/assessment/test_reproducibility.py`](../../tests/assessment/test_reproducibility.py): Bit-for-bit reproducibility and order invariance tests.
- [`tests/assessment/test_windows_paths.py`](../../tests/assessment/test_windows_paths.py): Windows paths with spaces, German umlauts, and handle release tests.
- [`tests/assessment/test_windows_restart.py`](../../tests/assessment/test_windows_restart.py): SQLite persistence across process/connection restart tests.
- [`tests/fixtures/assessment/eligible_posting.json`](../../tests/fixtures/assessment/eligible_posting.json): Synthetic eligible job fixture.
- [`tests/fixtures/assessment/hard_fail_posting.json`](../../tests/fixtures/assessment/hard_fail_posting.json): Synthetic hard-fail job fixture.
- [`tests/fixtures/assessment/missing_compensation_posting.json`](../../tests/fixtures/assessment/missing_compensation_posting.json): Synthetic missing compensation job fixture.
- [`tests/fixtures/assessment/excluded_employer_posting.json`](../../tests/fixtures/assessment/excluded_employer_posting.json): Synthetic excluded employer job fixture.
- [`tests/fixtures/assessment/README.md`](../../tests/fixtures/assessment/README.md): Assessment fixture documentation.

---

## 4. Key Architectural Decisions (D01–D10)

1. **D01: Single Implementation of Boundary 4**: `DeterministicRuleEvaluator` implements `RuleEvaluator` protocol (`job_automation.contracts.interfaces.RuleEvaluator`), backed by `AssessmentService` and pure functional evaluation (`evaluate_deterministic`).
2. **D02: Pure Evaluation & Immutability**: `evaluate_deterministic` is a pure function. It accepts frozen/immutable models, performs zero I/O, does not invoke LLMs or external networks, and mutates no inputs.
3. **D03: Missing-Information Precedence & Unknown Disposition**: Enforces rule-level `on_missing` > policy-level `missing_information_behavior[field]` > default `unknown`. Omitted advert facts or unverified requirements yield `UNKNOWN` and route to `REVIEW` with clear `identified_unknowns`. Waived criteria (`on_missing='pass'`) record a `PASS` rule outcome with explicit waiver notation in reason.
4. **D04: Candidate Truth vs. Job Advert Facts**: Candidate profile facts (work authorization, remote eligibility) are evaluated separately from job criteria. Omitted candidate facts are treated as unstated, never as negative proof.
5. **D05: Punctuation-Safe Literal Matching**: Literal keyword matching tokenizes on word boundaries while explicitly preserving programming languages and frameworks with symbols (`C++`, `C#`, `.NET`, `Go`). Substring false positives (such as matching `Java` inside `JavaScript`) are strictly prevented.
6. **D06: Decimal Compensation Semantics**: Monetary values are compared using `Decimal`. Comparisons check currency and period equality. Incompatible units, unparseable salaries, or missing periods produce `UNKNOWN`, routing to `REVIEW` unless waived.
7. **D07: Multi-Location Evaluation Semantics**: In postings with multiple structured locations: positive constraints (`equals`, `in`, `contains`) use existential logic (true if at least one location satisfies the constraint); negative constraints (`not_equals`, `not_in`, `not_contains`) use universal logic (true only if all locations satisfy the negative condition).
8. **D08: Complete Evaluation Without Short-Circuiting**: All configured hard criteria are evaluated even after a failure or unknown outcome is encountered. This ensures C11 records contain complete gap analysis (`identified_gaps`, `identified_unknowns`, and full `rule_outcomes`) for human review and downstream processing.
9. **D09: Deterministic Relevance & Exclusion Precedence**: Broad keyword evaluation expands search terms via policy `role_aliases` and `skill_aliases`. Employer/title exclusions produce immediate `REJECTED` disposition. Incidental description mentions produce `REVIEW` proposals. If a policy configures a numeric `min_score_threshold`, deterministic evaluation routes to `REVIEW` because model inference is disallowed in MATCH-01.
10. **D10: Downstream Outbox Compatibility**: C11 `Assessment` records cleanly map to C12 `SyncPayload` and `SyncOperation`. Machine-owned assessment fields (`final_disposition`, `summary_reason`, `relevance_score=None`) enter the outbox, while candidate-owned fields (application progress, candidate notes, interview dates) are strictly excluded.

---

## 5. Verification Commands and Actual Results

### Automated Assessment Test Suite Execution
Command executed:
```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests\assessment
```
Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0
rootdir: C:\Users\mrite\Projects\job-search
configfile: pyproject.toml
plugins: cov-6.3.0
collected 50 items

tests\assessment\test_candidate_eligibility.py ...                       [  6%]
tests\assessment\test_compensation.py ......                             [ 18%]
tests\assessment\test_consumer_boundary.py ..                            [ 22%]
tests\assessment\test_contract_boundary.py ....                          [ 30%]
tests\assessment\test_exclusions.py .....                                [ 40%]
tests\assessment\test_hard_rules.py ...                                  [ 46%]
tests\assessment\test_inputs.py ....                                     [ 54%]
tests\assessment\test_integration.py .......                             [ 68%]
tests\assessment\test_keywords.py ....                                   [ 76%]
tests\assessment\test_operators.py ......                                [ 88%]
tests\assessment\test_preferences.py ..                                  [ 92%]
tests\assessment\test_reproducibility.py ..                              [ 96%]
tests\assessment\test_windows_paths.py .                                 [ 98%]
tests\assessment\test_windows_restart.py .                               [100%]

============================= 50 passed in 0.55s ==============================
```

### Boundary Test Suites Execution
Command executed:
```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests\contracts tests\policy tests\profile tests\ingestion tests\identity tests\storage
```
Output:
```text
============================ 425 passed in 15.43s =============================
```

### Native Windows Path & Basetemp Verification
Command executed:
```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests\assessment --basetemp "$env:TEMP\job_search_täst pfäd"
```
Output:
```text
============================= 50 passed in 0.53s ==============================
```

### Full Repository Regression Execution
Command executed:
```powershell
& ".\.venv\Scripts\python.exe" -m pytest
```
Output:
```text
============================ 686 passed in 16.26s =============================
```

### Test Coverage Execution
Command executed:
```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests\assessment --cov=job_automation.assessment --cov-report=term-missing
```
Output:
```text
Name                                                Stmts   Miss  Cover
-----------------------------------------------------------------------
src\job_automation\assessment\__init__.py               6      0   100%
src\job_automation\assessment\compensation.py         128     61    52%
src\job_automation\assessment\composition.py           57      5    91%
src\job_automation\assessment\eligibility.py           47      1    98%
src\job_automation\assessment\errors.py                 5      0   100%
src\job_automation\assessment\evidence.py              18      2    89%
src\job_automation\assessment\exclusions.py            37      1    97%
src\job_automation\assessment\fields.py                52     37    29%
src\job_automation\assessment\hard_rules.py            56      9    84%
src\job_automation\assessment\inputs.py                37     11    70%
src\job_automation\assessment\keywords.py              63      1    98%
src\job_automation\assessment\literal_matching.py      37      8    78%
src\job_automation\assessment\models.py                82      0   100%
src\job_automation\assessment\operators.py            146     44    70%
src\job_automation\assessment\ports.py                 16      0   100%
src\job_automation\assessment\preferences.py           37      9    76%
src\job_automation\assessment\relevance.py             38      1    97%
src\job_automation\assessment\service.py               50      8    84%
-----------------------------------------------------------------------
TOTAL                                                 912    198    78%
```

### Native Windows Checks Summary
- **Python Runtime**: Native Windows CPython 3.12.10 (`.\.venv\Scripts\python.exe`).
- **Paths**: Absolute paths with drive letters, spaces, and German umlauts (`ä`, `ö`, `ü`) tested without escaping errors or double-prefixing.
- **File Locks**: SQLite connections explicitly close in `StorageEngine.close()`, verified by deleting active temporary test directories without Windows `PermissionError` (WinError 32 / Sharing Violation).
- **Restart Persistence**: State persists and round-trips cleanly across distinct `StorageEngine` instances and connection restarts.
- **Pending Windows Checks**: None.

---

## 6. Live Service Applicability
- **External Network / APIs**: Not applicable. Deterministic assessment operates entirely offline.
- **Salesforce Org**: Not applicable. Zero writes or gateway calls are performed.
- **Ollama / Local LLM**: Not applicable. No model inference is executed (`assessment_method=rules`, `model_metadata=None`).

---

## 7. Remaining Limitations and Guidance for Downstream Components

1. **MATCH-02 (Model-Assisted Relevance & Context Selection)**:
   - Evaluates jobs that pass deterministic hard criteria or require semantic reasoning (unstructured experience, qualifications, description requirements).
   - Generates C09 `ContextBundle` (JSON or RAG strategy within token budget).
   - Populates C11 `relevance_score`, `score_scale="0-100"`, and `model_metadata` (`LLMAssessmentMetadata`).
   - Must preserve all deterministic hard rule failures: a hard rule `REJECTED` disposition cannot be overridden by model inference.
2. **RUN-01 (Pipeline Orchestration)**:
   - Binds `CanonicalJob` and active `PostingRevision` to `NormalizedPosting` and candidate `ProfileSnapshot`.
   - Triggers `AssessmentService.evaluate_posting(...)` during evaluation stage.
   - Saves C11 assessment via `AssessmentRepository.save_assessment(...)`.
   - Retains run ledger metrics (`assessed_count`, `eligible_count`, `rejected_count`, `review_count`).
3. **SYNC-01 (Salesforce Synchronization)**:
   - Reads C11 `Assessment` records and transforms locally owned fields into `SyncPayload`.
   - Enforces that `SyncPayload` never overwrites candidate-owned status, notes, or application follow-up fields in Salesforce.

