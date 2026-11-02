# GEN-03 — Draft content generation implementation stories

Status: **IMPLEMENTED with a conservative source-extractive recipe; verification and limitations are recorded in [the GEN-03 handoff](../components/GEN-03.md)**  
Date: 29 October 2026  
Component: **GEN-03 only**, Phase 1  
Direct requirements: **R11, R15**; supporting constraints: R06, R07, R10, R12, R13, R14, R16  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), especially §§4–9 and G4  
Repository instructions: [README.md](../../README.md) and blueprint §§8–9. No applicable `AGENTS.md` was found in the repository or checked ancestor directories.

## Objective and scope

Generate a structured C14 CV or, when explicitly requested, a cover-letter draft using the exact inputs sealed by GEN-02, the requested language/template options, and LLM-01 local inference. Every candidate factual claim must cite an approved, purpose-permitted candidate fact through C08. Every job/employer factual claim must cite the frozen posting through C08. Subjective passages, uncertainty, source limitations and paraphrases remain identifiable for later human review.

GEN-03 owns drafting recipes, prompt versions, model-output proposals, conversion into structured C14 content, immediate grounding/admission checks, and durable content results. Minimal shared-contract, persistence and GEN-01 adapter changes needed to make that boundary usable belong here. The service must also work without a Salesforce connection or running polling worker.

Excluded: DOCX/PDF creation, page layout, fonts, renderer installation, artifact/file delivery, Salesforce mutations or notifications, approval actions/states, automatic applications and Phase 2 automation. GEN-04 owns the full factual/document validation report and later validation gate; GEN-05 owns layout templates/rendering/artifact versions; GEN-06 owns delivery and review integration. GEN-03 must not emit a ready-for-review processing transition merely because content was generated. Refusing invalid references at generation admission does not implement or replace GEN-04.

## Current repository evidence and dependencies

The blueprint's original planning-only status is historical. Current code and recorded handoffs determine the actual starting point. Paths below are relative to `src/job_automation/` unless otherwise stated.

| Dependency / inspected evidence | Current behavior and consequence |
|---|---|
| **GEN-02**, direct prerequisite | **No `docs/components/GEN-02.md` exists.** [GEN-02 stories](GEN-02.md) are PLANNED. `generation/ports.py` defines `GenerationInputService`, but there is no concrete freezer/context service. Treat the planned seal, `FrozenContextRecipe`, context receipt and complete-context accessor as required integration contracts, not implemented guarantees. Use explicit test fakes until the real handoff exists. |
| **LLM-01**, direct prerequisite | [LLM-01 handoff](../components/LLM-01.md) records offline and native-Windows checks, with live MODEL-01 verification pending. `models/provider.py`, `generation.py`, `inputs.py`, `fingerprints.py`, `schemas.py` provide local structured inference, immutable binding, budgeting, retries and audit ports. Do not add another HTTP/model client. |
| C14 v1.0, `contracts/artifacts.py` | `DraftDocument` has a flat claim list, subjective sections, four frozen version labels and optional model-call ref. It lacks an ordered factual-section model, requested language, complete recipe/context provenance and structured uncertainty. `requires_human_review` defaults to true but accepts false. Candidate name, role and employer strings have no citations. These are contract gaps to resolve first. |
| C08 v1.0, `contracts/evidence.py` | Discriminated candidate/job references exist. Candidate references contain profile version/fact UUID; job references contain revision, field path and quotation and/or Unicode span. Shape validation alone does not establish approval, request binding, valid source text or truthful paraphrasing. |
| C01 v1.0, `contracts/profile.py` | Facts contain claims, skills, metrics, parent links, precision dates and `allowed_uses`. There is no dedicated candidate-name/contact field. Explicit eligibility also has no fact ID of its own. Do not invent identity data or manufacture fact IDs to satisfy C14. |
| C13 v1.0, `contracts/generation.py` | One request chooses `cv` or `cover_letter`, language, template and context strategy. Freeze version labels alone are insufficient to authorize generation. A cover letter is a separately requested output, not an automatic CV side effect. |
| **CONTEXT-01–04**, through GEN-02 | `context/selector_records.py` returns C09 plus `RenderedPrompt`, trace and construction fingerprint. C09 alone cannot reconstruct the complete measured prompt. GEN-03 supplies recipes before freezing and consumes the saved result afterwards; it does not retrieve new facts or rerun the selector. |
| **GEN-01**, consumer | [GEN-01 handoff](../components/GEN-01.md), `contracts/interfaces.py` and `generation/coordinator.py` expose `Generator.generate_draft(request, context) -> (DraftDocument?, ClassifiedError?)`. The coordinator stores `draft_json` after generation, reopens it without checking input/content hashes, and uses `document_version` as output ref. A crash after inference but before checkpoint can repeat inference. Plan narrow receipt/reopen integration, not a worker redesign. |
| LLM schema registry, current code | `build_default_schema_registry()` already registers `C14_draft_document` and `C14_artifact` v1.0, beyond the older handoff's guidance. Register a content-only proposal schema with a real validating model; never select the artifact schema for drafting. Registry entries can be replaced under the same ID, so check pinned schema digest/version explicitly. |
| C10 fingerprint/provenance | `compute_generation_fingerprint` hashes prompt/system text, not the entire generation recipe. The harness rejects a differing observed digest when both digests exist, but permits a missing observed digest. GEN-03 needs a separate recipe fingerprint and explicit model-identity verification policy; a mutable tag alone is not evidence of frozen weights. |
| Existing evidence helpers | `assessment/reference_validation.py` illustrates exact job-span checks and admitted-fact checks, but candidate permission is hardcoded to `assessment` and some error messages include source text. Do not reuse unchanged for CV/cover-letter permissions or safe diagnostics. |
| **DATA-01 / OPS-01**, supporting integration | SQLite/repositories and retention machinery exist. `storage/repositories/artifacts.py` stores physical artifacts, not draft content. Current migration head is 010; allocate the next unused migration after any GEN-02 migration during implementation. |
| **MODEL-01/02 / EVAL-01** | Runtime installation, chosen model/digest, drafting budgets/quality benchmarks and broader JSON/RAG evaluation remain their owners' work. Prior handoff test counts are historical evidence, not tests run by this planning task. |

GEN-03 can be developed against synthetic sealed inputs and scripted LLM-01 transport. Integration acceptance must remain pending until real GEN-02 supplies verified bodies, permissions, prompt bytes and durable receipts. Do not implement GEN-02 inside GEN-03 to hide that dependency.

## Requirements and proposed technical decisions

Confirmed scope is structured CV/optional cover-letter generation, frozen inputs/options, typed grounding, local inference, untrusted-job isolation and preserved human review. The following implementation choices are proposals:

1. **Use a content-only model proposal.** The model proposes sections, atomic claims and subjective text. Application code supplies request IDs, versions, source-derived protected values, hashes, provenance and review requirements. Model output never controls paths, schemas, model selection, tools, approval or worker state.
2. **Version the richer C14 content explicitly.** Introduce `DraftDocumentV2` (schema 2.0) alongside the existing v1.0 reader/schema, rather than silently changing required fields or meanings. New generation uses v2. The physical `Artifact` contract is unchanged. S01 must document the blueprint contract decision and consumer migration before business logic.
3. **One saved draft per sealed request/recipe.** Retries reopen committed content. A deliberate regeneration uses a new C13 request. Failed physical inference attempts remain separately attributable; model output is not promised to be bitwise deterministic before a successful commit.
4. **Separate source data from generated phrasing.** Copy protected dates, original titles, organization names, skill labels and verified metrics from approved facts or frozen posting fields. Allow translations/paraphrases as separately reviewable text with source links; do not replace original values or increase certainty.
5. **Fail closed on incomplete provenance.** Missing seal/context bodies, incompatible recipe implementations or unavailable pinned model identity produce visible errors. Never fetch latest profile/posting data, switch JSON/RAG, select another model/template/language or turn a job requirement into candidate evidence.
6. **No open-ended repair loop.** Reuse LLM-01's bounded malformed-output handling (default zero regenerations, at most its supported one). Domain-grounding failures are inspectable errors. Do not silently drop failed claims, fabricate citations, ask a model to approve facts or use unbounded retries to obtain passing output.

## Contracts to establish before business logic

All proposed records use explicit schema versions, strict boundaries and detached reads. Exact filenames can be refined within GEN-03. Keep C01/C08/C09/C10/C13 semantics intact.

| Contract / interface | Required contents and invariants |
|---|---|
| `DraftRecipe` v1.0 | Document type, supported language, template ID/version/content-spec digest, prompt/system/framing versions and bytes/digests, proposal schema ID/version/digest, model identifier/verified digest, effective generation settings, context/output/safety limits, measurement policy and content limits. Canonical recipe hash includes all semantic inputs. Supply this to GEN-02 before sealing; no late prompt additions. |
| `DraftInputBinding` v1.0 | Request/candidate IDs; seal ID/hash; full frozen C01 and C06 access; exact revision UUID/material hash; frozen options and purpose; context receipt ID/hash, complete selection result, selected fact IDs, recipe identity and warnings. Verify all redundant bindings. This is a view of GEN-02-owned resources, not a second freezer. |
| `DraftContentProposal` v1.0 | Ordered sections/entries; unique local IDs; atomic claims classified as candidate or job; typed C08 references; subjectively worded blocks; proposed uncertainty linked to section/claim IDs. No persisted identities, approval/delivery fields, executable markup, tool arguments or arbitrary paths. Strict schema, bounded text/count/depth and no extra fields. |
| `DraftDocumentV2` / C14 content | Application-assigned draft UUID and document version; request ID/type; requested language/template identity; ordered sections/entries and claim links; canonical claim collection; subjective blocks; source-backed structured values; typed review issues; frozen-input labels plus seal/context/recipe hashes; prompt/schema/model-call provenance. No artifact paths, remote IDs or approval operation. |
| Atomic claim and section model | Each claim has unique ID, explicit `claim_subject=candidate|job`, nonempty text and one matching typed C08 reference. Split compound candidate/employer assertions into separate claims; a sentence/paragraph may link multiple atomic claims. Each factual passage or structured field has a claim/source binding; headings must not introduce untracked factual assertions. Section order and references must be coherent, without duplicate/dangling IDs. |
| Structured values | Preserve original source value, source field, typed C08 and date precision/null state for identity/role/organization/dates/skills/metrics where available. Separate optional translated display text. Missing candidate name/contact data stays null/omitted with a targeted issue, or fails an explicitly required template content rule. Never use account names, filenames, job text or synthetic placeholders as real identity. |
| `DraftReviewIssue` v1.0 | Stable issue code, safe message, severity, affected section/claim/source refs and uncertainty kind (for example source unknown, missing context, translation or semantic paraphrase). Subjective content has `requires_human_review: Literal[True]`. Preserve upstream warnings and source uncertainty even if the model omits them. These are generation issues, not a GEN-04 validation report. |
| `DraftGenerationReceipt` v1.0 | Stable logical result key, immutable C14 payload/hash or classified failure, binding/recipe hashes, call/result/audit refs, effective settings, UTC attempt times, usage/latency where available, selected versus actually cited fact IDs, and validation-stage status still pending. Exactly one usable draft or error in the service result. Keep nullable observed metrics/digests honest. |
| Service and adapter | Proposed `generate_content(binding_ref) -> DraftGenerationResult` and `reopen_draft(receipt_id) -> DraftGenerationResult`. Add a versioned Generator interface returning v2 and minimally update GEN-01's draft/validation port annotations and schema dispatch. Keep legacy v1 reading for existing checkpoints; never silently downcast and discard sections/provenance. The adapter resolves the request-owned GEN-02 receipt and compares caller C09/options, rather than trusting them as authority. |

Candidate claims require the frozen candidate identity, exact profile version, an approved fact, permission for `cv` or `cover_letter` at freeze, and membership in the admitted C09 evidence set. A fact merely present elsewhere in C01 or retrieved but excluded from the prompt is not usable model evidence. Explicit eligibility values without approved fact-level C08 mapping can constrain drafting but cannot become uncited candidate assertions. Coordinate missing fact representation with PROFILE-01; do not mint evidence in GEN-03.

Job references resolve only against the sealed C06 and its declared revision binding. Use a documented allowlist of text fields (initially `description_clean`, `title`, `company_name_hint`); additional paths need explicit typed resolution. No attribute traversal, file lookup or URL fetching. Quotations must be nonempty exact substrings; spans use zero-based Unicode code points with exclusive end, remain in bounds, and agree with quotations when both are supplied. Preserve original-language quotations even when the generated document is translated. Never confuse the raw-payload hash with the material posting-revision hash.

The v2 migration must retain v1 fixtures/readers and reject unsupported versions. Existing v1 drafts stay inspectable as legacy, with missing provenance recorded; do not manufacture new hashes/citations or treat them as verified v2 drafts. Update schema exports, tests and the minimal GEN-01/GEN-04 boundary together. Unknown future consumers must refuse unsupported content versions rather than discard fields.

## Implementation stories

### GEN-03-S01 — Establish versioned content and consumer contracts

**Objective:** Define usable structured content and a review-safe migration before prompts or model calls.  
**Requirements:** R11/R15; supporting R10/R12/R16.  
**Dependencies:** FND-01, current C08–C14, GEN-02 planned receipt contract, GEN-01 interface.  
**Owned modules:** proposed `generation/draft_records.py`, `draft_ports.py`; narrowly scoped `contracts/artifacts.py`, `contracts/interfaces.py`, schema exports/fixtures and consumer annotations.  
**Inputs → outputs:** existing contracts and frozen-input obligations → versioned proposal, C14 v2, receipt and adapter contracts.

Tasks:

- Implement the contract table, source-kind/claim-subject agreement, unique IDs, ordering, section links and literal review requirements. Keep factual metadata subject to the same citation rules as prose.
- Make candidate name/unknown employer handling explicit without inventing profile fields. Define missing-required-content errors versus optional omissions; template requirements cannot compel fabrication.
- Retain legacy parsing and add explicit version dispatch. Document the incompatible C14 decision, GEN-01 adapter changes and GEN-04 input expectations in the blueprint/handoff during implementation.
- Register strict proposal/C14 schemas with versioned IDs and pinned hashes. Reject registry entries without a validating model. Preserve Artifact v1 and unrelated schemas.

Acceptance: a CV with ordered employment entries, evidence-bearing dates/bullets and subjective summary round-trips without loss. A letter paragraph can contain separately cited candidate/job clauses. False review flags, wrong reference kinds, duplicate IDs and dangling links fail. A v1 fixture remains readable, without being promoted to v2.

Tests: proposed `tests/generation/content/test_contracts.py`, `test_schema_compatibility.py`; affected contract/interface/schema-export tests. Configuration/migration impact: new versioned schemas; no artifact or approval-state migration.

### GEN-03-S02 — Bind exclusively to sealed inputs and requested options

**Objective:** Authorize drafting from the exact GEN-02 result and expose a standalone service boundary.  
**Requirements:** R11/R15; supporting R06/R10/R16.  
**Dependencies:** S01, GEN-02 seal/reopen/context-access contracts, PROFILE-01 inclusion semantics.  
**Owned modules:** proposed `generation/draft_inputs.py`, `draft_service.py`, `draft_settings.py`.  
**Inputs → outputs:** request/receipt reference → verified `DraftInputBinding` or classified error, before any generation call.

Tasks:

- Reopen and verify the durable seal and complete context receipt. Match request/candidate/job/revision/purpose/language/template/strategy and all relevant hashes. Reject caller mutations and cross-request receipt reuse.
- Read neither latest profile/job records nor active index pointers. Use frozen inclusion authorization; later profile corrections do not silently change an existing request. Cancellation, if supported by its owner, stops work without replacing input data.
- Carry through availability/override, retrieval, budget and source-uncertainty warnings. Do not rerun availability or suitability scoring, invent overrides or modify application progress.
- Require an explicitly requested document type. An absent cover-letter request produces no letter; requesting one requires neither a prior generated CV nor permission to reuse its claims as evidence.
- Expose recipe resolution to GEN-02 independently of executing a draft, avoiding a dependency cycle between freezing and generation.

Acceptance: P1/J1/recipe A produce the same input binding after P2/J2/template B become current. Wrong purpose, changed language, missing measured prompt or corrupt seal fails before model invocation. JSON and RAG remain distinct; neither silently substitutes for the other.

Tests: `test_frozen_binding.py`, `test_options.py`, `test_no_mutable_reads.py`; use spies that fail on latest reads and fixtures for CV-only/letter-only permissions. Configuration impact: validated recipe/catalog reference, read at sealing only; no new profile selection, availability policy or global unavailable override.

### GEN-03-S03 — Version CV and cover-letter prompts with complete budgeting

**Objective:** Tailor evidence-backed content in the requested language within the frozen content specification.  
**Requirements:** R11/R15; supporting R06/R07/R14.  
**Dependencies:** S01–S02, GEN-02 recipe freezing, CONTEXT-04 prompt/measurement contract, LLM-01 input binding.  
**Owned modules:** proposed `generation/draft_prompts.py`, versioned prompt resources and content-spec fixtures; no layout-template files.  
**Inputs → outputs:** supported type/language/template content spec → immutable prompt/schema recipe used in the measured context.

Tasks:

- Provide distinct versioned CV and cover-letter instructions, initially supporting requested `de` and `en`. CV content groups source-backed chronology, education, experience and skills as supported; letters group salutation/opening, candidate evidence, job-specific connection and subjective motivation/closing. Missing optional material stays omitted or marked, never padded with inventions.
- Separate template ID/version from prompt version. Consume only a frozen template content specification (section IDs/order, required/optional fields and bounded length hints) supplied by configuration/GEN-05's boundary. Unsupported templates/languages fail clearly; layout design and language defaults remain GEN-05 ownership.
- Instruct the model to preserve attribution, dates/precision, titles, metric units and uncertainty. Requested German output does not establish German proficiency. Employer marketing statements remain attributed to the posting, not verified external employer facts.
- Serialize candidate data and job text in separate untrusted data blocks, escaping delimiter-like input. External text cannot change instructions, schema, options, facts or tools. No shell/browser/file/network capability is exposed to the model; URLs in data are citations only.
- Freeze all instructions, schema text, formatting and language/template constraints before GEN-02 measures context. Bind the exact saved `RenderedPrompt.full_prompt` to LLM-01; proposed initial transport uses no additional system text. Any later framing change requires a new recipe and matching measured receipt, never an unmeasured appended instruction.
- Record recipe version plus content digests; reject changed bytes under an old version. Align output reserve, effective `num_predict`, context ceiling and tokenizer/framing metadata with the frozen recipe. No truncation, reduced evidence set or extra repair prompt after measurement.

Acceptance: German and English drafts preserve original citations and precision while localizing prose. The same frozen template produces the declared section shape. An injected instruction to add Kubernetes expertise, change output language or run PowerShell remains inert job data. A one-token budget overflow is visible with zero generation calls, not a reduced CV.

Tests: `test_prompt_versions.py`, `test_language_templates.py`, `test_prompt_boundary.py`, `test_budget_binding.py`; exact prompt-byte/fingerprint comparisons and hostile delimiter fixtures. Configuration impact: non-secret versioned prompt/content catalogs, explicit limits; no model download, paid service or renderer dependency.

### GEN-03-S04 — Execute structured inference through LLM-01

**Objective:** Obtain a bounded, attributable proposal from the configured local model.  
**Requirements:** R11/R15; supporting R07/R16.  
**Dependencies:** S02–S03, LLM-01; MODEL-01/02 for live identity/benchmark evidence.  
**Owned modules:** proposed `generation/draft_inference.py`, `draft_errors.py`; minimal schema registration/composition wiring.  
**Inputs → outputs:** verified binding → C10 call/result plus proposal, or classified failure.

Tasks:

- Persist an attempt/call identity, bind exact prompt bytes with `InMemoryInputResolver`, and invoke `ModelProvider.generate`. Set `draft_cv` or `draft_cover_letter`, frozen model/digest/settings/limits, prompt versions and proposal schema ID explicitly.
- Compare schema version/digest with the frozen recipe. Preserve the LLM prompt fingerprint separately from the complete recipe/input fingerprint; identical prompts with different model/settings are not the same generation recipe.
- Validate returned call/model identity and parsed output even for alternative provider implementations. For a pinned digest, require trustworthy runtime identity verification; missing response digest is not proof of identity. Use a provider capability/preflight receipt bound to the invocation or fail `model_identity_unverified`. Do not invent a runtime-management implementation in GEN-03.
- Reuse strict parsing, completion checks, timeout/size/depth bounds and the shared LLM-01 retry cap/deadline. Do not coerce malformed output or strip prose/fences into apparently valid JSON.
- Persist requested/effective settings, observed provenance, timing, available usage and physical attempts. Ensure audit failures prevent successful completion. Keep raw private prompts/results only in protected runtime records when required, never normal logs.

Acceptance: a scripted valid local result produces a proposal with matching C10 provenance. Malformed JSON, extra authority fields, incomplete/length-limited completion, changed weights, unavailable model, budget overflow and audit failure yield distinct visible errors. No second model client or hosted fallback is invoked.

Tests: `test_model_calls.py`, `test_model_identity.py`, `test_failures.py`, `test_retry_bounds.py`, `test_safe_diagnostics.py`; real LLM-01 harness with `ScriptedModelTransport`. Configuration impact: reuse provider settings; make verified identity availability a live integration gate and retain null usage as unknown.

### GEN-03-S05 — Admit grounded content and preserve review obligations

**Objective:** Turn a proposal into C14 without accepting invented candidate evidence or hiding uncertainty.  
**Requirements:** R11/R15; supporting R06/R13.  
**Dependencies:** S01–S04, frozen C01/C06/C09 and C08 rules above.  
**Owned modules:** proposed `generation/draft_grounding.py`, `draft_assembly.py`, `draft_review.py`; purpose-aware pure reference helpers if shared safely.  
**Inputs → outputs:** proposal plus binding → structured, unapproved C14 with issues, or rejected proposal receipt.

Tasks:

- Resolve every candidate citation against approved, purpose-permitted, admitted frozen facts. Resolve job claims only against the frozen posting; enforce claim subject/reference kind. Neither a search preference nor an assessment score, model rationale, previous generated draft or job requirement is new candidate evidence.
- Assemble protected structured values from source fields. Accept skill/metric selections only when present in the cited fact; reject fabricated skills, inflated metrics, changed units, unsupported dates/titles and synthetic precision. Keep derived totals or strengthened responsibility claims out of protected values unless explicitly supported.
- Check factual text against its cited source for directly detectable unsupported skill/metric changes; retain paraphrases with an explicit semantic-review obligation rather than claiming general entailment is proven. GEN-04 later runs fuller factual/consistency checks. A valid fact ID cannot certify changing “contributed” to “led.”
- Require factual clauses inside motivational passages to be split out and cited. Known factual material cannot bypass checks by selecting `subjective`; detected disguised experience/employer assertions fail admission. Preserve genuinely subjective wording as generated text with mandatory review, without representing it as a confirmed candidate preference.
- Merge upstream and generated uncertainty into typed issues, including missing information, ambiguous wording and retrieval omissions. A RAG miss is not proof the candidate lacks a skill. Never convert “not supplied” into a negative claim or strengthen a tentative posting statement into certainty.
- Set metadata from trusted bindings, preserve source text/values and record selected versus cited IDs for later EVAL-01 use. Do not alter C01, approve a fact/document, create a GEN-04 report or mark a request ready for review.

Acceptance: an advert requiring SQL cannot justify “I have SQL expertise” without an approved admitted SQL fact. Citing an unrelated approved fact does not rescue an invented 40% metric. A posting's “may offer hybrid working” remains uncertain and job-cited. Motivation such as “I would welcome the opportunity” remains visible and review-required. Mixed claims are split, and source/translation text stays available to GEN-04.

Tests: `test_candidate_claims.py`, `test_job_claims.py`, `test_protected_values.py`, `test_subjective_uncertainty.py`; adversarial valid-ID/false-text, wrong-purpose, cross-profile, wrong-revision, Unicode-span, nested factual-text and missing-context fixtures. Configuration impact: versioned grounding rules and content bounds; no toggle may disable evidence/review requirements.

### GEN-03-S06 — Persist content, reconcile retries and expose the worker adapter

**Objective:** Recover the same logical draft after a restart without losing evidence or repeating committed work.  
**Requirements:** R11/R15; supporting R12/R16.  
**Dependencies:** S01–S05, DATA-01, GEN-01/02 receipt interfaces, OPS-01 reference inventory.  
**Owned modules:** proposed `storage/repositories/draft_content.py`, `generation/draft_store.py`, `draft_adapter.py`; narrow migration, engine, retention and coordinator draft-stage changes.  
**Inputs → outputs:** admitted draft or error → durable receipt; repeated invocation → verified original result.

Tasks:

- Store attempt-start metadata before inference, then commit accepted C14, its hash, final receipt/audit links and dependency references atomically. Perform inference outside database write locks. Separate physical attempts from the stable request/seal/context/recipe result key.
- Persist rejected proposal/failure history safely, with no usable draft on fatal error. Do not erase previous failure evidence or overwrite an accepted draft. Concurrent completions use uniqueness/CAS; the first committed matching result wins, with subsequent attempts retained for audit.
- On restart, validate the content hash and frozen binding before reuse. A crash before content commit may require bounded repeat inference; a crash after commit must reopen content without another model call. Never promise exactly-once inference.
- Update the GEN-01 adapter/checkpoint to reference the durable receipt/hash, retaining explicit legacy `draft_json` reading. Repair a missing checkpoint from an existing valid receipt. A completed checkpoint with missing/corrupt content is an integrity error, not permission to regenerate or select current inputs.
- Register draft/receipt/audit and frozen-input references for backup/retention, including failed requests. Preserve records under storage pressure; surface capacity/write failures. Draft content persistence is not physical artifact creation.

Acceptance: terminate after receipt commit but before worker checkpoint; reopen yields identical content/IDs/hash with zero inference calls. Concurrent exact retries produce one logical draft. Deliberate regeneration under a new request gets a separate identity. Missing GEN-04 leaves the worker blocked at validation, with no renderer/deliverer calls or readiness transition.

Tests: `test_storage.py`, `test_replay.py`, `test_crash_matrix.py`, `test_worker_adapter.py`, `test_retention_restore.py`; real SQLite with fault injection and subprocess reopen. Configuration/migration impact: forward migration after actual head, explicit runtime data root; preserve C13/artifact semantics and old rows without fabricating provenance.

### GEN-03-S07 — Demonstrate component acceptance and hand off to GEN-04

**Objective:** Establish what structured generation guarantees, and state what remains unverified.  
**Requirements:** R11/R15; supporting R06/R07/R13/R14/R16.  
**Dependencies:** S01–S06; real GEN-02 for its integration gate, live MODEL-01/02 only for live checks.  
**Owned modules:** focused synthetic fixtures/tests, optional local smoke runner, non-secret example configuration and `docs/components/GEN-03.md`.  
**Inputs → outputs:** scenario matrix → repeatable verification evidence and consumer handoff.

Tasks:

- Exercise all eight type/language/strategy combinations: CV/cover letter × German/English × JSON/RAG, using the same approved snapshot and purpose rules. Add supported alternate content specs and invalid options. Use fake sealed-input providers explicitly until GEN-02 is implemented; never report those as real-freezer acceptance.
- Run security, provenance, retry and crash cases below through real local persistence and LLM-01 with scripted transport. Keep fixtures synthetic and assert no Salesforce, filesystem execution, renderer, delivery or approval calls occur.
- Supply GEN-04 with exact C14/receipt schemas, protected source values, typed references, warning locations, failure examples and snapshot resolution rules. Supply selected/cited evidence counts and latency metadata to EVAL-01 without building its Phase 1 evaluation workflow.
- Document actual dependency versions, schema/migration numbers, commands/results, native-Windows checks, live model/identity status and known limits. Live quality needs measured examples and human assessment; passing schema/reference tests cannot establish semantic truth.

Acceptance: the matrix passes at the declared offline/integration level; required live or prerequisite gaps remain clearly pending. No claim of G4 completion, delivered files or approved content follows from GEN-03 completion.

Tests: proposed `test_integration.py`, `test_windows_paths.py`, `test_windows_restart.py` plus the matrix. Configuration impact: example files and explicit test-only recipes/transports; no new required dependency or external deployment.

## Failure and retry policy

Use existing `ClassifiedError` categories with stable `details.reason_code`, safe IDs/paths/codes and no private source text. Do not add processing states implicitly. GEN-03 returns/persists errors; GEN-01 owns stage scheduling, retry policy and remote projection.

| Condition | Category / proposed reason code | Behavior |
|---|---|---|
| GEN-02 accessor, recipe/schema implementation or configured model absent | `missing_configuration` / `draft_dependency_missing`, `recipe_unavailable` | No inference; visible dependency block through worker adapter. Restoring the exact dependency permits resume. |
| Unsupported type/language/template | `unsupported_input` / `draft_option_unsupported` | No fallback. Corrected options require a new request if already sealed. |
| Missing/corrupt/cross-bound frozen resources | `validation` / `draft_binding_mismatch`, `frozen_input_corrupt` | No draft; restore original resources or create a new request. No latest-input substitution. |
| Context overflow or completion cut short by length | `context_budget` / preserve provider reason | No partial draft/truncation/strategy change. A different budget/recipe needs a new freeze/request. |
| Service unavailable, network/rate limit | Preserve LLM-01 transient/rate category | Bounded provider attempts/deadline; outer GEN-01 stage attempts also bounded. Document total worst-case physical calls; no independent GEN-03 retry multiplier. |
| Invalid JSON/schema, empty result, wrong identity | `model_output` / `draft_output_invalid`, `model_identity_unverified` | No usable draft. Only LLM-01's explicitly configured malformed retry is allowed; unverified identity requires dependency remediation. |
| Invalid citation, source-kind mismatch, unsupported skill/metric, detected factual disguise | `model_output` / `draft_grounding_failed` | Retain safe issue locations and protected failed-proposal record; do not silently relabel as subjective or accept a partial draft. |
| Genuine subjective wording or unresolved source uncertainty | Successful draft plus typed review issue | Preserve text and uncertainty, always review-required; never auto-approve. |
| Storage full/write/audit failure | `capacity` for actual capacity; otherwise explicit classified storage/audit failure | No success/checkpoint until durable commit. Retain prior committed results; retry only after remediation under bounded policy. Do not misclassify corruption as transient capacity. |

Transport retry, malformed regeneration and outer stage retry retain the same sealed inputs. New physical calls receive their own audit identity; previously committed content always wins. Diagnostics expose correlation IDs, versions, hashes and codes. Private raw prompts, CV text, candidate values and signed URL parameters must not appear in logs, exception strings or public handoffs.

## Required acceptance and verification matrix

| Scenario | Required observable result |
|---|---|
| CV only / explicit cover-letter request | Exactly the requested structured document; no implicit letter and no dependence on a previously generated CV. |
| `de`/`en`, both context strategies and supported templates | Correct declared content language/structure/options; preserved originals and citation language; no inference of candidate fluency. |
| Profile/job/template/prompt/config edited after freeze | Saved receipt/prompt/options still used; stale or unavailable pinned implementation fails visibly. |
| Candidate P1 fact used from P2, other candidate, wrong purpose, private or unselected fact | Grounding fails even if the UUID exists somewhere in storage. |
| Job C08 with wrong revision/path, empty quotation, out-of-bounds Unicode span or quote/span disagreement | Grounding fails against exact frozen content; no fuzzy matching or URL fetch. |
| Required skill appears only in posting; unrelated valid fact cited for new metric | Unsupported candidate claim rejected; no profile mutation. |
| “Contributed” rewritten as “led”; ambiguous source wording | Never certified truthful by ID matching; identifiable semantic review obligation and downstream GEN-04 handoff. Detectable contradictions fail admission. |
| Null/partial dates, unknown employer/name, missing salary or proficiency | Preserve unknown/precision; omit optional fields or fail explicit required-content rule. No invented numbers, contact details, dates or certainty. |
| Prompt injection in description, employer name, quotation, retrieved text or delimiters | No authority change, executable action, secret access, new evidence or altered output options. Normal grounded output or explicit failure. |
| Factual text hidden in header/summary/motivation | Citation checks cover it; detected disguise fails instead of bypassing grounding as subjective. |
| Source availability/retrieval warnings omitted by model | Application copies them into C14 review issues; absence from RAG is not a negative candidate fact. |
| Invalid model payload, wrong call/schema/model digest, missing pinned identity evidence | Distinct classified failure, bounded calls and no successful content receipt. |
| Crash before model result / after result before commit | Inspectable interrupted attempt; bounded retry with identical frozen inputs; no false completed checkpoint. |
| Crash after content commit before checkpoint / repeated polling | Exact receipt reused and checkpoint repaired without inference; one logical content version. |
| Backup/restore, cleanup, capacity failure, corrupt receipt | Referenced content/inputs protected; valid restore resumes exactly; corruption/capacity stays visible. |
| Missing GEN-04/05/06 | Content can persist; no rendering, delivery, notification, approval or readiness side effect. |
| Native Windows paths with spaces/non-ASCII and changed CWD | Explicit base/pathlib resolution, safe open/close/reopen and subprocess restart work. |

Proposed fixture root: `tests/fixtures/generation/content/`, with frozen P1/P2 and J1/J2, per-purpose permissions, partial dates, German characters, mixed factual/subjective passages, hostile jobs and scripted provider failures. Keep expected semantic outcomes explicit; do not use only tests that mirror serialization. Use real repositories and LLM-01 harness offline; separately record real GEN-02 integration and opt-in local model checks. No live Salesforce access is required for this component.

Implementation-time PowerShell commands (not executed by this planning task):

```powershell
$gen03Repo = (Resolve-Path '.').Path
$gen03Python = Join-Path $gen03Repo '.venv\Scripts\python.exe'
& $gen03Python -m pytest (Join-Path $gen03Repo 'tests\generation\content')
& $gen03Python -m pytest (Join-Path $gen03Repo 'tests\generation') (Join-Path $gen03Repo 'tests\models') (Join-Path $gen03Repo 'tests\contracts') (Join-Path $gen03Repo 'tests\storage') (Join-Path $gen03Repo 'tests\context') (Join-Path $gen03Repo 'tests\operations')
$gen03Temp = Join-Path $env:TEMP ('GEN-03 Prüfung ä ' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $gen03Temp | Out-Null
Push-Location -LiteralPath $gen03Temp
try {
    & $gen03Python -m pytest (Join-Path $gen03Repo 'tests\generation\content\test_windows_paths.py') (Join-Path $gen03Repo 'tests\generation\content\test_windows_restart.py') --basetemp (Join-Path $gen03Temp 'Daten Größe')
} finally {
    Pop-Location
}
```

Run affected configuration/CLI/schema-export checks when changed, then the repository regression gate. Record exit codes and actual environment. Prior handoff results and fake transports do not prove current live/native-Windows acceptance.

## Configuration and migration impact

| Area | Planned impact |
|---|---|
| Draft configuration | Proposed `DraftGenerationSettings` and non-secret example/catalog reference in application configuration, separate from GEN-01 polling/retry settings. Supported type/language/template content specs, versioned recipes and output limits are validated. Values become semantic inputs only through GEN-02 sealing. |
| Prompts and schemas | Track prompt resources in source; keep real candidate data out. New proposal/receipt schemas v1.0 and C14 content v2.0 coexist with legacy C14 v1.0. Pin bytes/digests and record the explicit compatibility/blueprint decision. |
| Model and budget | Reuse local provider settings, timeouts and retry policy. Freeze semantic settings, model identity, output reserve/limit and measurement policy. No assumed 4 GB VRAM fit or unmeasured drafting budget; MODEL-02 owns recommendations. |
| Templates/languages | Carry requested options and frozen content-spec identity only. Do not install renderers, design layouts or alter GEN-05's defaults. Unsupported or unavailable production specs remain explicit dependencies; synthetic specs are test-only. |
| Persistence | Forward migration after current head and GEN-02 changes; immutable content receipts, attempts and reference edges. No physical Artifact records, approval fields or remote metadata deployment. Preserve legacy checkpoint inspection without invented provenance. |
| Paths/privacy/retention | Runtime records outside source under configured absolute Windows data root. Use `pathlib.Path`, resolve relative resources from explicit config/package base, escape JSON Windows paths properly and protect referenced content in backup/retention. Ordinary diagnostics contain safe metadata only. |
| Dependencies | Reuse Python/Pydantic/SQLite/local LLM infrastructure. No new service/framework, cloud API, paid dependency, scheduler or UI. Required GEN-02 and runtime identity support remain visible integration gates. |

## Implementation handoff checklist

- [x] Record GEN-03 status, direct R11/R15 acceptance and exact scope; distinguish implemented from verified.
- [x] List owned/changed files, schema/interface versions, migration number and C14 legacy migration/consumer behavior.
- [x] Name actual GEN-02 handoff/API versions or explicitly retain the missing-prerequisite gate; publish receipt/binding examples.
- [x] Record CV/cover-letter recipes, language/template behavior, prompt/schema digests, effective budget and model identity policy.
- [x] Demonstrate candidate/job C08 separation, approved-purpose/admitted-fact enforcement and frozen-posting quotation/span resolution.
- [x] Show unsupported skill/metric rejection, protected source values, missing identity handling and persistent subjective/uncertainty review flags.
- [x] Record strict model-output, privacy, injection, failure/retry and durable replay checks; state semantic-validation limits.
- [x] Prove receipt-before-checkpoint recovery, no repeated committed inference and deliberate regeneration isolation.
- [x] Report automated, fake-integration, real GEN-02, native-Windows and live local-model results separately; keep pending checks explicit.
- [x] Hand GEN-04 C14 content, source/receipt access and review issues; leave rendering, delivery, approval and Phase 2 with their owners.

The stories below preserve the original planning baseline. The implementation decision, actual GEN-02 integration repairs, verification results, and remaining language/quality limitations are authoritative in [the GEN-03 handoff](../components/GEN-03.md); the original planning observations above are historical, not current implementation status.
