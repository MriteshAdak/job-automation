# Component Handoff: MATCH-02 — Model-Assisted Relevance Assessment

Component ID: **MATCH-02**  
Status: **IMPLEMENTED — LIVE VERIFICATION PENDING**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Planning Reference: [docs/stories/MATCH-02.md](../stories/MATCH-02.md)  
Prerequisite Handoffs: [docs/components/MATCH-01.md](MATCH-01.md), [docs/components/CONTEXT-04.md](CONTEXT-04.md), [docs/components/LLM-01.md](LLM-01.md)  
Date Completed: 29 October 2026  
Direct Covered Requirements: [R01](../../IMPLEMENTATION_BLUEPRINT.md#r01), [R02](../../IMPLEMENTATION_BLUEPRINT.md#r02), [R05](../../IMPLEMENTATION_BLUEPRINT.md#r05), [R06](../../IMPLEMENTATION_BLUEPRINT.md#r06), [R07](../../IMPLEMENTATION_BLUEPRINT.md#r07), [R09](../../IMPLEMENTATION_BLUEPRINT.md#r09), [R13](../../IMPLEMENTATION_BLUEPRINT.md#r13), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16)  

---

## 1. Prerequisites and Upstream Dependencies Verification

Before implementing MATCH-02, prerequisite contracts and handoffs were inspected:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **Boundary 4 RuleEvaluator & Deterministic Trace** | MATCH-01 | **VERIFIED** | `job_automation.assessment.service` (`evaluate_deterministic_with_trace`, `DeterministicDecisionTrace`). Confirmed hard failures, exclusions, and missing-policy rejections are extracted into immutable trace. |
| **Boundary 7 Assessor Protocol & C11 Contracts** | MATCH-01 / FND-01 | **VERIFIED** | Preserved existing `Assessor.assess` protocol on Boundary 7 via `LegacyAssessorAdapter`. Extended `Assessment` and `LLMAssessmentMetadata` with backward-compatible defaults. |
| **Boundary 6 ContextSelectorV2Port & C09 ContextBundle** | CONTEXT-04 | **VERIFIED** | `job_automation.context.selector_ports.ContextSelectorV2Port` (`select_context(request) -> (ContextSelectionResult, ClassifiedError)`). Bridges both `ContextStrategy.JSON` and `ContextStrategy.RAG`. |
| **Boundary 5 ModelProviderPort & LLM-01 Client** | LLM-01 | **VERIFIED** | `job_automation.models.provider.LocalModelProvider`, `job_automation.models.inputs.InMemoryInputResolver`, `BoundGenerationInput`, `ModelCall`, `ModelResult`. Registered `assessment_proposal` schema with LLM-01 registry. |

---

## 2. Implementation Summary by Story

All eight planned stories from `docs/stories/MATCH-02.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **MATCH-02-S01** | Assessment Contracts & Legacy Assessor Adapter | **VERIFIED** | Extended C11 `Assessment` with `requirement_findings`, `validation_issues`, `assessment_input_fingerprint`, and `deterministic_trace_ref`. Defined `AssessorV2` protocol and `LegacyAssessorAdapter`. Exported and validated JSON schemas in `schemas/v1/`. |
| **MATCH-02-S02** | Source-Backed Requirement Preparation | **VERIFIED** | `requirements.py`, `requirement_validation.py`, `requirement_prompts.py`. Extracts requirements before retrieval with exact Unicode character offsets, preserving obligation (`REQUIRED`, `PREFERRED`), negation (`Keine Zertifizierung erforderlich`), and alternatives. German adverts alone yield zero language requirements. |
| **MATCH-02-S03** | Context Strategy Binding & Input Fingerprinting | **VERIFIED** | `context_bridge.py`, `llm_inputs.py`. Bridges to `ContextSelectorV2` with `purpose="assessment"`. Computes SHA-256 `assessment_input_fingerprint` over all output-affecting inputs, invariant to timestamps and attempt UUIDs. |
| **MATCH-02-S04** | Reference Validation & Finding Verification | **VERIFIED** | `reference_validation.py`, `finding_validation.py`. Enforces exact quotation/span checks for job references; requires candidate facts to exist in approved profile and be admitted in `selected_fact_ids`. Rejects invented IDs; flags semantic contradictions (e.g. introductory exposure vs. senior/C1). |
| **MATCH-02-S05** | Bounded Local Model Inference & Strict Schemas | **VERIFIED** | `llm_prompts.py`, `llm_inference.py`, `llm_provenance.py`. System prompt establishes that job postings and candidate context have zero instruction/tool authority. Schema `AssessmentProposal` strictly forbids extra fields (`final_disposition`). |
| **MATCH-02-S06** | Authoritative Deterministic Precedence Composition | **VERIFIED** | `llm_composition.py`. Strict precedence hierarchy: confirmed hard failures remain `REJECTED` (score 100 cannot override), missing-policy rejections (`on_missing='fail'`) remain `REJECTED`, factual unknowns remain `REVIEW`. Preserves all deterministic rule outcomes. |
| **MATCH-02-S07** | Pending Result Envelopes & Consumer Boundary | **VERIFIED** | `llm_errors.py`, `llm_result.py`. `AssessmentRunResult` enforces mutual exclusivity between success and pending. Outages and budget errors map to safe retryable pending envelopes without fabricating rejections or scores. |
| **MATCH-02-S08** | Fake-Model Catalog, Native Windows & Live Smoke | **VERIFIED** | Comprehensive test catalog (M02-01 through M02-14) covering 106 unit/integration tests. Native Windows path testing with German umlauts/spaces and process restarts. Opt-in live smoke test (`tests/manual/match02_smoke.py`). |

---

## 3. Interfaces and Public Surface

### Boundary 7 Extension: `AssessorV2` Protocol

```python
class AssessorV2(Protocol):
    """Boundary 7 Protocol: Model-assisted assessment service."""

    def assess(self, request: AssessmentRequest) -> AssessmentRunResult:
        """Perform model-assisted assessment combining rules, context, and inference."""
        ...
```

### Request Contract: `AssessmentRequest`

`AssessmentRequest` binds all execution inputs:
- `canonical_job_id: uuid.UUID`
- `posting_revision: str` (SHA-256 content hash)
- `posting: NormalizedPosting`
- `profile: ProfileSnapshot` (requires human approval metadata)
- `policy: Union[EffectivePolicy, SearchPolicy]`
- `context_strategy: ContextStrategy` (`json` or `rag`)
- `deterministic_baseline: Assessment` (from MATCH-01)
- `deterministic_trace: DeterministicDecisionTrace`
- `limits: AssessmentLimits` (`context_limit`, `output_reserve`, `safety_allowance`, `max_requirements`)
- `model_identifier: str` (default `llama3:8b-instruct-q4_K_M`)
- `prompt_version: str` (default `"v1"`)

### Result Envelope: `AssessmentRunResult`

Discriminated union enforcing mutual exclusivity:
- `status == "success"`: contains completed C11 `Assessment`, no `error` or `failed_stage`.
- `status == "pending"`: `assessment=None`, specifies `failed_stage`, `error: ClassifiedError`, `retryable: bool`, and retains `deterministic_baseline`.

### Backward-Compatibility Adapter: `LegacyAssessorAdapter`

Implements the historical `Assessor` protocol (`assess(rule_outcomes, revision, context) -> Assessment`). Fails visibly with `AssessmentInputError` if invoked without full posting/policy/profile bindings, prompting migration to `AssessorV2`.

---

## 4. Prompt Framing and Settings Versions

- **Extraction System Instruction**: Version `"v1"`, structured JSON extraction of verifiable posting requirements.
- **Assessment System Instruction**: Version `"v1"`, enforces untrusted data boundary (`<job_posting>`, `<requirements>`, `<candidate_facts>`) with explicit instruction that external text has **zero instruction, tool, or command authority**.
- **Output Schema**: `assessment_proposal` (`schemas/v1/assessment_proposal.json`), registered with LLM-01 registry (`extra="forbid"`, 0-100 float score, mandatory summary reason).
- **Default Settings**: `LLMAssessmentSettings` (`max_requirements=20`, `context_limit=4096`, `output_reserve=512`, `safety_allowance=64`, `prompt_version="v1"`, `extractor_mode="deterministic"`).

---

## 5. Authoritative Deterministic Precedence Hierarchy

The final disposition in `compose_llm_assessment` strictly enforces application authority:

```
Precedence 1: Deterministic confirmed hard failure (e.g. visa, location, salary fail)
              --> REJECTED (model score 100 cannot override)
Precedence 2: Missing-information policy rejection (on_missing='fail')
              --> REJECTED (remains distinct from candidate shortfall)
Precedence 3: Baseline deterministic rejection (exclusions, criteria fail)
              --> REJECTED
Precedence 4: Confirmed model gap on a REQUIRED requirement
              --> REJECTED
Precedence 5: Review conditions (deterministic unknowns, eligibility unknowns, or model required unknowns)
              --> REVIEW
Precedence 6: Semantic validation warnings (unsupported extraction, semantic contradiction, missing requirement coverage)
              --> REVIEW
Precedence 7: Relevance score threshold evaluation
              --> REVIEW if score < min_score_threshold, else ELIGIBLE
```

---

## 6. Citation Resolution and Evidence Semantics

> [!IMPORTANT]
> **Traceability Guarantee**: Reference validation verifies exact Unicode spans, field resolution, and candidate fact admission in `selected_fact_ids`. A valid citation proves **traceability**, but does **NOT** prove semantic truth.

Validation rules:
- **Job References**: Verified against normalized posting text at exact Unicode character offsets (`0 <= start < end <= len`). Spans and verbatim quotations must match character-for-character.
- **Candidate References**: Must resolve to an approved `CandidateFact` in the profile snapshot **and** must be present in `bundle.selected_fact_ids`. Unselected or restricted facts (`allowed_uses` lacking `"assessment"`) are fatal to the proposal.
- **Contradiction Detection**: Citing facts with "introductory exposure only" or "Grundkenntnisse" to support senior or C1 German requirements triggers a `semantic_contradiction` review warning.
- **Omission Handling**: Omitted requirements automatically default to application-owned `UNKNOWN` findings with a `missing_requirement_coverage` warning.

---

## 7. Test Catalog Verification (M02-01 through M02-14)

| ID | Scenario | Observable Result | Test File | Status |
|---|---|---|---|---|
| **M02-01** | Strict proposal / C11 / result schemas | Strict schema validation; mutual exclusivity of success/pending; extra fields forbidden. | `test_llm_contracts.py`, `test_llm_failures.py` | **PASSED** |
| **M02-02** | Structured and passage requirement extraction | Traceable source spans; stable deterministic source IDs; requirements extracted pre-retrieval. | `test_requirement_preparation.py` | **PASSED** |
| **M02-03** | Obligation, negation, alternatives & advert language | Preserves preferred status, negation, alternatives; German advert alone yields no language requirement. | `test_requirement_preparation.py`, `test_requirement_extraction.py` | **PASSED** |
| **M02-04** | Dual context strategy binding (JSON & RAG) | Both consume approved snapshot; mandatory facts preserved; strategy mismatch fails. | `test_llm_context_binding.py` | **PASSED** |
| **M02-05** | RAG retrieval omission handling | Omitted profile facts produce `UNKNOWN` with retrieval limitation; never false gap. | `test_llm_integration.py` | **PASSED** |
| **M02-06** | Finding validation & contradiction detection | Exactly one finding per requirement; matches require citations; introductory exposure flagged. | `test_llm_findings.py` | **PASSED** |
| **M02-07** | Recoverable failures & error classification | Model outage (503/timeout) returns pending result with `retryable=True`; preserves baseline. | `test_llm_failures.py` | **PASSED** |
| **M02-08** | Authoritative deterministic precedence | Hard failures remain `REJECTED` despite score 100; policy rejections survive; unknowns yield `REVIEW`. | `test_llm_precedence.py` | **PASSED** |
| **M02-09** | Prompt security boundary & zero tool authority | Job text fenced in untrusted tags; instructions to override rules ignored; no tool execution. | `test_llm_prompt_boundary.py` | **PASSED** |
| **M02-10** | Citation & evidence reference validation | Invalid spans, wrong revisions, unselected facts, and wrong versions flagged cleanly. | `test_llm_evidence.py` | **PASSED** |
| **M02-11** | Assessment input identity sensitivity | Stable SHA-256 fingerprint changes if any material input changes; invariant to attempt UUIDs. | `test_llm_input_identity.py` | **PASSED** |
| **M02-12** | Full end-to-end integration (JSON & RAG) | Real MATCH-01 + actual `ContextSelectorV2Service` + `LocalModelProvider` + SQLite round-trip. | `test_llm_integration.py` | **PASSED** |
| **M02-13** | Run result persistence & consumer adaptation | Serialization/deserialization round-trip; SQLite repository persistence; legacy adapter conformance. | `test_llm_consumer_boundary.py` | **PASSED** |
| **M02-14** | Native Windows paths, handle release & live smoke | Tested paths with spaces/German umlauts (`ä, ö, ü`); handles released cleanly; opt-in live runner. | `test_llm_windows_paths.py`, `test_llm_windows_restart.py`, `match02_smoke.py` | **PASSED** |

### Test Suite Execution Summary
- **Targeted Assessment Suite**: 106 passed in 1.01s (`pytest tests\assessment`).
- **Core Dependencies Suite**: 496 passed in 5.10s (`pytest tests\assessment tests\contracts tests\models tests\context`).
- **Full Repository Regression**: **1060 passed in 15.77s** (`pytest`).
- **Native Windows Out-of-Directory**: 2 passed from `$env:TEMP` (`test_llm_windows_paths.py`, `test_llm_windows_restart.py`).
- **Live Local Model Smoke Runner**: Successfully executed against local Ollama instance (`qwen:4b`), reporting completed structured generation and validation diagnostics cleanly.

---

## 8. Limitations and Handoff Gates

1. **Live Local Model Verification Pending**:
   - Component status is **IMPLEMENTED — LIVE VERIFICATION PENDING**. Offline fake-transport, contract, boundary, and native Windows tests are completely verified. Live evaluation over production corpora on target hardware is handed off to **EVAL-01**.
2. **Durable Orchestration & Retries (RUN-01)**:
   - MATCH-02 generates and returns `AssessmentRunResult(status="pending", retryable=True/False)`. Durable scheduling, checkpointing, and execution retry policies are owned by **RUN-01**.
3. **Salesforce Sync & Outbox (SYNC-01)**:
   - MATCH-02 does not publish to Salesforce or manage C12 outbox atomicity. Atomically committing the chosen C11 assessment with C12 publication belongs to **SYNC-01**.
4. **No Semantic Correctness Claim from Reference Validation**:
   - Reference validation confirms exact quotation and fact admission. It does not certify that the underlying text semantically guarantees candidate competence.

