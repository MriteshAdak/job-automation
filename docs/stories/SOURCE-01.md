# SOURCE-01 — Source registry and access policy

Status: **PLANNED** · Planning date: 28 October 2026 · Component: **SOURCE-01 only** · Phase 0

Baseline: [IMPLEMENTATION_BLUEPRINT.md][blueprint], v1.0, 26 October 2026. Requirement references are to §2; contracts to §4; correctness rules to §5; component ownership to §6; integration gates to §7; implementation/handoff instructions to §8; native Windows conventions to §9; unresolved source choices to §10. These are ordered implementation stories. This planning task creates only `docs/stories/SOURCE-01.md`.

## Repository evidence and scope

Read the blueprint, [README.md](../../README.md), the [FND-01 handoff][fnd], foundation stories, current source contracts/schemas/fixtures/tests, configuration and CLI. The [DATA-01 handoff][data] and source-posting repository establish existing persistence boundaries. The POLICY-01 plan supplies adjacent configuration context. No applicable repository or ancestor `AGENTS.md` was found; the checked user-level `.codex/AGENTS.md` is empty. README and blueprint §§8–9 supply the working instructions.

| Evidence | Current behavior and planning consequence |
|---|---|
| FND-01 handoff | Reports VERIFIED with schema 1.0 and native Windows checks. Its 78-test result is historical foundation evidence, not a SOURCE-01 test result. |
| [C03 model](../../src/job_automation/contracts/sources.py) | `SourceConfig` already contains `source_key`, `provider`, `board_id`, `acquisition_method`, `base_url`, `access_rules`, `attribution_rules`, `request_policy`, `enabled`, and `inventory_semantics`. Reuse this contract; do not create a competing source record. |
| C03 validation | Identity/URL fields only require nonempty strings. Access and attribution are nullable text; request policy is `dict[str, Any]`. There is no registry, access review, method-specific validation, scope descriptor, or selection gate. |
| Defaults and versions | `enabled=False`; inventory defaults to `search_results`. `ContractModel.schema_version` is an unrestricted string defaulting to `1.0`; `frozen=True` does not freeze nested dictionaries. Schema acceptance and snapshot isolation need explicit service behavior. |
| Identity types | C03 `source_key` is a configuration key. [SourceKey](../../src/job_automation/contracts/primitives.py) is the posting tuple `(provider, board_id, source_posting_id)`. They are different identities despite similar names. |
| [Enums](../../src/job_automation/contracts/enums.py) | Acquisition values are `api`, `permitted_scraping`, `manual_import`; inventory values are `complete_board`, `filtered_feed`, `search_results`. C04 execution outcome is separately `complete`, `partial`, or `failed`. Preserve these distinctions. |
| [C04](../../src/job_automation/contracts/postings.py) | `FetchManifest` already carries string `source_key`, `scope_id`, `inventory_semantics` and observed posting IDs. C03 has no explicit scope identity or structured query/filter definition. Define their handoff before downstream fetching. |
| [App configuration](../../src/job_automation/configuration.py) | `active_sources: list[str]` exists, but has no registry reference or referential validation. `config check` does not validate sources. Relative policy references are already anchored to the app-config directory; use that path convention for sources. |
| [Example configuration](../../config/app.example.json) | Selects `arbeitnow_de` although no registry exists. The C03 fixture uses that provider name, a disabled flag and `request_policy={"timeout": 30}`. These are synthetic examples, not verified endpoints, limits or permission evidence. |
| [Contract tests](../../tests/contracts/test_source_posting_identity.py) / [catalog](../../tests/contracts/test_contract_catalog.py) | Cover a C03 happy path, scoped posting identity and a malformed fixture. The catalog checks typed fixtures and schema JSON parsing, not full schema parity or registry behavior. |
| DATA-01 and current CLI | Storage already persists C04/C05 and enforces posting identity; storage/profile CLI commands also exist. SOURCE-01 needs no database table, migration, or storage engine initialization. Preserve existing CLI behavior. |
| Foundation guidance conflict | FND-01 handoff §7 groups SOURCE-01/02 under implementing `Adapter` and producing C05. Blueprint §6 controls: SOURCE-01 owns registry/access policy and C03; SOURCE-02 owns the adapter/manual-import boundary. Do not implement `fetch_page` or `draft_posting` here. |

**Direct requirements:** R02 (configurable permitted acquisition and honest coverage) and R15 (credential protection and untrusted input). Supporting constraints: R14 (native Windows), R16 (bounded request configuration, diagnostics and auditability), and R04 only at the source-identity/inventory handoff. This component does not complete source acquisition, disappearance inference, or the G1/G2 integration gates.

**Catalog dependency:** FND-01 only, especially its C03/C04/C05 contracts, `SourceKey`, enums/errors, configuration and schema exporter. DATA-01 and POLICY-01 are coordination references, not additional prerequisites. SOURCE-02, SOURCE-03 instances, INGEST-01, IDENTITY-02 and RUN-01 are downstream consumers.

**In scope:** local source registry loading, C03 semantic validation, provider/board identity, acquisition declarations, documented access and attribution metadata, bounded request-policy configuration, enabled/disabled and selection behavior, inventory/scope declarations, safe inspection CLI, synthetic fixtures, Windows verification and a component handoff.

**Outside scope:** HTTP requests, permission-page retrieval, robots retrieval, scraping, pagination, adapter implementation, CSV/text posting imports, raw-response storage, retry execution, caching, posting mapping/normalization, canonical identity resolution, availability updates, job filtering, Salesforce/model calls, scheduling and application submission. Recording a manual-import source is in scope; reading its postings belongs to SOURCE-02. Configuring rate/backoff limits is in scope; executing them belongs to INGEST-01 and its adapter.

## Invariants and decision register

Blueprint requirements are authoritative. The file names, public API names, CLI syntax and technical defaults below are **proposed implementation choices**, to resolve and record during their named stories. They are not new user-confirmed employer choices, provider permissions, job criteria or source-specific limits. Use synthetic `.invalid` URLs for executable test fixtures; shipped examples remain disabled.

- A public URL, a successful response, an unauthenticated API, permissive robots content, an acquisition enum called `permitted_scraping`, or an operator setting `enabled=true` cannot establish permission. Keep documented authorization/access conditions separate from reachability and operator selection.
- Access review applies to the exact provider, board/tenant, acquisition method, endpoint/path and intended use. API permission does not grant scraping permission; one employer's board does not grant access to another. Restrictive or unknown evidence must remain visible and block selection as appropriate.
- Attribution `null` means unknown, not “no attribution required.” An explicit reviewed “none required” is different from unknown. Carry required wording/links and reuse/retention restrictions to consumers without performing publication or retention here.
- Registry key, provider/board identity, posting tuple and inventory scope are distinct. Never derive a permanent posting identity from a title, description, display label or request-policy hash. Provider IDs remain opaque strings, including case and leading zeros.
- Disabled or unconfigured entries cannot become selected sources. An empty active-source list selects nothing; it does not mean all sources. Loading or checking a registry never executes a source.
- Inventory semantics describe coverage; C04 outcome describes execution. A completed search or filtered feed is not a complete employer board. Configuration alone never proves a successful complete inventory or changes a posting's availability.
- Source selection is configurable across general white-collar roles. No built-in technology-role filter, employer list, candidate capability, or work authorization is inferred from Germany, a provider name or example jobs.
- Errors use safe codes/field paths. Do not print raw request headers, credentials, URL userinfo, query tokens, arbitrary config payloads or exception representations. Metadata is data, never shell commands, Python expressions, plugins to import or instructions to execute.

Resolve these decisions once, before dependent behavior relies on them. Record resolutions and remaining real-source inputs in the future `docs/components/SOURCE-01.md`.

| ID | Decision / gap | Proposed direction, owner and closure |
|---|---|---|
| D01 | C03 metadata representation and supported versions | S01 with FND-01: retain existing C03 fields; prefer explicit additive access-review, attribution-review and inventory-scope metadata. Do not hide these inside arbitrary HTTP settings or prose parsing. Define exact models, schema versions and legacy behavior before S02–S06. |
| D02 | Registry format, configuration reference and path rules | S01/S02: versioned JSON envelope containing C03 entries, optional `AppConfig.source_registry_ref` and resolved registry path; explicit CLI override wins. Relative references use the containing configuration directory. No registry discovery by working directory or network. |
| D03 | Configuration identity, duplicate scopes and edits | S01/S02: unique exact `source_key`; preserve opaque provider/board IDs, reject blank/padded IDs rather than silently rewriting them. Multiple configured scopes may share a provider/board; conflicting duplicate keys are errors. Decide warning/error for identical effective scopes. Document key/provider/board changes as identity changes, not automatic aliases or merges. |
| D04 | Access review, freshness and attribution states | S01/S03: explicit unreviewed/permitted/denied status, scoped evidence references, review time and applicable restrictions; attribution unknown/required/none-required. Define how conflicting evidence, expiry or a known terms change invalidates review. No universal review interval or real permission is invented. Missing evidence blocks a runnable selection. |
| D05 | Request-policy vocabulary and legacy keys | S01/S04 with INGEST-01/SOURCE-02 boundary: finite typed interpretation of existing dictionary, with units and bounds. Decide exact keys, retry-count convention, header/parameter rules, credential references and conservative defaults. Resolve legacy `timeout` explicitly; never silently ignore a misspelling. |
| D06 | Manual-import origin and `base_url` | S01/S04 with FND-01/SOURCE-02: current C03 requires a URL-like string even for pasted text. Prefer a versioned method-specific origin that can be absent for local text/CSV; keep a supplied URL as provenance only. No invented HTTP endpoint. Nullable/reinterpreted `base_url` requires an explicit compatibility plan. |
| D07 | Inventory scope identity and completeness evidence | S01/S05 with C04/FND-01 and downstream INGEST-01/IDENTITY-02: explicit versioned scope descriptor and deterministic `scope_id`. Define membership-affecting fields and legacy manifests with unknown scope. Conservative baseline: only a documented complete board is a candidate for downstream disappearance evidence; filtered/search/manual subsets are not. |
| D08 | Selection API, validation severity and empty/mixed selection | S01/S06: read-only registry plus a single checked selection boundary. Missing, disabled, unreviewed or invalid requested entries yield blockers and no executable selection for that request; inspect valid entries separately. Future independent fetch failures remain INGEST-01's responsibility. Structural corruption blocks the registry; disabled drafts may retain clearly reported readiness gaps. |
| D09 | Initial sources, employers and actual limits | User configuration and SOURCE-03 instance: verify official source documentation/current conditions before real enablement. Arbeitnow and a Greenhouse board are blueprint suggestions only. Exact employer/tenant IDs, access evidence, rate limits, attribution and coverage remain pending; synthetic SOURCE-01 acceptance does not depend on choosing them. |
| D10 | Inspection CLI and safe diagnostic behavior | S02/S07: proposed `sources check` and `sources list`; check returns 0 for a valid requested selection, including explicit empty selection, and 2 for invalid configuration/selection. Distinguish structural validity, disabled, unselected and blocked readiness in output. Define encoding and safe JSON output before tests. |

Shared changes follow blueprint §8. Compatible additions require generated schemas, fixtures and a recorded version; because old readers forbid extra fields, describe consumer compatibility rather than assuming every addition is readable by them. Incompatible field/type/meaning changes require a migration/consumer plan and an updated blueprint decision. Preserve original inputs and historical C04/C05 records; never rewrite old permission or coverage claims as newly verified. Prefer source-local semantic validation over changing shared primitives for unrelated components. Do not hand-edit generated schemas.

## Ordered stories

Every story is **PLANNED** and belongs only to SOURCE-01. Owned paths below are proposed future implementation targets, not files created by this planning task. Each story records its decisions, checks and pending dependencies in the component handoff.

| Order | Story | Deliverable | Internal dependencies |
|---|---|---|---|
| 1 | [SOURCE-01-S01](#source-01-s01) | C03 semantics, public boundary and compatibility specification | None |
| 2 | [SOURCE-01-S02](#source-01-s02) | File-backed registry, identity checks and app-config reference | S01 |
| 3 | [SOURCE-01-S03](#source-01-s03) | Scoped access and attribution review validation | S01, S02 |
| 4 | [SOURCE-01-S04](#source-01-s04) | Acquisition-specific endpoints and bounded request policy | S01, S02; S03 for reviewed constraints |
| 5 | [SOURCE-01-S05](#source-01-s05) | Inventory semantics and stable scope identity | S01–S04 |
| 6 | [SOURCE-01-S06](#source-01-s06) | Checked enabled/selected-source boundary | S02–S05 |
| 7 | [SOURCE-01-S07](#source-01-s07) | Read-only CLI, examples and operator guidance | S02–S06 |
| 8 | [SOURCE-01-S08](#source-01-s08) | Consumer-boundary checks, Windows evidence and handoff | S01–S07 |

### SOURCE-01-S01

**Objective and references.** Specify an implementable C03 registry/access boundary before adding behavior. Direct R02/R15; supporting R14/R16 and identity boundary R04. Blueprint §§4/C03–C05, 5, 6/SOURCE-01, 8–10; FND-01-S02/S04/S07/S08 handoff.

**Dependencies.** FND-01. No adapter, storage, profile, search-policy, live provider or credential prerequisite.

**Owned files.** Proposed `src/job_automation/sources/__init__.py`, `models.py`, `errors.py`; `tests/sources/test_contract_boundary.py`; `tests/fixtures/sources/README.md`; decision/API sections of `docs/components/SOURCE-01.md`. Coordinated changes only as decided: `contracts/sources.py`, public exports, `configuration.py`, schema exporter and affected generated C03/app schemas, C03 fixtures/generator and affected contract tests. Do not implement or change `Adapter` signatures to add fetching.

**Inputs → outputs.** Blueprint and actual C03 v1.0 → supported wire/semantic versions, registry envelope, typed review/scope/request metadata specification, result/diagnostic API and explicit compatibility plan. Proposed result contains effective C03 plus checked policy/scope metadata and blockers/warnings; there is no C05 or C04 production.

**Tasks.**

1. Map every existing C03 field to validation, unknown/default behavior, consumer and ownership. Distinguish structural readability, readiness for selection, and actual adapter availability; a source can be inspectable but not runnable.
2. Close representation decisions D01–D08 sufficiently for subsequent stories: access basis/restrictions, attribution, manual origin, request settings, source identity, inventory scope and selected-result shape. Choose exact versions and supported keys; dependent stories implement this specification rather than independently redesigning C03.
3. Prefer additive, explicit C03 metadata for information downstream consumers need. Retain legacy human-readable `access_rules`/`attribution_rules` as notes, never executable permission checks. Validate `request_policy` into a typed effective policy without silently changing the existing wire type. Record any necessary incompatible alternative and its upgrade path.
4. Define registry and per-source diagnostics using `ValidationIssue` and `ClassifiedError`: missing configuration, validation, permission and unsupported input are distinct; these local checks do not retry. Specify safe field-path/error-code output and avoid attaching raw invalid values.
5. Define a detached/immutable selection snapshot so caller mutation of a nested policy cannot bypass validation. Specify which effective metadata consumers receive, including exact C03, review state, request settings, attribution and scope identity.
6. Record consumer changes required for SOURCE-02/03 and INGEST-01 to use checked selections later. Existing `Adapter.fetch_page(config, cursor)` is a downstream boundary, not an implementation task or authorization mechanism here.

**Acceptance examples.**

- The existing disabled C03 fixture remains inspectable under the documented legacy reader, but its prose and `timeout` dictionary do not become permission evidence automatically.
- An unknown `schema_version="99.0"` yields an unsupported-version error; the inherited default string does not count as version validation.
- `source_key="board-a-finance"` identifies a configuration; `SourceKey(provider="fixture_ats", board_id="00042", source_posting_id="007")` identifies a posting. The published API distinguishes them.
- A pasted-text source has a specified local/manual origin path; no implementer must invent an HTTP URL or assume permission to visit an attached URL.

**Tests.** Supported/legacy/future version matrix, typed result and diagnostic round trips, exact enum values, unknown fields, nested snapshot mutation and affected schema/fixture compatibility. Verify module import does not create files, initialize storage or connect to services.

**Native Windows verification.** Import the new package and run boundary/affected contract tests with the explicit `.venv\Scripts\python.exe` path. Record interpreter/platform, not merely the foundation's historical result.

**Migration/configuration impact and handoff.** No database migration. Publish the C03/envelope/app-config versions, minimal shared changes, legacy read/upgrade behavior and exact signatures. Resolve D01 and representation portions of D02–D08 before dependent stories are accepted; D09 can stay pending.

### SOURCE-01-S02

**Objective and references.** Load a deterministic local registry and preserve provider/board identity. Direct R02/R15; supporting R14 and R04 source identity. Blueprint §§3–5, 6/SOURCE-01, 8–9; C03, `SourceKey`, `AppConfig`/`ResolvedPaths`.

**Dependencies.** S01 and FND-01 configuration/error conventions.

**Owned files.** Proposed `sources/registry.py`, `sources/validation.py`, loader portions of `sources/models.py`; minimal `configuration.py` changes and generated app-config schema; `tests/sources/test_registry.py`, `test_identity.py`, additions to `tests/test_configuration.py`; synthetic registry fixtures.

**Inputs → outputs.** Explicit registry path or app-config reference plus local JSON → indexed C03 entries, resolved origin path and safe structural diagnostics. No network lookup or posting records.

**Tasks.**

1. Implement the versioned JSON envelope from S01. Reject malformed JSON, duplicate JSON object members, duplicate `source_key` entries, unsupported versions and wrong field types. An empty source collection is known-empty; missing/unreadable files are missing configuration, not an empty registry.
2. Add the agreed optional source-registry reference and resolved path. Use `pathlib.Path`; resolve a relative registry against the app-config parent and any registry-relative local references against the registry parent. Define explicit CLI override precedence; use no implicit scan of the working directory.
3. Preserve provider/board identifiers and source keys exactly under D03. Reject whitespace-only or padded identity fields without trimming into collisions. Require board/tenant identity even for providers with one feed: choose a documented source-local identifier, not a shared accidental blank. No company identity or posting ID is invented.
4. Permit two different scoped configurations for the same provider/board; they must share the same posting namespace downstream. Reject duplicate keys and report duplicate effective scope declarations according to D03. Do not case-fold opaque board IDs or infer an employer from a hostname/display name.
5. Keep explicit empty selection compatible with existing app configs that have no registry reference. A nonempty requested selection without a registry must fail. Existing `config check` must not imply source readiness unless it actually invokes the new validation path.
6. Handle file read/encoding/type failures with safe diagnostics. Read local configuration only; URLs in evidence metadata are not fetched. Preserve source file bytes and release handles after reads.

**Acceptance examples.**

- `fixture_ats/board-A/007` and `fixture_ats/board-B/007` remain distinct posting namespaces; board `"00042"` remains a string with its leading zeros.
- Two entries `board-a-all` and `board-a-finance` can share provider/board while declaring different scopes. Two `board-a-all` keys fail rather than selecting the last definition.
- A registry at `C:\Source Prüfung\config\sources.json` referenced relatively by its app config resolves identically after changing the process working directory.
- Missing registry plus `active_sources=["board-a-all"]` fails; `active_sources=[]` selects nothing and does not discover defaults. A misspelled `enabeld` field cannot silently disable or enable anything.

**Tests.** Missing/unreadable/malformed/duplicate-member files; supported version/type handling; duplicate identities; opaque IDs; multiple scopes per board; absent registry/empty selection distinction; config-relative paths; UTF-8/BOM policy; unchanged file bytes and released handles.

**Native Windows verification.** Run registry/config tests and load fixtures copied to a temporary directory containing spaces and `Prüfung ä`. Repeat from a different working directory with absolute interpreter/app-config paths. Rename a read file afterward to verify no leaked Windows handle.

**Migration/configuration impact and handoff.** Optional app-config field preserves old structural loading; old nonempty selections become visibly unconfigured at the new selection boundary. No automatic registry creation or rewriting of user config. Close D02/D03 and loader portions of D10; record exact path precedence and encoding.

### SOURCE-01-S03

**Objective and references.** Make access basis and attribution inspectable, scoped and enforceable at selection. Direct R02/R15; supporting R16. Blueprint §§4/C03, 6/SOURCE-01/SOURCE-03, 7, 10–11. R02 requires permitted sources; public accessibility is insufficient evidence.

**Dependencies.** S01/S02. Real source review is an external configuration dependency, not required for synthetic validation tests.

**Owned files.** Proposed `sources/access.py`, access/attribution models and validators; `tests/sources/test_access.py`, `test_attribution.py`, synthetic review fixtures; access-policy sections of the component handoff. Shared C03 schema/fixture changes only through S01's agreed contract plan.

**Inputs → outputs.** C03 plus recorded review/evidence → review/readiness diagnostics and preserved attribution/reuse metadata. The validator checks supplied evidence metadata; it does not claim to verify external terms by itself.

**Tasks.**

1. Validate explicit access state, evidence reference(s), reviewed-at UTC value, reviewed method/provider/board/endpoint scope, permitted operations/use and relevant constraints. Keep a reviewed denial distinguishable from missing review. Define review identity/provenance sufficiently to explain who/what recorded the decision without storing credentials.
2. Define how known expiry, changed endpoint/method/board, changed terms reference or conflicting evidence blocks or invalidates the recorded decision. Do not invent universal legal conclusions or a provider-wide grant from a single reviewed URL.
3. Require source-specific review for `permitted_scraping`, including applicable site access/robots restrictions and attribution. Neither a robots allow rule nor an HTTP 200 is the entire permission basis. API review remains scoped to API use; manual-import review records supplied-content use/provenance and no permission to retrieve a target.
4. Preserve attribution state, exact required text/link, evidence basis and relevant retention/redistribution constraints. Unknown attribution is a readiness gap; explicit reviewed none-required is valid. Required notices must be nonempty and available to downstream consumers, without rendering/publishing them here.
5. Allow disabled draft entries to be listed with incomplete-review warnings/readiness blockers. Enabled/selected entries must pass the applicable review requirements; `enabled` and `active_sources` cannot override denial, absent evidence or scope mismatch.
6. Keep evidence documents and credentials outside tracked examples. Treat notes/references as inert data; only configured local metadata is read, and ordinary diagnostics expose safe state/reason fields rather than whole evidence records.

**Acceptance examples.**

- An enabled API entry with `access_rules="public website"` and no scoped evidence is blocked with an access-review reason, even if a test describes the URL as reachable.
- A synthetic API permission for board A does not permit HTML scraping or board B. Changing either scope requires a matching review before selection.
- `attribution_rules=null` remains unknown. A reviewed none-required record passes; required text `"Source: Synthetic Board"` and its link survive the selection output exactly.
- An explicit denied entry remains denied after toggling `enabled`; a disabled unreviewed entry stays inspectable and cannot run.
- A supplied job URL plus pasted text remains a manual-input declaration. It does not authorize a future HTTP request to that URL.

**Tests.** Access-state × enabled/selected matrix; missing/conflicting/expired/mismatched evidence; acquisition-method changes; robots-only/public-only non-grants; attribution unknown/required/none-required; UTC review values; malicious instruction-like notes; secret markers never appear in diagnostics. Synthetic “permitted” fixtures are test records only.

**Native Windows verification.** Execute access/attribution tests offline. Read review metadata from Unicode/space paths and confirm checks do not visit evidence URLs or require browser/network services.

**Migration/configuration impact and handoff.** Legacy prose remains readable but is not retroactively approved. Record D04 status semantics, evidence scope and pending real reviews under D09; no access permission or current terms are asserted by this story.

### SOURCE-01-S04

**Objective and references.** Validate acquisition-specific configuration and bounded request intent without issuing requests. Direct R02/R15; supporting R14/R16. Blueprint §§4/C03 and error boundaries, 6/SOURCE-01/INGEST-01, 8–10.

**Dependencies.** S01/S02; S03 supplies reviewed source restrictions. No HTTP client or adapter dependency.

**Owned files.** Proposed `sources/request_policy.py`, acquisition/origin validators; `tests/sources/test_request_policy.py`, `test_acquisition.py`; synthetic request-policy fixtures. Update C03/schema fixtures only as agreed in S01, including the legacy fixture generator.

**Inputs → outputs.** C03 acquisition method, origin/endpoint, request-policy dictionary and reviewed constraints → typed effective policy or field-level blockers; original metadata remains inspectable. No request, import, sleep, retry or credential lookup occurs.

**Tasks.**

1. Define method-specific requirements for `api`, `permitted_scraping`, `manual_import`. Automated methods need a syntactically valid, reviewed endpoint; a manual origin can be supplied provenance or the agreed local-only representation. Reject unsupported methods and incompatible settings.
2. Validate endpoint schemes, hosts/paths, userinfo and fragments according to the declared policy. Proposed automated default is HTTPS; any supported exception must be explicit and reviewed. Do not transform Windows paths into URLs or turn origin URLs into scrape targets. Validate redirects/allowed targets as configuration if supported; follow none.
3. Specify a finite request vocabulary: finite positive timeout in seconds; request spacing/rate with explicit units; bounded attempts/backoff/cap; page/item or run budgets; declared non-secret headers, parameters and any caching/conditional-request settings consumers support. State defaults and whether attempts include the first request. Distinguish unset values from zero, false and unknown limits.
4. Validate numeric types/ranges and cross-field consistency, including booleans passed as numbers, NaN/infinity, negative/zero timeouts, unbounded retries and contradictory backoff caps. Reviewed source limits take precedence over a more aggressive configured policy; reject a conflict visibly rather than silently claiming compliance.
5. Use explicit credential-reference metadata only if required. Reject inline auth/cookies/API keys, URL userinfo and known secret-bearing query/header fields; generic strings cannot be guaranteed secret-free, so diagnostics use an allowlist. Never resolve secret values during registry validation or accept arbitrary executable hooks/import paths.
6. Define supported parameter types and which settings affect inventory membership for S05. Keep query/filter declarations consistent across the URL, request parameters and scope descriptor; do not parse arbitrary provider expressions or embed job-matching logic.
7. Resolve the current `timeout` key: explicitly support an identified legacy alias with a visible migration path, or return a precise upgrade diagnostic. Unknown keys and conflicts between old/new forms must not be silently ignored.

**Acceptance examples.**

- A synthetic timeout of 30 seconds, finite request spacing and bounded attempts round-trip with named units. These test values are not provider limits.
- `timeout_seconds=0`, `max_attempts=-1`, a boolean timeout or unbounded backoff fails. A typo such as `timeuot` fails instead of taking an accidental default.
- A reviewed synthetic maximum of one request per second conflicts with a configured ten requests per second; selection is blocked without making a request.
- `https://user:token@board.invalid/jobs` and a literal authorization header fail with safe field paths, without echoing their values.
- A manual source with pasted text needs no HTTP timeout or pretend endpoint; a URL reference never changes its method to API/scraping. Manual content parsing remains SOURCE-02.

**Tests.** Enum/method-specific matrix; URL syntax and secret-bearing values; allowed non-secret headers/parameter types; numeric boundaries and nonfinite values; retry/backoff consistency; reviewed-limit conflicts; legacy timeout compatibility; manual origin; no-network/no-secret-resolution assertions.

**Native Windows verification.** Run acquisition/request-policy tests with the native interpreter, including correctly escaped JSON Windows paths for manual provenance. Confirm tests use no timer sleeps or external services.

**Migration/configuration impact and handoff.** Publish exact effective policy keys/units/defaults, legacy handling and enforcement obligations for INGEST-01/adapter consumers. Close D05/D06. SOURCE-01 validates configuration; it must not report runtime rate limiting, retries, caching or authentication as implemented.

### SOURCE-01-S05

**Objective and references.** Describe coverage honestly and produce comparable inventory scope identities. Direct R02; supporting R04/R16 and safe-source constraint R15. Blueprint §§4/C03–C04, 5 source disappearance rules, 6/INGEST-01/IDENTITY-02, 7.

**Dependencies.** S01–S04 for identity, reviewed endpoint and effective parameters.

**Owned files.** Proposed `sources/inventory.py`, scope models; `tests/sources/test_inventory.py`, `test_scope_identity.py`; synthetic scope/manifest handoff fixtures. C04 remains a consumer contract; any necessary additive metadata change follows S01/FND-01 coordination, not an availability implementation.

**Inputs → outputs.** Effective C03 and explicit membership/coverage declaration → versioned scope descriptor, deterministic `scope_id`, completeness prerequisites and safe coverage explanation for future C04 creation. No fetch manifest is produced from a configuration check.

**Tasks.**

1. Enforce the three inventory meanings in the table below. A whole employer board means that configured board's documented listing universe, never the provider's entire service or the German job market. Record intrinsic visibility/region/language/time-window restrictions where they affect the universe.
2. Require explicit semantics and supporting scope evidence for runnable sources; a legacy omitted value may be read conservatively as `search_results`, never promoted to `complete_board`. A manual selection of postings cannot claim whole-board coverage without a separate documented exhaustive export contract; keep that extension pending by default.
3. Define the scope descriptor's membership fields: provider, board/tenant, acquisition method, endpoint/dataset, inventory kind, query/filter/category, region/language/visibility and stable access audience where relevant. Record result caps, rolling windows and ranking constraints. Query/filter facts live in one defined representation and must agree with request settings.
4. Derive `scope_id` using documented canonicalization and an algorithm/descriptor version. Preserve semantically ordered values; normalize only declared set-like collections. Exclude page cursor, fetch timestamp, transient transport headers, timeout and retry policy from membership identity. Never include secrets.
5. A membership-changing edit produces a new scope ID. A source-key rename does not merge old histories; C04 comparison requires an explicit source identity mapping and same compatible scope. Old manifests with insufficient scope evidence remain incomparable rather than becoming complete retroactively.
6. Pass scope ID/semantics and conditions to INGEST-01 for C04. Document that successful exhaustive pagination of the same scope, no truncation/failure and later IDENTITY-02 grace/repeated-miss rules are still necessary. A configured board plus a page cap cannot justify completeness after truncation.
7. Keep absence inference outside this component. No source or canonical job becomes `not_seen`/`unavailable` because a registry changed, a source was disabled, or a filtered/search result was empty. An active alternate source remains relevant to IDENTITY-02.

| Inventory value | Coverage declaration | Meaning of later C04 `outcome=complete` | Disappearance boundary |
|---|---|---|---|
| `complete_board` | Exhaustive published inventory for one explicitly identified board/universe, supported by source behavior evidence | Consumer asserts that the entire declared inventory was successfully exhausted, without truncation | Can supply evidence only for the same comparable scope; never closes a job by itself |
| `filtered_feed` | A category/filter, subset, rolling feed or other limited discovery inventory | Processing of that declared feed completed; this says nothing about the rest of the board | Absence may mean no longer in that subset. Baseline forbids using it to infer source/canonical closure; any future narrower membership policy belongs to IDENTITY-02 |
| `search_results` | Query/ranked/limited discovery results, with explicit query/scope | Search execution completed, even if it returned zero results | Absence cannot prove closure, including when all returned pages were read |

**Acceptance examples.**

- A synthetic exhaustive board has no role filter and a documented board universe. Adding `department=finance` requires a filtered scope/new scope ID; it cannot keep an unrestricted complete-board declaration.
- Reading all ten pages of ranked search remains `search_results`. An empty successful search creates no disappearance authority.
- Berlin versus Munich, changed query, board, visibility or rolling-window definition yields different scope identity. Reordered JSON object keys, changed timeout or next-page cursor does not change membership identity.
- A complete-board declaration with a partial/failed future C04 or an exhausted page budget cannot support disappearance. A successful empty complete board may become evidence for IDENTITY-02, subject to its own policy; SOURCE-01 changes no availability.
- Disabling a source or narrowing a feed changes selection/coverage reporting only. It does not close jobs previously seen there.

**Tests.** All inventory values × complete/partial/failed consumer fixtures; complete-board contradictions; explicit/omitted semantics; search/filtered empty results; changed/unchanged scope matrix; deterministic canonicalization; unknown legacy scope; manual subset; identity separation. These are boundary/metadata tests, not an availability state machine.

**Native Windows verification.** Run scope/inventory tests in independent processes and verify stable IDs for the same fixture, including non-ASCII query text. No filesystem separator conversion may alter URLs or scope content.

**Migration/configuration impact and handoff.** Close D07, document scope version/canonicalization and C04 mapping, and retain unknown legacy scope as unknown. No database migration or backfilled manifests. Actual source completeness evidence remains SOURCE-03/INGEST-01 live work.

### SOURCE-01-S06

**Objective and references.** Provide one checked boundary through which only configured, enabled, permitted and valid requested sources can be selected. Direct R02/R15; supporting R16. Blueprint §6/SOURCE-01 completion criterion, §§4/C03, 5, 8.

**Dependencies.** S02–S05. SOURCE-02/03 and INGEST-01 will consume this boundary later; they are not implemented here.

**Owned files.** Proposed `sources/service.py`, selection result models/public exports; `tests/sources/test_selection.py`, `test_snapshot.py`; a test-only consumer recorder in `tests/fakes/source_registry_consumer.py` if useful.

**Inputs → outputs.** Loaded registry and requested keys (`AppConfig.active_sources` or explicit selection) → detached validated C03 selections with effective access/attribution/request/scope metadata, or blocking diagnostics. Inspection can still show each entry's status. There is no dispatch/fetch call.

**Tasks.**

1. Implement the D08 selection contract consistently for CLI and future programmatic consumers. Requested order is deterministic; duplicate requested keys yield a visible error rather than duplicate work. Empty selection returns an explicit empty result, never all enabled entries.
2. Check existence, structural/semantic validity, enabled status, access readiness, attribution, method/request policy and inventory scope. Explicit single-key lookup must apply the same gate as batch selection; avoid a convenience path that returns an unchecked executable C03.
3. Distinguish configured/disabled, configured/enabled-but-unselected, selected-ready and selected-blocked. Enabled is operator intent; it does not imply a registered implementation or verified network access. Future missing adapter capability is an explicit SOURCE-02/03/INGEST-01 configuration error, never dynamic import from config.
4. Return no executable selection when any explicitly requested key has a blocker; include all safe reasons and preserve inspectable valid entries separately. Do not silently narrow the user's requested coverage. This preflight rule does not change INGEST-01's independent handling of failures after acquisition starts.
5. Return copies or immutable views of nested structures. Subsequent file/caller edits must not mutate a selection already validated; a new selection reads/revalidates the new configuration. Do not maintain an unvalidated process-global mutable cache.
6. Publish downstream use obligations: obtain checked selections before adapter invocation, carry exact provider/board/scope metadata and honor request/attribution restrictions. SOURCE-01 cannot guarantee arbitrary callers obey this until the later integration gate is wired; state that verification limit.

**Acceptance examples.**

| Registry/config situation | Requested keys | Required result |
|---|---|---|
| Valid, reviewed, enabled `alpha` | `[]` | Empty selection; no source runs |
| Valid, reviewed, disabled `alpha` | `["alpha"]` | Disabled blocker, no executable selection |
| No entry named `missing` | `["missing"]` | Missing-configuration blocker |
| Enabled `alpha`, unknown/denied access | `["alpha"]` | Permission/readiness blocker; enabled cannot override it |
| Enabled and fully validated `alpha` | `["alpha"]` | One checked selection; zero adapter calls |
| Valid `alpha`, blocked `beta` | `["alpha", "beta"]` | Both statuses visible, request rejected without silently dropping `beta` |
| Valid `alpha` | `["alpha", "alpha"]` | Duplicate-selection diagnostic; never duplicate work |

- Mutating the original request-policy dictionary after validation cannot change the result's timeout, target, permission state or scope.
- Disabling a source requires no posting deletion or availability update. A later selection reflects the disabled status; no already-produced historical C04 is rewritten.

**Tests.** Table-driven selection matrix, direct lookup parity, mixed/duplicate selections, immutable snapshot behavior, safe diagnostics and fake-consumer boundary checks. A fail-on-call adapter/network stub verifies checking and listing call neither acquisition method nor draft mapping.

**Native Windows verification.** Run selection/snapshot tests without services or a database; confirm imports and checks create no runtime data directory. Record this as isolated registry verification, not a live-run gate.

**Migration/configuration impact and handoff.** Close D08, publish exact lookup/selection signatures, statuses and failure behavior. Explain required later wiring and the distinction between permission validation and installed adapter capability. No run ledger, worker or dispatch loop is introduced.

### SOURCE-01-S07

**Objective and references.** Make source configuration reviewable through read-only native Windows commands and clearly synthetic examples. Direct R02/R15; supporting R14/R16. Blueprint §§3, 6/SOURCE-01, 8–10.

**Dependencies.** S02–S06 and current CLI; coordinate shared registration with existing storage/profile commands and future POLICY-01 wiring.

**Owned files.** Proposed `sources/cli.py`; minimal `src/job_automation/cli.py` registration/dispatch; `config/sources.example.json`, adjusted `config/app.example.json`; `tests/test_cli_sources.py`; `tests/fixtures/sources/` CLI fixtures; source usage sections of `README.md` and future component handoff.

**Inputs → outputs.** Explicit app-config/registry path and optional key selection → safe human-readable or JSON registry status and exit code. No config edits, network access or source execution.

**Tasks.**

1. Add proposed `sources list` for inspection and `sources check` for validation/selection. Both use the same loader/service. Specify `--config`, `--registry`, `--source` (repeatable explicit selection), `--data-root` where reusing app config, and optional `--json`. Reject conflicting/ambiguous input combinations.
2. Check the whole registry structurally and report readiness of all entries. Disabled draft review gaps may remain warnings/readiness blockers without making an explicitly empty selection fail; any malformed structure or requested blocked entry returns 2. A successful check is labelled offline configuration validation, never “source reachable” or “permission independently verified.”
3. Show source key, provider/board, method, enabled/selected state, access/attribution readiness, inventory semantics/scope ID and safe issue codes. Avoid dumping policy headers/parameters/URLs/evidence wholesale. Machine output uses the same safe allowlist.
4. Supply disabled synthetic API board, filtered feed, ranked search, permitted-scraping draft and manual-import examples. Include non-technology scope examples such as finance/operations without making them user preferences. Unknown review stays unknown; clearly mark synthetic reviewed test fixtures separately from operator examples.
5. Correct the orphan `arbeitnow_de` selection in the app example: proposed `active_sources=[]` plus a reference to the synthetic registry. Do not silently enable an actual provider to make the example pass. Document how to add an explicitly reviewed source later.
6. Document config-relative paths, methods, review evidence, empty selection, safe errors, inventory distinctions, legacy upgrade handling and downstream limits. Preserve existing CLI commands and side-effect expectations.

**Acceptance examples.**

- Checking the supplied disabled examples with `active_sources=[]` reports no selected sources, visible readiness gaps and exit 0 when structure is valid. It makes zero network calls and creates no runtime data.
- Explicitly selecting a disabled, unknown or unreviewed example returns 2 with source key and reason. Neither stdout nor stderr contains a synthetic credential inserted into a rejected policy.
- `sources list --json` shows `filtered_feed` and `search_results` separately and never reports “complete board” merely because the configuration is valid.
- Existing `--help`, `--version`, configuration, storage and profile CLI tests retain their prior behavior.

**Tests.** Subprocess CLI checks for exits 0/2, text/JSON parity, invalid flags, missing registry, disabled/unconfigured selection, empty selection, safe diagnostic fields, unchanged inputs, no database/network side effects and existing CLI regressions.

**Native Windows verification.** Execute the commands in the verification recipe below, including explicit interpreter paths, spaces/umlauts, changed working directory and an invalid source. Capture output and exit codes; no Bash or activated shell is assumed.

**Migration/configuration impact and handoff.** Close D10. Example changes are local synthetic documentation, not changes to the user's real configured providers. Record exact command syntax and configuration versions; do not create a live-source approval workflow or fetch command here.

### SOURCE-01-S08

**Objective and references.** Demonstrate SOURCE-01 acceptance and leave a precise handoff for later acquisition components. Direct R02/R15; supporting R14/R16 and C03–C05 identity/inventory boundary. Blueprint §§6–10 and G1/G2 limitations.

**Dependencies.** S01–S07. Use fixtures/fakes for all downstream consumers; no provider access, model runtime, Salesforce or database prerequisite.

**Owned files.** `tests/sources/test_consumer_boundary.py`, source fixture catalog/README and necessary focused tests from prior stories; final `docs/components/SOURCE-01.md`; source verification instructions in `README.md`. Shared regression tests are changed only for agreed contract/config updates.

**Inputs → outputs.** Implemented registry and synthetic cases → recorded automated results, native Windows evidence, schema/compatibility checks and component acceptance status with pending integrations.

**Tasks.**

1. Exercise the full local path: app config → registry → access/request/inventory validation → checked selection → test-only recorder. Confirm exact C03/provider/board/attribution/scope metadata and blocked selections; the recorder stores received values and performs no adapter logic.
2. Add consumer examples constructing C04 fixtures from the declared scope, while documenting that only INGEST-01 can assert actual execution completeness. Cover complete/partial/failed and empty outcomes for all three inventory kinds. Do not implement fetching or disappearance logic merely to test this boundary.
3. Check changed shared schemas against the exporter and positive/negative fixtures. Test model/schema structural parity if a JSON Schema validator is adopted, and explicitly distinguish semantic checks that require the registry service. A JSON file parsing successfully is not schema conformance. Record any added dev dependency rather than claiming existing dependencies already provide this check.
4. Run focused source/config/CLI/contract tests, then the existing regression suite after affected checks pass. Include native Windows path/encoding/handle tests and safe diagnostics. No live fetch is required or performed for SOURCE-01 acceptance.
5. Produce the component handoff: status, requirements, dependency and contract versions, files changed, public inputs/outputs, decisions, actual commands/results, native Windows evidence, fixture/fake results, live checks not applicable/pending, limitations and next consumers. Do not reuse FND-01 counts as new results.
6. Keep D09's real-source choices/evidence pending if unavailable. Mark implementation VERIFIED only when declared component acceptance passes; fake boundary success is not SOURCE-03, INGEST-01, G1/G2 or end-to-end verification.

**Acceptance examples.**

- A test selection carries board `"00042"`, required synthetic attribution, bounded request metadata and the same scope ID into a recorder/C04 example without any external call.
- Unknown/disabled/unreviewed configurations never reach that recorder; complete search execution remains search semantics and grants no closure authority.
- The handoff explicitly names SOURCE-02 as the next consumer, with later SOURCE-03/INGEST-01 and IDENTITY-02 obligations, and distinguishes completed component checks from pending real permission/completeness checks.

**Tests and native Windows verification.** Execute the component matrix and PowerShell recipe below; record actual Python/dependency versions and OS. If the existing virtual environment is unusable, report the exact limitation and restore it through the documented foundation setup before claiming test success. Documentation-only planning does not repair the environment.

**Migration/configuration impact and unresolved decisions.** Audit closure of D01–D08/D10, explicit shared-contract migration notes and unchanged historical record interpretation. No storage migration is expected. D09 remains an external configuration/adapter prerequisite when real evidence has not been supplied.

## Verification matrix and native Windows recipe

These are **future implementation checks**, not results of this planning session. All fixture identities, evidence, URLs and limits are synthetic. Avoid external calls throughout.

| Area | Required evidence | Owning stories |
|---|---|---|
| C03 and compatibility | Supported/legacy/future versions; all fields; generated schema/fixture alignment; no silent permission upgrade | S01, S08 |
| Identity/loading | Duplicate JSON members/keys; opaque provider/board values; multiple scopes on one board; missing versus empty registry | S02 |
| Access/attribution | Public/robots-only non-grants; scoped review; denied/unknown/expired/mismatched evidence; required versus unknown versus none-required attribution | S03 |
| Acquisition/policy | All three methods; endpoint/manual origin; units/bounds/legacy keys; reviewed-limit conflicts; credential-safe errors; no request execution | S04 |
| Coverage/scope | Board/feed/search distinctions; scope change matrix; partial/failed/empty cases; unknown legacy scope; no availability mutation | S05 |
| Selection | Enabled/selected/readiness matrix, direct lookup parity, empty/mixed/duplicate selections, detached snapshots | S06 |
| Operator surface | Exit codes, safe text/JSON, examples disabled, config-relative paths, regression of current commands | S07 |
| Native Windows | Explicit interpreter, space/Unicode paths, changed working directory, file handles, no runtime directory/database/network side effects | S02, S07, S08 |
| Consumer handoff | Exact C03 and C04 scope metadata via test recorder; no adapter, import parser or availability engine added | S08 |

Run from the repository root in PowerShell after implementation. The syntax below is proposed by S07; update the recipe if the implemented CLI differs. Python uses `pathlib.Path`; documentation links use `/`; runnable PowerShell paths use `\`.

```powershell
$repoPath = (Get-Location).Path
$sourcePython = Join-Path $repoPath '.venv\Scripts\python.exe'
$sourceAppConfig = Join-Path $repoPath 'config\app.example.json'
$sourceRegistry = Join-Path $repoPath 'config\sources.example.json'
$sourceDataRoot = Join-Path $env:LOCALAPPDATA ('Job Automation Source Prüfung ä ' + [guid]::NewGuid().ToString('N'))

& $sourcePython -c "import platform, sys; print(sys.version); print(platform.platform())"
& $sourcePython -m pytest tests\sources tests\test_cli_sources.py tests\test_configuration.py tests\contracts
& $sourcePython -m pytest

& $sourcePython -m job_automation sources check --config $sourceAppConfig --data-root $sourceDataRoot
$validSourceExit = $LASTEXITCODE
& $sourcePython -m job_automation sources list --config $sourceAppConfig --data-root $sourceDataRoot --json
$listSourceExit = $LASTEXITCODE
& $sourcePython -m job_automation sources check --config $sourceAppConfig --data-root $sourceDataRoot --source 'not-configured'
$invalidSourceExit = $LASTEXITCODE
Test-Path -LiteralPath $sourceDataRoot
```

Expected: focused/full checks pass, valid empty-selection check and list exit 0, missing-key check exits 2, and the unique runtime data root remains absent. Record each actual result. Test disabled and enabled-but-unreviewed keys from the implemented fixture catalog as additional exit-2 cases. Do not run an adapter to establish any of these results.

Copy non-secret examples to a temporary directory to verify configuration-relative loading and native text handling. The following keeps all temporary writes inside one explicitly created directory and does not delete user data:

```powershell
$sourceProbeRoot = Join-Path $env:TEMP ('Source Registry Prüfung ä ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $sourceProbeRoot | Out-Null
$sourceProbeConfig = Join-Path $sourceProbeRoot 'app.json'
$sourceProbeRegistry = Join-Path $sourceProbeRoot 'sources.example.json'
Copy-Item -LiteralPath $sourceRegistry -Destination $sourceProbeRegistry
$sourceProbeSettings = Get-Content -LiteralPath $sourceAppConfig -Raw -Encoding UTF8 | ConvertFrom-Json
$sourceProbeSettings.source_registry_ref = 'sources.example.json'
$sourceProbeSettings.active_sources = @()
$sourceProbeSettings.data_root = $sourceDataRoot
$sourceProbeSettings.active_policy_ref = $null
$sourceProbeJson = $sourceProbeSettings | ConvertTo-Json -Depth 30
[System.IO.File]::WriteAllText($sourceProbeConfig, $sourceProbeJson, [System.Text.UTF8Encoding]::new($false))

Push-Location $env:TEMP
try {
    & $sourcePython -m job_automation sources check --config $sourceProbeConfig
    $changedDirectorySourceExit = $LASTEXITCODE
    & $sourcePython -m job_automation sources list --config $sourceProbeConfig --json
    $changedDirectoryListExit = $LASTEXITCODE
} finally {
    Pop-Location
}
Test-Path -LiteralPath $sourceDataRoot
```

Expected: identical registry/scope interpretation from a different working directory, both exits 0, no created runtime data root. Path/handle tests additionally rename a temporary registry after reading it. Use only explicitly created probe files for malformed, BOM, Unicode, unsupported-version and secret-marker cases. Inspect stdout/stderr for safe codes rather than raw values. No admin rights, WSL, Docker, paid service or real source account is needed.

## Completion and next-component handoff

The future `docs/components/SOURCE-01.md` must include:

- Component status and objective; R02/R15 plus supporting constraints; FND-01 prerequisite versions and current-code differences.
- Final owned files and coordinated C03/app-config changes; registry format, path rules, exact public interfaces, supported versions and migration treatment.
- Provider/board/config/posting/scope identity distinctions; enabled/selection rules and all access/attribution states, with no inferred permission.
- Effective request-policy keys/units/bounds and enforcement obligations; all three inventory semantics, stable scope algorithm, C04 mapping and limitations of absence evidence.
- Actual unit/contract and fake-consumer checks, schema alignment evidence, native Windows commands/results and unresolved environment limitations. Live provider validation is not performed by SOURCE-01.
- Remaining real source/employer selections, permissions, attribution, current limits and completeness evidence; owners and next actions rather than fabricated approvals.
- SOURCE-02: consume checked configurations and preserve manual-input provenance; SOURCE-03 instance: verify actual source rules/behavior and implement exactly one authorized adapter; INGEST-01: enforce request policy and produce honest C04 completeness; IDENTITY-02: apply same-scope availability/grace rules with alternate-source evidence; RUN-01: wire the checked selection boundary before execution and report actual coverage.

No fetching, permission inference from public access, job availability changes or live integration claims are part of this story plan.

[blueprint]: ../../IMPLEMENTATION_BLUEPRINT.md
[fnd]: ../components/FND-01.md
[data]: ../components/DATA-01.md
