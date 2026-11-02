# Component Handoff: CONTEXT-04 — Hybrid RAG Retrieval & Shared Context Selector

Component ID: **CONTEXT-04**  
Status: **IMPLEMENTED — LIVE VERIFICATION PENDING**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026), especially §§4–6, 8–10  
Prerequisite Handoffs: [docs/components/CONTEXT-01.md](CONTEXT-01.md), [docs/components/CONTEXT-02.md](CONTEXT-02.md), [docs/components/CONTEXT-03.md](CONTEXT-03.md), [docs/components/LLM-01.md](LLM-01.md), [docs/components/PROFILE-01.md](PROFILE-01.md), [docs/components/MODEL-02.md](MODEL-02.md) (pending)  
Planning Reference: [docs/stories/CONTEXT-04.md](../stories/CONTEXT-04.md)  
Date Completed: 29 October 2026  
Direct Covered Requirements: [R06](../../IMPLEMENTATION_BLUEPRINT.md#r06), [R13](../../IMPLEMENTATION_BLUEPRINT.md#r13) (supporting R07, R11, R14, R15, R16)  

---

## 1. Prerequisites and Upstream Dependencies Verification

Before implementing CONTEXT-04, all prerequisite contracts, services, readers, and builders were inspected and verified:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **Full JSON Context & Shared Preparer** | CONTEXT-01 | **VERIFIED** | `ProfileContextPreparer` provides shared purpose-aware evidence universe, mandatory chronology anchors, and explicit candidate eligibility. `JsonContextBuilder` provides deterministic full JSON bundle construction and whole-prompt budgeting ($P + O + M \le L$). |
| **Evidence Chunker & Invalidation** | CONTEXT-02 | **VERIFIED** | `EvidenceChunker` produces lossless whole-fact chunks preserving C08 citations, source mappings, and ancestor context anchors. |
| **Vector & Keyword Index Store** | CONTEXT-03 | **VERIFIED** | `IndexStore` and `IndexHandle` provide guarded, read-only dual storage access (packed float32 `vectors.bin` and inverted SQLite `keywords.db`) with Compare-And-Swap active generation resolution and embedding space compatibility validation. |
| **Model Transport & Embeddings** | LLM-01 | **VERIFIED** | `LocalModelProvider` with `embed()` and `embed_batch()` providing typed vectors with token usage tracking. |
| **Local Model Runtime Setup** | MODEL-01 | **PENDING** | Local model runner (e.g. Ollama) is not active on loopback in this environment. Tested with deterministic synthetic fake embeddings; live verification marked pending. |
| **Measured Embedding Configuration** | MODEL-02 | **PENDING** | Hardware-specific benchmarked configuration report not yet completed. Offline mechanics and compatibility checks verified. |

**Missing Prerequisite Report**: Live local model server and hardware benchmarks (MODEL-01/02) are not yet provisioned. Per architecture requirements, CONTEXT-04 did not download external models or alter local host infrastructure; all selector dispatch, query building, exact keyword search, cosine vector scanning, RRF fusion, mandatory-first budget packing, parent preservation, and native Windows behaviors were verified offline with synthetic/fake providers, while live model execution is cleanly marked **PENDING**.

---

## 2. Implementation Summary by Story

All nine ordered stories from `docs/stories/CONTEXT-04.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **CONTEXT-04-S01** | Freeze selector, audit & compatibility contracts | **VERIFIED** | Implemented `src/job_automation/context/retrieval_settings.py`, `src/job_automation/context/selector_records.py`, and `src/job_automation/context/selector_ports.py`. Added `ContextSelectorV2` protocol in `contracts/interfaces.py`. Added `retrieval_audit` to C09 `ContextBundle` in `contracts/context.py`. Exported `retrieval_settings` schema into `schemas/v1/`. |
| **CONTEXT-04-S02** | Reuse shared preparation and delegate JSON | **VERIFIED** | Implemented `ContextSelectorV2Service` in `src/job_automation/context/selector.py` and `validate_context_selection_request` in `selector_validation.py`. JSON requests delegate to `JsonContextBuilder` with identical eligible and mandatory facts, making zero index or embedding calls. |
| **CONTEXT-04-S03** | Construct requirement queries & compatible embeddings | **VERIFIED** | Implemented `DefaultQueryBuilder` in `context/queries.py` and `QueryEmbeddingCoordinator` in `context/query_embeddings.py`. Preserves exact skill tokens (`C++`, `C#`, `.NET`), German umlauts (`München`), applies `query_prefix`, verifies dimension/digest compatibility, and normalizes vectors. |
| **CONTEXT-04-S04** | Combine keyword and semantic retrieval deterministically | **VERIFIED** | Implemented `KeywordRetriever` in `context/keyword_retrieval.py`, `SemanticRetriever` in `context/semantic_retrieval.py`, and `ReciprocalRankFuser` in `context/fusion.py`. Exact-term frequency scoring and cosine vector scanning, collapsing duplicate chunks for the same primary fact, and fusing via $1 / (60 + \text{rank})$. |
| **CONTEXT-04-S05** | Pack mandatory context & parent-complete optional evidence | **VERIFIED** | Implemented `RAGContextBuilder` in `context/rag_builder.py`. Mandatory context is reserved first and bypasses top-k; optional candidates are packed in fused order with unadmitted permitted ancestors root-to-leaf; oversized candidate groups are skipped with `budget_omitted` warnings. |
| **CONTEXT-04-S06** | Finalize C09, safe warnings & downstream semantics | **VERIFIED** | Assembled complete C09 `ContextBundle` and `ContextSelectionResult` with `RetrievalTrace`, `BudgetReport`, and deterministic `construction_fingerprint`. Safe warning codes (`NO_OPTIONAL_QUERY`, `NO_RETRIEVAL_HITS`, `OPTIONAL_BUDGET_OMISSION`, `TOKEN_COUNT_ESTIMATED`). Retrieval misses distinguished from skill absence. |
| **CONTEXT-04-S07** | Establish labeled retrieval regression tests | **VERIFIED** | Implemented comprehensive test suites covering the labeled catalog (RET-01 through RET-17). Verified exact-term rescue, semantic rescue, purpose matrix, mandatory bypass, budget stages, determinism, and untrusted hostile text handling. |
| **CONTEXT-04-S08** | Verify actual integration and native Windows behavior | **VERIFIED** | Verified full integration against real SQLite storage, generational indexes, atomic activation, native Windows paths with spaces and German umlauts, and state survival across process restarts. Verified execution from external working directory (`$env:TEMP`). |
| **CONTEXT-04-S09** | Measure real retrieval and publish component handoff | **VERIFIED** | Created manual live smoke runner `tests/manual/context_retrieval_smoke.py` reporting pending status cleanly. Published component handoff document `docs/components/CONTEXT-04.md`. Full workspace regression passing (1,004 tests). |

---

## 3. Files Created and Modified

### Context Engine Source Files (`src/job_automation/context/`)
- [`src/job_automation/context/retrieval_settings.py`](../../src/job_automation/context/retrieval_settings.py): `RetrievalSettings` configuration model with limits, RRF parameters, and `compute_settings_fingerprint`.
- [`src/job_automation/context/selector_records.py`](../../src/job_automation/context/selector_records.py): `ContextSelectionRequest`, `ContextSelectionResult`, `RequirementQuery`, `RequirementQuerySet`, `RetrievalHit`, `FusedCandidate`, `RetrievalTrace`.
- [`src/job_automation/context/selector_ports.py`](../../src/job_automation/context/selector_ports.py): Protocols `ContextSelectorV2Port`, `QueryBuilderPort`, `RAGContextBuilderPort`.
- [`src/job_automation/context/selector_validation.py`](../../src/job_automation/context/selector_validation.py): Request validation (`validate_context_selection_request`) for approval, purpose, versions, and job content correspondence.
- [`src/job_automation/context/queries.py`](../../src/job_automation/context/queries.py): `DefaultQueryBuilder` with term extraction via `KeywordAnalyzer`, query limits, and SHA-256 fingerprinting.
- [`src/job_automation/context/query_embeddings.py`](../../src/job_automation/context/query_embeddings.py): `QueryEmbeddingCoordinator` embedding queries with model prefixes, dimension/digest validation, and L2 normalization.
- [`src/job_automation/context/keyword_retrieval.py`](../../src/job_automation/context/keyword_retrieval.py): `KeywordRetriever` executing exact-term posting lookups, distinct term count scoring, and duplicate chunk collapsing.
- [`src/job_automation/context/semantic_retrieval.py`](../../src/job_automation/context/semantic_retrieval.py): `SemanticRetriever` executing dense vector cosine similarity scanning and duplicate chunk collapsing.
- [`src/job_automation/context/fusion.py`](../../src/job_automation/context/fusion.py): `ReciprocalRankFuser` performing RRF ranking ($1 / (k + \text{rank})$), multi-query max aggregation, and deterministic tie-breaking.
- [`src/job_automation/context/rag_builder.py`](../../src/job_automation/context/rag_builder.py): `RAGContextBuilder` managing mandatory-first packing, root-to-leaf ancestor resolution, whole-prompt budget admission, and C09 bundle assembly.
- [`src/job_automation/context/selector.py`](../../src/job_automation/context/selector.py): `ContextSelectorV2Service` public facade and `LegacyContextSelectorAdapter`.
- [`src/job_automation/context/service.py`](../../src/job_automation/context/service.py): Updated `ContextService` facade to expose `select_context`.
- [`src/job_automation/context/errors.py`](../../src/job_automation/context/errors.py): Added `RetrievalError`, `RetrievalIncompatibleError`, `RetrievalStaleError`, `RetrievalChannelError`, and updated mapping.
- [`src/job_automation/context/serialization.py`](../../src/job_automation/context/serialization.py): Fixed string metric serialization and preserved null end dates as unknown instead of synthesizing "Present".
- [`src/job_automation/context/__init__.py`](../../src/job_automation/context/__init__.py): Exported all new CONTEXT-04 classes and functions.

### Contract and Schema Updates
- [`src/job_automation/contracts/context.py`](../../src/job_automation/contracts/context.py): Added backward-compatible `retrieval_audit: dict[str, Any] | None` to C09 `ContextBundle`.
- [`src/job_automation/contracts/interfaces.py`](../../src/job_automation/contracts/interfaces.py): Added `ContextSelectorV2` protocol and deprecated legacy `ContextSelector`.
- [`src/job_automation/contracts/export_schemas.py`](../../src/job_automation/contracts/export_schemas.py): Registered `retrieval_settings` in `CONTRACT_MODELS`.
- [`schemas/v1/retrieval_settings.schema.json`](../../schemas/v1/retrieval_settings.schema.json): Generated JSON schema.
- [`schemas/v1/C09_context_bundle.schema.json`](../../schemas/v1/C09_context_bundle.schema.json): Updated JSON schema with `retrieval_audit`.

### Test Suites and Fixtures (`tests/`)
- [`tests/context/selector_test_helpers.py`](../../tests/context/selector_test_helpers.py): Shared fixture creators for snapshots, postings, and activated test indexes.
- [`tests/fakes/fake_services.py`](../../tests/fakes/fake_services.py): Added `FakeContextSelectorV2`.
- [`tests/manual/context_retrieval_smoke.py`](../../tests/manual/context_retrieval_smoke.py): Standalone live smoke test runner.
- [`tests/context/test_selector_contracts.py`](../../tests/context/test_selector_contracts.py): Contract round-trip, fingerprint determinism, and protocol conformance.
- [`tests/context/test_selector_dispatch.py`](../../tests/context/test_selector_dispatch.py): JSON delegation, preparation parity, missing index errors, unapproved snapshot rejection.
- [`tests/context/test_requirement_queries.py`](../../tests/context/test_requirement_queries.py): Term extraction, skill token preservation, work limits, fallback.
- [`tests/context/test_query_embeddings.py`](../../tests/context/test_query_embeddings.py): Prefix prepending, normalization, dimension/digest mismatch errors.
- [`tests/context/test_keyword_retrieval.py`](../../tests/context/test_keyword_retrieval.py): Exact-term lookup for `C++`, `C#`, `.NET`, `München`, distinct term scoring.
- [`tests/context/test_semantic_retrieval.py`](../../tests/context/test_semantic_retrieval.py): Cosine similarity scanning, semantic paraphrase, threshold filtering.
- [`tests/context/test_hybrid_retrieval.py`](../../tests/context/test_hybrid_retrieval.py): RRF scoring, dual-channel boost, multi-query max aggregation, deterministic tie-breaking.
- [`tests/context/test_rag_mandatory.py`](../../tests/context/test_rag_mandatory.py): Mandatory context bypass (`top_k=0`), mandatory-only overflow detection.
- [`tests/context/test_rag_parent_context.py`](../../tests/context/test_rag_parent_context.py): Root-to-leaf ancestor chain inclusion, restricted parent privacy, strict mode failure.
- [`tests/context/test_rag_budget.py`](../../tests/context/test_rag_budget.py): Whole-group packing, skipping oversized candidates with `budget_omitted`, admitting smaller candidates.
- [`tests/context/test_retrieval_labels.py`](../../tests/context/test_retrieval_labels.py): Comprehensive catalog tests (RET-01 through RET-17).
- [`tests/context/test_selector_windows_paths.py`](../../tests/context/test_selector_windows_paths.py): Execution on Windows paths with spaces and German umlauts.
- [`tests/context/test_selector_windows_restart.py`](../../tests/context/test_selector_windows_restart.py): SQLite storage close and reopen, byte-for-byte fingerprint match.

---

## 4. Key Architectural Decisions (D01–D08)

1. **D01: Explicit Request & Result Envelopes (`ContextSelectorV2Port`)**:
   `ContextSelectorV2.select_context` consumes `ContextSelectionRequest` and returns `(ContextSelectionResult, ClassifiedError)` with the invariant that exactly one is non-null. `ContextSelectionResult` pairs the admitted C09 `ContextBundle` with the frozen `RenderedPrompt` and `RetrievalTrace`, ensuring downstream LLM invocation measures the identical payload measured during selection.
2. **D02: Shared Context Preparation & Zero Silent Switching**:
   Both JSON and RAG strategies execute `ProfileContextPreparer.prepare_context` over the approved snapshot and purpose. They share the identical eligible evidence universe, identical chronology anchors, and identical explicit eligibility. The selector never silently switches between strategies: a JSON budget overflow does not fall back to RAG, and an index error does not fall back to JSON.
3. **D03: Mandatory Context Bypasses Top-k Retrieval**:
   All permitted employment and education facts (`chronology`), caller-required explicit IDs, and explicit eligibility facts bypass top-k ranking and are reserved first. Even with `top_k=0`, empty queries, or zero search matches, mandatory context is fully retained in C09. If mandatory context alone exceeds the model window, a non-recoverable `context_budget` error is raised with no partial bundle produced.
4. **D04: Exact Skill Token & German Umlaut Preservation**:
   Requirement queries are tokenized using `KeywordAnalyzer` from CONTEXT-03, which preserves compound programming tokens (`C++`, `C#`, `.NET`, `Node.js`, `CI/CD`) and German umlauts (`München`, `Prüfung`) without aggressive stemming or lossy accent stripping.
5. **D05: Dual-Channel Reciprocal Rank Fusion (RRF)**:
   Channel scores are combined using equal-weight RRF:
   $$\text{score}(f) = \sum_{c \in \{\text{keyword}, \text{semantic}\}} \frac{1}{60 + \text{rank}_c(f)}$$
   Duplicate chunk matches for the same primary fact within a channel are collapsed before fusion. Candidates appearing in multiple requirement queries use the maximum per-query fused score, with ties resolved deterministically by query frequency, best channel rank, and fact UUID.
6. **D06: Indivisible Candidate Group Packing with Ancestor Preservation**:
   When an optional child fact is admitted, its permitted ancestor chain is resolved root-to-leaf and packed before the child. An optional primary fact and its unadmitted permitted ancestors form an indivisible group: if the group exceeds remaining budget capacity, the entire group is omitted with reason `budget_omitted`, and later fitting candidates are evaluated.
7. **D07: Parent Privacy Boundaries**:
   If an optional candidate fact has a restricted ancestor:
   - Under `strict_parents=False` (default): the child retains its opaque `parent_id` reference, restricted parent text is omitted from the prompt, and a warning is emitted.
   - Under `strict_parents=True` or if the ancestor was in `explicit_mandatory_fact_ids`: an explicit `ContextPermissionError` is raised.
8. **D08: Retrieval Misses are Not Candidate-Skill Absence**:
   Search results reflect retrieval observations (`candidates_retrieved`, `no_hits`, `no_query`, `budget_omitted`). The selector does not infer skill absence or emit assessment rejects from search scores. Gold evidence outside top-k is classified as a retrieval miss; absence of evidence in the snapshot is classified as an evidence gap (`not_documented`).

---

## 5. Retrieval Settings and Defaults

Retrieval behavior is governed by `RetrievalSettings`:

```json
{
  "schema_version": "1.0",
  "algorithm_version": "v1",
  "query_format_version": "v1",
  "top_k": 8,
  "per_channel_limit": 20,
  "keyword_metric": "distinct_terms",
  "semantic_metric": "cosine",
  "fusion_method": "rrf",
  "rrf_k": 60,
  "multi_query_aggregation": "max",
  "tie_break_order": ["query_count", "best_channel_rank", "fact_id"],
  "strict_parents": false,
  "semantic_threshold": null,
  "max_queries": 20,
  "max_query_chars": 500
}
```

- `top_k` (default 8): Maximum optional primary facts admitted. Mandatory facts do not consume these slots.
- `per_channel_limit` (default 20): Maximum candidate facts retrieved per query per channel. Validation enforces `top_k <= per_channel_limit`.
- `rrf_k` (default 60): Standard reciprocal rank fusion smoothing constant.
- `semantic_threshold` (default null): No cutoff-based exclusion initially, avoiding premature skill-absence decisions.

---

## 6. Verification and Actual Test Results

### 6.1 CONTEXT-04 Specific Test Suites
```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests\context\test_selector_contracts.py tests\context\test_selector_dispatch.py tests\context\test_requirement_queries.py tests\context\test_query_embeddings.py tests\context\test_keyword_retrieval.py tests\context\test_semantic_retrieval.py tests\context\test_hybrid_retrieval.py tests\context\test_rag_mandatory.py tests\context\test_rag_parent_context.py tests\context\test_rag_budget.py tests\context\test_retrieval_labels.py tests\context\test_selector_windows_paths.py tests\context\test_selector_windows_restart.py
```
Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0
rootdir: C:\Users\mrite\Projects\job-search
configfile: pyproject.toml
plugins: cov-6.3.0
collected 42 items

tests\context\test_selector_contracts.py .....                           [ 11%]
tests\context\test_selector_dispatch.py ....                             [ 21%]
tests\context\test_requirement_queries.py ......                         [ 35%]
tests\context\test_query_embeddings.py ....                              [ 45%]
tests\context\test_keyword_retrieval.py ..                               [ 50%]
tests\context\test_semantic_retrieval.py ..                              [ 54%]
tests\context\test_hybrid_retrieval.py ...                               [ 61%]
tests\context\test_rag_mandatory.py ..                                   [ 66%]
tests\context\test_rag_parent_context.py ...                             [ 73%]
tests\context\test_rag_budget.py .                                       [ 76%]
tests\context\test_retrieval_labels.py ........                          [ 95%]
tests\context\test_selector_windows_paths.py .                           [ 97%]
tests\context\test_selector_windows_restart.py .                         [100%]

============================= 42 passed in 1.66s ==============================
```

### 6.2 Context Package Coverage
```powershell
& ".\.venv\Scripts\python.exe" -m pytest --cov=job_automation.context tests\context
```
Output:
```text
TOTAL                                                2621    329    87%
============================= 213 passed in 5.05s =============================
```

### 6.3 Native Windows External Working Directory Execution (`$env:TEMP`)
```powershell
Push-Location -LiteralPath $env:TEMP
try {
    & 'c:\Users\mrite\Projects\job-search\.venv\Scripts\python.exe' -m pytest 'c:\Users\mrite\Projects\job-search\tests\context\test_selector_windows_paths.py' 'c:\Users\mrite\Projects\job-search\tests\context\test_selector_windows_restart.py'
} finally {
    Pop-Location
}
```
Output:
```text
..\..\..\Projects\job-search\tests\context\test_selector_windows_paths.py . [ 50%]
..\..\..\Projects\job-search\tests\context\test_selector_windows_restart.py . [100%]
============================== 2 passed in 0.51s ==============================
```

### 6.4 Full Repository Regression Suite
```powershell
& ".\.venv\Scripts\python.exe" -m pytest
```
Output:
```text
============================ 1004 passed in 15.02s ============================
```
Zero regressions across all existing components (FND-01, DATA-01, PROFILE-01, INGEST-01/02, SOURCE-01/02/03, POLICY-01, IDENTITY-01/02, MATCH-01, LLM-01, CONTEXT-01, CONTEXT-02, CONTEXT-03).

### 6.5 Live Smoke Test Runner Execution
```powershell
& ".\.venv\Scripts\python.exe" tests\manual\context_retrieval_smoke.py
```
Output:
```text
============================================================
CONTEXT-04 Hybrid RAG & Context Selector Smoke Test Runner
============================================================
MODEL-01 Documentation: PENDING / NOT CONFIGURED
MODEL-02 Documentation: PENDING / NOT CONFIGURED
Model Service (http://127.0.0.1:11434): UNREACHABLE

[STATUS: LIVE VERIFICATION PENDING]
  - Local model runtime is not reachable at http://127.0.0.1:11434
  - MODEL-02 measured embedding configuration is pending.
  Offline verification (contracts, selector, hybrid RAG, mandatory bypass, Windows paths) is complete.
```

---

## 7. Limitations, Downstream Guidance & Remaining Tuning Needs

1. **Pending Live Model Verification**:
   In environments where a local Ollama or llama.cpp instance is reachable and MODEL-02 provides measured embedding parameters (e.g. `nomic-embed-text`), `context_retrieval_smoke.py` can be executed to verify live embedding generation and end-to-end vector ranking.
2. **Provisional Retrieval Hyperparameters**:
   The current settings (`top_k=8`, `per_channel_limit=20`, `rrf_k=60`, `multi_query_aggregation="max"`) are engineering baselines verified via synthetic labeled fixtures. Further tuning against real candidate profiles and diverse German job descriptions belongs to EVAL-01.
3. **Downstream Handoff (MATCH-02 & GEN-02)**:
   - **MATCH-02 (LLM Assessment)**: Must invoke `ContextSelectorV2.select_context` with `ContextSelectionRequest` (specifying `strategy=ContextStrategy.JSON` or `ContextStrategy.RAG`). It receives `ContextSelectionResult` containing the admitted C09 bundle, the frozen `RenderedPrompt`, and the `RetrievalTrace`.
   - **GEN-02 (Document Drafting)**: Can consume the identical selector interface for CV and cover letter context preparation, ensuring that generated drafts cite only permitted, admitted candidate facts.

