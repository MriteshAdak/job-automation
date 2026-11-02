# MATCH-02 — LLM relevance assessment

Status: **PLANNED** · Planning date: **29 October 2026** · Phase 0 · Scope: **MATCH-02 only**

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially §§4–6 and 8–10. Direct requirements: **R05, R06, R07**. Supporting constraints: **R01, R09, R13, R14, R15, R16**. Every story describes future implementation. This planning task changes only this file.

## Objective and boundaries

Combine deterministic outcomes, the exact job revision and permitted candidate context into a validated C11 Assessment with typed citations, cited matches and gaps, explicit unknowns, and reproducible input/model versions. Prepare source-backed requirement inputs before context selection. Preserve deterministic rejection authority and leave unsuccessful model work pending and inspectable.

MATCH-02 owns requirement interpretation, assessment prompts and model-output schemas, domain evidence validation, C11 composition, and its callable assessment boundary. CONTEXT-04 owns deterministic retrieval-query construction, retrieval and strategy dispatch; CONTEXT-01 owns full JSON construction. LLM-01 owns local transport, inference serialization, strict parsing, bounded transport retries and call audit. MATCH-01 retains hard-rule evaluation and missing-information policy interpretation. Do not create alternate implementations of those components.

RUN-01 owns durable stage/retry orchestration and selection of one authoritative result per job/input version. DATA-01 and SYNC-01 own persistence and atomic assessment/outbox publication. EVAL-01 owns comparison runs and measured matching quality. MODEL-01/02 own runtime/model setup and measured configurations. Salesforce changes, document generation, scheduling, automatic applications and new external services are outside scope.

## Instructions, handoffs and current code

Read [README](../../README.md) and [schema instructions](../../schemas/README.md) alongside the blueprint. No applicable ancestor or repository `AGENTS.md`, including under `docs/` or `docs/stories/`, was found; the user-level `.codex/AGENTS.md` is empty. Generate schemas from typed models rather than editing generated JSON. Use synthetic fixtures and configurable local runtime paths. Documentation paths use `/`; runnable commands use native PowerShell paths. The observations below are static inspection, not tests executed by this planning task.

| Source | Observed baseline and implementation consequence |
|---|---|
| [MATCH-01 handoff](../components/MATCH-01.md), [service](../../src/job_automation/assessment/service.py), [composition](../../src/job_automation/assessment/composition.py) | Handoff records VERIFIED deterministic matching. Use `AssessmentService.evaluate_posting` or `evaluate_deterministic` with complete bound inputs. Preserve the full deterministic assessment, not just its rule list: eligibility/exclusion rejection can exist outside `rule_outcomes`. Do not use `DeterministicRuleEvaluator`'s synthetic posting/profile fallback for production MATCH-02. |
| [Detailed rule models](../../src/job_automation/assessment/models.py), [hard rules](../../src/job_automation/assessment/hard_rules.py) | `CriterionEvaluation` distinguishes factual unknown, waiver and policy rejection, but `to_rule_outcome` collapses these to pass/fail. Composition also drops typed eligibility/exclusion details. A narrow upstream handoff must expose these distinctions; parsing reason strings is not a reliable contract. |
| [C11](../../src/job_automation/contracts/assessment.py), [C08](../../src/job_automation/contracts/evidence.py) | C11 has one optional reference per rule, free-text gap/unknown lists, and no typed requirement findings or issue list. Metadata has model name, prompt version, strategy and optional bundle reference only. The validator prevents fail→eligible but still allows fail→review. C08 validates shape, not fact existence, permissions, source content or meaning. Plan explicit contract evolution first. |
| [Assessment evidence helpers](../../src/job_automation/assessment/evidence.py), [eligibility](../../src/job_automation/assessment/eligibility.py) | Existing helpers do not verify source quotations and may append an ellipsis to long quotations. Some callers synthesize structured-field display strings. MATCH-02 needs exact resolvers and an agreed structured-value representation; it must not bless these helpers as proof of valid C08. |
| Requested CONTEXT-04 handoff | `docs/components/CONTEXT-04.md` is absent. Read [CONTEXT-04 stories](CONTEXT-04.md) as a provisional interface/handoff plan, not completed acceptance. Actual shared selector/RAG integration is gated on its delivered handoff. Recheck before implementation. |
| [Current context service](../../src/job_automation/context/service.py), [records](../../src/job_automation/context/records.py), [C09](../../src/job_automation/contracts/context.py) | JSON service and richer C09 exist. CONTEXT-01/02/03 code and handoffs now exist, contrary to older availability statements in the CONTEXT-04 plan. That plan's proposed `ContextSelectionRequest`, `ContextSelectionResult`, `RequirementQuerySet` and frozen payload boundary are not current APIs. Coordinate them rather than implementing retrieval here. |
| [Job binding](../../src/job_automation/context/binding.py), [identity hashing](../../src/job_automation/identity/hashing.py), [assessment input binding](../../src/job_automation/assessment/inputs.py) | The default context binder compares a revision hash to the raw payload hash, while IDENTITY-01 hashes a normalized content projection. Assessment binding only requires a nonempty revision string. Require authoritative canonical/revision/C06 correspondence, including source identity; raw hash and normalized revision hash are distinct. Latest-by-source lookup is insufficient for an old revision. |
| [LLM-01 handoff](../components/LLM-01.md), [input resolver](../../src/job_automation/models/inputs.py), [schema registry](../../src/job_automation/models/schemas.py), [generation harness](../../src/job_automation/models/generation.py) | IMPLEMENTED, offline/conformance verified in its handoff; live model verification pending. Bind prompts by call ID and fingerprint, register domain proposal schemas and call `ModelProvider.generate`. The default `C11_assessment` registry entry is not a reason to trust model-authored IDs, rules or final dispositions. `validate_against_schema` uses ordinary Pydantic validation, so strict domain types need explicit tests rather than reliance on the handoff's no-coercion claim. |
| [C10](../../src/job_automation/contracts/models.py), [fingerprints](../../src/job_automation/models/fingerprints.py) | Model digest is nullable. The harness checks a pinned digest only when an observed digest is present. Generation fingerprint covers prompt/system text, not all settings or versions. Add a separate assessment input identity and require a verified model binding for completed results; never invent an observed digest. |
| [Public interfaces](../../src/job_automation/contracts/interfaces.py), [fake services](../../tests/fakes/fake_services.py) | `Assessor.assess(rule_outcomes, revision, context) -> Assessment` lacks complete policy/profile/job binding and a failure outcome. `ContextSelector` is also underspecified. Version the assessor boundary and migrate fakes/tests explicitly with the selector owner. |
| [Assessment repository](../../src/job_automation/storage/repositories/assessments.py), [consumer tests](../../tests/assessment/test_consumer_boundary.py), [model consumer tests](../../tests/models/test_consumer_boundary.py) | Repository stores C11 JSON and rejects duplicate IDs; latest-by-job is not authority by input version. Current tests demonstrate persistence and C12 compatibility, not final-result sequencing or durable MATCH-02 retries. Model consumer tests use a mock assessor. New tests must exercise the real MATCH-02 service. |

The MATCH-01 handoff suggests MATCH-02 constructs C09; the blueprint takes precedence: MATCH-02 calls CONTEXT-04, which constructs/delegates C09. The handoff's advert-language discussion does not authorize treating an advert's language as required candidate proficiency. Only explicit, cited requirements support that interpretation.

Missing upstream contracts block their real integration acceptance, not planning or clearly labeled fake tests. Do not implement whole prerequisites or declare them verified to remove a gate.

## Contract decisions to freeze before business logic

Names and versions below are proposed engineering choices. S01 must publish the final names, serialized schema versions and compatibility plan. They are not APIs already implemented or new confirmed user preferences.

| Record/boundary | Required inputs and outputs |
|---|---|
| `AssessmentRequest` | Execution UUID; canonical job/C07 and exact C06; approved C01/candidate identity; effective C02; complete rules C11 plus typed deterministic decision trace and evaluator version; purpose=`assessment`; selected strategy; inclusion/mandatory versions; model/configuration and prompt/schema versions; finite limits; assessment mode (`primary` or comparison). Deeply freeze collections/content. |
| `DeterministicDecisionTrace` | Original criterion IDs/results/evidence, factual outcomes, effective missing actions and sources, waivers, policy rejections, eligibility checks and exclusions. Identify confirmed failures separately from decisions caused by missing data. Bind to the same inputs and baseline C11. Obtain this through a narrow MATCH-01 handoff; do not infer it from prose or have the model reconstruct it. |
| `RequirementSet` | Exact job binding, extractor/schema/prompt versions and content fingerprint; stable requirement IDs; literal text, category and obligation (`required`, `preferred`, `unclear`); C08 job references; qualifiers, alternatives and explicit thresholds/units where supported; source/validation status and typed issues. Include extraction C10 references when inference was used. No candidate conclusions or dependency on final C11. |
| Context request/result | Adapt requirement inputs into CONTEXT-04's agreed request. CONTEXT-04 derives deterministic `RequirementQuerySet` before retrieval and returns C09, query identity, diagnostics and the exact measured model-facing payload/binding. JSON and RAG use identical approved snapshot, purpose, inclusion and mandatory rules. No second query builder here. |
| `AssessmentProposal` | Strict bounded model-owned output: one finding for every admitted requirement ID, cited candidate evidence and job evidence, match/gap/unknown status, reasons and optional finite score on the declared scale. No writable canonical/profile/policy identities, hard-rule outcomes or authoritative final disposition. Additional fields fail validation. |
| C11 extension | Typed `requirement_findings` and `validation_issues`; deterministic trace/reference; complete assessment input fingerprint and enriched model/context provenance. Preserve existing consumer fields. Free-text gaps, unknowns and summary are application projections of validated findings/trace, not a separate unchecked narrative. Rules-only records remain valid without model metadata. |
| `AssessmentRunResult` | Discriminated success or pending result. Success carries one validated C11, frozen input identity and audit references. Pending carries classified error/issues, failed stage, retryability, exact input identity and existing deterministic baseline; **no completed LLM C11**. Pending is execution state, not a new C11 disposition. Safe review projection remains a caller decision under the rules below. |

Use an explicit `AssessorV2.assess(request) -> AssessmentRunResult` boundary and a separate pre-retrieval preparation entry point as needed. The legacy assessor can adapt only with a complete explicit immutable binding; otherwise it reports unsupported input. Do not invent policy/profile versions to satisfy its old signature. Freeze interfaces with FND-01 and CONTEXT-04 before downstream stories.

C11 should carry typed findings directly, so citations survive JSON persistence and are not hidden only in logs. Prefer additive fields with legacy defaults and a recorded contract revision; `extra='forbid'` means old readers cannot automatically read new fields. Preserve old records for audit through version-aware readers, update exported schemas and fixtures, and coordinate consumers. Any incompatible change needs the blueprint decision and migration/consumer plan required by §8. Do not globally bump every unrelated contract or backfill invented provenance.

### Requirement preparation without a circular dependency

Execution order is:

`freeze/validate inputs → inspect deterministic baseline → prepare source-backed requirements → CONTEXT-04 query construction and context selection → assessment inference → evidence/domain validation → application-owned C11 composition`.

For ordinary confirmed deterministic rejects, return the rules assessment without model work. An explicit evaluation request may enrich it, but cannot change its rejection. A rules-only choice is explicit caller routing, never an implicit fallback after failed inference.

For requirements, first project allowlisted structured C06 fields and bounded title/description passages with exact source references. Passage queries can be prepared deterministically without asserting that every passage is a mandatory requirement. A separately configured local extraction call may interpret these passages before retrieval, using job data only, its own schema/prompt/budget and C10 operation (`requirement_extraction`). It must not depend on candidate retrieval or completed assessment. Extraction and assessment are distinct calls/stages with separate audit references and bounded work.

Validate extraction before promoting it to a requirement. Preserve negation, required/preferred wording, numerical units, alternatives such as “degree OR equivalent experience,” and role-specific duration. A title, technology mention, employer aspiration, policy alias or advert language alone does not establish a mandatory qualification. Query expansion from C02 remains a search hint, not a newly cited job requirement. Empty or incomplete extraction is visible, not proof that the job has no requirements. Unsupported interpretations stay in issues and cannot drive rejection or a complete eligible decision. No silently dropped oversized job text or requirements.

Optional inference mode is an explicit versioned configuration choice, not an automatic retry/fallback path. Deterministic passage input remains a supported route for testing and simple structured requirements. Freeze its rules and completeness limitations in S02. CONTEXT-04 continues to own terms, aliases, embeddings, query ordering and retrieval settings.

### Evidence and finding semantics

| Finding | Required meaning and evidence |
|---|---|
| `match` | C08 job requirement reference plus at least one C08 candidate reference to a permitted fact actually present in the supplied model context. Evidence must support the specific claim and qualifiers; similarity alone is insufficient. |
| `gap` | A cited requirement and explicit approved evidence supporting a limitation/contradiction, or a separately authorized, recorded complete-evidence review establishing a documented qualification shortfall. Do not label an undocumented skill as a proven lack of ability. Default model inference cannot certify exhaustive profile absence. |
| `unknown` | Ambiguous job requirement, no supporting evidence in supplied context, retrieval/packing omission, conflicting facts, incomplete dates/units or restricted/unavailable evidence. A job citation is required when a known requirement exists; no invented candidate reference for absence. |
| Extraction/reference issue | Typed code, stage, affected requirement/finding, safe source locator and severity. Distinguish `unsupported_requirement_extraction` from `invalid_evidence_reference`, missing required citations, incomplete requirement coverage and semantic concern. Retain invalid proposals for protected local inspection without accepting them as findings. |

Candidate references resolve exactly to `(candidate_id binding, profile_version, fact_id)` in the approved assessment-permitted snapshot and selected C09 facts. A fact that exists historically or was retrieved but omitted from the payload is not admissible model evidence. Validate fact/ID equality, mandatory references and purpose; preserve parent attribution and date precision. Do not fetch private provenance files or switch to older snapshots to repair a citation.

Job references resolve only against the frozen C06/C07 binding and an allowlisted field/path. Define nested-list paths and scalar serialization in S01/S04. Text offsets are zero-based, end-exclusive Unicode character offsets in the exact normalized field supplied to the model; byte offsets and raw-HTML offsets are different. Quotations must be nonempty exact substrings; spans must be in bounds; when both are present, their text must agree. Do not repair citations by fuzzy matching, ellipses, switching revisions or choosing a nearby sentence. Structured values use a documented canonical field rendering, not arbitrary fabricated prose.

Structured `explicit_eligibility` currently has no fact UUID. Preserve it and its profile/path provenance in the deterministic trace and C09 mandatory context. Do not invent a candidate C08 fact ID. New model-authored candidate claims must cite real C01 facts; if a shared eligibility reference type is required, resolve it explicitly with FND-01/PROFILE-01 before use.

Reference validity proves traceability, not semantic truth. Check mechanically detectable contradictions (changed numbers, negation, required/preferred flips, mismatched subject or dates). Keep ambiguous paraphrases visibly reviewable. Do not claim that a second model, valid IDs or a high score establishes entailment. Human-reviewed synthetic labels and later EVAL-01 measurements assess semantic quality.

### Disposition and failure precedence

| Condition | Required behavior |
|---|---|
| Confirmed deterministic hard failure, explicit exclusion or eligibility failure | Preserve original outcomes and rejection regardless of score, model recommendation or model outage. Model text cannot waive a hard rule. |
| Deterministic rejection from configured missing-information handling | Preserve the policy rejection and factual unknown separately. It is not a confirmed skill gap. Any later factual resolution requires an explicit deterministic reevaluation on versioned inputs, not an LLM overwrite. |
| Unresolved required unknown, unsupported extraction, semantic conflict or incomplete requirement coverage | Review; retain typed reasons and relevant source references. A high score cannot bypass the review condition. A hard failure still takes precedence. |
| Valid supported assessment without blocking unknowns/failures | Eligible when configured relevance conditions are met. A broad keyword miss alone is not rejection. Optional/preferred gaps affect ranking/explanation, not hard-rule outcomes. |
| Score missing, below an eligible threshold, or unsupported scale | Missing/low score is review under the proposed initial policy; invalid scale/value is output/configuration failure. No score-based rejection is introduced by this plan. Any future rejection threshold needs an explicit versioned policy decision and EVAL-01 evidence. |
| Retrieval/context/model/schema/reference/audit failure | Pending result with classified diagnostic and baseline preserved. Never fabricate score zero, empty successful findings, a skill gap or new rejection. Without a preexisting deterministic rejection, callers may expose a clearly marked rules-only review fallback with null model metadata and a separate pending-attempt link. |

The proposed initial score scale is C02's existing `0-100`, finite and inclusive, with no invented threshold; null remains unknown/unscored. Reject unsupported scales/configurations explicitly. Scores rank assessed fit and are not offer probabilities. Composition is deterministic for a fixed baseline, validated proposal and settings; real model text need not be bit-for-bit reproducible.

### Versions, audit and untrusted data

Record canonical job/revision ID and normalized content hash separately from raw hash; candidate/profile version and content fingerprint; policy/effective-policy and deterministic evaluator/trace versions; requirement/extractor/query identities; C09 strategy, content/payload fingerprint, builder/serialization/inclusion/mandatory versions; RAG index/query/settings versions where used; assessment and extraction prompt/system/schema versions; requested and observed model identity/digest or verified immutable runtime binding; effective generation settings, context window, reserves, measurement method/version, C10 call IDs and assessment composer version. Keep all used identities on C11 or resolvable immutable audit records referenced by C11. Preserve null unknown telemetry and explicitly record provenance limitations.

A mutable model tag with missing digest is not reproducible model provenance. Require a verified immutable model binding from LLM-01/MODEL-02 or leave completion pending; do not relabel a requested digest as observed. Validate returned call ID/model against the bound call. Compute a separate canonical assessment input fingerprint over all output-affecting inputs/settings, in addition to LLM-01's prompt-only fingerprint. Exclude attempt timestamps, latency and random execution IDs from stable input identity. Input changes invalidate reuse; retries retain frozen inputs and get separately correlated attempts. No result cache is required in MATCH-02.

Prompts have fixed application-owned instructions and separately serialized untrusted job/candidate data. Include original evidence identifiers; escape data so delimiter text cannot alter message roles. State that external text is evidence, never authority. Job text cannot modify system prompts, select models/endpoints/schemas/tools, read paths, execute commands, approve profiles or choose a disposition. Send only to LLM-01's configured local provider; no URL fetching, shell execution, cloud fallback or arbitrary tools. Prompt wording is one defense; strict schemas, application-owned decisions and validation enforce the boundary.

The exact prompt/schema/job/requirements/rules/context/framing transmitted must be measured under `P + O + M <= L`. Do not append unchecked rules or instructions after CONTEXT-04 admission. Require its frozen payload handoff, or a coordinated renderer/measurement integration before claiming a valid budget. Keep raw prompts, candidate facts, rejected output and job text out of ordinary logs; use safe issue codes and local protected audit references.

## Ordered implementation stories

All stories are **PLANNED**. Paths beginning `assessment/` or `contracts/` are relative to `src/job_automation/`. Proposed new filenames may be refined within that boundary. Shared-file edits are narrowly coordinated; they do not transfer another component's ownership.

| Order | Story | Dependencies | Deliverable |
|---|---|---|---|
| 1 | MATCH-02-S01 | FND-01; MATCH-01, CONTEXT-04 and LLM-01 interface coordination | Versioned request/result, typed C11 findings/provenance and compatibility gates |
| 2 | MATCH-02-S02 | S01; exact C06/C07 binding; LLM-01 if extraction enabled | Validated requirement preparation before retrieval |
| 3 | MATCH-02-S03 | S01–S02; CONTEXT-04 selector/payload contract | Frozen, purpose-consistent context selection and whole-input binding |
| 4 | MATCH-02-S04 | S01–S03; PROFILE-01 resolution; MATCH-01 trace | Typed reference resolution and finding/domain validation |
| 5 | MATCH-02-S05 | S01–S04; LLM-01 | Local assessment prompt, strict proposal inference and complete provenance |
| 6 | MATCH-02-S06 | S01–S05; effective C02 and complete deterministic baseline | C11 composition with hard-failure precedence and honest unknowns |
| 7 | MATCH-02-S07 | S01–S06; DATA-01/RUN-01/SYNC-01 consumer contracts | Pending/error behavior, retry identity and publication handoff |
| 8 | MATCH-02-S08 | S01–S07; actual upstream implementations for integration; MODEL-01/02 for live checks | Fake-model and local integration corpus, Windows checks and component handoff |

### MATCH-02-S01 — Freeze assessment contracts and prerequisite gates

**Objective/requirements.** Make all required authority, findings and versions representable before implementation. R05/R06/R07/R15/R16; C01/C02/C06–C11.

**Dependencies.** FND-01 and delivered MATCH-01/LLM-01; provisional CONTEXT-04 plan pending its actual handoff. DATA-01/SYNC-01/RUN-01 participate only in reader/result compatibility decisions.

**Inputs → outputs.** Current contracts and prerequisite handoffs → agreed request/result/proposal/requirement/issue records, extended C11 and metadata, typed deterministic trace contract, versioned assessor interface and explicit consumer migration plan.

**Owned files.** New `assessment/{llm_records,llm_ports,llm_settings}.py`; narrow `contracts/{assessment,interfaces,__init__,export_schemas}.py`; generated C11/auxiliary schemas, `schemas/README.md`, contract fixtures; `tests/assessment/test_llm_contracts.py`, affected `tests/contracts/` and `tests/fakes/fake_services.py`.

**Tasks.** Freeze the contract tables, required versus nullable provenance, finding states and cardinality, score scale, safe issue taxonomy and success/pending union. Separate model-owned proposal fields from application-owned C11. Request the minimal MATCH-01 trace export retaining missing-action and eligibility/exclusion detail. Resolve authoritative job binding and selector payload semantics with their owners. Document C11 reader behavior for legacy records and exact future persistence needs.

**Acceptance criteria.** A valid cited LLM C11 round-trips; a rules-only legacy fixture remains readable without fictitious LLM metadata. Missing typed evidence or required provenance cannot yield completed LLM success. A pending result cannot carry a completed LLM assessment. Incomplete legacy interface input fails visibly. Type coercion of score strings/booleans, duplicate requirement IDs, unknown enum values and extra model authority fields is rejected.

**Tests.** M02-01 and M02-11 below; generated-schema parity; explicit old/new reader fixtures; malformed success/pending variants; mutable-list changes after binding cannot alter a request. Tests assert behavior rather than merely restating field definitions.

**Migration/configuration and handoff.** Publish chosen contract/API/schema versions and prerequisite owners before S02. New configuration is versioned, non-secret and has no production model/threshold defaults. Any database change is a DATA-01 gate, not an implicit MATCH-02 migration.

### MATCH-02-S02 — Prepare traceable requirements before context selection

**Objective/requirements.** Produce queries' source inputs without a completed assessment and flag unsupported interpretation. R05/R06/R07/R15; C06/C07/C08/C10.

**Dependencies.** S01; authoritative revision binding; CONTEXT-04 requirement-input contract; LLM-01 only for explicitly enabled extraction mode.

**Inputs → outputs.** Frozen C06/C07, extraction configuration/schema and optional C02 search hints → versioned source-backed `RequirementSet`, query inputs and issues, or pending extraction/input failure. No candidate retrieval input is required to extract job requirements.

**Owned files.** `assessment/{requirements,requirement_validation,requirement_prompts}.py`; `tests/assessment/{test_requirement_preparation,test_requirement_extraction}.py`; synthetic `tests/fixtures/assessment/match02/requirements/`; MATCH-02 schema registration through the existing registry port.

**Tasks.** Implement the bounded deterministic structured/passage path and explicit local extraction path. Assign stable IDs from source binding/meaning-preserving content, preserve separate same-text requirements at distinct source locations when meaningful, and record versions. Validate job references before selector invocation. Retain original obligation, alternatives and units; flag hallucinated or unsupported interpretations. Carry labeled policy hints without promoting them to employer statements. Bound count/text/model work; distinguish empty source, no extracted requirements and extraction failure.

**Acceptance criteria.** A spy selector receives usable requirement inputs before any assessment call exists. Identical frozen input/configuration gives identical deterministic query-source identity. “German desirable” cannot become mandatory C1 German; “degree or equivalent experience” retains the alternative; a German advert alone yields no proficiency requirement. A valid quote that does not support the interpretation raises `unsupported_requirement_extraction`. Invalid quotation/span raises a reference issue. Incomplete extraction remains reviewable and cannot silently remove unmet requirements.

**Tests.** M02-02/M02-03/M02-09; scripted extraction success, fabricated years, negation/preference reversal, unrelated exact quotation, duplicates, empty text, input limit boundaries and extraction timeout/malformed output. Assert no retrieval/final assessment on fatal extraction failure and no candidate data in extraction prompts.

**Migration/configuration and handoff.** Freeze extractor mode/version, input bounds and extraction prompt/schema IDs separately from assessment and CONTEXT-04 query versions. No changes to retrieval internals or C06 inferred facts. Hand off source-backed requirements, issues and completeness status to S03/S04.

### MATCH-02-S03 — Bind one context strategy and the complete model input

**Objective/requirements.** Use the same approved evidence universe for JSON/RAG and prove the inference payload matches the selected context and budget. R06/R07/R15; C01/C02/C06–C10.

**Dependencies.** S01–S02; delivered CONTEXT-04 request/result and authoritative job-binding/payload handoffs. Real JSON/RAG acceptance waits for that dependency; fake ports permit contract tests.

**Inputs → outputs.** Bound request, requirements, deterministic trace and selected strategy → verified C09 plus frozen complete prompt material and input identity, or pending context/binding failure.

**Owned files.** `assessment/{context_bridge,llm_inputs}.py`; `tests/assessment/{test_llm_context_binding,test_llm_input_identity}.py`; `tests/fakes/assessment_context.py`.

**Tasks.** Invoke the shared selector with purpose=`assessment`, exact profile/job/policy and inclusion/mandatory versions. Validate returned profile/candidate/job/strategy, selected fact IDs and mandatory coverage. Propagate no-hit/omission/coverage diagnostics without interpreting them as candidate limitations. Supply rules, requirements, schema and instructions before whole-request measurement. Adapt the returned frozen payload into LLM-01 binding without semantic rerendering or double-counting omissions. Hash all output-affecting inputs/settings separately from the prompt-only fingerprint.

**Acceptance criteria.** JSON uses all permitted facts, RAG uses its declared selected facts, and neither changes the approved snapshot. A wrong-revision or wrong-purpose bundle fails before inference. JSON overflow does not switch to RAG. Mandatory eligibility/chronology are retained with unknown dates unchanged. A model citation cannot later refer to retrieved-but-not-rendered evidence. Changing only policy, model/settings, prompt/schema, query/index or inclusion version changes assessment identity.

**Tests.** M02-04/M02-05/M02-11/M02-12; selector spies, actual JSON delegation when its handoff is ready, empty retrieval and budget-omission fixtures, exact-budget and one-token-over fake counters, mutation after binding and same-version/different-content mismatch. Assert transmitted prompt equality with admitted payload.

**Migration/configuration and handoff.** No new context builder, retriever or automatic fallback. Record exact selector version and unresolved payload/measurement gates. Share the immutable payload and identity manifest with S05 and callers.

### MATCH-02-S04 — Resolve citations and validate requirement findings

**Objective/requirements.** Reject invalid references and prevent ungrounded findings from becoming assessment facts. R05/R06/R15; C01/C06/C08/C09/C11.

**Dependencies.** S01–S03; PROFILE-01 approved reference resolution and permission rules; MATCH-01 detailed trace and evidence representation decision.

**Inputs → outputs.** Requirement set, candidate/job evidence universe, C09 and extraction/assessment proposals → validated typed findings and safe issues, or pending validation failure. Application-derived unknowns fill explicitly incomplete coverage; never fill missing model evidence with fabricated matches/gaps.

**Owned files.** `assessment/{reference_validation,finding_validation}.py`; narrowly coordinated `assessment/evidence.py` changes only if the shared resolver convention is adopted; `tests/assessment/{test_llm_evidence,test_llm_findings}.py`; synthetic invalid-reference fixtures.

**Tasks.** Implement exact candidate and job resolvers, selected-fact membership, allowlisted nested paths and structured scalar rendering. Enforce one finding per requirement, no new IDs, both-side evidence for matches/confirmed gaps, and no candidate reference invented for unknowns. Validate qualifiers/numbers/negation where deterministically checkable; mark semantic uncertainty for review. Distinguish retrieved, selected, cited and validated-use sets. Invalid references are fatal to that proposal; semantic extraction concerns remain visible and prevent an unqualified eligible result.

**Acceptance criteria.** Wrong profile/revision, missing/private/unselected fact, invalid path, empty/fabricated quotation, out-of-bounds span and quote/span mismatch are flagged with distinct safe diagnostics. An existent unrelated fact is not automatically accepted as support. A no-hit RAG requirement remains unknown; a cited explicit negative statement can support a gap. A salary/year or candidate metric altered by the proposal is detected without changing source facts. Upstream invalid citations cause a dependency/validation issue rather than silent repair or loss of hard-failure authority.

**Tests.** M02-03–M02-06/M02-10; Unicode offsets, repeated quotations, structured lists/scalars, long exact quotes, wrong-version same UUID, private parent, unrelated-valid-reference semantic fixture, duration with incomplete/overlapping dates, missing/duplicate findings and explicit-negative versus silence cases.

**Migration/configuration and handoff.** Version path/serialization and validation rules. Keep C08 variants unchanged unless S01 explicitly coordinates an extension; profile eligibility path provenance is not a fake fact reference. Publish issue severity, invalid-proposal handling and limits of semantic validation.

### MATCH-02-S05 — Invoke the local model with bounded authority and provenance

**Objective/requirements.** Obtain a structured assessment proposal through LLM-01 with complete model/prompt/input metadata. R05/R07/R15/R16; C09/C10.

**Dependencies.** S01–S04; LLM-01 provider/input resolver/schema registry/audit; MODEL-01/02 only for real inference and immutable model/measurement evidence.

**Inputs → outputs.** Frozen admitted payload, context, requirement set and configured model → strict `AssessmentProposal`, C10 result/audit references and validation result, or pending model/output/provenance failure.

**Owned files.** `assessment/{llm_prompts,llm_inference,llm_provenance}.py`; `tests/assessment/{test_llm_prompt_boundary,test_llm_inference,test_llm_provenance}.py`; `tests/fakes/assessment_model.py`; synthetic model wire fixtures. Register schemas through LLM-01's existing API; do not add a direct HTTP client.

**Tasks.** Render fixed instructions with serialized untrusted evidence; use `BoundGenerationInput`/`InMemoryInputResolver` and `compute_generation_fingerprint`. Register a strict assessment proposal object schema instead of accepting model-authored C11 authority. Record extraction and assessment calls separately. Validate returned call/model identity, immutable model binding, actual settings and all required metadata before completion. Pass parsed results through S04. Reuse the shared provider's lock, retry cap and deadline; do not multiply attempts in a second local retry loop.

**Acceptance criteria.** Model output cannot change deterministic rules, IDs or policy. Tools, endpoint instructions and role delimiters inside job text remain data. Missing/wrong observed model provenance is visible and never invented. Boolean/string/out-of-range scores and extra fields fail. Parsing success with invalid evidence is still failure. The transmitted request fits the agreed whole-input budget; no automatic truncation or hosted fallback occurs.

**Tests.** M02-01/M02-07/M02-09/M02-11; actual `LocalModelProvider` with `ScriptedModelTransport`, recording resolver and fake clock. Test structured success, duplicate JSON keys, fences/prose, nonfinite numbers, truncated completion, unexpected model/call ID, nullable digest without binding, missing schema, injection sentinels and malformed-output retry cap. Inspect transport and audit records, not only final strings.

**Migration/configuration and handoff.** Version domain prompts, output schemas, settings and fingerprint algorithm. Pin no production model in this story plan. Upstream strict-validation/model-identity gaps remain LLM-01 gates if not enforceable through the supplied domain schemas/ports. Publish safe call/provenance diagnostics.

### MATCH-02-S06 — Compose validated C11 with deterministic precedence

**Objective/requirements.** Make application code authoritative for final disposition while retaining cited model findings and honest unknowns. R01/R05/R06/R07; C02/C08/C11.

**Dependencies.** S01–S05; complete deterministic trace and effective C02 missing-information/relevance settings.

**Inputs → outputs.** Baseline C11/trace, validated requirements/proposal, context and immutable provenance → one validated LLM C11 or pending domain failure. Explicit rules-only routing returns its original valid rules C11.

**Owned files.** `assessment/{llm_composition,llm_service}.py`; narrow exports in `assessment/__init__.py`; `tests/assessment/{test_llm_precedence,test_llm_unknowns,test_llm_scoring}.py`.

**Tasks.** Implement the disposition table. Preserve each deterministic rule's identity/result/reason/evidence and all rejection sources. Project typed findings into cited matches, gaps, unknowns and concise summary without unchecked free-text claims. Keep factual unknown separate from policy fail/waiver. Apply explicit score/threshold settings only after review/failure precedence. Carry extraction and context warnings into the result. Assign application execution identity and versions, then validate full C11 and metadata.

**Acceptance criteria.** Score 100 cannot change a confirmed fail to eligible or review. A deterministic exclusion/eligibility reject with no failing `rule_outcomes` remains rejected. Missing salary rejected by policy remains factual unknown with a policy reason, not “candidate lacks salary qualification.” Unknown required language is review despite a high score. Preferred-skill gaps and broad keyword misses do not become hard failures. Model-authored unknown→pass does not mutate a hard rule. Same validated inputs produce the same decision/findings/identity projection apart from documented execution metadata.

**Tests.** M02-06/M02-08/M02-10/M02-11; table-driven hard fail/pass/unknown × supported/gap/unknown × score boundaries; policy waiver versus missing-data rejection; altered/dropped rules; explicit-negative evidence; language-advert distinction; score `0`, `100`, null and out-of-scale values. Use real MATCH-01 evaluation for key baseline cases.

**Migration/configuration and handoff.** Preserve deterministic API behavior. Do not change C02 preference meanings or add an unmeasured rejection threshold. Publish exact disposition matrix, scale semantics and C11 consumer projection; no candidate-owned application status or availability changes.

### MATCH-02-S07 — Expose pending failures and a single-result consumer boundary

**Objective/requirements.** Keep failures recoverable and inspectable without falsely completing or rejecting assessment work. R07/R09/R15/R16; C10/C11 and C12 compatibility.

**Dependencies.** S01–S06; DATA-01/RUN-01/SYNC-01 result/checkpoint/publication contracts. Actual orchestration implementation remains with those owners.

**Inputs → outputs.** Success, classified error or validation issues from any stage → serializable success/pending envelope, protected audit references and caller handoff containing exact input identity, failed stage and retryability.

**Owned files.** `assessment/{llm_errors,llm_result}.py`, narrow `assessment/llm_service.py` wiring; `tests/assessment/{test_llm_failures,test_llm_consumer_boundary}.py`; fake caller/checkpoint ports under `tests/fakes/`. Coordinated C11 reader changes only if required by S01; no new scheduler/outbox implementation.

**Tasks.** Map context errors, service errors, schema/evidence failure, missing configuration, permission changes and audit exceptions to safe explicit pending states. Preserve original deterministic authority. Distinguish recoverable transient errors from operator-action/invalid-output cases; LLM-01 owns physical retries, RUN-01 owns durable retries. Define how callers persist the envelope and immutable references before considering work resumable. Return one chosen result per execution; intermediate rules/extraction/proposals cannot independently publish. Comparison results carry separate identity/mode and no publication authority.

**Acceptance criteria.** An outage on an otherwise plausible job leaves no completed LLM C11 and no rejection. Preexisting hard rejection survives outage. A review fallback is explicitly rules-only with null LLM metadata, unscored and linked to the pending attempt; it is not an LLM success. An audit/storage acknowledgement failure is visible. Retry with frozen inputs retains logical work identity; changed input needs new work. Returned data can be reopened and inspected without raw prompt logging. No call directly writes Salesforce or claims assessment/outbox atomicity from independent repository saves.

**Tests.** M02-07/M02-12/M02-13; transient exhaustion, missing model, context overflow, malformed/invalid evidence, permission revocation, audit recorder exception, failed checkpoint acknowledgement, serialization/reopen and changed-input retry. A recording fake caller proves intermediate/comparison results never become publishable final updates. Test C11 repository round-trip separately from downstream atomic transaction behavior.

**Migration/configuration and handoff.** Hand off pending record schema, retry categories, stable identity and authoritative-result rules to RUN-01/DATA-01. SYNC-01 atomically commits the chosen C11 with its C12 operation; any missing storage transaction support remains its explicit gate. Do not use `get_latest_assessment(job)` alone to select between strategies or revisions.

### MATCH-02-S08 — Verify fake-model behavior, integration and native Windows handoff

**Objective/requirements.** Demonstrate component acceptance with meaningful independent oracles and distinguish fake, actual local and live verification. R05/R06/R07/R13/R14/R15/R16.

**Dependencies.** S01–S07; actual MATCH-01/PROFILE-01/POLICY-01/IDENTITY-01/CONTEXT-04/LLM-01/DATA-01 for their integration cases. MODEL-01/02 gate real local inference, not offline testing.

**Inputs → outputs.** Synthetic labeled corpus, scripted model responses and actual component services → reproducible per-case results, regression report, known limitations and `docs/components/MATCH-02.md` implementation handoff.

**Owned files.** `tests/assessment/{test_llm_integration,test_llm_windows_paths,test_llm_windows_restart}.py`; `tests/fixtures/assessment/match02/README.md` and labeled fixtures; opt-in `tests/manual/match02_smoke.py`; future `docs/components/MATCH-02.md`. Narrow updates to existing affected contract/model/context tests only.

**Tasks.** Implement the catalog below with fixed synthetic IDs and independently authored expected requirements/evidence/outcomes. Test the real MATCH-02 entry point using both a scripted provider for domain failures and the actual local-provider harness over fake transport for wire failures. Exercise actual JSON selector and actual RAG selector/index when delivered, using controlled embeddings to make retrieval omission predictable. Verify persistence/reopen and changed versions. Add opt-in real local-model checks with explicit pending-prerequisite reporting. Report retrieved/selected/cited/validated-use coverage separately; hand measurements to EVAL-01 without building its comparison pipeline.

**Acceptance criteria.** Every safety, authority, citation and failure invariant in the catalog passes offline. Actual JSON/RAG integration uses the same approved snapshot and rules while retaining distinct context identities; deliberately missing RAG evidence becomes unknown. No skips count as passed integration. Native Windows paths with spaces/umlauts, another working directory and closed SQLite/file handles are tested. Live behavior records actual model/digest, prompts, settings, corpus, latency and failures; fake success is not a model-quality or hardware-fit claim.

**Tests.** M02-01 through M02-14; targeted regression for all changed shared consumers. Freeze real-model labeled acceptance cases before inspecting outputs; retain reviewer findings and unsupported-claim examples. Real model runs need no Salesforce writes or candidate data.

**Migration/configuration and handoff.** Record exact delivered versions, schema/reader migration outcomes, commands/results, gate status and next consumers RUN-01/SYNC-01/EVAL-01. Use IMPLEMENTED when required live/integration verification is pending; VERIFIED only for acceptance actually demonstrated with the scope clearly stated.

## Fake-model and integration test catalog

These are future test IDs and oracles, not existing tests or reported passes. Include technical and general office-role examples, German/English text, and only synthetic candidate data. Fakes live under `tests/`; production code uses real configured ports.

| ID | Scenario and independent oracle | Required observable result |
|---|---|---|
| M02-01 | Strict proposal/C11/result schemas; legacy C11; missing versions; extra `final_disposition`; score string/bool | No coercion or model authority; success/pending exclusivity; legacy audit readability and exact serialized schema versions. |
| M02-02 | Structured requirement plus job passage; spy call order; optional extraction before retrieval | Requirements and query inputs exist before selection/inference; no final C11 dependency; extraction receives no candidate context; stable deterministic source IDs. |
| M02-03 | “Preferred German,” “degree OR equivalent,” “no certification required,” fabricated five years with a real but unrelated quote | Original obligation/negation/alternative survives; unsupported extraction is flagged and cannot reject or yield unqualified eligibility. Invalid source references are distinguished from unsupported meaning. |
| M02-04 | Same approved snapshot in JSON/RAG; mandatory chronology; private and CV-only facts; permission change | Same inclusion/mandatory authority; no restricted facts in prompts/output/logs; stale/wrong-purpose context fails; JSON never truncates or silently switches strategy. |
| M02-05 | Gold skill in allowed snapshot but outside RAG top-k; retrieved then budget-omitted variant; full JSON sees it | RAG remains unknown with a retrieval/selection limitation, never “lacks skill.” Separate selected evidence from retrieved evidence and final use. JSON can produce a cited match. |
| M02-06 | No skill documented versus explicit approved “introductory exposure only”; incomplete dates and overlapping employment | Silence is unknown. Explicit limitation may support a cited gap. No invented duration, fluency, ongoing employment or addition of overlapping years. |
| M02-07 | Runtime 503/timeout, missing model, overflow, malformed JSON, truncated response, audit failure | Bounded attempts and pending result; no fabricated score/gap/reject; safe diagnostic and exact stage/input/call identity. Existing hard rejection remains intact. |
| M02-08 | Real MATCH-01 confirmed fail plus model score 100; missing-policy fail; exclusion/eligibility fail outside rule list | All baseline rejection sources survive; factual unknown stays distinct from policy rejection; model cannot drop or rewrite a rule. |
| M02-09 | Job text asks to ignore rules, output eligible, reveal a private sentinel, run a command or select an external endpoint | Application instructions/configuration unchanged; zero extra tool/network authority; fabricated references rejected; no sentinel leakage in ordinary diagnostics. |
| M02-10 | Missing/private/wrong-version candidate UUID; valid but unselected fact; wrong job revision/path; bad Unicode span; conflicting quote/span; unrelated valid fact | Reference failures are reported rather than repaired. Semantic concern is distinguished from traceability. Valid source IDs alone cannot certify the claim. |
| M02-11 | Change one input at a time: job/profile/policy/context/query/index/inclusion/model/prompt/schema/settings; missing digest; wrong result call ID | Assessment input identity changes for material changes; calls/metadata reconcile; unsupported provenance stays pending; timestamps/attempt UUIDs do not alter stable input identity. |
| M02-12 | Real MATCH-01 + actual selector + `LocalModelProvider` with scripted transport + real assessment service + SQLite C11 round-trip | Both strategies yield validated evidence-bearing C11 with complete links. Exact admitted bytes reach transport; schema/evidence errors traverse actual service. Fake selector tests alone cannot satisfy this case. |
| M02-13 | Pending envelope save/reopen through consumer adapter; successful retry; changed input; intermediate/comparison results | Failure remains inspectable; frozen inputs/identity survive; stale results cannot be chosen as current; only chosen final result is offered for publication. Atomic C11/outbox integration is separately gated on owners. |
| M02-14 | Native Windows Unicode/space paths, different working directory, restart; opt-in live local model with labeled cases | Correct path handling/handle release and evidence/version round-trip. Report unit, fake transport, actual local integration, Windows and live results separately; unavailable prerequisites are pending, not passed. |

## Future verification and completion checklist

The following commands are implementation-time checks, **not executed by this Markdown planning task**. Use test-owned temporary roots and an explicitly resolved repository/interpreter. Do not install a model or contact services just to validate this plan.

```powershell
$repo = 'C:\Path To Checkout\Job Automation Prüfung'
$python = Join-Path $repo '.venv\Scripts\python.exe'
Set-Location -LiteralPath $repo
& $python --version
& $python -m job_automation.contracts.export_schemas
& $python -m pytest tests\assessment tests\contracts tests\models tests\context
& $python -m pytest tests\policy tests\profile tests\identity tests\storage

Push-Location -LiteralPath $env:TEMP
try {
    & $python -m pytest (Join-Path $repo 'tests\assessment\test_llm_windows_paths.py') (Join-Path $repo 'tests\assessment\test_llm_windows_restart.py')
} finally {
    Pop-Location
}
```

Run the full suite if the shared-contract migration affects consumers beyond the targeted checks. S08 defines the opt-in smoke command once its configuration interface exists. No claimed native Windows or live inference result can be inferred from the repository's historical handoff test totals.

- Record all eight story statuses, owned files, requirement coverage, actual dependency/handoff versions and unresolved gates.
- Publish final request/result, requirements/proposal, typed C11 findings and metadata contracts; generated schemas, backward-reader behavior and any coordinated migration decisions.
- Demonstrate pre-retrieval requirement derivation, independent CONTEXT-04 query construction, exact source binding, both context strategies and complete prompt measurement.
- Demonstrate typed two-sided citations, invalid-reference detection, unsupported extraction flags, unknown/gap distinction and preserved hard/policy failures.
- Record model/prompt/context/profile/policy/job versions and call/input identity, including extraction and assessment separately; never fabricate unknown provenance.
- Demonstrate that job text has no instruction/tool authority and that sensitive content stays out of ordinary logs.
- Record bounded model failures as pending/reviewable, preserve existing deterministic rejection, and hand durable retry/publication sequencing to the correct owners.
- Separate fake-model, fake-transport, actual local integration, native Windows and real local-model results. Explicitly record the absent CONTEXT-04 handoff and any continuing integration gate until delivered.
- Hand off to RUN-01, SYNC-01 and EVAL-01 without claiming end-to-end Salesforce operation, tuned thresholds, model quality, or Phase 0 completion.

Planning result: **eight ordered stories, all PLANNED**. No application code, schemas, configuration, fixtures, tests or implementation handoffs are created by this planning task.
