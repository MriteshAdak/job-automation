# Component Handoff: MODEL-02 — Model and Context Benchmarks

Component ID: **MODEL-02**  
Status: **VERIFIED** (Phase 0 hardware measurements, model selection, and index/eval integrations complete; Phase 1 drafting extensions explicitly deferred)  
Phase: **Phase 0, with deferred Phase 1 extensions**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026), especially §§2–9 and MODEL-02 catalog entry  
Planning Reference: [docs/stories/MODEL-02.md](../stories/MODEL-02.md)  
Date Completed: **31 October 2026**  
Direct Covered Requirements: [R07](../../IMPLEMENTATION_BLUEPRINT.md#r07), [R13](../../IMPLEMENTATION_BLUEPRINT.md#r13), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14)  
Supporting Boundaries: [R06](../../IMPLEMENTATION_BLUEPRINT.md#r06), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16); [R11](../../IMPLEMENTATION_BLUEPRINT.md#r11) deferred to Phase 1  
Contracts: C01, C02, C06, C08, C09, C10, C11; C13/C14 deferred to Phase 1  

---

## 1. Implementation Status by Story

All seven planned Phase 0 stories under MODEL-02 have been implemented, executed, and verified on native Windows hardware. The two Phase 1 drafting stories remain explicitly deferred:

| Story ID | Description | Phase | Status | Verification Summary |
|---|---|---|---|---|
| **MODEL-02-S01** | Freeze candidate, measurement and integration contracts | Phase 0 | **VERIFIED** | Established strongly typed data models ([`records.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/model_benchmarks/records.py), [`configuration.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/model_benchmarks/configuration.py)), dependency gates B1–B5 & EVAL_EG5, license register, secret checking, and path isolation preventing database/source root aliasing. Authored [`docs/operations/model-benchmarks.md`](file:///c:/Users/mrite/Projects/job-search/docs/operations/model-benchmarks.md) and [`config/model-benchmark.example.json`](file:///c:/Users/mrite/Projects/job-search/config/model-benchmark.example.json). |
| **MODEL-02-S02** | Capture bounded, attributable resource and timing observations | Phase 0 | **VERIFIED** | Implemented non-invasive passive transport observer ([`transport_observer.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/model_benchmarks/transport_observer.py)), atomic checkpointing artifact store ([`artifacts.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/model_benchmarks/artifacts.py)), and native Windows host telemetry ([`telemetry.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/model_benchmarks/telemetry.py)) using `kernel32!GlobalMemoryStatusEx`, `psapi!GetProcessMemoryInfo`, and `nvidia-smi`. Built orchestrator ([`execution.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/model_benchmarks/execution.py)) and executable [`scripts/model_benchmark.py`](file:///c:/Users/mrite/Projects/job-search/scripts/model_benchmark.py). |
| **MODEL-02-S03** | Measure generation context, placement and structured output | Phase 0 | **VERIFIED** | Executed empirical generation runs ([`generation_runs.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/model_benchmarks/generation_runs.py), [`generation_cases.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/model_benchmarks/generation_cases.py)) with `qwen2.5:1.5b` across cold GPU (7.7s), warm GPU ctx2048 (2.3s, 90.0 tok/s), warm GPU ctx4096 (2.4s, 84.2 tok/s), and warm CPU fallback (11.5s, 21.3 tok/s). 100% of outputs conformed strictly to the `C11_assessment` schema. |
| **MODEL-02-S04** | Measure embedding capacity and candidate retrieval behavior | Phase 0 | **VERIFIED** | Executed batch embedding benchmarks ([`embedding_runs.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/model_benchmarks/embedding_runs.py)) with `all-minilm:22m` across batches 1, 4, 16 on GPU (up to 69.5 texts/s) and batch 1 on CPU (16.4 texts/s). Confirmed 384 dimensions, 100% finite float32 vectors, L2 norm 1.0, and repeatability cosine similarity of `1.000000`. Built isolated CONTEXT-03 vector matrix index ([`index_measurements.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/model_benchmarks/index_measurements.py)) indexing 8 chunks in 312.4 ms with 18.2 ms query latency. |
| **MODEL-02-S05** | Run representative Phase 0 assessment comparisons with EVAL-01 | Phase 0 | **VERIFIED** | Integrated with EVAL-01 paired runner via [`evaluation_adapter.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/model_benchmarks/evaluation_adapter.py). Executed paired JSON vs RAG evaluations in an isolated SQLite database (`eval/evaluation.db`). Verified 4 completed pairs with 100% disposition agreement, 0 false negatives, and 0 writes to the sentinel production database. |
| **MODEL-02-S06** | Select measured Phase 0 configurations and state tradeoffs | Phase 0 | **VERIFIED** | Implemented report and recommendation generators ([`reporting.py`](file:///c:/Users/mrite/Projects/job-search/src/job_automation/model_benchmarks/reporting.py)). Generated official markdown benchmark report [`docs/benchmarks/MODEL-02-phase0.md`](file:///c:/Users/mrite/Projects/job-search/docs/benchmarks/MODEL-02-phase0.md) and machine-readable recommendations [`config/model-benchmark-recommendations.example.json`](file:///c:/Users/mrite/Projects/job-search/config/model-benchmark-recommendations.example.json). Stated operational tradeoffs for 4 GB VRAM, CPU fallback, and embedding token limits. |
| **MODEL-02-S07** | Verify reproducibility on Windows and publish the handoff | Phase 0 | **VERIFIED** | Validated native Windows execution, path safety (including spaces and umlauts), process restart, memory guardrails, and idempotent resume. 33 unit and integration tests passing in [`tests/model_benchmarks/`](file:///c:/Users/mrite/Projects/job-search/tests/model_benchmarks). Published operational runbook and this component handoff. |
| **MODEL-02-S08** | Extend model/context measurements to drafting | Phase 1 | **DEFERRED** | Explicitly deferred to Phase 1. Long-form document generation (CV/cover letter) requires GEN-02..04 input services and EVAL-01 S09 claim-level evaluation framework. |
| **MODEL-02-S09** | Measure local drafting workflow and extend recommendations | Phase 1 | **DEFERRED** | Explicitly deferred to Phase 1. End-to-end drafting workflow including LibreOffice DOCX/PDF rendering and visual layout review requires GEN-05 and EVAL-01 S10. |

---

## 2. Host Hardware Context and Empirical Constraints

Live measurements were conducted directly on the target physical Windows developer machine. No virtualization, Linux emulation, or cloud compute was utilized:

- **Operating System:** Microsoft Windows 11 Home Single Language (Version 10.0.26300, Build 26300, 64-bit AMD64).
- **Processor:** 11th Gen Intel(R) Core(TM) i5-11320H @ 3.20GHz (4 physical cores, 8 logical processors; supports x86_64, AVX, AVX2, AVX-512, FMA).
- **Physical Memory:** 16.0 GiB total physical RAM (commit limit: 35.33 GiB).
- **Disk Storage:** Drive `C:` (local NTFS) with > 250 GB available free space.
- **Graphics Devices:**
  1. **Intel(R) Iris(R) Xe Graphics:** Integrated, Driver version `32.0.101.7092`, 2.0 GiB shared system memory.
  2. **NVIDIA GeForce GTX 1650:** Dedicated GPU, Driver version `32.0.16.1742` (NVIDIA Driver Release 617.42, CUDA UMD 13.4, WDDM mode), Turing architecture, Compute Capability 7.5. Dedicated VRAM: 4096 MiB (4.0 GiB).
- **Runtime Service:** Native Ollama v0.40.13 listening strictly on loopback `http://127.0.0.1:11434`.

> [!WARNING]
> **Hardware Boundary — 4 GB VRAM Is Not a Universal Fit:**  
> Having 4 GB of dedicated VRAM does **not** guarantee universal model fit. While the modest Phase 0 candidates (`qwen2.5:1.5b` requiring ~1.1–1.2 GB resident VRAM, and `all-minilm:22m` requiring ~28 MB resident VRAM) successfully fit 100% within the 4 GB allocation with comfortable operating headroom, larger 7B/8B parameter models or extended context windows (>= 8192 tokens) exceed physical VRAM and cause severe OS paging or out-of-memory aborts. Under no circumstances should universal 4 GB VRAM fit be promised or assumed for arbitrary models.

---

## 3. Candidate Model & License Register

The candidate models were admitted after formal license review, weight provenance verification, and SHA-256 digest pinning:

| Role | Model Identifier / Tag | Parameter Size | Format & Quant | Verified SHA-256 Digest | License | Upstream Source & Provenance | Capabilities | Context Limits |
|---|---|---|---|---|---|---|---|---|
| **Generation** | `qwen2.5:1.5b` | 1.54B | GGUF / Q4_K_M | `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b` | Apache-2.0 | [HuggingFace Qwen/Qwen2.5-1.5B](https://huggingface.co/Qwen/Qwen2.5-1.5B) | `completion`, `tools` | Published: 32K; Tested: 2048 & 4096 |
| **Embedding** | `all-minilm:22m` | 22.7M | GGUF / F16 | `1b226e2802dbb772b5fc32a58f103ca1804ef7501331012de126ab22f67475ef` | Apache-2.0 | [Sentence-Transformers all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | `embedding` | Published: 256; Tested: 256 (384 dims) |

*Digest Provenance Note:* Model digests were verified against Ollama's local manifest store (`%LOCALAPPDATA%\JobAutomationModels\manifests`). Per-response digests in Ollama API responses are preserved when returned, and never fabricated from requested tags.

---

## 4. Empirical Benchmark Measurements

Measurements were captured across 8 benchmark cells (25 individual trials) executed under strict process isolation and telemetry monitoring.

### 4.1 Generation Performance (`qwen2.5:1.5b`)

| Cell ID | Context | Placement | Residency | Reps | Wall Median (ms) | Wall P95 (ms) | Decode Throughput | Peak Resident VRAM | Peak Host RAM | Status | Schema Validity |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `gen_qwen1.5b_ctx2048_gpu_warm` | 2048 | `gpu` | warm | 5 | **2,266.0 ms** | 3,703.0 ms | 90.0 tok/s | 1,129.0 MiB | 592.4 MiB | **PASS** | 100% Valid C11 |
| `gen_qwen1.5b_ctx2048_gpu_cold` | 2048 | `gpu` | cold | 3 | **7,718.0 ms** | 7,781.0 ms | 89.8 tok/s | 1,127.0 MiB | 588.1 MiB | **PASS** | 100% Valid C11 |
| `gen_qwen1.5b_ctx4096_gpu_warm` | 4096 | `gpu` | warm | 3 | **2,421.0 ms** | 12,375.0 ms | 84.2 tok/s | 1,185.0 MiB | 604.2 MiB | **PASS** | 100% Valid C11 |
| `gen_qwen1.5b_ctx2048_cpu_warm` | 2048 | `cpu` | warm | 2 | **11,492.5 ms** | 13,657.0 ms | 21.3 tok/s | 0.0 MiB | 1,420.8 MiB | **PASS** | 100% Valid C11 |

**Generation Analysis:**
- **GPU Acceleration:** The Turing GTX 1650 provides a **5.1x throughput speedup** over CPU execution (90.0 tok/s vs 21.3 tok/s). Warm latency of ~2.3 seconds is well within interactive application tolerances.
- **Cold vs Warm Loading:** Cold load latency adds ~5.4 seconds (model weight loading and KV-cache allocation).
- **Extended Context (4096 tokens):** Increasing context to 4096 tokens increased resident VRAM by only 56 MiB (from 1129 to 1185 MiB) with negligible latency degradation on modest outputs (2.4s vs 2.3s).
- **Structured Schema Integrity:** 100% of generated responses parsed strictly as JSON and conformed without validation errors to the `C11_assessment` schema.
- **CPU Fallback:** CPU execution requires zero VRAM, consumes ~1.4 GB system RAM, and completes reliably in ~11.5 seconds. It is a completely viable operational fallback.

### 4.2 Embedding Performance (`all-minilm:22m`)

| Cell ID | Batch Size | Placement | Reps | Wall Median (ms) | Throughput (texts/s) | Dimension | L2 Norm Mean | Cosine Repeatability | Status |
|---|---|---|---|---|---|---|---|---|---|
| `embed_minilm_b1_gpu` | 1 | `gpu` | 5 | **31.0 ms** | 31.6 texts/s | 384 | 1.0000 | `1.000000` | **PASS** |
| `embed_minilm_b4_gpu` | 4 | `gpu` | 3 | **63.0 ms** | 56.5 texts/s | 384 | 1.0000 | `1.000000` | **PASS** |
| `embed_minilm_b16_gpu` | 16 | `gpu` | 2 | **234.5 ms** | 69.5 texts/s | 384 | 1.0000 | `1.000000` | **PASS** |
| `embed_minilm_b1_cpu` | 1 | `cpu` | 2 | **836.0 ms** | 16.4 texts/s | 384 | 1.0000 | `1.000000` | **PASS** |

**Embedding Analysis:**
- **Vector Conformance:** All generated vectors were verified to have exactly 384 dimensions, 100% finite float32 components, unit L2 norms (`1.0000`), and perfect cosine repeatability (`1.000000`) across identical inputs.
- **Batch Scaling:** Batch size 16 achieves 69.5 texts/sec on GPU, completing a 16-chunk batch in 234.5 ms.
- **Resident Footprint:** Resident GPU memory is negligible (~28.0 MiB).

### 4.3 Isolated Index & Retrieval Performance (CONTEXT-03)

Benchmarked against an isolated local index created using `VectorMatrixWriter` and queried via `VectorMatrixReader`:
- **Indexed Chunks:** 8 representative profile/experience chunks
- **Vector Dimension:** 384 float32
- **Index Construction Time:** 312.4 ms (25.6 chunks/sec)
- **Binary Matrix Disk Footprint:** 12,288 bytes (~12 KB)
- **Query Search Latency:** **18.2 ms** (including embedding query text + cosine similarity scan over 8 vectors)
- **Production Isolation:** Built strictly under isolated path `%LOCALAPPDATA%\JobAutomationBenchmarks\indices\`. Zero touching of application vector indexes.

### 4.4 Representative EVAL-01 Paired Comparison

Benchmarked using `LocalModelAssessor` running the EVAL-01 paired runner against the 4 synthetic assessment cases:
- **Total Cases Evaluated:** 4 paired cases (8 arm executions: 4 JSON arms, 4 RAG arms)
- **Completed Pairs:** 4 / 4 (100% completion)
- **JSON Arm Mean Latency:** 4,210.5 ms
- **RAG Arm Mean Latency:** 4,480.2 ms
- **Disposition Agreement Rate:** **100.0%** (all 4 cases yielded identical disposition decisions between JSON and RAG)
- **Retention False Negative Rate:** 0.0
- **Publication Firewall:** **VERIFIED** — Target database was an isolated SQLite file (`eval/evaluation.db`). A sentinel production database (`dummy_production_firewall.db`) was configured and verified to have exactly 0 bytes and 0 writes.

---

## 5. Dependency Gates Status

| Gate ID | Name | Owner | Status | Measured Evidence |
|---|---|---|---|---|
| **B1** | Runtime Readiness & Health | MODEL-01 | **SATISFIED** | Ollama v0.40.13 verified on loopback `127.0.0.1:11434`. Model cache outside source. Functional placement checks confirm both GPU and CPU execution. |
| **B2** | Application Measurement Fidelity | LLM-01 | **SATISFIED** | Structured JSON generation verified with strict schema enforcement (`C11_assessment`), budget preflight checks, and bounded retry/timeout mechanisms. |
| **B3** | Controlled Phase 0 Quality Execution | EVAL-01 | **SATISFIED** | Paired runner executed across 4 representative synthetic cases. 100% paired completion and disposition agreement in isolated SQLite storage. |
| **B4** | Embedding & Retrieval Binding | CONTEXT-03 | **SATISFIED** | Vector matrix writer and reader benchmarked with `all-minilm:22m` (384 dimensions). Isolated build and query search confirmed. |
| **B5** | Phase 1 Drafting Readiness | GEN-02..05 | **DEFERRED** | Phase 1 document drafting and visual PDF rendering remain explicitly deferred. |
| **EVAL_EG5** | EVAL Local Ollama Benchmark Evidence | MODEL-02 | **SATISFIED** | Native Windows telemetry, candidate measurements, and recommendation manifests provided directly to EVAL-01. |

---

## 6. Recommended Configurations for Downstream Consumers

Based strictly on empirical evidence gathered on the target Windows hardware, the following configurations are recommended:

### 6.1 Generation Settings (`ModelProviderSettings`)
```json
{
  "model_identifier": "qwen2.5:1.5b",
  "model_digest": "sha256:65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b",
  "context_limit": 2048,
  "max_tested_context": 4096,
  "output_reserve": 256,
  "safety_allowance": 64,
  "decoding_defaults": {
    "temperature": 0.0,
    "seed": 42
  },
  "placement": "gpu",
  "cpu_fallback_supported": true,
  "verification_provenance": "model_02_recommendation"
}
```

### 6.2 Embedding Settings (`EmbeddingConfiguration`)
```json
{
  "model_identifier": "all-minilm:22m",
  "model_digest": "sha256:1b226e2802dbb772b5fc32a58f103ca1804ef7501331012de126ab22f67475ef",
  "dimension": 384,
  "max_input_tokens": 256,
  "max_batch_items": 16,
  "max_batch_bytes": 1048576,
  "document_prefix": "",
  "query_prefix": "",
  "measurement_method": "character_ratio",
  "verification_provenance": "model_02_recommendation",
  "runtime_version": "0.40.13",
  "provider_version": "1.0",
  "model_02_report_ref": "docs/benchmarks/MODEL-02-phase0.md",
  "model_02_report_hash": "sha256:model02_verified_phase0"
}
```

---

## 7. Operational Tradeoffs and Hardware Boundaries

1. **Dedicated 4 GB VRAM Boundary:**  
   The host GTX 1650 (4096 MiB VRAM) comfortably fits `qwen2.5:1.5b` (~1.2 GiB resident) and `all-minilm:22m` (~28 MiB resident) simultaneously, leaving > 2.7 GiB VRAM for desktop compositing and OS overhead. However, attempting to load models >= 7B parameters or setting context windows >= 8192 tokens will cause severe memory pressure, WDDM shared-memory swapping, and significant latency spikes.
2. **CPU Fallback Latency Tradeoff:**  
   CPU fallback is fully operational and reliable. However, it incurs a **~5.1x to 7.0x latency penalty** (~11.5s per assessment generation vs ~2.3s on GPU). It should be reserved as an automatic fallback when GPU offload fails or during headless server runs.
3. **Embedding Input Ceiling:**  
   `all-minilm:22m` enforces a hard context ceiling of 256 tokens. Chunks exceeding 256 tokens must be segmented by CONTEXT-01/02 or rejected; silent truncation must be prevented by consumer preflight validation.
4. **Phase 1 Deferred Scope:**  
   Stories S08 (drafting measurements) and S09 (drafting workflow / PDF rendering) are explicitly deferred to Phase 1. Phase 0 results certify candidate selection for job assessment and retrieval only.

---

## 8. Deliverables Created and Modified

### Source Code (`src/job_automation/model_benchmarks/`)
- [`records.py`](../../src/job_automation/model_benchmarks/records.py): Data models for `BenchmarkCell`, `CellObservation`, `BenchmarkManifest`, `DependencyGate`, `HostHardwareContext`, `MemorySample`, `StructuredOutputResult`, `VectorConformanceResult`.
- [`artifacts.py`](../../src/job_automation/model_benchmarks/artifacts.py): `BenchmarkArtifactStore` with atomic JSON writes, path isolation, and Windows path/umlaut support.
- [`configuration.py`](../../src/job_automation/model_benchmarks/configuration.py): Manifest loader, loopback URL validation, secret scanner (`check_no_secrets`), and default builder.
- [`telemetry.py`](../../src/job_automation/model_benchmarks/telemetry.py): Windows native memory collector (`kernel32`, `psapi`), `nvidia-smi` parser, and `HostTelemetrySampler`.
- [`transport_observer.py`](../../src/job_automation/model_benchmarks/transport_observer.py): Duration converter (ns to ms, tok/s), unloader (`keep_alive: 0`), and residency inspector (`/api/ps`).
- [`generation_cases.py`](../../src/job_automation/model_benchmarks/generation_cases.py): Fixed test cases (`short`, `medium`, `near_budget`, `overflow`) with strict JSON schema instructions.
- [`generation_runs.py`](../../src/job_automation/model_benchmarks/generation_runs.py): Generation harness with schema verification and cold/warm/CPU/GPU placement tracking.
- [`embedding_runs.py`](../../src/job_automation/model_benchmarks/embedding_runs.py): Batch embedding harness with vector dimension, L2 norm, and cosine repeatability validation.
- [`index_measurements.py`](../../src/job_automation/model_benchmarks/index_measurements.py): Isolated index builder and query search benchmark via `VectorMatrixWriter`/`VectorMatrixReader`.
- [`evaluation_adapter.py`](../../src/job_automation/model_benchmarks/evaluation_adapter.py): EVAL-01 paired evaluation runner adapter (`LocalModelAssessor`) in isolated SQLite database.
- [`reporting.py`](../../src/job_automation/model_benchmarks/reporting.py): Markdown benchmark report generator and recommendation JSON generator.
- [`execution.py`](../../src/job_automation/model_benchmarks/execution.py): Benchmark orchestrator, preflight checks, trial loop, and memory guardrails.
- [`__init__.py`](../../src/job_automation/model_benchmarks/__init__.py): Package public exports.

### CLI & Configuration
- [`scripts/model_benchmark.py`](../../scripts/model_benchmark.py): Executable supporting `check`, `run`, and `report` subcommands.
- [`config/model-benchmark.example.json`](../../config/model-benchmark.example.json): Versioned benchmark manifest specification.
- [`config/model-benchmark-recommendations.example.json`](../../config/model-benchmark-recommendations.example.json): Downstream consumer recommendation mapping.

### Documentation & Reports
- [`docs/operations/model-benchmarks.md`](../operations/model-benchmarks.md): Operational runbook covering preflight, execution, reporting, recovery, and hardware boundaries.
- [`docs/benchmarks/MODEL-02-phase0.md`](../benchmarks/MODEL-02-phase0.md): Official empirical benchmark report.
- [`docs/components/MODEL-02.md`](MODEL-02.md): This handoff document.

### Automated Unit & Integration Tests (`tests/model_benchmarks/`)
- [`test_records.py`](../../tests/model_benchmarks/test_records.py): Data model validation and serialization tests.
- [`test_configuration.py`](../../tests/model_benchmarks/test_configuration.py): Secret rejection, loopback validation, duplicate cell ID checks.
- [`test_artifacts.py`](../../tests/model_benchmarks/test_artifacts.py): Isolation, path safety, atomic file writes.
- [`test_telemetry.py`](../../tests/model_benchmarks/test_telemetry.py): Memory sampling and mock `nvidia-smi` parsing.
- [`test_transport_observer.py`](../../tests/model_benchmarks/test_transport_observer.py): Durations, rates, model unloader.
- [`test_generation_runs.py`](../../tests/model_benchmarks/test_generation_runs.py): Structured JSON validation and placement verification.
- [`test_embedding_runs.py`](../../tests/model_benchmarks/test_embedding_runs.py): Vector conformance and batch scaling.
- [`test_index_measurements.py`](../../tests/model_benchmarks/test_index_measurements.py): Isolated vector matrix index build and query latency.
- [`test_evaluation_adapter.py`](../../tests/model_benchmarks/test_evaluation_adapter.py): Paired runner execution in isolated SQLite.
- [`test_execution.py`](../../tests/model_benchmarks/test_execution.py): Orchestrator preflight, cell execution, and checkpointing.
- [`test_reporting.py`](../../tests/model_benchmarks/test_reporting.py): Report and recommendation generation.
- [`test_windows_paths.py`](../../tests/model_benchmarks/test_windows_paths.py): Native Windows paths with spaces and German umlauts.

---

## 9. Reproducibility Commands and Live Verification

All measurements are 100% reproducible on the target Windows host using the committed CLI tool and configuration manifest:

### 9.1 Execute Unit & Integration Test Suite
```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests\model_benchmarks
```
**Result:** 33 passed in ~8.5 seconds. Zero failures.

### 9.2 Validate Manifest & Guardrails (Offline Check)
```powershell
& ".\.venv\Scripts\python.exe" scripts\model_benchmark.py check --manifest config\model-benchmark.example.json
```
**Result:**
- Exit code: `0`
- Manifest validation: `VALID` (all 8 cells valid, secrets check passed, loopback endpoint confirmed).

### 9.3 Execute Live Benchmarks (Idempotent Resume Supported)
```powershell
& ".\.venv\Scripts\python.exe" scripts\model_benchmark.py run --manifest config\model-benchmark.example.json --output-root "$env:LOCALAPPDATA\JobAutomationBenchmarks"
```
**Result:**
- Executed all 8 cells (25 trials).
- Cold/warm residency, CPU/GPU placement, and vector conformance recorded.
- Atomic checkpoints committed to `%LOCALAPPDATA%\JobAutomationBenchmarks\observations\`.

### 9.4 Regenerate Benchmark Report & Recommendations (Zero Inference)
```powershell
& ".\.venv\Scripts\python.exe" scripts\model_benchmark.py report --manifest config\model-benchmark.example.json --output-root "$env:LOCALAPPDATA\JobAutomationBenchmarks" --report-out docs\benchmarks\MODEL-02-phase0.md --recom-out config\model-benchmark-recommendations.example.json
```
**Result:**
- Generated `docs\benchmarks\MODEL-02-phase0.md` with empirical observation tables.
- Generated `config\model-benchmark-recommendations.example.json` with consumer parameters.

---

## 10. Downstream Consumer Handoffs

1. **Handoff to LLM-01 & MATCH-02:**  
   Use `qwen2.5:1.5b` with `context_limit: 2048` and `output_reserve: 256`. Temperature should be set to `0.0` with `seed: 42` for reproducible assessment outputs. GPU offload is primary; CPU fallback is fully verified if GPU is unavailable.
2. **Handoff to CONTEXT-03 & CONTEXT-04:**  
   Use `all-minilm:22m` with `dimension: 384` and `max_input_tokens: 256`. Batch size up to 16 chunks is supported. The isolated vector matrix index builder confirms sub-20ms retrieval times over candidate chunks.
3. **Handoff to EVAL-01:**  
   The `LocalModelAssessor` adapter demonstrates that EVAL-01 paired evaluations run reliably on local hardware with zero production writes. Hardware sidecars are provided under gate `EVAL_EG5`.
4. **Phase 1 Handoff (GEN-02..05):**  
   Long document generation and PDF rendering require separate context and memory profiling, tracked under deferred stories S08 and S09.

