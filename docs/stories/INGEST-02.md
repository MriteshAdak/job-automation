# INGEST-02 — Common normalization and validation

Status: **VERIFIED** · Planning date: **28 October 2026** · Completed: **28 October 2026** · Phase 0 · Scope: **INGEST-02 only**

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), v1.0. References below use requirements (§2), contracts (§4), correctness rules (§5), component ownership (§6), integration gates (§7), story/handoff instructions (§8), and native Windows conventions (§9). This is an ordered implementation plan, not an implementation or a verification report.

## Scope and repository evidence

**Objective:** turn heterogeneous C05 source-mapped drafts and their preserved raw provenance into deterministic, validated C06 postings, or structured issues that retain enough context for quarantine and later reprocessing. Direct requirement: **R03**. Supporting constraints: **R14** (native Windows), **R15** (untrusted text and safe diagnostics), and **R16** (inspectable failures). Source identity preservation supports R04 without implementing identity resolution.

**Inputs → outputs:** C05 `SourceJobDraft`, associated immutable `RawPosting`/capture metadata, mapping version and provenance, and explicit normalization settings → C06 `NormalizedPosting` plus warning issues, or no C06 plus blocking validation issues and a quarantine handoff. No candidate profile or search policy is an input.

**Excluded:** fetching/pagination/retries, adapter implementation, company/job deduplication, canonical IDs/revisions, availability/closure, eligibility filtering, keyword relevance, candidate authorization decisions, salary comparisons against policy, model inference, Salesforce, pipeline CLI/scheduling, and durable storage migrations. INGEST-02 defines quarantine content and routing; DATA-01 and RUN-01 own durable persistence and orchestration. No prerequisite component is silently implemented here.

Read the blueprint, [README](../../README.md), [schema instructions](../../schemas/README.md), [FND-01 handoff](../components/FND-01.md), [SOURCE-02 handoff](../components/SOURCE-02.md), and adjacent [INGEST-01 stories](INGEST-01.md). Inspected current posting/primitives/error/interface models, adapter result models, source mapping/manual adapters, Arbeitnow mapping, raw capture/storage readers, policy field declarations, and relevant fixtures/tests. No applicable repository or ancestor `AGENTS.md` was found; the checked user-level `.codex/AGENTS.md` is empty. README and blueprint §§8–9 provide the repository instructions.

| Current evidence | Consequence for this plan |
|---|---|
| FND-01 and SOURCE-02 handoffs report VERIFIED, including native Windows checks | Treat their recorded results as upstream evidence, not fresh INGEST-02 results. Both are direct catalog dependencies. |
| [Normalizer protocol](../../src/job_automation/contracts/interfaces.py) | Actual signature is `normalize(draft: SourceJobDraft) -> tuple[NormalizedPosting | None, list[ValidationIssue]]`. Preserve it using an injected provenance reader unless S01 records an explicit owner-approved interface change. |
| [C05/C06 models](../../src/job_automation/contracts/postings.py), schema 1.0 | C05 draft has a raw reference but no raw hash. C06 requires a hash, company name, title, nonempty cleaned description and source URL. Company absence is allowed by the mapper but not C06. |
| C06 unknown-value gaps | `locations` and `remote_eligibility_restrictions` default to `[]`; global semantics say empty means known empty. `JobCompensation` silently defaults currency to EUR and period to yearly. C06 source dates accept timestamps only. S01 must resolve these before dependent behavior is declared complete. |
| [Primitives](../../src/job_automation/contracts/primitives.py) and [base model](../../src/job_automation/contracts/base.py) | `UtcDatetime` is timezone-aware, but does not itself invoke `validate_utc`; the normalizer must actually convert to UTC. Models are frozen but nested dictionaries/lists remain mutable. Default Pydantic coercion is not a strict source-type check. |
| [SOURCE-02 mapping](../../src/job_automation/sources/adapters/mapping.py) | Vocabulary includes `title`, `company_name_hint`, `description`, URLs, `locations_raw`, `workplace_type_raw`, `employment_type_raw`, `compensation_raw`, `source_published_raw`, `source_deadline_raw`, plus `mapping_version` and `provenance`. It lacks standardized updated-date, remote-restriction, company-ID and advert-language inputs. Some fields are converted with `str()`, so validating mapped types alone cannot catch all original invalid types. |
| [Arbeitnow code](../../src/job_automation/sources/adapters/arbeitnow.py) and [fixtures](../../tests/fixtures/sources/arbeitnow/README.md) now exist | Earlier INGEST-01 planning says no provider adapter exists; that statement is stale for this snapshot. No SOURCE-03 component handoff is present. Do not infer live verification. Current mapping retains `remote` as a boolean, `job_types` as a list, attribution metadata, and `created_at` only in original fields because its unit/event meaning remains unresolved. |
| Mapping provenance is not uniformly original-field provenance | Arbeitnow passes an intermediate mapping dictionary through the common helper; some paths name intermediate fields and boolean/list overrides lack complete original paths. Missing/incorrect provenance needs an explicit mapping-owner decision, not invented source paths. |
| [Raw capture port](../../src/job_automation/sources/adapters/raw.py) | `capture(bytes)` returns reference/hash; `get(ref)` returns exact bytes. Parent CSV/API response and derived row/envelope are different captures. Only an in-memory sink is present at this boundary. |
| [Raw repository](../../src/job_automation/storage/repositories/raw_postings.py) | Looks up by source tuple and reads payload as text. It is not an immutable-observation-by-reference byte reader. Do not use it to re-encode text and claim exact-byte hash verification. |
| `ingestion/` and normalization tests do not yet exist | All INGEST-02 files below are proposed. Coordinate package creation with INGEST-01. The foundation `FakeNormalizer` invents sample values/hash/time; it proves interface shape only and is not production behavior to copy. |

## Required behavior and contract decisions

The user-confirmed requirement is common normalization with preserved raw input/provenance. The parsing rules, module names, issue codes, and contract changes below are **proposed technical choices**. S01 records their final versions once, before field-level implementation; future stories consume that decision rather than redesigning it.

### Unknowns, evidence and source precedence

| Situation | Required result / proposed policy |
|---|---|
| Absent optional scalar | `null`; enum fields use their explicit `unknown` member. Do not convert absence to zero, false, an empty string, EUR, yearly, Germany, or the current date. |
| Absent location/restriction collection | Unknown, distinct from an explicitly known empty collection. Proposed C06 change: nullable collections. This is a consumer-visible change requiring FND-01 version/reader agreement, not a silent schema 1.0 edit. |
| Missing company hint | Never infer it from a hostname or synthesize “Unknown company.” Until FND-01 decides whether this required field becomes nullable, emit a blocking missing-field issue. |
| Blank title or description after cleaning | Blocking issue and raw reference retained. Do not infer a title from description, URL, source ID or company. |
| Optional value with an unsupported but valid representation | Preserve original value by raw reference, leave normalized field unknown, and emit a warning. A wrong JSON type, corrupt provenance or structurally invalid value is blocking. |
| Conflicting explicit facts | Retain both evidence paths, issue a conflict, and avoid silently selecting a convenient fact. Proposed optional-field behavior: unknown plus warning; invalid compensation ranges remain blocking. |
| Unknown original fields | Preserve in C05; do not copy arbitrary keys into C06 or reinterpret them as instructions. Known mapped keys with unknown versions/shapes produce a visible unsupported-input issue. |
| Source field precedence | Use declared mapped fields and versioned mapping metadata. Do not search original provider payloads ad hoc for “better” facts. Original fields support traceability/type validation; provider extraction remains SOURCE-02/03 work. |
| Reprocessing | Same draft, exact raw snapshot, mapping metadata and normalizer settings/version produce identical values and ordered issues. `observed_at` comes from fetch time, never processing wall clock. |

C06 must preserve the exact `SourceKey` tuple, including leading zeros and case. Company IDs remain hints. URLs remain source/application facts, not identity decisions; do not remove query parameters, resolve redirects, fetch links, or manufacture an application URL from the source URL.

### Validation and quarantine boundary

Retain the current tuple protocol: a posting may accompany warnings only; any blocking issue means the posting is `None`. Never return `(None, [])`. Collect independent field failures in a deterministic order where safe, rather than only the first Pydantic error. Validate C05/C06 schema versions explicitly; the current base class's version string does not enforce compatibility by itself.

Use shared `ValidationIssue(field_path, code, message, severity)` for normalizer results. Propose an INGEST-02-local, versioned quarantine handoff containing: draft/raw reference, trusted raw hash if available, source key if usable, mapping and normalizer versions, fetch/observation time, ordered issues, and upstream input/record/line locators when available. A missing trusted hash remains null in the handoff; never fabricate one. This envelope is not a C06 posting and cannot enter identity/matching as one. A caller may wrap it in a durable receipt; it need not duplicate raw payloads.

| Proposed stable code | Severity and routing | Example |
|---|---|---|
| `missing_required_field` / `empty_after_cleaning` | Error → quarantine | Title absent; description contains only discarded script content. |
| `invalid_field_type` / `invalid_value` | Error → quarantine | Location object where an allowed list/string is required; boolean salary; negative amount; impossible date. |
| `raw_reference_unresolved` / `raw_provenance_mismatch` / `raw_hash_mismatch` | Error → no C06, inspectable handoff | Draft and raw identity/ref differ or bytes fail integrity verification. |
| `unsupported_mapping_version` / `unsupported_schema_version` | Error → quarantine | Unknown mapped-field semantics; no permissive fallback. |
| `unsupported_representation` / `ambiguous_value` | Warning → optional value unknown | Weekly salary without an agreed enum representation; ambiguous numeric locale/date. |
| `conflicting_values` | Warning → optional field unknown, except blocking structural invariants | Hybrid and onsite both explicitly asserted without precedence evidence. |
| `provenance_missing` / `provenance_invalid` | Blocking for a populated source-derived field until traceable | Path claims to reference an original field that does not exist. |

Ordinary absence of optional facts need not create noisy warnings. A supplied value that cannot be represented does. Codes and field paths are stable API data; human messages are safe templates without raw descriptions, URLs with secrets, filesystem paths, tokens, or unfiltered exception/validation dumps. Full references remain in protected result metadata, not routine logs.

Operational read/permission/capacity failures are distinct from malformed postings. S01 must specify their classified error channel outside the normalization tuple, or an agreed typed wrapper, so RUN-01 can preserve pending work. Do not mark a transient storage failure as an eligibility rejection or start a retry loop here.

## Ordered implementation stories

All stories belong exclusively to **INGEST-02**. Shared-owner changes in S01 are dependency requests, not authorization to implement FND-01, SOURCE-02/03, DATA-01, IDENTITY or MATCH inside these stories. Every story's native Windows checks also participate in the final S08 recipe.

| Order | Story | Depends on | Main deliverable |
|---|---|---|---|
| 1 | INGEST-02-S01 | FND-01, SOURCE-02 | Frozen input/provenance/unknown/error contract and owner decisions |
| 2 | INGEST-02-S02 | S01 | Synthetic multi-shape corpus and expected outputs/issues |
| 3 | INGEST-02-S03 | S01–S02 | Provenance reader integration, core fields and HTML/text cleaning |
| 4 | INGEST-02-S04 | S03; date decision D04 | Source-date normalization and observation semantics |
| 5 | INGEST-02-S05 | S03; D02, D05–D06 | Locations, workplace/restrictions and employment types |
| 6 | INGEST-02-S06 | S03; compensation decision D03 | Explicit-unit compensation normalization |
| 7 | INGEST-02-S07 | S03–S06 | Composed C06 validation and structured quarantine handoff |
| 8 | INGEST-02-S08 | S01–S07 | Boundary/regression/Windows evidence and component handoff |

### INGEST-02-S01 — Freeze contracts, provenance access and unknown semantics

**Objective/references.** Establish one implementable C05-to-C06 boundary. R03/R14/R15; C05, C06, `Normalizer`, `ValidationIssue`, `RecordIssue`; blueprint §§4, 6, 8–9.

**Dependencies.** FND-01 and SOURCE-02 handoffs/current versions. Consult SOURCE-03 only for its mapping semantics; DATA-01/INGEST-01 only for raw-reader and result-persistence integration. Their live services are not prerequisites for pure tests.

**Owned files.** Proposed `src/job_automation/ingestion/normalization/{__init__,models,ports}.py`, `tests/ingestion/test_normalization_boundary.py`, and a decision section in `docs/components/INGEST-02.md`. Shared-owner review targets: `contracts/{postings,interfaces,errors,export_schemas}.py`, affected schemas/fixtures/fakes, and source mapping vocabulary. Do not edit generated schemas by hand.

**Inputs → outputs.** Existing contracts and gaps → typed normalizer construction/settings, raw provenance reader port, mapping-shape table, quarantine envelope, stable issue catalog, and compatibility decisions.

**Tasks.**

1. Keep `normalize(draft)` and inject a reader resolving that exact `raw_reference` to trusted C05 metadata and bytes. Record identity/ref/fetch-time consistency checks. Never look up “latest posting” by source tuple for historical normalization.
2. Freeze supported mapping versions, allowed raw shapes and metadata describing text format, date unit/event/zone, locale, source field paths and boolean workplace meaning. Missing metadata must have documented conservative behavior. Reject unsupported mapping versions rather than guessing.
3. Close D01–D08 below. Resolve nullable collections and compensation units with FND-01 before those outputs are shipped. Record version changes, affected readers, stored-record handling, and regeneration of affected schemas. Do not globally relax strictness or change C02 salary-policy semantics.
4. Record minimum required fields and how invalid original types exposed by mapper coercion are detected. Prefer a SOURCE-02/03 strict mapping/provenance correction; do not reverse-parse stringified objects in the normalizer.
5. Specify local quarantine serialization and operational errors separately from validation. Define result invariants, versioned normalizer settings, stable ordering and the no-network/no-model boundary.

**Acceptance examples.** A C05 draft whose raw reference cannot be resolved yields an explicit failure, never a fabricated hash. A supported all-known draft produces a contract-valid C06. Missing restrictions and explicitly worldwide restrictions have distinguishable output representations. A draft containing unknown mapping semantics fails visibly. A raw read permission error remains operational pending work.

**Tests/Windows.** Protocol conformance, compatibility fixtures, result invariants, deep-copy behavior and version rejection. Reader fakes accept opaque references; file-backed test helpers use `pathlib.Path` under a Unicode/spaced Windows root and an explicit base. Test import/construction without network, model, database or directory-creation side effects.

**Migration/configuration/handoff.** No DB migration or CLI. Prefer constructor settings over new global config keys. Owner-approved incompatible changes require a blueprint decision and reader/migration plan; schema version and normalizer algorithm version are separate. Publish exact ports and decisions before dependent stories proceed. A fake reader can unblock unit tests; it does not prove durable storage integration.

### INGEST-02-S02 — Establish fixtures for heterogeneous inputs and failures

**Objective/references.** Make cross-source equivalence, unknown preservation and malformed-record retention executable. R03/R14/R15; C05/C06 and shared issues; blueprint §§4, 6–8.

**Dependencies.** S01; reuse SOURCE-02 manual adapters and their checked test bindings. Provider-shaped fixtures need no real source registration or network.

**Owned files.** Proposed `tests/fixtures/ingestion/normalization/README.md`, fixture subdirectories listed below, `tests/fakes/normalization_inputs.py`, and `tests/ingestion/test_normalization_fixtures.py`. Existing source fixtures are references; do not silently change their meanings.

**Inputs → outputs.** Synthetic raw bytes, original dictionaries, mapped drafts and provenance → a versioned manifest linking each case to independently authored expected C06 fields/issues and invariants.

**Tasks.**

1. Create the corpus specified below with known fixed fetch times, real computed hashes, supported mapping metadata, and complete field paths. Store raw bytes separately from derived row/envelope captures.
2. Run actual manual text/CSV mapping for integration cases. Use test-only mappings for nested ATS/feed examples, labelled illustrative rather than verified provider schemas. Use current Arbeitnow mapping only through fixture/fake transport; never initiate HTTP.
3. Establish semantic comparison projections: compare cleaned description, title, location facts, workplace, restrictions, dates and pay; exclude source keys, raw references/hashes and source-specific provenance from cross-source equality. Assert those differing provenance fields separately.
4. Include general office roles and technical roles. Fixtures must contain no real candidate data or credentials; hostile strings and secret-like URL test values are synthetic.

**Acceptance examples.** Manual HTML, CSV and nested ATS examples for “Sachbearbeiter (m/w/d)” yield the same explicit factual projection but retain three distinct sources. A broad remote flag with no region does not equal a remote-DE posting. Each negative fixture specifies error path/code/severity and its preserved raw reference.

**Tests/Windows.** Verify fixture hashes and manifest completeness before exercising normalization; round-trip C05 and expected C06 against selected contract models. Include UTF-8/BOM, CRLF, multiline CSV, `Größe`, umlauts, `ß`, spaces and non-ASCII file names. Existing contract placeholder hashes are not valid integrity-test payloads.

**Migration/configuration/handoff.** Test data only; no runtime configuration or schema change. Publish fixture meaning, mapping versions and equality exclusions in the fixture README. Expected values must not be generated by the implementation under test.

### INGEST-02-S03 — Preserve provenance and clean core text fields

**Objective/references.** Produce traceable, inert text while preserving source meaning. R03/R15; C05/C06, `SourceKey`, `ContentHash`; blueprint §§4–5.

**Dependencies.** S01–S02, especially D01 raw reader and D05 provenance/text-format decisions.

**Owned files.** Proposed `ingestion/normalization/{provenance,text,core}.py` beneath `src/job_automation/`; `tests/ingestion/test_normalization_{provenance,text,core}.py` and corresponding fixtures.

**Inputs → outputs.** Draft, trusted raw snapshot and declared text format → validated source identity/URLs/company hints/title/cleaned description, observed time, raw hash/ref and field provenance; otherwise structured field issues.

**Tasks.**

1. Resolve and verify exact raw bytes against the trusted stored hash. Copy the draft source tuple, reference and fetch time after consistency checks. For CSV/API envelopes, preserve the link to parent capture and record locator without substituting the parent hash for the C05 record hash.
2. Validate types before coercion, including original-field types where reliable provenance exposes them. Trim title/company outer whitespace without renaming the employer, translating titles, stripping `(m/w/d)`, or inferring company identities.
3. Implement deterministic HTML-to-text parsing, preferably with a standard-library parser after fixture evaluation. Decode entities once, preserve paragraph/list/table-cell boundaries and readable whitespace, normalize line endings, discard comments and non-content script/style content, and tolerate recoverable malformed markup. Do not execute HTML, load links/assets, evaluate scripts, or use regex alone as an HTML parser.
4. Respect plain-text input as text: `C++`, `C#`, `x < 5`, SQL, PowerShell and prompt-injection text remain inert content. Unknown format needs a documented conservative decision; do not strip literal text merely because it resembles markup. Do not repeatedly decode escaped markup into active tags.
5. Validate source/application URL syntax and allowed schemes without opening them. Preserve valid exact values, including query and fragment components; missing application URL stays null. Unsafe/malformed supplied URLs yield issues. No tracking-parameter cleanup or identity canonicalization.
6. Construct provenance for each populated source-derived output, nested location/pay member and URL; distinguish source paths from transformations and local `fetch_time`. Record mapping/normalizer versions and parser settings in the agreed metadata. Preserve attribution through the raw/mapping receipt or approved output metadata; do not append attribution to job requirements.

**Acceptance examples.** `<p>Planung &amp; Einkauf</p><ul><li>SAP</li><li>Excel</li></ul>` becomes `Planung & Einkauf\nSAP\nExcel`. A script-only description produces `empty_after_cleaning`. German text and gender markers survive. Changing raw CRLF to LF fails the original byte hash, even if the visible text is identical. `source_posting_id="0007"` remains exactly `"0007"`. A signed application URL is preserved in protected C06 data and absent from error messages.

**Tests/Windows.** Golden text outputs, malformed/unclosed tags, escaped entities, inline tags without artificial word breaks, nonbreaking spaces, tables/lists, hostile content and plain-text comparisons. Check input immutability and repeated-output stability. Socket/process-launch guards prove zero external effects. Byte integrity tests use BOM/CRLF and Unicode paths on native Windows.

**Migration/configuration/handoff.** No source adapter rewrite or storage migration. If a parser dependency is necessary, document its free/native-Windows suitability and version under D08 before adding it. Publish precise path/transform provenance conventions and any blocked mapper cases.

### INGEST-02-S04 — Normalize source dates without inventing precision

**Objective/references.** Separate source publication/update/deadline evidence from local observation time. R03/R14; C05/C06 and UTC primitives; blueprint §4.

**Dependencies.** S03 and D04 date representation; SOURCE-02/03 agreement for `source_updated_raw` and explicit epoch/zone semantics.

**Owned files.** Proposed `src/job_automation/ingestion/normalization/dates.py`, `tests/ingestion/test_normalization_dates.py`, and date fixtures.

**Inputs → outputs.** Supplied source date values plus explicit format/unit/event/zone metadata → UTC instants where justified, unknown timestamp values plus precision-preserving evidence/warnings where not, and `observed_at=draft.fetch_time` converted to UTC.

**Tasks.**

1. Parse offset-aware ISO dates and convert the instant to UTC. Accept epoch seconds/milliseconds only when the mapping declares both unit and event meaning; never guess from digit count. Reject booleans as numeric dates and reject impossible/out-of-range dates safely.
2. Preserve date-only/month-only precision through the S01 decision. Proposed baseline with current C06: leave the timestamp null and retain the supplied precision in linked raw evidence with `unsupported_representation`; do not insert midnight or end-of-day. A typed companion requires FND-01 changes before use.
3. Treat naive timestamps as ambiguous unless a versioned source rule supplies a timezone. With an explicit IANA zone, handle DST folds/gaps explicitly; unresolved ambiguity stays unknown with warning, never silently uses the host zone or a default fold.
4. Keep missing deadline null. Do not derive publication from fetch time, deadline from follow-up time, or first/last seen from normalization time. An elapsed deadline is a source fact, not an instruction to reject or close a job.
5. Keep current Arbeitnow `created_at` unpromoted while its unit/event meaning is unresolved. Do not bypass the adapter's null `source_published_raw` by mining `original_fields`.

**Acceptance examples.** `2026-10-28T09:30:00+01:00` becomes `2026-10-28T08:30:00Z`. Explicit epoch seconds `0` becomes the Unix epoch, not absence. `2026-10-31` does not become a fabricated timestamp. `03/04/2026` without a format stays ambiguous. Berlin `2026-03-29 02:30` is nonexistent and `2026-10-25 02:30` ambiguous without an offset/fold rule. A replay tomorrow keeps the same observed time.

**Tests/Windows.** Offset/date-unit tables; leap-year validity; bool/float/string mismatches; missing/blank values; DST folds/gaps; fixed fetch-time replay. Resolve `Europe/Berlin` using installed `tzdata` on native Windows and prove results do not depend on machine timezone or CWD.

**Migration/configuration/handoff.** No scheduler or source-time inference. Record supported formats and limits. Updated-date vocabulary is a source-owner dependency; keep absent updates null until available. Publish precision limitations explicitly rather than claiming full timestamp coverage.

### INGEST-02-S05 — Normalize locations, workplace and remote restrictions

**Objective/references.** Preserve multiple locations and distinguish workplace arrangement from where a person may work. R03; C05/C06, `StructuredLocation`, `WorkplaceType`, `EmploymentType`; blueprint §4.

**Dependencies.** S03; D02 nullable collection semantics; D05 mapped restriction fields; D06 boolean/alias/conflict rules.

**Owned files.** Proposed `src/job_automation/ingestion/normalization/{locations,workplace,vocabulary}.py`, `tests/ingestion/test_normalization_{locations,workplace}.py`, and geographic fixtures.

**Inputs → outputs.** String/list/structured location values, workplace labels/declared flags, explicit restriction values and employment labels → structured location collection, workplace enum, separate restrictions and employment enum, each with provenance/issues.

**Tasks.**

1. Accept only declared shapes. Preserve each original location text; populate country/region/city/postal code only where source structure or a finite documented parsing rule supplies the fact. Normalize supported country aliases such as `Deutschland`/`Germany` to `DE`. No geocoding, guessed countries from source market, or broad comma splitting of city/region/country into separate locations.
2. Preserve multiple locations in stable source order; remove only exact repeated location entries under a documented rule while retaining all evidence paths. This is collection normalization, not job deduplication. Do not merge Berlin and remote into one city or expand EU into an invented country list.
3. Map explicit aliases (`vor Ort`/`on-site`, `hybrid`, `remote`) through a versioned vocabulary independent of user search-policy aliases. For a broad remote boolean, `true` is usable as remote only with declared mapping semantics; `false` alone does not establish onsite rather than hybrid. Unknown/contradictory values stay unknown with a warning.
4. Normalize explicit geographic restrictions independently: remote-DE, remote-EU and unrestricted worldwide remain distinct. A job location in Berlin does not itself restrict remote work to Germany. Preserve unsupported compound restrictions as evidence and warn; do not split `DE or AT` into an AND requirement or equate work authorization with permitted work location.
5. Map finite employment aliases such as `Vollzeit`/`Full-time` and `Teilzeit`/`Part-time`. For lists, collapse equivalent labels only; incompatible simultaneous labels stay unknown with evidence/warning. Do not infer employment from salary period.
6. Keep declared advert language separate from candidate proficiency or required languages. Prefer explicit source language metadata; absent language stays null. Free-text requirement extraction is downstream work.

**Acceptance examples.** `['Berlin, Germany', 'Hamburg, Deutschland']` produces two location entries with country `DE` and preserved text. Ambiguous `Springfield` has no invented country. Remote plus absent restrictions remains remote with unknown restrictions; explicit worldwide has a known empty restriction set only after D02 defines that meaning. Explicit `['DE']` stays restricted. A broad false remote flag stays `unknown` unless the mapper supplies stronger workplace evidence. `['Vollzeit', 'Full-time']` becomes `full_time`; `['Vollzeit', 'Teilzeit']` does not pick the first label.

**Tests/Windows.** String/list/structured equivalence; invalid item types; unknown versus explicit empty; multi-location ordering; ambiguity and negation; remote/hybrid/onsite conflicts; bool versus `"false"`; unsupported labels; no eligibility outputs. Test `München`, `Köln`, `Baden-Württemberg`, Unicode whitespace, JSON round-trips and native Windows fixture paths.

**Migration/configuration/handoff.** Nullable output collections require the agreed C06 consumer plan. Do not alter POLICY-01 criteria or implement MATCH-01. Record supported vocabulary and shape boundaries, remaining raw-only restrictions, and boolean-provider limitations.

### INGEST-02-S06 — Normalize compensation with explicit units and provenance

**Objective/references.** Preserve actual pay facts without fabricating units or comparability. R03; C05/C06 `JobCompensation`, `SalaryPeriod`, `CompensationProvenance`; blueprint §4.

**Dependencies.** S03 and D03; SOURCE-02/03 shape/locale declarations from S01.

**Owned files.** Proposed `src/job_automation/ingestion/normalization/compensation.py`, `tests/ingestion/test_normalization_compensation.py`, and pay fixtures.

**Inputs → outputs.** Structured pay or bounded supported textual formats plus source/locale evidence → Decimal bounds, explicit currency and period where known, gross/net/unknown, employer/estimated/unknown origin, and field issues/provenance.

**Tasks.**

1. Parse supported strings and structured fields with Decimal-safe handling, preserving exact/range/lower-only/upper-only meanings. Explicit zero stays zero; absent bounds stay null. Reject booleans, nonfinite/negative values and min greater than max; do not swap bounds silently.
2. Normalize unambiguous `EUR`/`€`, hourly/monthly/yearly aliases and `brutto`/`netto`. Do not guess a currency from `$`, a period from the amount's size, locale from the machine, or gross/net from Germany. Locale-specific grouping/decimal separators require explicit metadata or an unambiguous bounded grammar.
3. Prevent current `JobCompensation` EUR/yearly defaults from filling unknown facts. Preferred D03 resolution: nullable currency/period with explicit construction. If unresolved, incomplete-unit compensation must remain raw with unknown normalized compensation and warning, never falsely comparable.
4. Keep employer-provided pay distinct from estimates, including provenance on bounds/units. Do not merge an employer range with a third-party estimate. A source that omits origin yields `unknown`, not employer-provided by default.
5. No annualization, currency conversion, hours-per-week assumptions, bonus addition or policy comparison. Weekly/daily or multiple pay packages remain visibly unsupported unless FND-01 explicitly extends the shared representation.

**Acceptance examples.** With declared German numeric formatting, `60.000–75.000 EUR brutto/Jahr` becomes bounds `60000`/`75000`, `EUR`, `yearly`, gross true. `25 EUR/Stunde` stays hourly. `ab 4.500 EUR/Monat` has min `4500`, max null. `75.000–85.000 EUR` from the existing manual CSV must not acquire yearly units. Bare `70000` has unknown currency/period. `€0/hour` is a known zero. `90000–70000 EUR/year` is blocking. Estimated pay remains estimated even when the employer name is known.

**Tests/Windows.** Table-driven structured/text equivalence; Decimal serialization; single/open ranges; whitespace/nonbreaking spaces; grouping ambiguity; currency symbols; gross/net; employer/estimate conflicts; unsupported units; invalid types and boundaries. Run under native Windows without depending on OS numeric locale. Assert no derived annual or converted amount appears.

**Migration/configuration/handoff.** Record exact C06 compensation version and compatibility with existing C02 target declarations. The normalizer does not change policy salary thresholds. Publish supported grammars, partial-unit behavior, fallback warnings and provenance rules.

### INGEST-02-S07 — Compose validation and emit inspectable quarantine results

**Objective/references.** Make malformed records safe to isolate while valid neighbors continue. R03/R15/R16; C05/C06, `ValidationIssue`, upstream `DraftResult`/`RecordIssue`; blueprint §§4–6.

**Dependencies.** S03–S06; S01 result/error decisions. DATA-01/INGEST-01/RUN-01 are consumers of the handoff, not prerequisites for the pure service.

**Owned files.** Proposed `src/job_automation/ingestion/normalization/{service,validation,quarantine}.py`, public normalization exports, `tests/ingestion/test_normalization_{validation,quarantine,service}.py` and test-only consumer fakes. Do not take ownership of INGEST-01 controller files.

**Inputs → outputs.** C05 draft and provenance → final validated C06 plus warnings, or a no-posting result plus structured blocking issues. A thin boundary helper accepts upstream result/locator context and constructs a quarantine handoff without losing original issues.

**Tasks.**

1. Compose field normalizers in a deterministic order; enforce type, nonblank required-field, UTC, compensation and provenance invariants beyond permissive model defaults. Finalize C06 through its selected versioned model and translate failures into safe shared issues.
2. Enforce the result invariant: any error excludes C06; warnings permit C06; no fabricated “best effort” posting on a fatal error. Populate all required version/raw/source/observation metadata explicitly.
3. Carry upstream missing-title warnings into the record history while producing the downstream blocking title issue. A `DraftResult` with no draft is not passed to `normalize`; preserve its existing `RecordIssue` and raw locator. Invalid identity may fail C05 construction upstream; retain that upstream quarantine evidence without inventing a `SourceKey`.
4. Preserve all issues and input/record/line metadata in the quarantine envelope. Distinguish an adapter-stage issue from a normalizer-stage issue; avoid counting one rejected record once per issue. Do not relabel quarantine as `AssessmentDisposition.rejected`.
5. Demonstrate independent-record isolation with a test consumer loop. Successful neighbors survive one malformed record. Storage/reader outages remain separately classified operational failures; unexpected defects stay visible and do not become fabricated C06 outputs.
6. Make reprocessing callable with a new normalizer version and the same raw snapshot. Return new derived results without mutating/deleting raw evidence or overwriting prior receipt history. Durable replay scheduling/transactions remain with their owners.

**Acceptance examples.** Three drafts containing valid data, a blank title plus wrong location type, and remote work with unknown restrictions yield two C06 results and one quarantine record with both errors. Raw references remain available for all three. The unknown-remote case is not filtered. Two identical source tuples are both normalized independently; no merge, duplicate decision, canonical ID or eligibility label is emitted.

**Tests/Windows.** Mixed-batch fake integration; warning-only versus blocking results; upstream failure retention; stable issue order; no `(None, [])`; safe diagnostic serialization with synthetic secret-like values; repeat processing and nested input immutability. Windows tests reopen serialized result metadata and raw fixtures under spaced/non-ASCII paths; temporary readers release handles. Pure serialization tests do not establish durable crash recovery.

**Migration/configuration/handoff.** No SQLite tables, recovery scheduler or production CLI. Publish quarantine envelope schema/version, callable signatures, count units and operational error channel for DATA-01/INGEST-01/RUN-01. If durable ports are unavailable, mark production quarantine persistence pending while accurately reporting pure routing tests.

### INGEST-02-S08 — Verify cross-source behavior and publish the handoff

**Objective/references.** Demonstrate INGEST-02 acceptance and document remaining integration limits. R03/R14/R15/R16; C05/C06; blueprint §§6–9 and G1/G2 evidence boundaries.

**Dependencies.** S01–S07 and resolved mandatory contract decisions. Live source access is not needed for deterministic normalization acceptance. Test-only shapes do not demonstrate a second configured automated source or full G2 completion.

**Owned files.** Proposed `tests/ingestion/test_normalization_{equivalence,adapter_integration,windows}.py`, fixture README updates and `docs/components/INGEST-02.md`. Update README only if a concrete supported invocation needs documentation; do not invent a normalization CLI.

**Inputs → outputs.** Completed service, corpus and current dependency versions → reproducible focused/regression results, native Windows evidence, explicit production/live pending work and a consumer handoff.

**Tasks.**

1. Exercise the real manual URL-plus-text and CSV adapters through `DraftResult` into the normalizer; use checked source bindings and in-memory exact-byte capture. Verify HTML, date, geography, pay and provenance outputs against independent expected values.
2. Run structured/nested feed fixtures through test-only mappers into the same normalizer protocol with no provider-specific branches in the consumer. Add fixture-backed current Arbeitnow mapping compatibility where its unresolved semantics are honestly represented.
3. Run focused ingestion tests, affected source/contract/policy regressions and the complete existing suite. Include a schema-export consistency check; current catalog tests only parse schema JSON and do not establish full JSON Schema semantic equivalence. State which validators were actually used.
4. Run the Windows recipe below after proposed test files exist. Record platform/Python/packages, commands, exit codes, counts and limitations. No upstream test count is reused as an INGEST-02 result.
5. Publish status, contract/normalizer/mapping versions, owned files, final decisions, fixture coverage, safe invocation examples, required integration ports and next consumers IDENTITY-01, MATCH-01 and RUN-01.

**Acceptance examples.** At least three distinct source shapes yield equivalent shared facts while retaining distinct raw provenance. Missing units and unknown restrictions remain unknown in serialized outputs. All malformed examples retain locators and structured issues. Path tests pass outside the repository CWD on native Windows. No deduplication, eligibility result, network call or model call occurs.

**Tests/Windows.** Execute the matrix/recipe below and inspect actual failures. If a prerequisite regression already fails, record the exact result and owner rather than claiming green or broadening INGEST-02 to repair unrelated work.

**Migration/configuration/handoff.** Document actual shared-owner migrations separately from this component's changes. Use `implemented` while required acceptance checks are pending; `verified` only when the declared normalization acceptance passes. Distinguish optional live/provider/durable pipeline integration from component acceptance and full-project completion.

## Fixture specification

All paths below are **planned**, relative to `tests/fixtures/ingestion/normalization/`. Each case includes original bytes, C05 metadata/draft, mapping version/settings, expected C06 projection or quarantine issues, and provenance expectations. Actual record hashes are computed from the included bytes. Exact expected filenames may be refined in S02 without dropping coverage.

| Fixture family | Source shape and concrete content | Required assertions |
|---|---|---|
| `manual_text/office_html` | URL-plus-text HTML for `Sachbearbeiter (m/w/d)`, explicit company, paragraphs/list, entities | Clean German text, intact title, valid URLs, raw byte identity and source paths. |
| `manual_csv/office_bom_crlf` | UTF-8 BOM/CRLF CSV, quoted multiline text, explicit ID `0007`, semicolon variant | Same explicit office facts as HTML; parent CSV and derived row refs/hashes remain distinct; exact ID retained. |
| `nested_ats/office_multilocation` | Illustrative nested title/company/location objects, offset date, structured pay | Test mapper exposes common fields; equivalent C06 facts, nested paths and multiple locations retained. Not a claimed live Greenhouse schema. |
| `flat_feed/remote_boolean` | Current Arbeitnow fixture-derived draft: boolean remote, list job types, raw `created_at`, attribution | No worldwide inference, false does not automatically mean onsite, created_at stays unpromoted, attribution traceable. |
| `structured_board/hybrid_restricted` | Illustrative explicit workplace enum, remote-DE restriction, employment label and language metadata | Workplace/restrictions/location/language remain distinct. No new production adapter. |
| `unknowns/absent_null_empty` | Missing key, null, blank text, explicit empty collection, zero and false variants | Document each shape's meaning; unknown collections differ from known empty; zero/false not erased. |
| `text/hostile_and_malformed` | Script/style/comments, broken tags, `&lt;...&gt;`, `C++`, `x < 5`, shell/SQL/prompt text | Deterministic inert text, no fetching/execution, script-only text fails nonempty output. |
| `dates/precision_and_zones` | ISO offsets, declared seconds/milliseconds, zero epoch, date/month precision, naive time, DST fold/gap, invalid leap date | Exact UTC conversions only with evidence; no precision invention; stable observed time. |
| `locations/multiple_and_ambiguous` | Berlin/Hamburg structured and string variants, Springfield, unknown country, duplicate entry, remote text | No geocoding or guessed Germany; stable location set, raw labels and all contributing provenance. |
| `workplace/restriction_conflicts` | Remote-DE, EU, worldwide, remote with no restriction, hybrid, broad true/false, conflicting labels | Null versus known empty; no regional authorization inference or filtering. |
| `compensation/units_and_origins` | German/English ranges, hourly/monthly/yearly, lower/upper only, bare number, ambiguous `$`, weekly unit, net/gross, employer/estimate | Decimal amounts, no hidden EUR/yearly defaults/conversions, origin distinction and raw-only unsupported representations. |
| `invalid/typed_and_required` | Blank title/company, cleaned-empty description, integer title before mapper coercion, wrong location/list item types, bool pay, reversed range, bad URL | Stable field-specific errors, no C06 on blocking errors, no fabricated replacements. |
| `provenance/broken_and_replay` | Missing raw capture, wrong hash/source/ref, absent/invalid source path, unknown mapping/schema version, replay snapshot | Fail visibly; retain trusted available references; never hash cleaned/re-serialized text as original bytes. |
| `mixed/three_records` | Valid office record, malformed record with two errors, valid unknown-remote record | Valid neighbors survive; counts are records versus issues; raw history retained; no job merging or assessment. |

## Verification matrix and native PowerShell recipe

| Lane | Evidence required | What it does not establish |
|---|---|---|
| Unit/contract | Exact field outputs, negative issues, version/serialization checks, provenance integrity | Provider permission or live correctness. |
| Adapter integration, offline | Real manual adapters and fixture-backed mappings produce consumable C05; same normalizer protocol | Production fetch/controller storage wiring. |
| Quarantine consumer fake | Correct routing, retained locators, deterministic issues and independent neighbors | SQLite commit/restart recovery or durable quarantine. |
| Native Windows | Unicode/spaced paths, BOM/CRLF, alternate CWD, tzdata, handle release | Unattended scheduling or a working live pipeline. |
| Live/provider and durable integration | Record separately as passed/pending/not applicable with exact evidence | Never inferred from fixtures or an upstream VERIFIED label. |

Run **after implementation**, from the repository root in native PowerShell. These commands are a future verification recipe, not checks executed during this planning task. No activated environment, Bash, WSL or service accounts are required.

Planning-time environment note: invoking the existing `.venv/Scripts/python.exe` for a document check failed because its referenced base Python installation was unavailable. Document structure and local links were checked with native PowerShell instead. No application tests were run for this planning task. Repair or recreate the native environment through the repository setup instructions before executing this recipe; upstream handoff results do not establish that the current environment still works.

```powershell
$ingest02Repo = (Get-Location).Path
$ingest02Python = Join-Path $ingest02Repo '.venv\Scripts\python.exe'
$ingest02Tests = Join-Path $ingest02Repo 'tests\ingestion'
$ingest02WindowsTest = Join-Path $ingest02Tests 'test_normalization_windows.py'
$ingest02Contracts = Join-Path $ingest02Repo 'tests\contracts'
$ingest02Sources = Join-Path $ingest02Repo 'tests\sources'
$ingest02Policy = Join-Path $ingest02Repo 'tests\policy'
$ingest02AllTests = Join-Path $ingest02Repo 'tests'
$ingest02TempRoot = Join-Path $env:TEMP ('Job Automation Prüfung ä INGEST-02 ' + [guid]::NewGuid().ToString())

& $ingest02Python -c "import platform, sys; from zoneinfo import ZoneInfo; print(platform.platform()); print(sys.version); print(ZoneInfo('Europe/Berlin'))"
$ingest02EnvironmentExit = $LASTEXITCODE
& $ingest02Python -m pip show pydantic pytest tzdata
& $ingest02Python -m pytest $ingest02Tests -k normalization
$ingest02FocusedExit = $LASTEXITCODE
& $ingest02Python -m pytest $ingest02Contracts $ingest02Sources $ingest02Policy
$ingest02BoundaryExit = $LASTEXITCODE

New-Item -ItemType Directory -Path $ingest02TempRoot | Out-Null
Push-Location $ingest02TempRoot
try {
    & $ingest02Python -m pytest $ingest02WindowsTest --basetemp (Join-Path $ingest02TempRoot 'Test Data Größe')
    $ingest02WindowsExit = $LASTEXITCODE
} finally {
    Pop-Location
}

& $ingest02Python -m pytest $ingest02AllTests
$ingest02RegressionExit = $LASTEXITCODE
[pscustomobject]@{
    EnvironmentExit = $ingest02EnvironmentExit
    FocusedExit = $ingest02FocusedExit
    BoundaryExit = $ingest02BoundaryExit
    WindowsExit = $ingest02WindowsExit
    RegressionExit = $ingest02RegressionExit
}
```

The planned Windows test must construct paths using `pathlib.Path` and an explicit fixture/input base, not process CWD. Check byte hashes before and after reads, Unicode JSON output, file handle release, repeat processing, and unchanged timestamps from another CWD. Runtime data stays outside the repository; test-only fixtures remain tracked. If approved models change, regenerate schemas through their generator and verify the export diff against the recorded version decision; do not hand-edit generated JSON or claim the current catalog test validates every schema constraint.

## Unresolved decisions and closure owners

| ID | Gap / decision | Proposed direction and closure evidence |
|---|---|---|
| D01 | Draft-only protocol lacks trusted raw hash and immutable observation lookup | INGEST-02 injects a read-only reference-based provenance reader, preserving the public protocol. DATA-01/INGEST-01 own durable implementation. S01 fixes exact port/error signatures; fixture reader permits isolated work. No hash reconstructed from decoded payload text. |
| D02 | C06 unknown collections and required company hint conflict with sparse source data | FND-01 decides nullable collections and whether company hints become nullable. Require explicit consumer/version handling; do not reinterpret existing `[]` or infer legacy company values. Unresolved cases quarantine or remain blocked, never fabricated. D02 is mandatory before unknown-collection acceptance can pass. |
| D03 | Compensation currency/period defaults and limited enum | Prefer explicit nullable units, preserve supported partial values and use raw-plus-warning fallback for unsupported units. FND-01 owns shared model/schema/reader changes. Do not change C02 policy units or add conversions. S01 records chosen version and legacy-default ambiguity handling. |
| D04 | Source date precision, naive dates and missing updated-date vocabulary | Baseline: UTC only for evidenced instants; preserve date-only evidence in raw with warning and null C06 timestamp. FND-01 may approve a precision companion; SOURCE-02/03 provide update/unit/event/zone metadata. Arbeitnow created_at remains unresolved until its owner supplies evidence. |
| D05 | Mapping vocabulary, original paths, coerced source types, format and attribution | SOURCE-02/03 own extraction/metadata corrections for restrictions, update dates, company ID, advert language, text format and original paths. INGEST-02 consumes the agreed version without provider payload mining. Safe fallback paths may identify the mapped field explicitly, but must never falsely claim an original path; S01 defines when this is sufficient versus blocking. |
| D06 | Broad boolean workplace semantics, finite aliases and complex restrictions | INGEST-02 owns conservative common normalization; SOURCE-03 declares each flag's meaning. `false` alone stays unknown; do not infer worldwide from true. Freeze aliases and conflict behavior; compound/unsupported restrictions stay explicit evidence with warnings. No candidate eligibility reasoning. |
| D07 | Quarantine serialization, operational error channel and persistence | INGEST-02 owns versioned envelope/routing; FND-01 reconciles shared error/interface changes if needed. DATA-01/RUN-01 own persistence, retry and stage state. Record fake versus durable status separately; no extra database added here. |
| D08 | Parser choice, normalization limits and reproducibility | Prefer standard library plus existing dependencies. INGEST-02 selects finite text/collection/numeric limits based on fixtures and documents them, with visible limit issues rather than silent truncation. Freeze a normalizer version covering parser/alias/settings changes; record any additional free dependency/native Windows validation. |

These decisions require repository-owner coordination and recorded evidence, not invented user preferences or a generic permission pause. Resolve contract choices once in S01. Where a dependency cannot yet supply a capability, retain the explicit pending integration and continue independent fixture work without claiming the blocked acceptance passed.

## Implementation handoff checklist

- Component/status/objective and R03 with supporting R14/R15/R16; exact scope exclusions.
- Dependency status and actual C05/C06, mapping, normalizer, quarantine and parser/settings versions.
- Owned files and any separately coordinated shared-owner changes, schema exports and compatibility/migration decisions.
- Callable input/output examples for successful, warning-only, quarantined and operational-failure cases; trusted raw references and issue paths/codes.
- Fixture coverage for distinct source shapes; equality projections; HTML, dates, locations, workplace, restrictions, compensation, provenance and unknown semantics.
- Commands, environment, exit codes and actual results; separate unit/contract, fake adapter integration, native Windows, durable integration and live evidence.
- Known limitations and open D01–D08 items, including current Arbeitnow date/flag/provenance limits and sparse source behavior.
- Next consumers: IDENTITY-01 receives valid C06 only; MATCH-01 receives unknown facts without precomputed eligibility; RUN-01 receives structured outcomes; DATA-01/INGEST-01 retain provenance/quarantine evidence. No deduplication, filtering, G1/G2 or full-pipeline completion claim.
