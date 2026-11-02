# CONTEXT-02 — Versioned retrieval evidence preparation

Status: **PLANNED** · Planning date: **28 October 2026** · Phase 0 · Scope: **CONTEXT-02 only**

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), v1.0, especially §§4–6, 8 and 9. Direct requirement: **R06**; supporting constraints: **R11, R14, R15, R16**. These stories specify future implementation. They do not record implemented chunking or executed application tests.

## Objective and boundary

Convert an exact approved C01 profile and its purpose-filtered evidence into deterministic, versioned retrieval chunks. Preserve stable fact and parent references, precision dates, original skill metadata, provenance and permissions. Carry enough permitted parent context to interpret evidence, and surface a conflict when required context cannot be included. Every candidate assertion must come directly from approved facts. Changes, removals, permission changes and chunking-policy changes must produce explicit invalidation information.

Own chunk records, deterministic construction, source mappings, content fingerprints, manifest comparison and the consumer validity contract under `context/`. Reuse PROFILE-01 approval, inclusion and exact historical references. The output is a serializable chunk set and change report, not C09 or a retrieval result.

Exclude embedding calls, embedding model selection, vectors, keyword/vector index construction, index persistence and atomic index activation (CONTEXT-03/LLM-01/MODEL-02); query generation, ranking, top-k, prompt budgets, mandatory-context assembly and the selector (CONTEXT-01/04); profile intake/approval redesign, assessment, drafting, Salesforce and Phase 2. Chunking must work offline without a model service. A model input limit may later require a new chunking configuration; it never authorizes silent truncation by this component.

## Repository instructions and current baseline

Read the blueprint, [README](../../README.md), [schema instructions](../../schemas/README.md), [PROFILE-01 handoff](../components/PROFILE-01.md), relevant [FND-01](../components/FND-01.md) and [DATA-01](../components/DATA-01.md) handoffs, the [CONTEXT-01 plan](CONTEXT-01.md), and current profile, contract, model-boundary and test code. No applicable ancestor or repository `AGENTS.md` was found. Follow the blueprint's shared-contract change discipline, generated-schema workflow, synthetic-fixture policy and native Windows path conventions.

| Inspected code/evidence | Planning consequence |
|---|---|
| [C01](../../src/job_automation/contracts/profile.py), [validation](../../src/job_automation/profile/validation.py) | Validate approval, supported schema, unique IDs, graph integrity and dates before inclusion. Pydantic construction alone does not establish those invariants. The graph validator checks references/cycles but does not enforce the parent-kind guarantee claimed in the handoff; do not label every parent an employment role without checking its actual kind. |
| [InclusionRules](../../src/job_automation/profile/inclusion.py), [ProfileInclusionView](../../src/job_automation/profile/models.py), [ProfileService](../../src/job_automation/profile/service.py) | Reuse purposes `assessment`, `cv`, `cover_letter`. Empty permissions exclude facts. A permitted child retains an opaque restricted-parent ID, with a warning; required restricted facts raise a conflict. Missing mandatory IDs need an explicit boundary check. Current fact order is start year descending, nulls last, UUID tie-break; warning order is not stable. |
| [Approval mapping](../../src/job_automation/profile/approval.py) | Stable fact UUIDs, approved claims/skills/metrics and precision dates reach C01. Draft `is_ongoing` does not. C01 has one provenance string, chosen from summary/ID/fallback, rather than a version-bound structured provenance record. Preserve these limits; do not recover extra assertions from drafts. |
| C01 versus draft defaults | Draft permissions default empty; `CandidateFact.allowed_uses` defaults to all three purposes. Eligibility has defaults including `remote_eligible=True`. Preserve supplied approved values without claiming they establish explicit attestation. Schema/default corrections belong to PROFILE-01/FND-01. |
| [Profile repository](../../src/job_automation/storage/repositories/profiles.py), [references](../../src/job_automation/profile/references.py), [C08](../../src/job_automation/contracts/evidence.py) | Published snapshots and `(profile_version, fact_id)` references support historical audit. Validate candidate identity separately because C08 has no candidate ID. The provenance table permits upserts; its current contents are not an immutable extension of a historical C01. |
| [History comparison](../../src/job_automation/profile/history.py) | `compare_snapshots` omits `parent_id` changes and compares claims/skills/metrics as sets. It is insufficient as the sole invalidation input. Use complete canonical dependency values, including parent links, order and duplicates where preserved. |
| [Profile consumer fakes](../../tests/fakes/profile_consumers.py), [inclusion tests](../../tests/profile/test_inclusion.py) | Fake `chunk_<fact_id>` dictionaries establish inclusion parity only. They lack versioning, parent expansion, complete metadata and invalidation. Keep them test-only; new acceptance must inspect actual chunk output. |
| [Contract base](../../src/job_automation/contracts/base.py), [schema exporter](../../src/job_automation/contracts/export_schemas.py) | Records carry `schema_version`, forbid extras and are frozen, but nested containers still need defensive copies. Add auxiliary chunk contracts and generated schemas; do not overload C08 or C09. |
| Current package inventory and [model interfaces](../../src/job_automation/contracts/interfaces.py) | `context/` and `tests/context/` do not yet exist. A production `models/` package and embedding harness now exist, despite the earlier CONTEXT-01 plan's inventory. Their existence does not make model calls a chunking dependency. |

The PROFILE-01 handoff reports VERIFIED and remains the upstream integration reference. Its historical test results are not new verification of this component. Current code determines available behavior. CONTEXT-01's proposed shared preparation API is coordination input, not an implemented prerequisite; reconcile ownership before introducing overlapping modules.

## Proposed contracts and invariants

The requirements above are fixed. Names, layouts and defaults below are implementation proposals to freeze in S01, with unresolved choices recorded at the end.

### Input, output and source fidelity

Propose `EvidenceChunker.build(ChunkBuildRequest) -> tuple[ChunkSet | None, ClassifiedError | None]`, with exactly one non-null result. The request binds the approved `ProfileSnapshot`, candidate/profile identity, explicit purpose, inclusion-rule version, chunking settings/version and any explicitly required context IDs. Obtain the snapshot through PROFILE-01 in operational callers; a detached inclusion view or `is_approved` flag from arbitrary text is not a replacement for that boundary. Pure tests may supply validated synthetic snapshots.

| Record | Required content and meaning |
|---|---|
| `ChunkingSettings` | Schema, algorithm, identity-scheme, rendering and parent-policy versions; explicit granularity; any size guard with its unit and failure behavior. No embedding model, vector dimensions, top-k or similarity threshold. |
| `EvidenceChunk` | Stable UUID `chunk_id`; `chunk_version` content fingerprint; candidate ID, exact profile version and purpose; primary fact ID/kind; original direct parent ID; ordered permitted ancestor references and context; primary dates with precision, skills, metrics, provenance and original allowed uses; effective permissions; source-mapped content units and deterministic retrieval text; dependency fingerprints; contextual limitations. |
| `ChunkSourceMapping` | C08 candidate reference plus source field path, list position where applicable, and exact value or character span for a fragment. Distinguish primary evidence from ancestor context. Candidate assertions in text/metadata must map back to these sources; neutral field labels/separators are renderer syntax. |
| `ChunkSet` | Schema, candidate/profile/purpose bindings; approved snapshot fingerprint; inclusion/chunking/settings versions; ordered chunks and binding fingerprints; eligible fact IDs and coverage; exclusion count and safe ordered warnings; deterministic manifest fingerprint. No vector/index/query metadata or fabricated token counts. |
| `ChunkChangeSet` | Base/target manifest fingerprints, candidate/purpose, added/removed/changed/unchanged-content chunk identities, old/new binding references, reason codes and replacement-required flag. A diff is descriptive until the downstream owner applies it. |

Proposed v1 granularity is **one complete approved fact per chunk**, with separately attributed permitted ancestor anchors. Every eligible fact, including a title-only fact with no claims or skills, gets a primary chunk. Equal text under different fact IDs remains separate evidence. Preserve every primary field; a size guard returns a visible error rather than a shortened successful chunk set. Semantic splitting, overlap and aggregation across facts are not silently enabled; D02 must settle them before claiming that capability.

Use approved title, organization, claims, skills and metrics verbatim. Preserve qualifiers, negation, list order, duplicate entries, nulls and known-empty collections. Dates retain `value` and `precision`; null end dates never become “present,” and employment duration is not calculated. Skills remain attached to their source fact; parent skills are not inherited by a child, and aliases/proficiency/years of experience are not inferred. No LLM paraphrase, translation, résumé strengthening or new claim synthesis is permitted.

Preserve the exact C01 provenance string on each primary/ancestor source, even when it is only a summary or `unspecified`. Do not fetch source files, dereference URLs, interpret provenance strings as paths, or merge mutable provenance-table records into approved content. Richer page/span/document-hash provenance requires an upstream versioned approval binding. Character spans introduced for chunk fragments refer to the approved C01 field, not an invented location in the original document.

### Parent context and allowed uses

Permission filtering precedes parent expansion. Use the same PROFILE-01 inclusion view as JSON; never obtain restricted text through the unfiltered snapshot, an old citation, another purpose's chunk or a sibling. Include ordered permitted ancestor anchors with their exact kind, title, organization, dates/precision, parent ID, provenance and permissions. Record each anchor as its own source; missing child dates or organization remain missing on the child. Resolve chains within the same snapshot and preserve the real graph rather than flattening a project into a role.

The child carries its own original `allowed_uses`. Effective uses for a materialized chunk are bounded by the intersection of permissions of **every fact whose content is included**. In addition, the chunk set is bound to the requested purpose; it cannot be served for another purpose even if that purpose appears in the intersection. Preserve source permissions separately from this derived restriction.

Retain PROFILE-01's optional-private-parent behavior: the permitted child and its opaque parent ID remain eligible, restricted text is absent, and unavailable context is explicit. Such a record must not be advertised as fully contextualized. If the selected parent policy or caller requires that ancestor to interpret the chunk, return a permission conflict with no successful chunk set. A missing required ID is validation failure. Do not silently discard the child or broaden permissions. The proposed conservative policy treats ancestors as required for parent-dependent evidence; D03 must define a deterministic rule for optional/self-contained cases before implementation is accepted. A model must not guess whether hidden context is dispensable.

Explicit eligibility is not a `CandidateFact` and has no C08 fact UUID. Keep it outside retrieval chunks. CONTEXT-01/04 own mandatory eligibility and essential chronology that bypass top-k; chunks cannot replace that requirement. Carry exact profile binding and any supplied required fact IDs so those consumers can use the same snapshot. Reuse shared preparation if it exists at implementation time, without creating a second mandatory policy here.

### Identity, versions and determinism

Separate logical identity, reusable content and snapshot-specific evidence binding:

1. Proposed whole-fact `chunk_id`: deterministic UUIDv5 in a documented project namespace over the identity-scheme version, candidate UUID, purpose, primary fact UUID and fixed logical slot `whole_fact`. Profile version, claim text, dates, parent text, input-list position and timestamps are not identity inputs. This is a persistent identity derived from stable keys, not a content hash. A fact correction or reparenting retains its logical chunk ID; a new fact UUID creates a new identity.
2. `chunk_version`: SHA-256 over a versioned canonical projection of payload, exact primary metadata, complete dependency fact fingerprints, parent relationships, source locations, effective permissions and semantic chunking/rendering/settings versions. Exclude profile-version labels and machine timestamps from this content projection. Store source IDs/paths in it; keep snapshot-specific C08 version labels in the binding below. Conservatively hashing complete contributing facts also invalidates a child when an unrendered field of a contributing ancestor changes.
3. Each emitted chunk is bound immutably to `(candidate_id, profile_version, purpose, chunk_id, chunk_version)` and contains C08 references to that exact profile version. Its separate binding fingerprint covers the full serialized chunk, including those C08 references. Unchanged evidence in v2 may retain `chunk_id` and `chunk_version`, but requires a v2 binding; never reuse v1 citations by relabeling them.
4. The manifest fingerprint covers the exact snapshot binding, purpose/rule/settings versions, ordered binding fingerprints, coverage and deterministic warnings. Retain a separate approved-snapshot fingerprint from PROFILE-01's stored content hash if using a different canonical encoding; do not silently substitute hashing recipes.
5. Fix UTF-8 encoding, object-key order, separators, UUID/date serialization and array semantics. Do not normalize Unicode, whitespace or punctuation inside approved values. Sort facts using the shared inclusion order; ancestor chain order follows the graph. Stabilize warning/reason order without rewriting private text into diagnostics. Exclude build time/random request IDs from deterministic fingerprints.

If a future segmentation policy changes logical slots or boundaries, change the identity-scheme version and explicitly replace affected identities. Do not reuse an ordinal-based ID for a different fragment or use fuzzy text matching to manufacture continuity. Chunk-schema version, algorithm version, settings fingerprint and content version have distinct meanings.

### Invalidation and consumer validity

Build complete target output from the target approved snapshot and compare validated manifests. Correctness must not depend on receiving every historical event or trusting `ProfileDiff`. Derive reverse dependencies from all primary and ancestor source IDs/links, then compare complete dependency fingerprints. A full rebuild is an acceptable v1 implementation; change classification still identifies unaffected content for downstream reuse.

| Change | Required outcome |
|---|---|
| Same snapshot/settings/request repeated, including after restart | Identical ordered chunk bytes, identities, versions, references and manifest; empty change set. |
| Primary claim/title/date/skill/metric/provenance/permissions changes | Same logical ID where still eligible, changed content version and binding; old revision cannot be served for target inputs. |
| Parent or ancestor changes, including dates, permissions or `parent_id` | Invalidate every dependent chunk, including transitive descendants; regenerate permitted context or fail its required-context check. Unrelated branches retain content versions. |
| Fact removed or no longer permitted for the purpose | Remove its primary chunk from the target manifest and emit a removal/tombstone reference. Invalidate dependent chunks too; never keep old source text in target output. |
| Parent removed while child still references it | Invalid target graph: fail validation. Do not repair by attaching the child to another role. A valid explicit reparenting is processed as a dependency change. |
| New eligible fact | Add a new primary identity; do not merge with another fact because text matches. |
| Only unrelated evidence, approval metadata or explicit eligibility changes | New snapshot/manifest and exact new bindings; unchanged dependency content keeps content versions. Eligibility remains a mandatory-context concern for CONTEXT-01/04. |
| Rules/rendering/settings/algorithm changes | Rebuild target and record reason/version transition. Semantic changes invalidate relevant content; unknown compatibility requires full replacement. Identity-scheme changes retire old IDs. |
| Embedding model/configuration changes | No change to model-independent chunk identity/content; CONTEXT-03 invalidates incompatible embeddings/indexes using its own metadata. |

Export an exact-binding validator for downstream callers. A manifest built for v1, a different candidate/purpose, or old rules/settings cannot satisfy a v2 request even when text matches. A failed v2 build never authorizes fallback to a v1 manifest for current work. Historical records stay available for audit; their existence does not authorize new operational use. Choosing the active profile and revalidating already-frozen work belong to RUN-01/GEN-02; their requested binding must be checked at the consumer boundary. CONTEXT-02 does not implement a watcher or physically delete old indexes.

## Ordered implementation stories

All stories are **PLANNED**. Paths below are proposed future files; coordinated shared-file edits remain narrow. No application file is changed by this planning task.

| Order | Story | Dependencies | Deliverable |
|---|---|---|---|
| 1 | CONTEXT-02-S01 | PROFILE-01; existing FND-01 contracts | Chunk, settings, source-map, manifest and change contracts |
| 2 | CONTEXT-02-S02 | S01; PROFILE-01 inclusion/validation | Validated purpose-bound evidence and parent preparation |
| 3 | CONTEXT-02-S03 | S01–S02 | Lossless chunk assembly and exact source mappings |
| 4 | CONTEXT-02-S04 | S01–S03 | Stable IDs, content versions, snapshot bindings and deterministic manifests |
| 5 | CONTEXT-02-S05 | S02–S04 | Dependency-aware invalidation and strict consumer binding checks |
| 6 | CONTEXT-02-S06 | S01–S05 | Public offline service, safe errors and CONTEXT-03 handoff boundary |
| 7 | CONTEXT-02-S07 | S01–S06; existing DATA-01 via PROFILE-01 for integration tests | Lifecycle/Windows verification and component handoff |

### CONTEXT-02-S01 — Freeze chunk and manifest contracts

**Objective/references.** Formalize approved evidence preparation before implementing chunk logic. R06/R15; C01/C08 and blueprint shared-contract discipline.

**Dependencies.** PROFILE-01 handoff/code and existing FND-01 models. Coordinate with CONTEXT-01's preparation proposal and CONTEXT-03's future input boundary; neither model services nor a working index are prerequisites.

**Inputs → outputs.** Current C01/C08/inclusion contracts and the proposals above → typed request/settings/chunk/source-map/manifest/change records, public protocol, version policy and generated schemas.

**Owned files.** New `src/job_automation/contracts/evidence_chunks.py`; narrow exports/schema-registry edits in `contracts/{__init__,export_schemas}.py`; `context/{__init__,chunk_ports,chunk_settings}.py`; generated `schemas/v1/evidence_chunk*.schema.json`, `schemas/v1/chunk_*.schema.json` as registered, and `schemas/README.md`; `tests/context/test_chunk_contracts.py` and affected contract/schema fixtures.

**Tasks.** Freeze mandatory fields, exact-one-result semantics, candidate/purpose bindings, typed C08 source mappings, primary/ancestor separation and permitted warning fields. Record whole-fact granularity, hash projections and compatibility rules; close D01 and the identity part of D04. Define validation for duplicate IDs, missing metadata, invalid spans, unknown versions and incomplete coverage. Keep C01/C08/C09 meanings intact; any necessary incompatible shared change needs its own recorded migration/consumer decision.

**Acceptance criteria.** A synthetic chunk resolves primary and ancestor sources to one exact profile and distinguishes content version from binding. Missing purpose/profile/source mapping, malformed dates or unsupported schema cannot produce a valid export. An empty eligible set has a valid explicit empty manifest. No schema contains vectors, model digests or retrieval scores.

**Tests.** Positive/negative records, schema round trips, extra-field/unknown-version rejection, duplicate primary/binding keys, exact-one-result invariant and generated-schema consistency. Include distinct facts with identical text and source spans that exceed their approved field.

**Migration/configuration impact and handoff.** New auxiliary schemas, no SQLite migration or reinterpretation of stored C01. Publish exact field names and compatibility decisions; do not assign an invented C16 contract. If reusable CONTEXT-01 records now exist, import them and document ownership instead of duplicating them.

### CONTEXT-02-S02 — Prepare permitted facts and traceable parent context

**Objective/references.** Establish the common approved evidence universe and safe ancestor context. R06/R15; C01/C08, PROFILE-01 inclusion.

**Dependencies.** S01; `validate_snapshot`, `InclusionRules.evaluate_inclusion` and `ProfileInclusionView`. Shared CONTEXT-01 preparation is reused if implemented; otherwise wrap the existing profile API with chunk-specific preparation.

**Inputs → outputs.** Exact approved snapshot, purpose, settings and required context IDs → detached prepared facts, permitted ancestor chains, dependency descriptors and stable warnings, or classified validation/permission failure.

**Owned files.** `context/chunk_preparation.py`; `tests/context/test_chunk_preparation.py`; synthetic preparation fixtures. Narrow `profile/inclusion.py` and `tests/profile/test_inclusion.py` corrections only if shared missing-required-ID/warning behavior is fixed here rather than by CONTEXT-01; record the chosen owner once.

**Tasks.** Validate snapshot and candidate/version bindings before filtering. Check required IDs exist. Reuse inclusion rules without job-relevance filtering. Follow parent chains only within the snapshot, check actual kinds, and retain optional restricted-parent references without copying text. Resolve D03's required-context rule; do not decide from a model or private parent text. Compute source and effective permissions, preserve shared fact order, detach nested values and stabilize diagnostics.

**Acceptance criteria.** Assessment-only evidence is absent for CV; empty-permission evidence appears nowhere in emitted content. A permitted role → project → achievement chain carries the exact approved context of each ancestor. Private parent data never appears through a child. Required restricted context fails without a successful subset; an optional restricted parent stays opaque and visibly unavailable under the documented policy. Both JSON preparation/fake and chunk preparation start with identical eligible fact IDs.

**Tests.** Three supported purposes and unsupported purpose; unapproved/mismatched snapshots; duplicates/cycles/dangling parents; missing/restricted required IDs; multi-level chains and non-role parents; sentinel secrets in all parent fields; order stability across input permutations; defensive-copy mutation; empty eligible evidence. Test failure versus optional omission explicitly rather than treating both as a successful fully contextualized chunk.

**Migration/configuration impact and handoff.** Version parent-policy and any shared inclusion behavior changes. Do not change approved facts or reconstruct `is_ongoing`. Record upstream schema limitations and the exact context-conflict behavior for CONTEXT-03/04.

### CONTEXT-02-S03 — Assemble lossless chunks with field-level traceability

**Objective/references.** Produce retrieval text and structured metadata without adding claims. R06/R11/R15; C01/C08.

**Dependencies.** S01–S02; D02/D03 decisions closed for the supported v1 policy.

**Inputs → outputs.** Prepared permitted facts/anchors and frozen settings → complete chunk payloads, source mappings, coverage and rendering diagnostics before identity/manifest finalization.

**Owned files.** `context/{chunk_builder,chunk_rendering,chunk_traceability}.py`; `tests/context/{test_chunk_builder,test_chunk_traceability,test_chunk_parent_context}.py`; `tests/fixtures/context/chunks/` fixture catalog and payload examples.

**Tasks.** Implement one primary fact per chunk with all approved primary fields, separately attributed ancestor anchors and deterministic text labels. Every rendered assertion/value must have an exact approved field mapping. Retain original skills and metrics without alias expansion or parent-to-child inheritance. Verify coverage of every eligible fact and every primary evidence field. If size guards are configured, measure in the declared unit and fail visibly on overflow; never call a model, drop text or silently split. Preserve candidate/job-text-looking strings as inert data.

**Acceptance criteria.** “Contributed to” stays “Contributed to”; a verified metric and its qualifier remain together. A month-only date stays month-only and null end date stays unknown. Two roles using the same skill remain separate chunks with the correct organizations. A child with no date retains null own dates alongside labeled parent dates. All permitted title-only, skill-only and non-employment facts are covered. Tracing any source-bearing output value finds an exact approved field in the declared snapshot.

**Tests.** Full-field fidelity including null/empty values and list duplicates/order; qualifiers/negation; German/English and Unicode; long claims; mixed precision dates; multiple employers; identical text with different UUIDs; malformed/stale mappings; provenance-string fidelity; raw-file/network/model spies; hostile instruction-like claims treated as text. Test configured size boundaries and no partial success. If splitting is selected in D02, add source-span, overlap, no-loss and qualifier-preservation tests before enabling it.

**Migration/configuration impact and handoff.** Publish the exact rendering/source-path conventions and supported size behavior. No tokenizer or hardware-safe token count is presumed. Rich provenance enrichment and unsupported splitting remain explicit limitations, not inferred data.

### CONTEXT-02-S04 — Assign stable identities and immutable version bindings

**Objective/references.** Make chunk creation reproducible and distinguish content reuse from evidence-version reuse. R06/R16; blueprint identity rules and C08.

**Dependencies.** S01–S03; D04/D05 canonicalization and identity decisions.

**Inputs → outputs.** Complete payloads, dependency records and exact approved snapshot/settings → finalized chunk IDs/content versions, C08 bindings and canonical `ChunkSet` bytes/fingerprint.

**Owned files.** `context/{chunk_identity,chunk_serialization,chunk_manifest}.py`; `tests/context/{test_chunk_identity,test_chunk_serialization,test_chunk_reproducibility}.py`; golden synthetic canonicalization fixtures.

**Tasks.** Implement the documented UUID namespace/key encoding, content projection and separate binding/manifest hashes. Hash complete contributing fact values including parent references and permissions. Use deterministic ordering while preserving semantic list values. Verify detached output and exact snapshot bindings. Reject collisions where an existing logical/binding key would name inconsistent content; do not overwrite or deduplicate by text. Publish canonical bytes for the downstream persistence owner.

**Acceptance criteria.** Repeated/restarted builds are byte-identical. Editing a fact retains its chunk ID and changes content version. The same unchanged fact across v1/v2 retains content version but has new C08 bindings and manifest. Reordering input facts changes neither output order nor IDs; reordering a preserved claims list changes its content fingerprint. Candidate/purpose scopes cannot collide. A semantic chunking-version change cannot reuse old content under an indistinguishable version.

**Tests.** Deterministic fixtures, independent-process reproduction, candidate/purpose isolation, text edits/reparenting, list-order/duplicate changes, Unicode/newlines, snapshot versus payload fingerprint separation, mutable input/output isolation, identity-scheme transition and corrupted/colliding binding detection.

**Migration/configuration impact and handoff.** Record hash algorithm/version, namespace and canonical examples. There is no new durable registry for UUID allocation under the proposed stable-key scheme. If a different identity allocation scheme is selected, specify persistence/migration ownership before proceeding rather than hiding a new DATA-01 dependency.

### CONTEXT-02-S05 — Detect stale dependencies and publish invalidation results

**Objective/references.** Ensure changed or removed approved evidence cannot remain usable under a target chunk-set binding. R06/R15/R16; blueprint §5 invalidation and historical-reference rules.

**Dependencies.** S02–S04. PROFILE-01 snapshots are authoritative; `compare_snapshots` may assist diagnostics but cannot decide validity alone.

**Inputs → outputs.** Validated base and complete target manifests/dependency inventories → deterministic `ChunkChangeSet`; expected candidate/profile/purpose/settings plus a manifest → valid binding or explicit stale/mismatch error.

**Owned files.** `context/{chunk_changes,chunk_validity}.py`; `tests/context/{test_chunk_invalidation,test_chunk_validity}.py`; synthetic multi-version/branching-parent fixtures. No index repository or profile publication hook.

**Tasks.** Compare complete source dependencies and their transitive effects. Classify additions, removals, content changes and unchanged-content rebinding; identify old and replacement bindings precisely. Validate input manifests before comparison. Reject cross-candidate/purpose comparisons and unsupported schema/version transitions, or explicitly require full replacement where supported. Make target membership authoritative so skipped profile versions and lost change notifications are safe. Define idempotent application expectations for CONTEXT-03 without implementing index mutation. Keep audit access separate from valid current-use exports.

**Acceptance criteria.** Correcting a role invalidates its chunk and all dependent descendant chunks, leaving an unrelated role's content version unchanged. Removing a fact removes it from target membership; withdrawing a parent's permission removes its text from every affected output or produces the documented conflict. A pure `parent_id` change is detected even when the existing history diff reports unchanged. A v1 manifest fails a v2 expected-binding check before serving text. A failed target build supplies no successful replacement or authorization to serve stale data.

**Tests.** Every row of the invalidation matrix; permission narrowing and widening; ancestor-only change; parent removal with invalid/valid reparenting; provenance-only correction; duplicate/list-order changes missed by set diffs; v1→v3 skipped version; empty target; no-op retry; mixed/corrupt manifests; cross-purpose/candidate requests; chunking/identity-policy change; unrelated changes causing rebinding only. Assert tombstone/change diagnostics contain references and reason codes, not removed private text.

**Migration/configuration impact and handoff.** Define tombstone semantics as exclusion from the new active manifest, not destruction of approved history. CONTEXT-03 owns persistent manifest storage, index replacement/removal and activation checks; RUN-01/GEN-02 own expected active/frozen input selection. Physical stale-vector removal remains pending until that integration exists.

### CONTEXT-02-S06 — Expose the offline chunking service and consumer boundary

**Objective/references.** Deliver complete, inspectable preparation or a visible safe failure while keeping indexing separate. R06/R15/R16.

**Dependencies.** S01–S05 and existing shared error taxonomy. No LLM-01 runtime, embedding configuration, network service or database write is required for pure construction.

**Inputs → outputs.** `ChunkBuildRequest` → complete validated `ChunkSet` or `ClassifiedError`; explicit prior manifest may be compared separately. A test-only index consumer receives exact ordered texts, metadata and binding validity results.

**Owned files.** `context/{chunk_service,chunk_errors,__init__}.py`; `tests/context/{test_chunk_service,test_chunk_consumer_boundary,test_chunk_errors}.py`; `tests/fakes/chunk_consumer.py`. Coordinate package exports with any CONTEXT-01 implementation; no production index/selector/CLI pipeline wiring.

**Tasks.** Compose preparation, construction and finalization; validate coverage, permissions, references and manifest consistency before exposing success. Distinguish invalid/unapproved input, permission/context conflict, missing settings, unsupported versions and size/capacity failures using stable reason codes and existing error categories. Do not mislabel a character guard as a measured model token overflow. Allowlist diagnostics, omitting claims, provenance paths, approval notes and raw payloads. Provide the downstream contract: ordered text plus binding metadata, no model-specific preprocessing; any downstream transformation is explicitly versioned by its owner.

**Acceptance criteria.** Consumers cannot receive partial chunks with a success manifest, an automatic older-version fallback or swallowed errors. A spy proves zero embedding/generation/network/index calls. Wrong expected profile/purpose/settings fails before serving text. A fake consumer demonstrates removal/replacement semantics and rejects stale bindings, without claiming to implement or verify a production index.

**Tests.** Exact-one-result and failure propagation; private sentinels in every diagnostic channel; no implicit model/index access; wrong bindings; mandatory-context conflict; empty success versus failure; retry determinism; tampered manifest; fake consumer replacement/replay and index-boundary contract checks.

**Migration/configuration impact and handoff.** Publish the service/protocol, safe error projection, canonical export format and expected-binding obligations. No app configuration/model settings redesign or storage migration. Record that audit access and profile freshness selection are caller responsibilities.

### CONTEXT-02-S07 — Verify lifecycle, native Windows behavior and handoff

**Objective/references.** Demonstrate the component's fidelity, reproducibility and invalidation acceptance with synthetic approved evidence. R06, supporting R14/R15/R16; blueprint §§7–9.

**Dependencies.** S01–S06; existing PROFILE-01/DATA-01 services for publication and reopen tests. Actual CONTEXT-01 parity is conditional on its implementation; otherwise label parity against shared inclusion and test consumers accurately.

**Inputs → outputs.** Implemented stories, schemas, synthetic lifecycle fixtures and decisions → test evidence and `docs/components/CONTEXT-02.md` with exact limitations and next-owner integration obligations.

**Owned files.** `tests/context/{test_chunk_lifecycle,test_chunk_windows_paths,test_chunk_windows_restart}.py`; `tests/fixtures/context/chunks/README.md` and versioned synthetic fixtures; `docs/components/CONTEXT-02.md`; minimal README API/verification instructions. Correct earlier story-owned files only for demonstrated defects.

**Tasks.** Publish synthetic v1/v2/v3 through PROFILE-01 with corrected claims, reparenting, changed dates/skills/provenance, withdrawn permissions and removed facts. Build all three purposes, compare target membership and verify exact historical C08 resolution remains possible without granting new-use permission. Reopen storage and rebuild in a fresh process; persist canonical exports only in a test-owned runtime directory to prove round-trip interoperability, not a new production store. Run focused/affected checks then full regression once. Record actual environment and results; complete the checklist below.

**Acceptance criteria.** Every successful chunk's candidate assertions match exact approved fields; permitted parent context and source attribution survive. Relevant changes invalidate affected revisions and stale bindings fail. No private sentinel appears in text/metadata/logs. Restart preserves canonical results. Native Windows paths with spaces/non-ASCII characters work from another working directory, or that verification is explicitly pending. No model access is necessary and no end-to-end RAG quality claim is made.

**Tests and proposed commands.** These are future implementation checks; the named chunk tests do not exist yet and were not run during story planning. Verify the local Python interpreter first rather than treating historical handoff results as current environment evidence.

```powershell
$repo = 'C:\Path To Checkout\Job Automation Prüfung'
$python = Join-Path $repo '.venv\Scripts\python.exe'
Set-Location -LiteralPath $repo
& $python --version
& $python -m pytest tests/context tests/profile tests/contracts
& $python -m pytest

Push-Location -LiteralPath $env:TEMP
try {
    & $python -m pytest (Join-Path $repo 'tests\context\test_chunk_windows_paths.py') (Join-Path $repo 'tests\context\test_chunk_windows_restart.py')
} finally {
    Pop-Location
}
```

Generate/check schemas using the established exporter during implementation. Use `pathlib.Path` and an explicitly configured test runtime root outside tracked source, with space/non-ASCII path coverage; use no real candidate evidence. Distinguish pure unit/contract checks, real local profile integration, fake index integration and native Windows results.

**Migration/configuration impact and handoff.** Record schema/algorithm/identity/settings versions, accepted old versions, rebuild requirements and upstream limitations. No application data migration is expected for the pure builder. Index persistence, activation/recovery and real stale-vector removal require CONTEXT-03; retrieval behavior and JSON/RAG quality require CONTEXT-04/EVAL-01.

## Unresolved chunking choices and decision owners

Close choices needed for supported behavior before the dependent story is accepted. Proposed defaults are engineering choices, not approved personal facts or measured retrieval-quality results. Unsupported options must fail explicitly, not remain ambiguous in production.

| ID | Choice | Owner / evidence needed | Proposed default or boundary |
|---|---|---|---|
| D01 | Exact auxiliary schema/API placement and compatibility with evolving shared preparation | S01 with FND-01/CONTEXT-01; current code and consumer/schema fixtures | Separate chunk contracts; no C01/C08/C09 reinterpretation and no duplicate preparation policy. |
| D02 | Whole fact versus claim/section splitting; overlap, maximum size and oversize handling | S01/S03 with future CONTEXT-03/MODEL-02/EVAL-01; synthetic long/qualified claims and later measured embedding limits | Whole fact, no overlap or cross-fact aggregation. No unmeasured token default. Any configured guard fails visibly. Splitting requires exact spans, complete coverage, preserved qualifiers and identity rules before support is claimed. |
| D03 | Minimum ancestor projection, depth and definition of required versus optional parent context | S02/S03 with PROFILE-01/CONTEXT-01/04; nested roles/projects, private parents and ambiguous child examples | Walk the full permitted chain; no arbitrary depth truncation. Use structured anchors. Parent-dependent evidence requires ancestors; optional omission must be deterministic, explicit and preserve the shared eligible universe. If safe interpretation needs unavailable content, fail. |
| D04 | UUID namespace/key encoding and fragment identity evolution | S01/S04; stable-key/reparenting and segmentation-transition fixtures | UUIDv5 over stable candidate/purpose/fact/slot keys. Whole-fact corrections keep IDs; boundary/slot changes require versioned replacement, never text-based fuzzy identity. |
| D05 | Canonical bytes, fingerprint projections and full-dependency versus field-level invalidation | S04/S05; golden serialization and all-field mutation tests | Hash complete contributing facts conservatively, with content version separate from profile binding. More selective reuse needs explicit dependency proof. |
| D06 | Rich provenance, lost ongoing status and parent-kind enforcement upstream | PROFILE-01/FND-01; versioned approval/schema/migration decision | Preserve exact approved C01 only. No mutable provenance enrichment, draft recovery, invented ongoing status or reclassification of parents. Keep unresolved source limitations visible. |
| D07 | Manifest persistence, index activation, physical stale-vector removal and reuse policy | CONTEXT-03/DATA-01 with S05/S06 input contract | CONTEXT-02 supplies deterministic complete exports, changes and validity checks. Consumer must check expected bindings and must not serve an old manifest for changed inputs. No persistence work is pulled into these stories. |
| D08 | Current permission withdrawal versus already-frozen work | RUN-01/GEN-02 with PROFILE-01; explicit lifecycle policy | Chunker never chooses latest or authorizes audit data for new work. Consumers provide and validate exact expected bindings; no historical fallback on target failure. |

## Completion and handoff checklist

- Report CONTEXT-02 and every story's status, actual changed files, requirement/dependency versions and decisions closed or pending.
- Publish exact request/chunk/source-map/manifest/change/error contracts, schema versions, canonical examples, UUID namespace and separate content/binding fingerprint recipes.
- Demonstrate complete eligible primary-fact coverage, approved source mappings, parent context/permissions, precision dates, original skills/metrics/provenance and no claim synthesis.
- Demonstrate direct/transitive invalidation, removals/permission withdrawal, reparenting, unchanged-content rebinding, policy transitions and no successful stale fallback. State what the future index owner must persist/apply.
- Record limitations of C01 provenance, defaults, ongoing status and parent-kind validation; do not report those as fixed by chunking.
- Record commands/results for unit/contracts, profile lifecycle, fake consumer and native Windows checks separately. Historical/fake evidence is not production retrieval or model verification.
- Hand off to CONTEXT-03, with CONTEXT-01/04 coordination and RUN-01/GEN-02 binding obligations. Leave embeddings, index implementation, retrieval, model benchmarks and evaluation to their owners.

Planning result: **seven ordered stories, all PLANNED**. This task creates only `docs/stories/CONTEXT-02.md`; no application code, schemas, configuration, fixtures or component handoffs are implemented or changed.
