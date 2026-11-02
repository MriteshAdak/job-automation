# Operational Runbook: MODEL-02 — Model & Context Benchmarking on Windows

Component ID: **MODEL-02**  
Target Environment: **Native Windows (Intel Core i5-11320H, 16 GB RAM, NVIDIA GeForce GTX 1650 4 GB VRAM)**  
Runtime Baseline: **Ollama v0.40.13 via loopback `http://127.0.0.1:11434`**  
Phase: **Phase 0 (with Phase 1 drafting extensions deferred)**  

---

## 1. Overview and Operational Purpose

The `MODEL-02` benchmarking suite provides empirical, reproducible performance measurements of local small quantized language models and embedding models on the intended native Windows workstation.

It verifies:
1. **Context Admission and Ceilings:** Validates prompt budgets from 2048 to 4096 tokens, ensuring input fit and detecting context overflow without silent truncation.
2. **Hardware Placement:** Confirms 100% GPU offload on Turing CUDA (`GTX 1650`) and validates host CPU-only fallback execution (`num_gpu: 0`).
3. **Structured Generation Reliability:** Evaluates strict JSON schema parsing against registered contract schemas (`C11_assessment`), ensuring zero schema violations.
4. **Embedding Vector Conformance:** Measures batch processing (1, 4, 16), vector dimensions, numerical finiteness, L2 norms, and cosine similarity repeatability (`1.000000`).
5. **Memory and Latency Profiling:** High-resolution periodic sampling (200ms) of host physical RAM, commit limits, process working sets, and VRAM allocation.

---

## 2. Prerequisites and Preflight Verification

Before initiating benchmark runs, verify that:
1. Native Python virtual environment is activated: `.\.venv\Scripts\python.exe`.
2. Local Ollama service is running and listening on IPv4 loopback: `http://127.0.0.1:11434`.
3. Candidate models are present in the local cache:
   - Generation: `qwen2.5:1.5b` (Q4_K_M)
   - Embedding: `all-minilm:22m` (F16)
4. Available physical RAM >= 512 MiB and free dedicated VRAM >= 256 MiB.

### Run Preflight Offline Validation:
```powershell
& ".\.venv\Scripts\python.exe" scripts\model_benchmark.py check --manifest config\model-benchmark.example.json
```
**Expected Exit Code:** `0` (`VALID`).

---

## 3. Benchmark Execution Commands

### 3.1 Full Benchmark Run (All Cells, Index, and EVAL Paired Comparison)
```powershell
$benchRoot = Join-Path $env:LOCALAPPDATA 'JobAutomationBenchmarks'
& ".\.venv\Scripts\python.exe" scripts\model_benchmark.py run `
    --manifest config\model-benchmark.example.json `
    --output-root $benchRoot
```

### 3.2 Selective Cell Execution (Targeted Diagnostic)
To run a specific planned cell without re-running other cells:
```powershell
$benchRoot = Join-Path $env:LOCALAPPDATA 'JobAutomationBenchmarks'
& ".\.venv\Scripts\python.exe" scripts\model_benchmark.py run `
    --manifest config\model-benchmark.example.json `
    --output-root $benchRoot `
    --cell gen_qwen1.5b_ctx2048_gpu_warm `
    --no-eval `
    --no-index
```

### 3.3 Fast Microbenchmark (Skip Downstream Integration)
To measure only model inference and embeddings without the full EVAL corpus:
```powershell
$benchRoot = Join-Path $env:LOCALAPPDATA 'JobAutomationBenchmarks'
& ".\.venv\Scripts\python.exe" scripts\model_benchmark.py run `
    --manifest config\model-benchmark.example.json `
    --output-root $benchRoot `
    --no-eval `
    --no-index
```

---

## 4. Report Generation

To compile the empirical observations into human-readable Markdown and machine-readable JSON recommendations without executing additional model inference:

```powershell
$benchRoot = Join-Path $env:LOCALAPPDATA 'JobAutomationBenchmarks'
& ".\.venv\Scripts\python.exe" scripts\model_benchmark.py report `
    --output-root $benchRoot `
    --output docs\benchmarks\MODEL-02-phase0.md `
    --json config\model-benchmark-recommendations.example.json
```

---

## 5. Resumption and Recovery Discipline

1. **Atomic Checkpointing:** Every cell repetition is committed atomically as `<cell_id>_rep<index>.json` under `<output_root>\observations\`.
2. **Safe Resumption:** Re-running the benchmark with an existing output directory automatically detects and skips completed valid observations, preventing redundant inference and GPU wear.
3. **Guardrail Abort:** If host physical memory drops below `min_available_ram_bytes` (512 MiB), the engine halts safely before starting the next trial, protecting host stability.
4. **VRAM Unloading:** Upon completion or failure, the harness automatically posts `keep_alive: 0` to release all models from VRAM.

### Manual VRAM Flush Recipe:
If a previous abnormal termination left weights resident in VRAM:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/generate" -Method Post -Body '{"model":"qwen2.5:1.5b","prompt":"","keep_alive":0}' -ContentType "application/json" | Out-Null
Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/generate" -Method Post -Body '{"model":"all-minilm:22m","prompt":"","keep_alive":0}' -ContentType "application/json" | Out-Null
```
Verify zero models loaded:
```powershell
(Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/ps").models.Count
```

---

## 6. Hardware Boundaries and Fit Warnings

> [!WARNING]
> **4 GB Dedicated VRAM Boundary:**  
> A dedicated VRAM allocation of 4 GB is sufficient for small quantized candidates (`qwen2.5:1.5b` requiring ~1.2 GB resident VRAM, and `all-minilm:22m` requiring ~30 MB). However, 7B/8B parameter models or context windows >= 8192 tokens will exceed 4 GB VRAM, triggering heavy WDDM shared memory paging or CUDA out-of-memory errors. Do not recommend or promise universal GPU fit for models larger than 2.0B parameters on this host.

> [!NOTE]
> **CPU Fallback Profile:**  
> When the GPU is busy or unavailable, passing `num_gpu: 0` runs `qwen2.5:1.5b` on CPU with full structural schema fidelity, with a latency penalty factor of ~5x - 7x (~12.0s per assessment vs ~2.0s on GPU).

---

## 7. Deferred Phase 1 Extensions

- **MODEL-02-S08:** Model & context measurements for document drafting (CV, cover letter) with expanded output reserves (>1024 tokens) remain explicitly **DEFERRED** pending `GEN-02..05` and `EVAL-01-S09`.
- **MODEL-02-S09:** Local drafting workflow resource profiling and PDF rendering remain explicitly **DEFERRED** pending `EVAL-01-S10`.

