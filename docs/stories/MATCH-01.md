# MATCH-01 — Deterministic eligibility and keyword matching

Status: **PLANNED** · Planning date: **28 October 2026** · Phase 0 · Scope: **MATCH-01 only**

Requirements baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), v1.0. References below use the requirement register (§2), contracts (§4), correctness/ownership rules (§5), component catalog (§6), integration gates (§7), implementation instructions (§8), and native Windows conventions (§9). This document specifies future implementation, not completed application work or verification.

## Objective, requirements and boundary

Evaluate configured hard criteria, preferences, exclusions and broad keyword/alias signals against an exact normalized job revision and approved candidate evidence. Produce a complete **C11 rules-only Assessment** with traceable pass/fail/unknown outcomes, reasons, unknowns, relevance and final dispositions, and null model/context metadata.

Direct requirements: **R01** (preferences separate from candidate history) and **R05** (hard rules, unknown handling, broad relevance). Supporting constraints: **R03** (normalized facts/provenance), **R08** (assessment distinct from candidate-owned application progress), **R09/R16** (durable references, reproducibility/audit), **R14** (native Windows), **R15** (private candidate evidence and untrusted job text). This component implements the deterministic portion of R05; MATCH-02 owns LLM assessment.

Inputs → outputs: validated/fingerprinted C02 policy, exact C06 content bound to a C07 canonical/revision identity, approved C01 snapshot and assessment-purpose inclusion view, traceable eligibility inputs, explicit execution identity and evaluator version → C11 Assessment or a classified input/configuration error. A valid posting with missing salary or eligibility data produces an inspectable assessment; a broken revision reference, invalid policy or unapproved profile does not become a rejection.

Excluded: acquisition, normalization, identity matching/merge changes, availability inference, arbitrary requirement extraction from prose, legal eligibility advice, profile approval, policy authoring UI, LLMs/embeddings/RAG, Salesforce calls or metadata, production C12 queueing/sync, pipeline scheduling/recovery, application submission and document generation. Narrow shared-contract/prerequisite corrections are coordinated explicitly below; they do not authorize implementing other components wholesale.

**Separate state domains:** `eligible/review/rejected` in C11 describes machine assessment. `Applied`, `Interviewing`, application `Rejected`, notes, follow-ups and overrides belong to the candidate. `active/not_seen/unavailable/unknown` belongs to IDENTITY-02. Neither assessment failure nor a lexical miss changes these other domains or deletes a job/application.

## Repository instructions and inspected evidence

Read [README](../../README.md), blueprint §§8–9 and [schema instructions](../../schemas/README.md). No applicable `AGENTS.md` was found in the checked repository/ancestor directories; the user-level `.codex/AGENTS.md` is empty. Generate shared JSON schemas from typed models; never edit generated schemas by hand. Use synthetic fixtures, config-relative path resolution, external runtime data directories and native PowerShell commands. Technical choices labeled proposed below are not user facts or confirmed thresholds.

| Current evidence | Consequence for MATCH-01 |
|---|---|
| [POLICY-01 handoff](../components/POLICY-01.md), [service](../../src/job_automation/policy/service.py), [validation](../../src/job_automation/policy/validation.py) | Reports VERIFIED. Consume `EffectivePolicy`, its materialized `on_missing` actions and fingerprinted `policy.policy_version`. Keep action provenance (`explicit_rule`, `field_default`, `global_default`). `regions` is discovery scope, not a hidden geographic hard filter. |
| [Target catalog](../../src/job_automation/policy/fields.py), [vocabulary](../../src/job_automation/policy/vocabulary.py) | Finite posting targets/operators; candidate targets and raw `skills` are rejected. Role/skill alias namespaces are distinct; normalization uses NFC, casefold and collapsed whitespace while preserving punctuation. Reuse these definitions rather than creating incompatible policy semantics. |
| [Policy models](../../src/job_automation/policy/models.py), [criteria validation](../../src/job_automation/policy/criteria.py) | The handoff promises explicit salary units, but `SalaryOperand` defaults EUR/yearly and `_validate_salary_operand` does not require those dictionary keys. Missing-unit dictionaries can therefore be accepted. Add a boundary regression and coordinate a narrow POLICY-01 correction before comparisons; do not silently use default units. |
| [PROFILE-01 handoff](../components/PROFILE-01.md), [service](../../src/job_automation/profile/service.py), [inclusion](../../src/job_automation/profile/inclusion.py) | Reports VERIFIED. Provides immutable snapshots, assessment-purpose inclusion and historical C08 fact resolution. Validate approval at the assessment boundary; the inclusion method itself is not an approval check. Real candidate inputs remain pending; synthetic fixtures demonstrate behavior. |
| [C01](../../src/job_automation/contracts/profile.py) | `CandidateEligibility.remote_eligible` defaults to `True`; lists/maps default empty; `min_salary` is a desired threshold and `target_locations` mixes eligibility/willingness. These shapes conflict with treating omitted facts as unknown and preferences as C02-only. There are no fact IDs on explicit eligibility fields. Do not infer truth from these defaults or mint evidence IDs. |
| [INGEST-02 handoff](../components/INGEST-02.md), [normalizer](../../src/job_automation/ingestion/normalization/service.py) | Reports VERIFIED. Missing/incomplete-unit salary becomes `None`; ambiguous remote flags become `unknown`; restriction/location collections can become `[]` when unstated. Keep them unknown for eligibility, despite the blueprint's general empty-collection convention, until presence semantics are represented explicitly. |
| [C06](../../src/job_automation/contracts/postings.py) | Has salary bounds/units/origin, multiple locations, workplace type, free-string remote restrictions and advert language. It has no structured language-level, sponsorship or work-authorization requirement object. Advert language cannot stand in for required candidate proficiency. Normalization issue/provenance data may be needed to distinguish ambiguous from known facts. |
| [IDENTITY-01 handoff](../components/IDENTITY-01.md), [revision code](../../src/job_automation/identity/revisions.py), [identity service](../../src/job_automation/identity/service.py), [identity repository](../../src/job_automation/storage/repositories/identity.py) | Now present and reports VERIFIED, including migration 4. However, C07 revisions hold title/URLs/hash, not full C06 content; observations hold raw references, not immutable normalized snapshots. The source-key-unique normalized table and ignored duplicate saves do not establish revision-specific historical content. Bind exact C06 input explicitly; durable historical snapshot resolution is an integration gap, not a missing whole identity component. |
| [RuleEvaluator protocol](../../src/job_automation/contracts/interfaces.py) | `evaluate_rules(revision, policy, eligibility) -> Assessment` lacks normalized content, profile version, inclusion permissions and fact provenance. No production assessment package/evaluator exists. S01 must freeze an explicit versioned input/reader strategy; never fabricate the profile version as the test fake does. |
| [C11](../../src/job_automation/contracts/assessment.py), [C08](../../src/job_automation/contracts/evidence.py) | `RuleOutcome` has only one optional evidence reference and no factual-versus-policy distinction. C11 lacks structured preference/exclusion details and evaluator version. C08 candidate citations require real fact IDs; job citations require a quotation/span, so absence is not represented by an invented quote. Contract changes need version/consumer plans. |
| [Assessment tests](../../tests/contracts/test_context_model_assessment.py), [assessment repository](../../src/job_automation/storage/repositories/assessments.py), [C12](../../src/job_automation/contracts/sync.py) | Existing tests prove basic shape, not evaluator correctness. C11 forbids eligible after hard fail but permits review and rules metadata that MATCH-01 should constrain. C11 storage and machine-only C12 payload exist; demonstrate compatibility in tests without implementing synchronization. |

The listed handoff results are historical reports, not tests rerun for this planning task. Actual code determines the interfaces available. Re-read dependencies at implementation time because repository work can advance independently.

## Evaluation rules to freeze before implementation

### Unknown facts and policy actions

**Proposed representation:** preserve a factual `pass/fail/unknown` result separately from the policy action taken for missing data. An unknown salary with `on_missing='fail'` can lead to policy rejection, but it must still say that salary is unknown, not proven below the threshold. An unknown with `on_missing='pass'` is an explicit waiver, not verified compliance. Prefer a versioned C11 extension carrying result basis, effective missing action/source, multiple evidence references and structured absence/ambiguity diagnostics. Keep absence diagnostics separate from C08 positive citations.

| Condition | Factual result | Proposed operational treatment |
|---|---|---|
| Valid comparable fact satisfies explicit hard criterion | pass | Hard gate satisfied; retain evidence |
| Valid comparable fact contradicts explicit hard criterion | fail | Rejected, regardless of preference/keyword strength |
| Required value unknown; missing action `unknown` | unknown | Review, with missing field/requirement and policy reason |
| Required value unknown; explicit effective missing action `pass` | unknown | Gate waived; preserve unknown in C11; other gates/relevance still decide |
| Required value unknown; explicit effective missing action `fail` | unknown | Rejected by missing-information policy, clearly distinguished from factual failure |
| Missing soft preference | unknown preference | No hard failure; record missing preference and score coverage |
| Invalid contract, unresolved snapshot/version or unsupported configuration | No factual outcome invented | Classified validation/configuration error; no successful/rejected C11 fabricated |

Unknown means more than `None`: unsupported/ambiguous representations, incomplete location alternatives, unknown enum values and unverified eligibility also matter. Negation does not turn unknown into pass. Do not reuse C02 job-field missing actions for candidate eligibility unless S01 defines an explicit policy binding.

### Candidate truth, geography and salary

- Use only approved, assessment-permitted C01 facts. Policy values describe desired jobs and how uncertainty is handled; they do not assert authorization, residence, language proficiency or experience. C01 `min_salary` and willingness fields must not override C02 criteria or silently create new gates.
- Absence from authorization lists or allowed candidate facts is not proof of inability. Explicitly scoped negative attestation, requirement applicability and source evidence are needed for a factual fail. Do not derive authorization from nationality, employer country, job location alone, or a search region.
- Remote arrangement, employer/job location, residence restrictions, willingness to relocate and work authorization are distinct. `remote` does not mean worldwide; `['DE']` restrictions need a defined interpretation and relevant explicit candidate fact. `EU` needs a versioned vocabulary/meaning, not a guessed set or a legal conclusion.
- Evaluate supported explicit requirements deterministically. Current C06 lacks typed language/authorization requirements and C01 lacks citeable eligibility attestations; S01/S05 must agree the minimal typed requirement/attestation and policy-action boundary. Unrecognized prose stays unknown/review rather than invoking a parser/LLM that this component does not own.
- Compare salary only with explicit comparable currency, period, gross/net assumptions and provenance. No implicit EUR/yearly defaults, annualization, exchange rates, hours-per-week assumptions, or conflation of employer pay with estimates. Proposed default is unknown for unapproved conversions or uncertain units/origin; expose the precise cause.

### Keyword recall, preferences and disposition

- Keep explicit hard job predicates, preference matches and broad relevance signals separately typed. Preferences cannot override hard failure or become rejection gates through a low weighted score.
- Apply declared role/skill aliases with Unicode-aware literal token/phrase matching. Preserve `C++`, `C#`, `.NET`, `Go`, and German text; do not use unbounded regex, arbitrary Python expressions, network lookup or automatic synonym invention.
- A missing broad keyword is inconclusive relevance, not a failed eligibility fact. Plausible alternate wording without a narrow hit stays reviewable for human/MATCH-02 assessment. Text searches cannot prove absence of candidate capability.
- Freeze the distinction between a literal hard text predicate and semantic recall. Proposed safe behavior: ordinary lexical no-hit routes to review; any intentional exact-text hard gate needs an explicit, versioned policy meaning. Do not silently turn existing broad keywords into exact-text rejection or silently ignore an accepted hard rule. S01/S06 resolve this policy ambiguity before implementation.
- Exclusions are configured literals, but context still matters: employer equality or an affirmative role/title match can provide a clear rejection basis; incidental/negated description mentions and ambiguous negative-keyword matches require review. Define finite fields and contexts, retain the exact match span, and do not promise general semantic understanding.
- Proposed initial C11 `relevance_score` and `score_scale` are null. Report preference outcomes/weights and lexical signals separately. If a relevance threshold is configured without a supported calibrated deterministic score, expose `score_not_evaluated` and route otherwise undecided relevance to review, not zero or rejection. An optional future deterministic score requires its own declared formula, coverage and version before threshold use; it is not an offer probability.
- Final precedence: confirmed hard failure or clear configured exclusion → rejected; policy rejection of unknown → rejected with explicit basis; unresolved required eligibility or inconclusive relevance → review; otherwise → eligible. A waived unknown remains listed. Evaluate all hard rules for complete reasons rather than short-circuiting at the first failure. Policy-invalid input never enters this precedence table.

## Ordered implementation stories

All stories belong to MATCH-01. Names below are proposed within `assessment/`; shared-contract and upstream files are narrowly coordinated. Each story contributes to S08's native Windows acceptance.

| Order | Story | Dependencies | Deliverable |
|---|---|---|---|
| 1 | MATCH-01-S01 | POLICY-01, PROFILE-01, INGEST-02; FND-01/IDENTITY-01 boundary owners | Frozen input, evidence, unknown and C11 compatibility contracts |
| 2 | MATCH-01-S02 | S01; profile inclusion and exact revision inputs | Validated input binding and evidence resolution |
| 3 | MATCH-01-S03 | S01–S02; POLICY-01 catalog | Typed hard predicates and missing-action evaluation |
| 4 | MATCH-01-S04 | S02–S03; salary operand correction | Comparable compensation rules |
| 5 | MATCH-01-S05 | S01–S03; explicit eligibility/requirement boundary | Geography and candidate eligibility checks |
| 6 | MATCH-01-S06 | S02–S03; POLICY-01 vocabulary | Preferences, broad recall and conservative exclusions |
| 7 | MATCH-01-S07 | S03–S06 | Complete deterministic C11 composition and consumer contract |
| 8 | MATCH-01-S08 | S01–S07; real local prerequisite interfaces | Integration, Windows evidence and component handoff |

### MATCH-01-S01 — Freeze assessment inputs, semantics and contract changes

**Objective/references.** Resolve representation gaps before rule logic. R01/R05/R03/R15/R16; C01/C02/C06/C07/C08/C11 and `RuleEvaluator`; blueprint §§4–6 and 8.

**Dependencies.** Actual POLICY-01, PROFILE-01 and INGEST-02 handoffs/code; FND-01 shared models; IDENTITY-01 revision/observation boundary. DATA-01 is a storage compatibility dependency, not a reason to build a new persistence framework.

**Inputs → outputs.** Current contracts and decisions below → approved-for-implementation input/result schema, supported semantic catalog, explicit policy decisions and consumer/migration plan.

**Owned files.** Proposed `src/job_automation/assessment/{__init__,models,ports,errors}.py`, `tests/assessment/test_contract_boundary.py`, fixture README. Coordinated `contracts/{assessment,interfaces,evidence,profile,policy,export_schemas,__init__}.py` only where necessary; affected schema generation and contract/fake-consumer fixtures. Upstream fixes must remain limited to the stated boundary gaps.

**Implementation tasks.**

1. Define a frozen assessment input containing C07 UUID/revision reference, exact C06 content/provenance, approved profile version and permitted facts, `EffectivePolicy` including action provenance, eligibility requirements/attestations, evaluator version and execution ID. Choose explicit versioned protocol arguments or injected immutable readers; never hidden mutable “current profile” state.
2. Resolve factual unknown versus missing policy action in C11. Define typed outcome basis, multiple citations (job plus candidate), missing-field diagnostics and stable IDs for derived eligibility/exclusion checks. Every configured hard criterion must have exactly one outcome; soft preference results must not become hard outcomes.
3. Decide typed C11 preference/exclusion/keyword detail storage, evaluator/input fingerprint metadata, reason codes, and rules-only null metadata invariants. Keep C11 the complete machine assessment rather than an undocumented sidecar essential to understanding disposition.
4. Coordinate C01 default/presence and attestation changes with PROFILE-01: omitted `remote_eligible` must not become proven true; legacy materialized defaults need a documented unknown/reconfirmation path. Define real fact/provenance links for eligibility, not synthetic fact IDs assigned by the evaluator. Preserve candidate-approved snapshot history.
5. Define configurable eligibility missing behavior and requirement applicability without reopening arbitrary `candidate.*` policy writes. Candidate truth stays C01; C02 can select checks/unknown actions through a separately typed, versioned configuration addition if needed. Current default for unresolved required eligibility is review.
6. Freeze collection quantifiers, salary interval semantics, lexical/no-hit handling, exclusions/negative keywords, preference scoring and relevance-threshold behavior. Record proposed choices separately from blueprint mandates.
7. Version shared changes, regenerate schemas during implementation, update fixtures/readers and record old-record compatibility. Frozen models with `extra='forbid'` cannot assume additive fields are transparently readable. Incompatible changes require the blueprint decision/consumer plan in §8.

**Acceptance criteria.** A reviewable input names exact job/profile/policy versions without an LLM context. Missing salary cannot be encoded as factual below-threshold evidence. A job-versus-candidate comparison can cite both sides; unknown has a structured diagnostic without a fabricated quote. Rules metadata cannot claim a JSON/RAG/model run just because C02 selects a strategy.

**Meaningful tests.** Contract combinations, rules/LLM metadata validation, legacy schema reads, missing action separation, invalid/mismatched versions, duplicate outcome IDs and fake protocol consumers. Validate omitted-versus-explicit candidate booleans across serialization, not only `model_fields_set` in memory.

**Migration/configuration/handoff.** Close D01–D05 below before dependent representations ship. Document forward migration/legacy-reader needs; do not rewrite old approved profiles or persisted assessments. Record final signatures and semantic versions.

### MATCH-01-S02 — Bind exact inputs and build resolvable evidence

**Objective/references.** Make every result refer to the data actually evaluated. R03/R05/R09/R15/R16; C01/C02/C06/C07/C08/C11; blueprint §§4–5.

**Dependencies.** S01; POLICY-01 validation/fingerprints, PROFILE-01 approval/inclusion/reference services, INGEST-02 valid output, IDENTITY-01 hash/revision binding. Durable historical content resolution requires the narrow prerequisite repair described below.

**Inputs → outputs.** Caller-supplied exact revision content and approved profile/policy → immutable evaluation view, allowlisted field accessors and evidence builders, or a classified boundary error.

**Owned files.** Proposed `assessment/{inputs,evidence,fields}.py`, `tests/assessment/{test_inputs,test_evidence,test_privacy}.py`. Coordinated immutable snapshot reader/persistence changes in IDENTITY-01/DATA-01 only if necessary to supply exact historical C06; no matching/merge redesign.

**Implementation tasks.**

1. Require successful policy validation and propagate the effective fingerprint, not authored labels. Preserve missing-action provenance without reserializing a materialized policy through the loader and losing whether the action was explicit.
2. Validate profile approval and build `purpose='assessment'` inclusion. Reject unavailable/unapproved profile versions as input errors. Never fall back to the latest version, expose excluded parent facts, or use historical audit resolution as permission for new use.
3. Verify canonical/revision/source identity and the IDENTITY-01 versioned content hash against the exact supplied C06. Never use a raw byte hash as a revision digest or fetch whichever normalized row matches a source tuple. Assess one bound revision; do not assemble favorable fields from several sources.
4. Establish immutable revision-content resolution with the upstream owner. Until available, explicit validated C06+revision fixtures and in-process inputs support isolated evaluation; historical persistence acceptance remains pending. Preserve old revision evidence after edits and merge/reversal without inventing snapshots from latest content.
5. Implement an explicit accessor table for supported targets, preserving null/unknown/presence and normalization warnings. Never `eval` policy fields or traverse arbitrary object paths.
6. Build job C08 references to exact normalized field values/spans with raw provenance links. For structured values, freeze a deterministic textual representation or explicit typed evidence extension; do not invent a source quotation. Map Unicode casefold/NFC lookup spans back to original text. Candidate references must resolve to permitted real facts at the exact profile version.
7. Record absence/ambiguity as a typed field diagnostic plus evaluated snapshot reference; do not put fabricated text such as “salary not supplied” into a C08 quotation. Validate quotations/spans against actual retained content.

**Acceptance criteria.** Salary in revision R2 cannot be assessed using R1's first stored normalized row. A citation to a normalized phrase resolves after an edit. A private fact remains excluded even if its alias matches the job. A mismatched canonical/revision ID returns an input error rather than an eligible/rejected result.

**Meaningful tests.** Real normalization/profile inclusion integration, exact historical citation lookup, cross-source same-content collisions, stale C06/hash mismatch, missing snapshots, unknown paths, Unicode offset round trips and injection-like field/job text remaining inert.

**Migration/configuration/handoff.** Prefer reader reuse; if snapshot persistence is missing, assign its repair explicitly to IDENTITY-01/DATA-01 and record the integration blocker. New fields/references require forward compatibility work, not a new MATCH-01 identity database.

### MATCH-01-S03 — Evaluate typed hard predicates and missing actions

**Objective/references.** Implement all supported non-compensation job predicates with honest pass/fail/unknown semantics. R01/R05; C02/C06/C08/C11; POLICY-01 D01–D03 and blueprint §5.

**Dependencies.** S01 semantics, S02 bound values/evidence, current `TARGET_CATALOG`. Salary delegates to S04; candidate eligibility to S05. Establish the literal matching primitive here for reuse by S06.

**Inputs → outputs.** Configured hard rules + typed field values → one factual outcome, evidence/diagnostic and effective missing action per criterion, in deterministic order.

**Owned files.** Proposed `assessment/{operators,hard_rules,missing,literal_matching}.py`, `tests/assessment/{test_operators,test_hard_rules,test_missing,test_literal_matching}.py`; narrow POLICY-01 validation/test corrections for accepted operands the evaluator cannot safely interpret.

**Implementation tasks.**

1. Implement allowlisted scalar `equals/not_equals`, set `in/not_in`, and text/collection `contains/not_contains` for each declared field/operator combination. Reject unsupported accepted configurations visibly before assessment; do not silently skip rules.
2. Distinguish unknown enum values from actual onsite/full-time values. `not_equals` and `not_in` on missing data remain unknown rather than passing. Explicit metadata-query use of the literal enum `unknown`, if allowed by POLICY-01, must be distinguished from proven eligibility.
3. Specify multi-location alternative quantifiers: proposed positive location tests pass if any fully evidenced alternative satisfies; fail only if all relevant known alternatives fail and no unresolved alternative remains; otherwise unknown. Negative tests use the corresponding conservative universal semantics. Freeze separate restriction-list semantics rather than borrowing scalar comparison accidentally.
4. Consume materialized missing actions and origin from `EffectivePolicy`; retain factual unknown plus the action selected. Do not treat a missing dictionary key, zero, false, empty collection and unknown enum as equivalent without the field-specific presence rule.
5. Evaluate every hard rule even after one fails, retaining all evidence and unknowns. Do not let preference or broad keyword state overwrite a hard outcome. Preserve rule ID/name from policy.
6. Implement the shared literal token/phrase primitive with POLICY-01 normalization and declared alias lookup, honoring S01's explicit exact-predicate versus recall decision. A missing skill word must never become “candidate lacks skill.” Surface ambiguous legacy hard-text policies for review/configuration clarification rather than silently assigning stricter semantics. S06 reuses this primitive for broad recall and exclusion context.

**Acceptance criteria.** `workplace_type=unknown` with required remote yields unknown/default review. Known onsite with required remote fails. A DE/FR multi-location job can satisfy “one available location in DE”; FR plus an unknown-country alternative is unknown, not a confirmed outside-DE failure. Changing only `regions` does not create a new hard outcome. Unknown salary policy actions remain distinct from factual fail.

**Meaningful tests.** Table-driven target/operator coverage, truth tables for null/unknown/known values, complete and incomplete sets, negation, empty versus unstated collections, duplicate alternatives, rule order invariance, all-results completeness and explicit/field/global missing precedence using real POLICY-01 outputs.

**Migration/configuration/handoff.** No extra runtime config beyond S01 policy semantics. Publish supported operators, collection quantifiers and rejected ambiguous configurations; version changes to meanings of existing operators.

### MATCH-01-S04 — Compare compensation without invented units or pay

**Objective/references.** Make missing/incomparable salary reviewable and evidenced contradictions decisive. R01/R05/R03; C02 salary operands, C06 compensation, C08/C11; blueprint §4 compensation conventions.

**Dependencies.** S02–S03; POLICY-01 explicit-unit validation correction and INGEST-02 compensation output. Actual desired salary amounts are user configuration, not inferred from examples or candidate history.

**Inputs → outputs.** Compensation criterion + structured salary/operand → Decimal-safe outcome, comparability/missing diagnostic and cited bounds/origin.

**Owned files.** Proposed `assessment/compensation.py`, `tests/assessment/test_compensation.py`, salary fixture matrix; coordinated `policy/criteria.py` tests for absent currency/period and invalid numeric values.

**Implementation tasks.**

1. Require authored explicit amount/currency/period for policy salary operands; distinguish the current model defaults from real supplied units. Reject non-finite/boolean/invalid operands before evaluation. Preserve Decimal precision.
2. Compare named `compensation.min_amount`/`max_amount` directly only when the requested bound and units are known. A missing lower bound is not zero; a missing upper bound is not infinity unless an explicit contract says it is unbounded.
3. Freeze whole-`compensation` interval semantics. Proposed conservative rule: pass when every value in the known interval satisfies the predicate, fail when none can satisfy it, unknown when it straddles the threshold or needed bounds are missing. For EUR/yearly `[50,000,70,000] >= 60,000`, return unknown; `[65,000,70,000]` passes; `[40,000,55,000]` fails. Named-bound rules keep their distinct meanings.
4. Do not annualize monthly/hourly pay or convert currencies. Gross/net mismatch or unknown required basis is incomparable, not a numeric failure. Respect requested provenance; estimated/unknown salary cannot satisfy an employer-provided-pay requirement as if it were an offer. Define whether explicit origin mismatch is a policy predicate failure or comparability unknown in S01 and explain it.
5. Apply configured missing action to absent/incomparable information using S03, preserving its cause and factual unknown. Candidate C01 salary history or `min_salary` must not fill missing job pay or supply a hidden policy threshold.

**Acceptance criteria.** Absent salary → unknown/review by default; explicit policy fail-on-missing → policy rejection with factual unknown retained. EUR/monthly 5,000 is not compared directly to EUR/yearly 60,000. Estimated yearly 80,000 is not described as employer-confirmed salary. Exact boundary equality follows the declared operator.

**Meaningful tests.** Boundary Decimal values, open/missing bounds, interval overlap, scalar-bound distinction, gross/net/null, currency/period mismatch, estimates, missing operand units, no float rounding, and real INGEST-02 incomplete-unit fixtures. Include metamorphic tests that changing irrelevant candidate salary history cannot change this result.

**Migration/configuration/handoff.** No conversion dependency or exchange-rate lookup. Record interval/default comparability decisions and explicit-unit rejection compatibility with existing policy files.

### MATCH-01-S05 — Evaluate location restrictions and explicit candidate eligibility

**Objective/references.** Compare job requirements to candidate truth without treating willingness, remote labels or missing attestations as authorization. R01/R05/R15; C01/C02/C06/C08/C11; blueprint §§4–5.

**Dependencies.** S01 explicit requirement/attestation and policy-action boundary, S02 permission/evidence binding, S03 unknown handling. PROFILE-01/FND-01 own eligibility representation; INGEST-02/SOURCE owners own supplied structured requirement provenance.

**Inputs → outputs.** Structured job geography/requirements + relevant approved eligibility attestations + selected policy behavior → evidence-bearing eligibility checks and unknowns with stable IDs, separate from job-preference checks.

**Owned files.** Proposed `assessment/{geography,eligibility}.py`, `tests/assessment/{test_geography,test_candidate_eligibility,test_eligibility_privacy}.py`; minimal coordinated shared models/profile validation or upstream mapping needed for S01's contracts. No legal rules service or general prose extractor.

**Implementation tasks.**

1. Keep location-preference matching from S03 distinct from candidate eligibility. A job satisfies C02's DE location preference independently of whether the candidate can lawfully work there.
2. Evaluate remote restrictions only when their meaning is supported and evidenced. An absent/empty-unstated restriction list is unknown, not worldwide; `remote_eligible=True` alone does not prove DE residence or work authorization. Preserve unrecognized restriction strings as reviewable uncertainty.
3. Compare a supported explicit job requirement with a relevant candidate attestation, citing both. Positive authorization in DE does not imply authorization elsewhere; missing authorization in a list does not prove explicit denial. Explicit scoped negative facts can fail a relevant confirmed requirement; uncertain applicability/sponsorship conditions remain reviewable.
4. Do not infer language requirements from `advert_language`, candidate nationality/name, residence or document language. If a supported structured language-level requirement and approved explicit proficiency exist, use a versioned comparison vocabulary; otherwise retain unknown. Do not parse arbitrary CEFR/free-text descriptions into invented levels.
5. Ignore C01 preference-like fields for job filtering unless an explicit future migration moves them into C02. Do not rewrite snapshots or merge willingness and capability. For legacy defaulted eligibility, follow the unknown/provenance migration decision, not an in-memory supplied-fields heuristic that disappears on storage round trip.
6. Route unresolved required eligibility via its explicit policy setting; default review. A missing policy binding cannot silently borrow a location or salary job-field action. Do not add unrelated authorization/language gates to every job merely because those candidate facts are absent.

**Acceptance criteria.** A remote DE-only role and unknown candidate residence/authorization remain reviewable. Evidence of meeting an explicit residence restriction passes that check but does not independently prove work authorization. An approved, scoped negative authorization attestation versus an explicit no-sponsorship authorization requirement can fail. A German advert with no stated language requirement does not fail an otherwise supported candidate lacking a stored German level. Empty candidate lists do not become factual failure.

**Meaningful tests.** Requirement applicability matrix, missing versus explicit positive/negative attestations, contradictory evidence, EU/free-text restrictions, onsite/hybrid/remote differences, alternative locations, defaulted booleans after persisted reload, profile-version changes and withheld facts. Assert citations resolve and excluded/private facts never influence outputs or logs.

**Migration/configuration/handoff.** Document prerequisite contract/mapping gaps and supported requirement kinds. Fixture-only requirements do not prove live extraction. If typed requirements/attestations are unavailable, report affected checks/integration pending; do not claim complete eligibility support from job-location matching alone.

### MATCH-01-S06 — Evaluate preferences, broad aliases and exclusions

**Objective/references.** Preserve plausible jobs while explaining ranking signals and explicit exclusions. R01/R05/R15; C02/C06/C08/C11; blueprint §5 broad recall and POLICY-01 vocabulary/exclusion decisions.

**Dependencies.** S01 matching/context decisions, S02 evidence, S03 typed field semantics and literal matching primitive, POLICY-01 vocabulary and preference catalog.

**Inputs → outputs.** Policy aliases/keywords/preferences/exclusions + bound job text/fields → structured preference matches, lexical hits/no-hits, exclusion decisions and conservative relevance disposition with evidence.

**Owned files.** Proposed `assessment/{keywords,preferences,exclusions,relevance}.py`, `tests/assessment/{test_keywords,test_preferences,test_exclusions,test_recall}.py`; synthetic technical and general office/job-family fixtures. Narrow policy conflict/validation changes only if the agreed matcher exposes inconsistent accepted semantics.

**Implementation tasks.**

1. Expand configured canonical role/skill groups deterministically with namespace-aware matching. Use NFC/casefold/whitespace behavior from POLICY-01, preserve original text for citations, and define token/phrase boundaries that handle punctuation. `Java` is not `JavaScript`; `Go` is not every “ongoing.” No unbounded regex or inferred synonym graph.
2. Evaluate every soft preference against allowed targets, recording match/non-match/unknown, weight and evidence. Weight zero is inert. Missing preferences are visible without hard failure. Proposed optional preference coverage/weighted match details are separate from C11 relevance score; never divide by zero or silently renormalize missing values into a perfect score.
3. Search configured broad signals across explicitly allowed title/description fields. Match German/English aliases and skill synonyms. No-hit remains inconclusive; return review when relevance cannot be established. Support an empty broad-filter configuration as “no lexical gate configured,” not universal mismatch.
4. Implement literal exclusions on finite fields with documented semantics. Use exact employer matching for an employer exclusion and bounded affirmative role/title evidence where supported. Preserve ambiguity when a legacy untyped exclusion could refer to company, role or prose. Negated/incidental/benefit-context matches and ambiguous negative keywords propose review, not automatic rejection; do not invent a general negation parser.
5. Freeze whether each negative keyword is a clear explicit exclusion or only a review proposal. Preserve distinction in output and align POLICY-01 contradiction checks. Existing regex detection also rejects some literal punctuation (for example `C++`); add a boundary fixture and resolve literal support with POLICY-01 rather than bypass validation.
6. Keep relevance score/scale null unless S01 explicitly adopts a documented deterministic scoring formula. Configured score thresholds with no evaluated score produce visible unresolved relevance and review, not fabricated numeric scores. Preferences and keyword frequency cannot override a hard failure or become hidden reject thresholds.

**Acceptance criteria.** “Projektleiterin” can match configured “Project Manager” role aliases. An office coordination role without one technical keyword remains reviewable. A missed remote preference does not reject a hybrid role. “No unpaid work” is not automatically rejected for the word “unpaid”; a clear configured excluded employer is rejected with exact employer evidence. Default example thresholds 65/70 do not force invented relevance scores.

**Meaningful tests.** Labeled positive/negative phrase corpus, German casing/umlauts/gender markers, punctuation, word boundaries, namespaces with overlapping terms, aliases added without narrowing recall, duplicate keywords not inflating strength, negated/incidental exclusions, private candidate text excluded from job keyword search, zero/unknown preference coverage and no-hit false-negative regression examples. Treat fixture results as local correctness evidence, not a market-wide accuracy benchmark.

**Migration/configuration/handoff.** Publish field scope, alias expansion and exclusion semantics, score/threshold behavior and matcher version. No new role/skill/employer facts or user thresholds are invented.

### MATCH-01-S07 — Compose a complete rules-only C11 and expose the consumer boundary

**Objective/references.** Produce the same complete assessment contract used by later LLM assessments while enforcing deterministic precedence and state ownership. R01/R05/R08/R16; C11/C12; blueprint §§3–6.

**Dependencies.** S03–S06 outputs and S01 C11 changes; DATA-01 serializer/repository and C12 payload for compatibility tests. MATCH-02, RUN-01 and SYNC-01 are consumers, not implementations included here.

**Inputs → outputs.** Bound evaluation input and all rule/preference/relevance results → validated C11 with deterministic semantic content and explicit execution/input-version metadata.

**Owned files.** Proposed `assessment/{service,composition}.py`, public exports, `tests/assessment/{test_assessment,test_disposition,test_reproducibility,test_consumer_boundary}.py`; affected contract/storage serialization tests.

**Implementation tasks.**

1. Fill assessment/canonical/revision IDs, actual approved profile version, effective policy fingerprint, method `rules`, all hard outcomes and structured auxiliary results, relevance/final dispositions, nullable score/scale, gaps/unknowns and concise summary. Use revision UUID as the preferred C11/C08 reference; document compatibility with legacy content-hash references.
2. Enforce the disposition precedence table. Distinguish confirmed job-preference failure, verified candidate gap, unknown fact and policy rejection/waiver. Missing skill evidence is an unknown, not a candidate gap. Record all rule outcomes even for rejected jobs.
3. Set `model_metadata=None` and any proposed model/prompt/context fields to null. C02 `primary_context_strategy` remains a policy input/version dimension, not evidence that context was constructed. Do not call model/context services.
4. Define reproducibility over exact revision/profile/policy, inclusion, evaluator/matcher/semantic versions. The same inputs produce the same semantic results and reasons; execution IDs may be caller-supplied/new per deliberate assessment. Retries preserve the supplied execution ID. Do not promise repository idempotency from its current duplicate-ID rejection; RUN-01 owns persistence/retry orchestration.
5. Keep computation free of external writes and candidate/availability mutations. Demonstrate C11 round-trip through the existing assessment repository in tests and conversion by a test-only consumer into the same machine-only C12 payload shape used for rules and LLM results, including null scores. No production mapping, queue worker, remote publication or sync sequencing is added.
6. Document the handoff to MATCH-02/RUN-01: a rules-only result can be final in deterministic mode or an intermediate input to later assessment. Selection of one final publication per input version belongs to orchestration; this evaluator never races to publish its result.

**Acceptance criteria.** High preference/keyword strength cannot make confirmed hard failure eligible. Unknown salary with default action gives review and a factual unknown; explicit waiver may permit eligible if every other required check/relevance condition is settled. A rejected assessment leaves `Interviewing`, notes, availability and existing artifacts unchanged. Rules-only output with null scores and metadata is consumable by C11 storage/C12 contract fakes.

**Meaningful tests.** Full disposition truth table, hard-failure dominance, policy waiver/rejection distinction, score-null threshold handling, all-rule completeness, stable ordering across input collection permutations, version-change sensitivity, actual JSON/SQLite round trips, rules-versus-LLM consumer parity and sentinel assertions for protected state. Unsupported/failed input must not emit a successful assessment.

**Migration/configuration/handoff.** Record C11 compatibility and storage implications. If serialization changes need migration, allocate the next version at implementation time after current migration 4 and any intervening work; do not edit applied SQL or introduce production outbox work.

### MATCH-01-S08 — Verify the local integration and publish the handoff

**Objective/references.** Demonstrate MATCH-01 acceptance using real local prerequisites and native Windows checks. R01/R05/R03/R08/R14/R15/R16; C01/C02/C06–C08/C11; blueprint §§6–9.

**Dependencies.** S01–S07, actual POLICY-01/PROFILE-01/INGEST-02 APIs and resolved exact-revision/evidence dependencies. External services, models and Salesforce are not prerequisites for this component's deterministic acceptance.

**Inputs → outputs.** Implemented evaluator, labeled synthetic corpus and compatibility decisions → documented verification, limitations, examples and `docs/components/MATCH-01.md` handoff.

**Owned files.** `tests/assessment/{test_integration,test_windows_paths,test_windows_restart}.py`, `tests/fixtures/assessment/README.md` and synthetic cases, future `docs/components/MATCH-01.md`, minimal README usage/API examples.

**Implementation tasks.**

1. Exercise real PolicyService, approved ProfileService inclusion and DefaultNormalizer with manual/structured synthetic source shapes through actual IdentityService and the bound assessment input. Cover eligible/review/rejected, missing pay, location restrictions, explicit eligibility, aliases, preferences, exclusions and malformed-input isolation.
2. Verify historical job/candidate references after edits and reload; where upstream durable snapshots/attestations are missing, label integration pending and demonstrate only the explicit-input fixture boundary. Do not claim historical auditability from a title/hash-only revision.
3. Build a labeled decision corpus with expected outcomes and reasons reviewed independently of implementation structure. Include plausible no-keyword jobs, nontechnical roles, ambiguous restrictions and explicit policy rejection of missing data. Record any known false negatives and unsupported semantics without building EVAL-01's benchmarking system.
4. Run focused tests, affected policy/profile/normalization/identity/contracts/storage tests, then one full regression. Record exact platform/Python/dependency versions and exit codes. Run native Windows paths/restart tests below with synthetic external temporary data and no network.
5. Publish status per blueprint: implemented if required checks remain pending; verified only when declared component acceptance is demonstrated. Separate unit, fake consumer, real local integration, SQLite/restart and native Windows evidence. Live Salesforce/model checks are outside scope, not implied by mocks.

**Acceptance criteria.** All catalog outcomes are shown: missing salary/geographic eligibility is reviewable, required and preferred criteria behave differently, aliases work, and complete C11 can enter the common downstream payload contract. Candidate/application/availability state is untouched. Unresolved prerequisite decisions and real-input onboarding remain explicit.

**Meaningful tests.** Execute the recipe after tests exist. Reassess from another CWD and a separate native process against the same immutable inputs; semantic output/citations match. No real personal data, executable external text, live API, model service or Salesforce credentials are needed.

**Migration/configuration/handoff.** Record all owned/coordinated files, final contract/evaluator/policy versions, migration/legacy behavior, examples, check results, open decisions and next work for MATCH-02, RUN-01, SYNC-01 and EVAL-01.

## Native Windows verification recipe for implementation

These are future checks, not tests executed while creating this story document. Start at the repository root in native PowerShell. Use a functioning native Python environment; do not claim old handoff results prove the current environment works. Dependencies are currently ranges in `pyproject.toml`, so record actual versions. Resolve executable/test paths before changing CWD.

```powershell
$match01Repo = (Resolve-Path '.').Path
$match01Python = Join-Path $match01Repo '.venv\Scripts\python.exe'
$match01Tests = Join-Path $match01Repo 'tests\assessment'
$match01Temp = Join-Path $env:TEMP ('Job Automation Bewertung Prüfung ' + [guid]::NewGuid().ToString())

& $match01Python -c "import platform, sys, sqlite3; from zoneinfo import ZoneInfo; print(platform.platform()); print(sys.version); print(sqlite3.sqlite_version); print(ZoneInfo('Europe/Berlin'))"
$match01EnvironmentExit = $LASTEXITCODE
& $match01Python -m pip show pydantic pytest tzdata
$match01VersionsExit = $LASTEXITCODE
& $match01Python -m pytest $match01Tests
$match01FocusedExit = $LASTEXITCODE
& $match01Python -m pytest (Join-Path $match01Repo 'tests\contracts') (Join-Path $match01Repo 'tests\policy') (Join-Path $match01Repo 'tests\profile') (Join-Path $match01Repo 'tests\ingestion') (Join-Path $match01Repo 'tests\identity') (Join-Path $match01Repo 'tests\storage')
$match01BoundaryExit = $LASTEXITCODE

New-Item -ItemType Directory -Path $match01Temp | Out-Null
Push-Location $match01Temp
try {
    & $match01Python -m pytest (Join-Path $match01Tests 'test_windows_paths.py') (Join-Path $match01Tests 'test_windows_restart.py') --basetemp (Join-Path $match01Temp 'Test Daten Größe')
    $match01WindowsExit = $LASTEXITCODE
} finally {
    Pop-Location
}

& $match01Python -m pytest (Join-Path $match01Repo 'tests')
$match01RegressionExit = $LASTEXITCODE
[pscustomobject]@{
    EnvironmentExit = $match01EnvironmentExit
    VersionsExit = $match01VersionsExit
    FocusedExit = $match01FocusedExit
    BoundaryExit = $match01BoundaryExit
    WindowsExit = $match01WindowsExit
    RegressionExit = $match01RegressionExit
}
```

Require zero exit codes and record failures. Tests must cover spaced/non-ASCII checkout, config and data paths, Unicode policy/text/citations, config-relative input resolution from another CWD, exact-version SQLite reload and released handles. Use `pathlib.Path` and `sys.executable` for child processes. No current MATCH-01 CLI is assumed; test the public service directly. If contracts change, run the existing schema exporter during implementation and review generated output against S01's version decision.

## Missing prerequisites and unresolved choices

These are implementation/dependency decisions, not a blanket approval pause. Continue independent tests while an upstream boundary is unresolved, but do not mark the dependent acceptance complete.

| ID | Gap or decision | Owner and required closure |
|---|---|---|
| D01 | `RuleEvaluator` lacks C06 content and approved profile/version/evidence binding | FND-01 + S01/S02. Freeze versioned input or injected readers and protocol consumer tests. Never fabricate versions or read unbound current state. |
| D02 | C07/raw observations do not provide immutable full normalized content for each historical revision | IDENTITY-01/DATA-01 + S02/S08. Implement/verify exact revision snapshot resolution or document explicit-input-only limitation. A source-key lookup is insufficient; no identity rewrite belongs here. |
| D03 | Default true remote eligibility, empty eligibility collections and preference-like C01 fields | PROFILE-01/FND-01 + S01/S05. Establish presence/unknown semantics, citeable attestations and legacy policy. Do not rewrite approved history or use default values as evidence. |
| D04 | C11 single citation and missing factual-versus-policy basis; C08 absence/structured-value limitations | FND-01 + S01/S02/S07. Version typed outcomes/diagnostics and multiple evidence; preserve existing consumer compatibility. Unknown actions must remain distinguishable from factual proof. |
| D05 | No structured authorization/language requirements or eligibility-specific policy bindings | POLICY-01/PROFILE-01/INGEST-02/FND-01 + S01/S05. Agree supported requirement kinds, applicability, policy actions and provenance. Free-text/unsupported cases remain reviewable; no hidden legal or LLM extraction engine. |
| D06 | Salary operand defaults contradict explicit-unit handoff; whole-interval and gross/net/provenance meanings | POLICY-01 + S01/S04. Require authored units, freeze comparisons and mismatch/unknown treatment with negative fixtures. Conversions stay disabled unless separately specified. |
| D07 | Unknown versus empty job collections; multi-location and restriction quantifiers | INGEST-02 + S01/S03/S05. Preserve field presence/ambiguity through the input boundary and document alternatives/restrictions independently. No empty-unstated worldwide assumption. |
| D08 | Literal text hard gates versus recall; exclusion field scope, negative keywords and punctuation | POLICY-01 + S01/S06. Publish finite matcher semantics and compatibility decisions with false-positive/false-negative examples. No rejection solely from a narrow broad-keyword miss. |
| D09 | Preference aggregation and existing `min_score_threshold` without a deterministic score | S01/S06/S07 with POLICY-01. Proposed null relevance score plus visible review when threshold cannot be evaluated; no silent zero or preference-based rejection. Any alternative scoring formula needs versioned meaning and tests. |
| D10 | Execution identity, evaluator fingerprint and durable serialization compatibility | S07 with DATA-01/RUN-01/SYNC-01. Define stable semantic outputs, caller-controlled retry identity and consumer contract. Production assessment/outbox atomicity and final-publication sequencing remain downstream work. |
| D11 | Real candidate/profile/policy inputs and verification environment | PROFILE-01/POLICY-01 operator onboarding; S08 verification owner. Synthetic fixtures are sufficient for local logic, not proof of user eligibility/preferences. Record actual native environment and pending real-input integration separately. |

## Implementation handoff checklist

- Component ID/status/objective, R01/R05 and supporting requirements; exact input/output contracts and prerequisite versions.
- Owned/coordinated files, generated schemas, compatibility/migrations and preserved historical references.
- Supported field/operator/collection semantics, salary comparability, candidate requirement applicability and missing-action precedence.
- Candidate facts versus preferences, factual result versus policy action, hard versus soft outcomes, and all disposition precedence cases.
- Evidence resolution for pass/fail/unknown; exact revision/profile references, original Unicode spans and privacy/inclusion behavior.
- Alias/exclusion/negative-keyword semantics, plausible no-hit handling, preference detail and score/threshold decisions.
- Complete C11 examples for eligible/review/rejected with rules-only null metadata; protected application and availability state unchanged.
- Reproducibility/execution identity, existing storage/C12 consumer compatibility, and separation from production synchronization.
- Actual commands, versions, exit codes and results, distinguishing fixture/fake/real local integration/native Windows; no unsupported live-service claims.
- Resolved/open D01–D11, missing snapshots/attestations/mappings, real-input limitations and next steps for MATCH-02, RUN-01, SYNC-01 and EVAL-01.
