# FND-01 — Project foundation and shared contracts

Status: **PLANNED** · Planning date: 27 October 2026 · Component: **FND-01 only** · Phase 0

Baseline: [IMPLEMENTATION_BLUEPRINT.md][blueprint], version 1.0, 26 October 2026. The requirement register is in §2, contracts in §4, correctness rules in §5, FND-01 in §6, handoff instructions in §8, and Windows conventions in §9. This document plans future implementation; it does not report implemented or tested application behavior.

## Repository evidence and scope

Initial inspection found `README.md`, `IMPLEMENTATION_BLUEPRINT.md`, and four historical documents under `archive/`. At final inspection, `archive/` was no longer present; this task did not modify or remove it. The blueprint and README remain the planning sources, and historical documents do not add requirements. There is no application package, project/dependency configuration, schema implementation, test suite, example configuration, or component handoff. The exposed `.git` directory contains no usable repository metadata; Git status could not be obtained. No existing implementation or migration needs to be preserved at this starting point.

FND-01 directly covers [R03][requirements], [R14][requirements], and [R15][requirements]: establish the uniform data contracts, native Windows foundation, and safe configuration/data boundaries. Other requirement IDs below explain which consumers need a contract. Those links do not claim that FND-01 implements or completes the downstream requirement.

In scope: project configuration and package boundaries; C01–C15 typed records, JSON schemas, enums, structural validators, identity conventions, service-independent interfaces, synthetic fixtures, non-secret configuration, and a CLI skeleton that loads configuration without external accounts.

Out of scope: SQLite repositories/migrations and durable state (DATA-01); candidate approval/import and search-policy semantics (PROFILE-01/POLICY-01); source registry behavior, importers, fetching, normalization and identity resolution (SOURCE/INGEST/IDENTITY); rule evaluation, retrieval, inference and benchmarks (MATCH/CONTEXT/LLM/MODEL); Salesforce inspection, authentication, metadata and writes (SF/SFCLIENT/SYNC); pipeline execution, locks, checkpoints and recovery (RUN-01); document generation/rendering/delivery (GEN); retention/backups (OPS-01); all Phase 2 scheduling, automatic drafting and notifications. Define the fields/interfaces these components will consume, without implementing their workflows.

### Requirements, baseline decisions, and proposals

| Classification | Meaning for these stories |
|---|---|
| Confirmed user requirements | Native Windows on the existing 16 GB RAM / 4 GB VRAM computer; effectively zero monetary budget; existing Salesforce Developer Org; Germany/general white-collar search with configurable criteria; explicit uniform restructuring of heterogeneous input; both full-profile JSON and RAG. FND-01 supports these through contracts and setup, without configuring real searches or accessing the org. |
| Blueprint engineering baseline | Modular Python package, local data outside source control, UUID local identities, opaque scoped provider IDs, UTC events, explicit unknowns, shared versioned contracts, separate ownership/state domains, local-only model access, synthetic fixtures, and the proposed module boundaries. These are adopted blueprint decisions, not additional statements of user confirmation. |
| New proposals in this plan | Story IDs/order, exact file names, configuration format/precedence, CLI command names/exit codes, schema packaging, protocol style, and test organization. All owned paths below are proposed implementation targets. An implementer may refine them within FND-01, recording the decision and updating examples. |
| Unresolved implementation choices | Exact supported Python/dependency versions, validation/schema library, schema dialect, serialization details, and interface signatures must be selected and pinned/documented in FND-01. No version, model, employer, candidate fact, threshold, or source access permission is selected by this planning document. |

Structural validation means checking record shape, field types, enums, and explicitly documented record-local consistency. It does not mean proving evidence true, resolving stored references, evaluating eligibility, enforcing durable uniqueness, or executing state transitions. Schema-expressible constraints and Python-only cross-field checks must be documented separately; JSON Schema validation alone must not be advertised as full domain validation.

## Story map and execution order

Every story below belongs to FND-01 and starts PLANNED. FND-01 has no prerequisite component. Internal story dependencies establish build order; downstream consumers are not prerequisites and can be represented by test-only fakes.

| Story | Deliverable | Internal dependencies |
|---|---|---|
| [FND-01-S01](#fnd-01-s01) | Installable project and package ownership baseline | None |
| [FND-01-S02](#fnd-01-s02) | Shared primitives, serialization, enums and errors | S01 |
| [FND-01-S03](#fnd-01-s03) | Profile, policy and evidence contracts: C01, C02, C08 | S02 |
| [FND-01-S04](#fnd-01-s04) | Source, posting and identity contracts: C03–C07 | S02 |
| [FND-01-S05](#fnd-01-s05) | Context, model and assessment contracts: C09–C11 | S03, S04 |
| [FND-01-S06](#fnd-01-s06) | Sync, request, document and summary contracts: C12–C15 | S03, S04, S05 |
| [FND-01-S07](#fnd-01-s07) | Typed service boundaries and fake conformance checks | S03–S06 |
| [FND-01-S08](#fnd-01-s08) | Non-secret configuration and native CLI skeleton | S01, S02; S03/S04 for referenced example contracts |
| [FND-01-S09](#fnd-01-s09) | Complete schema/fixture verification and component handoff | S01–S08 |

S03 and S04 can progress independently after S02. S08 can progress alongside contract work once configuration primitives are settled. Each contract story owns its schemas and fixtures; S09 integrates and audits them rather than postponing all validation until the end.

<a id="fnd-01-s01"></a>
## FND-01-S01 — Establish the Python project and ownership boundaries

**Objective and linked requirements.** Make the foundation installable and testable on native Windows with explicit executable paths and no external account. Direct: [R14][requirements], [R15][requirements]. Source: blueprint §§3, 6/FND-01, 9–10.

**Inputs, outputs, and owned files/modules.** Input: the blueprint and current documentation-only repository. Output: minimal package/build metadata, a documented Python version and reproducible dependency installation, source/data exclusions, and a package ownership map. Owns `pyproject.toml`, the selected lock/pin artifact, `.gitignore`, `src/job_automation/__init__.py`, test-package markers including `tests/__init__.py` and `tests/contracts/__init__.py`, `README.md` setup instructions, and the setup/ownership sections of the future `docs/components/FND-01.md`. Reserve the blueprint's package boundaries in documentation; do not populate future components with placeholder business services.

**Implementation tasks.**

1. Select a maintained native-Windows-compatible Python release and minimal build, validation, schema-checking, and test dependencies. Verify support when implementing; record exact tested versions, free licensing, and installation commands. Pin the resolved dependencies, including Windows timezone data required to resolve `Europe/Berlin`.
2. Establish a `src` package layout and a single foundation entry-point location. Proposed: `python -m job_automation`, with command implementation added in S08. Keep imports free of network calls, data-directory creation, and model/service initialization.
3. Document the module map from blueprint §3, including the handoff of future CLI pipeline commands to RUN-01. Avoid adding database, model, Salesforce, web, or rendering dependencies merely because later components will need them.
4. Exclude virtual environments, local secret/config overrides, runtime databases/files, profiles, raw data, indexes, artifacts, logs and backups from source control. Preserve intentionally committed synthetic fixtures and non-secret examples.

**Acceptance criteria with concrete examples.**

- In a clean native Windows virtual environment, the documented installation succeeds and `python -c "import job_automation"` succeeds without Salesforce/Ollama credentials or services. Importing creates no database, runtime directories, or outbound requests.
- Setup uses an explicit executable such as `.\.venv\Scripts\python.exe`; it does not depend on activating the environment or installing WSL, Docker, Bash, or Linux services.
- Exclusion checks cover representative `.env`, local configuration, `runtime/profiles/private.json`, database sidecars, and generated drafts, while `tests/fixtures/contracts/` and `config/app.example.json` remain includable. The `runtime/` example is defense in depth; the configured data root must still be outside the repository.
- The ownership map assigns `storage/` to DATA-01 and operational `orchestration/` behavior to RUN-01; it does not claim these exist or work.

**Tests and native Windows verification.** Use installation/import smoke checks and an exclusion-pattern check, not empty tests for package files. On native Windows, record OS, PowerShell and Python versions, dependency resolution, package import, and `ZoneInfo("Europe/Berlin")` success. A Linux installation is supplementary evidence only. No live-service test applies.

**Dependencies and unresolved decisions.** No component/story prerequisite. Resolve Python release, package/build backend, pin/lock mechanism, and minimal dependencies here. Proposed test runner: standard-library `unittest`; a different free runner is acceptable if pinned/documented and all commands are updated. Do not select an ORM or vector store.

**Migration/configuration impact and handoff.** This creates the first package baseline; no database/data migration. Record exact versions, owned paths, installation evidence, exclusions and import side effects in the component handoff. Leave actual Windows checks pending if that environment is unavailable.

<a id="fnd-01-s02"></a>
## FND-01-S02 — Define versioned primitives, state domains, and error contracts

**Objective and linked requirements.** Give all shared records consistent identity, time, unknown-value, serialization and failure semantics. Direct: [R03][requirements], [R14][requirements], [R15][requirements]. Supporting contract traceability: [R04][requirements], [R16][requirements]. Source: blueprint §§4–5, 8–10.

**Inputs, outputs, and owned files/modules.** Inputs: global conventions and baseline states/errors in the blueprint. Outputs: common typed values, independent enums, safe validation/error records, version rules, and reusable schema definitions. Owns `contracts/base.py`, `contracts/primitives.py`, `contracts/enums.py`, `contracts/errors.py` under `src/job_automation/`; `schemas/v1/common.schema.json`; corresponding `tests/contracts/test_primitives.py`, `test_errors.py`, and synthetic primitive fixtures; serialization/compatibility documentation in `docs/components/FND-01.md`.

**Implementation tasks.**

1. Define schema version placement and unsupported-version behavior for every independently persisted/exchanged record, including each member of paired contracts. Separate schema versions from profile, policy, input, normalizer, prompt, model, template and artifact versions.
2. Define local UUID identity types, opaque remote/provider strings, source identity `(provider, board_id, source_posting_id)`, revision/hash references, UTC machine-event values, precision-preserving candidate dates, and explicit nullable/empty collection handling. Keep hashes distinct from permanent identities.
3. Define all eight state domains independently: pipeline stage, hard criterion, assessment disposition, posting availability, application progress, sync operation, generation processing, and document approval. Preserve the blueprint's value sets, including `unknown`, `not_seen`, `retry_wait`, `upload_pending`, and `ready_for_review`; document wire values versus Salesforce display mappings.
4. Define structured `ValidationIssue` and classified error results with safe messages and field paths. Distinguish validation, missing configuration, permission/authentication, rate limit, transient network/service, context budget, model output, capacity, and permanent unsupported input. Document which may be recoverable; runtime retry limits/backoff remain with their owning components.
5. Set serialization and strictness rules: enum values, UUID text, UTC rendering, numeric/decimal precision, unknown fields, missing versus explicit null, and schema format validation. Proposed: reject incompatible types without lossy coercion and reject unsupported schema versions clearly.
6. Document compatible additive versus incompatible changes. Require updated schema/fixtures and recorded versions for additive changes; require a consumer/migration plan and blueprint decision for incompatible meaning changes. Do not implement a migration engine.

**Acceptance criteria with concrete examples.**

- A local ID such as `11111111-1111-4111-8111-111111111111` validates; `not-a-uuid` produces an identity field error. Provider ID `"00042"` round-trips as that string, without becoming `42`. Salesforce IDs are separate remote references.
- A machine event serialized as `2026-10-27T10:00:00+00:00` is UTC and offset-aware; a naive `2026-10-27T10:00:00` fails. The implementation documents whether another explicit offset is normalized or rejected. Candidate month `2021-05` stays month precision, without an invented day/time.
- `null`, `false`, `0`, and `[]` retain distinct meanings wherever allowed. A nullable salary amount does not become zero; a null fact collection does not become known-empty.
- Assessment `rejected`, availability `unavailable`, and application progress `Rejected` remain separate fields/types. A fixture cannot use `upload_pending` as a document approval state.
- A malformed field yields a contract/field path and stable error code without echoing a synthetic secret marker from the offending payload. A model-output error has no automatic mapping to an eligibility rejection.

**Tests and native Windows verification.** Exercise valid/invalid primitives, round trips, enum-domain misuse, schema version rejection and error redaction. Run them on native Windows with Unicode fixture text, verify UTC serialization and Berlin timezone lookup, and record results separately from Linux. No database or service is required.

**Dependencies and unresolved decisions.** Depends on S01. Resolve validation/schema library and dialect, schema identifiers, decimal/date encoding, version compatibility policy, exact error wire values, and strictness here before consumers freeze contracts. UUID generation and hash algorithms may be proposed/documented; identity matching and production hash computation belong to later components.

**Migration/configuration impact and handoff.** Creates version-1 shared conventions, with no persisted records to migrate. Record selected wire formats, representable nulls, schema-only versus Python-only checks, state ownership and change discipline. Consumers must use these definitions rather than invent alternate enums.

<a id="fnd-01-s03"></a>
## FND-01-S03 — Formalize profile, policy, and evidence contracts

**Objective and linked requirements.** Represent candidate truth, desired-job criteria, and evidence references separately, ready for both context strategies. Direct: [R03][requirements], [R15][requirements]. Supporting contract traceability: [R01][requirements], [R06][requirements], [R11][requirements]. Source: blueprint §4/C01, C02, C08 and §5.

**Inputs, outputs, and owned files/modules.** Inputs: common types from S02 and synthetic candidate/job evidence only. Outputs: C01 `ProfileSnapshot`, C02 `SearchPolicy`, and typed C08 candidate/job evidence variants. Owns `contracts/profile.py`, `contracts/policy.py`, `contracts/evidence.py`; `schemas/v1/C01*.schema.json`, `C02*.schema.json`, `C08*.schema.json`; `tests/contracts/test_profile_policy_evidence.py`; fixtures in `tests/fixtures/contracts/C01/`, `C02/`, `C08/`. These contract files do not implement `profile/` or `policy/` services.

**Implementation tasks.**

1. Define C01 candidate/profile identities, approval metadata, explicit eligibility facts, and approved evidence records: fact IDs, kinds, parent role/project references, precision-aware dates, claims/skills/metrics, provenance and allowed uses. Distinguish unknown eligibility from explicit denial.
2. Define C02 policy version, regions, role/skill aliases, hard criteria, preferences, exclusions, missing-information behavior, relevance configuration and selected primary `json|rag` strategy. Use typed criterion shapes; do not implement alias conflict resolution, matching, policy fingerprinting, or thresholds.
3. Define a discriminated C08 union: candidate references require `profile_version` and `fact_id`; job/employer references require posting revision, field/path and quotation or source span. Do not accept an untyped string as evidence.
4. Provide related synthetic snapshots and policies illustrating separate candidate capability and preferences, approved allowed uses, month precision and unknown facts. Label every example as fictitious.

**Acceptance criteria with concrete examples.**

- A synthetic policy preferring German-language jobs does not add German proficiency to a candidate snapshot whose proficiency is unknown. Both records round-trip independently.
- A synthetic role with start month `2021-05`, an approved fact, parent role ID and provenance validates without fabricating the first day of the month.
- A candidate C08 reference with `fact_id` but no `profile_version` fails at that field; a job C08 reference with a posting revision but neither quotation nor span fails. Correctly shaped references validate without claiming that stored evidence exists or is truthful.
- A policy with `primary_context_strategy: "rag"` validates; `"automatic-agent"` fails. A missing required criterion value fails structurally; choosing what the criterion should be is not part of this story.
- Fixtures demonstrate `allowed_uses` and approval metadata; validation never approves imported facts or promotes external job text into candidate facts.

**Tests and native Windows verification.** Run typed/schema shape checks, evidence variant tests, null/date round trips, and Unicode provenance/quotation fixtures. On native Windows, load the fixtures through an explicit interpreter from a repository path containing spaces and non-ASCII characters. Do not contact a candidate data store or build either context strategy.

**Dependencies and unresolved decisions.** Depends on S02. Resolve exact fact/criterion union variants, approval metadata shape, allowed-use vocabulary, precision encoding, and evidence discriminator/quotation/span representation within FND-01. Actual facts, languages, eligibility, target criteria and inclusion decisions remain with PROFILE-01/POLICY-01; reference resolution and factual validation remain downstream.

**Migration/configuration impact and handoff.** Introduces C01/C02/C08 version-1 schemas and examples only. No user profile import or live policy activation. Record schema versions, field semantics, fixture IDs and consumers; keep real candidate evidence out of the handoff.

<a id="fnd-01-s04"></a>
## FND-01-S04 — Formalize source, posting, and identity contracts

**Objective and linked requirements.** Establish the common representation and provenance needed for heterogeneous postings without fetching, normalizing, deduplicating, or closing jobs. Direct: [R03][requirements], [R15][requirements]. Supporting contract traceability: [R02][requirements], [R04][requirements], [R09][requirements]. Source: blueprint §4/C03–C07 and §5.

**Inputs, outputs, and owned files/modules.** Inputs: S02 types and hand-authored synthetic source shapes. Outputs: C03 `SourceConfig`, C04 `FetchManifest`, both C05 `RawPosting`/`SourceJobDraft` records, C06 `NormalizedPosting`, and both C07 `CanonicalJob`/`PostingRevision` records. Owns `contracts/sources.py`, `contracts/postings.py`, `contracts/identity.py`; C03–C07 schemas; `tests/contracts/test_source_posting_identity.py`; corresponding fixture directories. `sources/`, `ingestion/` and `identity/` implementations remain unowned by this story.

**Implementation tasks.**

1. Define C03 provider/board/source keys, acquisition method, URLs, access/attribution rules, request policy, enabled status and complete-board/filtered-feed/search inventory semantics. Synthetic sources use non-live example addresses and are disabled.
2. Define C04 run/scope identities, start/end events, pagination/cursor progress, raw references, observed posting identities and complete/partial/failed outcome. Keep inventory scope semantics separate from successful pagination; completing a search-result page sequence does not make it a complete board inventory.
3. Define C05 raw references/hashes, source identities, fetch events, original fields and source-mapped candidate fields. Permit malformed upstream data to be represented as raw evidence; require C06 structural validity only at the normalized boundary.
4. Define every C06 field from §4, including schema/normalizer versions, raw lineage, company hints, title/description, separate source/application URLs, structured locations preserving original text, workplace type, separate remote restrictions, employment type, compensation, advert language versus required proficiency, source dates versus observation time, and field provenance.
5. Define C07 stable canonical/company mappings, linked source postings, revision identities/hashes, first/last seen, availability, alternate/prior URLs and merge/split evidence. Represent unresolved company mapping explicitly where needed; do not invent a company match.
6. Document scoped source uniqueness and the no-ID conservative URL fallback representation. Record fallback method/evidence; delegate actual URL normalization, matching, content hashing, merging and disappearance inference to their owners.

**Acceptance criteria with concrete examples.**

- Synthetic postings `(provider-a, board-1, "42")` and `(provider-a, board-2, "42")` are distinct source keys. The same tuple is the same key in a pure comparison test; no durable uniqueness guarantee is claimed.
- Raw data lacking a title remains representable in C05 with a raw reference. The equivalent C06 payload fails with a `title` issue, preserving access to raw provenance. An invalid salary object fails without replacing it with zero.
- A C06 example has locations in Berlin and Hamburg, `workplace_type: "remote"`, remote eligibility restricted to Germany, and no closing date. It round-trips with both locations and restrictions intact and deadline null.
- Compensation examples distinguish EUR/month employer-provided pay from EUR/year estimates, with minimum/maximum, period, gross/net unknown when absent, and provenance. No comparison or annualization occurs. German advert language does not become a candidate language proficiency fact.
- A partial manifest with a continuation cursor and a completed search-only manifest both validate as observations. Their fields do not assert that missing jobs are unavailable; runtime inference is outside FND-01.
- Two revisions of one synthetic canonical UUID retain different content hashes and prior application URLs. Changing title or description does not require a new canonical ID in the contract. This demonstrates representation, not a deduplication algorithm.

**Tests and native Windows verification.** Validate positive/negative fixtures for each record in the paired contracts, source-key preservation, missing title/identity, invalid types, compensation units, location collections and raw provenance. Use two different hand-authored source shapes and separately authored C06 examples, without building a mapper. On native Windows, verify Unicode locations, JSON round trips and raw path/reference serialization using a path containing spaces and umlauts; URLs must not undergo filesystem slash conversion.

**Dependencies and unresolved decisions.** Depends on S02. Resolve exact location/compensation/provenance types, raw reference format, manifest scope representation, and URL-fallback identity envelope. Actual fallback normalization rules, employer matches and availability thresholds belong to SOURCE/IDENTITY; providers and permission checks are not selected here.

**Migration/configuration impact and handoff.** Adds version-1 C03–C07 schemas and disabled examples. No source registration in a runtime registry, network calls, storage layout migration, or adapter code. Document how DATA-01 and INGEST/IDENTITY will consume identity, provenance and completeness fields.

<a id="fnd-01-s05"></a>
## FND-01-S05 — Formalize context, model-call, and assessment contracts

**Objective and linked requirements.** Make rules-only and model-assisted assessment representable through one shared output contract, with explicit context strategy and failure metadata. Direct: [R03][requirements], [R15][requirements]. Supporting contract traceability: [R05][requirements], [R06][requirements], [R07][requirements], [R13][requirements]. Source: blueprint §§3–5/C09–C11.

**Inputs, outputs, and owned files/modules.** Inputs: S03/S04 contracts and synthetic job/profile/evidence references. Outputs: C09 `ContextBundle`, both C10 `ModelCall`/`ModelResult`, and C11 `Assessment`. Owns `contracts/context.py`, `contracts/models.py`, `contracts/assessment.py`; C09–C11 schemas; `tests/contracts/test_context_model_assessment.py`; corresponding fixtures.

**Implementation tasks.**

1. Define C09 strategy, profile/job revision, ordered facts, mandatory context, selected/retrieved IDs, query/index/settings versions, token budget/measurement and warnings. Document fields applicable only to RAG versus JSON. Preserve mandatory eligibility/chronology separately so downstream retrieval cannot treat all context as optional top-k output.
2. Define C10 operation type, model identifier/digest, prompt/output-schema versions, settings, context limit, input fingerprint, result/error, timing and available usage. Keep absent usage unknown. Do not include credentials or arbitrary execution/tool authority in request shapes.
3. Define C11 job/revision and profile/policy versions, method `rules|llm`, per-rule `pass|fail|unknown` with typed evidence, relevance decision, optional score with a documented scale, gaps/unknowns/reasons and `eligible|review|rejected` disposition.
4. Specify record-local metadata consistency: rules-only assessment permits null context/model/prompt fields; LLM assessment requires the metadata actually used. Separate a model error from an assessment decision. Document downstream obligations for hard-failure precedence, common profile inclusion rules, JSON overflow and comparison-run publication.

**Acceptance criteria with concrete examples.**

- A rules-only C11 fixture with an unknown salary criterion, review disposition and null model/context/prompt metadata validates. An LLM fixture missing its model/prompt or context reference fails clearly.
- JSON and RAG C09 examples reference the same synthetic profile version and posting revision. The RAG example records retrieval settings and selected fact IDs; the JSON example records the full eligible fixture set. Passing these fixtures does not prove a context builder exists.
- A synthetic JSON budget overflow is representable as a `context_budget` error. It is neither a successful truncated JSON bundle nor an automatic change of strategy.
- Model output/timeout examples use distinct classified errors, not a fabricated rejected assessment. A result with unavailable token usage retains null rather than reporting zero.
- An optional score of `75` accompanied by a declared `0–100` ranking scale is representable; a score without a defined scale fails under the selected contract rule. It is not described as offer probability.
- Text such as “ignore prior instructions” in a synthetic job quotation remains string data after parsing; parsing does not execute it, fetch URLs, or alter candidate facts.

**Tests and native Windows verification.** Test schema and typed validation, conditional LLM metadata, score/scale constraints, strategy values, error/result consistency, and inert untrusted text. Run on native Windows with no model service installed/running. Record that hardware fit, model quality, token counting, retrieval correctness and prompt safety during inference remain unverified downstream behavior.

**Dependencies and unresolved decisions.** Depends on S03/S04. Resolve result/error union shape, context version applicability, score-scale representation, model settings types and exact required LLM metadata. Do not select models, context sizes, retrieval parameters or ranking thresholds; MODEL-02, CONTEXT and MATCH own those choices.

**Migration/configuration impact and handoff.** Adds C09–C11 schemas and examples only. No model downloads, endpoint calls, prompt execution or assessment storage. Record conditional fields and errors for LLM-01, CONTEXT-01–04, MATCH-01/02 and EVAL-01.

<a id="fnd-01-s06"></a>
## FND-01-S06 — Formalize sync, generation, artifact, and run-summary contracts

**Objective and linked requirements.** Represent durable-work identities, machine/candidate ownership, frozen inputs and separate delivery/approval states without implementing work execution. Direct: [R03][requirements], [R15][requirements]. Supporting contract traceability: [R08][requirements], [R09][requirements], [R10][requirements], [R11][requirements], [R12][requirements], [R16][requirements]; C15 also provides the future boundary for deferred [R17][requirements]. Source: blueprint §§4–5/C12–C15.

**Inputs, outputs, and owned files/modules.** Inputs: S02–S05 types and synthetic work records. Outputs: C12 `SyncOperation`, C13 `GenerationRequest`, both C14 `DraftDocument`/`Artifact`, and C15 `RunSummary`. Owns `contracts/sync.py`, `contracts/generation.py`, `contracts/artifacts.py`, `contracts/runs.py`; C12–C15 schemas; `tests/contracts/test_work_records.py`; corresponding fixtures. No storage tables or Salesforce metadata are owned here.

**Implementation tasks.**

1. Define C12 operation/canonical IDs, payload version/fingerprint, typed machine-owned payload, attempt/retry metadata, state and remote acknowledgment/record ID. Include an explicit ordering/version reference for future stale-write prevention; do not implement a queue or retries. Keep candidate status, notes, overrides and follow-ups outside the update payload. Creation defaults belong to Salesforce configuration.
2. Define C13 stable local/request and remote references, job reference, document type, language/template/context options, `allow_unavailable_job` default false, timestamps/state, frozen inputs once claimed, result references and concise errors. Document the distinction between local UUIDs, UI-origin request keys and Salesforce record IDs; preserve originating identity rather than pretending all remote IDs are UUIDs.
3. Define C14 typed sections/claims with C08 candidate/job references, review warnings/subjective text, request/input/model/template versions, local artifact paths, format/hash/version, remote file/version IDs, delivery status and separate human approval. Include correlation fields needed for later upload reconciliation, without writing an uploader.
4. Define C15 run identity, start/end/status, source/stage counts, new/changed/duplicate/eligible/review/rejected counts, errors and pending work. Document every counter's unit and phase so source postings, revisions and canonical jobs cannot be silently added together.
5. Document the identity/ownership obligations for consumers: retries preserve operation/request identity; deliberate regeneration uses a new request; delivery does not approve a document; runtime ordering, atomicity, recovery and notification transitions remain downstream.

**Acceptance criteria with concrete examples.**

- Two C12 examples for the same job carry distinguishable payload versions and stable operation IDs. A machine-owned update payload containing candidate notes or application status fails the selected typed payload contract. No test claims to prevent an old network write in this story.
- A pending C13 example with omitted `allow_unavailable_job` reads as false. A claimed/running example records frozen job/profile/policy/context configuration versions. Missing required frozen-input fields fail a record-local check; no request is actually claimed or persisted.
- Two fixtures illustrating attempts for one request retain its ID; a deliberate regeneration example has a distinct request ID and can link its predecessor. A single-record validator is not claimed to enforce uniqueness across stored requests.
- A C14 artifact can be delivered and still have approval `draft`. An `upload_pending` request can reference a local artifact with no remote file ID. A `ready_for_review` example includes delivery evidence for the advertised artifact; access to a real remote file is not checked here.
- A candidate claim cites a candidate C08 reference; an employer claim cites the frozen posting. Reviewable subjective text has an explicit warning/marker, not fabricated supporting evidence. Valid reference syntax does not establish truthful paraphrasing.
- A C15 example can report three source postings corresponding to two canonical jobs, with separate units, without asserting five jobs. Negative counts fail; empty, partial and failed run summaries remain representable without inventing successful processing.

**Tests and native Windows verification.** Validate ownership payload boundaries, record-local state/metadata consistency, default false, typed claim references, delivery/approval separation, counts and versions. On native Windows, round-trip a synthetic artifact path such as `C:\Users\Example\Job Automation Daten\Entwürfe\CV.docx`, including correct JSON escaping. Do not require the artifact to exist, render a document, create a database, poll Salesforce or send notifications.

**Dependencies and unresolved decisions.** Depends on S03–S05. Resolve ordering token representation, request-origin key mapping, frozen-input envelope, delivery evidence shape and counter units. Physical uniqueness/order guarantees belong to DATA-01/SYNC-01; request lifecycle to GEN; Salesforce field names/permissions to SF. No Phase 1 runtime or Phase 2 story is created by defining these contracts.

**Migration/configuration impact and handoff.** Introduces schemas only, without tables, migrations, remote fields or work records. Record machine/user ownership, version references, count units, and representational limits for downstream implementation.

<a id="fnd-01-s07"></a>
## FND-01-S07 — Publish service-independent interface boundaries

**Objective and linked requirements.** Let later components implement against stable typed interfaces and demonstrate compatibility using isolated fakes. Direct: [R03][requirements], [R14][requirements], [R15][requirements]. Source: blueprint §4 interface table and §6/FND-01. Other requirements are supported only through the linked contracts.

**Inputs, outputs, and owned files/modules.** Inputs: C01–C15 and shared errors from S02–S06. Outputs: typed boundary declarations, small auxiliary request/result types, interface documentation, and test-only conformance fakes. Owns `contracts/interfaces.py` or a documented split beneath `contracts/interfaces/`; `tests/contracts/test_interfaces.py`; `tests/fakes/`; auxiliary schema definitions where those records are exchanged/persisted. Concrete adapter interfaces/operational behavior remain with SOURCE-02; FND-01 defines the shared service-independent signature they must honor.

**Implementation tasks.**

1. Define final language-specific signatures and error behavior for every boundary below. Proposed: Python protocols with explicit request/result objects, no service initialization in constructors, and a consistent synchronous convention for the initial single-worker design. Record the choice rather than implying it is user-confirmed.
2. Define only the minimum auxiliary shapes needed by those signatures: page/cursor results, existing-identity lookup view and match decision, requirement inputs, embedding vectors/metadata, frozen input reference, and acknowledgment/classified error envelopes. Version any independently exchanged/persisted auxiliary record.
3. Keep callers dependent on contracts, not HTTP clients, SQLite connections, provider SDKs, Salesforce record dictionaries, or model-runtime classes. State where a consumer must resolve references and enforce business rules.
4. Add deterministic fakes under tests only. Verify input/output contracts and error propagation; do not ship a fake as a production default or build a fake end-to-end pipeline.

| Required boundary | Contract-level input → output |
|---|---|
| Adapter | C03 + cursor → page of C05 raw postings + continuation metadata; raw posting → C05 source draft |
| Normalizer | C05 draft + raw provenance → C06 or validation issue |
| Identity resolver | C06 + existing identity mapping view → canonical ID + revision/match decision |
| Rule evaluator | Canonical revision + C02 + explicit candidate facts → rules-only C11 |
| Context selector | Job requirements + C01 + strategy + budget → C09 or budget/retrieval error |
| Model provider | Structured generation call → C10 result; texts + embedding model → vectors with model metadata |
| Assessor | Rule outcomes + job revision + C09 → C11 |
| Salesforce gateway | Typed operation + stable identity → acknowledgment or classified error |
| Generator | Frozen request + context + template/language options → C14 draft |
| Renderer/delivery | Validated draft → local C14 artifact; artifact/delivery operation → remote acknowledgment |

**Acceptance criteria with concrete examples.**

- A test-only adapter returns one synthetic raw posting and a continuation cursor; a fake normalizer returns either a valid C06 or a typed issue. No HTTP calls or real field mapping occur.
- A fake model provider can return a classified transient error and a separate embedding response containing vectors and model identity. No caller must pretend a generation response is an embedding response.
- A fake context selector can return `context_budget`; the caller can distinguish it from invalid model output and from missing configuration.
- A fake gateway acknowledgment preserves the supplied operation identity and remote ID separately. Fake renderer and delivery outputs are distinct: an artifact path is not proof of remote delivery.
- All ten table rows have signatures, documented failure types and conformance coverage. Importing those declarations needs no service, account, GPU, database, source registry or renderer.

**Tests and native Windows verification.** Use signature/type conformance checks and small contract calls against fakes. Run the same checks on native Windows with unavailable external services; verify import/call behavior has no network, shell or persistence side effects. Record fake integration separately from live service checks. Runtime business correctness is not part of conformance.

**Dependencies and unresolved decisions.** Depends on S03–S06. Resolve protocol versus abstract class, synchronous/asynchronous convention, exception versus result-union policy, cursor typing and auxiliary records here. Reconcile SOURCE-02 and future RUN-01 ownership in the handoff. There is no requirement to implement those components first.

**Migration/configuration impact and handoff.** Adds interfaces and test fakes only. Record public signatures, auxiliary versions, side-effect expectations, and which component supplies each implementation. Interface changes after this baseline follow the shared-contract change discipline.

<a id="fnd-01-s08"></a>
## FND-01-S08 — Load non-secret configuration through a native Windows CLI

**Objective and linked requirements.** Provide the FND-01 acceptance path: a native PowerShell invocation loads validated configuration without external accounts and respects explicit Windows paths/data boundaries. Direct: [R14][requirements], [R15][requirements]. Supporting: [R03][requirements] for configuration validation. Source: blueprint §§3, 6/FND-01, 9.

**Inputs, outputs, and owned files/modules.** Inputs: explicit config/data paths, non-secret examples, S02 error types and optional C02/C03 example references. Outputs: typed foundation configuration, resolved runtime paths and a concise safe CLI result. Owns `src/job_automation/configuration.py`, `__main__.py`, and `cli.py`; `config/app.example.json`; any explicitly synthetic C02/C03 example files; foundation configuration schema; `tests/test_configuration.py`, `tests/test_cli.py`; README PowerShell instructions. RUN-01 owns future pipeline commands.

**Implementation tasks.**

1. Define the minimum app configuration: configuration version, absolute runtime data root, display timezone, and references needed by the skeleton. Separate settings from C01 candidate facts and C02 search policy. Proposed format: JSON, with explicit `--config` and optional `--data-root` override; no automatic discovery of local secret files.
2. Specify configuration precedence and base paths. Proposed: CLI override > config value > a documented `$env:LOCALAPPDATA`-derived default for data root only. Resolve a relative configuration file against the invocation directory once; resolve relative referenced files against the configuration file's parent. Require the resulting runtime data root to be absolute and outside the repository. Do not expand arbitrary shell expressions.
3. Resolve separate child paths for profile evidence, raw snapshots, database, indexes, artifacts, logs and backups using `pathlib.Path`. Configuration loading need not create them or validate future backup policy. Do not infer that a local backups path covers disk failure.
4. Provide `--help`, `--version`, and a proposed `config check` command. Loading configuration must not fetch sources, open/create storage, install/contact Ollama, inspect/mutate Salesforce, render files, or start workers. Proposed exits: 0 success, 2 invalid/missing configuration; document the final choice.
5. Print only an allowlisted summary, such as configuration version and validation result. Do not dump arbitrary settings, private facts, raw input or secret-bearing errors. If future service sections are represented, use non-secret references, disabled examples and optional/unconfigured services; no real endpoint or credential is required. Any model endpoint example must follow the blueprint's loopback-only baseline, without a health call.
6. Document native PowerShell invocation with quoted paths, `Join-Path`, `$env:LOCALAPPDATA`, an explicit interpreter and correct JSON backslash escaping. Do not globally convert slashes in URLs/Markdown links.

**Acceptance criteria with concrete examples.**

- Given a valid synthetic config and `--data-root "C:\Users\Example\Job Automation Daten\Bewerbungen ä"`, `config check` exits 0 without credentials, services or outbound traffic. The resolved profile/raw/database/index/artifact/log/backup paths sit beneath that data root, and no runtime files are created by the check.
- Calling from another working directory with an absolute `--config` resolves a referenced `policy.example.json` against the config file's directory, not the new working directory.
- A relative data root, a root inside the repository, an absent config file and an invalid config type each give a nonzero exit and a useful error without traceback/payload disclosure. Syntactically correct outside paths may be checked without creating or requiring the eventual directory.
- JSON `"C:\\Users\\Example\\Job Automation Daten\\Bewerbungen ä"` decodes to the intended Windows path. A source URL containing `/` remains a URL; a Markdown link is not rewritten.
- An invalid setting containing synthetic `SECRET_SENTINEL` does not appear in stdout/stderr. The check never reads a real candidate profile merely to validate its configured reference.
- Help exposes only implemented foundation commands; a `search`, `sync`, or `generate` invocation cannot silently run a placeholder pipeline.

**Tests and native Windows verification.** Test precedence, relative-reference bases, absolute/outside-repository data-root validation, nonexistent files, malformed JSON, redacted errors, and CLI exit codes. Use subprocess smoke checks to observe no file creation or service calls. Native Windows checks must use paths containing spaces and non-ASCII characters, run from a different directory, and invoke `.\.venv\Scripts\python.exe` without environment activation. Portable path tests and Linux checks do not substitute for this execution.

**Dependencies and unresolved decisions.** Depends on S01/S02; coordinate with S03/S04 if policy/source example references are included. Resolve format, key names, precedence, config-relative rules, data-root containment policy including Windows path aliases, CLI syntax/exit codes, and whether the optional LOCALAPPDATA default is offered. Credential storage/authentication belongs to SF-02/SFCLIENT-01, endpoint runtime setup to MODEL-01. Do not block the skeleton on those services.

**Migration/configuration impact and handoff.** Creates the first application config version and documented defaults; no secrets or runtime data are added to the repository. Record final commands, precedence and safe output, path behavior, tests and Windows results. No application execution beyond foundation loading is implied.

<a id="fnd-01-s09"></a>
## FND-01-S09 — Verify the complete contract baseline and hand off FND-01

**Objective and linked requirements.** Demonstrate the declared FND-01 acceptance and make the exact shared baseline usable by the next implementation chat. Direct: [R03][requirements], [R14][requirements], [R15][requirements]. Source: blueprint §§4, 6/FND-01, 7–9.

**Inputs, outputs, and owned files/modules.** Inputs: all S01–S08 code, schemas, fixtures, decisions and check results. Outputs: complete contract catalog, consistent schema artifacts, offline validation evidence, native Windows evidence or explicit pending status, and component handoff. Owns `schemas/README.md`, `tests/fixtures/contracts/README.md`, fixture manifest/catalog, `tests/contracts/test_contract_catalog.py`, any minimal schema export/check helper under `contracts/`, and completion of `docs/components/FND-01.md`. Coordinate fixes in previously owned files with their story; do not create another schema implementation.

**Implementation tasks.**

1. Inventory C01–C15 and every paired record: C05 raw/draft, C07 canonical/revision, C10 call/result and C14 draft/artifact. Include their dependencies, auxiliary records, schema IDs/versions, public imports, fixture paths, and owning story. Ensure all schemas resolve references locally without fetching remote definitions.
2. Validate positive fixtures against both typed parsing and JSON schemas. Include negative fixtures for missing required fields, wrong types, enum misuse and version errors for every contract, plus the specific semantic boundaries in S02–S06. Document any Python-only constraints rather than claiming schema parity for checks the schema cannot express. Confirm test discovery includes the nested contract suite and record the test count; a successful command that discovers no contract tests is not acceptance evidence.
3. Establish a deterministic schema generation/check process using the selected implementation as source of truth. Detect stale checked-in schema artifacts; keep serialization examples and schema versions aligned. Record intentional permissiveness where raw C05 data must be retained.
4. Run service-independent interface checks and the CLI configuration smoke test. Inspect fixture contents for real candidate facts, credentials, live accounts and personal prompts. Use only synthetic IDs, evidence and addresses.
5. Complete the native Windows checks below and capture actual environment/commands/results. The implementation can be marked `implemented` with specified checks pending; use `verified` only after declared acceptance, including native PowerShell loading, is demonstrated.
6. Write the component handoff with component/story status, objective, linked requirements, dependencies and versions, changed files, contracts/interfaces, choices versus baseline requirements, commands/results, limitations, pending integration and next owners. Record live service checks as not applicable to FND-01, not passed.

**Acceptance criteria with concrete examples.**

- The catalog includes all fifteen contract IDs and each paired record; every positive fixture validates, and every negative fixture fails for its documented reason. For example, an LLM assessment missing prompt metadata fails while the rules-only counterpart with null metadata succeeds.
- A round trip preserves a provider ID with leading zeros, an unknown salary, a known-empty list, month precision, Unicode quotation text and the separation between delivery and approval. Any normalization in serialization is documented and intentional.
- Schema checks and fake conformance run with network access unavailable after dependencies are installed. No source fetch, Salesforce mutation, database migration, model call or artifact rendering is required.
- A native PowerShell `config check` succeeds in a path containing spaces and non-ASCII characters without account credentials. The handoff contains actual output/exit status and Windows/Python versions, or clearly leaves verification pending.
- Handoff acceptance refers to FND-01 only. It does not label the entire G0 gate, deterministic pipeline, Phase 0, or R03's normalization workflow complete.

**Tests and native Windows verification.** Run the integrated contract/schema suite once after constituent checks pass, then the native setup/configuration scenarios. Repeat only for changed artifacts or unresolved failures. The proposed command recipe below becomes executable documentation during implementation; it has not been run by this planning task. Record unit/contract, fake integration, native Windows and live-service statuses separately.

**Dependencies and unresolved decisions.** Depends on S01–S08. No live services or other components are prerequisites. Resolve the authoritative schema export/check command, final fixture catalog format and evidence location. Any unresolved FND serialization/signature choice must be settled before publishing a verified baseline; downstream choices stay assigned to their owners.

**Migration/configuration impact and handoff.** No live data migration. Publish version-1 contracts and compatibility rules, safe setup examples and the handoff. Next independent owners include DATA-01, POLICY-01, SOURCE-01 and LLM-01 (with fakes); SF-00 and MODEL-01 remain separate setup components. Their availability does not expand this story.

## Native Windows verification recipe for implementation

These commands are a proposed acceptance recipe, not existing application functionality or executed test evidence. S01 selects/pins the exact Python/dependency versions; S08 confirms the CLI syntax. Record literal tested paths and versions in the handoff. The examples use PowerShell syntax; Markdown/file ownership paths elsewhere use `/` notation.

1. Use a native Windows checkout at a path containing spaces and non-ASCII characters, for example `C:\Work\Job Automation Prüfung`. Use a separate data root under the user's local application data directory.
2. Create a virtual environment using the explicit installed Python executable selected in S01. Install the pinned foundation/test dependencies using the chosen lock workflow. Record the exact command; the editable installation below must not silently re-resolve unpinned dependencies.
3. Run the tests and configuration smoke commands with the virtual environment's explicit executable. Service credentials, model downloads and administrative org access must be absent/unnecessary.

```powershell
# Replace this with the actual executable selected and recorded in S01.
$basePython = 'C:\Path To Selected Python\python.exe'
$repo = 'C:\Work\Job Automation Prüfung'
Set-Location -LiteralPath $repo
& $basePython -m venv '.\.venv'
$python = Join-Path $repo '.venv\Scripts\python.exe'

# First execute S01's documented pinned-dependency installation command.
& $python -m pip install --no-deps --no-build-isolation -e .
& $python -c "import job_automation; from zoneinfo import ZoneInfo; print(ZoneInfo('Europe/Berlin'))"
& $python -m unittest discover -s '.\tests' -p 'test_*.py'

$config = Join-Path $repo 'config\app.example.json'
$dataRoot = Join-Path $env:LOCALAPPDATA 'Job Automation Prüfung'
& $python -m job_automation --help
& $python -m job_automation --version
& $python -m job_automation config check --config $config --data-root $dataRoot
$LASTEXITCODE  # Expected: 0

# Repeat with a different working directory and explicit config/interpreter paths.
Push-Location -LiteralPath $env:TEMP
try {
    & $python -m job_automation config check --config $config --data-root $dataRoot
    $LASTEXITCODE  # Expected: 0; same configuration-relative references
} finally {
    Pop-Location
}

# Missing configuration is a safe, observable failure.
$missingConfig = Join-Path $repo 'config\does-not-exist.json'
& $python -m job_automation config check --config $missingConfig --data-root $dataRoot
$LASTEXITCODE  # Proposed: 2; no secrets/payload dump
```

Also execute S08's relative/inside-repository data-root failures, malformed JSON, redaction, correct JSON path escaping, and no-side-effect checks on native Windows. Record stdout/stderr and exit codes without storing sensitive local values. Reboot/logged-out startup, Task Scheduler, GPU fit, rendering, real sources and Salesforce are outside this verification gate.

## Completion and decision record

Use this checklist in the future `docs/components/FND-01.md`:

- All nine stories report their owned files, input/output contract versions, acceptance evidence and remaining limitations.
- C01–C15, paired records, eight state domains, required error categories and all ten interface boundaries are covered; schemas and synthetic fixtures agree.
- Python/dependencies are pinned and native installation instructions are explicit. Configuration loading works without external accounts; runtime data and secrets remain outside source control.
- Each new technical choice is recorded as selected during implementation, with rationale, rather than retroactively called a user requirement. FND-owned unresolved choices are closed before `verified` status.
- Schema/typed validation, fake integration, native Windows checks and live-service applicability have separate results. No Linux or fake-only result is labeled native Windows or live verification.
- No downstream business workflow, storage engine integration, source access, Salesforce change, or Phase 2 automation is included. Any needed contract change follows the blueprint's change discipline.

Current planning result: **all stories PLANNED; no application code, schemas or fixtures implemented; no application tests or native Windows verification performed.** Document structure and links were checked during planning. The only file written by this planning task is `docs/stories/FND-01.md`.

[blueprint]: ../../IMPLEMENTATION_BLUEPRINT.md
[requirements]: ../../IMPLEMENTATION_BLUEPRINT.md
