# Component Handoff: MODEL-01 — Local Model Runtime Setup and Health

Component ID: **MODEL-01**  
Status: **VERIFIED** (Native Windows host setup, health verification, and synthetic test suites complete)  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026)  
Planning Reference: [docs/stories/MODEL-01.md](../stories/MODEL-01.md)  
Date Completed: **31 October 2026**  
Direct Covered Requirements: [R07](../../IMPLEMENTATION_BLUEPRINT.md#r07), [R14](../../IMPLEMENTATION_BLUEPRINT.md#r14), [R15](../../IMPLEMENTATION_BLUEPRINT.md#r15), [R16](../../IMPLEMENTATION_BLUEPRINT.md#r16)  

---

## 1. Implementation Status by Story

All six planned stories under MODEL-01 have been implemented, tested, and verified on native Windows:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **MODEL-01-S01** | Establish host compatibility and installation decision | **VERIFIED** | Audited Windows 11 Build 26300 64-bit host, 11th Gen i5-11320H (AVX2/AVX-512), 16 GB RAM, and dual GPU setup (Intel Iris Xe + NVIDIA GTX 1650 4 GB VRAM with Driver 617.42). Established CPU baseline requirement and recorded that 4 GB VRAM does not guarantee model fit. |
| **MODEL-01-S02** | Install and configure local-only manual runtime | **VERIFIED** | Configured native Ollama runtime (v0.40.13) under local user account. Listener bound strictly to IPv4 loopback `127.0.0.1:11434` with owning PID established. Disabled cloud routing (`OLLAMA_NO_CLOUD=1`) and verified zero LAN exposure (`0.0.0.0`). |
| **MODEL-01-S03** | Establish storage and explicit models for both capabilities | **VERIFIED** | Configured dedicated model cache directory outside repository source root (`%LOCALAPPDATA%\JobAutomationModels`). Explicitly pulled and verified separate smoke models: `qwen2.5:1.5b` for generation (986 MB, Q4_K_M) and `all-minilm:22m` for embeddings (46 MB, F16, 384 dimensions). |
| **MODEL-01-S04** | Implement layered health diagnostics with honest results | **VERIFIED** | Implemented `scripts/model_runtime_health.py` and `job_automation.models.runtime_health`. Implemented standard exit codes (0, 2, 3, 4, 5, 6) with strict failure precedence (2 > 3 > 4 > 5 > 6 > 0). Verified live execution on Windows host. |
| **MODEL-01-S05** | Demonstrate supported CPU fallback and acceleration reporting | **VERIFIED** | Functional placement checks query `/api/ps` during residency. Observed 100% GPU offload on host GTX 1650 for both smoke models, and documented the verified CPU-only execution recipe (`CUDA_VISIBLE_DEVICES="-1"`, `OLLAMA_VULKAN="0"`, `OLLAMA_LLM_LIBRARY="cpu"`). |
| **MODEL-01-S06** | Verify recovery, removal and component handoff | **VERIFIED** | Authored comprehensive operational runbook `docs/operations/model-runtime-windows.md`. Tested process restart, model retention, clean model unloading via `keep_alive: 0`, and safe uninstallation procedures preserving application data. |

---

## 2. Host Hardware Context and Limitations

Inspection was executed directly on the host using native CIM and PowerShell cmdlets:

- **Operating System:** Microsoft Windows 11 Home Single Language (Version 10.0.26300, Build 26300, 64-bit AMD64).
- **Processor:** 11th Gen Intel(R) Core(TM) i5-11320H @ 3.20GHz (4 physical cores, 8 logical processors; supports x86_64, AVX, AVX2, AVX-512, FMA).
- **Physical Memory:** 16.0 GB total system RAM (~7.5 GB free before model load).
- **Disk Storage:** Drive `C:` (local NTFS) with > 250 GB available free space.
- **Graphics Processing Units:**
  1. **Intel(R) Iris(R) Xe Graphics:** Integrated, Driver version 32.0.101.7092, 2.0 GB shared system memory.
  2. **NVIDIA GeForce GTX 1650:** Dedicated GPU, Driver version 32.0.16.1742 (NVIDIA Driver Release 617.42, CUDA UMD 13.4, WDDM mode), Turing architecture, Compute Capability 7.5. Dedicated VRAM: 4096 MiB (4.0 GB).
- **Execution Account:** Standard local user account (`mrite`).

> [!WARNING]
> **VRAM Fit Policy (MODEL-01 Hardware Finding):**  
> Having 4 GB of dedicated VRAM does **not** guarantee model fit or full GPU acceleration for arbitrary models or extended context windows. While the modest smoke models (`qwen2.5:1.5b` requiring ~1.1 GB resident VRAM, and `all-minilm:22m` requiring ~27 MB resident VRAM) successfully fit 100% within the 4 GB allocation on this host, larger models (e.g. 7B/8B parameter models or context windows > 4096 tokens) will exhaust 4 GB VRAM and fail or require partial CPU offload. Host CPU fallback is a tested and required operational baseline.

---

## 3. Runtime Configuration and Verified Model Inventory

### Runtime Settings

- **Executable Path:** `C:\Users\mrite\AppData\Local\Programs\Ollama\ollama.exe`
- **Installed Runtime Version:** `0.40.13`
- **Effective Service URL:** `http://127.0.0.1:11434`
- **Listener Verification:** TCP connection confirmed on `127.0.0.1:11434` owned exclusively by PID `6656` (`ollama.exe`). Zero exposure on `0.0.0.0` or external network adapters.
- **Model Storage Cache:** Dedicated path `C:\Users\mrite\AppData\Local\JobAutomationModels` (expanded, outside repository root).
- **Server Environment Profile:**
  - `OLLAMA_HOST=127.0.0.1:11434`
  - `OLLAMA_NO_CLOUD=1`
  - `OLLAMA_NUM_PARALLEL=1`
  - `OLLAMA_MAX_LOADED_MODELS=1`
  - `OLLAMA_MAX_QUEUE=1`
  - `OLLAMA_CONTEXT_LENGTH=2048`
  - `OLLAMA_KEEP_ALIVE=0`

### Model Inventory and Capability Separation

| Role | Model Identifier / Tag | Parameter Size | Format & Quant | Verified SHA-256 Digest | Capabilities | Smoke Context / Dimension | Observed Placement |
|---|---|---|---|---|---|---|---|
| **Generation** | `qwen2.5:1.5b` | 1.5B | GGUF / Q4_K_M | `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b` | `completion`, `tools` | 2048 tokens | 100% GPU (Turing CUDA) |
| **Embedding** | `all-minilm:22m` | 23M | GGUF / F16 | `1b226e2802dbb772b5fc32a58f103ca1804ef7501331012de126ab22f67475ef` | `embedding` | 384 dimensions (512 ctx) | 100% GPU (Turing CUDA) |

*Note: Models are unloaded immediately after inference (`keep_alive: 0`), releasing dedicated VRAM to 0 MiB.*

---

## 4. Deliverables Created and Modified

### Source and Scripts
- [`src/job_automation/models/runtime_health.py`](../../src/job_automation/models/runtime_health.py): Core diagnostics engine, `ModelRuntimeManifest` schema, `RuntimeHealthChecker`, and exit-code resolution.
- [`scripts/model_runtime_health.py`](../../scripts/model_runtime_health.py): Executable CLI entrypoint supporting `--config`, `--runtime-config`, `--metadata-only`, `--json`, and `--output`.

### Configuration and Manifests
- [`config/model-runtime.example.json`](../../config/model-runtime.example.json): Versioned diagnostic manifest example with exact model tags, digests, dimensions, and server environment profile.
- [`config/local.model-runtime.json`](../../config/local.model-runtime.json): Local app configuration targeting loopback (gitignored).
- [`config/local.model-runtime-manifest.json`](../../config/local.model-runtime-manifest.json): Local manifest with discovered host executable and model digests (gitignored).

### Documentation
- [`docs/operations/model-runtime-windows.md`](../operations/model-runtime-windows.md): Comprehensive operational runbook covering system requirements, installation, loopback configuration, model management, CPU fallback, troubleshooting, and clean removal.
- [`docs/components/MODEL-01.md`](MODEL-01.md): This handoff document.

### Tests
- [`tests/models/test_runtime_health.py`](../../tests/models/test_runtime_health.py): 19 unit and synthetic integration tests covering all exit codes (0, 2, 3, 4, 5, 6), exit precedence, loopback enforcement, path traversal rejection, capability mismatches, OOM failures, timeouts, and Unicode Windows paths.

---

## 5. Verification Commands and Live Results

### 5.1 Automated Unit & Integration Suite
Executed from repo root on native Windows PowerShell:
```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests\models\test_runtime_health.py tests\models\test_configuration.py tests\models\test_local_transport.py tests\models\test_safe_diagnostics.py tests\test_configuration.py
```
**Result:** 50 passed in 2.63s.

### 5.2 Offline App Configuration Check
```powershell
& ".\.venv\Scripts\python.exe" -m job_automation config check --config config\local.model-runtime.json
```
**Result:** Exit code 0, Configuration check: VALID.

### 5.3 Metadata-Only Health Diagnostic
```powershell
& ".\.venv\Scripts\python.exe" scripts\model_runtime_health.py --config config\local.model-runtime.json --runtime-config config\local.model-runtime-manifest.json --metadata-only --json
```
**Result:**
- Exit code: `6` (`EXIT_METADATA_ONLY_OR_INCOMPLETE`)
- Overall Status: `metadata_healthy`
- Reasons: `["metadata_only"]`
- All metadata layers (config, executable, listener, runtime version, tags, show) passed. Active probes safely skipped.

### 5.4 Full Active Inference Health Diagnostic
```powershell
& ".\.venv\Scripts\python.exe" scripts\model_runtime_health.py --config config\local.model-runtime.json --runtime-config config\local.model-runtime-manifest.json
```
**Result:**
- Exit code: `0` (`EXIT_SUCCESS`)
- Overall Status: `ready`
- Generation Probe: `PASS` (`qwen2.5:1.5b`, latency: ~7.7s, done: True, observed_placement: `gpu`)
- Embedding Probe: `PASS` (`all-minilm:22m`, latency: ~4.3s, vectors: 2, dimension: 384, observed_placement: `gpu`)
- Acceleration: `PASS` (`observed_acceleration: gpu`)
- VRAM freed immediately to 0 MiB after check completion.

### 5.5 Live Negative Check (Missing Model)
Executed against a manifest requesting `nonexistent_test_model:1.0`:
- Exit code: `4` (`EXIT_MODEL_MISSING_OR_MISMATCH`)
- Reasons: `["generation_model_missing"]`
- Remediation: `Pull missing model via 'ollama pull nonexistent_test_model:1.0'`

---

## 6. Downstream Handoffs and Next Actions

1. **Follow-up for LLM-01:**  
   The local model runtime is operational and verified. Note that `tests/manual/model_smoke.py` currently assumes a single model serves both generation and embeddings (`installed_models[0]`). Because Ollama enforces strict capability separation, the application harness correctly routes generation calls to `qwen2.5:1.5b` and embedding calls to `all-minilm:22m`.
2. **Follow-up for MODEL-02:**  
   Runtime setup and health diagnostics provide the necessary baseline for MODEL-02 model/context benchmarking. Smoke tests established that `qwen2.5:1.5b` fits in 4 GB VRAM at 2048 context tokens; MODEL-02 will systematically measure latency, context ceilings, and memory consumption across model candidates.
3. **Phase 2 (AUTO-01):**  
   Manual startup and loopback configuration are verified. Unattended background service management and Windows Task Scheduler deployment are deferred to Phase 2 (AUTO-01).

