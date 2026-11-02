# MODEL-02 — Model and context benchmarks

Status: **PLANNED** · Planning date: **31 October 2026** · Component: **MODEL-02 only** · **Phase 0, with deferred Phase 1 extensions**

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially §§2–9 and the MODEL-02 catalog entry. Direct requirements: **R07, R13, R14**; supporting boundaries: **R06, R15, R16**, and **R11** for Phase 1. Contracts: C01/C02/C06/C08/C09/C10/C11; C13/C14 only in the later drafting extension.

This document specifies future implementation and measurements. **No benchmark, runtime installation, model download, hardware probe, or application test was run for this planning task. No model is selected for production and no measured result is asserted.** Candidate sizes and context capacities below are published specifications, not local observations.

## Scope and repository evidence

Deliver reproducible generation/embedding measurements and evidence-backed configuration recommendations for the confirmed **16 GB RAM / 4 GB VRAM native Windows** target. Begin with small quantized candidates, measure CPU operation and supported GPU placement, and retain failures as results. Exact CPU, GPU vendor/model, driver, available RAM/VRAM, and acceptable task latency remain unverified. Use local inference and zero-cost tooling; no mandatory Docker, WSL, hosted model, paid inference, or hardware purchase.

MODEL-02 owns the hardware experiment manifest, resource/timing instrumentation, model comparison records, reproducibility instructions, and recommendations. EVAL-01 owns its corpus, gold labels, paired runner, metrics, review workflow and reporting framework. MATCH-02/GEN-03 own application prompts; CONTEXT-01–04 own context construction, chunking, indexes and retrieval. MODEL-01 owns runtime installation, health, backend compatibility and launch recipes. No Salesforce publication, production index activation, prompt redesign, scheduler or automatic drafting is part of this component.

Instructions read: [README](../../README.md), the complete blueprint and [schema instructions](../../schemas/README.md). No applicable `AGENTS.md` was found in the repository documentation path or inspected ancestors; the user-level `.codex/AGENTS.md` is empty. Generate shared schemas from typed models if a separately coordinated contract change becomes necessary; do not edit generated JSON schemas directly. Runtime artifacts belong outside source, under explicit absolute Windows paths.

| Inspected evidence | Consequence for these stories |
|---|---|
| [MODEL-01 stories](MODEL-01.md) | Setup is planned. **`docs/components/MODEL-01.md` does not exist** at planning time. Its proposed health script/configuration are not installed capabilities. Live benchmarks depend on its actual handoff, including CPU launch and optional acceleration evidence. Offline benchmark tooling can proceed. |
| [LLM-01 handoff](../components/LLM-01.md), [provider](../../src/job_automation/models/provider.py), [audit records](../../src/job_automation/models/records.py) | Provider and audit interfaces exist; handoff reports offline checks with live verification pending. Reuse `LocalModelProvider`, bound inputs, local schema registry and audit recorder. Its lock is per provider instance, not cross-process exclusion. Historical test counts do not prove benchmark readiness. |
| [Generation harness](../../src/job_automation/models/generation.py), [settings](../../src/job_automation/models/settings.py) | Sends schema `format`, `stream:false`, and `options.num_ctx`. Allowlist includes `num_predict`, but not `think`, `num_gpu` or `keep_alive`; those must not be smuggled into decoding settings. The harness treats `done_reason='length'` as context exhaustion; measurement must distinguish an output cap from proven input overflow. Detailed runtime phase timings are not preserved in C10. |
| [Embedding harness](../../src/job_automation/models/embeddings.py) | Sends model/input only: no explicit `truncate:false`, dimension selection, context option or residency override. Published API defaults can therefore truncate silently. Response digests are optional and checked only when present. Current behavior is a live-readiness gap, not a proven no-truncation guarantee. |
| [Budget implementation](../../src/job_automation/models/budget.py) | Default character/3.5 estimate is not a verified upper bound for German, identifiers or arbitrary Unicode; `ExactTokenCounter` defaults to whitespace counting. Preflight counts prompt/system plus reserve/margin, without proving complete rendered-template overhead or aligning reserve to every requested output cap. Neither implementation name establishes exact model token accounting. |
| [EVAL-01 handoff](../components/EVAL-01.md), [CLI](../../src/job_automation/evaluation/cli.py), [runner](../../src/job_automation/evaluation/runner.py), [arm adapter](../../src/job_automation/evaluation/assessment_adapter.py) | Framework exists and accepts an injected `AssessorV2`. Current CLI run/resume constructs no live assessor; run supplies an all-zero placeholder digest. Runner ordering uses Python `hash(case_id)`, which can vary across processes. Do not present ordinary CLI output as live measurements or assume its seed alone reproduces order. Route fixes to EVAL-01; validate actual call traces against declared controls. |
| [EVAL manifests](../../src/job_automation/evaluation/records.py), [symmetry checks](../../src/job_automation/evaluation/manifest_validation.py), [composition](../../src/job_automation/evaluation/composition.py) | Reuse isolated EVAL storage and publication firewall. One JSON/RAG pair must keep model/settings/profile/policy constant. Separate experiments compare models. Default gate objects and matching manifest dictionaries are not evidence that actual wire requests used those controls. |
| [Embedding configuration](../../src/job_automation/contracts/retrieval_index.py), [index embedding](../../src/job_automation/context/index_embeddings.py), [query embedding](../../src/job_automation/context/query_embeddings.py) | Existing configuration records identity, dimension, prefixes, normalization-related options, versions and batch limits. Prefixes are applied by consumers. Declaring `output_affecting_options` does not prove the provider sent them. Rebuild isolated indexes on incompatible identity/config changes; never reuse one model's vectors for another. |
| [GEN-03](../components/GEN-03.md), [GEN-04](../components/GEN-04.md), [GEN-05](../components/GEN-05.md), blueprint C14 decision | Generation code/handoffs now exist, despite the older EVAL handoff saying these prerequisites did not exist. Current C14 content is schema 2.0 with conservative extractive recipes; live quality and native PDF/visual checks remain pending. EVAL S09/S10 are still deferred. Phase 1 measurements require refreshed owner gates, not an assumption that generation is absent or fully verified. |

Documentation validation found no broken local links. The repository's `.venv/Scripts/python.exe` could not launch its referenced Python312 interpreter when invoked for a documentation check; the check was completed with PowerShell instead. Revalidate/repair the native Python environment through FND-01 before implementation checks. This observation does not establish any application test result.

## Official sources and initial candidates

Checked **31 October 2026**. These are a small, tractable starting comparison, not a claim to cover every current model or identify the best one. Recheck exact artifacts and release compatibility at implementation. Do not use mutable `latest` tags as identities.

| Lane / initial order | Official artifact and published details | License / application caveat |
|---|---|---|
| Generation G-A, first | [`qwen3:0.6b`](https://ollama.com/library/qwen3:0.6b), Q4_K_M, published download 523 MB. Upstream [Qwen3-0.6B card](https://huggingface.co/Qwen/Qwen3-0.6B) specifies 32,768-token context and thinking/non-thinking modes. | [Apache-2.0 license](https://huggingface.co/Qwen/Qwen3-0.6B/blob/main/LICENSE). Start at 2,048 configured context; published maximum is not a tested operating limit. |
| Generation G-B, after G-A preflight | [`qwen3:1.7b`](https://ollama.com/library/qwen3:1.7b), Q4_K_M, published download 1.4 GB. [Upstream card](https://huggingface.co/Qwen/Qwen3-1.7B) specifies 32,768-token context. | [Apache-2.0 license](https://huggingface.co/Qwen/Qwen3-1.7B/blob/main/LICENSE). Same initial controls; no assumption of full GPU residency. |
| Embedding E-A, multilingual candidate | [`qwen3-embedding:0.6b`](https://ollama.com/library/qwen3-embedding:0.6b), Q8_0, published download 639 MB. [Upstream card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) specifies 32K context, up to 1,024 dimensions and multilingual support. | Card declares Apache-2.0. Query instructions and document formatting differ; freeze their exact strings. The library page's generic 8B description is not the 0.6B dimension specification. Verify packaged license/provenance before admitting the downloaded artifact. |
| Embedding E-B, tiny baseline | [`all-minilm:22m`](https://ollama.com/library/all-minilm:22m), F16, published download 46 MB and `num_ctx:256`. [Upstream all-MiniLM-L6-v2 card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) describes 384-dimensional sentence embeddings and default truncation beyond 256 word pieces. | Apache-2.0 in card and runtime library. This is an explicitly **unquantized small baseline**, with an English-focused card, not an assumed German retrieval solution. Test German/cross-language cases and reject overlength inputs. |

Ollama's generation artifact pages report parameter counts differing from upstream model names/cards (752M versus 0.6B; 2.03B versus 1.7B). Retain both source descriptions and inspect actual `/api/show` metadata; do not infer the local weight layout from the name. Published MB/GB are not GiB, process memory, KV-cache size, or peak VRAM. Website short digest prefixes are not reproducibility pins.

| Runtime evidence | Benchmark consequence |
|---|---|
| [Official release](https://github.com/ollama/ollama/releases/tag/v0.40.13) | The official latest-release endpoint resolved to v0.40.13 during this check. This is not an installed version or a mandatory upgrade. MODEL-01 selects/verifies the actual Windows build; MODEL-02 records and freezes it for each experiment. |
| [Windows requirements](https://docs.ollama.com/windows), [GPU compatibility](https://docs.ollama.com/gpu) | Native Windows 10 22H2+ is documented. Windows NVIDIA minimum is 551.61; compute capabilities 5.0–6.2 require the higher 570+ floor. AMD support is backend/device-specific. MODEL-01 must reconcile the exact host with the current tables. 4 GB VRAM alone proves neither support nor fit. |
| [Configuration FAQ](https://docs.ollama.com/faq) | Context, parallelism, model residency and backend settings affect memory. `ollama ps` distinguishes CPU/GPU/mixed placement. Apply environment changes to the server process and restart as required; preserve and restore the original profile. Do not rely on changing only a client shell. |
| [Generate API](https://docs.ollama.com/api/generate), [structured outputs](https://docs.ollama.com/capabilities/structured-outputs) | JSON Schema can be supplied through `format`; validate locally too. `think` is a top-level request control whose supported values/default come from `/api/show`. Completion responses expose counts and nanosecond durations. Schema compliance does not establish factual accuracy. |
| [Embed API](https://docs.ollama.com/api/embed) | Explicit `truncate:false` is necessary for runtime overflow errors. Supports batch input, dimension option and residency; verify support on the pinned model/build. Embedding timing/count fields differ from generation; do not invent decode throughput. |
| [Installed inventory](https://docs.ollama.com/api/tags), [model details](https://docs.ollama.com/api-reference/show-model-details), [loaded inventory](https://docs.ollama.com/api/ps) | Capture full installed digests, capabilities, template/parameters and loaded context/VRAM allocation. Loaded allocation is not total board usage or an observed peak. Generation/embed API responses do not guarantee a digest. |
| [Ollama license](https://github.com/ollama/ollama/blob/main/LICENSE), [Apache-2.0 terms](https://www.apache.org/licenses/LICENSE-2.0) | Ollama source uses MIT; shortlisted model sources declare Apache-2.0. Keep runtime, bundled third-party components, tokenizer and model licenses distinct. Preserve applicable license/attribution notices; redistribution of modified Apache artifacts also requires change notices and applicable NOTICE material. Benchmark reports need not redistribute weights. |

License verification must record the exact source URL/revision, license identifier/text hash, attribution/NOTICE requirements, artifact conversion/quantization provenance and intended local use. The embedding card declares Apache-2.0, but its direct `LICENSE` URL was unavailable during this check; do not pretend the packaged file was inspected. Resolve that artifact-level evidence before use. A missing or conflicting license/provenance record leaves that candidate pending; it does not justify substituting an undocumented community quantization. Recheck any later candidate separately, including family variants with different licenses.

## Dependency gates and EVAL-01 coordination

| Gate | Owner / required evidence | What can proceed while pending |
|---|---|---|
| B1 — runtime readiness | MODEL-01 actual handoff: host inventory, loopback/local-only server, selected build/cache, separate generation/embed health, supported CPU launch profile, optional GPU/backend evidence. | Offline manifest/instrumentation tests and source research. No live fit claim. |
| B2 — application measurement fidelity | LLM-01: actual request controls and bounded attempts; explicit embedding no-truncation; model-aware token accounting or a documented validated bound; output cap/reserve consistency; thinking/default behavior and length-stop interpretation. MODEL-02 supplies reproducible cases/evidence, not a replacement client. | Clearly labeled raw-runtime synthetic probes. These cannot certify the application path. |
| B3 — controlled Phase 0 quality execution | EVAL-01/MATCH-02/CONTEXT-04: real assessor/provider/selector composition, actual identity and controls, frozen corpus/split, stable persisted execution order, isolated storage and no publication. Replace CLI placeholder behavior through EVAL ownership, or use the existing injected runner interface in an agreed MODEL-02 experiment entry point. | Resource microbenchmarks and embedding conformance. Quality recommendations stay pending. |
| B4 — embedding/retrieval binding | CONTEXT-02/03/04: frozen chunk set/query set, isolated index generations, exact prefixes/dimension/normalization/digests; EVAL-owned relevance labels and metric definitions. | Vector shape, latency, batch and memory measurements. No retrieval-quality conclusion. |
| B5 — Phase 1 readiness | GEN-02/03/04 compatible current services/recipes and EVAL-01 S09; GEN-05 plus EVAL S10 for rendered-artifact extensions. | Phase 0 completion; drafting remains separately deferred. |

No circular prerequisite: first measure a provisional embedding configuration on synthetic input, supply its exact identity/dimension to CONTEXT-03 for an isolated index, then use that index in controlled EVAL retrieval measurements. A provisional configuration is not the final recommendation. MODEL-02 supplies hardware/candidate/manifest evidence for EVAL's EG5; EVAL supplies quality evidence back to MODEL-02. Neither component marks the other's full acceptance complete. RUN production-export gates are required for production-history/rejected-population claims, not for an isolated synthetic benchmark.

Agree with EVAL-01 on corpus/label/split/metric versions, declared controls, experiment IDs, review coverage and artifact references before running comparisons. MODEL-02 attaches a versioned hardware sidecar joined by experiment/case/arm/repetition/call/attempt IDs. It must not fork EVAL schemas, implement a second reviewer workflow, or silently repair EVAL's runner. Route stable-order and CLI-composition gaps to that owner, with acceptance examples. If current manifests cannot faithfully represent a cohort's profile/policy controls, partition compatible cohorts or request an EVAL contract change before execution.

## Experiment contract and measurement protocol

The numerical settings in this section are **proposed starting controls**, not user thresholds or measured safe limits. Freeze them before observing comparative results; deviations require a new manifest/run, with a reason.

### Reproducibility record

Record at least:

- Experiment/schema version, UTC timestamps, code revision or source-tree hashes when Git metadata is unavailable, Python/dependency versions, exact commands and resolved configuration hashes. Use Europe/Berlin only for display.
- Windows build/architecture, CPU model/core/thread count, total/available physical RAM, pagefile/commit limits, GPU identity/driver/backend/dedicated and shared memory, power mode/AC state, storage, background-load notes and telemetry tool versions.
- Runtime executable/version/hash, server process identity, effective endpoint and model-cache location, local-only setting, server environment, parallelism, threads, residency, Flash Attention and KV-cache precision if supported. Record unavailable settings as unknown, not presumed defaults.
- Requested tag, full installed manifest digest, available weight/blob hashes, upstream revision and quantizer provenance; requested, inventory-observed and response-observed identities separately. Hash model template/parameters/tokenizer files and record their versions. Recheck inventory before/after each cell; refuse drift and never fill an absent response digest with a requested value.
- Exact requested/effective decoding options, `num_ctx`, `num_predict`, output reserve, safety allowance, thinking mode, schema and prompt hashes, model-specific token counting method and overhead. Explicitly record omitted options and discovered defaults.
- Frozen corpus/split/case hashes, C01/C02/C06 versions, context strategy, complete C09 references, extractor/prompt/schema versions, chunk/index/query settings and embedding identity. Retain input/output payloads only in the isolated local workspace; use hashes and sanitized summaries in shared reports.
- Cold/warm state, persisted execution order, random seeds, repetitions, attempts/regenerations, result status, all timing/resource samples with units and collection provenance, stop reasons, and reviewer/metric artifact references.

A tag may move, a runtime may update, and equal seeds may still yield different output across backends. Reproducibility means reconstructing controls and quantifying repeated observations; it is not a promise of identical tokens or floating-point vectors.

### Staged matrix and execution controls

1. **Generation screening:** G-A then G-B, one model loaded and one request at a time. Begin at context 2,048, then 4,096; attempt 8,192 only if smaller cells meet the resource guardrails. No automatic sweep to advertised 32K. Add larger models or contexts only as a separately justified follow-up after small-model evidence.
2. **Placement:** run the MODEL-01 verified CPU-only profile and supported automatic GPU profile. Classify observed placement as CPU/full GPU/mixed/unknown using loaded-model metadata plus runner evidence. A mixed-offload cell is conditional on supported controls or observed runtime behavior; do not force an OOM to obtain one. If full GPU is unavailable, record it as unavailable and retain CPU/mixed results.
3. **Generation load:** use identical frozen text across models for task comparisons and a separate tokenizer-sized synthetic workload for capacity curves. Probe short, medium and near-budget inputs, plus exact-boundary/one-over cases where reliable counts exist. Include system/template/schema overhead and output reserve in the budget. Proposed microbenchmark output cap/reserve is 256 tokens with a 128-token initial margin; domain assessment uses MATCH-02's frozen supported output budget, not an arbitrary 256-token cap that cannot express its schema.
4. **Decoding:** propose non-thinking structured generation, fixed seed 42 and temperature 0 for a diagnostic baseline only. Freeze remaining sampling/stop defaults explicitly. Confirm that the selected runtime and provider actually disable thinking; otherwise record the observed/default mode and gate that comparison. Application quality uses owner-approved MATCH-02 settings; do not alter its prompts to optimize an individual candidate. A second thinking/sampling configuration is a separate experiment.
5. **Embedding:** E-A and E-B, one model at a time, CPU and supported GPU profiles, batch sizes 1 then 4 then 16 only while headroom permits. Use fixed texts and record actual model tokens/UTF-8 bytes. Common short-input cells must fit both tokenizers including prefixes/special tokens; longer 512/1,024/2,048-token cells apply only to supported candidates. MiniLM over-256 inputs are explicit overflow probes, not truncated quality samples. Dimension stays at the observed native output initially; dimension reduction is optional follow-up requiring verified runtime/provider support and a new index identity.
6. **Residency:** three measured model-cold requests per shortlisted cell, unloading and verifying absence from `/api/ps` each time; separately one excluded warm-up plus five measured warm requests with verified residency. Model-cold means unloaded weights, not cleared Windows disk cache. Keep that limitation explicit. Use a bounded warm residency profile, then unload; MODEL-01's immediate-unload smoke profile cannot establish warm performance. Record prompt-cache reuse, and distinguish repeated-prompt warm results from warm-model/new-case latency.
7. **Order and repetitions:** screen cheaply, freeze the shortlist, then use EVAL's counterbalanced serial JSON/RAG comparisons, proposed three repetitions per held-out case. Persist the order and use stable hashing/seed handling across process restarts. Runtime profiling and quality trials remain separate records. Repeated measurements of one case are not independent labeled cases.
8. **Operational bounds:** start with parallelism/max-loaded-models/max-queue all 1, explicit per-call total deadline 120 seconds and one attempt/no regeneration for first-pass diagnostics. Record runtime, transport and overall limits; a deadline is not a quality target. A longer CPU deadline or bounded regeneration comparison requires a predeclared separate cell, not an invisible retry. Serialize with other application work; per-instance provider locking is insufficient.

Before each cell, measure idle baseline and available capacity. Proposed stop guardrails: do not start/continue with less than **2 GiB available physical RAM** or **256 MiB free dedicated VRAM** for an accelerator cell; stop on allocation failure, observed commit pressure/persistent paging, watchdog expiry or unresponsive runtime. Freeze exact commit/paging thresholds and sampling rules after baseline inspection and before candidate comparisons. These reserves are cautious experiment controls, not OS-enforced caps or fit guarantees. Account for Python, index, telemetry, Windows and desktop GPU use. Cancel only owned requests/processes through the verified recovery recipe; retain the failed cell, restore runtime settings and verify recovery before continuing. Simulate severe OOM/cancellation cases offline rather than deliberately destabilizing the workstation.

### Required measurements and interpretation

| Dimension | Method and stored evidence | Limitation / reporting rule |
|---|---|---|
| Context admission and useful context | Compare provider preflight, actual wire `num_ctx`, `/api/ps` loaded context and runtime counts. Tokenize complete rendered input with pinned compatible tokenizer/template; validate against runtime observations on German, English, Unicode, IDs and schema-heavy cases. Place gold evidence at beginning/middle/end; test boundary and one-over input, and separate output-cap stops. | An accepted request or correct end sentinel alone cannot prove no truncation or useful long-context reasoning. Advertised, requested, observed, largest tested passing and recommended limits are separate fields. If exact accounting is unavailable, mark estimates and leave exact-boundary/no-truncation acceptance pending. Full JSON overflow remains an error, never silent trimming or RAG fallback. |
| Placement | Capture `ollama ps`, `/api/ps`, backend/runner logs while loaded and at phase transitions; correlate PID/device with telemetry. | A requested GPU setting is not observed offload; an empty loaded list after unloading proves no placement. GPU percentage does not measure compute utilization. Unknown/unsupported modes remain visible. |
| RAM and VRAM | Proposed 200 ms monotonic sampling from before load through unload: Windows available physical memory and commit, Ollama server/runner and Python working set/private bytes, board dedicated/shared usage and vendor counters where supported. Store raw samples, baseline, peak, sample gaps and collector overhead. | Process working sets may double-count shared pages; do not equate their sum with host consumption. `/api/ps.size_vram` is allocation metadata, not total board peak. Sampled peaks are lower bounds; missing vendor/WDDM counters are null with reason. Model file size is reported separately. |
| Latency and throughput | `perf_counter` around each logical call and physical attempt; collect runtime total/load/prompt-eval/eval durations in ns and convert explicitly. Generation prompt/decode rates use counts divided by their respective duration in seconds, only when both exist and duration is positive. Embeddings: batch wall time, texts/s, available input-token counts/rate, rebuild/query time separately. | C10 audit wall latency is available; detailed server durations require a passive transport observer or owner-provided metadata extension. It must forward bytes unchanged and log only allowlisted fields. Do not infer missing values by subtraction. Non-streaming provider cannot measure time to first token: report N/A; any future streaming probe is a separately labeled diagnostic. |
| Structured output | Count scheduled calls, preflight admissions, runtime completions, strict JSON parses, schema-valid outputs, domain-valid assessments, first-attempt successes, post-regeneration successes and all failures separately. Preserve done reason, length caps, refused/empty outputs and thinking-field behavior. | Schema-valid is not grounded. No JSON repair or dropping malformed runs. A rate among completed calls must also disclose scheduled/ineligible/failed denominators. Raw malformed output stays restricted to local evidence. |
| Assessment quality | Consume EVAL's eligible/review/rejected confusion/error metrics, evidence coverage/use, unsupported claims, stage attribution and blinded reviewer effort; include deterministic-only control cases. | Keep extraction, retrieval, ranking, packing and inference failures distinct. Unknown facts/retrieval misses are not confirmed lack of skills. Hard-rule rejection precedence remains intact. Model outage is failed/reviewable work, not candidate rejection. |
| Embedding quality | Use EVAL-labeled fact/query relevance; report recall@k and ranking metrics with declared k/metric version, language slices, raw semantic hits and hybrid hits separately via existing CONTEXT services. Record dimension, vector count/finiteness/norm, repeated-vector tolerance, ordering, index build time/size and query latency. | EVAL owns new metric definitions if needed. Keyword fallback can hide weak embeddings; neither shape validity nor upstream leaderboard scores establish retrieval quality. Changed prefixes, model/dimension/normalization or chunking require an isolated rebuild. |
| Summaries and uncertainty | Report per-cell sample count, median, min/max, failures/timeouts and raw references. Estimate p95 only with a declared method and adequate samples (proposed minimum 20); otherwise mark insufficient/exploratory. Use EVAL-approved case-grouped uncertainty for quality differences. | Do not pool CPU/GPU, cold/warm, context lengths or successful/failed trials into one average. Timeouts are censored observations, not successful latency equal to the timeout. No population accuracy claim from a small synthetic corpus. |

## Ordered implementation stories

All files below are **proposed deliverables**, except linked existing files. These stories do not create them in this planning task. Proposed MODEL-02 code lives in `src/job_automation/model_benchmarks/`, keeping it separate from the provider and EVAL framework; a thin `scripts/model_benchmark.py` entry point is sufficient. No new service or production database migration is planned.

| Order | Story | Phase | Depends on | Deliverable |
|---|---|---|---|---|
| 1 | MODEL-02-S01 | 0 | MODEL-01/LLM-01 handoff review | Frozen benchmark contract, candidate/license register, dependency gates |
| 2 | MODEL-02-S02 | 0 | S01; B1 for live telemetry | Passive instrumentation and reproducible bounded execution |
| 3 | MODEL-02-S03 | 0 | S01–02; B1/B2 | Generation context/placement/structured-output measurements |
| 4 | MODEL-02-S04 | 0 | S01–02; B1/B2; B4 for retrieval | Embedding resource/conformance and retrieval evidence |
| 5 | MODEL-02-S05 | 0 | S03–04; B3/B4; EVAL-01 | Controlled representative assessment comparison |
| 6 | MODEL-02-S06 | 0 | S03–05 | Measured configurations, limitations and decision record |
| 7 | MODEL-02-S07 | 0 | S01–06 | Repeatability/native checks and implementation handoff |
| 8 | MODEL-02-S08 | 1, deferred | S07; B5, GEN-02–04, EVAL S09 | Separate drafting model/context measurements |
| 9 | MODEL-02-S09 | 1, deferred | S08; GEN-05, EVAL S10 | Workflow resource measurements and Phase 1 handoff extension |

### MODEL-02-S01 — Freeze candidate, measurement and integration contracts

**Objective / references:** make every future result attributable to actual hardware, artifacts and controls. R07/R13/R14/R15/R16; C09/C10 and embedding configuration.

**Inputs → outputs:** current code, upstream handoffs and official sources → versioned experiment/cell/observation manifests, license register, gate status and execution matrix. Missing MODEL-01 handoff is an explicit pending gate.

**Owned files:** proposed `model_benchmarks/{records,configuration,manifest}.py`, `config/model-benchmark.example.json`, `tests/model_benchmarks/test_manifest.py`, synthetic metadata fixtures and `docs/operations/model-benchmarks.md`.

**Tasks:** formalize the reproducibility fields and requested/observed distinctions above; freeze units, status values (`planned`, `measured`, `failed`, `skipped`, `unsupported`, `pending`) and unknown-value handling. Resolve exact licenses/artifact lineage before candidate admission. Document B1–B5 with owner/action/evidence. Agree sidecar IDs and frozen corpus/review controls with EVAL. Inventory LLM gaps without expanding the provider's allowlist locally. Define an external benchmark root and prohibit production path aliasing, including Windows junction/case aliases. Reject secrets and unresolved live-run identity placeholders.

**Acceptance criteria:** changing a model digest, template, context budget or embedding prefix creates a distinct configuration fingerprint. No record claims a response digest when only inventory supplied one. Missing runtime/license or all-zero EVAL placeholder identity fails live preflight with a reason; offline fixtures remain usable. License descriptions do not imply all artifacts in a model family share terms.

**Verification:** manifest validation with missing/changed digests, unknown metrics, unit mismatches, unsupported settings, duplicate cell IDs, aliasing paths and synthetic secrets. Reconstruct a plan from its manifest without inference.

**Configuration / migration:** standalone benchmark schema; no new `AppConfig` fields or production tables. Any needed shared-contract extension is handed to its owner with compatibility/version/test requirements.

### MODEL-02-S02 — Capture bounded, attributable resource and timing observations

**Objective / references:** measure what executes on Windows and preserve failures/restarts. R07/R14/R16; C10 audit join.

**Inputs → outputs:** S01 plan, B1 launch profiles, LLM provider/audit ports → immutable per-attempt observations, raw telemetry and cell status. Offline work does not depend on a reachable runtime.

**Owned files:** proposed `model_benchmarks/{telemetry,transport_observer,execution,artifacts}.py`, `scripts/model_benchmark.py`, synthetic collector/transport fixtures and targeted tests.

**Tasks:** implement passive timing/metadata capture around the real provider; never change its request to obtain a better result. Label separate direct-runtime diagnostic calls. Sample the full process tree and board/host memory with supported tools. Save actual wire-control hashes and allowlisted numeric fields without private payload logs. Persist execution order before starting; checkpoint each finished cell atomically. On resume, reject control drift, preserve interrupted attempts and skip committed cells. Bound collector/runtime lifetimes and stop safely under the protocol. Restore touched server settings on success/failure. Prevent competing project work during measurements using existing coordination primitives or explicit manual exclusion, without implementing scheduling.

**Acceptance criteria:** a failed HTTP call or watchdog stop retains status, elapsed time and available memory samples. Missing counters remain null. Nanoseconds and milliseconds cannot be confused. A raw diagnostic success cannot masquerade as `LocalModelProvider` success. Restart does not duplicate committed observations or silently use new weights. Ordinary diagnostics contain no prompt, vectors or generated candidate text.

**Verification:** fake clock/collector/transport tests for exact timing formulas, zero/missing counts, sampling gaps, telemetry failure, response-size bounds, cancellation and identity drift; native Windows process cleanup and paths with spaces/umlauts. Measure collector overhead with a no-inference baseline; report sampling limitations.

**Configuration / migration:** versioned telemetry interval, deadlines, stop thresholds and output retention settings. Reuse external files for numeric samples; no second EVAL database or production migration.

### MODEL-02-S03 — Measure generation context, placement and structured output

**Objective / references:** establish a measured operating envelope for small quantized generation models before application selection. R07/R14; C10, supports R13.

**Inputs → outputs:** S01–02, B1 and relevant B2 resolutions → per-model/context/placement/cold-warm resource tables, structured-output counts and failure classifications. Raw-runtime cells may proceed while application cells remain pending.

**Owned files:** proposed `model_benchmarks/{generation_cases,generation_runs}.py`, synthetic non-domain probe fixtures and tests; local observations under the benchmark root.

**Tasks:** execute the staged G-A/G-B matrix; verify actual context, thinking mode, output cap and CPU/GPU placement. Test nested schema objects/arrays, enums, nullable/required values, Unicode, extra fields, empty/refused/malformed output and long completion exhaustion. Exercise exact and one-over budgets with validated tokenizer accounting. Use bounded evidence-position probes to separate admitted context from model use. Keep first-pass success separate from an optional bounded-regeneration experiment. Attach LLM defect reproductions for truncation/counting/length-stop/unsupported-option discrepancies; do not patch them invisibly in benchmark code.

**Acceptance criteria:** each planned cell is measured or has a concrete skip/failure reason. Largest tested passing context is named precisely; 8K passing does not claim 32K support or quality. CPU-only results can be valid even without GPU support. An input budget rejection, output-cap stop, malformed JSON and memory failure are distinct observations. Runtime success with failing provider validation leaves the application configuration unqualified.

**Verification:** scripted responses verify counters/classifications and first-pass denominators; native live measurements verify actual placement, identity, memory and repeated timings. Existing LLM schema/malformed-output tests are rerun only when its owner changes those paths. No smoke script or fake model result supplies performance evidence.

**Configuration / migration:** temporary per-cell settings and pinned capability proposals only; no automatic production model/context changes. Server-level settings remain outside `generation_settings` unless LLM-01 explicitly adds a compatible interface.

### MODEL-02-S04 — Measure embedding capacity and candidate retrieval behavior

**Objective / references:** supply a reproducible embedding configuration with measured resource use and separately attributable retrieval quality. R07/R13/R14; C08/C09 and CONTEXT-03 embedding/index contracts.

**Inputs → outputs:** S01–02 and B1/B2; B4 for retrieval → embedding identity/dimension/prefix/batch recommendations, per-cell timings/memory, vector conformance and EVAL retrieval references.

**Owned files:** proposed `model_benchmarks/{embedding_runs,index_measurements}.py` and focused tests; isolated local index references. CONTEXT/EVAL retain their production modules and corpus ownership.

**Tasks:** measure E-A/E-B batches/lengths/placements using explicit no-truncation. Verify count/order, finite nonzero vectors, observed dimension, norm and repeatability tolerance across repeat calls. Freeze document/query input formats; for Qwen use the upstream instruction-aware query convention through CONTEXT-owned prefix configuration and include prefix tokens in budgets. Check applied normalization and similarity metric. Measure full isolated index build and single-query latency separately from warm embed calls. Rebuild through CONTEXT-03 on model/config changes, verify rejected incompatible reads and leave production activation untouched. Use fixed chunks for model comparison; any chunk-size adjustment to fit MiniLM is a separate context experiment and must not be hidden as a model-only change.

**Acceptance criteria:** short input, overlength rejection, mixed-length batch and maximum safe tested batch have explicit outcomes. A response without digest retains the inventory binding and provenance limitation. Model/dimension/prefix changes cannot reuse old vectors. Report German, English and cross-language retrieval slices and semantic versus hybrid results; English performance alone cannot qualify the multilingual task. Missing B4 yields a resource-only result, not a quality recommendation.

**Verification:** vector validation, batch-order and prefix fixtures; isolated build/query integration with existing services; actual CPU/GPU/overflow measurements. Compare repeated vectors numerically using declared tolerances, not guaranteed byte identity. Supply metric-definition additions to EVAL rather than implementing duplicate metrics.

**Configuration / migration:** propose existing `EmbeddingConfiguration` fields with actual runtime/provider versions, observed dimension, digest provenance, prefixes, normalization/options, measurement method and batch limits. Bind the resulting report through its existing `model_02_report_ref` and `model_02_report_hash` fields. Never emit `verification_provenance='model_02_recommendation'` for unmeasured defaults. Activation/rebuild migration remains CONTEXT ownership.

### MODEL-02-S05 — Run representative Phase 0 assessment comparisons with EVAL-01

**Objective / references:** connect hardware feasibility to evidence-grounded task quality while preserving the existing evaluation framework. R07/R13/R06/R15; C01/C02/C06/C08–C11.

**Inputs → outputs:** shortlisted S03/S04 configurations, B3/B4, frozen EVAL corpus and MATCH-02/CONTEXT services → EVAL experiment/review reports joined to MODEL-02 resource sidecars.

**Owned files:** proposed `model_benchmarks/evaluation_adapter.py` as thin composition/manifest mapping, integration tests and recommendation evidence references. No fork of `evaluation/` runners, gold labels or metrics.

**Tasks:** request EVAL to freeze a coverage matrix spanning technical and general office roles, German/English/mixed-language postings, plausible synonyms versus exact identifiers (C++/C#), hard fails, unknown eligibility, unsupported skills, chronological/parent evidence, conflicting or absent facts, prompt injection and long-profile overflow. Existing eight synthetic cases are a smoke corpus; propose at least 24 distinct grouped cases for this campaign, subject to EVAL curation, with separate development/held-out splits. Record actual counts and uncovered slices if that size is unavailable. Tune candidate selection on development only; freeze shortlist/criteria before held-out execution.

For each generation configuration, hold the embedding/index and all application controls fixed and run JSON/RAG pairs. For embedding comparisons, hold the generation configuration, chunks, queries and retrieval algorithm fixed; only the embedding configuration and resulting isolated index change. Within every JSON/RAG pair keep the same approved facts, policy, generation model/settings, prompt/schema and budget. Full JSON must contain all eligible facts or visibly overflow. Compare shared completed cases and separately report coverage/failure differences, including cases only one configuration can execute. EVAL owns blinded reviews, evidence/claim rubrics and active reviewer time. Preserve deterministic hard-reject cases with zero inference as controls; exclude them from model throughput denominators.

**Acceptance criteria:** each live arm has actual provider call/audit evidence and matching controls, with no placeholder digests. Same persisted order reproduces after a new process starts. No configuration is favored by silently dropping its failures, shortening its profile, changing prompts or viewing held-out labels during tuning. Reports distinguish retrieval/admission/use and reviewer correctness from schema validity. Evaluation causes no production assessment selection, outbox write, Salesforce call or candidate-fact correction. No production sampling claim without RUN/EVAL export gates.

**Verification:** controlled integration with only transport/time faked first; mismatch and publication traps; then real provider/selector/index/assessor composition and EVAL review evidence. If owner integration is incomplete, retain the exact pending gate and completed resource results without fabricating quality scores.

**Configuration / migration:** consume existing EVAL manifests/repositories and metric versions. Persist MODEL-02 sidecars and references, not a new evaluation schema. Coordinated changes to stable ordering/live composition remain EVAL-owned dependencies.

### MODEL-02-S06 — Select measured Phase 0 configurations and state tradeoffs

**Objective / references:** make a reproducible recommendation justified by resource and representative-quality evidence. R07/R13/R14.

**Inputs → outputs:** S03–05 observations, EVAL reports/reviews and predeclared selection criteria → `docs/benchmarks/MODEL-02-phase0.md` and proposed `config/model-benchmark-recommendations.example.json`, containing sanitized measured references and configuration mappings.

**Owned files:** proposed `model_benchmarks/reporting.py`, report/config examples and report tests. EVAL remains the source of task metrics.

**Tasks:** agree acceptable latency/reviewer-error targets before final selection; label any provisional target as proposed, never achieved by definition. Compare feasible configurations across memory, latency, reliability, evidence use and review burden; explain tradeoffs without an invented aggregate score. Recommend generation and embedding separately, including CPU fallback and conditional acceleration profiles, tested context/output reserve/batch size, exact artifact/runtime identities and operating headroom. Require all core correctness invariants even if a candidate is fast. Measure a representative alternating embedding→generation workload with one loaded model to expose reload costs and combined Python/index memory; concurrent residency is not required. A recommendation must be exercised through the real application path, not only direct API probes.

**Acceptance criteria:** every recommended number links to measured cells/metrics. Report the maximum tested and the chosen conservative context separately, with untested regions and missing GPU modes explicit. If no candidate meets the agreed criteria, publish “no qualifying configuration,” the failed/pending reasons and the smallest justified next experiment; do not select a winner anyway or add paid inference. No completed recommendation while required quality evidence is pending. Config examples map to actual `ModelProviderSettings`/`ModelCapabilities` and `EmbeddingConfiguration` fields without automatically modifying consumer settings.

**Verification:** regenerate report from saved evidence with zero inference; verify nulls/denominators, failed cells, identities, settings and owner boundaries. Verify proposed configs parse using current consumers after dependencies resolve; separate benchmark-only controls from application-supported controls.

**Configuration / migration:** document proposed downstream change and index rebuild implications. Production promotion is a distinct consumer action; retain prior working artifacts/config for rollback. No automatic thresholds, policy edits or database migrations.

### MODEL-02-S07 — Verify reproducibility on Windows and publish the handoff

**Objective / references:** demonstrate repeatable operation and disclose remaining integration limits. R07/R13/R14/R16.

**Inputs → outputs:** S01–06 → native verification evidence, complete runbook and `docs/components/MODEL-02.md` with Phase 0 acceptance status.

**Owned files:** proposed manual benchmark verification script/tests, operation guide and component handoff.

**Tasks:** repeat a representative selected CPU and supported accelerator cell after runtime restart using the frozen manifest; verify identities/control equality and compare timing/output variability. Exercise interrupted/resumed execution, changed CWD, spaces/Unicode paths, missing model/counter, stale digest, unavailable backend, malformed output and safe cancellation. Use synthetic offline fault injection for dangerous memory exhaustion. Record restored server settings, closed handles and no unintended production writes. Publish exact PowerShell commands, dependency versions, input manifests, report regeneration commands and pending owner actions. Broaden regression tests only for changed integration code.

**Acceptance criteria:** another run can locate the pinned artifacts and reproduce the procedure without hidden shell state. Native Windows, offline fixtures, live inference, reviewer quality and consumer integration have separate statuses. Drift causes a new experiment or explicit failure. No mocked pass count establishes G2 completion. Missing B1/B2/B3/B4 evidence keeps corresponding live/quality acceptance pending.

**Verification:** component unit/contract tests, narrow provider/context/EVAL integration tests, native subprocess restart/path checks and recorded live repetitions. Test reports must name actual files/commands/counts only after they exist and execute.

**Configuration / migration:** finalize artifact-schema versions and compatibility. Preserve private evidence locally; retain only sanitized metrics/manifests and source references in handoff. No Phase 2 startup/reboot/scheduling work.

### MODEL-02-S08 — Extend model/context measurements to drafting (DEFERRED, Phase 1)

**Objective / references:** measure document generation separately from assessment, with longer outputs and stronger evidence requirements. R07/R11/R13/R14/R15; C13 and current C14 v2.

**Dependencies / inputs → outputs:** S07, B5, GEN-02 frozen input/context services, GEN-03 recipes, GEN-04 validation, and implemented EVAL-01 S09 → separate Phase 1 experiments, quality/resource observations and drafting configuration proposals. Existing generation code alone does not activate this story.

**Owned files:** future `model_benchmarks/drafting_adapter.py`, integration tests and `docs/benchmarks/MODEL-02-phase1.md`. GEN/EVAL keep prompts, validation, corpus and review ownership.

**Tasks:** freeze document type, language, profile/job, template options, purpose permissions, recipe/schema/model versions and output reserve. Benchmark CV and explicitly requested cover letter in German/English through both JSON/RAG using isolated local requests, without polling Salesforce. Start from measured small Phase 0 candidates but remeasure context/output/memory; assessment success does not qualify drafting. Include long histories, missing dates, restricted facts, metrics, invalid references, job-text injection and output-cap exhaustion. Current extractive recipes preserve factual excerpts in the source language; measure requested-language headings/allowed subjective text accordingly, not unsupported full translation. Free paraphrase/translation would require a separately reviewed GEN recipe and new experiment.

Use EVAL claim-level reviews for invented facts, altered dates/titles/numbers, contribution→leadership inflation, candidate versus employer citations, completeness, readability and editing effort. Record validator catches/misses separately. Include embedding query/retrieval costs for document purpose; retain originals and edits.

**Acceptance criteria:** measured drafting tables are separate from Phase 0; no Phase 0 latency/context recommendation is silently promoted. Schema/citation validity never substitutes for semantic review. No draft approves itself, updates production requests or triggers delivery. Missing EVAL S09 or compatible GEN contracts leaves this story deferred with an owner/action.

**Verification:** frozen-input/purpose and C14 v2 compatibility fixtures, actual GEN provider/validator integration, live generation and blinded claim review. Longer output reserves require new budget/capacity checks; unsupported output sizes remain failures.

**Configuration / migration:** separate versioned drafting profiles/sidecars; GEN owns recipe/config adoption. Any C14 compatibility migration follows its owner; no new document schema invented here.

### MODEL-02-S09 — Measure the local drafting workflow and extend recommendations (DEFERRED, Phase 1)

**Objective / references:** account for end-to-end local resource use without confusing model quality, validation and rendering. R07/R11/R13/R14/R16.

**Dependencies / inputs → outputs:** S08, GEN-05 real rendering readiness and EVAL-01 S10 → separate embedding/context/generation/validation/render timing and combined-memory observations, plus Phase 1 handoff extension. GEN-01 is needed only for a specifically isolated worker-integration lane; remote delivery is excluded.

**Owned files:** future `model_benchmarks/drafting_workflow.py`, targeted integration tests and Phase 1 report/handoff updates.

**Tasks:** use GEN-05's existing local renderer, serialize inference/rendering initially, measure unload/reload transitions and renderer/Python/runtime peaks. Distinguish inference completion, validator acceptance and locally readable DOCX/PDF. Consume EVAL's visual-review and editing evidence, retaining artifact hashes/versions. Measure long/multi-page and Unicode documents with pinned renderer/template versions. Missing LibreOffice or failed PDF conversion stays an explicit unmeasured/failed rendering lane, not a model failure.

**Acceptance criteria:** recommendations state stage-specific latency, resource envelope, reviewed quality, output limits and artifact evidence. File existence alone proves neither readable layout nor factual correctness. No uploads, notifications, application submissions or approval changes. MODEL-02 completion does not certify GEN delivery or the entire G4 gate.

**Verification:** real local rendering and EVAL visual review when available; fake renderer faults only establish orchestration/reporting. Repeat a selected frozen drafting case and verify retained lineage and restoration of runtime settings.

**Configuration / migration:** add Phase 1 results/profiles without overwriting Phase 0 evidence. No production worker, delivery or approval schema changes.

## Future verification commands and handoff checklist

The following is a **proposed interface after S01–S07 implementation**, not a currently available command or a benchmark performed by this plan. `check` must be offline; `run` must require valid local manifests and satisfied gates, with no implicit download or runtime installation.

```powershell
# Start in the real checkout once; all later paths are explicit.
$benchRepo = (Resolve-Path '.').Path
$benchPython = Join-Path $benchRepo '.venv\Scripts\python.exe'
$benchScript = Join-Path $benchRepo 'scripts\model_benchmark.py'
$benchRoot = Join-Path $env:LOCALAPPDATA 'JobAutomation Benchmarks Prüfung ä'
$benchConfig = Join-Path $benchRoot 'phase0.manifest.json'
$benchTests = Join-Path $benchRepo 'tests\model_benchmarks'

& $benchPython -m pytest $benchTests
if ($LASTEXITCODE -ne 0) { throw 'Benchmark component checks failed' }
& $benchPython $benchScript check --manifest $benchConfig
if ($LASTEXITCODE -ne 0) { throw 'Benchmark manifest is not ready' }
& $benchPython $benchScript run --manifest $benchConfig --output-root $benchRoot
# Inspect actual exit/status: pending or incomplete is never reported as passed.
```

The implemented runbook must add the actual bounded metadata preflight, selected-cell, resume and report-only commands, plus a native different-CWD run. No unknown hash, model identity, result or runtime version should be filled in merely to make an example runnable.

The implementation handoff must contain:

- Story/phase status, requirement coverage, changed files and artifact/schema versions; B1–B5 and EVAL EG5 status with evidence, owner and next action.
- Official-source check dates and exact model/runtime/tokenizer/license/quantization identities; installed versus per-response digest provenance and unresolved metadata discrepancies.
- Hardware/backend inventory, effective server/application settings, tested context/batch/output limits, paths and reproducible commands; full model/config hashes rather than mutable tags alone.
- Planned versus completed cells, real counts and failures, raw observation/report references, memory sampling limitations, cold/warm definitions and latency units/statistics.
- EVAL experiment/corpus/split/metric/reviewer references, actual reviewed counts, quality limitations and tradeoffs; no unsupported population-quality claim.
- CPU/GPU/mixed/unknown status; no universal 4 GB VRAM fit promise. Retain an honest “no qualifying configuration” or pending recommendation when evidence does not support one.
- Consumer handoff to LLM-01, CONTEXT-03/04, MATCH-02, MODEL-01 and EVAL-01; later GEN profiles remain explicitly Phase 1. Record required owner changes without taking over those components.
- Separate offline, native Windows, live inference, semantic review, reproducibility and rendering results. This planning task supplies **none** of those empirical results; Phase 2 and production promotion remain outside scope.
