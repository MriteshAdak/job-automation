# LLM-01 — Model client and call harness

Status: **IMPLEMENTED** · Planning date: **28 October 2026** · Phase 0 · Scope: **LLM-01 only**

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), v1.0. References below use requirements (§2), shared contracts (§4), correctness/security rules (§5), component boundaries (§6), integration gates (§7), implementation instructions (§8), and native Windows conventions (§9). These are implementation stories, not a record of implemented behavior or passed tests.

## Objective and boundary

Implement the shared local provider for structured generation and embeddings. Consume C10 calls, return validated output or a classified error, and retain model identity, effective settings, prompt/input versions, input fingerprint, timing and available usage. Enforce configured loopback endpoints, deadlines, context limits and bounded malformed-output handling. Service failure, invalid model output and context overflow must remain distinguishable and must never become fabricated eligibility rejections.

Direct requirements: **R07, R15, R16**. Supporting constraint: **R14**, native Windows without mandatory hosted inference, Docker, WSL or paid dependencies. Downstream C09/C11/C14 consumers motivate the boundary but are not implemented here.

Own `src/job_automation/models/`, its tests and non-secret provider configuration. Shared-contract/configuration edits are limited to the explicit gaps below and follow FND-01 versioning discipline. Exclude runtime installation, model downloads, GPU configuration and health/setup ownership (MODEL-01); model selection, hardware fit and benchmarking (MODEL-02); context construction, retrieval/indexing, assessment/drafting prompts, factual validation, Salesforce, persistence framework changes and scheduling. Schema-valid output does not prove semantic truth. No application code is changed by this planning task.

## Instructions and inspected repository evidence

Read the blueprint, [README](../../README.md), [schema generation instructions](../../schemas/README.md), [FND-01 stories](FND-01.md) and [FND-01 handoff](../components/FND-01.md). No applicable `AGENTS.md` was found in repository/ancestor searches; the user-level `.codex/AGENTS.md` is empty. Generate schemas from typed models, keep shared fixtures synthetic, and follow the blueprint's Windows path and external runtime-data conventions.

| Evidence inspected | Consequence for LLM-01 |
|---|---|
| FND-01 handoff reports VERIFIED, Python 3.12.10 and native Windows checks | Reuse its contracts and synchronous interfaces. Its 78-test result is historical, not a check rerun for this plan. Current `pyproject.toml` specifies dependency ranges, despite the handoff's pinning language; record actual versions during implementation. |
| [C10 models](../../src/job_automation/contracts/models.py), [call schema](../../schemas/v1/C10_model_call.schema.json), [result schema](../../schemas/v1/C10_model_result.schema.json) | `ModelCall` carries IDs, operation, model/digest, prompt versions, arbitrary settings, context limit, fingerprint and a schema ID. It has **no prompt payload or input reference**. `ModelResult` has output, error, latency and nullable token usage, but does not enforce exclusive success/error or retain attempts/effective settings itself. |
| [ModelProvider and EmbeddingResponse](../../src/job_automation/contracts/interfaces.py) | Existing signatures are `generate(call: ModelCall) -> ModelResult` and `embed(texts: list[str], model: str) -> tuple[EmbeddingResponse | None, ClassifiedError | None]`. Embeddings expose vectors, model identifier and dimension only; call identity, digest, timing, usage and fingerprint need an explicit audit binding. |
| [Contract base](../../src/job_automation/contracts/base.py), [error taxonomy](../../src/job_automation/contracts/errors.py) | Records use schema version `1.0`, are frozen and forbid extra fields. Nested dictionaries/lists still need defensive copying. Recoverable categories include rate limit, transient network/service and capacity; `model_output` and `context_budget` are not generically retryable. Do not change this taxonomy to make malformed-output retries convenient. |
| [Configuration](../../src/job_automation/configuration.py), [example](../../config/app.example.json), [CLI](../../src/job_automation/cli.py) | Only `model_service_url` exists for models. Its validator checks the hostname allowlist, not the whole URL or transport routing. CLI prints the entire configured URL. Add strict scheme/authority/path handling and safe diagnostics before using it for private prompts. |
| [Schema exporter](../../src/job_automation/contracts/export_schemas.py), [contract tests](../../tests/contracts/test_context_model_assessment.py), [interface tests](../../tests/contracts/test_interfaces.py), [C10 fixture](../../tests/fixtures/contracts/C10/valid.json) | Generated JSON Schema and Pydantic exist; there is no runtime output-schema registry/validator. Catalog fixtures primarily cover ModelCall, so add real ModelResult/embedding failure and validation cases. Do not treat schema names in fixtures as executable schema lookup. |
| [Foundation fakes](../../tests/fakes/fake_services.py) | The fake provider returns fixed results/vectors and a transient failure. It establishes interface shape, not real transport, token accounting, vector validity or privacy behavior. Keep it in tests and add scripted transports for the production harness. |
| Repository search for MODEL-01 handoffs and production provider | No `docs/components/MODEL-01.md`, MODEL-01 story file or production `models/` package was found. Live runtime/API/model capabilities are unverified. FND-01 explicitly leaves runtime/model work pending. |

Re-read these files when implementing. A later MODEL-01 handoff may supply runtime version, reachable endpoint, installed model identities/digests, supported API operations, local-only settings and known capability limits. Its absence blocks live verification, **not** offline implementation. MODEL-02 is a later consumer of this harness and is not a prerequisite for fake tests.

## Contract decisions and proposed implementation defaults

Blueprint/user requirements above are mandatory. The following are proposed technical choices to freeze in S01; they are not measured model recommendations or candidate facts.

1. **Preserve the public synchronous signatures.** Supply an explicit immutable input resolver at provider construction, keyed by C10 `call_id` and `input_fingerprint`, to obtain caller-prepared system instructions and user/data content. Missing/mismatched binding fails before transport. The provider does not discover the current profile, read arbitrary files, invent prompts or rebuild context. A different explicit request-envelope design is acceptable only with a recorded protocol/schema and consumer migration plan in S01.
2. **Use a local schema registry.** Resolve `requested_schema` to a pinned schema/version/digest plus a strict validator. Structured generation requires an object-shaped supported schema, matching `parsed_output: dict`; missing, unknown or unsupported schemas fail before inference. Resolve references only from the trusted local registry. No network schema resolution or schema selection from model text.
3. **Make audit metadata a typed boundary.** Join the original C10 call, effective execution settings and result by call ID. Define a versioned call/attempt audit record, including embedding calls, exposed to an injected caller-owned recorder. Embedding success and failure must expose a safe call reference so consumers can obtain the record; coordinate the minimal `EmbeddingResponse` extension and error-details binding. LLM-01 creates records; durable run storage/recovery remains with DATA-01/RUN-01.
4. **Serialize inference through one shared provider gate.** Generation and embeddings share it; queue wait counts toward the overall deadline. The application-wide process lock remains RUN-01's responsibility. Do not claim per-instance locking prevents independent application processes from overlapping.
5. **Use finite request limits.** Configuration declares connect/read timeouts, total logical-call deadline, total transport-attempt cap, bounded backoff, response-size limit, model/context/output limits and embedding batch limits. No benchmark-derived defaults are invented. Proposed malformed-output policy is fail immediately by default, with at most one explicitly enabled regeneration using the same frozen input/schema/settings. All attempts share the total cap/deadline. No automatic JSON rewriting or repair prompt is required.
6. **Separate model facts from requested values.** Preserve requested and observed model identity/digest, and record unknown metadata as null. A caller-pinned digest mismatch is an explicit failure. Never label a response as executed by the requested digest merely because it was requested, silently switch models, download a missing model or fall back to cloud inference.

## Ordered stories

All stories belong to LLM-01. File names under `models/` and `tests/models/` are proposed; references to shared files identify narrow coordinated edits, not transfer of another component's ownership.

| Order | Story | Dependencies | Deliverable |
|---|---|---|---|
| 1 | LLM-01-S01 | FND-01 | Frozen input/schema/audit contracts and compatibility plan |
| 2 | LLM-01-S02 | S01 | Local-only configuration and injectable bounded transport |
| 3 | LLM-01-S03 | S01–S02 | Immutable input binding, fingerprint and context preflight |
| 4 | LLM-01-S04 | S01–S03 | Strict structured-generation provider |
| 5 | LLM-01-S05 | S01–S03; S04 provider composition | Validated embeddings through the shared provider |
| 6 | LLM-01-S06 | S02–S05 | Classified failures and unified bounded attempt control |
| 7 | LLM-01-S07 | S01–S06 | Complete audit recording and privacy verification |
| 8 | LLM-01-S08 | S01–S07; MODEL-01 only for live checks | Offline integration, Windows checks and implementation handoff |

### LLM-01-S01 — Freeze input, output-schema and audit boundaries

**Objective/references.** Make the FND-01 model interfaces executable without hidden input or metadata loss. R07/R15/R16; C10, `ModelProvider`, `EmbeddingResponse`, `ClassifiedError`; blueprint §§4, 6/LLM-01 and 8.

**Dependencies.** FND-01 contracts, schemas, fixtures and handoff. MODEL-01 is not needed to define fake capabilities; installed-runtime specifics remain pending.

**Inputs → outputs.** Existing interface shapes and the gaps above → documented input resolver, local schema registry, transport/clock/recorder ports, audit records and versioned compatibility decisions.

**Owned files.** Proposed `models/{__init__,records,ports}.py`, `tests/models/test_contract_boundary.py`, `tests/fixtures/models/README.md`. Coordinate only necessary edits to `contracts/{models,interfaces,export_schemas}.py`, relevant exports, generated schemas, `tests/contracts/`, C10 fixtures and foundation fakes.

**Tasks.**

1. Freeze prompt binding and lifetime, exact fingerprint recipe, schema ID/version resolution, embedding audit association and result/error invariants. Keep secret-bearing transient input distinct from the ordinary audit projection.
2. Define safe attempt records: logical call ID, attempt number/purpose, operation, requested/observed model identity and digest, prompt/system/input-format/schema versions, effective settings/context limit, fingerprint algorithm/version, UTC start/end, monotonic duration, nullable usage and classified outcome.
3. Specify generation success as validated object plus no error; failure has error with both `output_text` and `parsed_output` null. Specify exactly one embedding response/error. Retain invalid raw output only transiently, never in an error message or ordinary audit event.
4. Define an embedding input-format version instead of inventing a natural-language prompt version. Account for absent usage/digest and per-attempt versus logical-call totals explicitly.
5. Record concrete shared schema versions and reader compatibility before dependent stories ship. Old `extra='forbid'` readers will reject new fields; test old fixtures and update fake consumers explicitly. Incompatible changes require the blueprint decision/consumer plan, not a silent edit to field meaning.

**Acceptance criteria.** A synthetic C10 call can identify exactly which immutable prompt and schema will execute. Missing input and ambiguous bindings yield classified preflight failures. A result cannot contain both an error and successful output. Embedding callers can associate success or failure with complete audit metadata without changing the existing tuple semantics.

**Tests.** Protocol conformance; positive/negative request/result/audit fixtures; ambiguous success/error combinations; unknown versions; old fixture readability; deterministic schema export; mutation of caller-owned dictionaries after binding cannot change the executed request.

**Migration/configuration/handoff.** Record the final public signatures, embedding metadata extension, schema IDs/versions and compatibility table. No database migration or prompt persistence is assumed. Resolve these decisions before S02–S05 depend on them.

### LLM-01-S02 — Configure and enforce the local transport boundary

**Objective/references.** Restrict all provider traffic to the configured local runtime and enforce finite I/O. R07/R14/R15/R16; C10 and `AppConfig`; blueprint §§5, 6/LLM-01 and 9.

**Dependencies.** S01 ports and configuration decision; FND-01 config loader. MODEL-01 supplies real runtime compatibility later.

**Inputs → outputs.** Validated non-secret application/provider settings → configured provider transport or a safe configuration error, with zero inference during construction/config checking.

**Owned files.** `models/{configuration,transport,provider}.py`, `tests/models/{test_configuration,test_local_transport,test_deadlines}.py`, scripted transport in `tests/fakes/model_transport.py`. Narrow edits to `configuration.py`, `cli.py`, `config/app.example.json`, generated app schema and existing configuration/CLI tests; `pyproject.toml` only for a justified transport/validation dependency.

**Tasks.**

1. Reuse `model_service_url`; add a typed, versioned provider-settings section or reference with explicit precedence. Validate positive finite timeouts, counts and size limits; reject unknown/unsafe settings. Existing configs must still load without initiating inference; missing execution configuration fails at provider use, not unrelated commands.
2. Accept only supported HTTP(S) loopback authorities/ports; reject URL credentials, query secrets, fragments, unsupported schemes and unapproved base paths. Honor only `127.0.0.1`, `localhost`, or `::1` per current policy. For `localhost`, constrain the actual connection to loopback resolution. No caller/model-output endpoint override.
3. Disable environment proxy routing and redirects, including redirects to a different local port. Keep TLS verification when HTTPS is configured. Use fixed application-owned operation routes, not URL concatenation with model names or untrusted text.
4. Inject transport, monotonic clock and sleeper. Bound connect/read and total elapsed time, including queue wait, metadata lookups, response reads and retries. A read-idle timeout alone must not permit an endless trickle response. Bound response bytes and close resources on all paths.
5. Make config/HTTP diagnostics safe. The current CLI must not echo a credential-bearing URL on either success or validation failure. Imports, provider construction and config checks perform no downloads, subprocess calls or network health probes.

**Acceptance criteria.** Invalid endpoints and limits fail before any transport call. A proxy environment variable and a remote redirect cannot route prompt data off loopback. Fake stalled and trickling responses terminate within the injected deadline; oversized responses fail without unlimited buffering. No runtime/model installation is attempted.

**Tests.** Table-driven IPv4/IPv6/localhost URL validation, URL userinfo/query/fragment cases, resolver returning a non-loopback address, redirect and proxy traps, connect/read/deadline exhaustion, response-size bounds, resource closure and configuration compatibility. Test the production transport policy using injected low-level connections; replacing the entire policy with a fake does not prove enforcement.

**Migration/configuration/handoff.** Document new keys, units, precedence, selected transport/version and compatibility. Config examples are synthetic; any file reference resolves against the explicit config directory using `pathlib.Path`.

### LLM-01-S03 — Bind inputs, effective settings and context budgets

**Objective/references.** Execute the exact fingerprinted input within configured limits without silent truncation. R07/R15/R16; C10 and C09 budget boundary; blueprint §§4–5.

**Dependencies.** S01 immutable input/schema ports; S02 validated provider configuration. MODEL-02 owns eventual measured model/context choices.

**Inputs → outputs.** C10, bound prompt or ordered embedding texts, configured model capabilities and registered schema → frozen execution request and budget measurement, or classified validation/configuration/context error.

**Owned files.** `models/{inputs,fingerprints,budget,settings}.py`, `tests/models/{test_inputs,test_fingerprints,test_context_budget,test_settings}.py`, synthetic input/budget fixtures.

**Tasks.**

1. Verify call ID/fingerprint binding. Define canonical encoding over the actual ordered input, roles and boundaries; document Unicode/whitespace behavior and version it. Verify the supplied C10 fingerprint rather than trusting it. Separately bind effective model/settings/schema versions for reproducibility; never rewrite the original call silently.
2. Validate an allowlist of typed model settings, rejecting unknown keys, non-finite numbers, tool definitions, remote-model selectors and transport overrides. Deep-copy settings/input. Record requested and effective values; reject conflicts with provider ceilings instead of silently clamping or ignoring values.
3. Require configured context capabilities for the selected model. Check prompt/system/data/schema or template overhead plus reserved maximum output and safety allowance against both the call limit and configured ceiling. Embeddings check each input and batch limits with no generation reserve.
4. Distinguish tokenizer measurement from a conservative estimate and record method/version/allowance. If a reliable supported count or conservative bound is unavailable, fail visibly as unsupported capability/configuration rather than claim guaranteed fit. Post-call usage is not a substitute for preflight. Test tokenizer behavior with fakes; selecting/benchmarking a model is excluded.
5. Disable runtime input truncation where supported and verify that behavior against the selected runtime before live acceptance. Reject unsupported no-truncation guarantees. Map an explicit runtime context rejection to `context_budget`, even after preflight succeeds. Never trim the profile, swap JSON for RAG, split away required context or reduce output reserve silently.

**Acceptance criteria.** With a synthetic 1,024-token context ceiling and 128 reserved output tokens, counted input plus overhead of 896 fits; 897 returns `context_budget` without inference. Changing ordered input changes its fingerprint. An unknown tokenizer/capability remains visible. No error becomes an empty successful context or a job rejection.

**Tests.** Exact-limit and one-over tests; oversized single embedding text; overhead/output-reserve accounting; Unicode and multi-message fingerprints; reordered input; fingerprint mismatch; unknown settings; caller mutation; configured-versus-call limit conflicts; runtime overflow; no truncation/fallback assertions.

**Migration/configuration/handoff.** Publish the fingerprint and budget-method versions, capability provenance and unknown behavior. Synthetic test limits do not establish a safe production context size or hardware fit.

### LLM-01-S04 — Implement strict structured generation

**Objective/references.** Implement `ModelProvider.generate` with validated structured output and C10 identity/usage mapping. R07/R15/R16; C10 and shared model-provider boundary.

**Dependencies.** S01–S03. S06 adds the common retry controller; initial execution remains single-attempt and already returns classified errors.

**Inputs → outputs.** Validated C10 plus bound input/schema → `ModelResult` containing a schema-valid object or a classified error, linked to the same call ID.

**Owned files.** `models/{generation,schemas,validation,provider}.py`, `tests/models/{test_generation,test_schema_validation,test_generation_metadata}.py`, generation wire fixtures under `tests/fixtures/models/`.

**Tasks.**

1. Map the frozen request to the supported local structured-generation API. Request a complete bounded response and the registered output schema. Verify current official API behavior against the runtime version during implementation and document the supported subset; do not infer support from a fixture name.
2. Validate transport envelope, completion state, model identity and response types before parsing content. Distinguish explicit context exhaustion from malformed/truncated output and service errors. Missing model/capability must not trigger a download or a second provider.
3. Parse strict JSON: reject duplicate keys, non-finite numbers, surrounding prose/fences, trailing data and unsupported top-level types. Validate the full object against the registered schema without coercing values, filling missing business facts or dropping unknown fields to obtain a pass. Bound parsing/validation depth and size.
4. Return only fully validated results. Failure clears raw/parsed output in C10; schema diagnostics use safe codes/paths without echoing offending values. Successful raw output remains private application data and is never automatically logged.
5. Map available usage to `TokenUsage` and runtime durations to explicitly named audit fields with documented units. Unknown metrics stay null; zero is recorded only when supplied/measured. Validate reported counts and identity instead of allowing malformed metadata to crash the boundary.

**Acceptance criteria.** The fake runtime's valid JSON object passes the exact caller-selected schema. Syntactically valid but schema-invalid JSON returns `model_output`. Invalid request schema returns a preflight configuration/input error with no HTTP call. An unexpected tool-call response cannot execute anything. A result never contains an invented assessment disposition.

**Tests.** Valid structured response; missing/wrong/extra fields; wrong top-level type; duplicate keys; NaN/infinity; fenced JSON; incomplete completion; unknown schema and external `$ref`; model/digest mismatch; absent and malformed usage; wire-envelope errors; untrusted text that attempts to change endpoints/tools.

**Migration/configuration/handoff.** Record schema-registry registration rules, strict-validation library/subset and supported runtime API version. Consumer prompts and domain semantics remain with MATCH-02/GEN-03.

### LLM-01-S05 — Implement validated embeddings with model provenance

**Objective/references.** Supply ordered vectors and complete call metadata through the shared provider. R07/R15/R16; `ModelProvider.embed`, `EmbeddingResponse`, C10 audit semantics; blueprint §5 prohibits mixing incompatible embeddings.

**Dependencies.** S01–S03 and S04 provider composition; no index builder or real model is required for automated verification.

**Inputs → outputs.** Ordered texts and configured embedding model → `(EmbeddingResponse, None)` or `(None, ClassifiedError)`, with a retrievable call/attempt audit record for either outcome.

**Owned files.** `models/{embeddings,provider}.py`, `tests/models/{test_embeddings,test_embedding_metadata}.py`, embedding wire fixtures. Shared response changes are only those frozen in S01.

**Tasks.**

1. Allocate a logical call ID, freeze ordered input and fingerprint, and use an explicit embedding input-format version. Record effective embedding settings, context limit, identity/digest, timing and available usage through the same audit path as generation.
2. Apply model allowlist, input/context and batch ceilings before transport. Proposed initial behavior rejects empty batches, empty individual texts and oversize batches as explicit input/budget errors; it does not silently split, trim, reorder or drop inputs.
3. Validate exactly one vector per input in the original order, positive consistent dimensions and finite numeric values, excluding booleans. Enforce the configured/verified model dimension when known. Never pad, truncate, normalize or fabricate vectors to disguise a mismatch.
4. Preserve observed embedding model/digest and dimension for downstream compatibility checks. A pinned identity/dimension mismatch is a visible failure. Unknown digest stays unknown, not proof of compatibility; CONTEXT-03 owns whether/how to build or reuse an index.
5. Fail the logical batch on any invalid/partial response. Do not return a shortened success or partial vectors alongside an error. Share the same serialized inference gate and timeout/error policy as generation.

**Acceptance criteria.** Three texts produce three correctly ordered vectors for the selected model. A missing vector, mixed dimension or non-finite value produces `model_output` with no usable response. Context overflow produces `context_budget`. Timing/fingerprint/settings remain available on both success and failure.

**Tests.** Ordered success; duplicate texts preserve positions; empty input policy; count mismatch; mixed/zero/wrong dimension; string/boolean/non-finite elements; model/digest mismatch; partial batch failure; context limits; nullable usage; generation/embedding serialization.

**Migration/configuration/handoff.** Record embedding metadata/version and batch policy for CONTEXT-03 and MODEL-02. Do not build an index, select a production embedding model or claim retrieval quality.

### LLM-01-S06 — Classify failures and bound every attempt

**Objective/references.** Surface actionable failures without infinite retries or silent rejects. R07/R16; C10 and `ErrorCategory`; blueprint §§4–6.

**Dependencies.** S02 transport/deadlines, S03 preflight and S04–S05 response validators.

**Inputs → outputs.** Preflight failures, transport outcomes and validation outcomes → final classified results plus bounded attempt history.

**Owned files.** `models/{errors,retry,harness}.py`, `tests/models/{test_error_classification,test_retries,test_malformed_output,test_serialization}.py`, scripted clock/sleeper/transport fixtures.

**Tasks.**

1. Use shared categories and stable safe reason codes. Freeze mappings for the supported runtime's documented status/error signals; HTTP 400 alone is not proof of context overflow. Do not classify errors by blindly echoing or loosely searching arbitrary response text.
2. Use one total transport-attempt cap/deadline across service retries and optional malformed-output regeneration. Bound exponential backoff and any service retry hint by remaining time. Default to no malformed-output regeneration; optional maximum is one additional attempt, never recursive repair.
3. Preserve the logical call ID, original input, schema, settings and model across retries. Record each attempt separately. If a future repair prompt changes input, it needs a separately versioned/fingerprinted derived invocation; it is outside the proposed initial policy.
4. Keep `model_output` non-recoverable for generic outer retry. The finite internal regeneration policy is distinct and reports exhaustion. Preflight validation, context, permission/authentication and unsupported input do not loop. Retry recoverable network/service/rate/capacity failures only when configured and within budget.
5. Preserve the final causal category and attempt history when the cap is exhausted; attach exhaustion/deadline reason without turning every failure into one generic service error. After an ambiguous timeout, do not claim the server stopped inference or that retries are exactly-once; close local resources and document runtime cancellation limits.

**Acceptance criteria and classification examples.**

| Synthetic condition | Expected category / treatment |
|---|---|
| Connection refused or I/O timeout | `transient_network`, bounded retry eligibility |
| Runtime unavailable / documented temporary server failure | `transient_service`, bounded retry eligibility |
| Explicit model memory/resource exhaustion | `capacity`, bounded policy; no automatic model substitution |
| Rate-limited local service | `rate_limit`, bounded delay |
| Missing configured model/schema/capability binding | `missing_configuration` or `unsupported_input` with documented reason; no install/fallback |
| Authentication/permission failure | `authentication` / `permission`, no retry loop or secret echo |
| Invalid caller settings/fingerprint | `validation`, zero inference attempts |
| Known preflight/runtime context overflow | `context_budget`, no truncation or unchanged-input retry |
| Malformed JSON/schema-invalid object/invalid vectors | `model_output`, at most configured internal regeneration |

For a fake three-attempt cap, a sequence of transient error, malformed generation and valid generation may make at most three requests, only if policy and deadline allow. Two malformed outputs exhaust the proposed one-regeneration allowance. Service failure, invalid output and overflow remain separately observable to a fake consumer; none emits C11 `rejected`.

**Tests.** Classification table; zero-attempt preflight failures; bounded transient recovery/exhaustion; mixed failure sequences; deadline during backoff/queue wait; retry hints beyond remaining time; regeneration disabled/enabled; lock release on errors; no concurrent provider requests; stable call metadata across attempts.

**Migration/configuration/handoff.** Document attempts versus retries, cap/deadline precedence, reason codes and recoverability. Do not modify the global recoverable-category set or implement pipeline retry/storage state machines.

### LLM-01-S07 — Record complete audit metadata and prove privacy boundaries

**Objective/references.** Make every invocation inspectable while keeping credentials and private content out of ordinary logs. R07/R15/R16; C10; blueprint §5 security and §8 handoff rules.

**Dependencies.** S01 audit contract and S02–S06 execution outcomes. Safe handling applies throughout prior stories; this story completes cross-path verification.

**Inputs → outputs.** Frozen call and all execution attempts → versioned audit records and a small allowlisted diagnostic projection, with no raw prompt/text/vector/document dump.

**Owned files.** `models/{audit,diagnostics,harness}.py`, `tests/models/{test_audit,test_safe_diagnostics,test_untrusted_input}.py`. Narrow CLI sanitization regression tests if S02 changes config output.

**Tasks.**

1. Emit one logical-call record plus attempt records for generation and embeddings, including failures before transport. Retain requested/effective settings, operation, model identity/digest provenance, prompt/system/input-format/schema versions, fingerprint/version, context/budget method, UTC times, monotonic duration and available usage.
2. Specify `ModelResult.latency_ms` as total elapsed logical-call time, including queue/backoff, with individual transport/service durations separately named. Separate final-attempt usage from aggregate known usage; incomplete usage does not become a complete zero-based total.
3. Provide a caller-owned recorder port with explicit delivery/failure behavior; a recorder failure must be visible, not silently discard required metadata or rerun successful inference. Unit tests use an in-memory recorder. Do not add database tables, durable prompt storage or a new logging framework to satisfy this story.
4. Build ordinary logs/errors from allowlisted metadata, not serialized models or raw exceptions. Exclude prompts, input texts, generated output, vectors, authentication headers, credentials, URL userinfo/query data and validation input values. Bound/sanitize any configurable metadata labels to prevent log injection; raw schema IDs/settings dictionaries are not automatically safe.
5. Keep credentials separate from prompts/settings. The baseline local runtime needs no application credential in model input; if configured transport authentication is supported, resolve it at the transport boundary and never serialize it into C10. No real credentials or private candidate fixtures enter the repository.
6. Treat model/job text as inert data. It cannot select routes/models/schema files, invoke tools/shell, read local files, change approved facts or instruct logging to expose input. This boundary does not claim to solve semantic prompt injection or factual assessment.

**Acceptance criteria.** Success, preflight rejection, exhausted retry, malformed output and embedding failure all produce auditable records. Sentinel private strings injected into inputs, invalid output, URL credentials and transport exceptions never appear in captured ordinary logs, stdout/stderr or returned error details. Legitimate structured output remains available only through the intended result boundary.

**Tests.** Exact metadata correlation; requested versus observed identity; fake-clock latency across waits; unknown/partial usage; recorder failure; caplog/stdout/stderr sentinel tests for all error branches; duplicate-key/Pydantic validation errors; injected multiline labels; inert tool/URL instructions. Verify denied URL values are not echoed by CLI configuration errors.

**Migration/configuration/handoff.** Document audit fields, retention ownership, diagnostics allowlist and recorder obligations. Fingerprints are identifiers, not encryption or anonymization. Any future persistence uses configured external runtime data paths, not source-controlled files.

### LLM-01-S08 — Verify offline integration, Windows operation and the live gate

**Objective/references.** Demonstrate LLM-01 acceptance using fake transports and report live prerequisites honestly. R07/R14/R15/R16; C10/provider boundary; blueprint §§6–9.

**Dependencies.** S01–S07 for automated checks. **MODEL-01 handoff and functioning configured local generation/embedding APIs are mandatory before live checks.** MODEL-02 remains separate.

**Inputs → outputs.** Production provider wired to scripted transport, synthetic consumers and config → offline/native Windows evidence, opt-in live smoke procedure and `docs/components/LLM-01.md` implementation handoff.

**Owned files.** `tests/models/{test_provider_integration,test_consumer_boundary,test_windows_paths}.py`, `tests/fakes/model_consumers.py`, fixture documentation, proposed `tests/manual/model_smoke.py`, `docs/components/LLM-01.md`, focused README usage notes. No production assessment/context/generation consumer is built here.

**Tasks.**

1. Exercise the actual provider/harness with fake transport/clock/recorder. Generation and embedding consumers must receive valid results and distinctly handle service, output and context errors. Demonstrate no fabricated reject, empty success, dropped vector or cloud fallback.
2. Keep automated tests network-free, including when Ollama happens to be installed. Block accidental socket use; inject low-level transport behavior for routing/deadline tests. Fakes belong in tests and cannot become production fallbacks.
3. Run affected contract/configuration/CLI checks alongside component tests. Verify schema regeneration is deterministic and compatibility matches S01. Use native Windows, paths containing spaces and non-ASCII characters, and an explicit working-directory change for any config-relative references.
4. Prepare a manual, opt-in synthetic generation/embedding smoke script outside default pytest collection. Read MODEL-01 first; record runtime/API version, configured endpoint, installed models/digests, local-only configuration and capabilities. Use those existing models; never install, pull or benchmark as part of the smoke check.
5. Live checks cover one schema-valid generation, ordered embedding vectors with identity/dimension/usage where available, bounded failure against an unavailable endpoint, and visible context rejection where supported. Record unverified cases explicitly; synthetic output correctness is not model-quality, GPU-fit or end-to-end evidence.
6. Publish the component handoff with exact files, contracts/versions, decisions, commands/results, fake versus live versus native-Windows status and remaining integration. If MODEL-01 is absent, leave live verification pending with its precise missing inputs; do not mark live acceptance complete from mocks.

**Acceptance criteria.** The offline suite needs no installed model/service/GPU, account or network. It covers both provider methods, limits, error distinctions, audit completeness and privacy. Native Windows evidence is recorded separately. Live tests run only after MODEL-01 readiness; otherwise the handoff states the live gate is pending.

**Planned verification commands, after implementation.** These commands have not been run for this planning task:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests\models tests\contracts tests\test_configuration.py tests\test_cli.py
& ".\.venv\Scripts\python.exe" -m job_automation config check --config ".\config\app.example.json" --data-root (Join-Path $env:LOCALAPPDATA "Job Automation Prüfung ä")
```

The manual script's final CLI/options belong in its implementation handoff once MODEL-01 supplies real runtime/model configuration. Do not publish runnable commands containing invented model selections or claim that the script already exists.

**Migration/configuration/handoff.** No model installation, benchmark result or database migration is delivered. Next consumers are MODEL-02 (application measurements), CONTEXT-03 (embedding index), MATCH-02 (assessment) and GEN-03 (drafting). Their integration remains separate work.

## Completion and handoff checklist

- [x] S01 input binding, schema lookup, audit correlation and shared-version decisions are recorded; compatibility fixtures pass.
- [x] Both public provider methods use the configured loopback transport and enforce time/size/context/attempt limits.
- [x] Structured objects and embeddings are strictly validated; invalid results expose no successful partial payload.
- [x] Service, output and context errors are distinct; no error becomes an eligibility rejection.
- [x] Model identity/digest provenance, effective settings, prompt/input/schema versions, fingerprint, timing and available usage are recorded for success and failure.
- [x] Ordinary logs/errors exclude credentials, private input and generated content, with captured-output tests proving the boundary.
- [x] Automated verification uses fake transports only; native Windows commands/results and path checks are recorded.
- [x] MODEL-01 is cited for live readiness, or its absence and pending live checks are explicit. Installation stays with MODEL-01; model selection and benchmarks stay with MODEL-02.
- [x] The implementation handoff names owned files, contract/configuration impact, actual checks, limitations and next consumers. Use `implemented` while specified verification remains pending; claim `verified` only with the declared acceptance evidence.

Planning deliverable: this story file only. No application implementation, schema migration, model execution or live verification is claimed.
