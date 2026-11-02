# CONTEXT-01 — Full-profile JSON context

Status: **PLANNED** · Planning date: **28 October 2026** · Phase 0 · Scope: **CONTEXT-01 only**

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), v1.0, especially §§2, 4, 5, 6/CONTEXT-01, 8 and 9. Direct requirements: **R06, R13**; supporting constraints: **R07, R11, R14, R15, R16**. These stories specify future implementation; they do not record completed code or executed application tests.

## Objective and boundary

Build C09 `ContextBundle` records with `strategy=json` from an exact approved C01 `ProfileSnapshot`, a bound job revision and an explicit model budget. Full JSON contains the complete evidence set permitted for the requested purpose, mandatory eligibility and essential chronology. Preserve fact IDs, dates and precision, parent references, provenance, profile/job versions and stable ordering. Include instructions, job text, candidate context, framing and output reserve in admission to the configured model window. If the complete input cannot fit, return a visible `context_budget` error without a partial bundle, truncation, summarization or an automatic retrieval fallback.

Own the JSON builder and reusable context preparation/budget boundaries under `src/job_automation/context/`. Reuse PROFILE-01's permission evaluator; make the mandatory-context policy usable by CONTEXT-02/04. Narrow corrections to shared profile behavior and contract extensions are identified below, not a reimplementation of PROFILE-01.

Exclude chunking, embeddings, indexes, retrieval, the production `json|rag` dispatcher (CONTEXT-02–04), requirement extraction and assessment prompts (MATCH-02), inference transport (LLM-01), model selection/hardware benchmarks (MODEL-02), generation workflows/prompts, persistent context caches, Salesforce and scheduling. RAG parity tests use test-only consumers; they do not establish functioning retrieval or complete R06/R13/G2 acceptance.

## Repository instructions and inspected baseline

Read the blueprint, [README](../../README.md), [schema instructions](../../schemas/README.md), [PROFILE-01 handoff](../components/PROFILE-01.md), [FND-01 handoff](../components/FND-01.md), their story plans and relevant current code/tests. No applicable repository/ancestor/docs `AGENTS.md` was found; `C:/Users/mrite/.codex/AGENTS.md` is empty. The blueprint takes precedence over historical planning documents. Generate schemas from typed models; retain synthetic fixtures, external runtime data and native PowerShell conventions.

| Inspected evidence | Consequence for these stories |
|---|---|
| PROFILE-01 and FND-01 handoffs report VERIFIED | Reuse their implemented APIs. Their historical test counts and verification claims are not new test evidence for CONTEXT-01. |
| [C01 models](../../src/job_automation/contracts/profile.py), [snapshot validation](../../src/job_automation/profile/validation.py) | C01 parsing alone does not establish approval, unique IDs or valid graphs. Invoke `validate_snapshot` before inclusion; reject unsupported versions and unapproved snapshots. |
| [InclusionRules](../../src/job_automation/profile/inclusion.py), [ProfileInclusionView](../../src/job_automation/profile/models.py), [ProfileService](../../src/job_automation/profile/service.py) | Existing API accepts snapshot, purpose and optional mandatory IDs. It supplies eligible facts/IDs, mandatory facts, explicit eligibility, exclusions and warnings. It does not derive essential chronology or reject mandatory IDs absent from the snapshot. |
| Current inclusion ordering | Facts sort by known start year descending, null dates last, UUID as tie-breaker. Despite the comment, month/day are not sort keys. Warning creation iterates a set, so warning order needs explicit stabilization. Preserve the established fact order unless a versioned shared change is deliberately selected. |
| PROFILE-01 privacy behavior | Empty `allowed_uses` excludes a fact. A permitted child retains its original parent ID but does not expand a restricted optional parent; a restricted mandatory fact causes `InclusionConflictError`. Both strategies must retain this behavior. |
| C01 defaults and [approval mapping](../../src/job_automation/profile/approval.py) | Draft permissions default empty, but `CandidateFact.allowed_uses` defaults to all purposes. `CandidateEligibility.remote_eligible` defaults true. Draft `is_ongoing` is not retained in published `CandidateFact`; published provenance is one string. Do not claim these gaps are solved, fabricate ongoing status from null dates, or infer that a defaulted eligibility value was explicitly attested. |
| [C09](../../src/job_automation/contracts/context.py) | Contains facts/IDs, `mandatory_context: list[str]`, versions, RAG metadata, positive `token_budget`, `estimated_tokens` and warnings. Lacks purpose, candidate identity, inclusion/settings versions, structured eligibility/chronology and a complete measurement record. Does not enforce completeness or fact/ID correspondence. |
| [ContextSelector](../../src/job_automation/contracts/interfaces.py) | `select_context(requirements, profile, strategy, token_budget)` returns `(bundle, error)`. It lacks purpose, job revision/text, instructions and output reserve; it cannot honestly implement full request budgeting without a richer explicit binding. |
| [C07](../../src/job_automation/contracts/identity.py), [C06](../../src/job_automation/contracts/postings.py), [assessment binding](../../src/job_automation/assessment/inputs.py) | `PostingRevision` identifies a revision but has no description. Job content must accompany its exact revision, as it already does at the assessment boundary; never look up mutable latest text during construction. |
| [C10](../../src/job_automation/contracts/models.py), [LLM-01 plan](LLM-01.md), [configuration](../../src/job_automation/configuration.py) | C10 holds model/context/prompt metadata but no prompt payload. LLM-01 proposes explicit frozen input binding. No production `models/` or `context/` package, tokenizer, output-reserve setting or measured model window exists in this checkout. LLM-01's proposed design is coordination input, not implemented functionality. |
| [Foundation tests](../../tests/contracts/test_context_model_assessment.py), [profile fakes](../../tests/fakes/profile_consumers.py) | Existing C09 examples can have selected IDs without facts; profile JSON fake projects only selected fields. They establish shape/parity examples, not full JSON fidelity or budget correctness. New production tests must compare complete records. |
| [Contract base](../../src/job_automation/contracts/base.py), [error taxonomy](../../src/job_automation/contracts/errors.py) | `schema_version=1.0`, frozen models, extra fields forbidden; nested lists/dicts still require defensive copies. `context_budget` is nonrecoverable for unchanged inputs. Preserve the shared error taxonomy. |

Read these inputs again at implementation time. Current code determines available behavior; do not expand this component to close every historical handoff discrepancy. In particular, C01 default/ongoing/provenance changes require PROFILE-01/FND-01 decisions and any necessary migration, separately recorded from this builder's fidelity to existing C01.

## Contract and behavior proposals to freeze in S01

User/blueprint requirements above are fixed. The following names and representations are proposed implementation choices, not confirmed personal facts or measured hardware settings.

### Request, preparation and result

- Introduce a versioned `JsonContextRequest` and synchronous `JsonContextBuilder.build(request) -> tuple[ContextBundle | None, ClassifiedError | None]`. Exactly one result is non-null. Inputs explicitly bind approved C01, purpose (`assessment`, `cv`, `cover_letter`), canonical job ID, posting revision ID/hash, the corresponding normalized job content, caller-prepared requirements, instruction/template/schema inputs, model identity/configuration, output reserve and mandatory-policy settings.
- Bind job provenance using the supplied C07 revision plus C06/content association, including source key/hash identity where available. Validate the association through an existing revision-content lookup or an injected read-only binding port. A plain nonempty version label does not prove the text belongs to that revision. Do not copy identity hashing logic into the context module or fetch current job text.
- Define `PreparedProfileContext` around the existing `ProfileInclusionView`: exact candidate/profile/purpose/rule identity, all eligible facts, mandatory IDs with reason codes, structured explicit eligibility, chronology references and safe ordered warnings. JSON consumes every eligible fact; future RAG consumes the same eligible universe and mandatory subset, then selects optional evidence itself.
- Keep the existing FND `ContextSelector` intact initially. CONTEXT-01 provides its richer JSON builder; CONTEXT-04 later adapts a fully bound request or versions the shared selector. Do not pretend the four-argument legacy signature contains missing inputs, fill them with dummy revisions/empty instructions, or introduce hidden mutable defaults.
- Propose a C09 revision with typed additions for candidate ID, purpose, inclusion-rule version, mandatory-policy version, builder/serialization version, mandatory fact IDs, structured eligibility/chronology, content fingerprint and a budget report. Retain `ordered_facts`, `selected_fact_ids`, `mandatory_context` and current field meanings. Final field names/schema version and reader compatibility must be recorded before S03; suggested C09 `1.1` is a proposal, not a version already supported.
- Use structured mandatory content as the authoritative representation. Existing string `mandatory_context` may be a deterministic compatibility projection, with its duplication counted if transmitted. Chronology entries cite exact `(profile_version, fact_id)` and dates; explicit eligibility is sourced by C01 field path/version because those fields have no fact UUID. Never invent fact IDs for eligibility.
- An audit C09 and its model-facing JSON projection are distinct named representations. The model projection includes all permitted evidence fields and mandatory context; audit-only counters/fingerprints need not enter the prompt. Record exactly which representation was counted and freeze the exact rendered input for the downstream caller. No self-referential token count is needed if measurement metadata stays outside that input.

### Shared inclusion and mandatory policy

Permission filtering is independent of job relevance, top-k, model size and output budget. Include every permitted fact regardless of whether it matches the supplied requirements. Empty permissions remain private; unsupported purposes fail. Approved snapshots are never modified to make context fit.

Proposed mandatory-policy v1: include all `explicit_eligibility` fields as represented in approved C01; include every permitted employment and education fact as a chronology anchor; include permitted role/project ancestor chains needed to interpret permitted evidence; union these with explicit caller-required fact IDs. Record the reason for each mandatory ID, deduplicate and use the shared fact order. This intentionally conservative chronology definition must be confirmed in S01 and reused by future RAG, whose top-k never removes mandatory anchors. Other dated facts remain fully present in JSON even when not mandatory.

Apply permissions before automatically deriving chronology anchors: private history is not automatically made mandatory merely because it has dates. Restricted optional ancestors remain unexpanded with a safe warning and the original opaque parent reference. If a caller/policy explicitly requires a restricted anchor, fail with a permission conflict; if a required ID is missing, fail validation. Never omit a required item silently, bypass privacy, infer dates, calculate unsupported total experience, or treat an unknown end date as current employment. Nulls, known-empty collections and actual date precision are preserved.

The builder uses the exact approved snapshot supplied. It must not resolve an older citation to circumvent a restriction in the requested snapshot, switch to latest, or mix versions. Historical C08 resolution is an audit capability, not permission for new use. Choosing an active profile for new work and deciding how withdrawn permission affects already-frozen generation remain caller/GEN-02 responsibilities.

### Complete request budgeting

Let `L` be the configured effective model context limit, `O` the explicit maximum output reserve, and `M` a recorded safety allowance. Render the exact instructions, requested output-schema material, complete job text/requirements and complete candidate JSON using the pinned prompt/chat template. Count its total input `P`, including all framing, separators and special tokens. Admit only when:

```text
P + O + M <= L
```

Preserve C09 `token_budget` as the allocated candidate-context allowance and `estimated_tokens` as the count/estimate for the candidate model projection. The new budget report additionally records total input, effective window, instruction/job/candidate/framing breakdown, output reserve, margin, remaining capacity/overflow, measurement method/version and exactness. Define the candidate allowance's overhead allocation in S01; it is not the global model window. If no positive candidate allowance remains, return an error rather than constructing a C09 that violates `token_budget > 0`.

The full rendered-input measurement governs admission. Token counts of separately encoded strings need not add to the count of concatenated/template-rendered input. Define breakdown attribution/reconciliation explicitly; do not assume additivity. If mandatory content is rendered twice, both occurrences consume input. Output reserve is not observed output usage, and preflight estimates are not C10 runtime token usage.

Measurement must identify the tokenizer/estimator, its version, model identity/digest when available, chat-template version, serialization version and settings fingerprint. Missing measurement capability or unknown template overhead cannot become a zero count or an asserted fit. A heuristic may be offered only as an explicitly labeled estimate with a documented admission policy and evidence; it cannot promise exact fit. MODEL-02 owns measured operational limits; LLM-01 must recheck effective limits/settings and surface runtime context failures. The unresolved choices below remain visible until evidence settles them.

## Ordered implementation stories

All file names under new `context/` and `tests/context/` are proposed. Shared-file edits are narrow coordinated changes, not transfer of ownership. Every story remains **PLANNED**.

| Order | Story | Dependencies | Deliverable |
|---|---|---|---|
| 1 | CONTEXT-01-S01 | FND-01, PROFILE-01 | Explicit request/result, mandatory and budget contracts; compatibility decisions |
| 2 | CONTEXT-01-S02 | S01 | Validated purpose-aware preparation shared with future RAG |
| 3 | CONTEXT-01-S03 | S01–S02 | Complete, deterministic JSON assembly and provenance binding |
| 4 | CONTEXT-01-S04 | S01, S03 | Model-bound whole-prompt measurement and admission |
| 5 | CONTEXT-01-S05 | S02–S04 | Public builder, safe visible errors and consumer handoff |
| 6 | CONTEXT-01-S06 | S01–S05 | Integrated verification, Windows evidence and component handoff |

### CONTEXT-01-S01 — Freeze construction, mandatory-context and budget contracts

**Objective/references.** Make complete JSON construction possible without implicit inputs or overloaded budget fields. R06/R13; C01/C06/C07/C08/C09/C10, blueprint §§4–6 and shared-contract discipline in §8.

**Dependencies.** FND-01 and PROFILE-01 handoffs/code. Coordinate the request rendering/measurement boundary with the LLM-01 plan and future CONTEXT-04; their production implementations are not prerequisites for offline contract work.

**Inputs → outputs.** Existing contracts and gaps above → typed request/preparation/settings/measurement records, builder/renderer/counter/binding ports, documented C09 changes and compatibility plan.

**Owned files.** `src/job_automation/context/{__init__,records,ports,settings}.py`; narrow edits to `contracts/context.py`, relevant contract exports/schema exporter; generated C09/auxiliary schemas and `schemas/README.md`; `tests/context/test_contract_boundary.py`, affected `tests/contracts/`, `tests/fixtures/contracts/C09/` and foundation fakes. Touch `contracts/interfaces.py` only if a new JSON-specific protocol is exported; leave production strategy dispatch to CONTEXT-04.

**Tasks.**

1. Freeze each request field, required identity/version binding, no-side-effect port, exact-one-result invariant and classification for absent/invalid data. Make purpose, instructions and output reserve explicit; do not default them from job text.
2. Freeze the mandatory-policy proposal, structured eligibility/chronology representation and C08 mapping. State that provenance preservation means exact approved C01 provenance strings/references, not automatic inclusion of source-document bytes or unapproved draft notes.
3. Specify canonical JSON encoding, model-facing projection, fingerprint inputs, budget units/semantics and rule/template/settings versions. Include purpose, candidate/profile content, job binding/content, model/settings, prompts/schema, output reserve and serialization in construction identity; exclude random IDs/current timestamps.
4. Record exact version handling: supported old C09 records remain readable for audit, but missing new fields do not prove completeness or safe budget admission. New fields are rejected by old `extra='forbid'` readers; update consumers/fakes/schemas together. Incompatible changes need a documented migration/consumer plan and blueprint decision before implementation proceeds.
5. Define settings as an explicit versioned input with a non-secret example. Reuse a later LLM-01 settings model if available; do not introduce competing model limits. Do not choose a production model, tokenizer or hardware-safe window by guesswork.

**Acceptance criteria.** A synthetic request identifies all content and reserves needed to determine fit. Missing purpose, job binding or instruction/template binding cannot yield success. Budget report can distinguish candidate estimate from total input/output reservation and identify unknown measurements. Legacy fixtures are either supported explicitly or fail with a documented version outcome; no old fixture is silently treated as fully budgeted.

**Tests.** Positive/negative request/report/C09 fixtures, supported/unknown versions, invalid numeric budgets, exactly-one-result checks, schema regeneration consistency and affected fake consumers. Confirm any new shared constraints do not accidentally apply JSON completeness rules to RAG bundles.

**Migration/configuration impact and handoff.** Publish exact schema/API changes and settings ownership. No SQLite migration is expected for a stateless builder; if a shared-record change affects stored JSON, document readers/upgrades before writing new records. Close representation decisions D01/D02 below before S03; measurement implementation choice can remain an explicit capability dependency.

### CONTEXT-01-S02 — Prepare the complete permitted set and mandatory context once

**Objective/references.** Supply one permission-aware evidence universe and mandatory-context policy for JSON and future RAG. R06/R15; C01/C08 and PROFILE-01 inclusion behavior.

**Dependencies.** S01; existing `validate_snapshot`, `InclusionRules.evaluate_inclusion`, `ProfileInclusionView` and exact C08 resolver.

**Inputs → outputs.** Approved snapshot, explicit purpose, mandatory-policy version and caller-required IDs → `PreparedProfileContext`, or safe validation/permission error. No job relevance score or budget may change this output's eligible set.

**Owned files.** `context/preparation.py`; narrowly coordinated fixes in `profile/inclusion.py` for missing mandatory IDs and stable warning order, and `profile/models.py` only if required metadata cannot be represented otherwise; `tests/context/test_preparation.py`, `tests/profile/test_inclusion.py`, `tests/fakes/profile_consumers.py` and synthetic `tests/fixtures/context/`.

**Tasks.**

1. Validate the snapshot before the inclusion evaluator, including approval, graph/ID/date integrity and supported schema. Reject drafts and malformed imported snapshots; do not approve or repair them.
2. Derive automatic mandatory IDs from permitted evidence using S01's versioned policy, union explicit required IDs, then invoke the shared inclusion evaluator with the complete mandatory set. Reject IDs absent from the exact snapshot and restricted required facts. Preserve optional restricted-parent behavior.
3. Copy all explicit eligibility fields faithfully and create chronology references without inventing precision, ongoing status, parent text, language proficiency or employment duration. Document C01 representational limits in the result/handoff where they affect interpretation.
4. Preserve existing year/UUID fact order and stabilize warnings/reason lists. Change shared ordering only with a recorded rule-version transition and updated consumers. Ensure mandatory IDs are a unique ordered subset of eligible IDs.
5. Defensively detach output lists/dicts from the snapshot. Share the preparation API with a test-only RAG consumer so purpose handling, mandatory IDs and private-parent treatment cannot diverge.

**Acceptance criteria.** An assessment-only fact appears for assessment and not CV; an empty-permission fact appears nowhere in operational output. A permitted child of an optional private parent remains present with an opaque parent ID and a warning, without parent text. Explicitly requiring that parent fails; requiring an unknown UUID fails. Permitted employment/education anchors and explicit eligibility survive even when a test RAG consumer returns zero optional hits. Reordering the input fact list does not change prepared output.

**Tests.** All three purposes; unsupported purpose; unapproved snapshot; duplicate IDs/cycles/missing parents; missing/restricted mandatory IDs; private sentinels in every output field; equal-year and undated order; warning determinism; empty permitted evidence with eligibility; mixed date precision/nulls; deep-mutation isolation; JSON/RAG preparation parity. Include multi-level ancestor chains and duplicate explicit mandatory requests.

**Migration/configuration impact and handoff.** Record the mandatory-policy and inclusion-rule versions. Existing snapshots remain unchanged. C01 default/ongoing representation fixes remain upstream issues rather than automatic data migrations here. Hand off the exact preparation API and privacy/conflict behavior to CONTEXT-02/04.

### CONTEXT-01-S03 — Assemble lossless, deterministic full JSON

**Objective/references.** Produce the complete candidate model projection and provisional C09 metadata with traceable input bindings. R06/R13/R15; C01/C07/C08/C09. A provisional assembly is internal and is not a successful C09 until S04 admission passes.

**Dependencies.** S01–S02; caller-supplied exact job binding. Production storage lookup is optional through the binding port, not a new DATA-01 dependency for pure construction.

**Inputs → outputs.** Prepared context, bound job content/revision and frozen rendering settings → canonical candidate JSON, structured mandatory context, ordered IDs, content fingerprint and provisional bundle fields.

**Owned files.** `context/{json_builder,serialization,binding}.py`; `tests/context/{test_json_builder,test_serialization,test_provenance,test_reproducibility}.py`; synthetic full-field, multi-version and job fixtures under `tests/fixtures/context/`.

**Tasks.**

1. Serialize every field of every permitted `CandidateFact`, including claims, skills, metrics, dates/precision, organization, original parent ID, provenance and permissions. Do not project the limited fields used by the existing profile fake, deduplicate distinct facts with identical text, summarize long claims or filter by requirements.
2. Set `ordered_facts` exactly to the prepared eligible facts and `selected_fact_ids` exactly to their ordered UUIDs, once each. Populate the complete mandatory eligibility/chronology representation and stable warnings. Keep JSON `query_version`, `index_version` and `retrieval_settings` null.
3. Carry exact candidate/profile/job identities and all inclusion/mandatory/builder/serialization versions. Validate job content belongs to the declared revision; preserve content/provenance binding in fingerprint metadata. No lookup of latest profile/job or copying unrelated revision labels.
4. Use a documented deterministic encoding, for example UTF-8, fixed JSON separators, sorted object keys and preserved array order/Unicode values. Do not normalize claim text or sort semantic lists such as claims merely for hashing. Escape JSON correctly without changing decoded values.
5. Separate trusted instruction fields from untrusted job/evidence data in the render boundary. Job text such as “ignore candidate permissions” remains data and cannot select a strategy, alter facts, fetch URLs, open provenance files or execute tools.
6. Supply downstream consumers the exact canonical candidate payload and a deterministic reconstruction/fingerprint contract. Approval free-text notes and bulky provenance documents are not part of the permitted evidence set merely because the parent snapshot is approved.

**Acceptance criteria.** Complete per-fact model dumps round-trip unchanged. Every selected ID resolves through candidate C08 to the same version and original fact. Repeated construction with equivalent inputs gives identical bytes/fingerprint/order/warnings. Correcting a fact in v2 preserves its UUID and changes content/fingerprint; building v1 still uses v1. Different job revisions/contents, purposes or serialization settings change the appropriate input identity. A long low-relevance fact remains complete.

**Tests.** Full-field equality rather than ID-only assertions; Unicode/quotes/newlines/long strings; known-empty/null preservation; two facts with identical text and distinct IDs; reordered input records; historical citation resolution after repository reopen; job revision mismatch; parent privacy sentinels; hostile job data; mutation isolation. Verify decoded model projection equals the eligible evidence oracle from PROFILE-01.

**Migration/configuration impact and handoff.** Freeze the serialization and fingerprint versions. No persistent context cache or repository write is required. Any caller caching later must use the complete input identity, not profile version alone.

### CONTEXT-01-S04 — Measure and admit the whole request within the model budget

**Objective/references.** Account for all material that consumes the configured model window and refuse overflows before inference. R06/R07/R13; C09/C10 and blueprint §5 full-JSON rule.

**Dependencies.** S01 and S03. Use injected deterministic counters/renderers for offline tests. A supported local measurement capability and MODEL-02 effective configuration are required for a production fit claim, not for implementing the arithmetic/error boundary.

**Inputs → outputs.** Frozen instructions/schema/template, complete bound job text/requirements, complete candidate JSON, configured model/window/output/margin and a measurement implementation → budget report and admitted bundle, or classified measurement/configuration/budget error.

**Owned files.** `context/{budget,measurement,rendering,settings}.py`; non-secret `config/context.example.json`; `tests/context/{test_budget,test_measurement,test_settings}.py`; `tests/fakes/context_measurement.py`. Any dependency added to `pyproject.toml` must be necessary for the selected local counter and recorded with Windows verification; no tokenizer dependency is chosen by this plan.

**Tasks.**

1. Render/count the entire frozen prompt, including system/developer instructions if present, job data, requirements, output-schema instructions, candidate JSON, separators and model chat-template/special-token overhead. Include each transmitted field exactly as executed; candidate-only counting is insufficient.
2. Validate finite positive limits/reserves and nonnegative margin, configured/runtime-supported context compatibility, tokenizer/model/template identity and output-cap constraints. Do not use advertised theoretical model maximum as measured hardware capacity. A changed prompt/model/template/config invalidates the measurement.
3. Apply `P + O + M <= L`, populate the report and candidate allowance under S01 semantics, and define explicit overflow diagnostics. If fixed instructions/job/output consume the window alone, return a budget error before exposing a successful bundle. Even an empty eligible set still requires eligibility and envelope accounting.
4. Use authoritative full-input counts for admission; record breakdown attribution and any residual overhead. Label estimates accurately. Reject absent, negative, non-finite or otherwise unusable measurements; never substitute zero or a fabricated exact count.
5. Keep measured input immutable through delivery to the caller. Provide a fingerprint check so downstream additions, regenerated templates, larger output settings or lower effective windows force remeasurement. Reconcile with LLM-01 preflight rather than letting two components count different strings.
6. Resolve D03–D07 below to the extent supported by installed capabilities. If only a fake counter exists, leave production measurement pending and fail production requests visibly. Never invoke generation merely to discover whether a private prompt fits.

**Acceptance criteria.** With a deterministic test counter, `P=3000`, `O=900`, `M=100`, `L=4000` fits exactly; increasing any included input by one token returns `context_budget` with overflow 1. A candidate-only estimate below its allowance cannot override a whole-prompt overflow. Long German text, schema instructions, framing and output reserve all affect admission. Unknown counter/template capability produces a visible configuration/unsupported-capability error, not success.

**Tests.** Exact boundary and ±1 token; instructions/job/output-only overflow; oversized single fact; thousands of facts; empty permitted set; mandatory duplication actually rendered; invalid settings; nonadditive test tokenizer; estimator/exactness metadata; unknown tokenizer/template and counter failure; model digest/settings changes; input-fingerprint mismatch; safe overflow report. Use controlled fake counts to test arithmetic separately from any real tokenizer fidelity tests.

**Migration/configuration impact and handoff.** Publish the effective settings/report schema, example units and explicit placeholders, with no unmeasured production window/model default. State ownership of runtime context/output settings and how consumers obtain the same prepared bytes. Local counter calibration/live model checks remain separately reported.

### CONTEXT-01-S05 — Expose complete success or visible, actionable failure

**Objective/references.** Wire the JSON-only public builder and error path without hiding evidence loss or strategy changes. R06/R13/R15/R16; C09, `ClassifiedError`, downstream LLM-01/CONTEXT-04 boundary.

**Dependencies.** S02–S04.

**Inputs → outputs.** `JsonContextRequest` → `(complete_budgeted_C09, None)` or `(None, ClassifiedError)`. Expose the exact model-payload binding to the caller using S01's API; never return a usable partial success with an error.

**Owned files.** `context/{service,errors,__init__}.py`; `tests/context/{test_service,test_errors,test_consumer_boundary}.py`; test-only caller/renderer/counter spies. No production pipeline/assessment/drafting worker is implemented.

**Tasks.**

1. Compose validation, preparation, full assembly, rendering and admission. Validate success invariants: JSON strategy, complete fact equality, unique ordered IDs, mandatory subset/content and exact identity/measurement bindings.
2. Map unapproved/invalid/mismatched inputs and missing mandatory IDs to validation; required-but-restricted evidence to permission; absent settings/counter to missing configuration; unsupported installed measurement capability to unsupported input; measured overflow to `context_budget`. Preserve recoverability semantics. Unexpected failures must not be rewritten as budget errors or empty context.
3. Return safe diagnostics with stable reason codes, budget totals/deficit and method/version information. Example: “Full JSON context exceeds the configured window by 1 token; complete context was not produced.” Allowlist error details; omit raw facts, job text, prompts, source paths and approval notes.
4. Fail visibly for a RAG request to the JSON-specific entry point. Never invoke retrieval, rank facts, trim strings, shorten the job, reduce output reserve, change models or reinterpret JSON as RAG to make the request succeed. A later caller may deliberately request RAG as a separate, honestly labeled operation.
5. Provide a caller-facing safe error rendering example and test that errors reach it. A returned exception swallowed in a logger is not visible failure. Leave actual RUN-01/GEN-02 UI/status integration to their owners; do not convert context failures into C11 rejection or a missing-skill claim.

**Acceptance criteria.** Overflow returns only a nonrecoverable `context_budget` error with useful safe numbers. Counter/rendering failure remains distinct. No model or retrieval call occurs on failure. A simulated caller receives and displays the failure while retaining its input IDs; neither it nor the builder emits an empty or shortened success. Success contains all permitted evidence and null RAG metadata.

**Tests.** Every error category/reason; exact-one-result; forbidden fallback and mutation spies; no input disclosure through messages/details/warnings; unsupported strategy; mandatory privacy conflict; failure propagation to a test caller; repeated unchanged overflow produces the same diagnostic rather than a retry loop. Include large private sentinel-bearing inputs without logging them.

**Migration/configuration impact and handoff.** Document the public builder API, safe error projection, result invariants and deliberate retry rules. No new CLI pipeline, persisted work state or automatic strategy selection is added. CONTEXT-04 owns shared dispatcher wiring; RUN-01/GEN-02 own durable visibility to operators.

### CONTEXT-01-S06 — Verify fidelity, shared inclusion and native Windows behavior

**Objective/references.** Demonstrate CONTEXT-01 acceptance and hand off exact limitations and integration requirements. R06/R13, supporting R14/R15/R16; blueprint §§7–9.

**Dependencies.** S01–S05. Existing PROFILE-01/DATA-01 services for synthetic lifecycle integration; live LLM-01/MODEL-02 capability only for separately labeled measurement verification.

**Inputs → outputs.** Implemented stories, schemas, synthetic fixtures, settings decisions and test results → component verification evidence and `docs/components/CONTEXT-01.md`.

**Owned files.** `tests/context/{test_integration,test_windows_paths,test_windows_restart}.py`; `tests/fixtures/context/README.md` and catalogued fixtures; `docs/components/CONTEXT-01.md`; minimal README usage/API documentation. Correct earlier story files only where tests expose a concrete defect.

**Tasks.**

1. Publish synthetic v1/v2 profiles through the existing approval path. Cover corrected facts, changed permissions, removed evidence, parent relationships and mixed precision dates. Build all three purposes against exact bound jobs with fitting and overflowing budgets.
2. Reopen the profile repository and repeat construction; compare canonical bytes, references, warnings and fingerprints. Check exact historical C08 resolution without using it to bypass the requested operational permissions.
3. Compare production JSON preparation with a test-only RAG consumer: identical eligible universe, eligibility, mandatory IDs/reasons, versions and privacy failures. Test top-k=0 at that fake boundary; mandatory anchors remain. Do not label this retrieval quality evaluation.
4. Run affected profile/contract tests and context tests, then the full regression suite once. Check generated schemas by the established exporter workflow. Keep tests synthetic and external runtime data outside the checkout.
5. Verify native Windows execution with space/non-ASCII profile/config paths, a different working directory, and process restart. Record actual OS/Python/counter versions and results. No network or model account is required for offline acceptance.
6. Complete the handoff checklist below, including current C01 limitations and unresolved measurement choices. Distinguish isolated builder correctness, fake integration, real tokenizer checks, live runtime fit checks and Windows verification.

**Acceptance criteria.** Every permitted fact and its provenance survives JSON construction; none of the private sentinels does. Mandatory information is complete or an explicit conflict prevents output. Repeated/restarted construction is stable. Budget boundary/overflow and failure visibility are demonstrated. No evidence is silently truncated and no fallback is labeled JSON. Native Windows results are recorded, or verification remains explicitly pending.

**Tests and proposed commands.** Commands are a future implementation recipe, not tests executed by this planning task. Test modules above do not exist yet.

```powershell
$repo = 'C:\Path To Checkout\Job Automation Prüfung'
$python = Join-Path $repo '.venv\Scripts\python.exe'
Set-Location -LiteralPath $repo
& $python -m pytest tests/context tests/profile tests/contracts
& $python -m pytest

# Run Windows/restart checks from another working directory using absolute paths.
Push-Location -LiteralPath $env:TEMP
try {
    & $python -m pytest (Join-Path $repo 'tests\context\test_windows_paths.py') (Join-Path $repo 'tests\context\test_windows_restart.py')
} finally {
    Pop-Location
}
```

Use `pathlib.Path` in tests and a test-owned external runtime root with spaces/non-ASCII characters, for example beneath `$env:LOCALAPPDATA`; never use real profile evidence. Do not claim live model fit from fake counters. If production measurement is unavailable, record the limitation and classify the component as implemented with that acceptance pending, rather than claiming fully verified operational budgeting.

Environment observation during planning: the existing `.venv\Scripts\python.exe` could not launch its configured base Python when invoked for a document-only check. Verify/repair the local interpreter before running this future recipe; the historical handoff's Python results do not establish that the present environment is runnable. Document structure and local links were instead checked with PowerShell; application tests were not run.

**Migration/configuration impact and handoff.** Record all shared schema changes, accepted legacy versions, inclusion/mandatory/serialization/settings versions and caller migration actions. No live external writes or deployment are needed. Next owners are CONTEXT-02/04, LLM-01, MODEL-02, MATCH-02 and GEN-02; their implementation remains separate.

## Unresolved choices and decision owners

These are decisions to close with implementation evidence, not reasons to invent token counts or widen the component. D01/D02 must close before full assembly; D03–D07 must have a selected supported behavior or an explicit production capability failure before budgeting is accepted.

| ID | Choice still to resolve | Owner / evidence required | Interim rule |
|---|---|---|---|
| D01 | C09 typed additions/version, auxiliary record placement, model projection and legacy reader compatibility | CONTEXT-01 S01 with FND-01; schema/fixture and downstream consumer checks | Keep existing fields' meanings; old records do not prove full accounting. |
| D02 | Exact essential chronology definition, ancestor policy and structured/string mandatory projection | CONTEXT-01 S01/S02 with PROFILE-01; purpose/parent fixtures and future RAG contract | Proposed policy above; permission always takes precedence, explicit mandatory conflict fails. |
| D03 | Exact local tokenizer versus provider-supported counting versus conservative estimation | CONTEXT-01 S04 with LLM-01/MODEL-02; installed capability, model/template parity, German/English/Unicode and long-input cases | Inject counters for tests. No tokenizer is presumed available; missing production capability is visible. |
| D04 | Effective window and output-cap values for each operation/model | MODEL-02 owns measurement; LLM-01 owns runtime settings; CONTEXT-01 consumes them | No production values inferred from 4 GB VRAM, model name or synthetic examples. |
| D05 | Chat-template, BOS/EOS, role framing and output-schema token overhead; breakdown attribution | CONTEXT-01/LLM-01 with pinned runtime/template and rendered-input comparison | Count full rendered input; unknown overhead cannot be assumed zero. Candidate subtotals alone cannot admit a request. |
| D06 | Safety allowance and admission policy for approximate counts; uncertainty threshold | CONTEXT-01/MODEL-02, calibrated maximum undercount and representative near-limit inputs | Estimate remains labeled; unsupported uncertainty fails visibly. Never claim guaranteed fit from a generic characters-per-token ratio. |
| D07 | Preflight versus observed provider usage reconciliation and mismatch handling | LLM-01/MODEL-02; identical frozen prompts, model digests/templates and runtime usage where available | Observed usage can be null. Later discrepancies are recorded and invalidate the counting configuration as needed; they do not retroactively turn estimates into exact counts. |
| D08 | Shared preparation rule-version lifecycle and where callers retain C09/rendered payload | CONTEXT-01/CONTEXT-04 and RUN-01/GEN-02 | Return explicit versions/fingerprints; no mutable global rules or new persistent cache here. |
| D09 | C01 defaulted eligibility/permissions, ongoing-status loss and richer provenance | PROFILE-01/FND-01; reviewed schema/publication/migration decision | Preserve supplied approved C01; never fabricate unknown distinctions or rehydrate from unapproved drafts. A required unavailable distinction is an explicit input limitation. |

## Completion and handoff checklist

- Report CONTEXT-01 and each story's status, actual owned files, requirement links and dependency/contract versions.
- Publish the exact request/preparation/builder/error APIs, canonical serialization/fingerprint recipe and downstream payload binding. Document legacy C09/selector compatibility without pretending the old signature supplies missing data.
- Prove complete eligible-record equality, shared purpose rules, mandatory eligibility/chronology, parent privacy, stable order/warnings, exact versions and C08/provenance traceability.
- Publish budget field meanings, full rendered-input recipe, counter/template/model identity, output reserve, safety policy and boundary/overflow evidence. Record unresolved measurement choices and real-world limits plainly.
- Demonstrate visible errors, no partial bundle, no truncation/summarization/relevance pruning and no automatic strategy/model switch. Candidate context and job text remain data; sensitive payloads stay out of diagnostics.
- Record commands/results separately for unit/contracts, fake consumers, native Windows, local tokenizer validation and live runtime integration. Mark tests pending where dependencies are unavailable.
- Leave retrieval/indexing, model benchmarks, assessment/generation orchestration, Salesforce and Phase 2 work with their owners. Successful JSON construction alone does not complete Phase 0 or the JSON/RAG comparison requirement.

Planning result: **six ordered stories, all PLANNED**. Only `docs/stories/CONTEXT-01.md` is created by this task. No application code, schemas, configuration, fixtures or component handoffs are changed; no application tests or live model checks are claimed.
