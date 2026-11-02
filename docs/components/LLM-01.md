# Component Handoff: LLM-01 — Model Client and Call Harness

Component ID: **LLM-01**  
Status: **IMPLEMENTED** (Offline/conformance verified; live model verification pending MODEL-01 setup)  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Planning Reference: [docs/stories/LLM-01.md](../stories/LLM-01.md)  
Date Completed: 28 October 2026  
Direct Covered Requirements: [R07](../../IMPLEMENTATION_BLUEPRINT.md#r07), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16)  
Supporting Constraint: [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14) (Native Windows without mandatory hosted inference, Docker, WSL, or paid dependencies)

---

## 1. Prerequisites and Upstream Dependencies Verification

Before implementing LLM-01, upstream foundations and handoffs were inspected:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **FND-01 Shared Contracts** | FND-01 | **VERIFIED** | Reused `ModelCall` (C10), `ModelResult` (C10), `ModelProvider` protocol, `ClassifiedError`, and error taxonomy. |
| **MODEL-01 Runtime Setup** | MODEL-01 | **PENDING** | No `docs/components/MODEL-01.md` or live model service is active. Automated test suite runs completely offline with fake/scripted transports. Live smoke test script `tests/manual/model_smoke.py` is delivered and records live readiness as pending. |

---

## 2. Implementation Summary by Story

All eight planned stories from `docs/stories/LLM-01.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **LLM-01-S01** | Freeze Input, Output-Schema & Audit Boundaries | **VERIFIED** | `records.py`, `ports.py`, `inputs.py`. Defined `BoundGenerationInput`, `BoundEmbeddingInput`, `AttemptAuditRecord`, `LogicalCallAuditRecord`. Added mutually exclusive output/error validator on `ModelResult`. Extended `EmbeddingResponse` with `call_id`, `model_digest`, `token_usage`. Mutation resilience verified. |
| **LLM-01-S02** | Configure & Enforce Local Transport Boundary | **VERIFIED** | `configuration.py`, `transport.py`. Strict loopback URL validation (`127.0.0.1`, `localhost`, `::1`), forbidding credentials, query parameters, fragments, directory traversal, and non-loopback DNS resolution. Zero proxy routing, zero auto-redirects, bounded read/connect timeouts, and max response payload limits (default 10MB). |
| **LLM-01-S03** | Bind Inputs, Effective Settings & Context Budgets | **VERIFIED** | `fingerprints.py`, `settings.py`, `budget.py`. Canonical SHA-256 fingerprinting (`v1`) over structured prompts and ordered embedding texts. Settings allowlist rejecting unknown keys, non-finite values, and tools. Context budget preflight checks input, output reserve, and safety margin against context ceilings without truncation. Exact 896 fit vs 897 overflow verified. |
| **LLM-01-S04** | Implement Strict Structured Generation | **VERIFIED** | `schemas.py`, `generation.py`. Bounded POST to `/api/generate`. Wire envelope inspection and strict JSON parsing (`parse_strict_json`) rejecting duplicate keys, NaN/Infinity, markdown code fences, and surrounding prose. Schema validation against registered contract models (`C11_assessment`) forbidding extra or missing fields without type coercion. Null token usage preserved as null. |
| **LLM-01-S05** | Implement Validated Embeddings with Model Provenance | **VERIFIED** | `embeddings.py`. Bounded POST to `/api/embed`. Enforces batch size limits and rejects empty texts. Validates exact 1:1 vector count, original ordering, finite float elements (strictly excluding booleans), and consistent vector dimensions matching declared model capabilities. Links call ID for audit correlation on success and failure. |
| **LLM-01-S06** | Classify Failures & Bound Every Attempt | **VERIFIED** | `errors.py`, `retry.py`. Full mapping of socket exceptions and HTTP status codes (`400`, `401`, `403`, `404`, `429`, `502`, `503`, `504`, `507`) to `ErrorCategory`. Unified `RetryController` with shared transport-attempt cap and overall deadline. Bounded exponential backoff. Configurable malformed-output regeneration (default 0, max 1). |
| **LLM-01-S07** | Record Complete Audit Metadata & Privacy Boundaries | **VERIFIED** | `audit.py`, `diagnostics.py`. Comprehensive audit event emission linking all physical attempts. Visible `AuditRecordError` on recorder failure. Safe diagnostics: url credential redaction, log text sanitization, and allowlisted result projections. Verified that private sentinel prompt tokens never leak into ordinary logs, error messages, or audit records. |
| **LLM-01-S08** | Offline Integration, Windows Hardening & Live Gate | **VERIFIED** | `test_provider_integration.py`, `test_consumer_boundary.py`, `test_windows_paths.py`, `tests/manual/model_smoke.py`. Verified that model errors never turn into job rejection. Path resilience on Windows with spaces and German umlauts. Offline test suite passes 102/102 tests. Live smoke runner checks MODEL-01 availability and records status honestly. |

---

## 3. Files Created and Modified

### Source Files (`src/job_automation/models/`)
- [`src/job_automation/models/__init__.py`](../../src/job_automation/models/__init__.py): Public package exports for provider, settings, schemas, inputs, and utilities.
- [`src/job_automation/models/records.py`](../../src/job_automation/models/records.py): Contracts for `BoundGenerationInput`, `BoundEmbeddingInput`, `AttemptAuditRecord`, and `LogicalCallAuditRecord`.
- [`src/job_automation/models/ports.py`](../../src/job_automation/models/ports.py): Decoupled interfaces: `Clock`, `Sleeper`, `InputResolver`, `AuditRecorder`, `Tokenizer`, `ModelTransport`.
- [`src/job_automation/models/configuration.py`](../../src/job_automation/models/configuration.py): `ModelCapabilities`, `ModelProviderSettings`, and `validate_loopback_url`.
- [`src/job_automation/models/fingerprints.py`](../../src/job_automation/models/fingerprints.py): Canonical SHA-256 fingerprinting for generation prompts and embedding texts.
- [`src/job_automation/models/inputs.py`](../../src/job_automation/models/inputs.py): `InMemoryInputResolver` with immutable binding and defensive copying.
- [`src/job_automation/models/budget.py`](../../src/job_automation/models/budget.py): `ContextBudgetManager`, `CharacterRatioTokenizer`, and `ExactTokenCounter`.
- [`src/job_automation/models/settings.py`](../../src/job_automation/models/settings.py): `validate_generation_settings` and `ALLOWED_GENERATION_SETTINGS`.
- [`src/job_automation/models/schemas.py`](../../src/job_automation/models/schemas.py): `LocalSchemaRegistry`, `parse_strict_json`, and `validate_against_schema`.
- [`src/job_automation/models/transport.py`](../../src/job_automation/models/transport.py): `LoopbackHttpTransport` with timeout enforcement, size bounding, and socket cleanup.
- [`src/job_automation/models/errors.py`](../../src/job_automation/models/errors.py): Mappings for transport exceptions and HTTP status codes to `ClassifiedError`.
- [`src/job_automation/models/retry.py`](../../src/job_automation/models/retry.py): `RetryController` bounding total physical attempts, malformed regenerations, backoff, and deadlines.
- [`src/job_automation/models/generation.py`](../../src/job_automation/models/generation.py): `GenerationHarness` for structured generation workflow.
- [`src/job_automation/models/embeddings.py`](../../src/job_automation/models/embeddings.py): `EmbeddingHarness` for batch text embeddings.
- [`src/job_automation/models/audit.py`](../../src/job_automation/models/audit.py): `AuditManager`, `InMemoryAuditRecorder`, and `AuditRecordError`.
- [`src/job_automation/models/diagnostics.py`](../../src/job_automation/models/diagnostics.py): `redact_url_credentials`, `sanitize_log_text`, and `safe_result_summary`.
- [`src/job_automation/models/provider.py`](../../src/job_automation/models/provider.py): `LocalModelProvider` implementing `ModelProvider` under a serialized inference gate.

### Modified Existing Files
- [`src/job_automation/contracts/models.py`](../../src/job_automation/contracts/models.py): Added `@model_validator` to `ModelResult` enforcing mutual exclusivity of error and output.
- [`src/job_automation/contracts/interfaces.py`](../../src/job_automation/contracts/interfaces.py): Added `call_id`, `model_digest`, and `token_usage` to `EmbeddingResponse`.
- [`src/job_automation/configuration.py`](../../src/job_automation/configuration.py): Added `model_provider: ModelProviderSettings | None` to `AppConfig`; enforced `validate_loopback_url`.
- [`src/job_automation/cli.py`](../../src/job_automation/cli.py): Sanitized error reporting to prevent credential leakage in `config check`.
- [`src/job_automation/contracts/export_schemas.py`](../../src/job_automation/contracts/export_schemas.py): Added `model_provider_settings` to exported schemas.
- `schemas/v1/`: Re-exported schemas, updating `app_config.schema.json` and adding `model_provider_settings.schema.json`.

### Test Files (`tests/`)
- `tests/fakes/model_transport.py`: `ScriptedModelTransport`, `ScriptedClock`, `ScriptedSleeper`.
- `tests/fixtures/models/`: Synthetic wire fixtures (`README.md`, `generation_success.json`, `generation_malformed.json`, `embeddings_success.json`).
- `tests/manual/model_smoke.py`: Opt-in manual live smoke test runner.
- `tests/models/`: 23 test modules containing 102 unit and integration tests.

---

## 4. Key Architectural Decisions

1. **Synchronous Boundary Preservation**: Preserved the public synchronous `ModelProvider` signatures (`generate` and `embed`). Prompts are explicitly bound in an immutable `InputResolver` keyed by `(call_id, input_fingerprint)` before invocation. The provider never discovers facts, invents prompts, or reads arbitrary files.
2. **Local Schema Registry & Strict JSON**: Structured generation requires registered object schemas (`C11_assessment`). `parse_strict_json` strictly rejects duplicate keys, non-finite numbers (NaN/Inf), markdown fences, surrounding prose, and non-object top levels. Validation forbids extra or missing fields without type coercion.
3. **Audit Correlation for Both Outcomes**: Logical call records join requested settings, effective options, observed model/digest provenance, prompt/schema versions, canonical input fingerprint, start/end timestamps, duration, usage, and physical attempt records. Embedding callers receive a safe `call_id` on both success (`EmbeddingResponse.call_id`) and failure (`ClassifiedError.details["call_id"]`).
4. **Serialized Inference Gate**: A shared instance-level lock (`threading.Lock`) serializes generation and embedding calls, bounding queue wait within the overall deadline.
5. **Unified Bounded Attempt Control**: All attempts (transient service retries and at most 1 optional malformed-output regeneration) share a single total transport-attempt cap and overall deadline.
6. **No Silent Rejections**: Model runtime errors (service outage, context overflow, malformed JSON) surface distinctly as `ClassifiedError` and never become candidate rejections. Downstream assessors leave jobs in review/pending.

---

## 5. Verification Commands and Test Results

### Automated Unit and Integration Suite
Executed from repo root on native Windows PowerShell:
```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests\models
```
Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0
rootdir: C:\Users\mrite\Projects\job-search
configfile: pyproject.toml
testpaths: tests
plugins: cov-6.3.0
collected 102 items

tests\models\test_audit.py ..                                            [  1%]
tests\models\test_configuration.py .................                     [ 18%]
tests\models\test_consumer_boundary.py ...                               [ 21%]
tests\models\test_context_budget.py ....                                 [ 25%]
tests\models\test_contract_boundary.py ....                              [ 29%]
tests\models\test_deadlines.py ..                                        [ 31%]
tests\models\test_embedding_metadata.py ..                               [ 33%]
tests\models\test_embeddings.py ......                                   [ 39%]
tests\models\test_error_classification.py .............                  [ 51%]
tests\models\test_fingerprints.py ....                                   [ 55%]
tests\models\test_generation.py .                                        [ 56%]
tests\models\test_generation_metadata.py ..                              [ 58%]
tests\models\test_inputs.py ..                                           [ 60%]
tests\models\test_local_transport.py ....                                [ 64%]
tests\models\test_malformed_output.py ...                                [ 67%]
tests\models\test_provider_integration.py .                              [ 68%]
tests\models\test_retries.py ...                                         [ 71%]
tests\models\test_safe_diagnostics.py ....                               [ 75%]
tests\models\test_schema_validation.py ........                          [ 83%]
tests\models\test_serialization.py ..                                    [ 85%]
tests\models\test_settings.py ............                               [ 97%]
tests\models\test_untrusted_input.py ..                                  [ 99%]
tests\models\test_windows_paths.py .                                     [100%]

============================= 102 passed in 1.26s =============================
```

### Full Repository Regression Run
```powershell
& ".\.venv\Scripts\python.exe" -m pytest
```
Output:
```text
============================ 788 passed in 18.77s =============================
```

### Native Windows Configuration Check
```powershell
& ".\.venv\Scripts\python.exe" -m job_automation config check --config ".\config\app.example.json" --data-root "$env:LOCALAPPDATA\Job Automation Prüfung ä"
```
Output:
```text
Configuration check: VALID
  App Name:          JobAutomation
  Schema Version:    1.0
  Timezone:          Europe/Berlin
  Model Service:     http://127.0.0.1:11434
  Data Root:         C:\Users\mrite\AppData\Local\Job Automation Prüfung ä
  Profiles Path:     C:\Users\mrite\AppData\Local\Job Automation Prüfung ä\profiles
  Raw Snapshots:     C:\Users\mrite\AppData\Local\Job Automation Prüfung ä\raw
  Database Path:     C:\Users\mrite\AppData\Local\Job Automation Prüfung ä\database\job_automation.db
  Artifacts Path:    C:\Users\mrite\AppData\Local\Job Automation Prüfung ä\artifacts
  Logs Path:         C:\Users\mrite\AppData\Local\Job Automation Prüfung ä\logs
  Backups Path:      C:\Users\mrite\AppData\Local\Job Automation Prüfung ä\backups
  Policy Reference:  C:\Users\mrite\Projects\job-search\config\policy.example.json
  Source Registry:   C:\Users\mrite\Projects\job-search\config\sources.example.json
```

### Live Smoke Test Probe (MODEL-01 Readiness Gate)
```powershell
& ".\.venv\Scripts\python.exe" tests\manual\model_smoke.py
```
Output:
```text
============================================================
LLM-01 Local Model Client Smoke Test Runner
============================================================
Target Service URL:     http://127.0.0.1:11434
MODEL-01 Documentation: PENDING / NOT CONFIGURED

[STATUS: LIVE VERIFICATION PENDING]
  Reason: Local model runtime is not reachable at http://127.0.0.1:11434
  MODEL-01 installation and native service startup are prerequisites for live testing.
  Offline verification (contract, budget, retry, transport, privacy tests) is complete.
```

---

## 6. Known Limitations and Pending Work

1. **MODEL-01 Dependency**: Live verification against physical local models (Ollama runtime, weights installation, and GPU placement) is pending MODEL-01.
2. **MODEL-02 Benchmarking**: Concrete model selection, context limit calibration, and latency/VRAM benchmarking are owned by MODEL-02 and are not configured here.
3. **Consumer Integration**: Domain prompt engineering, evidence retrieval, and assessment logic remain with CONTEXT-01..04, MATCH-02, and GEN-03.
4. **Single-Process Gate**: The provider inference gate serializes calls within an application process instance. Cross-process concurrency control remains with RUN-01.

---

## 7. Guidance for Dependent Components

- **MODEL-02 (Benchmarking)**: Use `LocalModelProvider` with `InMemoryAuditRecorder` to measure latency, attempt counts, and actual `TokenUsage` across candidate local models.
- **CONTEXT-03 (RAG Index)**: Use `provider.embed(texts, model)` to generate vectors. Inspect `EmbeddingResponse.dimension` and `model_digest` to ensure index reproducibility and prevent mixing vectors from incompatible models.
- **MATCH-02 (LLM Assessment)**: Bind candidate context and job requirements into `InMemoryInputResolver` using `compute_generation_fingerprint`. When `generate` returns an error (`TRANSIENT_SERVICE`, `CONTEXT_BUDGET`, `MODEL_OUTPUT`), map the job disposition to `review` rather than `rejected`.
- **GEN-03 (Draft Content Generation)**: Register C14 generation schemas in `LocalSchemaRegistry` and bind structured generation prompts.

