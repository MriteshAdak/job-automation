# MODEL-01 — Native Windows runtime setup and health

Status: **PLANNED** · Planning date: **31 October 2026** · Component: **MODEL-01 only** · Phase 0

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially §§2–3, 5–9 and the MODEL-01 catalog entry. Direct requirements: **R07, R14, R15**; recovery and actionable diagnostics support **R16**. This document specifies future implementation. No runtime installation, model download, driver change, live inference, or machine compatibility verification was performed while creating these stories.

## Scope and current repository evidence

The outcome is a manually operated, native Windows model service with local generation and embedding availability, verified loopback binding, explicit storage, and diagnoses that separate runtime, model, capacity and acceleration problems. The confirmed target is **16 GB RAM and 4 GB VRAM**. GPU vendor, model, driver, CPU instruction support and actual available memory remain unknown. GPU acceleration is optional; CPU execution must be demonstrated where the selected runtime build supports the host CPU.

Ollama is the proposed runtime, consistent with the blueprint and existing client. Small models and conservative resource settings below are **setup choices**, not benchmark recommendations or promises of suitability for matching, German-language retrieval, or document generation. Excluded: application prompts and schemas, model/context benchmarks, quality or latency targets, retrieval/index construction, Salesforce changes, and Phase 2 startup/scheduling. Do not implement Task Scheduler jobs, Windows services, NSSM, unattended operation or reboot-without-login tests in this component. Existing AUTO components do not expand this task.

Repository instructions read: the root [README](../../README.md) directs planning to the blueprint; no applicable `AGENTS.md` was found in the repository or its inspected ancestors. Historical deployment documents do not override the blueprint.

| Inspected source | Existing interface or limitation relevant to this plan |
|---|---|
| [FND-01 handoff](../components/FND-01.md), [configuration](../../src/job_automation/configuration.py) | Handoff records native Windows foundation verification. `AppConfig` requires an absolute data root outside the repository; `load_config` uses explicit data-root override, then config, then a LOCALAPPDATA-derived default. `config check` is offline. `ResolvedPaths` has no model-cache field. |
| [Model settings](../../src/job_automation/models/configuration.py), [provider](../../src/job_automation/models/provider.py) | Effective URL is `model_provider.service_url` when supplied, otherwise `model_service_url`, whose default is `http://127.0.0.1:11434`. Capabilities include identifier, context ceiling, output reserve, optional dimension and expected digest. Provider locking is per instance. |
| [Transport](../../src/job_automation/models/transport.py) | Existing POST transport validates loopback targets, bypasses environment proxies, disallows automatic redirects and bounds response size. Client validation does **not** establish the server's listening address. |
| [Generation](../../src/job_automation/models/generation.py), [embeddings](../../src/job_automation/models/embeddings.py) | Use `/api/generate` and `/api/embed`. Generation sends `options.num_ctx`, overriding a runtime default. Embedding currently sends only model/input. Both read an optional response `digest`; absence does not establish a match against a pin. |
| [LLM-01 handoff](../components/LLM-01.md), [manual smoke script](../../tests/manual/model_smoke.py) | Handoff records offline verification and pending live tests. Script probes with `urllib`, ignores the provider endpoint override, selects the first installed model for both capabilities, uses a domain prompt, and returns zero even for pending/failed checks. It is not MODEL-01 acceptance evidence. |
| [Diagnostics](../../src/job_automation/models/diagnostics.py), [errors](../../src/job_automation/models/errors.py), [shared errors](../../src/job_automation/contracts/errors.py) | Reuse safe projections and existing categories where useful. MODEL-01 needs richer diagnostic reasons without redefining C10 or treating every HTTP 500 as a GPU failure. |
| [Example config](../../config/app.example.json), [exclusions](../../.gitignore), [project metadata](../../pyproject.toml) | Example data root is illustrative. Local overrides, logs and runtime data are excluded. Python 3.12+ is required; use the existing environment without adding an Ollama Python SDK merely for health requests. |

## Official documentation checked for this plan

Checked **31 October 2026**. Recheck against the exact release selected during implementation; documentation is mutable and is not a host test. Record source URLs, check date, runtime version, installer provenance and actual results in the handoff.

| Evidence | Current documented facts and implementation consequence |
|---|---|
| [Windows installation](https://docs.ollama.com/windows) | Windows 10 22H2 or newer, Home/Pro; NVIDIA driver 551.61+; AMD acceleration depends on the appropriate ROCm/HIP7 or Vulkan stack. Account installer needs no administrator and needs at least 4 GB for binaries, plus models. Choose the native account installer. A standalone amd64 ZIP also exists; it is an alternative, not a required service deployment. |
| [GPU support](https://docs.ollama.com/gpu) | NVIDIA compute capability 5.0+; capabilities 5.0–6.2 require driver 570+. AMD has a distinct Windows ROCm list requiring ROCm v7/HIP7; do not apply its Linux list to Windows. Vulkan is enabled by default when installed and can be disabled with `OLLAMA_VULKAN=0`. Match the exact GPU, driver and backend; do not infer support from VRAM. |
| [Runtime configuration](https://docs.ollama.com/faq) | Documents `OLLAMA_HOST`, `OLLAMA_MODELS`, `OLLAMA_NO_CLOUD`, context, residency and concurrency controls. Windows configuration changes require restarting Ollama. Local-only cloud disabling and socket binding are separate controls. Request options can override server defaults. `ollama ps` distinguishes CPU, GPU and mixed placement. |
| [Troubleshooting](https://docs.ollama.com/troubleshooting) | Windows server logs normally live under `%LOCALAPPDATA%\Ollama`; foreground `serve` logs appear in that terminal. CPU library overrides are documented as experimental and build-dependent. Select only a library actually supplied by the installed build and supported by the CPU; never assume an old `cpu_avx2` example is a universal switch. |
| [Model inventory](https://docs.ollama.com/api/tags), [model details](https://docs.ollama.com/api-reference/show-model-details), [loaded models](https://docs.ollama.com/api/ps) | `/api/tags` supplies installed identifiers/digests; `/api/show` supplies capabilities/details; `/api/ps` describes loaded models including VRAM allocation and context. Installed, loaded and usable are different states. |
| [Generation API](https://docs.ollama.com/api/generate), [embedding API](https://docs.ollama.com/api/embed), [version](https://docs.ollama.com/api-reference/get-version) | Check `/api/version`, then separate non-streaming generation and embedding requests. Embedding defaults to truncation, so the diagnostic explicitly sends `truncate:false`. Generation/embedding response contracts do not guarantee a digest; inventory provenance must remain distinguishable from response provenance. |
| [CLI reference](https://docs.ollama.com/cli) | Use explicit `pull`, `ls`, `ps`, `stop`, `rm` and manual `serve` operations. Health checks must not implicitly pull or delete models. |

Documentation differences need explicit resolution: the general NVIDIA page says driver 550+ while the Windows page says 551.61+; apply the Windows minimum and any higher GPU-specific requirement, then verify the selected release. The FAQ also retains an older Radeon ROCm note; use the current Windows/hardware requirements for compatibility and record any release-specific discrepancy. Do not copy Linux driver, container or kernel-reload commands into the Windows runbook.

## Dependencies, deliverables and configuration boundaries

MODEL-01 has **no hard component prerequisite** in the catalog. Coordinate with the implemented FND-01 configuration and LLM-01 transport; neither MODEL-02 nor a live Salesforce connection blocks setup. MODEL-01 supplies runtime evidence to LLM-01 live testing and MODEL-02 later selection. Existing consumer/index configuration is not silently changed.

Proposed implementation deliverables:

- `docs/operations/model-runtime-windows.md`: installation, start/stop, configuration, storage, troubleshooting, recovery and removal runbook.
- `scripts/model_runtime_health.py`: manual diagnostic entry point; `tests/models/test_runtime_health.py` and synthetic fixtures for its behavior. Keep diagnostic helpers together; reuse the existing URL validator/transport policy rather than creating an application model provider.
- `config/model-runtime.example.json`: versioned **diagnostic/setup manifest**, separately loaded by the diagnostic, not an unrecognized `AppConfig` section. Validated shape may live alongside the script. No application schema or database migration is required by default.
- `docs/components/MODEL-01.md`: actual implementation and verification handoff. These paths are proposed deliverables, not files created by this planning task.

| Interface | Proposed value/behavior and ownership |
|---|---|
| Application endpoint | Reuse `AppConfig` and its effective URL precedence. Keep the canonical setup URL `http://127.0.0.1:11434`; if the port changes, change both client config and runtime bind. Reject mismatches before inference. Do not silently rewrite config. |
| Runtime listener | Set `OLLAMA_HOST=127.0.0.1:11434` before launch. No wildcard, LAN address, tunnel, proxy exposure or inbound firewall allowance. IPv6 use requires an explicitly verified `::1` configuration. |
| Local execution | Set `OLLAMA_NO_CLOUD=1`; use local weight inventory and refuse remote/cloud descriptors. Do not sign in or configure cloud models for setup. Downloads/updates are separate outbound operations; loopback binding alone does not block cloud inference. |
| Model cache | Set `OLLAMA_MODELS` to an expanded absolute, account-writable local path outside source, proposed `Join-Path $env:LOCALAPPDATA 'JobAutomationModels'`. Keep it separate from application evidence and default backups. Do not put a shell expression or `%LOCALAPPDATA%` literally into JSON. |
| Conservative server profile | Proposed `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_MAX_QUEUE=1`, `OLLAMA_CONTEXT_LENGTH=2048`, `OLLAMA_KEEP_ALIVE=0`. These are initial operational bounds, not model-quality recommendations or hard RAM limits. |
| Diagnostic manifest v1.0 | Fields: `schema_version`, absolute `runtime_executable`, absolute `model_storage_path`, `expected_runtime_version`, `generation_model`, `embedding_model`, `generation_digest`, `embedding_digest`, `smoke_context_tokens`, `embedding_dimension` (nullable until observed), `acceleration_mode` (`auto`/`cpu`), and expected runtime environment values. Reject unknown fields and unresolved required values for a full check. No private data or credentials. |
| Diagnostic endpoint/deadlines | Required `--config` loads the actual application config; no independent default endpoint that could hide override drift. Proposed `--runtime-config`, `--metadata-only`, `--json`; optional `--output` must point outside source. Use bounded 5-second metadata requests and 120-second active requests, one attempt each, with a finite overall deadline (proposed 300 seconds). Report timeouts; do not claim CPU support from a timed-out call. |
| LLM configuration handoff | Record actual identifiers/digests/dimension and tested smoke context. Preserve `ModelProviderSettings` names and URL precedence. Its 8192-token default is not a hardware recommendation; generation sends its effective context explicitly. Document that application ceilings need coordination with MODEL-02. Do not add `num_gpu` or `keep_alive` to LLM-01's generation-settings allowlist just to control the server. |

Server settings are applied to the **server process**, not merely the client terminal. For the default account app, snapshot and set only the named User environment values, fully quit Ollama, then relaunch. For a diagnostic foreground server, set process variables in its PowerShell session and ensure the tray server is stopped. Do not change Machine environment values or run two servers on the same port. Changing the app `data_root` does not relocate the Ollama cache.

The resource plan is to load one small model at a time, use one short generation request and a tiny embedding batch, release loaded models, and leave capacity for Windows and the application. Record free RAM/disk before loading; stop on memory pressure or allocation failures. Disk model size is not peak RAM/VRAM consumption. No throughput comparison, context sweep, automatic timeout escalation or hardware purchase is part of acceptance.

## MODEL-01-S01 — Establish host compatibility and the installation decision

**Objective / requirements:** establish a reproducible native setup path without assuming acceleration. R07, R14, R15.

**Dependencies / inputs / outputs / ownership:** no preceding story. Inputs are this plan, current official documentation, and read-only host inventory. Outputs are the compatibility section and a pre-change inventory in the runbook/handoff. Owns no driver installation or application logic.

**Tasks**

1. Record Windows edition/build and OS/process architecture, CPU model/instruction compatibility, total/available RAM, each GPU's exact identity, driver and dedicated VRAM, disk free space, and execution account. Use native inventory such as `Get-CimInstance Win32_OperatingSystem`, `Win32_Processor`, and `Win32_VideoController`; use vendor tools only if already available. Do not trust `AdapterRAM` alone for accurate VRAM reporting.
2. Detect an existing Ollama executable, installation method, client/server versions, listening process, model inventory/location, environment overrides and login entry. Preserve existing unrelated models/settings. Distinguish PATH discovery failure from an absent executable or offline server.
3. Match the OS/architecture and actual GPU against the release and official Windows tables. For NVIDIA, resolve compute capability using the linked vendor table and the applicable driver floor. For AMD, distinguish Windows ROCm from Vulkan support. For Intel/other/unknown GPUs, require documented backend support and a live test before claiming acceleration.
4. Select an official stable Windows installer/build during implementation. Record exact version, official download URL, downloaded SHA-256, publisher signature verification and architecture. A locally computed hash records the artifact; it is not independent publisher authentication. Record minimum required API/features and reject an incompatible version without treating it as a missing model.
5. Produce the branch decision: supported CPU baseline; optional supported acceleration; or unsupported/unverified host with a concrete reason. Do not assume an x64 package works on ARM64 through emulation. Do not install a CUDA toolkit, ROCm stack or alternate runtime merely because a GPU is present.

**Acceptance criteria**

- A machine described only as “4 GB GPU” is recorded as unverified; a matching vendor/model/driver plus observed placement is required for an acceleration claim.
- An unsupported GPU with a supported CPU leads to the CPU setup branch, not failure of the whole runtime plan.
- An unsupported OS/architecture or missing compatible CPU runner blocks live readiness with an actionable requirement; it does not trigger hosted inference, WSL or Docker.

**Verification:** inspect the inventory and compatibility sources; exercise unsupported/unknown inventory fixtures. Record actual Windows results separately from fixture outcomes. No benchmark or stress test.

**Configuration / recovery impact:** read-only inventory, no migration. Save only relevant pre-change values locally; sanitized compatibility facts and pending decisions go in the handoff.

## MODEL-01-S02 — Install and configure a local-only manual runtime

**Objective / requirements:** provide one manually started native server on verified loopback. R14, R15; supports R07.

**Dependencies / inputs / outputs / ownership:** depends on S01. Inputs: approved setup choices, existing FND-01 config and inventory. Outputs: installation/start/stop instructions and the environment/configuration mapping in the runbook. This story covers future installation; the present planning task does not execute it.

**Tasks**

1. Document downloading and running the selected official `OllamaSetup.exe` under the intended account, including a quoted `/DIR` override if needed. Reuse a compatible existing installation. Verify the installed binary path and version; do not rely only on PATH or install a service wrapper.
2. Capture previous values of each touched User/process environment setting, including whether it was absent. Apply the configuration table before first controlled launch. Do not overwrite unrelated `server.json` settings or environment variables. Disable the installer's login startup entry for this manual-operation setup if it was newly introduced; preserve the recorded prior state of an existing installation.
3. Fully quit an existing tray instance before starting the configured app or `& $ollamaExe serve`. Quote the discovered absolute executable path. Document tray Quit versus foreground Ctrl+C; closing a client shell does not necessarily stop the tray server.
4. Validate the application config offline, then compare the effective endpoint with the listener. Check all IPv4/IPv6 listeners on the port and their owning PID/executable using `Get-NetTCPConnection`. Reject `0.0.0.0`, `::`, LAN binds or an unrelated process even if localhost responds. Do not kill an unknown process to resolve a conflict.
5. Verify cloud-disabled state through effective settings/startup evidence. Keep `OLLAMA_ORIGINS` unexpanded; CORS is not an access-control substitute. Do not add firewall exceptions, remote listeners or reverse proxies.

**Acceptance criteria**

- A second local PowerShell session reaches the intended server; its listening address is exclusively configured loopback and PID ownership is established.
- A provider URL override pointing to another local port is reported as config/listener mismatch instead of checking the default port and claiming success.
- Restarting manually retains the selected bind/cache settings. A port conflict, stale environment or unsupported version gets its own diagnosis.
- Existing `config check` remains offline and succeeds without installing or starting the runtime.

**Verification:** test config precedence and listener snapshots with fakes, then inspect a real native listener and perform a bounded metadata probe. Test non-loopback rejection with fixtures rather than deliberately exposing a real server. A LAN connection test is optional supplementary evidence; listener inspection is required.

**Configuration / recovery impact:** User/process environment and account installation only; no new AppConfig meaning. Restore saved environment/startup values and stop the identified server on setup failure. Do not infer unattended readiness from manual success.

## MODEL-01-S03 — Establish storage and explicit models for both capabilities

**Objective / requirements:** make generation and embedding available independently, with reproducible local model identities. R07, R14, R15.

**Dependencies / inputs / outputs / ownership:** depends on S01–S02. Inputs: cache path, capacity, selected runtime and proposed smoke models. Outputs: validated setup manifest, installed-model inventory and storage/recovery runbook. No RAG index or application prompt configuration.

**Tasks**

1. Validate cache path containment outside source, local disk capacity, account read/write permissions and spaces/non-ASCII handling. Detect aliases/reparse points that would place it inside source. Prefer an account-private directory; do not grant Everyone access. Confirm the running server uses this path, not an old account cache.
2. Estimate required free disk from installer/unpacked binaries, selected weight downloads, temporary/update space and an explicit spare-space reserve. Record the estimate and observed free space; stop before downloading if inadequate. Do not assume 16 GB RAM implies sufficient disk space.
3. Proposed **smoke-only** choices: `qwen2.5:1.5b` for generation (registry lists about 986 MB) and `all-minilm:22m` for embeddings (about 46 MB, embedding-only). Recheck tag details, quantization and license before use; record full observed digests rather than the registry's short IDs. These modest artifacts reduce setup demands but do not prove RAM/VRAM fit or application quality. [Qwen tag](https://ollama.com/library/qwen2.5:1.5b), [embedding tag](https://ollama.com/library/all-minilm:22m).
4. Download explicitly with `ollama pull <exact-tag>` as a setup step, serially. Separate download/network/TLS/proxy failure from local service failure. Never have health checks pull automatically, select the first model, use `latest` implicitly, or fall back to a cloud model.
5. Query inventory and model details to verify generation `completion` and embedding capability separately. Record tag, digest, size, quantization, capability and context metadata. Record the embedding dimension from a successful response; do not invent it from the model name. Inventory digest is inventory evidence, not an invented response field.
6. Keep generation smoke context at the proposed 2048 limit or lower supported limit. Respect the embedding model's separate limit (the proposed small embedding tag documents 256 tokens); use only short synthetic input. Do not set every model to the generation ceiling. Unload between operations; both models must be installed, not simultaneously resident.
7. For an existing cache relocation: stop Ollama; record original paths/inventory; copy to a verified destination without deleting the source; switch `OLLAMA_MODELS`, restart, and verify both capabilities/digests. Only offer removal of the old copy after successful verification and explicit selection of that exact directory.

**Acceptance criteria**

- Empty inventory with a working service reports both models missing. A generation-only installation reports embedding unavailable without invalidating generation health.
- Wrong capability, mismatched digest, incomplete download, unwritable cache and insufficient disk produce different actions. None causes automatic deletion of all weights.
- A path such as `C:\Users\Example\AppData\Local\Model Daten Prüfung ä` works from a different working directory on native Windows.
- After initial downloads, both smoke operations succeed with external connectivity unavailable while retaining loopback access; use an isolated test condition without changing unrelated network policy.

**Verification:** synthetic inventory/capability/digest/path tests, followed by native sequential downloads and live smoke checks from S04. Record offline-after-download evidence separately. MODEL-02 selection remains pending.

**Configuration / recovery impact:** new model cache and manifest; no application-data migration. Restore the old cache pointer if relocation fails. Preserve inventory/digests for re-download; tags can change and old digests may cease to be downloadable, so archive exact artifacts when reproducibility requires them. Coordinate backup inclusion explicitly with OPS-01 rather than assuming its backup covers this separate cache.

## MODEL-01-S04 — Implement layered health diagnostics with honest results

**Objective / requirements:** identify what is usable and why a failure occurs. R07, R14, R15; supports R16.

**Dependencies / inputs / outputs / ownership:** depends on S02–S03 interfaces; fake-based work can start without a live service. Owns the proposed diagnostic script/tests and report format. It does not replace LLM-01's application harness or alter its existing domain smoke script.

**Tasks**

1. Validate app/manifest configuration before any network call. Reuse effective endpoint precedence and loopback validation; use direct connections, no proxy or redirects, bounded body sizes and finite deadlines for GET as well as POST. Never infer the server environment from a client shell's environment alone.
2. Probe in layers: executable/version and listener identity; `/api/version`; `/api/tags`; `/api/show` for each selected model; explicit generation; explicit embedding; placement evidence where available. Continue independent capability checks when safe. A failed runtime makes dependent checks `not_tested`, not `missing_model`.
3. Generation probe: POST `/api/generate` with the explicit generation tag, `stream:false`, bounded `num_predict` (proposed 16), and `options.num_ctx` from the smoke limit. Use a fixed non-sensitive greeting as protocol-test input, without domain instructions or an application schema. Require successful HTTP/JSON, `done:true`, expected model identity and nonempty response; do not require exact wording.
4. Embedding probe: POST `/api/embed` with the explicit embedding tag, two short synthetic strings, `truncate:false`, and immediate unloading. Require exactly two nonempty vectors, finite numeric values, equal dimensions and the configured dimension if present. Do not print vectors or input text. Missing API route and missing selected weights are distinct diagnoses.
5. Read digests from inventory before and after checks; fail readiness on changed/mismatched identity. If inference responses omit digest, keep it null and label inventory provenance separately. Do not claim this proves per-call weight identity against concurrent external model replacement. Serialize setup and avoid concurrent model mutations.
6. Emit human-readable output and JSON report v1.0: UTC timestamp, effective URL, server/client versions, listener evidence, per-layer status/reason, per-capability tag/digest/dimension, expected versus observed acceleration, safe remediation and check mode. Unknown evidence remains unknown. Save reports only when requested, outside source; keep raw runtime logs local and sanitize excerpts.
7. Proposed exits: **0** both capabilities passed, including a verified CPU-only result; **2** invalid/incomplete configuration or unsafe binding; **3** runtime unavailable/incompatible; **4** missing/wrong/mismatched model; **5** execution/capacity/acceleration failure; **6** metadata-only or otherwise incomplete verification. On multiple failures retain all reasons and select exit precedence 2, 3, 4, 5, 6. A skipped check never counts as passed.

**Diagnostic decision table**

| Observation | Stable reason / result | Recovery action |
|---|---|---|
| No resolved executable | `runtime_not_installed` or `runtime_path_invalid` | Distinguish missing software from wrong manifest/PATH; use installation instructions. |
| Binary exists, no listener / refused connection | `runtime_not_running` | Start the identified runtime manually; inspect launch failure. |
| Wrong PID, non-loopback bind, endpoint drift | `port_conflict`, `unsafe_binding`, `endpoint_mismatch` | Correct ownership/configuration before model calls. |
| Runtime version/route incompatible or malformed metadata | `runtime_incompatible` / `runtime_response_invalid` | Verify chosen release/API; do not download random models. |
| Healthy inventory lacks selected tag | `generation_model_missing` / `embedding_model_missing` | Explicitly pull that model in setup, or correct its identifier. |
| Tag exists, unsupported capability or changed digest | `model_capability_mismatch` / `model_digest_mismatch` | Correct model/config; retain the existing artifact until resolved. |
| GPU unsupported, CPU call succeeds | `ready_cpu`, acceleration `unsupported` | Ready with CPU limitation clearly visible. |
| GPU initialization fails, CPU succeeds | `ready_cpu`, acceleration `failed` | Preserve the acceleration diagnosis; optional driver/backend repair can follow. |
| GPU fails and CPU has not passed | `acceleration_failed`, fallback `unverified` | No ready status; execute S05 or record the blocker. |
| RAM/VRAM allocation or disk failure | `memory_capacity` / `storage_capacity` | Unload, free appropriate resources, check path/space; no automatic model enlargement. |
| Timeout, busy server or unexplained runner failure | `request_timeout`, `runtime_busy`, `execution_failed` | Inspect bounded evidence; never label GPU failure solely from HTTP 500. |
| Embedding route works but invalid shape/values | `embedding_response_invalid` | Check model/runtime compatibility; not proof of missing weights. |

**Acceptance criteria:** fixtures demonstrate every branch, including empty inventory, generation success/embedding failure, response without digest, redirects, proxy environment, malformed/oversized responses and deadline expiry. A healthy metadata endpoint alone yields incomplete readiness. Raw candidate text, synthetic secret sentinels, prompts, output and vectors do not appear in ordinary reports. Diagnostic checks cause no installation, model pull/removal, config rewrite, worker start or Salesforce activity.

**Verification:** run diagnostic unit tests plus affected existing configuration, transport and diagnostic tests. Exercise the real native service with the exact two models. Stopped-server and deliberately nonexistent-tag tests are sufficient live negative cases; use fixtures for unsafe exposure and resource exhaustion.

**Configuration / recovery impact:** local diagnostic manifest/report versions only. Reuse existing `ClassifiedError` categories if exposing errors to callers, with diagnostic reasons in details; no new shared error enum or C10 migration is implied. Report runtime readiness separately from any remaining LLM-01 application integration issue.

## MODEL-01-S05 — Demonstrate supported CPU fallback and acceleration reporting

**Objective / requirements:** keep a usable local path when the GPU is unsupported or fails. R07, R14.

**Dependencies / inputs / outputs / ownership:** depends on S01–S04. Inputs: real hardware/runtime inventory and smoke models. Outputs: a tested CPU launch recipe and optional acceleration result in the runbook/handoff. This is a functional placement check, not a performance comparison.

**Tasks**

1. Start from runtime autodetection on supported hardware. Keep unsupported/unknown acceleration explicitly marked; do not install compatibility hacks or force a different AMD architecture. Capture observed CPU/GPU/mixed placement during each loaded model using `ollama ps`, `/api/ps` and relevant runner startup evidence.
2. For placement inspection only, use a short explicit residency override (proposed 30 seconds), inspect while loaded, then unload before testing the other model. Restore immediate unloading afterwards. An empty `/api/ps` after unloading means unknown placement, not CPU success.
3. Stop the runtime before applying a CPU diagnostic profile. For NVIDIA the official hardware guide documents hiding devices with `CUDA_VISIBLE_DEVICES=-1`; disable Vulkan as well so another GPU backend cannot satisfy the test. On AMD/mixed systems do not assume that a Linux visibility variable disables all Windows backends. Use a documented CPU library override only if the exact installed build provides it, or another release-documented CPU selection mechanism. Record the precise tested mechanism and source. [GPU selection](https://docs.ollama.com/gpu), [CPU library overrides](https://docs.ollama.com/troubleshooting).
4. If an override is ignored, unavailable or unsupported by the CPU, report `cpu_fallback_unverified`/`cpu_backend_unsupported`. Do not claim success based on environment values alone. Require both functional probes and observed CPU placement. No mandatory GPU driver upgrade is needed to accept a verified CPU path.
5. Restore the original backend environment on leaving a temporary diagnostic session. If CPU is the chosen operating mode, persist only the proven settings and document that choice. Repeat the same short probes after a manual restart.

**Acceptance criteria:** an unsupported GPU with both CPU probes passing is ready with acceleration unavailable. A GPU runner failure followed by CPU success retains both facts. A CPU timeout/OOM is a failure, not a recommendation to use paid inference. CPU-only success is acceptable; successful GPU placement is not mandatory. If no supported CPU mechanism is demonstrated, this story remains pending with the exact blocker.

**Verification:** fake unknown/unsupported/failed/mixed placement cases plus native CPU generation and embedding. Optional accelerator test only on compatible hardware; absent hardware is explicitly not tested. Record functional success and placement, not tokens/second, comparative timings or quality claims.

**Configuration / recovery impact:** backend selection is a runtime setting, not application prompt data. Snapshot/restore only touched environment values, restart, and repeat metadata/binding checks after changing mode.

## MODEL-01-S06 — Verify recovery, removal and the component handoff

**Objective / requirements:** make setup reversible and readiness reviewable. R07, R14, R15; supports R16.

**Dependencies / inputs / outputs / ownership:** depends on S01–S05. Outputs: complete runbook and `docs/components/MODEL-01.md`, recording actual status and downstream interfaces. No production uninstall is required just to complete verification.

**Tasks and recovery instructions**

1. **Normal restart:** stop only the identified project runtime, retain config/cache, relaunch under the same account with the same environment, verify bind/version/inventory, then run both probes. A process restart must not require downloading unchanged weights.
2. **Interrupted download or corrupt model:** retain healthy models; inspect disk/path permissions and the specific failed artifact. Retry the exact pull explicitly. Remove/re-pull only that selected model if needed, recording any changed digest. Do not recursively clear the whole cache or alter application indexes; pass incompatible embedding changes to their owner.
3. **Update failure:** record old/new runtime versions and recheck binding, cloud-disabled state and APIs after every update. Preserve a known-good official installer and pre-change settings/inventory for rollback where supported. If the new build fails, stop it and reinstall the selected compatible prior build; verify model-format compatibility before reuse. Do not promise downgrades support every newer model. No automatic update task is added.
4. **Storage move failure:** stop the runtime, restore the original `OLLAMA_MODELS` value, restart, verify original digests and both probes. The source copy remains until the destination is proven. Never delete a path computed from an empty/malformed variable.
5. **Uninstall runtime:** quit the tray app/foreground server, confirm its PID/listener is gone, then use Windows Settings → Apps → Installed apps/Add or remove programs → Ollama → Uninstall for the installer deployment. For a selected standalone deployment, remove only its recorded extracted directory after stopping it. The Windows uninstaller does not remove models at a custom `OLLAMA_MODELS` location. [Official uninstall guidance](https://docs.ollama.com/windows).
6. **Retain or remove models separately:** default to retain for recovery. While the server is available, `ollama rm <exact-tag>` removes a selected disposable model. For complete removal after uninstall, first enumerate and show the resolved absolute project cache path; verify it equals the recorded cache, lies outside source/application evidence, is not a drive/profile root and has no unexpected reparse target. Delete only that explicitly selected directory with native PowerShell `Remove-Item -LiteralPath` if removal was requested. Never remove all of the user's `.ollama` directory or unrelated keys/config/models.
7. **Restore settings:** restore recorded prior User/process environment values, remove only values introduced by this setup when no previous value existed, and restore the prior login entry state. Verify no orphan project listener/process remains. Preserve application database, evidence, indexes and generated documents. Retain a sanitized manifest and provenance for recovery; do not publish raw logs or local account paths.
8. Complete the handoff checklist below, with exact command results, failures and pending checks. A documented uninstall review may be recorded as reviewed; a disposable-install uninstall/reinstall exercise must be recorded separately if actually performed.

**Acceptance criteria:** manual restart preserves identity and local availability; failed relocation can return to the intact original cache; removal instructions distinguish binary/cache/application data and preserve existing user assets. Mock/fake results do not satisfy native/live gates. `verified` requires both APIs and supported CPU fallback demonstrated; optional acceleration may remain unsupported or untested.

**Verification:** perform a non-destructive restart; validate removal paths and recovery steps without deleting the working installation. If a disposable native installation/cache is available, exercise removal/reinstall there and retain exact results. No reboot/scheduler test or benchmark.

**Configuration / migration impact:** no shared-schema or database migration expected. If implementation discovers a required shared-contract change, record its compatibility/schema/consumer plan before changing it; do not silently redesign FND-01 or LLM-01.

## Verification sequence and completion gate

Commands below are **future implementation verification**, not commands executed during planning. Use absolute paths derived once from the actual checkout; manifest/config placeholders must be replaced with validated local files. The proposed diagnostic flags do not exist until S04 is implemented.

```powershell
# Run initially from the actual repository root.
$repoRoot = (Get-Location).Path
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$appConfig = Join-Path $repoRoot 'config\local.model-runtime.json'
$runtimeConfig = Join-Path $repoRoot 'config\local.model-runtime-manifest.json'
$healthScript = Join-Path $repoRoot 'scripts\model_runtime_health.py'

# Existing offline command; never starts or installs Ollama.
& $pythonExe -m job_automation config check --config $appConfig

# Proposed tests after implementation; no runtime dependency for these tests.
& $pythonExe -m pytest tests\models\test_runtime_health.py tests\models\test_configuration.py tests\models\test_local_transport.py tests\models\test_safe_diagnostics.py tests\test_configuration.py

# Proposed metadata check exits 6 when healthy but active tests are unperformed.
& $pythonExe $healthScript --config $appConfig --runtime-config $runtimeConfig --metadata-only --json

# Full functional readiness: require exit 0 and both capability results passed.
& $pythonExe $healthScript --config $appConfig --runtime-config $runtimeConfig --json
$healthExitCode = $LASTEXITCODE
```

Run the full check in the established normal profile and the supported CPU profile, one at a time. Repeat with absolute paths from another working directory and with a spaces/Unicode cache path. Inspect actual sockets separately (default-port example: `Get-NetTCPConnection -State Listen -LocalPort 11434`); an environment declaration is not listener evidence. Keep native OS, PowerShell, Python, runtime version and test results in the record. Broaden application tests only if implementation changes shared code.

| Gate | Required evidence |
|---|---|
| Offline diagnostic checks | Meaningful fixtures for config, safe networking, missing models, capability/digest mismatch, acceleration distinction, response validation and exit semantics. |
| Native installation/configuration | Actual supported Windows/architecture, explicit executable/cache paths, actual listener PID and loopback addresses, local-only runtime settings, restart behavior. |
| Live runtime capability | Explicit generation and embedding models both pass; metadata-only, skipped or wrong-model checks cannot satisfy this gate. |
| CPU / acceleration | Supported CPU fallback passes both operations with observed CPU placement. GPU support and observed placement are recorded separately, including unsupported/failed/unknown states. |
| Recovery | Restart evidence, reviewed uninstall instructions, cache relocation rollback instructions and model identity preservation. Destructive rehearsals accurately marked performed or not performed. |

Implementation handoff checklist:

- Component/story statuses, requirements, owned files, source check date and versioned diagnostic interfaces.
- Exact runtime version/artifact provenance, host compatibility and execution account context (sanitized), configuration precedence and pre-change restoration procedure.
- Verified endpoint/binding/cloud-disabled state, absolute executable/cache conventions, free-space assumptions and limits of RAM/VRAM evidence.
- Separate generation/embedding identifiers, full inventory digests, observed dimension, smoke context and CPU/backend settings; no assertion that these are MODEL-02 recommendations.
- Commands, exits and actual results for unit/fake, native Windows, live generation, live embedding, CPU fallback, optional GPU and recovery checks; all unavailable checks explicitly pending.
- LLM-01 follow-up: application integration remains its own gate; note the existing smoke-script limitations, response-digest gap and embedding truncation behavior without implementing prompt/client redesign here.
- MODEL-02 follow-up: runtime is available for later model/context selection; benchmarks and application quality are not established by health probes.
- Known limitations and safe next actions. Do not claim the entire G0/G2 gate, application pipeline, Phase 0 or Phase 2 is complete from MODEL-01 readiness.
