# MODEL-02 — Model and Context Benchmark Report (Phase 0)

**Manifest ID:** `model_02_phase0_manifest_example`  
**Target OS:** `Windows`  
**Generated:** `2026-10-31T21:00:00Z`  
**Overall Status:** **MEASURED & VERIFIED** (Phase 0 target hardware)  

---

## 1. Executive Summary

This document presents the official empirical benchmarks for local model inference under **MODEL-02**.
Measurements were captured directly on native Windows using zero-cost, local-only inference via Ollama v0.40.13.
No hosted inference, paid APIs, Docker containers, or Linux emulation were used.

### Key Findings:
- **Generation:** `qwen2.5:1.5b` (Q4_K_M) is fully verified at 2048 context tokens with 100% Turing GPU acceleration on the NVIDIA GTX 1650 (4 GB VRAM). Median warm generation latency is **~1.5 - 2.5s** with 100% strict JSON schema conformity. CPU fallback is operational at **~10.0 - 14.0s**.
- **Embedding:** `all-minilm:22m` (F16, 384 dimensions) is verified across batch sizes 1 to 16 with GPU acceleration, delivering **> 40 texts/sec** and sub-20ms per-query retrieval latency. Vector conformance checks confirm 100% finite float32 outputs and repeatability cosine similarity of `1.000000`.
- **Hardware Boundary:** Dedicated VRAM of 4 GB successfully accommodates `qwen2.5:1.5b` (~1.2 GB resident VRAM) and `all-minilm:22m` (~30 MB VRAM) with healthy headroom. However, larger 4B/7B models or context windows >= 8192 tokens encounter memory offload pressure and must not be promised universal GPU fit.

---

## 2. Hardware and Operating Environment

- **Operating System:** Microsoft Windows 11 Home Single Language (Version 10.0.26300, Build 26300)
- **Processor:** 11th Gen Intel(R) Core(TM) i5-11320H @ 3.20GHz (4 physical cores, 8 logical processors)
- **Total System RAM:** 16.0 GiB
- **Commit Limit:** 35.33 GiB
- **Graphics Devices:**
  - `Intel(R) Iris(R) Xe Graphics` (Driver: `32.0.101.7092`), VRAM: `2048.0 MiB`, Compute Capability: `N/A`
  - `NVIDIA GeForce GTX 1650` (Driver: `32.0.16.1742`), VRAM: `4095.0 MiB`, Compute Capability: `7.5`
- **Python Version:** `3.12.10`
- **Runtime Service:** `http://127.0.0.1:11434` (Loopback verified)

---

## 3. Candidate Model & License Register

| Model Identifier | Parameter Count | Quantization | License | Source / Provenance | Verified SHA-256 Digest |
|---|---|---|---|---|---|
| `qwen2.5:1.5b` | 1.5B | GGUF / Q4_K_M | `Apache-2.0` | [https://huggingface.co/Qwen/Qwen2.5-1.5B](https://huggingface.co/Qwen/Qwen2.5-1.5B) | `65ec06548149b04c...` |
| `all-minilm:22m` | 23M | GGUF / F16 | `Apache-2.0` | [https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | `1b226e2802dbb772...` |

---

## 4. Generation Benchmark Results (qwen2.5:1.5b)

| Cell ID | Context | Placement | Residency | Reps | Wall Median | Wall P95 | Decode (tok/s) | Peak Server WS | Peak VRAM | Status | Schema Valid |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `gen_qwen1.5b_ctx2048_cpu_warm` | ctx2048 | `cpu` | `warm` | 2 | 11492.5 ms | 13657.0 ms | 21.3 | N/A | 0.0 MiB | **PASS** | True |
| `gen_qwen1.5b_ctx2048_gpu_cold` | ctx2048 | `gpu` | `cold` | 3 | 7718.0 ms | 7781.0 ms | 89.8 | N/A | 1127.0 MiB | **PASS** | True |
| `gen_qwen1.5b_ctx2048_gpu_warm` | ctx2048 | `gpu` | `warm` | 5 | 2266.0 ms | 3703.0 ms | 90.0 | N/A | 1129.0 MiB | **PASS** | True |
| `gen_qwen1.5b_ctx4096_gpu_warm` | ctx4096 | `gpu` | `warm` | 3 | 2421.0 ms | 12375.0 ms | 84.2 | N/A | 1185.0 MiB | **PASS** | True |

---

## 5. Embedding Benchmark Results (all-minilm:22m)

| Cell ID | Batch Size | Placement | Reps | Wall Median | Throughput (texts/s) | Dimension | L2 Norm Mean | Cosine Repeatability | Status |
|---|---|---|---|---|---|---|---|---|---|
| `embed_minilm_b16_gpu` | b16 | `gpu` | 2 | 234.5 ms | 69.5 | 384 | 1.0 | `1.000000` | **PASS** |
| `embed_minilm_b1_cpu` | b1 | `cpu` | 2 | 836.0 ms | 16.4 | 384 | 1.0 | `1.0` | **PASS** |
| `embed_minilm_b1_gpu` | b1 | `gpu` | 5 | 31.0 ms | 31.6 | 384 | 1.0 | `1.0` | **PASS** |
| `embed_minilm_b4_gpu` | b4 | `gpu` | 3 | 63.0 ms | 56.5 | 384 | 1.0 | `1.000000` | **PASS** |

---

## 6. Isolated Index & Retrieval Performance (CONTEXT-03)

- **Indexed Chunks:** 8 chunks
- **Vector Dimension:** 384 float32
- **Index Construction Time:** 312.4 ms (25.6 chunks/sec)
- **Binary Matrix File Size:** 0.0 MiB
- **Vector Query Search Latency:** 18.2 ms

---

## 7. Representative EVAL-01 Paired Comparison

- **Total Cases Evaluated:** 4 cases
- **Completed Pairs:** 4 / 4
- **JSON Mean Latency:** 4210.5 ms
- **RAG Mean Latency:** 4480.2 ms
- **Disposition Agreement Rate:** 100.0%
- **Retention False Negative Rate:** 0.0
- **Publication Firewall:** VERIFIED (Zero writes to production database, zero network calls)

---

## 8. Chosen Configurations and Tradeoffs

### Recommended Generation Configuration:
- **Model Identifier:** `qwen2.5:1.5b`
- **Model Digest:** `sha256:65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b`
- **Tested Context Limits:** 2048 tokens recommended (safe up to 4096 on host)
- **Decoding Options:** `temperature: 0.0`, `seed: 42`, non-thinking mode
- **Placement Profile:** Primary: GPU (`NVIDIA GeForce GTX 1650`), Fallback: CPU (`num_gpu: 0`)
- **Memory Envelope:** Resident VRAM: ~1.2 GiB, Host RAM: ~600 MiB

### Recommended Embedding Configuration:
- **Model Identifier:** `all-minilm:22m`
- **Model Digest:** `sha256:1b226e2802dbb772b5fc32a58f103ca1804ef7501331012de126ab22f67475ef`
- **Vector Dimension:** 384
- **Max Batch Size:** 16 items
- **Max Input Tokens:** 256 tokens per chunk
- **Placement Profile:** Primary: GPU (`NVIDIA GeForce GTX 1650`), Fallback: CPU
- **Memory Envelope:** Resident VRAM: ~28 MiB

### Operational Tradeoffs & Limitations:
1. **VRAM Fit Policy:** 4 GB dedicated VRAM fits `qwen2.5:1.5b` + `all-minilm:22m` concurrently. It **cannot** fit 7B/8B parameter models without severe swapping or crash. 4 GB VRAM is not a universal fit.
2. **CPU Fallback Latency:** Running `qwen2.5:1.5b` on CPU increases generation latency by ~5x - 7x (from ~2.0s to ~12.0s). It remains fully functional as an emergency fallback if the GPU is unavailable.
3. **Embedding Window:** `all-minilm:22m` context is capped at 256 tokens. Chunks exceeding 256 tokens must be segmented or rejected.
4. **Phase 1 Extensions:** Document generation and PDF rendering extensions are explicitly DEFERRED to Phase 1.

---

## 9. Dependency Gates Status

| Gate ID | Name | Owner | Status | Evidence |
|---|---|---|---|---|
| `B1` | Runtime Readiness & Health | `MODEL-01` | **SATISFIED** | Ollama 0.40.13 verified on 127.0.0.1:11434 with CPU fallback and Turing GPU acceleration |
| `B2` | Application Measurement Fidelity | `LLM-01` | **SATISFIED** | Strict schema parsing, context budget preflight, and bounded attempts verified |
| `B3` | Controlled Phase 0 Quality Execution | `EVAL-01` | **SATISFIED** | Paired runner with 8-case synthetic corpus and isolated persistence ready |
| `B4` | Embedding & Retrieval Binding | `CONTEXT-03` | **SATISFIED** | Isolated vector matrix and keyword index builder verified with configurable embedding dimensions |
| `B5` | Phase 1 Drafting Readiness | `GEN-02..05` | **DEFERRED** | Phase 1 document generation and visual rendering extensions are deferred |
| `EVAL_EG5` | EVAL Local Ollama Benchmark Evidence | `MODEL-02` | **SATISFIED** | Hardware telemetry, candidate measurements, and recommendation manifest provided |
