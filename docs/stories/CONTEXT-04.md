# CONTEXT-04 — RAG retrieval and shared context selector

Status: **PLANNED** · Planning date: **28 October 2026** · Phase 0 · Scope: **CONTEXT-04 only**

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), v1.0, especially §§4–6, 8–10. Direct requirements: **R06, R13**; supporting constraints: **R07, R11, R14, R15, R16**. All stories below describe future work. This planning task changes only this document.

## Objective and ownership

Expose one explicitly bound `json|rag` context-selector interface. Delegate complete JSON construction to CONTEXT-01. For RAG, combine keyword and semantic retrieval over one compatible CONTEXT-03 generation, resolve selected evidence against the approved snapshot, retain fact and parent references, and assemble C09 within a whole-request budget. Both strategies use the same snapshot, purpose, inclusion rules and mandatory policy. Mandatory eligibility and essential chronology bypass top-k; permission restrictions still apply.

Own selector dispatch, deterministic requirement-query construction, query embeddings through LLM-01, keyword/semantic scoring and fusion, optional evidence selection, RAG assembly, retrieval diagnostics and component-level labeled tests. Reuse CONTEXT-01 preparation/rendering/measurement boundaries and CONTEXT-03 guarded readers. Keep evidence and model calls local on native Windows within measured limits.

Exclude full JSON reconstruction, chunk creation, index building/activation/cleanup, profile approval or permission-policy redesign, embedding-model selection, model/runtime installation, final requirement interpretation and C11 assessment, document generation, Salesforce publication, persistent pipeline state and Phase 2 scheduling. EVAL-01 owns end-to-end JSON/RAG comparisons and final-model evidence-use metrics. Component retrieval tests supply evidence for that work; they do not complete it.

## Repository instructions and inspected dependency baseline

Follow the blueprint, [README](../../README.md) and [schema instructions](../../schemas/README.md). No applicable ancestor, repository, `docs/` or `docs/stories/` `AGENTS.md` was found; `C:/Users/mrite/.codex/AGENTS.md` is empty. Generate schemas from typed models, document shared-contract compatibility, use synthetic fixtures, and keep runtime data outside tracked source. Documentation paths use `/`; runnable instructions use PowerShell and native Windows paths.

**Requested handoff availability:** `docs/components/CONTEXT-01.md` and `docs/components/CONTEXT-03.md` are absent in this checkout. Read [CONTEXT-01 stories and handoff requirements](CONTEXT-01.md) and [CONTEXT-03 stories and reader handoff requirements](CONTEXT-03.md) as provisional coordination material. Neither is a completed implementation handoff. Recheck both paths before implementation and reconcile their delivered APIs rather than treating proposed names as existing code.

| Inspected source | Current behavior and consequence |
|---|---|
| [CONTEXT-01 service](../../src/job_automation/context/service.py), [builder](../../src/job_automation/context/json_builder.py), [records](../../src/job_automation/context/records.py), [ports](../../src/job_automation/context/ports.py) | Code now exists despite older story baseline statements. `ContextService.build_json_context(JsonContextRequest)` delegates to `JsonContextBuilder.build` and returns `(C09, error)`. `prepare_profile_context` returns a shared `PreparedProfileContext`. Presence of code is not completed verification. Delegate to these boundaries, subject to the gates below. |
| [Preparation](../../src/job_automation/context/preparation.py), [PROFILE-01 handoff](../components/PROFILE-01.md), [inclusion](../../src/job_automation/profile/inclusion.py) | Validate approval/graph, filter by purpose, reject missing/restricted mandatory IDs, and derive all permitted employment/education facts plus permitted ancestor chains and caller-required IDs as mandatory. Empty `allowed_uses` excludes a fact. Optional private parents remain opaque references with warnings. Reuse this exact policy; do not derive a narrower RAG chronology. |
| [Current selector protocol](../../src/job_automation/contracts/interfaces.py), [foundation fake](../../tests/fakes/fake_services.py) | `select_context(requirements, profile, strategy, token_budget)` lacks purpose, bound job content/revision, instructions, output reserve and model/template binding. Only a fake selector exists. S01 must explicitly version the public interface and migrate its consumers; missing inputs cannot be supplied as dummy values. |
| [Current C09](../../src/job_automation/contracts/context.py), [base contract](../../src/job_automation/contracts/base.py), [schema](../../schemas/v1/C09_context_bundle.schema.json) | C09 already has optional candidate/purpose/rule/builder/serialization metadata, structured mandatory context, fingerprint and `BudgetReport`, in addition to query/index fields. Records still default to schema `1.0`; there are no cross-field validators establishing complete accounting or fact/ID equality. `retrieval_settings` is an untyped dictionary. Reconcile existing additions before proposing another revision. |
| [Serialization](../../src/job_automation/context/serialization.py), [C01](../../src/job_automation/contracts/profile.py) | Static inspection finds `serialize_candidate_fact` calling `model_dump` on metrics although C01 metrics are strings, and mandatory chronology strings mapping unknown end dates to `Present`. These conflict with fidelity/unknown rules. CONTEXT-01 must correct and verify them; CONTEXT-04 must not fork a substitute full JSON builder. |
| [Binding](../../src/job_automation/context/binding.py), [measurement](../../src/job_automation/context/measurement.py), [rendering](../../src/job_automation/context/rendering.py), [budget](../../src/job_automation/context/budget.py) | Job binding permits opaque nonempty revision labels unless an authoritative custom validator is supplied. The default counter is a character-ratio estimate. Rendering repeats headers in component breakdowns; the full-input count is distinct from their sum. The builder does not return its frozen rendered prompt. Its fingerprint omits output-schema/model/budget/template settings and complete job content. Require upstream binding, payload and measurement handoffs before claiming production parity or fit. |
| [CONTEXT-02 plan](CONTEXT-02.md), [CONTEXT-03 plan](CONTEXT-03.md) | No implemented chunk/index modules or component handoffs are present. Proposed whole-fact chunks preserve primary/ancestor source mappings. Proposed reader supplies a verified, closeable generation handle, exact-term postings, bounded vectors and row/chunk resolution; it rejects incompatible spaces and unauthorized historical use. Tests may use explicit fakes until these APIs exist. |
| [LLM-01 handoff](../components/LLM-01.md), [embedding harness](../../src/job_automation/models/embeddings.py), [input binding](../../src/job_automation/models/inputs.py) | Local provider and offline tests exist; live verification is pending. Use `ModelProvider.embed(texts, model)` and its call metadata. Its nullable digest, model-name validation and no-truncation guarantees need the CONTEXT-03/LLM-01 compatibility handoff; same vector length is insufficient. Share the provider instance for serialized inference; RUN-01 owns the cross-process worker lock. |
| [Context tests](../../tests/context/test_preparation.py), [contract tests](../../tests/context/test_contract_boundary.py), [project configuration](../../pyproject.toml) | Current context tests cover request/preparation boundaries, not functioning hybrid retrieval or measured quality. No numeric retrieval dependency is declared. Existing `8192`/`512`/`64` context defaults and `3.5` characters/token are code defaults, not measured recommendations. MODEL-01/02 handoffs and measured configurations are absent. |

C01 also defaults remote eligibility to true and fact permissions to all purposes when omitted, and does not retain a separate ongoing-employment flag. PROFILE-01/FND-01 own those representation decisions. Preserve the supplied approved values and their limitations; never infer new authorization, proficiency, duration or ongoing status. Historical citation resolution does not authorize new use.

These observations are static inspection findings, not newly executed test results. Missing prerequisites block actual integration/verification, not contract planning or explicitly labeled fake tests. Do not implement whole prerequisite components to remove the gates.

## Contracts and invariants to freeze in S01

Names below are proposals, not APIs already available. Coordinate final names/schema versions with FND-01, CONTEXT-01 and CONTEXT-03 before dependent stories.

### Public request and result

Propose `ContextSelectorV2.select_context(request: ContextSelectionRequest) -> tuple[ContextSelectionResult | None, ClassifiedError | None]`, with exactly one non-null outcome. `ContextSelectionResult` contains the produced **C09**, the exact frozen model-facing payload/binding used for measurement, and any auxiliary retrieval trace not carried in C09. It is an auxiliary result envelope, not a new numbered contract. Consumers receive the same result shape for both strategies.

| Contract/input | Required meaning |
|---|---|
| `ContextSelectionRequest` | Explicit `json` or `rag`; exact approved C01 and candidate/profile fingerprint; purpose (`assessment`, `cv`, `cover_letter`); canonical job ID, exact C07 revision and corresponding C06 content verified by a read-only binding port; requirement inputs; instructions, prompt/schema/template versions; generation-model configuration and effective window/output reserve/safety settings; inclusion/mandatory versions and explicit mandatory IDs. RAG also requires exact index/read authorization and retrieval settings. |
| `RequirementQuerySet` | Versioned deterministic query recipe and query-set content fingerprint; stable requirement/query IDs; ordered original text and query text/terms; C08 job references to source field/span or an explicit caller-supplied provenance classification; policy/vocabulary version when aliases are used. Query construction is independent of final C11. |
| `RetrievalSettings` | Typed validated values, schema/algorithm version and canonical effective-settings fingerprint; per-channel candidate limits, optional-fact top-k, fusion/tie/aggregation rules, keyword analyzer binding, query-format version, metric/normalization binding, finite work limits and explicit failure policy. No implicit model selection. |
| Index/query binding | CONTEXT-03 expected candidate/profile/purpose, snapshot/chunk manifest fingerprints, index artifact/generation identity, embedding-space fingerprint, analyzer/settings versions, current-use or explicitly authorized frozen-use mode and read token. Query embedding identity includes verified model/digest, dimension, input format/prefix, compatible runtime/options and normalization. |
| `RetrievalTrace` | Per-query channel statuses, bounded ranked hits, chunk/fact/parent C08 references, channel scores/ranks and fusion score, selection reasons, budget exclusions, selected versus merely retrieved IDs, call IDs and safe warning codes. Keep audit-only trace out of the model payload unless explicitly rendered and counted. |
| `ContextSelectionResult` | C09 plus frozen rendered payload/binding, construction fingerprint and trace. No partially admitted result on failure. JSON uses CONTEXT-01's payload and bundle; RAG supplies its selected projection through the shared rendering/measurement boundary. |

Retain the legacy protocol as explicitly deprecated until its fake/tests and any consumers migrate. Do not implement the under-specified four-argument API by inventing job revisions, assuming `assessment`, or treating a candidate token allowance as a model window. A legacy adapter may succeed only with an explicit immutable complete request binding; otherwise return a classified unsupported-input error. Record the API/reader migration and blueprint decision required for the incompatible interface change.

### Shared preparation and mandatory context

Use one CONTEXT-01 preparation policy and PROFILE-01 permission evaluator for both paths. Bind configured rule versions to the actual preparer; a requested version string cannot merely relabel a different implementation. Unsupported versions fail. JSON must receive the complete approved snapshot, never a RAG-selected subset. RAG queries only the matching purpose-bound index and revalidates all returned sources against the same prepared eligible universe before returning content.

Mandatory-policy v1 is the current shared proposal/code: all represented explicit eligibility, every permitted employment and education fact, permitted ancestor chains of permitted evidence, and explicit caller-required IDs. Mandatory fact IDs/reasons, structured eligibility and chronology are identical between strategies for identical preparation inputs, including `top_k=0`, empty queries and no hits. Eligibility uses a profile-version/field-path citation; it has no invented fact UUID. Privacy is evaluated before deriving chronology. Explicitly required restricted context is a permission error; missing mandatory IDs are validation errors.

Resolve selected primary facts and permitted ancestors using C08 `(profile_version, fact_id)` plus the candidate binding. Preserve parent IDs, role/project hierarchy, original claims/skills/metrics/provenance and exact date precision. Ancestor content is attributed to the ancestor, never inherited as a child's achievement. A restricted optional parent remains an opaque ID and a limitation warning. If upstream chunk policy requires that parent, fail rather than secretly suppressing the conflict. Reconcile CONTEXT-02's required-parent proposal with shared preparation before accepting integration.

RAG's model projection uses complete selected approved facts, mandatory context and permitted parent records. Chunks identify retrieval hits; they do not become fabricated C01 records or cropped “full facts.” Preserve chunk/source mappings in the trace. Deduplicate by evidence identity, not text: equal text under distinct fact IDs remains distinct evidence. Include all parent records actually rendered in `selected_fact_ids`, except opaque restricted references whose text is not rendered. Do not fetch raw evidence/provenance files.

### Retrieval, budgeting and C09 semantics

1. Validate request, shared preparation and job binding. For JSON, delegate without opening an index or calling embeddings. For RAG, acquire one exact authorized index generation; never mix keyword rows from one generation with vectors from another.
2. Build deterministic queries from supplied requirements or a documented C06 title/description fallback. Validate claimed job quotations/spans. Caller-supplied hints remain labeled as such; they do not become verified employer requirements. Bound query work; oversized inputs fail visibly rather than silently dropping requirements. Empty input means no optional query work, with a warning. Query text and retrieved text are untrusted data, never instructions or tool authority.
3. Query both keyword and semantic channels. Use CONTEXT-03's analyzer and query-format rules, LLM-01 for embeddings and CONTEXT-03's identity checks. Collapse duplicate chunk hits for the same primary fact within each channel before fact-level fusion; retain all contributing source references. Use bounded matrix blocks and deterministic ranking/ties. A valid empty channel differs from an unavailable/corrupt channel; default behavior fails on channel failure with no keyword-only, JSON, old-index or alternate-model fallback.
4. Reserve mandatory context first. Rank optional evidence with the frozen fusion policy, inspect candidates in order, and admit at most `top_k` distinct optional primary facts. A candidate's required permitted parent closure is indivisible. Skip an optional group that does not fit and record `budget_omitted`; continue with later groups deterministically. Do not shorten claims or mandatory facts. Mandatory-only overflow returns `context_budget` with no usable C09.
5. Re-render and measure the entire final request, including instructions, schema, job/requirements, candidate/parent/mandatory content, framing and runtime template overhead. Admit only when `P + O + M <= L`. `token_budget` remains the positive candidate allowance; `estimated_tokens` describes the actual candidate projection. Record full input, breakdown, output reserve, margin, remaining capacity, counter/method/version and exactness in `BudgetReport`. Count duplicated transmitted material. The whole rendered input governs admission; independently counted parts are not assumed additive. Estimates require a calibrated admission policy; missing/uncertain counting capability is visible.
6. Recheck read authorization and bindings before publishing the result, release the handle in all paths, and freeze exactly what was measured for downstream LLM-01 binding. Changes to permissions/profile/configuration during retrieval cannot yield a stale success. Unsupported frozen-use authorization fails closed. Do not rely on a pin alone as permission.

| C09 field or coordinated addition | JSON | RAG |
|---|---|---|
| `strategy`, candidate/profile/purpose, posting revision | Exact delegated identity | Exact request/index/preparation identity |
| `ordered_facts`, `selected_fact_ids` | Complete permitted set from CONTEXT-01 | Exact ordered unique records/IDs actually included, including mandatory facts and rendered ancestors; IDs match facts one-for-one |
| `structured_mandatory`, `mandatory_fact_ids`, `mandatory_context` | Shared preparation | Same shared preparation, unaffected by retrieval limits; string projection must not contradict structured unknowns |
| `query_version`, `index_version` | Null, unchanged | Versioned query identity bound to recipe and actual query-set hash; immutable index artifact identity per CONTEXT-03 mapping, with generation UUID and manifest hash retained in audit metadata |
| `retrieval_settings` | Null, unchanged | Canonical serialized typed settings, including algorithm/settings version and fingerprint; never an unversioned bag of top-k values |
| Proposed typed `retrieval_audit` | Null | Retrieved chunk/fact IDs, final selected references/reasons, per-query outcomes, index/query embedding identity and call references, budget omissions and warnings; no raw vectors required |
| Budget and content identity | Delegated report and payload binding | Complete measured projection, report and frozen-payload binding; constructor identity includes snapshot/job content, purpose/rules, query/index/settings, prompt/schema/template, model/configuration and reserves |

Freeze the C09 extension/version and legacy reader rules in S01. Old `extra='forbid'` readers cannot consume arbitrary additions. Old records may remain readable for audit but cannot prove current permission, retrieval completeness or model admission. Keep CONTEXT-01's JSON null-RAG convention and field meanings. Separate stable fingerprints from attempt timestamps, call UUIDs and latency. Changes to any output-affecting input must invalidate construction identity; do not rename the existing incomplete fingerprint as proof of a full payload binding.

### Retrieval misses are not candidate-skill absence

Runtime outcomes report observations: `candidates_retrieved`, `no_hits`, `no_query`, `empty_permitted_corpus`, `budget_omitted`, or a classified operational failure. “Retrieved” means a search result, not verified support for the requirement. A high similarity score is not proficiency or eligibility evidence. With no semantic cutoff, even an unrelated corpus can return nearest neighbors; never describe that as supported skill coverage.

Use labeled cases or an explicit later review of the complete permitted snapshot to determine retrieval false negatives. Runtime cannot infer a hidden oracle from top-k. Distinguish these evaluation labels:

- `supported_in_permitted_snapshot`: gold C08 evidence exists; if it is not retrieved, record a retrieval miss; if retrieved but not packed, record a selection/budget miss.
- `not_documented_in_permitted_snapshot`: the complete allowed snapshot lacks supporting evidence according to the label/review. This is an evidence gap, not a claim that the candidate lacks the skill.
- `explicit_negative_evidence`: a cited approved statement explicitly limits experience or capability; retain negation. Interpretation belongs to MATCH-02, not a search-score threshold.
- `not_assessable`: restricted/unavailable evidence, ambiguous requirement or incomplete labels. Do not search another purpose/history or disclose restricted text to fill the gap.

Provide MATCH-02/GEN-02 with coverage warnings and references; do not emit C11 rejects, invented negative candidate facts or automatic unsupported-claim judgments. Final-model failure to use selected evidence is a separate EVAL-01 metric.

## Provisional settings and measurement gates

These are **unmeasured engineering proposals for fixtures and initial experiments**, not tuned quality claims, acceptance scores or user preferences. Freeze/version them before implementation; record effective values on every result.

| Setting | Provisional behavior | Evidence needed before a production recommendation |
|---|---|---|
| Optional primary-fact `top_k` | `8`; allow explicit `0`; mandatory/parent context does not consume these slots | Labeled coverage and final packing results at several budgets; count total included facts separately |
| Per-query channel pool | Up to `20` unique primary facts per channel; `top_k` cannot exceed a pool's configured limit | Candidate recall and work/resource measurements; detect invalid combinations, never silently clamp |
| Keyword score | Count distinct matching normalized query terms; rank descending, no repeated-term boost; preserve exact skill tokens per CONTEXT-03 analyzer | German/English, `C++`, `C#`, `.NET`, umlaut, case and punctuation fixtures; no assumed stemming or accent stripping |
| Semantic score | Index-declared metric/normalization; cosine only if compatible configuration explicitly selects it; reject invalid/zero vectors as required by that metric | MODEL-02/CONTEXT-03 immutable embedding-space and numeric-tolerance handoff |
| Hybrid fusion | Equal-weight reciprocal rank fusion: `sum(1 / (60 + channel_rank))`, ranks start at 1; absent channel hit contributes zero | Labeled ablations and parameter sweep; scores are ranking signals, never probabilities |
| Multiple queries/ties | Fuse per query, then use the maximum per-query fused score for a fact; tie by number of query lists containing it, best channel rank, then fact UUID; chunk ties by chunk ID | Multi-requirement coverage tests and documented deterministic ordering; no frequency inflation from duplicate chunks |
| Semantic threshold | None initially; no cutoff-based “skill absent” decision | Labeled positive/negative calibration before adding a threshold and new settings version |
| Aliases and reranking | No undeclared expansion, translation or LLM reranker; optional aliases only from a supplied validated POLICY-01 vocabulary/version, retaining original terms | Controlled alias/cross-language cases; search expansion never modifies candidate facts |
| Channel failure | Fail visibly; no degraded successful RAG by default | Error/recovery tests; any future degraded mode needs an explicit contract/settings decision |
| Limits and caching | Finite query count/text/token/block/time limits required; serialized bounded calls; no retrieval cache in v1 | MODEL-02/CONTEXT-03 resource settings and observed local workload; 16 GB RAM/4 GB VRAM are not allocations |
| Model and generation budget | No selected model/digest, dimension, production window, tokenizer or safety allowance is supplied here | MODEL-01/02 and CONTEXT-01/LLM-01 measured handoffs; existing example values are not substitute evidence |

Do not claim that hybrid retrieval is better than either channel, that top-k=8 is sufficient, or that any model fits until the recorded measurements support that claim. Offline fake vectors demonstrate mechanics only.

## Ordered implementation stories

All stories are **PLANNED**. Paths beginning `context/` or `contracts/` below are relative to `src/job_automation/`; new filenames are proposed. Shared-file changes are narrow coordinated edits. No story owns upstream index migrations or JSON construction.

| Order | Story | Dependencies | Deliverable |
|---|---|---|---|
| 1 | CONTEXT-04-S01 | FND-01; CONTEXT-01 and CONTEXT-03 contract coordination | Versioned shared selector, result/C09 audit contracts and migration plan |
| 2 | CONTEXT-04-S02 | S01; PROFILE-01; CONTEXT-01 preparation/builder | Shared validation/preparation and delegated JSON dispatch |
| 3 | CONTEXT-04-S03 | S01–S02; LLM-01; CONTEXT-03 embedding/query-format contract | Deterministic bounded query set and compatible query embeddings |
| 4 | CONTEXT-04-S04 | S01–S03; CONTEXT-03 guarded reader | Keyword/semantic retrieval, deterministic fusion and trace |
| 5 | CONTEXT-04-S05 | S02–S04; CONTEXT-01 rendering/measurement handoff | Mandatory-first, parent-preserving RAG assembly and budget admission |
| 6 | CONTEXT-04-S06 | S01–S05 | Complete C09/result, safe diagnostics and consumer boundary |
| 7 | CONTEXT-04-S07 | S01–S06; synthetic labels; EVAL-01 coordination | Labeled retrieval regression suite and metric definitions |
| 8 | CONTEXT-04-S08 | S07; actual CONTEXT-01/02/03 for real local integration | Native Windows/restart and cross-component verification |
| 9 | CONTEXT-04-S09 | S08; MODEL-01/02, LLM-01 and CONTEXT-03 live readiness | Measured retrieval experiment and precise component handoff |

### CONTEXT-04-S01 — Freeze the selector, audit and compatibility contracts

**Objective/references.** Expose a complete shared request/result without hidden context or competing C09 meanings. R06/R13; C01/C06/C07/C08/C09/C10.

**Dependencies.** FND-01; current CONTEXT-01 records/code and eventual handoff; CONTEXT-03 proposed reader/manifest handoff. Contract work may use explicitly marked provisional ports.

**Inputs → outputs.** Existing legacy selector/C09 and upstream interfaces → versioned `ContextSelectionRequest`, `ContextSelectionResult`, query/settings/trace records, public V2 protocol, C09 extension and compatibility decision.

**Owned files.** `context/{selector_records,selector_ports,retrieval_settings}.py`; narrow `contracts/{interfaces,context,__init__,export_schemas}.py` edits; generated C09/auxiliary schemas and `schemas/README.md`; `tests/context/test_selector_contracts.py`; affected `tests/contracts/`, C09 fixtures and `tests/fakes/fake_services.py`.

**Tasks.** Freeze the contract tables above, settings fingerprints, exact-one-result invariant, current/frozen authorization boundary, and distinct candidate/generation budgets. Define strategy-conditional validation: JSON null retrieval metadata; RAG complete query/index/settings identity. Specify fact/ID/mandatory subset and budget consistency checks. Register the legacy reader/selector migration, including the returned payload envelope. Obtain upstream decisions for the static fidelity/binding/measurement gaps; record them as owner gates rather than implementing a second builder.

**Acceptance criteria.** Missing purpose/job binding/model budget cannot yield a production success. Unknown strategy/version/settings fail clearly. Valid RAG C09 round-trips with selected, retrieved and mandatory IDs distinguished. A legacy C09 remains audit-only unless its required metadata is present and valid. JSON completeness validators do not require RAG to include the full optional universe. No protocol migration leaves stale fake/test signatures masquerading as V2 conformance.

**Tests.** `RET-01`, `RET-14`, `RET-17` below; valid/invalid conditional schemas, cross-field ID/budget mismatches, defensive copying, unsupported versions and regenerated-schema consistency.

**Migration/configuration impact and handoff.** Publish the chosen schema/API versions and consumer upgrade plan before S02. No database migration is expected for this stateless selector; persisted C09 readers must be coordinated explicitly if a schema upgrade requires one.

### CONTEXT-04-S02 — Reuse shared preparation and delegate JSON

**Objective/references.** Establish one approved evidence universe and mandatory policy for both branches. R06/R11/R15.

**Dependencies.** S01; PROFILE-01; CONTEXT-01 preparation and public JSON builder. JSON acceptance requires upstream fidelity, chronology, binding and payload gaps to be resolved and tested.

**Inputs → outputs.** Fully bound request and explicit services → validated prepared universe, exact JSON delegation/result or shared classified validation/permission error; a prepared RAG input for later stories.

**Owned files.** `context/{selector,selector_validation}.py`; narrow exports/service wiring in `context/{__init__,service}.py`; `tests/context/{test_selector_dispatch,test_selector_inclusion,test_selector_json_delegate}.py`; `tests/fakes/context_selector_dependencies.py`.

**Tasks.** Validate exact snapshot/job/purpose and supported rule settings. Wire the same preparer and authorization semantics into both paths. Adapt complete request fields to `JsonContextRequest` without changing evidence, reserves or warnings. Require the CONTEXT-01 frozen payload result/binding; coordinate any small public adapter with that owner. Keep RAG settings/index readiness irrelevant to valid JSON calls. Handle unsupported RAG prerequisites visibly until implemented.

**Acceptance criteria.** A spy builder receives the original complete approved snapshot and bound values exactly once; JSON never opens an index or calls embeddings. Its success is equivalent to direct CONTEXT-01 output, allowing only the documented outer result envelope. JSON overflow/error propagates with no automatic RAG retry. For each supported purpose, both paths prepare identical eligible IDs, mandatory IDs/reasons, eligibility and chronology. Unapproved snapshots, required private parents, missing mandatory facts and unsupported rule versions fail identically.

**Tests.** `RET-01`, `RET-02`, `RET-03`, `RET-10`, `RET-14`; actual JSON parity with nonempty string metrics, unknown end date, purpose differences, nested parents, nulls and long evidence. Label fake-builder contract tests separately from actual CONTEXT-01 integration.

**Migration/configuration impact and handoff.** No new profile or permission policy. Publish exact dispatch/error behavior; upstream fixes stay attributed to CONTEXT-01/PROFILE-01 and block relevant acceptance until delivered.

### CONTEXT-04-S03 — Construct requirement queries and compatible embeddings

**Objective/references.** Produce bounded traceable retrieval inputs before final assessment. R06/R07/R13/R15; C06/C07/C08/C10.

**Dependencies.** S01–S02; LLM-01 embed API; CONTEXT-03 query analyzer/embedding-space contract. MODEL-02 supplies production model and limits. POLICY-01 is optional only when an explicit alias vocabulary is supplied.

**Inputs → outputs.** Bound requirements or declared job-text fallback, query settings and index manifest → stable query set, normalized keyword terms and query vectors with compatible identity/call references, or classified input/model/limit failure.

**Owned files.** `context/{queries,query_embeddings}.py`; `tests/context/{test_requirement_queries,test_query_embeddings}.py`; synthetic query fixtures and `tests/fakes/retrieval_embeddings.py`.

**Tasks.** Define stable requirement/query IDs, exact source binding, deterministic ordering/deduplication and a versioned fallback recipe. Keep caller hints separate from source-backed requirements. Apply the index's analyzer to original and explicitly configured alias terms. Follow its model-specific query prefix once, without applying document prefixes incorrectly. Enforce finite count/length/token/deadline limits; use the shared local provider and retain call identity. Verify every response's model/digest/space, count, dimension and finite values before scoring. No final C11, LLM requirement extractor, cloud fallback or direct HTTP client.

**Acceptance criteria.** The same frozen requirements/settings produce the same query fingerprint. Changed source text, alias version or prefix changes identity. Invalid spans or job revision fail. An empty query list remains distinguishable from failed embedding; no empty-string model call occurs. A model/digest mismatch of equal dimension fails. Null digest requires the documented verified immutable binding, never an assumed match. Hostile instructions in job text affect only query data.

**Tests.** `RET-04`–`RET-07`, `RET-11`, `RET-12`, `RET-16`; query limits at/over boundary, duplicate requirements, multilingual text, missing model, timeout, malformed vectors and query-format mismatch.

**Migration/configuration impact and handoff.** Version query recipe/settings independently from index build settings. A query-format change that changes embedding space requires a compatible index, not relabeling vectors. Hand off query provenance and classified failure codes.

### CONTEXT-04-S04 — Combine keyword and semantic retrieval deterministically

**Objective/references.** Retrieve candidate evidence using both channels without losing exact references or confusing failure with no matches. R06/R07/R13/R16.

**Dependencies.** S01–S03; CONTEXT-03 guarded reader and row/source mappings. Fakes may implement that port for mechanics tests, not production access.

**Inputs → outputs.** Prepared universe, compatible query set/vectors, exact read request and settings → bounded per-channel fact ranks, fused optional candidates and retrieval trace, or classified failure.

**Owned files.** `context/{retrieval,keyword_retrieval,semantic_retrieval,fusion}.py`; `tests/context/{test_keyword_retrieval,test_semantic_retrieval,test_hybrid_retrieval,test_retrieval_reader_binding}.py`.

**Tasks.** Open one guarded generation, use parameterized exact-term primitives and bounded vector blocks, validate every hit against the prepared universe and source mappings, collapse same-fact duplicates and apply the frozen scoring/fusion/tie rules. Keep original scores and ranks independently, without adding incomparable raw scores. Preserve primary/ancestor attribution and index/query/settings identities. Release handles on all outcomes and check read-token validity between operations. Bound total work and leave retry control to LLM-01/caller policy.

**Acceptance criteria.** Exact-only and semantic-only labeled facts can both reach the fused list; a hit in both channels appears once with both reasons. Equal text with distinct fact IDs is not merged. Repeated parent text or chunk duplication cannot multiply a fact's score. Same input/fake vectors gives identical order across processes. Wrong-purpose/stale/corrupt index or channel outage produces failure, never an empty successful search or unannounced lexical-only result. Query terms cannot execute SQL or control file access.

**Tests.** `RET-04`–`RET-09`, `RET-11`–`RET-13`, `RET-16`; matrix-block boundaries, deterministic ties, both-channel deduplication, incompatible model/settings, active generation replacement and close-on-error behavior.

**Migration/configuration impact and handoff.** No index-format or storage ownership transfer. Any missing reader primitive is a narrow CONTEXT-03 contract request. Publish score units, pool semantics and reproducibility limits.

### CONTEXT-04-S05 — Pack mandatory context and parent-complete optional evidence

**Objective/references.** Preserve essential candidate context while fitting the actual generation request. R06/R07/R11/R13; C08/C09.

**Dependencies.** S02–S04; CONTEXT-01 shared rendering/measurement/admission APIs and corrected mandatory projection; MODEL-02/LLM-01 budget capability for real acceptance.

**Inputs → outputs.** Shared mandatory set, ranked optional facts, permitted source graph and model budget → deterministic RAG candidate projection, selected records/reasons, omissions and admitted frozen payload/report, or visible budget/permission/binding error.

**Owned files.** `context/{rag_builder,rag_serialization,rag_budget}.py`; `tests/context/{test_rag_mandatory,test_rag_parent_context,test_rag_budget}.py`. Reuse shared preparation/measurement via ports; coordinated helper generalization must not duplicate the JSON builder or alter its completeness behavior.

**Tasks.** Build mandatory-only projection first; preserve structured eligibility even when no fact is retrieved. Add optional fact groups in fused order with complete allowed ancestors, deduplicate rendered records and measure each proposed addition under finite packing limits. A fact already mandatory needs no optional slot. Define final order as shared mandatory order followed by accepted optional groups, inserting any additional permitted ancestors before children in stable root-to-leaf order. Record skipped candidates/reasons and measure the final exact payload again. Preserve unknown dates, original qualifiers, metrics and C08 references. Never reduce instructions, output reserve or job content to force a fit.

**Acceptance criteria.** `top_k=0` and no hits still retain mandatory eligibility and chronology. Required parent text survives a child-only retrieval hit and counts toward budget. Restricted optional parent content never appears; explicit mandatory conflict fails. Optional overflow skips whole groups with warnings. Mandatory-only overflow and no positive candidate allowance return only `context_budget`. Exact boundary fits; one token over fails. JSON remains complete-or-error under the same budget, without being pruned by RAG logic.

**Tests.** `RET-02`, `RET-03`, `RET-08`–`RET-10`, `RET-14`, `RET-17`; shared parents counted once when rendered once, repeated transmitted strings counted each time, component non-additivity, output schema/framing overhead, changed template and unavailable counter.

**Migration/configuration impact and handoff.** Publish packing/ordering version, selected-versus-retrieved semantics, budget units and estimate policy. No standalone uncalibrated tokenizer or production window is introduced. Exact rendered-input handoff is a required integration gate.

### CONTEXT-04-S06 — Finalize C09, safe warnings and downstream semantics

**Objective/references.** Make selection auditable and prevent retrieval uncertainty from becoming invented skill gaps. R06/R13/R15/R16; C09/C10 and future MATCH-02/GEN-02 boundary.

**Dependencies.** S01–S05; coordinated JSON result and C09 reader changes.

**Inputs → outputs.** Admitted projection, selected evidence, trace and frozen bindings → validated C09/result with explicit coverage observations, or a safe classified error with no partial bundle.

**Owned files.** `context/{selector_result,retrieval_diagnostics,retrieval_errors}.py`; final `context/selector.py` wiring; `tests/context/{test_retrieval_audit,test_selector_consumer_boundary,test_retrieval_diagnostics}.py`; test-only assessor/generator consumers.

**Tasks.** Populate C09 per the field table, validate IDs/permissions/versions, attach stable construction identity and frozen payload binding, and recheck authorization before return. Separate raw hits, packed evidence and mandatory inclusion. Report safe warning codes such as `NO_OPTIONAL_QUERY`, `NO_RETRIEVAL_HITS`, `OPTIONAL_BUDGET_OMISSION`, `PARENT_CONTEXT_RESTRICTED` and `TOKEN_COUNT_ESTIMATED`; exact code names freeze in S01. Map failures to existing categories with reason codes, retaining upstream call IDs where safe. Diagnostics exclude private text, raw prompts, vectors, secret URLs and exception payloads. Return trace locally; RUN-01/GEN-02 own durable storage.

**Acceptance criteria.** Every selected ID resolves to the exact included approved fact; every retrieved hit identifies query/channel/chunk/index. Mandatory/ancestor additions have reasons even without a hit. All query/index/settings versions and budget data are present for successful RAG. A consumer fake cannot convert no hits, budget omission or service outage into “candidate lacks skill” or a C11 reject. It receives the same immutable payload measured by the selector. Changing any bound input invalidates construction identity. No external write or assessment/generation call occurs.

**Tests.** `RET-01`, `RET-10`–`RET-12`, `RET-14`–`RET-17`; exact-one-result, nested input mutation, stale authorization at finalization, safe diagnostic sentinels, C09 serialize/reload and payload hash mismatch.

**Migration/configuration impact and handoff.** Publish the warning/error vocabulary and downstream responsibility for review/pending decisions. No new broad error category or automatic retry loop is needed. Retries preserve explicit input bindings and must not silently choose a newer index/profile.

### CONTEXT-04-S07 — Establish labeled retrieval regression tests

**Objective/references.** Demonstrate retrievability and identify where supporting evidence was lost, without claiming general semantic quality. R06/R13.

**Dependencies.** S01–S06; reviewed synthetic labels. Coordinate fixture/metric format with EVAL-01 without implementing its comparison pipeline.

**Inputs → outputs.** Frozen synthetic approved profiles, job requirements, purpose-specific gold references, negative/unknown labels and controlled vectors → reproducible labeled test results and a component retrieval report format.

**Owned files.** `tests/context/{test_retrieval_labels,test_retrieval_metrics,test_retrieval_reproducibility}.py`; `tests/fixtures/context/retrieval/{README.md,cases.json}` and synthetic profiles/jobs; `tests/fakes/retrieval_embeddings.py`. No production `evaluation/` pipeline in this story.

**Tasks.** Implement the labeled catalog below. Each case records case/schema/label versions, rationale, candidate/profile/purpose/job binding, exact gold C08 IDs, acceptable alternative evidence sets, forbidden IDs and expected stage outcomes. Freeze labels before tuning and distinguish tuning cases from held-out cases. Calculate channel candidate recall, fused recall, final packed evidence coverage, mandatory coverage and permission violations separately. For nonempty gold sets, recall is `gold IDs present / gold IDs`; for empty gold sets, recall is not applicable, not 100%. Report case counts and per-case misses, plus aggregate numerator/denominator and macro/micro convention. Record retrieval versus budget misses and preserve unknown labels.

**Acceptance criteria.** Every deterministic fixture passes its specified evidence/permission/budget invariants, including forced misses; a forced miss is a correctly diagnosed test outcome, not a perfect-recall claim. A case with known supporting evidence below the pool/top-k limit reports a retrieval/selection miss, while a no-documented-evidence case never asserts absence of skill. Mandatory coverage is complete on successful bundles and permission violations are zero. Fake-vector semantic tests are explicitly mechanics tests. Missing real-model results remain pending.

**Tests.** All `RET-01`–`RET-18`; metric unit cases with known numerators/denominators, multiple valid evidence alternatives, empty gold sets, partial labels and both retrieval/packing loss. Assert exact expected IDs/order for fake-vector cases rather than arbitrary aggregate quality thresholds.

**Migration/configuration impact and handoff.** Version fixtures, labels and report calculations. EVAL-01 receives selected/retrieved references and stage metrics; final-model use, unsupported claims, assessment errors and reviewer effort remain its responsibility.

### CONTEXT-04-S08 — Verify actual integration and native Windows behavior

**Objective/references.** Verify the selector against real local component boundaries and failure/restart behavior. R06/R13/R14/R15/R16.

**Dependencies.** S07; implemented CONTEXT-01/02/03 and their delivered handoffs. Explicit fake tests can run earlier but do not satisfy actual integration.

**Inputs → outputs.** Synthetic profile revisions, actual local indexes with deterministic fake embeddings, corrected JSON builder, fake provider transport and frozen requests → recorded local integration/Windows results and pending-live status.

**Owned files.** `tests/context/{test_selector_integration,test_selector_windows_paths,test_selector_windows_restart}.py`; `tests/fixtures/context/retrieval/README.md`; draft verification sections in `docs/components/CONTEXT-04.md`; concise README API usage. Earlier files change only for demonstrated defects.

**Tasks.** Build/reopen actual CONTEXT-03 indexes from actual CONTEXT-02 chunks; run both strategies through the shared selector; compare source/purpose/mandatory parity. Publish changed/removed/permission-narrowed synthetic profiles through PROFILE-01 and prove old handles cannot serve new work. Exercise active-generation replacement, index corruption, caller mutation, reader release after failure and deterministic close/reopen. Verify JSON still works without a model service/index when its measurement dependency is available. Run focused/affected suites and one full regression after fixes.

**Acceptance criteria.** Real local component integration reproduces fake-port invariants without bypassing guards or using storage internals. Restart preserves reference/version interpretation; a missing current index is a visible error. Absolute Windows paths containing spaces/non-ASCII characters and a different working directory work. No profile/index writes originate from selection, no leaked handles block cleanup, and no private payload appears in ordinary logs. Tests requiring absent prerequisites are recorded pending, not passed.

**Tests.** `RET-01`–`RET-03`, `RET-08`–`RET-18`, affected contracts/profile/models/context suites. Record actual commands/environment/results; do not reuse historic handoff counts.

**Migration/configuration impact and handoff.** No selector-owned SQLite migration or CLI pipeline. Coordinate schema consumer updates with upstream owners. Record actual versus fake dependencies and native Windows results separately.

### CONTEXT-04-S09 — Measure real retrieval and publish the component handoff

**Objective/references.** Verify the chosen local configuration and report observed labeled behavior with explicit limits. R06/R07/R13/R14.

**Dependencies.** S08; MODEL-01 runtime readiness, MODEL-02 measured generation/embedding configuration, LLM-01 live identity/no-truncation readiness, CONTEXT-03 verified real-model index and CONTEXT-01 model/template measurement binding. Missing prerequisites leave this story pending.

**Inputs → outputs.** Explicit installed model/configuration/report references, frozen synthetic corpus/labels and bounded settings experiment → reproducible retrieval measurements, chosen or still-provisional settings and `docs/components/CONTEXT-04.md`.

**Owned files.** `tests/manual/context_retrieval_smoke.py` outside default pytest collection; synthetic real-check inputs under `tests/fixtures/context/retrieval/`; `docs/components/CONTEXT-04.md`; concise manual instructions. MODEL-02 benchmark artifacts and EVAL-01 application comparisons remain with their owners.

**Tasks.** Require explicit config/index/model/label references; never choose the first installed model or automatically download one. Verify immutable query/index compatibility, retrieve and pack the same labeled requirements, and compare keyword-only, semantic-only and hybrid **diagnostic experiments** with the same pool/budget/input bindings. These ablations do not enable production fallback. Record per-case stage coverage, top-k/pool/fusion settings, timing, token measurement method, resource observations and failed/unknown cases. Separate tuning from held-out results, retain all tested configurations and avoid tuning labels to outcomes. If evidence does not support a recommendation, retain provisional status and explain the misses.

**Acceptance criteria.** Actual compatible embeddings retrieve labeled supporting facts in the declared acceptance cases and preserve all safety/reference/mandatory/budget invariants. Report failures without lowering a hidden threshold or claiming success from a skipped check. Latency/RAM/VRAM observations identify method, hardware/runtime/model identity and unavailable telemetry. Results apply only to the recorded corpus/configuration; no universal quality, model fit or JSON/RAG assessment superiority claim follows. Any unmet real acceptance leaves the component `IMPLEMENTED — live verification pending` or explicitly failed, not `VERIFIED`.

**Tests/procedure.** `RET-04`–`RET-10`, `RET-12`, `RET-15`, `RET-17`–`RET-18` on the frozen real-check corpus. Script reports `passed`, `failed` or `pending_prerequisite` with distinct exit behavior. Use only local services and synthetic data; no Salesforce write or full generation workflow. Document actual commands and results in the handoff.

**Migration/configuration impact and handoff.** Freeze effective settings/version only with the recorded evidence; settings changes invalidate selection identity. Hand off to MATCH-02, GEN-02, RUN-01 and EVAL-01 with remaining gates and exact public contracts.

## Labeled retrieval test catalog

IDs are stable fixture/test labels, not claims that tests exist or have passed. Synthetic symbolic evidence names below must map to fixed UUIDs/C08 references in fixtures. Label supporting evidence against the complete permitted snapshot before inspecting retrieval output.

| Label | Case and oracle | Required observable outcome |
|---|---|---|
| RET-01 — shared selector | Same snapshot/job/purpose/rules through `json` and `rag`; spy JSON builder | JSON delegates with all allowed facts and null retrieval metadata; both use identical mandatory/preparation results. No index/embed call for JSON. |
| RET-02 — mandatory bypass | Eligibility plus unrelated employment/education chronology; `top_k=0`, empty query, and irrelevant query variants | Every mandatory item remains with exact source/precision, even when neither channel ranks it. No fabricated eligibility UUID. |
| RET-03 — permission matrix | Assessment-only, CV-only, cover-letter-only and private facts; explicit restricted/missing mandatory ID variants | Purpose parity between strategies; excluded text absent from queries, hits, prompts and logs; explicit conflicts fail. |
| RET-04 — exact-term rescue | Requirement `C++`; supporting skill fact has exact token but deliberately poor fake semantic rank | Lexical hit contributes to hybrid selection and cites the correct fact. `C`, `C#` and `.NET` are distinct analyzer fixtures. |
| RET-05 — semantic rescue | Office-role requirement “coordinate appointments”; approved scheduling accomplishment has no exact query tokens | Controlled fake vectors select gold evidence through semantic retrieval. Real-model variant measures whether paraphrase retrieval works; fake success is not semantic-quality evidence. |
| RET-06 — German/English and aliases | Frozen German requirement and English evidence, umlauts/case, optional explicitly supplied alias map | Analyzer/prefix/vocabulary versions are recorded; no invented translation/proficiency. Cross-language real-model misses are reported. |
| RET-07 — multiple requirements | Technical and general office requirements, duplicate queries, deterministic equal-score candidates | Per-query trace and stable fusion order; duplicates do not inflate rank. Report which requirement gold evidence is absent at each stage. |
| RET-08 — parent context | Achievement → project → employment; gold child is the only direct hit | Complete permitted chain and C08 attribution survive; dates/skills remain attached to source facts. Unknown end stays unknown. |
| RET-09 — private parent / duplicate evidence | Allowed self-contained child with restricted optional parent; required-parent variant; equal text under two facts | Opaque reference plus warning without parent text; required-parent case fails. Distinct fact IDs survive; repeated chunks/ancestors do not multiply score. |
| RET-10 — budget stages | Small gold optional fact, oversized higher-ranked group, required parent, mandatory-only overflow | Whole-group omission recorded; later fitting evidence may be selected; mandatory context never trimmed. Distinguish retrieval success from packing loss. |
| RET-11 — empty versus failure | No query, empty permitted corpus, empty keyword hits, stale/missing/corrupt index and service timeout | Empty/no-query observations differ from failures. Semantic neighbors need not be relevant. No silent fallback and no skill-absence inference. |
| RET-12 — compatibility and invalidation | Same-dimension different digest, changed query prefix/analyzer/settings, corrected/removed fact and purpose withdrawal | Incompatible/stale results fail before success; no old citation relabeling, no mixed-generation keyword/vector reads. |
| RET-13 — determinism | Equal scores, reordered chunk delivery, matrix block boundaries, close/reopen in another process | Exact deterministic fake-vector IDs/order/fingerprints; variable call/timing metadata excluded from stable identities. |
| RET-14 — JSON delegation/overflow | Complete JSON fits, then one-token overflow; nonempty metrics and unknown dates | Delegated parity and correct error; no retrieval, shortening, RAG fallback or invented “Present.” |
| RET-15 — miss versus evidence gap | A: gold permitted skill falls outside pool/top-k. B: full permitted snapshot has no documented evidence. C: approved explicit negative statement. D: only restricted/ambiguous evidence | A is a labeled retrieval/selection miss; B is “not documented,” not “lacks”; C retains cited negation; D remains not assessable without disclosure. Runtime never reads gold labels. |
| RET-16 — hostile text/privacy | Job/chunk text containing SQL, shell-like instructions, delimiter strings and private sentinel exception text | All remain data; no commands/extra authority, prompt-policy change or raw diagnostic leakage. |
| RET-17 — C09 and payload accounting | Selected/mandatory/parent references, retrieved-but-excluded hits, output schema/template/reserve changes | C09 IDs equal included facts; complete version trace and measured payload binding; every material input change alters construction identity. Counter unknown/error cannot report fit. |
| RET-18 — Windows and real-check boundary | Paths with spaces/Unicode, another working directory, actual reader reopen, explicit local-model experiment | Native Windows results recorded separately from fake vectors; missing runtime/model/measurement gates yield pending prerequisite, never passed. |

## Verification recipe and unresolved decisions

Future implementation checks, **not commands executed by this planning task**:

```powershell
$repo = 'C:\Path To Checkout\Job Automation Prüfung'
$python = Join-Path $repo '.venv\Scripts\python.exe'
Set-Location -LiteralPath $repo
& $python --version
& $python -m job_automation.contracts.export_schemas
& $python -m pytest tests/context tests/contracts tests/profile tests/models
& $python -m pytest

Push-Location -LiteralPath $env:TEMP
try {
    & $python -m pytest (Join-Path $repo 'tests\context\test_selector_windows_paths.py') (Join-Path $repo 'tests\context\test_selector_windows_restart.py')
} finally {
    Pop-Location
}
```

Use test-owned temporary data roots. Verify interpreter readiness before the recipe; historical test runs do not establish the current environment. Freeze the manual real-check script arguments during S09 and document actual invocations then. No live service check or application test is necessary to validate this Markdown-only planning change.

| Decision | Owner and gate |
|---|---|
| D01 — V2 selector, result envelope, C09 revision and compatibility | S01 with FND-01/CONTEXT-01; explicit schema/reader/consumer plan before S02, including richer fields already present under `1.0` |
| D02 — JSON fidelity, unknown chronology, authoritative job binding, rule-version enforcement, complete payload fingerprint and return binding | CONTEXT-01 with PROFILE-01/LLM-01; regression evidence before S02/S05 actual parity acceptance |
| D03 — Exact index reader/manifests and optional versus required parent policy | CONTEXT-02/03 with S01/S04; implemented handoffs and source-mapping/permission tests before actual retrieval integration |
| D04 — Model/digest/space, query prefixes, numeric tolerances and no-truncation guarantee | MODEL-01/02, LLM-01 and CONTEXT-03; verified immutable identity and measured limits before real query scoring |
| D05 — Token counter/runtime template, estimate calibration, whole-prompt breakdown and reserves | CONTEXT-01/MODEL-02/LLM-01; same frozen payload and documented overhead before production fit claims |
| D06 — Query recipe, pools, top-k, fusion/ties, aliases and semantic cutoff | CONTEXT-04 S03/S04/S07/S09 with EVAL-01; provisional table until labeled measurements justify a recommendation |
| D07 — Current/frozen authorization and mid-read revocation | PROFILE-01/CONTEXT-03/RUN-01/GEN-02; exact token/pin policy and finalization checks; unsupported frozen use fails closed |
| D08 — Finite query/block/time/resource limits and quality acceptance cases | CONTEXT-04 with MODEL-02/EVAL-01; freeze labeled cases before tuning, record measured limits and failed cases; no invented aggregate quality threshold |

## Completion and handoff checklist

- Report all nine story statuses, actual files changed and dependency/handoff versions; distinguish proposed interfaces from delivered ones.
- Publish exact shared selector/request/result and C09 versions, legacy migration, error/warning codes and immutable model-payload binding.
- Demonstrate full JSON delegation, no silent fallback, identical purpose/approval/mandatory rules, source fidelity and parent privacy for both strategies.
- Record selected versus retrieved fact/chunk IDs, mandatory/ancestor reasons, query/index/embedding/settings identities, stable fingerprints and complete budget accounting.
- Demonstrate mandatory bypass and visible overflow, guarded current/frozen reads, invalidation and failure-versus-empty distinctions.
- Publish labeled fixture versions, per-case/channel/fused/packed coverage, retrieval-versus-selection misses, no-documented-evidence semantics and known limitations. Do not equate retrieval scores with skill possession.
- Separate unit/contracts, fake ports/vectors, actual local integration, native Windows and real-model results. Missing prerequisites remain pending; only demonstrated component acceptance earns `VERIFIED`.
- Hand off coverage/trace to MATCH-02 and EVAL-01, payload/budget semantics to LLM-01/GEN-02, and input authorization/retry/persistence obligations to RUN-01/GEN-02. Leave final-model evidence use, JSON/RAG assessment comparison, Salesforce and scheduling with their owners.

Planning result: **nine ordered stories, all PLANNED**. This task creates only `docs/stories/CONTEXT-04.md`; it implements no application code, schemas, configuration, fixtures, tests or component handoffs and claims no retrieval-quality measurements.
