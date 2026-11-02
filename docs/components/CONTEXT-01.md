# Component Handoff: CONTEXT-01 — Full-Profile JSON Context

Component ID: **CONTEXT-01**  
Status: **VERIFIED**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026), especially §§2, 4, 5, 6/CONTEXT-01, 8, 9  
Prerequisite Handoffs: [docs/components/FND-01.md](FND-01.md), [docs/components/PROFILE-01.md](PROFILE-01.md)  
Planning Reference: [docs/stories/CONTEXT-01.md](../stories/CONTEXT-01.md)  
Date Completed: 28 October 2026  
Direct Covered Requirements: [R06](../../IMPLEMENTATION_BLUEPRINT.md#r06), [R13](../../IMPLEMENTATION_BLUEPRINT.md#r13) (supporting R07, R11, R14, R15, R16)  

---

## 1. Prerequisites and Upstream Dependencies Verification

Before implementing CONTEXT-01, all prerequisite contracts and services from **FND-01** and **PROFILE-01** were inspected and verified:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **C01 ProfileSnapshot** | FND-01 / PROFILE-01 | **VERIFIED** | `validate_snapshot` validates schema version, approval metadata (`is_approved=True`), and fact graph integrity (cycles, duplicates, precision date ranges). |
| **Shared Inclusion Rules** | PROFILE-01 | **VERIFIED** | `InclusionRules` in `profile/inclusion.py` enforces purpose matrix filtering (`assessment`, `cv`, `cover_letter`), parent privacy protection, and deterministic sorting. |
| **C08 EvidenceReference** | FND-01 / PROFILE-01 | **VERIFIED** | `CandidateEvidenceReference` resolves historical `(profile_version, fact_id)` pairs via `ProfileService.resolve_candidate_reference`. |
| **C06 NormalizedPosting** | FND-01 / INGEST-02 | **VERIFIED** | `NormalizedPosting` provides clean description, title, company hint, workplace type, and raw content hash. |
| **C09 ContextBundle** | FND-01 | **VERIFIED** | Existing contract baseline loaded cleanly; updated with backward-compatible rich typed fields. |

**Missing Prerequisite Report**: Zero missing prerequisites. All upstream dependencies are active and functional.

---

## 2. Implementation Summary by Story

All six ordered stories from `docs/stories/CONTEXT-01.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **CONTEXT-01-S01** | Freeze construction, mandatory-context & budget contracts | **VERIFIED** | Created `src/job_automation/context/records.py`, `ports.py`, `settings.py`. Extended C09 `ContextBundle` with typed fields (`candidate_id`, `purpose`, `inclusion_rule_version`, `mandatory_policy_version`, `builder_version`, `serialization_version`, `mandatory_fact_ids`, `structured_mandatory`, `content_fingerprint`, `budget_report`). Maintained 100% backward compatibility for legacy readers. Regenerated schema `schemas/v1/C09_context_bundle.schema.json`. |
| **CONTEXT-01-S02** | Prepare complete permitted set & mandatory context once | **VERIFIED** | Implemented `ProfileContextPreparer` in `context/preparation.py` implementing Mandatory Context Policy v1 (chronology anchors for permitted employment/education, permitted ancestor chains, validated caller explicit IDs). Fixed `profile/inclusion.py` to reject mandatory IDs absent from the snapshot and stabilized warning ordering. |
| **CONTEXT-01-S03** | Assemble lossless, deterministic full JSON | **VERIFIED** | Implemented `context/serialization.py` with `serialize_candidate_fact` preserving every fact field losslessly (claims, skills, metrics, precision dates, organization, parent ID, provenance, allowed uses), `serialize_candidate_model_projection` producing deterministic sorted-key JSON with unescaped Unicode, and SHA-256 `compute_content_fingerprint`. Implemented `DefaultJobBindingValidator` in `context/binding.py`. |
| **CONTEXT-01-S04** | Measure & admit whole request within model budget | **VERIFIED** | Implemented `context/rendering.py`, `context/measurement.py`, and `context/budget.py`. Evaluates whole-prompt admission rule `P + O + M <= L` with explicit candidate allowance `L - (instruction + job + framing + O + M)`. Distinguishes exact token counts from conservative heuristic estimates. Overflow by 1 token returns visible `context_budget` error with exact deficit. |
| **CONTEXT-01-S05** | Expose complete success or visible, actionable failure | **VERIFIED** | Implemented `JsonContextBuilder` in `context/json_builder.py` and `ContextService` facade in `context/service.py`. Enforces invariant that exactly one of `(bundle, error)` is non-null. Maps failures to `ClassifiedError` (validation, permission, context_budget, missing_configuration, unsupported_input). Safe diagnostics omit sensitive claims and raw job text. No partial bundles, no truncation, and no silent RAG fallback. |
| **CONTEXT-01-S06** | Verify fidelity, shared inclusion & native Windows behavior | **VERIFIED** | Implemented 11 test suites (46 tests) in `tests/context/`. Verified multi-version snapshots across database reopenings/restarts, native Windows Unicode/space path execution, and execution from `$env:TEMP`. Regenerated contract catalog schemas. Ran full workspace regression (834 tests passing). |

---

## 3. Files Created and Modified

### Context Package Source Files (`src/job_automation/context/`)
- [`src/job_automation/context/__init__.py`](../../src/job_automation/context/__init__.py): Public exports for services, builders, preparers, evaluators, records, and errors.
- [`src/job_automation/context/records.py`](../../src/job_automation/context/records.py): `JsonContextRequest`, `PreparedProfileContext`, `RenderedPrompt`, `MeasurementResult`, `WholePromptMeasurement`.
- [`src/job_automation/context/ports.py`](../../src/job_automation/context/ports.py): Protocols `JobBindingPort`, `TokenCounterPort`, `PromptRendererPort`, `JsonContextBuilderPort`.
- [`src/job_automation/context/settings.py`](../../src/job_automation/context/settings.py): `ContextSettings` configuration model.
- [`src/job_automation/context/errors.py`](../../src/job_automation/context/errors.py): Domain exceptions (`ContextError`, `ContextValidationError`, `ContextPermissionError`, `ContextBudgetOverflowError`, `ContextConfigurationError`, `ContextUnsupportedError`, `JobBindingError`, `MeasurementError`) and classification mapper `map_context_exception_to_classified_error`.
- [`src/job_automation/context/preparation.py`](../../src/job_automation/context/preparation.py): `ProfileContextPreparer` implementing Mandatory Context Policy v1 shared with future RAG.
- [`src/job_automation/context/binding.py`](../../src/job_automation/context/binding.py): `DefaultJobBindingValidator` verifying job content and revision hash correspondence.
- [`src/job_automation/context/serialization.py`](../../src/job_automation/context/serialization.py): Deterministic canonical JSON serialization, model projection builder, string mandatory projection, and SHA-256 content fingerprinting.
- [`src/job_automation/context/rendering.py`](../../src/job_automation/context/rendering.py): `DefaultPromptRenderer` formatting whole prompt while treating job and candidate context strictly as untrusted data.
- [`src/job_automation/context/measurement.py`](../../src/job_automation/context/measurement.py): `ConservativeCharRatioEstimator` and `ExactTokenCounter` implementations with explicit `is_exact` labelling.
- [`src/job_automation/context/budget.py`](../../src/job_automation/context/budget.py): `BudgetEvaluator` enforcing `P + O + M <= L` and candidate allowance accounting.
- [`src/job_automation/context/json_builder.py`](../../src/job_automation/context/json_builder.py): `JsonContextBuilder` synchronous builder with strict failure visibility.
- [`src/job_automation/context/service.py`](../../src/job_automation/context/service.py): `ContextService` facade.

### Shared Contract and Profile Updates
- [`src/job_automation/contracts/context.py`](../../src/job_automation/contracts/context.py): Added `ChronologyReference`, `MandatoryFactReason`, `StructuredMandatoryContext`, `BudgetReport`, and backward-compatible typed fields on `ContextBundle`.
- [`src/job_automation/profile/inclusion.py`](../../src/job_automation/profile/inclusion.py): Fixed missing mandatory ID validation (`MANDATORY_FACT_NOT_FOUND`) and stabilized warning sorting order.
- [`schemas/v1/C09_context_bundle.schema.json`](../../schemas/v1/C09_context_bundle.schema.json): Regenerated JSON schema via `export_schemas.py`.

### Configuration and Fixtures
- [`config/context.example.json`](../../config/context.example.json): Non-secret configuration example.
- [`tests/fakes/context_measurement.py`](../../tests/fakes/context_measurement.py): `FakeTokenCounter` for deterministic boundary testing.
- [`tests/fixtures/context/README.md`](../../tests/fixtures/context/README.md): Fixture catalog documentation with synthetic data guarantee.
- [`tests/fixtures/context/synthetic_context_request.json`](../../tests/fixtures/context/synthetic_context_request.json): Synthetic valid request fixture.

### Test Suites (`tests/context/`)
- [`tests/context/__init__.py`](../../tests/context/__init__.py): Test package marker.
- [`tests/context/test_contract_boundary.py`](../../tests/context/test_contract_boundary.py): Request, report, settings, and C09 round-trip tests.
- [`tests/context/test_preparation.py`](../../tests/context/test_preparation.py): Purpose matrix, mandatory chronology derivation, ancestor chains, missing/restricted mandatory IDs, RAG parity, mutation isolation.
- [`tests/context/test_serialization.py`](../../tests/context/test_serialization.py): Complete fact serialization, Unicode preservation, deterministic key order, distinct identical-text facts, fingerprinting.
- [`tests/context/test_binding.py`](../../tests/context/test_binding.py): Job revision hash validation, content correspondence, custom validator hook.
- [`tests/context/test_budget.py`](../../tests/context/test_budget.py): Exact boundary `P=3000, O=900, M=100, L=4000`, +1 overflow detection, overhead exhaustion, invalid limits.
- [`tests/context/test_measurement.py`](../../tests/context/test_measurement.py): Estimator ceiling behavior, exact counter callback, negative count rejection.
- [`tests/context/test_json_builder.py`](../../tests/context/test_json_builder.py): Public builder end-to-end, success invariants, safe overflow errors, permission conflicts, absence of fallback.
- [`tests/context/test_safe_diagnostics.py`](../../tests/context/test_safe_diagnostics.py): Sensitive claim text and raw job secrets excluded from errors and warnings.
- [`tests/context/test_windows_paths.py`](../../tests/context/test_windows_paths.py): Execution with paths containing spaces and German umlauts.
- [`tests/context/test_windows_restart.py`](../../tests/context/test_windows_restart.py): SQLite storage reopen and reproducible bundle generation across restarts.
- [`tests/context/test_integration.py`](../../tests/context/test_integration.py): Multi-version lifecycle (v1, v2 corrections, permission restrictions), multiple purposes, and historical C08 resolution.

---

## 4. Key Architectural Decisions (D01–D09)

1. **D01: C09 Typed Additions and Backward Compatibility**:
   C09 `ContextBundle` was extended with optional typed fields (`candidate_id`, `purpose`, `inclusion_rule_version`, `mandatory_policy_version`, `builder_version`, `serialization_version`, `mandatory_fact_ids`, `structured_mandatory`, `content_fingerprint`, `budget_report`). By providing default values, legacy C09 readers and existing test fixtures validate and round-trip without regression.
2. **D02: Mandatory Context Policy v1 & Essential Chronology**:
   Permissions are evaluated strictly *before* deriving mandatory anchors. Private facts are never made mandatory. Mandatory context automatically includes:
   - All permitted employment and education facts (`chronology_employment`, `chronology_education`).
   - Permitted ancestor chains required to interpret permitted child evidence (`ancestor_chain`).
   - Caller explicit mandatory IDs (`caller_required`).
   Restricted optional ancestors remain unexpanded with an opaque parent reference and a deterministic warning. If an explicitly required fact is restricted from the target purpose, an explicit `ContextPermissionError` (`InclusionConflictError`) is raised. Missing mandatory IDs raise `ContextValidationError`.
3. **D03: Exact Local Tokenizer vs. Conservative Heuristic Estimation**:
   When no local tokenizer package (e.g. `tiktoken`, `transformers`) is installed in the Python environment, token counting defaults to `ConservativeCharRatioEstimator` (3.5 chars/token with ceiling rounding). All reports explicitly label `is_exact=False` and name the method (`conservative_char_ratio_v1`). Requests with `require_exact_measurement=True` fail visibly with `unsupported_input` rather than claiming exactness from a heuristic.
4. **D04: Whole-Prompt Model Window & Output Reservation Accounting**:
   Admission enforces `P + O + M <= L`, where:
   - `P` = total input tokens (complete rendered prompt).
   - `O` = output reserve tokens.
   - `M` = safety allowance margin.
   - `L` = effective model window limit.
   Candidate allowance is explicitly allocated: `candidate_allowance = L - (instruction_tokens + job_tokens + framing_tokens + O + M)`. If candidate allowance is non-positive or if total demand exceeds `L`, a visible non-recoverable `context_budget` error is returned.
5. **D05: Whole-Prompt Overhead & Component Attribution**:
   Token accounting measures the full rendered prompt string, including instructions, output schema instructions, job description, requirements, framing headers, separators, and candidate projection JSON. Breakdown attribution reports component totals while guaranteeing that whole-prompt demand governs admission.
6. **D06: Safe Overflow Diagnostics**:
   Diagnostics on budget overflow provide exact numerical deficits (`overflow`, `total_input_tokens`, `effective_window`, `output_reserve`, `safety_allowance`) and measurement metadata without disclosing raw candidate claims or proprietary job text.
7. **D07: Input Fingerprint Binding**:
   A deterministic SHA-256 fingerprint (`content_fingerprint`) binds candidate projection JSON, canonical job ID, posting revision, purpose, builder version, serialization version, instructions, and requirements. Any modification to prompt framing, job content, or candidate claims invalidates the fingerprint.
8. **D08: Shared Preparation API with Future RAG**:
   `ProfileContextPreparer.prepare_context` produces a shared `PreparedProfileContext` consumable by both full JSON context and future RAG retrieval (CONTEXT-02/04). Both strategies see the identical permitted evidence universe, identical chronology anchors, and identical explicit eligibility.
9. **D09: Lossless Candidate Evidence Serialization**:
   All permitted candidate facts are serialized with all fields intact (`fact_id`, `parent_id`, `kind`, `title`, `organization`, `start_date`, `end_date`, `skills`, `claims`, `metrics`, `provenance`, `allowed_uses`). No fields are truncated, summarized, or filtered based on requirement keywords. Two facts with identical text but distinct UUIDs are preserved as distinct records.

---

## 5. Verification Commands and Actual Results

### 1. Context Test Suite Execution with Coverage
```powershell
& ".\.venv\Scripts\python.exe" -m pytest --cov=job_automation.context tests\context
```
Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0
rootdir: C:\Users\mrite\Projects\job-search
configfile: pyproject.toml
plugins: cov-6.3.0
collected 46 items

tests\context\test_binding.py ......                                     [ 13%]
tests\context\test_budget.py ....                                        [ 21%]
tests\context\test_contract_boundary.py .....                            [ 32%]
tests\context\test_integration.py .                                      [ 34%]
tests\context\test_json_builder.py ......                                [ 47%]
tests\context\test_measurement.py .....                                  [ 58%]
tests\context\test_preparation.py .........                              [ 78%]
tests\context\test_safe_diagnostics.py ...                               [ 84%]
tests\context\test_serialization.py .....                                [ 95%]
tests\context\test_windows_paths.py .                                    [ 97%]
tests\context\test_windows_restart.py .                                  [100%]

=============================== tests coverage ================================
Name                                          Stmts   Miss  Cover
-----------------------------------------------------------------
src\job_automation\context\__init__.py           13      0   100%
src\job_automation\context\binding.py            29      2    93%
src\job_automation\context\budget.py             28      0   100%
src\job_automation\context\errors.py             31      4    87%
src\job_automation\context\json_builder.py       47      1    98%
src\job_automation\context\measurement.py        46     10    78%
src\job_automation\context\ports.py              20      0   100%
src\job_automation\context\preparation.py        77      4    95%
src\job_automation\context\records.py            69      0   100%
src\job_automation\context\rendering.py          37      4    89%
src\job_automation\context\serialization.py      42      0   100%
src\job_automation\context\service.py            17      1    94%
src\job_automation\context\settings.py           14      0   100%
-----------------------------------------------------------------
TOTAL                                           470     26    94%
============================= 46 passed in 1.52s ==============================
```

### 2. Execution from Different Working Directory (Native Windows `$env:TEMP`)
```powershell
Push-Location -LiteralPath $env:TEMP
try {
    & "C:\Users\mrite\Projects\job-search\.venv\Scripts\python.exe" -m pytest "C:\Users\mrite\Projects\job-search\tests\context\test_windows_paths.py" "C:\Users\mrite\Projects\job-search\tests\context\test_windows_restart.py"
} finally {
    Pop-Location
}
```
Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0
rootdir: C:\Users\mrite\Projects\job-search
configfile: pyproject.toml
plugins: cov-6.3.0
collected 2 items

..\..\..\Projects\job-search\tests\context\test_windows_paths.py .       [ 50%]
..\..\..\Projects\job-search\tests\context\test_windows_restart.py .     [100%]

============================== 2 passed in 0.54s ==============================
```

### 3. Full Repository Regression Suite Execution
```powershell
& ".\.venv\Scripts\python.exe" -m pytest
```
Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0
rootdir: C:\Users\mrite\Projects\job-search
configfile: pyproject.toml
testpaths: tests
plugins: cov-6.3.0
collected 834 items

============================ 834 passed in 24.15s =============================
```

---

## 6. Limitations, Open Choices, and Downstream Handoff

### Identified Limitations and Capabilities
- **No External Tokenizer Installed**: The local Python environment does not currently contain an external tokenizer (such as `tiktoken` or Hugging Face `tokenizers`). In production, exact tokenizer counting is simulated via `ExactTokenCounter` callbacks or estimated via `ConservativeCharRatioEstimator`. Requests requiring exact measurement when only an estimator is available fail visibly.
- **Hardware-Specific Context Window Limits**: Context limit `L` and output reserve `O` are supplied explicitly in `JsonContextRequest` or via `ContextSettings`. CONTEXT-01 does not infer VRAM limits or hardware capacities, deferring operational benchmarking to MODEL-02 and runtime invocation to LLM-01.
- **Immutable Input Snapshots**: Approved C01 snapshots are treated as immutable truth. If facts cannot fit in the window, CONTEXT-01 will never truncate claims, alter dates, omit facts, or silently switch to RAG. An explicit `context_budget` error is raised.

### Downstream Handoff
- **CONTEXT-02 / CONTEXT-04**: Must consume `ProfileContextPreparer` to ensure that chunking and RAG retrieval operate over the exact same permitted evidence universe and retain the mandatory chronology anchors.
- **LLM-01**: Must receive the exact `RenderedPrompt.full_prompt` and verify that runtime execution parameters match the `JsonContextRequest` context window and output reservation.
- **MATCH-02 / GEN-02**: Can invoke `JsonContextBuilder.build` directly with approved C01 snapshots and bound postings to obtain fully budgeted context bundles.

