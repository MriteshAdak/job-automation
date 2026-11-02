# Operational Runbook: Local Model Runtime on Native Windows (MODEL-01)

Document Reference: `docs/operations/model-runtime-windows.md`  
Component ID: **MODEL-01**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (R07, R14, R15, R16)  
Planning Reference: [docs/stories/MODEL-01.md](../stories/MODEL-01.md)  
Status: **OPERATIONAL**  
Check Date: **31 October 2026**  

---

## 1. System Requirements and Hardware Verification

This runbook establishes a reproducible, local-only Ollama runtime on native Windows 10/11 64-bit. No Docker, WSL, or paid external APIs are required.

> [!WARNING]
> **4 GB Dedicated VRAM Limit Warning:**  
> A graphics card equipped with 4 GB VRAM does **not** guarantee universal model fit or GPU acceleration. Offload depends on model parameter size, quantization level, context window length, and driver memory reservations. Modest smoke models (`qwen2.5:1.5b` and `all-minilm:22m`) fit comfortably within 4 GB VRAM, but larger models or extended context windows will exceed 4 GB and require CPU offload or fail. Supported CPU execution is the mandatory baseline.

### Verified Host Baseline
- **Operating System:** Microsoft Windows 11 Home / Pro (Build 22621 or newer; verified on Build 26300, 64-bit).
- **CPU:** x86_64 processor supporting AVX / AVX2 instructions (e.g. 11th Gen Intel Core i5-11320H @ 3.20GHz or AMD Zen 2+).
- **RAM:** Minimum 8 GB available physical memory; 16 GB recommended.
- **Disk Storage:** At least 4 GB free space for Ollama binaries and runtime runners, plus 5–15 GB for local model weights. Must reside on local NTFS drive.
- **GPU (Optional Acceleration):**
  - **NVIDIA:** Compute capability 5.0+; driver version >= 551.61 (driver 570+ for Maxwell/Pascal). Host verified with NVIDIA GeForce GTX 1650 (Compute Capability 7.5, Driver 617.42).
  - **AMD:** Windows ROCm v7 / HIP7 or Vulkan supported card.
  - **Intel:** Intel Iris Xe / ARC via Vulkan or LevelZero.
  - **CPU Baseline:** Always required and functional even if no GPU or driver is available.

---

## 2. Installation Runbook

Ollama is distributed as a native Windows per-user installer. It installs into `%LOCALAPPDATA%\Programs\Ollama` and does not require administrative privileges.

### Step 2.1: Download and Verify Official Installer
1. Download official installer from: `https://ollama.com/download/OllamaSetup.exe`
2. Verify digital publisher signature:
   ```powershell
   Get-AuthenticodeSignature "$env:USERPROFILE\Downloads\OllamaSetup.exe"
   ```
   Ensure `Status: Valid` and publisher is `Ollama, Inc.`.

### Step 2.2: Execute Account Installation
Run the installer under the standard user account:
```powershell
& "$env:USERPROFILE\Downloads\OllamaSetup.exe"
```
The installer places the binaries at:
`$env:LOCALAPPDATA\Programs\Ollama\ollama.exe`

### Step 2.3: Disable Automatic Startup
For controlled manual operation, disable the automatic login startup entry:
```powershell
Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'Ollama' -ErrorAction SilentlyContinue
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'Ollama' -ErrorAction SilentlyContinue
```

---

## 3. Local-Only Runtime Configuration & Storage

Ollama runtime behavior is governed by environment variables applied to the server process.

### Environment Variable Table

| Variable | Recommended Setup Value | Operational Purpose |
|---|---|---|
| `OLLAMA_HOST` | `127.0.0.1:11434` | Binds server exclusively to IPv4 loopback. Prevents 0.0.0.0 or LAN exposure. |
| `OLLAMA_MODELS` | `C:\Users\<user>\AppData\Local\JobAutomationModels` | Dedicated model cache path strictly outside repository source root. |
| `OLLAMA_NO_CLOUD` | `1` | Disables remote/cloud model inference. Local weights only. |
| `OLLAMA_NUM_PARALLEL` | `1` | Serializes request processing to avoid resource thrashing. |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Ensures only 1 model is resident in RAM/VRAM at a time. |
| `OLLAMA_MAX_QUEUE` | `1` | Bounds incoming request queue depth. |
| `OLLAMA_CONTEXT_LENGTH` | `2048` | Conservative default context ceiling. |
| `OLLAMA_KEEP_ALIVE` | `0` | Unloads weights immediately after inference, releasing RAM/VRAM. |

### Applying User-Level Environment Variables (Permanent)
```powershell
$modelsPath = Join-Path $env:LOCALAPPDATA 'JobAutomationModels'
New-Item -ItemType Directory -Path $modelsPath -Force | Out-Null

[System.Environment]::SetEnvironmentVariable('OLLAMA_HOST', '127.0.0.1:11434', 'User')
[System.Environment]::SetEnvironmentVariable('OLLAMA_MODELS', $modelsPath, 'User')
[System.Environment]::SetEnvironmentVariable('OLLAMA_NO_CLOUD', '1', 'User')
[System.Environment]::SetEnvironmentVariable('OLLAMA_NUM_PARALLEL', '1', 'User')
[System.Environment]::SetEnvironmentVariable('OLLAMA_MAX_LOADED_MODELS', '1', 'User')
[System.Environment]::SetEnvironmentVariable('OLLAMA_MAX_QUEUE', '1', 'User')
[System.Environment]::SetEnvironmentVariable('OLLAMA_CONTEXT_LENGTH', '2048', 'User')
[System.Environment]::SetEnvironmentVariable('OLLAMA_KEEP_ALIVE', '0', 'User')
```

---

## 4. Starting, Stopping, and Verifying the Runtime

### Method A: Foreground Console (Diagnostic Session)
Best for testing, debugging, and observing server logs directly:
```powershell
$ollamaExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'

# Set session variables
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = Join-Path $env:LOCALAPPDATA 'JobAutomationModels'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_MAX_QUEUE = '1'
$env:OLLAMA_CONTEXT_LENGTH = '2048'
$env:OLLAMA_KEEP_ALIVE = '0'

# Start foreground server
& $ollamaExe serve
```
To stop: Press `Ctrl+C`.

### Method B: Background Application
Launch `ollama app.exe` from the Start Menu or command line.  
To stop: Right-click the Ollama llama icon in the Windows taskbar notification tray and select **Quit**.

### Verifying Socket Binding and Process Ownership
Verify that port 11434 is listening strictly on `127.0.0.1`:
```powershell
Get-NetTCPConnection -LocalPort 11434 |
    Where-Object { $_.RemoteAddress -eq '0.0.0.0' -or $_.RemotePort -eq 0 } |
    Select-Object LocalAddress, LocalPort, OwningProcess, State
```
Ensure `LocalAddress` is `127.0.0.1` and `OwningProcess` matches `ollama.exe`.

---

## 5. Model Management Runbook

Explicitly pull the designated smoke models serially. Never rely on automatic pulls during pipeline execution.

### Step 5.1: Pull Text Generation Model
```powershell
$ollamaExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
& $ollamaExe pull qwen2.5:1.5b
```
- **Tag:** `qwen2.5:1.5b`
- **Size:** ~986 MB
- **Quantization:** Q4_K_M
- **Observed Digest:** `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b`

### Step 5.2: Pull Embedding Model
```powershell
& $ollamaExe pull all-minilm:22m
```
- **Tag:** `all-minilm:22m`
- **Size:** ~46 MB
- **Quantization:** F16
- **Embedding Dimension:** 384
- **Observed Digest:** `1b226e2802dbb772b5fc32a58f103ca1804ef7501331012de126ab22f67475ef`

### Step 5.3: Verify Installed Models
```powershell
& $ollamaExe list
```

---

## 6. Running Health Diagnostics (MODEL-01-S04)

Use the dedicated health verification tool:

```powershell
$pythonExe = Join-Path (Get-Location).Path '.venv\Scripts\python.exe'
$appConfig = 'config\local.model-runtime.json'
$manifest = 'config\local.model-runtime-manifest.json'

# Non-intrusive metadata check (exits 6 when healthy)
& $pythonExe scripts\model_runtime_health.py --config $appConfig --runtime-config $manifest --metadata-only --json

# Full active probe check (exits 0 on success)
& $pythonExe scripts\model_runtime_health.py --config $appConfig --runtime-config $manifest
```

### Diagnostic Exit Code Reference

| Exit Code | Classification | Meaning | Recommended Action |
|---|---|---|---|
| **0** | `SUCCESS` | Both generation and embedding capabilities passed. | System is ready for local model operations. |
| **2** | `CONFIG_OR_BINDING` | Invalid config, manifest error, endpoint mismatch, or non-loopback bind. | Check app config URL, manifest paths, and ensure loopback binding. |
| **3** | `RUNTIME_UNAVAILABLE` | Ollama binary missing, offline, port conflict, or version mismatch. | Install Ollama, start service, resolve port conflict, or update build. |
| **4** | `MODEL_MISMATCH` | Required model missing from tags, capability mismatch, or wrong digest. | Pull missing model via `ollama pull <tag>` or update manifest. |
| **5** | `EXECUTION_FAILURE` | Inference timeout, out-of-memory (507), or invalid vector format. | Inspect RAM/VRAM capacity, reduce context tokens, or inspect logs. |
| **6** | `METADATA_ONLY` | Metadata checks passed successfully, active probes unperformed. | Expected behavior when running with `--metadata-only`. |

---

## 7. Supported CPU Fallback Execution (MODEL-01-S05)

When a GPU is unsupported, lacks sufficient VRAM, or encounters driver crashes, Ollama must run on CPU:

### Launching CPU-Only Session
```powershell
$ollamaExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'

# Hide all CUDA devices and disable Vulkan
$env:CUDA_VISIBLE_DEVICES = "-1"
$env:OLLAMA_VULKAN = "0"
$env:OLLAMA_LLM_LIBRARY = "cpu"

& $ollamaExe serve
```

### Verifying CPU Placement
While a model is executing or resident:
```powershell
& $ollamaExe ps
```
The **PROCESSOR** column must display `100% CPU` (and `size_vram` in `/api/ps` must equal `0`).

---

## 8. Troubleshooting and Error Recovery

| Symptom | Diagnostic Reason | Root Cause & Recovery Procedure |
|---|---|---|
| Connection Refused | `runtime_not_running` | Server is offline. Start `& $ollamaExe serve` or launch Ollama desktop app. |
| Port 11434 occupied by other app | `port_conflict` | Another service uses port 11434. Identify PID via `Get-NetTCPConnection` and change port or stop conflicting app. |
| Listener on `0.0.0.0` | `unsafe_binding` | Security violation. Ollama is exposed to LAN. Stop Ollama and launch with `OLLAMA_HOST=127.0.0.1:11434`. |
| Model not in `/api/tags` | `generation_model_missing` / `embedding_model_missing` | Model has not been pulled. Run `ollama pull <tag>`. |
| Model returns wrong vector shape | `embedding_response_invalid` | Model is not an embedding model or output corrupted. Verify model capability in `/api/show`. |
| HTTP 507 or Out of Memory | `memory_capacity` | Model or context exceeded physical RAM/VRAM. Set `OLLAMA_KEEP_ALIVE=0`, reduce `smoke_context_tokens`, or use smaller model. |
| Request Timed Out (120s) | `request_timeout` | Host CPU/GPU is overloaded or model size too large. Check CPU utilization in Task Manager. |

---

## 9. Safe Removal and Uninstallation

Follow this procedure to cleanly remove Ollama without touching application databases, evidence, or personal configurations.

### Step 9.1: Stop Running Processes
```powershell
Get-Process -Name "*ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force
```

### Step 9.2: Uninstall Runtime
Open **Windows Settings** → **Apps** → **Installed apps** → search for **Ollama** → select **Uninstall**.  
Or run the uninstaller directly:
```powershell
$uninst = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\unins000.exe'
if (Test-Path $uninst) { Start-Process -FilePath $uninst -Wait }
```

### Step 9.3: Remove Custom Model Cache (Optional)
The Windows uninstaller does not delete models at custom `OLLAMA_MODELS` locations:
```powershell
$modelsPath = Join-Path $env:LOCALAPPDATA 'JobAutomationModels'
if (Test-Path $modelsPath) {
    Remove-Item -LiteralPath $modelsPath -Recurse -Force
}
```
> [!CAUTION]
> Never delete the user's entire `%USERPROFILE%\.ollama` directory, as it may contain SSH keys (`id_ed25519`) or unrelated user configurations.

### Step 9.4: Clean Up Environment Variables
```powershell
$vars = @('OLLAMA_HOST', 'OLLAMA_MODELS', 'OLLAMA_NO_CLOUD', 'OLLAMA_NUM_PARALLEL',
          'OLLAMA_MAX_LOADED_MODELS', 'OLLAMA_MAX_QUEUE', 'OLLAMA_CONTEXT_LENGTH', 'OLLAMA_KEEP_ALIVE')
foreach ($v in $vars) {
    [System.Environment]::SetEnvironmentVariable($v, $null, 'User')
}
```

