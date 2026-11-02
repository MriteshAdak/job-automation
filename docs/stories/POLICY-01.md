# POLICY-01 — Search policy and vocabulary

Status: **PLANNED** · Planning date: 28 October 2026 · Component: **POLICY-01 only** · Phase 0

Baseline: [IMPLEMENTATION_BLUEPRINT.md][blueprint], v1.0, 26 October 2026. Requirement IDs refer to §2; contracts to §4; correctness rules to §5; component ownership to §6; story and handoff instructions to §8; native Windows conventions to §9. These are ordered stories for future implementation. This planning task creates only this document.

## Repository evidence and component boundary

Read [README.md](../../README.md), the blueprint, the [FND-01 handoff][fnd], existing [FND-01 stories](FND-01.md), relevant current contracts, schemas, fixtures, tests, configuration and CLI. Also inspected the [PROFILE-01 plan][profile-plan] for the candidate-facts boundary and the [DATA-01 handoff][data] for existing CLI ownership. No applicable `AGENTS.md` was found in the repository or checked ancestor directories; README and blueprint §§8–9 provide the working instructions.

| Evidence | Actual baseline and consequence for these stories |
|---|---|
| FND-01 handoff | Reports VERIFIED, schema 1.0, Python 3.12.10 and 78 passing tests on native Windows. Those are historical prerequisite results, not POLICY-01 verification. |
| [C02 models](../../src/job_automation/contracts/policy.py) | `SearchPolicy`, `HardCriterion`, `PreferenceRule` and `RelevanceConfig` exist. There is no `src/job_automation/policy/` service yet. Structural parsing alone does not validate usable policy semantics. |
| `HardCriterion` / `PreferenceRule` | `field` and `operator` are strings; `expected_value` is `Any`; rule IDs are not checked for uniqueness. Preference weight is bounded to 0–1. No field/operator/operand catalog or cross-rule conflict detector exists. |
| Missing-information fields | `HardCriterion.on_missing` defaults to `unknown`; `SearchPolicy.missing_information_behavior` supplies a second per-field setting. Both permit `pass`, `fail`, `unknown`. Precedence, omitted-versus-explicit handling and interpretation are undefined. |
| Versions and mutability | C02 has an authored `policy_version` string, no computed fingerprint. `ContractModel.schema_version` defaults to `1.0` but is not a supported-version check. Frozen models still contain mutable lists/dicts. |
| [Configuration](../../src/job_automation/configuration.py) and [CLI](../../src/job_automation/cli.py) | `active_policy_ref` resolves to `ResolvedPaths.policy_path` relative to the app configuration file. `config check` reports the path but does not open or validate the policy. DATA-01 has added `storage migrate` and `storage status`; preserve their ownership. |
| [Example policy](../../config/policy.example.json), C02 fixture and tests | Synthetic examples call an all-workplace-types rule “Germany or Remote”, use a nonexistent C06 `skills` field, and group FastAPI/Django with Python as aliases. They contain no substantive German alias coverage. Their roles, thresholds and exclusions are not user preferences. |
| C01 / PROFILE-01 plan | Current `CandidateEligibility.target_locations` mixes willingness and eligibility; `min_salary` is a preference; `remote_eligible` defaults to true. PROFILE-01 decision D02 already calls for coordinated correction. POLICY-01 must not consume these defaults as facts or migrate C01 itself. |
| C06 / C11 / interfaces | C06 distinguishes locations, workplace type, remote restrictions, compensation and advert language. It has no `skills` field. Its default empty location/restriction lists and EUR/yearly compensation units do not prove those values were supplied by a source. `RuleEvaluator.evaluate_rules(revision, policy, eligibility) -> Assessment` belongs to MATCH-01. C11 currently prevents hard-failure-plus-eligible, but does not implement all assessment/disposition rules. |
| Schemas and tests | `schemas/v1/C02_search_policy.schema.json` is generated from typed models. The current catalog tests typed fixtures and schema JSON parsing, not complete JSON Schema validation parity or export drift. |
| Dependency setup | `pyproject.toml` contains version ranges, despite handoff wording about pins. Record the actual environment used; do not claim a lockfile or a newly verified installation. |
| Planning-session environment | Invoking `.venv/Scripts/python.exe` for a document-only check failed because its referenced base Python executable was unavailable. No application tests ran. Validate or repair the environment through the FND setup instructions before future implementation checks; this task does not alter it. |

**Direct requirements:** R01 (independent desired-job criteria, required/preferred distinction and missing-information behavior) and R05 (configuration needed by deterministic and broad relevance assessment). Supporting constraints: R14 (native Windows), R15 (safe local configuration and diagnostics), R16 (explainable versions and errors). POLICY-01 prepares inputs for R05; it does not complete matching or the G1 deterministic pipeline gate.

**Catalog dependency:** FND-01 only, particularly its C02/C01/C06/C11 contracts, error types, schema export and configuration boundary. PROFILE-01 and DATA-01 are coordination/consumer references, not added prerequisites. Synthetic fixtures suffice; no real candidate profile, job source, database, model service or Salesforce account is required.

**In scope:** local C02 loading, structural and semantic validation, an explicit criterion vocabulary, German/English aliases, hard/preferred separation, effective missing-information settings, bounded conflict diagnostics, deterministic policy fingerprints, minimal validation CLI wiring, examples, tests and a component handoff.

**Outside scope:** applying rules or keywords to postings, extracting requirements, deciding pass/fail/unknown for an actual job, scoring or producing C11, candidate approval/history, source fetching, normalization, identity resolution, JSON/RAG construction, model calls, policy database/history infrastructure, cache invalidation execution, Salesforce changes, scheduling and document generation. Direct alias lookup is vocabulary work; a job-text matching engine remains MATCH-01 work.

## Decisions, invariants and compatibility

Blueprint requirements are authoritative. File names, the story split, API/result names, normalization rules, CLI syntax and fingerprint design below are **proposals to resolve during implementation**, not additional user-confirmed requirements. All sample roles, salaries, thresholds and exclusions are synthetic. Germany is the confirmed search market; no candidate proficiency, authorization or particular profession follows from that target.

The following invariants apply across all stories:

- C02 describes wanted jobs and search behavior. C01 describes approved candidate facts. Loading a policy needs no C01 and must not create, modify, approve or infer candidate facts. A preferred German advert, German alias, desired salary, remote preference or `regions=["DE"]` cannot establish language proficiency, salary history, geographic eligibility or work authorization.
- Hard criteria are explicit constraints. Preferences retain their own IDs, values and weights and cannot silently become eligibility gates. A confirmed hard failure cannot be overridden by preferences or an LLM score; actual outcome computation belongs to MATCH-01/02.
- Unknown/null differs from known-empty, false and zero. Invalid configuration is a validation error, not an unknown candidate or rejected job. Missing retrieval evidence is not proof of missing capability.
- Workplace type, job location and remote geographic restrictions are separate. Advert language and candidate language requirements/proficiency are separate. Salary units and employer-versus-estimate provenance stay explicit; no implicit conversion is introduced.
- Narrow keyword absence must not be configured as an automatic rejection shortcut. Explicit exclusions and broad vocabulary can be configured without implementing assessment here.
- An executable policy is released only after blocking validation succeeds. Errors have stable codes/paths; warnings stay visible. No partial policy or misleading success fingerprint is returned on error.
- A validated policy's fingerprint must continue to describe its exact effective content. Nested caller mutations must not silently alter a cached/returned policy beneath an unchanged fingerprint.

Resolve these decisions in the named stories and record them in the future `docs/components/POLICY-01.md`. A decision marked blocking must close before dependent stories are accepted. Real user preferences can remain pending while synthetic component acceptance is verified.

| ID | Decision / gap | Proposed direction, owner and closure |
|---|---|---|
| D01 | Supported C02 schema, field/operator/value combinations and service result | POLICY-01 S01, coordinated with FND-01. Use a finite catalog of C06 paths and any explicitly named lexical targets; reject arbitrary attribute traversal or expressions. Prefer a versioned policy-local result containing effective C02, vocabulary, diagnostics and version metadata. No duplicate C02 model. Blocking for S02–S06. |
| D02 | `regions`, desired salary, language and legacy C01 preference fields | POLICY-01 S01/S04 with PROFILE-01 D02/FND-01 coordination. Proposed `regions` describes search scope; a hard geographic restriction must be explicit in `hard_criteria`, with no hidden region gate. Put desired compensation/job-language choices in C02; leave C01 correction/migration to its owners. Decide exact geographic aggregation and compensation operand definitions before accepting those configurations. |
| D03 | Missing precedence, materialized defaults and legacy `pass`/`fail` | POLICY-01 S01/S04; coordinate C11 implications with FND-01/MATCH-01. Proposed precedence: explicitly supplied criterion setting, then exact field default, then `unknown`. Preserve explicit `unknown` versus omission during loading. Default unknown remains reviewable. Define any explicit pass/fail as a policy action on missing information, never proof of a fact; if that distinction cannot be represented safely, reject that action with a migration diagnostic until a versioned representation is agreed. Blocking for S04–S06. |
| D04 | Exclusions, negative keywords and soft/hard conflicts | POLICY-01 S01/S05. Define bounded, literal scopes and exact relationship to explicit exclusions; no implicit regex/code execution or unconditional keyword-veto inference. Typed exclusion kinds, if needed, require a versioned C02 change. Select error versus warning rules; define where analysis is incomplete. |
| D05 | German/English normalization and alias scope | POLICY-01 S03. Proposed NFC, trimming/collapsing whitespace and case folding for lookup, with original display strings retained. Separate role/skill namespaces; direct explicitly configured equivalence only. No stemming, machine translation, implicit transliteration, acronym expansion or related-skill inference. Normalized collisions require a visible decision. |
| D06 | Fingerprint transport, canonicalization and relation to `policy_version` | POLICY-01 S01/S06 with FND-01 and downstream consumers. Proposed tagged SHA-256 over effective configuration plus schema/semantic/normalization versions. Preferred approach: retain the authored label as metadata and use a computed version in effective C02 for C11 consumers. An alternative additive fingerprint field requires a consumer/compatibility plan. An unchanged authored label must never conceal changed behavior. Blocking before S06 is complete. |
| D07 | Relevance scales, ordering, weights and examples | POLICY-01 S04/S06. Proposed initial supported scale `0-100`, optional threshold within that scale, finite weights in 0–1 with no requirement to total one. Record which collections are semantic sets and which preserve order. Actual thresholds/preferences remain user inputs; MATCH-02/EVAL-01 own quality calibration. |
| D08 | Operator command and path/encoding rules | POLICY-01 S02/S07. Proposed read-only `policy check` with direct file or app-config reference and optional JSON output; exit 0 for valid including warnings, 2 for configuration/validation errors. Choose UTF-8/BOM behavior explicitly and verify PowerShell 5.1/7-compatible file creation. |
| D09 | Actual preferences and future retention/invalidation | User configuration remains pending; do not solicit invented defaults to complete these stories. POLICY-01 S08 documents the versioned handoff. DATA-01/RUN-01 own durable retention and reassessment wiring; MATCH-01 owns consuming the effective policy. Those integrations remain separately pending. |

Any shared contract change follows blueprint §8: compatible additions update generated schemas, fixtures and recorded versions; incompatible changes require a migration/consumer plan and updated blueprint decision. Do not silently change meanings in `schemas/v1/`, reinterpret old `policy_version` labels as hashes, or reject historically supported payloads without documenting the compatibility path. Distinguish legacy structural readability from acceptance as a newly executable policy. Preserve original legacy inputs; no automatic rewriting of the user's files.

## Ordered story map

Every story below is **PLANNED**, belongs to POLICY-01, and uses the implemented FND-01 baseline. Owned file names are proposed implementation targets; this planning task does not create them.

| Order | Story | Deliverable | Internal dependencies |
|---|---|---|---|
| 1 | [POLICY-01-S01](#policy-01-s01) | Semantic specification, public boundary and compatibility decisions | None |
| 2 | [POLICY-01-S02](#policy-01-s02) | Safe local C02 loader and structural diagnostics | S01 |
| 3 | [POLICY-01-S03](#policy-01-s03) | German/English vocabulary normalization and alias validation | S01, S02 |
| 4 | [POLICY-01-S04](#policy-01-s04) | Hard/preferred validation and effective missing-information settings | S01, S02; S03 for canonical term references |
| 5 | [POLICY-01-S05](#policy-01-s05) | Bounded cross-policy conflict detection | S03, S04 |
| 6 | [POLICY-01-S06](#policy-01-s06) | Deterministic fingerprint and effective version binding | S02–S05 |
| 7 | [POLICY-01-S07](#policy-01-s07) | Read-only CLI and corrected synthetic policy examples | S02–S06 |
| 8 | [POLICY-01-S08](#policy-01-s08) | Integrated checks, native Windows evidence and handoff | S01–S07 |

### POLICY-01-S01

**Objective and references.** Establish the policy semantics and shared-contract decisions before implementing validators. Direct R01/R05; supporting R14/R15/R16. Blueprint §§4–6/POLICY-01, 8–10. Primary C02; boundary references C01, C06, C11 and `RuleEvaluator`. C09 consumes the selected strategy later; it is not built here.

**Dependencies.** FND-01, especially S02/S03/S05/S07/S08 and its verified handoff. No PROFILE-01, DATA-01 or live-service implementation prerequisite.

**Owned files.** New `src/job_automation/policy/__init__.py`, `models.py`, `fields.py`; `tests/policy/__init__.py`, `test_contract_boundary.py`; `tests/fixtures/policy/README.md`; decision/API sections of future `docs/components/POLICY-01.md`. Coordinated edits only when justified: `contracts/policy.py`, public exports, schema exporter, affected generated schemas, C02 fixtures/generator and contract tests. Record any incompatible change in the blueprint and FND compatibility handoff. C01 remediation stays with PROFILE-01/FND-01.

**Inputs → outputs.** Existing C02 v1.0 and repository gaps → a supported policy schema/semantics specification, finite target/operator catalog, versioned result boundary, classified diagnostics and a compatibility plan. Proposed operations are load, validate, normalize vocabulary and fingerprint; none accepts a posting or candidate profile for assessment.

**Tasks.**

1. Enumerate all C02 settings: `policy_version`, `regions`, `role_aliases`, `skill_aliases`, `hard_criteria`, `preferences`, `exclusions`, `missing_information_behavior`, `relevance_configuration`, `primary_context_strategy`. Specify required/optional/default/known-empty meanings and reject unsupported schema versions at the policy boundary.
2. Define each supported target's origin, value shape, allowed operators, missing-state representation and collection semantics. Initial candidates are C06 `title`, `description_clean`, `company_name_hint`, `workplace_type`, `employment_type`, `locations` subfields, `remote_eligibility_restrictions`, `compensation` and `advert_language`. A `skills` target must either be an explicitly specified derived lexical target or be rejected; it is not a C06 property. Do not implement extraction or field evaluation.
3. Define salary operands with amount, currency, period, gross/net knowledge and admissible employer/estimate provenance. Choose how collection quantifiers work for multi-location constraints. Unknown conversion policy or ambiguous units cannot be hidden inside a bare number.
4. Resolve the wire/API aspects of D01–D04/D06: preference separation, missing-setting precedence/representation, exclusion scope and how downstream C11 receives an unambiguous policy version. Record candidate-field issues without reading candidate data or implementing PROFILE-01 fixes.
5. Define a versioned validation result carrying either an executable effective C02 plus metadata, or blocking issues. Reuse `ValidationIssue` and `ClassifiedError`; expose stable field paths, codes and severities. Validation success does not assert that any job is eligible.
6. Specify supported legacy reads, explicit migration diagnostics and schema generation ownership. Keep the implementation free of a general expression language or new framework.

**Acceptance examples.**

- “Prefer German-language adverts” is represented as a C02 preference on advert language; no C01 language proficiency is created. “Desired minimum pay” is a C02 operand, never candidate salary history.
- `regions=["DE"]` and a remote-work preference remain distinct from country/work-authorization facts. The catalog identifies location and remote restrictions separately.
- A policy referencing `candidate.language_proficiencies` as a posting field is rejected. A `skills` target has an explicit supported lexical definition or a specific unsupported-target error; it never silently resolves against nonexistent data.
- A legacy v1 policy remains structurally inspectable, while ambiguous semantics can block new execution with a migration diagnostic. An unknown future schema version fails explicitly.

**Tests.** Boundary tests for supported schema versions, complete setting coverage, supported target/operator declarations, forbidden candidate targets, typed diagnostics and absence of profile/assessment dependencies. Coordinate affected typed/schema fixture tests if the contract changes; do not write an evaluator fake that contains matching logic.

**Native Windows verification.** Import the new policy package with the explicit virtual-environment interpreter; run boundary/affected contract tests. Confirm imports need no credentials and create no runtime directories or database.

**Migration/configuration impact and handoff.** No database migration. Record exact shared/internal versions, field catalog, public signatures, legacy treatment and affected consumer contracts. Existing source labels and files remain preserved.

**Unresolved decisions.** Close D01 and the representation portions of D02–D04/D06. Later stories implement the declared rules; they must not each invent a different interpretation.

### POLICY-01-S02

**Objective and references.** Load local policy configuration predictably and distinguish missing, malformed and structurally invalid input. Direct R01; supporting R14/R15/R16. Blueprint §§3–4/C02, 8–9; existing `AppConfig`, `ResolvedPaths`, `ValidationIssue` and `ClassifiedError`.

**Dependencies.** FND-01; S01.

**Owned files.** New `policy/loader.py`, `policy/validation.py`, `tests/policy/test_loader.py`, loader fixtures under `tests/fixtures/policy/`. Minimal coordinated configuration helper/tests only if the existing path API is insufficient; no general configuration rewrite.

**Inputs → outputs.** Explicit policy `Path`, or app-config path resolved through `active_policy_ref` → parsed C02 plus author-presence metadata for later semantic validation, or safe classified issues. This intermediate result is not yet executable or fingerprinted.

**Tasks.**

1. Read JSON using an explicit UTF-8 policy, selected BOM behavior and `pathlib.Path`. Reuse app-config-relative resolution. Direct CLI paths are resolved once against the invocation directory and documented separately.
2. Reject duplicate JSON object keys before ordinary decoding silently drops a criterion/alias declaration. Reject non-object roots, malformed encodings/JSON, non-finite numeric literals and unsupported schema versions. Do not repair input by dropping unknown fields or coercing arbitrary expressions.
3. Preserve whether each `on_missing` was explicitly supplied; Pydantic's materialized default alone is insufficient. Carry enough source-path information for stable diagnostics without retaining unnecessary private payload copies.
4. Map absent active reference/missing files to missing configuration; invalid shape/content to validation; unsupported versions to the declared unsupported-input category; inaccessible files to permission errors. These are actionable errors, not retryable job outcomes.
5. Build safe allowlisted messages rather than printing raw JSON or `ValidationError` input values. Policy text remains data; no `eval`, shell execution, remote include fetching or environment expansion beyond documented path handling.

**Acceptance examples.**

- `active_policy_ref="policy.example.json"` resolves beside the app config even when launched from another directory. An absolute reference resolves to the same content and later fingerprint.
- Missing reference/file, invalid UTF-8, malformed JSON, a JSON list at the root, duplicate `role_aliases` keys and an unsupported schema version each produce distinct safe diagnostics.
- Omitted `on_missing` is distinguishable from explicit `on_missing="unknown"` for S04. Loading alone creates no C01, C11, database or data-root directory.
- A unique synthetic secret marker in a malformed value never appears in normal stdout/stderr or returned public diagnostics. Instructions embedded in alias text are inert strings.

**Tests.** Parameterized loader cases covering paths, encodings/BOM decision, malformed roots/keys, extra fields, supported versions, error taxonomy, explicit-field preservation and safe messages. Verify no network/model/storage calls using fail-if-called doubles. Do not require real candidate data.

**Native Windows verification.** Load files and app-config references with spaces and `Prüfung äöü` in their paths, from the repository and a different working directory. Record permission-test limitations if actual Windows ACL denial is not exercised; a mocked error is not an ACL test.

**Migration/configuration impact and handoff.** Reuse `active_policy_ref`; no new data directory or persistence API. Document encoding, relative-path bases, error categories and legacy-load behavior. No automatic input rewriting.

**Unresolved decisions.** Close D08's encoding/BOM behavior and S01's exact result/error signatures. Command presentation follows in S07.

### POLICY-01-S03

**Objective and references.** Build deterministic German/English vocabulary lookup from explicit alias declarations without inferring related skills or candidate knowledge. Direct R01/R05; supporting R14/R15. Blueprint §§4/C02, 5/broad recall and candidate truth, 6/POLICY-01.

**Dependencies.** FND-01; S01/S02.

**Owned files.** New `policy/vocabulary.py`, `tests/policy/test_vocabulary.py`, bilingual/collision fixtures in `tests/fixtures/policy/`; update policy-local result models and fixture README as needed.

**Inputs → outputs.** C02 `role_aliases` and `skill_aliases` → separate normalized canonical-term indexes with original display terms and versioned normalization metadata, plus duplicate/ambiguity issues. Lookup is direct string-to-canonical-term resolution, not posting tokenization or matching.

**Tasks.**

1. Implement the selected Unicode/case/whitespace normalization consistently for canonical names and aliases. Preserve punctuation that distinguishes terms such as `C`, `C++`, `C#` and `.NET`. Preserve display spelling separately.
2. Treat each canonical term as resolvable to itself. Define behavior for blank strings, normalized duplicate aliases in one group, canonical-key collisions, and aliases assigned to multiple canonical groups. Never use last-write-wins.
3. Keep role and skill namespaces separate. Reject ambiguous cross-group canonical/alias chains rather than deriving transitive equivalence, unless S01 explicitly introduces and versions a different model.
4. Provide explicit German/English examples beyond software, such as `Projektmanager` / `Project Manager`. Put broader related terms in broad keyword/preference configuration rather than pretending they are equivalent aliases.
5. Keep transliterations, gendered forms and domain-specific acronyms explicit when wanted. No dictionary download, LLM translation, stemming or automatic proficiency inference is required.

**Acceptance examples.**

- Explicitly configured `Project Manager: ["Projektmanager", "Projektmanagerin"]` resolves each name to the same role; whitespace/case variants follow the declared normalization. This asserts no candidate experience or language skill.
- Composed/decomposed umlaut spellings normalize consistently. `München` does not automatically equal `Muenchen` unless configured; any case-folding collision involving `ß` is handled visibly.
- One normalized role alias mapped to two different canonical roles returns an ambiguity error with both declaration paths. The same spelling in distinct role/skill namespaces is not automatically a conflict.
- `Java` and `JavaScript`, and `C`, `C++`, `C#`, stay distinct. FastAPI and Django are not silently supplied as Python synonyms. A single-group duplicate receives the documented warning/deduplication result.

**Tests.** Golden bilingual lookup examples, normalization idempotence, punctuation preservation, blank/collision/chain cases, namespace isolation and stable diagnostic ordering. Test only vocabulary operations; no whole-advert relevance results.

**Native Windows verification.** Run vocabulary tests and UTF-8 fixture loading with the explicit interpreter. Verify German characters survive JSON serialization and machine-readable CLI output later, independent of console glyph rendering.

**Migration/configuration impact and handoff.** Record normalization/version rules and duplicate handling. Changing normalization later requires a semantic-version/fingerprint change and compatibility note. No global candidate skill rewriting.

**Unresolved decisions.** Close D05, including case-folding collisions, punctuation, namespace rules and warning-versus-error treatment of duplicates.

### POLICY-01-S04

**Objective and references.** Validate hard and preferred criteria and resolve missing-information settings without evaluating jobs. Direct R01/R05; supporting R15/R16. Blueprint §§4/C02/C06/global unknown and unit conventions, 5/assessment rules, 6/POLICY-01 and MATCH-01. C01/C11 are boundary contracts only.

**Dependencies.** FND-01; S01/S02; S03 for canonical term references.

**Owned files.** New `policy/criteria.py`, `policy/missing.py`, `tests/policy/test_criteria.py`, `test_missing.py`; extend `fields.py`, `validation.py`, policy fixtures and fixture README. Shared-model changes only through S01's recorded contract plan.

**Inputs → outputs.** Structurally parsed C02, explicit-field metadata and vocabulary → validated criteria/preferences/relevance settings, fully resolved per-criterion missing action with its source, and diagnostics. Output contains configuration, not `RuleOutcome` or `Assessment` records.

**Tasks.**

1. Validate nonblank stable IDs, uniqueness within/across the declared rule-ID namespace, supported targets/operators and exact operand shapes. Reject boolean-as-number accidents, non-finite values, invalid enum values, impossible empty operands and unsupported comparisons.
2. Keep hard constraints and weighted preferences distinct. Validate finite 0–1 weights; define zero-weight and empty-preference-list behavior explicitly. Do not normalize weights into hard gates or require them to sum to one unless a later version documents that requirement.
3. Validate regions and their relation to explicit geographic criteria, workplace/remote restrictions, advert language, and compensation units against S01's catalog. Monetary configuration must carry comparable units and provenance policy; no exchange-rate or annualization implementation belongs here.
4. Resolve missing settings with D03 precedence. Reject misspelled/unsupported field keys; report unused defaults where appropriate. Materialize effective actions so serialize/reload does not change meaning. An explicit rule-level override is not itself a contradiction with a field default.
5. Document null/absent/enum-unknown versus known-empty/false/zero for consumers. Preserve the missing-fact state separately from any explicitly chosen operational action. Do not allow configuration to assert candidate authorization or proficiency; absent candidate evidence remains an assessment unknown. Hand off C06 default ambiguity to FND-01/INGEST-02/MATCH-01: provenance or a versioned representation must distinguish omitted restrictions/locations and salary units from source-supplied values. Do not repair C06 or infer missing source facts inside POLICY-01.
6. Validate supported relevance scales and threshold bounds, including `None` meaning no threshold and zero remaining a real value. Keep broad/negative keyword configuration separate from hard-criterion evidence. Accept only `json` or `rag`; selecting one does not initialize either strategy.

**Acceptance examples.**

- Hard `workplace_type in ["remote", "hybrid"]` plus a soft preference for `remote` remains two different kinds of configuration. Raising preference weight cannot weaken the hard constraint.
- Under the proposed precedence, omitted criterion `on_missing` inherits its exact field setting; explicit `unknown` overrides that setting; neither supplied resolves to `unknown`. Export/reload preserves the same effective actions.
- A missing salary/remote restriction is configured to remain unknown/reviewable by default. An explicit legacy missing `pass`/`fail` either retains a documented non-factual policy action or receives the migration error selected in D03; it never creates evidence of eligibility or lack of skill.
- Known zero pay, false values and known-empty lists are not classified as missing by the policy specification. A malformed salary operand fails policy validation rather than becoming a missing-salary rule.
- The consumer specification does not interpret a defaulted empty remote-restriction list as proof of unrestricted eligibility, or defaulted EUR/yearly values as proof of comparable salary units. Actual application of this distinction awaits INGEST-02/MATCH-01 and any FND-coordinated representation fix.
- A EUR/year threshold with explicit gross/net/provenance semantics validates under the supported catalog. A bare ambiguous salary number fails. EUR/month, EUR/year and USD/year cannot be treated as interchangeable bounds without an explicit supported conversion policy.
- Threshold 101 on scale `0-100`, NaN weight, duplicate IDs, `workplace_type gte 2` and unsupported strategy fail with field-specific diagnostics. A null threshold and weight zero round-trip without becoming omitted/unknown.

**Tests.** Table-driven field/operator/operand cases, ID uniqueness, weights/scales, strategy enum, missing-precedence matrix, explicit-versus-omitted round trips and candidate separation. Use tables of required consumer behavior for missing posting values; do not implement a mini rule evaluator to test them.

**Native Windows verification.** Run criteria/missing tests with the explicit interpreter and round-trip UTF-8 examples. Repeat in a fresh process to ensure behavior does not depend on prior loads or locale-specific number parsing.

**Migration/configuration impact and handoff.** Record supported operators/operands, fully materialized missing semantics and all changed example fields. Keep retained legacy inputs distinguishable from newly valid effective policies. No C01 or database migration.

**Unresolved decisions.** Close D02/D03 and D07's scale/weight semantics. Any mismatch requiring shared C02/C11 representation work must be reconciled through S01 before this story is accepted.

### POLICY-01-S05

**Objective and references.** Detect provable configuration conflicts and expose suspicious combinations without pretending to solve arbitrary language or job eligibility. Direct R01/R05; supporting R16. Blueprint §§4/C02, 5/hard criteria and broad relevance, 6/POLICY-01.

**Dependencies.** FND-01; S03/S04.

**Owned files.** New `policy/conflicts.py`, `tests/policy/test_conflicts.py`; conflict fixtures and catalog; compose checks in `policy/validation.py`.

**Inputs → outputs.** Validated targets/operands, canonical aliases, hard criteria, preferences, regions, exclusions, relevance and missing settings → deterministic error/warning diagnostics with involved IDs/field paths. No job input, score, disposition or automatic conflict repair.

**Tasks.**

1. Define a bounded conflict matrix: disjoint mandatory allowed sets for the same scalar domain, unequal required equalities, inverted comparable numeric bounds, and direct required/excluded intersections after alias normalization within the same declared scope.
2. Respect collection quantifiers: two location requirements are not automatically contradictory when a posting can contain multiple locations. Compare only constraints with compatible targets, quantifiers, units and provenance rules.
3. Report alias ambiguities from S03, invalid/contradictory configuration combinations, conflicting explicit missing declarations if the selected representation permits them, and relevance contradictions. Do not mislabel a permitted rule override of a field default as an error.
4. Treat merely unreachable or conflicting soft preferences as warnings where hard policy remains satisfiable. Distinguish explicit exclusion contradictions from broad positive/negative keywords that need human review; do not apply exclusions to jobs.
5. Sort issues predictably and include both sides of a conflict without dumping arbitrary input values. Explain that absence of a detected conflict is not proof every conceivable combination is satisfiable. Never pick a winning rule by file order or silently delete constraints.

**Acceptance examples.**

- Required `workplace_type=remote` and required `workplace_type=onsite` produce a blocking conflict for the same scalar field. Hard remote plus soft onsite produces the documented unreachable-preference warning, not a new hard restriction.
- A minimum compensation bound above a maximum in the same currency/period/basis produces an error. Unspecified/incompatible units produce a unit/unsupported-policy diagnostic rather than a false numeric contradiction or invented conversion.
- A required role term and an excluded alias of that same role in the same scope are reported together. A company-name exclusion and an unrelated skill term with the same spelling are not conflated across scopes.
- A multi-location policy is checked according to its declared any/all semantics. The validator does not assume all location lists represent one mutually exclusive city.
- Reordering declarations preserves the semantic conflict set identified by stable rule IDs/codes, with deterministic ordering. Index-based field paths must point to the corresponding declarations in the reordered input. An invalid policy returns no executable result/fingerprint; a warning-only policy remains inspectable and valid with warnings visible.

**Tests.** Conflict matrix including positive satisfiable cases, hard-versus-soft differences, alias-expanded collisions, scope/quantifier isolation, unit comparability, stable issue ordering and preservation of the original input. No NLP, solver service or matching engine.

**Native Windows verification.** Run conflict fixtures with the native interpreter. Check the later CLI's text/JSON diagnostics for UTF-8 paths and multiple simultaneous issues without console tracebacks.

**Migration/configuration impact and handoff.** Record the finite conflict matrix, severity policy and analysis limits. No automatic policy rewrite or data migration; formerly tolerated ambiguity gets an explicit compatibility diagnostic.

**Unresolved decisions.** Close D04, especially exclusion scopes, regex rejection, negative-keyword behavior and warning/error boundaries. Record unimplemented semantic analysis as a limitation, not an implicit guarantee.

### POLICY-01-S06

**Objective and references.** Give each effective policy a reproducible version fingerprint so future assessment/cache consumers can distinguish changed inputs. Direct R01/R05; supporting R16. Blueprint §§4/global versioning/C02/C11, 6/POLICY-01 and RUN-01, 8/change discipline.

**Dependencies.** FND-01; S02–S05 and the closed S01 version/consumer decisions.

**Owned files.** New `policy/fingerprint.py`, `tests/policy/test_fingerprint.py`, golden fingerprint fixtures; effective-result/export sections in `policy/models.py` and package exports. Coordinated C02 schema/fixture changes only if selected under D06. No storage repository or run/cache implementation.

**Inputs → outputs.** Completely validated effective policy, resolved missing rules and versioned vocabulary semantics → canonical bytes, tagged digest and a consumer-visible effective C02 version binding. Preserve the authored label and original source separately for explanation.

**Tasks.**

1. Specify canonical UTF-8 JSON bytes, key sorting, Unicode handling, numeric rendering, default materialization and field inclusion. Proposed digest is SHA-256 with a named canonicalization/semantics version; do not use Python's process-randomized `hash()`.
2. Include regions, role/skill aliases, hard criteria/operands, preferences/weights, exclusions, effective missing behavior, all relevance configuration and primary context strategy, plus schema/semantic/normalization versions. Include rule IDs/names if they affect audit output. Document treatment of every C02 field; never omit a setting merely because the initial matcher does not use it yet.
3. Define list semantics explicitly. Proposed set-like alias/region collections can be normalized/sorted; preserve order where meaningful. Do not indiscriminately sort all lists. Specify label-only changes separately from effective-content changes; proposed authored display-label changes alone do not alter the behavior fingerprint. Decide explicitly whether preserved alias display spellings enter the hash; proposed behavior hashing uses normalized alias identities and retains display-only spellings separately.
4. Exclude the derived fingerprint itself, filesystem location, mtime, current directory, machine/user identity, validation timestamps, diagnostics and candidate/job data. Resolve self-reference by distinguishing authored input from the versioned effective export.
5. Bind the fingerprint to downstream C02/C11 `policy_version` according to D06. Preferred effective C02 carries a computed tagged version; if a separate field is chosen, all consumers must carry it before claiming correct input invalidation. Document legacy labels and prevent accidental double-hashing/relabeling on reload.
6. Ensure returned effective data cannot mutate beneath its digest: use detached immutable structures/copies or revalidate/recompute at the defined boundary. Provide canonical payload bytes for future retention by DATA-01/RUN-01 without implementing that retention here.

**Acceptance examples.**

- Repeated loads, JSON whitespace/key-order changes, LF versus CRLF and copying a policy to another Windows path produce the same fingerprint. Equivalent explicit defaults and resolved omitted defaults produce the same effective version.
- A meaningful effective change to each of region, alias mapping, criterion/operator/value, preference weight, exclusion, missing action, score threshold, broad/negative keyword or `json`→`rag` changes the fingerprint even when the authored `policy_version` label is unchanged. Normalization-equivalent alias edits follow the explicit display-spelling decision rather than contradicting the equivalence tests.
- Supported alias/set ordering changes follow the recorded canonicalization rule; meaningful sequence changes produce a different digest. Changed semantic/normalization version invalidates the fingerprint even if source JSON is identical.
- A validated effective export reloads to the same fingerprint/version under its declared export schema. The computed version is not hashed recursively as a new author label.
- Invalid/conflicting policies receive no success fingerprint. Mutating a caller-owned nested collection cannot leave altered effective content paired with the original digest. Candidate profile edits do not affect a policy-only fingerprint.

**Tests.** Golden canonical bytes/digests, one-change-per-field matrix, default and encoding equivalence, ordering rules, locale/process independence, semantic-version sensitivity, effective export round trips, legacy-label behavior and nested-mutation resistance. Tests assert version propagation into a consumer input stub, not actual C11 creation or cache invalidation.

**Native Windows verification.** Compare digests from two fresh native Python processes, different working directories and Unicode/space paths. Verify LF/CRLF equivalence and byte-for-byte canonical exports. No timestamps or absolute paths may enter the canonical payload.

**Migration/configuration impact and handoff.** Record algorithm/tag, canonical payload definition, example golden vector, version/label relation and old-version reader/consumer plan. Do not backfill stored assessments, alter identities or implement a policy history database.

**Unresolved decisions.** Close D06 and D07's ordering/default/numeric choices. If downstream C11 cannot identify changed effective policy, this story is incomplete even if a standalone hash function works.

### POLICY-01-S07

**Objective and references.** Make policy validation reviewable from PowerShell and supply truthful synthetic examples. Direct R01/R05; supporting R14/R15. Blueprint §§3–4/C02, 6/POLICY-01, 8–9; existing app-config/CLI boundary.

**Dependencies.** FND-01; S02–S06.

**Owned files.** New `policy/cli.py`, `tests/policy/test_cli.py`; minimal registration in existing `src/job_automation/cli.py`; `config/policy.example.json`, new `config/policy.office.example.json`, policy fixture README and examples; README policy instructions. Touch `config/app.example.json`, configuration tests or C02 fixture/generator/tests only when needed for consistency. Preserve storage command behavior.

**Inputs → outputs.** Direct policy file or app-config reference → read-only validity summary, warnings/errors and effective version/fingerprint. Proposed `--json` emits a versioned allowlisted result suitable for repeatable verification. It does not print a candidate/profile payload or run a search.

**Tasks.**

1. Add proposed `python -m job_automation policy check --policy <path>` or `--config <app.json> [--data-root <path>]`, with exactly one source selected. A config with no active reference fails visibly. Decide `--json` output schema and retain 0/2 success/error conventions; warnings remain visible on success.
2. Keep `config check`'s existing scope explicit in help/docs, unless an intentional compatible integration change is selected and tested. Never claim path resolution alone validated a policy. Do not initialize storage or model services from `policy check`.
3. Print supported schema/semantic version, authored label when applicable, effective version/digest and safe issue code/path/severity. Invalid input has no success fingerprint. Aggregate useful independent issues without a traceback or raw payload dump.
4. Correct example semantics: separate geography from workplace type; use actual supported fields; replace related-technology aliases with genuine explicitly configured synonyms and broad/soft terms; add German/English role and skill vocabulary.
5. Supply at least one general office-role example and one technical example, exercising hard/preferred choices and `json`/`rag` selection. Explain every illustrative role, weight, exclusion and threshold as synthetic; do not activate or personalize them automatically.
6. Document how an operator changes desired jobs without changing candidate facts, reads warnings and obtains a new fingerprint. Do not add policy activation, source access, matching or persistence commands.

**Acceptance examples.**

- Both corrected example policies pass semantic checks and expose a fingerprint. The office example demonstrates that configuration is not limited to software jobs.
- A valid policy with an unreachable soft preference exits 0 with a visible warning; a conflicting hard policy exits 2 with both paths and no fingerprint. Missing policy/config reference exits 2.
- A desired German advert, target Germany and a remote preference neither require a profile file nor report that the candidate speaks German or may work remotely in Germany.
- Direct and app-config-relative references to the same file produce the same effective version from another working directory. Existing help/version/config/storage tests remain compatible.

**Tests.** CLI subprocess tests for success/warning/error/JSON output, mutually exclusive inputs, reference resolution, safe stderr, corrected examples, version visibility and no network/database/directory side effects. Extend only affected existing CLI/config tests.

**Native Windows verification.** Execute the recipe below from native PowerShell with explicit interpreter/config paths, UTF-8 files, space/umlaut paths and a second working directory. Capture exit codes immediately. Verify the runtime data root remains absent when it was absent before validation.

**Migration/configuration impact and handoff.** Examples/help change; no runtime migration or automatic replacement of real policy files. Document command syntax, JSON result version, exit codes and whether `config check` remains path-only.

**Unresolved decisions.** Close D08's final CLI/output details. Actual user choices under D09 remain pending and do not become guessed sample defaults.

### POLICY-01-S08

**Objective and references.** Demonstrate isolated POLICY-01 acceptance and publish a precise handoff for MATCH-01 and RUN-01. Direct R01/R05; supporting R14/R15/R16. Blueprint §§6/POLICY-01, 7/G1, 8/handoff, 9/Windows.

**Dependencies.** FND-01; S01–S07. Downstream components may be absent; their absence does not authorize implementing them here.

**Owned files.** New `tests/policy/test_integration.py`, `test_schema_compatibility.py`; final fixture catalog; future `docs/components/POLICY-01.md`. Update README and existing affected tests/schema catalog only as required by actual contract changes.

**Inputs → outputs.** Synthetic policy corpus, current C02 schemas, resolved decisions and native command runs → reproducible test evidence, compatibility/consumer notes and component status. A capturing consumer stub may receive effective C02/version; it must not evaluate a job or construct assessments.

**Tasks.**

1. Integrate load → structural/semantic/vocabulary/conflict checks → canonical fingerprint → read-only inspection. Verify both example policies, all expected warning/error fixtures, and same-label changed-content behavior.
2. Compare affected generated schemas with typed exports using a temporary output directory; preserve published version schemas according to S01. Test legacy readability and new executable-policy validation separately. Mark rules enforced only by semantic Python validation rather than claiming the JSON Schema proves them.
3. Run focused component/contract/CLI checks, then the existing regression suite once. Add full JSON Schema fixture validation only with an explicit free test-dependency decision; schema parsing alone is not parity validation. No dependency upgrade is implicit in this story.
4. Execute native Windows checks below and record OS/Python/dependency versions, literal tested paths, commands, stdout/stderr/exit codes and limitations without real private input. Keep unit/contract, fake integration, native Windows and live-service statuses separate.
5. Document the exact MATCH-01 input contract: supported targets/operators, alias semantics, hard/preferred roles, missing policy, exclusions, version binding and error handling. Document RUN-01/DATA-01 obligations for retaining canonical policy inputs and reassessing when effective versions change. Do not implement those consumers.
6. Publish the handoff checklist below. Mark VERIFIED only when declared POLICY-01 acceptance is demonstrated; otherwise mark IMPLEMENTED with precise pending checks. No claim of G1, Phase 0 or live matching completion.

**Acceptance examples.**

- An offline synthetic policy produces a stable effective C02 and fingerprint without loading a profile, posting, database or service. A capturing consumer sees a new effective version after a one-setting edit under the same source label.
- An alias/configuration conflict stops executable output and names the relevant fields. German/English examples, hard/preferred separation and default reviewable missing behavior are all demonstrated.
- Historical C02 fixtures are explicitly supported for structural reading or have a documented version/migration diagnostic; they are not silently rewritten to make tests pass.
- The handoff distinguishes actual native checks from fakes and identifies live-service verification as not applicable to this offline component. MATCH/RUN integration remains pending until its owners implement it.

**Tests and native Windows verification.** Run the planned commands and matrix below after constituent tests pass. Repeat only for changed artifacts, failures or unresolved concerns. Do not present the FND-01 count as a fresh result.

**Migration/configuration impact and handoff.** No database migration. Publish C02 compatibility details, policy-local output versions, canonicalization golden vector, corrected examples and pending consumer obligations. Final file ownership should remain within POLICY-01 plus justified shared-contract/CLI changes.

**Unresolved decisions.** All POLICY-owned blocking D01–D08 decisions must be closed. D09 real inputs and downstream live integration may remain pending with explicit owners; they are not evidence that logic has been exercised on actual jobs.

## Native Windows verification recipe for implementation

These are **proposed future acceptance commands**, not commands executed by this planning task. S07 must finalize the command/output names before they are advertised as working. First verify the interpreter: the planning-session document check found the current virtual environment's referenced base Python unavailable. Restore a working environment through the FND-documented setup before running these tests; record resolved dependency versions rather than calling range-based installation pinned.

```powershell
# Run from the native Windows checkout. No shell activation is assumed.
$repoPath = (Get-Location).Path
$pythonExe = Join-Path $repoPath '.venv\Scripts\python.exe'
& $pythonExe --version
& $pythonExe -m pip freeze

# Proposed tests added by these stories; run after implementation.
& $pythonExe -m pytest '.\tests\policy' '.\tests\contracts' '.\tests\test_cli.py' '.\tests\test_configuration.py'
# Expected: 0; capture the actual test count and output.
$LASTEXITCODE

# Complete existing regression suite once after focused checks pass.
& $pythonExe -m pytest
$LASTEXITCODE

$policyPath = Join-Path $repoPath 'config\policy.example.json'
$officePolicyPath = Join-Path $repoPath 'config\policy.office.example.json'
& $pythonExe -m job_automation policy check --policy $policyPath --json
$LASTEXITCODE  # Expected: 0, versioned result with fingerprint
& $pythonExe -m job_automation policy check --policy $officePolicyPath --json
$LASTEXITCODE  # Expected: 0

# Create only synthetic verification inputs outside the repository.
$verificationRoot = Join-Path $env:TEMP ('Policy Prüfung ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $verificationRoot | Out-Null
$configCopy = Join-Path $verificationRoot 'app Prüfung.json'
$policyCopy = Join-Path $verificationRoot 'Suchregel ä.json'
$externalDataRoot = Join-Path $verificationRoot 'Laufzeit Daten'
Copy-Item -LiteralPath $policyPath -Destination $policyCopy
$appInput = @{
    schema_version = '1.0'
    data_root = $externalDataRoot
    active_policy_ref = 'Suchregel ä.json'
}
# Explicit UTF-8 without BOM works consistently across PowerShell editions.
$utf8Encoding = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($configCopy, ($appInput | ConvertTo-Json), $utf8Encoding)
& $pythonExe -m job_automation policy check --config $configCopy --json
$LASTEXITCODE  # Expected: 0, same fingerprint as the original policy

Push-Location -LiteralPath $env:TEMP
try {
    & $pythonExe -m job_automation policy check --config $configCopy --json
    $LASTEXITCODE  # Expected: 0, same reference resolution and fingerprint
} finally {
    Pop-Location
}
Test-Path -LiteralPath $externalDataRoot  # Expected: False; check creates no runtime data

$missingPolicy = Join-Path $verificationRoot 'missing.json'
& $pythonExe -m job_automation policy check --policy $missingPolicy --json
$LASTEXITCODE  # Expected: 2, missing_configuration, no success fingerprint

$malformedPolicy = Join-Path $verificationRoot 'malformed.json'
[System.IO.File]::WriteAllText($malformedPolicy, '{', $utf8Encoding)
& $pythonExe -m job_automation policy check --policy $malformedPolicy --json
$LASTEXITCODE  # Expected: 2, validation error, no payload/traceback dump
```

The test-created input directory is distinct from the runtime data root. Record before/after file state and close all file handles; do not claim no writes merely because no database rows changed. Repeat the relevant path checks from a native checkout whose repository path itself includes spaces and non-ASCII characters, or record that case as pending.

Additional required native scenarios:

| Scenario | Expected evidence |
|---|---|
| Malformed, unsupported-version, duplicate-key and alias-conflict files | Safe code/path diagnostics, exit 2, no executable policy/fingerprint; no default-policy fallback |
| Warning-only soft/hard disagreement | Exit 0, visible warning, unchanged hard constraint |
| Omitted versus explicit `on_missing` and field-level override | Effective missing-action/source matrix matches S04 and survives export/reload |
| Unicode, BOM policy, LF/CRLF and two process invocations | Same effective content yields same fingerprint; documented unsupported encoding yields a clear error |
| Edit one alias/weight/missing setting/context strategy under the same authored label | Effective version/fingerprint changes; no job assessment or cache mutation occurs |
| Copy the same file across paths; change current directory | Fingerprint unchanged; app-relative references remain anchored to config |
| Config check with absent/relative/inside-repository data root cases | Existing foundation behavior is preserved; policy command does not create directories to validate paths |
| Synthetic secret markers and text resembling commands | No raw marker/payload leakage, execution, network request or external include fetch |
| Imports and policy checks with model/Salesforce unavailable | Success for valid policy, no service calls, no database open and no candidate file read |

Live source, Salesforce, model/GPU, renderer and scheduling checks are **not applicable** to POLICY-01. Downstream MATCH-01/RUN-01 integration is **pending**, not established by a capturing consumer stub.

## Handoff and completion checklist

The future `docs/components/POLICY-01.md` must contain:

- Component ID/status, objective, R01/R05 and supporting requirements, FND-01 dependency/version, and the status of every story.
- Actual owned/changed files; exact input/output schema and semantic versions; supported fields/operators, regions/exclusions semantics, alias normalization, missing precedence and hard/preferred distinction.
- Resolved D01–D08 decisions with rationale; explicit distinction between implementation defaults and real user preferences. Cross-reference PROFILE-01 D02 without claiming C01 was repaired here.
- C02/legacy compatibility and any schema/fixture migration plan; canonicalization specification, golden bytes/digest, algorithm tag, label/version relation and mutation guarantees.
- Actual commands/results with unit/contract, fake integration, native Windows and live applicability stated separately. Explain any unrun check or incomplete semantic/schema validation.
- Confirmation that policy validation requires no candidate/profile input and never supplies proficiency, authorization, salary history or remote eligibility.
- Known conflict-analysis limits and pending real configuration; no undocumented fallback to examples when a policy is absent or invalid.
- MATCH-01 handoff for evaluation semantics and C11 version propagation; FND-01/INGEST-02/MATCH-01 coordination for defaulted C06 restrictions/locations/salary units that obscure unknown source information; RUN-01/DATA-01 handoff for retained canonical policy inputs and invalidation. No matching engine, persistence workflow or Phase 2 work implemented under this component.

Planning result: **all eight stories PLANNED**. No application code, configuration, schema, fixture, test or component handoff was implemented or modified by this task. No application tests or native Windows acceptance commands were run for these stories; repository inspection and document checks are planning evidence only.

[blueprint]: ../../IMPLEMENTATION_BLUEPRINT.md
[fnd]: ../components/FND-01.md
[data]: ../components/DATA-01.md
[profile-plan]: PROFILE-01.md
