# CONTEXT-03 — Local vector and keyword index construction

Status: **PLANNED** · Planning date: **28 October 2026** · Phase 0 · Scope: **CONTEXT-03 only**

Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md), v1.0, especially §§3–6 and 8–10. Direct requirements: **R06, R07**. Supporting constraints: **R09, R14, R15, R16**. This document specifies future implementation; it does not report implemented indexes, executed tests or model benchmarks.

## Objective and scope

Build and persist a small local vector matrix and keyword index over the same complete, purpose-bound CONTEXT-02 chunk set. Obtain all embeddings through LLM-01. Preserve exact candidate/profile/chunk bindings, model identity and embedding configuration, and index format/settings versions. Rebuild reproducibly, remove stale evidence from both searchable representations, and refuse incompatible models, dimensions or versions before reuse, activation or query-vector comparison.

Use the existing native Windows machine with **16 GB RAM and 4 GB VRAM**, one active worker and serialized model inference. These are machine constraints, not an allocation budget or proof that a model fits. MODEL-02 owns measured embedding choices. All evidence, vectors, terms, index files and build metadata remain local beneath the configured runtime data root, outside tracked source. No hosted vector service, new network server, required Docker/WSL deployment or paid dependency is introduced.

Own index contracts, local persistence, embedding coordination, construction, validation, activation, rebuild/removal and a narrow read boundary for CONTEXT-04. Exclude chunk creation and permission-policy redesign (CONTEXT-02/PROFILE-01); runtime installation and model selection/benchmarks (MODEL-01/02); direct embedding HTTP clients (LLM-01); requirement-query generation, hybrid ranking, top-k selection, mandatory context, token-budget assembly and C09 production (CONTEXT-04); assessment, drafting, Salesforce, scheduling and general backup orchestration.

## Repository instructions, inspected evidence and dependency status

Follow the blueprint and [README](../../README.md), [schema generation instructions](../../schemas/README.md), native Windows path conventions and synthetic-fixture policy. No applicable ancestor or repository `AGENTS.md` was found. Generated schemas must come from typed models; incompatible shared changes require a recorded consumer/migration decision. File paths below are documentation notation, not shell commands.

| Inspected source | Available behavior and planning consequence |
|---|---|
| [CONTEXT-02 stories](CONTEXT-02.md) | **PLANNED**, not an implemented prerequisite. `docs/components/CONTEXT-02.md`, `src/job_automation/context/` and `tests/context/` are absent at planning time. Use the proposed `ChunkSet`, `EvidenceChunk`, `ChunkChangeSet` and exact-binding validator as coordination contracts; freeze against their actual implementation before production integration. Do not implement chunking inside these stories. |
| [LLM-01 handoff](../components/LLM-01.md), [provider](../../src/job_automation/models/provider.py), [embedding harness](../../src/job_automation/models/embeddings.py) | Implemented with offline verification reported by its owner; live verification is pending in the handoff. Call `ModelProvider.embed(texts, model)`. The provider gate is per instance; share the same instance with generation. It is not a cross-process worker lock. |
| [Model protocol](../../src/job_automation/contracts/interfaces.py), [model configuration](../../src/job_automation/models/configuration.py), [audit records](../../src/job_automation/models/records.py) | `EmbeddingResponse` exposes ordered vectors, `model_identifier`, `dimension`, nullable `model_digest`, `call_id` and usage. A declared `expected_digest` is compared only when a digest is returned. The harness does not explicitly reject every returned model-name mismatch. CONTEXT-03 must independently require verified compatible identity and dimensions. |
| [Embedding budget](../../src/job_automation/models/budget.py), [fingerprints](../../src/job_automation/models/fingerprints.py) | The current provider has configured batch/per-text limits and input-format version `v1`. Its default character-ratio estimator and fixture counters are not MODEL-02 measurements. The wire payload currently contains `model` and `input`; no explicit no-truncation option is sent. Validate this capability with LLM-01 before real acceptance; do not assume lossless embedding from a preflight estimate. |
| MODEL-02 availability | No `docs/components/MODEL-02.md`, MODEL-02 story document or measured embedding configuration was found in the inspected repository documentation/configuration. MODEL-01 handoff is also absent. Model name/digest, dimensions, calibrated input/batch limits, resource envelope and repeatability tolerance are **unresolved**, not supplied by the examples or tests. Recheck for new handoffs at implementation time. No runtime reachability probe was performed for this planning task. |
| [DATA-01 handoff](../components/DATA-01.md), [connection](../../src/job_automation/storage/connection.py), [engine](../../src/job_automation/storage/engine.py), [migrations](../../src/job_automation/storage/migrations.py) | Reuse SQLite connection/transaction conventions and versioned migrations. Current code has migrations **1–5**, beyond the handoff's historical 1–2 baseline. Choose the next free migration number when implementing; never edit applied migrations. The runner splits SQL on semicolons, so do not assume trigger bodies work unchanged. No existing vector/keyword store is supplied. |
| [Profile repository](../../src/job_automation/storage/repositories/profiles.py), [profile service](../../src/job_automation/profile/service.py), [inclusion](../../src/job_automation/profile/inclusion.py) | Approved historical snapshots, a current-version pointer and exact C08 resolution exist. Purpose filtering belongs upstream. Current-profile selection and frozen-work authorization must stay distinct. Check candidate identity as well as profile version; C08 alone has no candidate ID. |
| [Application configuration](../../src/job_automation/configuration.py), [example](../../config/app.example.json), [.gitignore](../../.gitignore) | `ResolvedPaths.indexes_dir` already exists and runtime roots must be absolute/outside the repository. Index settings are absent; the example has no measured model-provider block. Add narrow configuration wiring rather than a second path-resolution system. Index exclusion already exists, but it does not replace path validation. |
| [C09](../../src/job_automation/contracts/context.py), [project dependencies](../../pyproject.toml), [embedding tests](../../tests/models/test_embeddings.py), [storage tests](../../tests/storage/test_migrations.py) | C09 has `index_version` for the later selector. No numeric/vector dependency is declared. Existing model fixture names and small vectors are test data, not production recommendations. Reuse fake transport and storage-test patterns without treating prior passing counts as new verification. |

**Dependency gates:** offline contract/storage/index tests may use explicit synthetic chunk exports and deterministic fake embeddings. Production chunk integration requires CONTEXT-02's implemented handoff. Production embedding configuration and real-model acceptance require MODEL-02's measured recommendation plus MODEL-01 runtime readiness. Missing prerequisites do not justify implementing those entire components or selecting the first installed model.

## Proposed contracts and correctness rules

These are engineering proposals to freeze in S01/S02, separate from the fixed requirements above. Use auxiliary contracts, not an invented C16 or an overloaded C09.

### Inputs and outputs

Propose `IndexBuilder.build(IndexBuildRequest) -> (IndexBuildResult | None, ClassifiedError | None)` and `IndexStore.open(IndexReadRequest) -> (IndexHandle | None, ClassifiedError | None)`, with exactly one non-null result. Build success means both indexes are complete and verified; activation is a separately explicit operation with expected-state checks. An index handle is closeable and read-only.

| Contract | Required contents |
|---|---|
| `IndexBuildRequest` | Complete validated CONTEXT-02 `ChunkSet`; exact candidate/profile/purpose and approved-snapshot fingerprint; inclusion, chunk schema/algorithm/identity/rendering/settings versions; measured embedding configuration reference; index settings; requested build mode; expected prior activation token where applicable. An optional change set is a hint, never the authority for membership. |
| `EmbeddingConfiguration` | Schema/configuration version and content fingerprint; MODEL-02 report/config reference and hash; requested identifier and verified immutable model digest/revision with verification provenance; dimension; runtime/provider versions; document and query input-format/prefix rules; effective output-affecting options; input/token measurement method and limits; measured batch/resource envelope. Missing required values fail visibly. Keep requested, observed and independently verified identity separate. |
| `IndexSettings` | Schema, index algorithm/format and canonicalization versions; matrix dtype/byte order/layout, metric/normalization policy; keyword analyzer/version and exact options; finite chunk/dimension/text/batch/build-memory/disk/time limits; cleanup policy; local directory reference. Record semantic settings separately from operational attempt metadata. |
| `IndexManifest` | Schema; persistent generation UUID; exact upstream bindings and chunk-manifest hash; ordered row map with chunk ID/content version/binding fingerprint and fact/parent C08 references; complete embedding/configuration identity; index/settings/analyzer versions; row count/dimension; payload paths, byte lengths and hashes; logical build fingerprint and artifact fingerprint. Zero chunks is explicit, with configured dimension still recorded. |
| `IndexBuildRecord` / result | Build UUID, state, UTC times, requested logical fingerprint, generation reference, safe failure/reason codes, counts/bytes, embedding call IDs and safe audit records, available timings/usage, configured versus observed resource data and verification status. Never label an estimate as a measurement. Separate these variable records from reproducible payload identity. |
| `IndexReadRequest` / handle | Expected candidate/profile/purpose, chunk-manifest binding, embedding-space and index-settings fingerprints; current-use versus explicitly authorized frozen-use mode; verified manifest and bounded row/term access. Current-use reads also validate the active profile binding. Historical inspection is a distinct metadata/audit operation and cannot grant operational permission. |

Persist the canonical upstream chunk export unchanged, including parent context and source maps. Index preprocessing may derive only declared, versioned embedding text and keyword terms; it must not rewrite approved evidence or replace C08 references. Preserve distinct rows for different fact IDs even when their text is equal. Do not index private facts, raw evidence files, approval notes or mutable provenance-table enrichment. Eligibility and essential chronology still bypass retrieval in CONTEXT-04.

### Compatibility, versions and reproducibility

Define a versioned **embedding-space fingerprint** from immutable model identity, dimension, provider/runtime compatibility versions, document/query input-format rules, output-affecting options and vector normalization/encoding semantics. Compare the complete supported tuple, not merely a friendly model tag, vector length or profile version. Unknown version compatibility means rebuild or fail, never assume equivalence. Store the full measured configuration fingerprint separately, including batch/resource settings, so execution changes remain attributable.

Validate identity/dimension on **every batch**, restored payload and supplied query vector. Same dimension with a different model/digest is incompatible. Same model tag with changed weights is incompatible. Model changes midway through a build fail the entire staged generation. A null digest is not a wildcard and a configured expected digest is not observed proof. If the runtime omits per-call identity, MODEL-01/02 and LLM-01 must provide a verified immutable binding and documented drift-detection guarantee; until then fail real builds closed. Do not add runtime probing HTTP calls to CONTEXT-03 or substitute a hash of the model name.

Use three identities: a UUID for each build/generation; a deterministic logical fingerprint of complete frozen inputs/configurations; and a fingerprint of the actual ordered payloads. Exclude timestamps, random IDs, paths, call IDs and timings from logical/payload canonical projections. Manifest payload metadata may vary by generation; require identical canonical projections, not identical SQLite database file bytes. Record every actual artifact hash independently.

Proposed v1 does a **full deterministic rebuild without an embedding cache**. This is sufficient for the small candidate corpus and avoids stale-cache deletion complexity. Same validated chunks plus deterministic fake vectors produce identical ordered row bindings, encoded matrix, canonical term postings and logical fingerprints across runs/restarts. Real inference may differ numerically: MODEL-02 must supply the repeated-run evidence and acceptance tolerance, or verify exact repeatability. Persist observed differences and artifact hashes; never hide changed vector bytes behind a supposedly identical artifact version. Query-result quality and JSON/RAG comparison remain EVAL-01/CONTEXT-04 work.

If incremental reuse is later approved within this component, require exact compatible embedding space, preprocessing and text/content fingerprints, regenerated target-profile C08 bindings, complete target-membership reconciliation and tests for permission withdrawal. It is not required for v1 acceptance, and changing only a profile label on old citations is forbidden.

### Proposed local storage and resource design

Use immutable generation directories under `ResolvedPaths.indexes_dir`, with a canonical chunk/row export, a flat packed vector matrix, a small SQLite keyword-postings database and a manifest. Proposed initial encoding is explicit little-endian float32 with checked conversion; choose normalization/metric in D03 against MODEL-02's evidence. Reject non-finite values after encoding and zero vectors where the selected metric makes them invalid. Use bounded row blocks; do not introduce an ANN server or GPU index. Standard-library binary/SQLite handling is the initial proposal, not a measured performance claim.

Propose explicit keyword postings over the exact permitted retrieval text, including its already attributed parent anchors. Store `(term, row ordinal, positions/count)` with declared analyzer semantics and deterministic ordering; preserve original text separately. Specify German/English casing, Unicode, diacritics, punctuation and skill-like tokens such as `C++`, `C#` and `.NET` in fixtures. No stemming, aliases or stopword removal is implied. Empty term output for one chunk is valid if documented; missing row coverage is not. Keyword retrieval here means exact normalized-term lookup primitives; relevance scoring and hybrid selection belong to CONTEXT-04. FTS5 is an alternative decision, not an assumed installed feature; choosing it requires capability/tokenization checks and a versioned format decision.

Keep build records and the active-generation pointer in the application's SQLite database via a small CONTEXT-03 repository/migration. Store large payloads under `indexes/`, not raw/artifact directories. The per-generation keyword database has its own explicit format/schema version and lifecycle; do not run application migrations against it. Finalize/checkpoint/close all writers before publication so a published generation never depends on a missing WAL sidecar. Open operational files read-only and validate paths, sizes, hashes and cross-file row alignment before exposing a handle.

Account for matrix bytes as `N × D × bytes_per_element`, plus chunk text, term postings, Python/wire buffers, model RAM, build staging, retained generations and OS headroom. This formula is an estimate, not evidence of peak memory. Use finite MODEL-02-derived batch limits and CONTEXT-03 capacity settings, one shared provider instance, bounded sequential batches and bounded total build work. Measure combined runtime/application memory during real verification. The machine's 4 GB VRAM does not authorize allocating 4 GB to embeddings; honor measured CPU/GPU placement and remaining headroom. Oversize input, low disk, deadline or memory-limit failure leaves an inspectable failed build with no partial success and no cloud fallback or automatic evidence truncation.

### Activation, stale evidence and recovery

1. Validate the complete target chunk set and all required configuration before embedding. Stage into a new application-generated directory on the same local volume. No active files are edited in place.
2. Build both representations, verify counts/bindings and payload integrity, flush/close writers, and finalize the immutable directory. Only then transactionally register readiness and change the active pointer. Filesystem and SQLite are not one transaction: explicitly handle orphan files and failed pointer commits.
3. Activation compares the expected prior token and target binding. For current-use builds, recheck the authoritative profile pointer within the activation transaction so a slow v1 build cannot replace a newer v2 target. Revalidate configuration/purpose versions too. An intentional historical build may be stored but cannot become the current profile's index.
4. After activation both representations contain **exactly** target membership. Removed facts, withdrawn permissions, changed ancestor context and retired chunk versions have no rows or terms in the new generation. Full rebuilds handle skipped profile versions and missed change notifications without trusting an incremental diff.
5. Every operational open/read checks its expected binding and use authorization. If v2 is current but v2 construction failed, the v1 files may remain for recovery/audit, but cannot serve v2 work. No keyword-only fallback, model switch, older-profile fallback or stale open-handle use is silently permitted. Recheck generation/authorization tokens at operation boundaries; specify the read-snapshot concurrency semantics in S07.
6. Retired vectors, terms and chunk payloads are removed by idempotent, bounded cleanup when no active reader or explicitly authorized frozen-work reference pins them. Keep compact manifests/build provenance and approved source history as required for audit. Failed deletion, locks and pending retention are reported, not declared removed. Restricted history is not automatically searchable because it is pinned. OPS-01/RUN-01/GEN-02 own wider backup and frozen-work policy.
7. On restart, reconcile staging, ready-but-unactivated, active and retired states against the pointer and verified files. Quarantine or mark corrupt generations unusable and return a visible error. Never guess that the newest directory is active, resurrect a retired index or delete the last valid recovery payload before a replacement is committed.

Deleting application-owned payload files is not a promise of forensic erasure from filesystem free space or backups. Cleanup must not delete approved profile history or data needed by unfinished authorized work. With `synchronous=NORMAL` in current DATA-01, process-crash tests alone do not establish sudden-power-loss durability; document recovery checks and coordinate any stronger durability requirement explicitly.

## Ordered implementation stories

All stories are **PLANNED**. Owned files below are future implementation targets; this planning task changes only this Markdown file. Paths beginning `context/`, `contracts/`, `models/` or `storage/` are relative to `src/job_automation/`.

| Order | Story | Dependencies | Deliverable |
|---|---|---|---|
| 1 | CONTEXT-03-S01 | FND-01; CONTEXT-02 contract coordination; LLM-01/DATA-01 interfaces | Versioned index, binding and compatibility contracts |
| 2 | CONTEXT-03-S02 | S01; MODEL-02 measured configuration for production readiness | Validated local settings and capacity preflight |
| 3 | CONTEXT-03-S03 | S01–S02; DATA-01 | Generation persistence, build ledger and migrations |
| 4 | CONTEXT-03-S04 | S01–S02; LLM-01; CONTEXT-02 export contract | Bounded embedding batches with strict provenance |
| 5 | CONTEXT-03-S05 | S01–S04 | Complete deterministic matrix and keyword construction |
| 6 | CONTEXT-03-S06 | S03–S05; CONTEXT-02 validity/change semantics | Atomic activation, stale-data removal and recovery |
| 7 | CONTEXT-03-S07 | S01–S06 | Strict read boundary and manual operational commands |
| 8 | CONTEXT-03-S08 | S01–S07; implemented CONTEXT-02 for actual integration | Offline/fake and native Windows verification |
| 9 | CONTEXT-03-S09 | S08; MODEL-01, MODEL-02 measured handoffs; LLM-01 live readiness | Separate real-model verification and component handoff |

### CONTEXT-03-S01 — Freeze index contracts and compatibility rules

**Objective/references.** Establish explicit index inputs, outputs and version boundaries before persistence or model calls. R06/R07/R15/R16; C01/C08/C10 and future C09 `index_version`.

**Dependencies.** Existing FND-01 contracts/error taxonomy, CONTEXT-02-S01/S04–S06 contracts, LLM-01 response/audit types and DATA-01 conventions. While CONTEXT-02 is only planned, coordinate the boundary and label synthetic exports as fakes; do not claim real chunk integration.

**Inputs → outputs.** Complete chunk-export proposal and measured-configuration requirements → typed request/settings/manifest/build/read contracts, protocol definitions, fingerprint projections, supported-version policy and generated schemas.

**Owned files.** `contracts/retrieval_index.py`; `context/{index_ports,index_identity,index_errors}.py`; narrow exports in `contracts/{__init__,export_schemas}.py` and `context/__init__.py`; generated `schemas/v1/index_*.schema.json` and embedding-configuration schema as registered; `schemas/README.md`; `tests/context/{test_index_contracts,test_index_compatibility,test_index_identity}.py` and synthetic contract fixtures.

**Tasks.** Freeze exact-one-result semantics, required identity provenance, full input bindings, deterministic hash recipes and separation of logical fingerprints, artifact hashes and UUIDs. Define row alignment, zero-row behavior and unsupported-version failures. Use `ClassifiedError` with safe reason codes for stale binding, incompatibility, corruption, missing configuration, permissions and capacity; avoid inventing a new broad error framework.

**Acceptance criteria.** A valid manifest identifies exactly one candidate/profile/purpose/chunk set and compatible embedding space. Equal dimensions cannot make two models compatible. Missing/unknown identity cannot pass as verified. Changed chunk/settings/analyzer/schema versions are detected. The later selector can use one documented artifact identity as C09 `index_version` without implementing C09 here.

**Tests.** Schema round trips and deterministic export; every version/fingerprint field mutation; null/empty/unknown identity; same-tag/different-digest and same-dimension/different-model; wrong candidate/purpose/profile; malformed row maps; duplicate IDs; extra fields; detached-container mutation; hashes excluding timestamps/paths but including semantic inputs.

**Migration/configuration impact and handoff.** Close D01 and the compatibility policy in D02/D03. Additive auxiliary schemas only; no reinterpretation of C01/C08/C09 or silent public `ModelProvider` signature change. Record accepted schema versions and migration/rebuild rules for S02–S07.

### CONTEXT-03-S02 — Bind measured embedding settings and local resource limits

**Objective/references.** Make the configured build local, bounded and attributable to MODEL-02's measurements. R07/R14/R15/R16.

**Dependencies.** S01; current AppConfig/ResolvedPaths and LLM-01 settings. MODEL-02 handoff is required to close production values; fake settings suffice only for offline development.

**Inputs → outputs.** Runtime paths, index configuration and measured embedding recommendation → immutable validated effective settings/capacity plan, or a safe missing-configuration/unsupported/capacity error before model access.

**Owned files.** `context/{index_settings,index_capacity}.py`; narrow `configuration.py` wiring; `config/index.example.json` with clearly non-operational placeholders or omitted required measured fields; optional reference from `config/app.example.json`; generated app/index settings schemas; `tests/context/{test_index_settings,test_index_capacity,test_index_paths}.py` and affected `tests/test_configuration.py`.

**Tasks.** Bind exact recommendation/version/hash, model capabilities, tokenizer/preprocessing policy and execution envelope. Reject contradictory index/provider limits. Calculate matrix/text/staging estimates and enforce finite work/batch/disk budgets. Resolve the index location only through the configured local root; reject repository, UNC/network and path-escape targets, including resolved link/junction escapes. Do not download/select models or turn fixture dimensions/default batch size into measured settings.

**Acceptance criteria.** No MODEL-02 configuration produces an actionable configuration failure for a real build. Valid synthetic settings allow offline tests without a model service. Declared N/D limits, staging plus retained space and request/response buffers are considered before allocation; limits remain enforced as output grows. Paths with spaces/umlauts work independently of working directory. No import/check command creates files or performs model calls.

**Tests.** Missing and conflicting values; unsupported fingerprint versions; zero/negative/non-finite/unbounded limits; exact-limit/one-over cases; tiny synthetic memory/disk ceilings; integer-size/shape checks; local versus UNC/escaped paths; Unicode/CWD behavior; no-side-effect spies. Distinguish fake capacity arithmetic from observed RAM/VRAM.

**Migration/configuration impact and handoff.** Close D04/D05 numeric and path choices before production readiness. Keep configuration fingerprints versioned and record what triggers rebuild. Unresolved MODEL-02 values remain named blockers for S09, not guessed defaults.

### CONTEXT-03-S03 — Persist immutable generations and build metadata

**Objective/references.** Store independently verifiable local payloads and transactional activation metadata using DATA-01. R06/R09/R14/R16.

**Dependencies.** S01–S02 and existing DATA-01 migration/transaction APIs.

**Inputs → outputs.** Validated manifest/build records and bounded payload streams → staged/finalized generation files, durable build state and exact readback, or storage failure with no active-pointer change.

**Owned files.** `context/{index_files,index_serialization}.py`; `storage/repositories/context_indexes.py`; narrow repository exports, `storage/engine.py` and a newly appended migration in `storage/migrations.py`; `tests/context/{test_index_storage,test_index_integrity}.py`; `tests/storage/test_context_index_migrations.py`.

**Tasks.** Implement the versioned directory/file format, application-owned path containment, row/payload integrity checks and closeable resource handling. Add build/generation/activation/pin metadata tables with uniqueness and scoped keys. Keep payload writes outside long SQLite write transactions. Preserve old migrations and unrelated domain records. Explicitly manage keyword-database finalization and its schema separately from the main database. Store safe embedding audit data by call ID without private input/output text.

**Acceptance criteria.** Reopen from another process and recover the exact bindings, canonical row order, matrix shape and term postings. Corrupt/truncated/swapped payloads, missing keyword files, unsupported versions and duplicate binding conflicts fail before use. Applying the migration twice is idempotent; a failed migration leaves no partial application schema. No import creates runtime directories.

**Tests.** Fresh/upgrade/idempotent/failing migrations preserving profiles/jobs/requests; payload round trips; truncated matrix, extra bytes and invalid offsets; manifest/path tampering; keyword schema/row-count mismatch; disk-full/write/permission failures; close/reopen and file-lock release on Windows. Test safe SQL parameter binding with hostile terms/text.

**Migration/configuration impact and handoff.** Allocate the next available migration after the current 1–5 baseline. Publish main-database and per-generation format versions, artifact checksums and a rebuild/restore compatibility policy. Do not modify DATA-01's applied checksums or claim general backup support.

### CONTEXT-03-S04 — Obtain and validate embeddings through LLM-01

**Objective/references.** Produce one validated vector per target row using the measured local configuration. R06/R07/R15/R16; C10 and `ModelProvider.embed`.

**Dependencies.** S01–S02; LLM-01 public provider/audit boundary; CONTEXT-02's exact ordered text/binding export. S03 supplies the durable audit sink during integrated builds.

**Inputs → outputs.** Ordered permitted chunk texts, explicit embedding configuration and shared provider → validated bounded vector blocks with row ordinals, embedding-space identity and call audit references, or a whole-build failure.

**Owned files.** `context/{index_embeddings,index_model_audit}.py`; `tests/context/{test_index_embeddings,test_index_embedding_metadata,test_index_embedding_failures}.py`; `tests/fakes/index_embeddings.py`; scripted transport fixtures. Any necessary LLM-01 capability correction is an explicitly tracked upstream dependency, not an alternate HTTP client here.

**Tasks.** Apply only versioned measured document preprocessing/prefixes. Batch deterministically under both configured count and byte/token limits, sharing the provider instance and its serialization gate. Validate exact count, row order contract, every vector's dimension/finite values, returned model identity and immutable binding for every call. Validate conversion/normalization again before persistence. Link success/failure audit records; treat missing required audit evidence as failure rather than fabricate it. Bound total build work in addition to provider retries; do not add unbounded nested retry loops.

**Acceptance criteria.** Empty target uses zero embedding calls and builds a valid empty index; a nonempty row with empty/oversize input fails visibly. Equal text rows preserve distinct identities. A later failed/mismatched batch cannot yield a partial active index. Unknown digest, model swap, dimension drift, invalid/zero vectors under the chosen metric and unsupported preprocessing fail closed. Provider exceptions/unsafe messages become safe classified failures with no private text in ordinary logs. No direct network call, cloud fallback or silent truncation occurs.

**Tests.** Deterministic fake-provider results and actual LLM-01 with scripted transport; duplicate text/order; zero/one/multiple batches; mismatches in first and later batches; model alias drift; absent digest versus verified immutable binding; NaN/Inf/boolean elements and float32 overflow; service outage/deadline/audit failure; oversized qualified claim; injected private sentinels. Check one shared provider and zero calls for empty input.

**Migration/configuration impact and handoff.** Close D02/D06 provenance and no-truncation capability decisions before real use. Preserve requested versus effective/observed settings and call IDs. LLM-01's in-memory recorder alone is not durable index-build provenance; supply an index-build recorder through its existing port. Hardware fit is verified only in S09.

### CONTEXT-03-S05 — Construct aligned vector and keyword payloads

**Objective/references.** Materialize both local indexes from exactly the same approved chunk membership. R06/R07/R14/R15.

**Dependencies.** S01–S04; fixed matrix/analyzer decisions D03/D07.

**Inputs → outputs.** Complete target chunk export, ordered validated vectors and frozen index settings → staged matrix, keyword postings, row/source map and verified complete manifest.

**Owned files.** `context/{index_builder,vector_matrix,keyword_index,index_manifest}.py`; `tests/context/{test_index_builder,test_vector_matrix,test_keyword_index,test_index_alignment}.py`; `tests/fixtures/context/indexes/` synthetic corpus and canonical expectations.

**Tasks.** Preserve CONTEXT-02 ordering/IDs/bindings. Write vectors as bounded blocks and term postings with deterministic analyzer behavior. Keep original chunk/source metadata separate from derived tokens. Validate one vector per row, exact metadata coverage, all term references within the same generation, and declared zero-term behavior. Recompute and compare payload hashes/lengths before readiness. No relevance filter may reduce the target corpus.

**Acceptance criteria.** Every target chunk has exactly one vector row and keyword document identity, including title-only/nontechnical evidence. Distinct facts with equal text stay distinct. Known synthetic terms locate the expected rows and resolve the exact fact/parent references. Both indexes exclude a private sentinel before any provider input or file write. Empty target creates matching empty payloads, not an outage result. A failed keyword build prevents vector-only success.

**Tests.** Golden fake-vector matrix bytes and canonical postings; German/English/Unicode/diacritic and `C++`/`C#`/`.NET` cases; punctuation-only and known-empty term results; duplicate text, preserved parent context, changed analyzer/settings; shuffled input and deterministic ordering; malformed row/term references; keyword or matrix write failure; long-document limits and private-data spies.

**Migration/configuration impact and handoff.** Record dtype/endianness, metric/normalization, analyzer implementation/version/options and canonical export format. No new dependency is necessary under the proposal; any alternative must document native Windows support and resource costs. Expose primitive term/row access, leaving hybrid ranking and retrieval quality to CONTEXT-04.

### CONTEXT-03-S06 — Rebuild, activate, remove stale payloads and recover

**Objective/references.** Make evidence changes visible atomically and eliminate stale operational membership in both indexes. R06/R09/R15/R16.

**Dependencies.** S03–S05; CONTEXT-02 complete target/binding/invalidation semantics; PROFILE-01 current-version pointer; RUN-01 worker-lock boundary for eventual application composition.

**Inputs → outputs.** Complete target, expected prior activation token, optional change report and persisted generation state → committed replacement/removal, recovery/cleanup report, or inspectable failure preserving a valid prior state without authorizing stale current use.

**Owned files.** `context/{index_lifecycle,index_recovery,index_cleanup}.py`; lifecycle methods in `storage/repositories/context_indexes.py`; `tests/context/{test_index_rebuild,test_index_stale_removal,test_index_activation,test_index_recovery,test_index_cleanup}.py`.

**Tasks.** Implement the staged-to-ready-to-active lifecycle and compare-and-swap activation. Serialize competing writers through a local store lease/transaction mechanism; RUN-01's future worker lock must still cover application entry points. Recheck profile/config bindings at activation. Reconcile full membership even when intermediate versions/change events are absent. Retire old generation payloads and remove them after readers/authorized work release pins, retaining required compact provenance. Recovery verifies pointer/files and handles staging/orphans without promoting incomplete data. Retry cleanup safely after Windows sharing violations.

**Acceptance criteria.** A v1→v3 rebuild removes deleted facts, withdrawn-purpose facts and old ancestor text from **both** current payloads without needing v2. Changed model/dimension/settings produce an isolated replacement; no append mixes spaces. A v2 failure cannot serve v1 as v2. A slow earlier build cannot overwrite a later active target. A new empty target removes all prior search membership. Retired unpinned vectors, terms and chunk exports are physically deleted; blocked/pinned cleanup remains explicitly pending. Approved historical profiles and unrelated files remain intact.

**Tests.** Primary/ancestor correction, reparenting, permission narrowing/widening, fact removal, chunking/identity/analyzer/model changes, skipped versions, empty target and no-op retry. Inject failure before/after each file-finalization and database-commit boundary; kill/reopen in a subprocess; competing activations; concurrent readers; missing/corrupt active payload; path-containment and cleanup retries; pinned/unpinned retirement and restart. Assert no mixed-generation reads or stale successful fallback.

**Migration/configuration impact and handoff.** Close D08/D09 lifecycle/pin/retention rules. Full rebuild is the supported v1 mode; interrupted builds may restart cleanly rather than resume partial vector batches. Document how RUN-01/GEN-02 provide expected bindings and release pins. Report process-crash versus power-loss guarantees separately.

### CONTEXT-03-S07 — Expose guarded reads and manual index operations

**Objective/references.** Make persisted indexes usable and inspectable without implementing the selector or permitting stale consumers. R06/R07/R14/R15/R16.

**Dependencies.** S01–S06; existing CLI/configuration and PROFILE-01 exact snapshot access; production rebuild requires actual CONTEXT-02 service.

**Inputs → outputs.** Exact expected index bindings and operation parameters → closeable verified handle, bounded term/row results, safe build/status/cleanup reports, or a classified mismatch/capacity/storage error.

**Owned files.** `context/{index_reader,index_service,index_cli,__init__}.py`; minimal `cli.py` wiring; `tests/context/{test_index_reader,test_index_consumer_boundary,test_index_diagnostics}.py`; `tests/test_cli_context_index.py`; README operational instructions. Coordinate package exports with other context owners.

**Tasks.** Expose exact-term lookup, bounded vector blocks and row/chunk/source resolution. Require embedding-space identity with a query vector before any future comparison; reject model/dimension/input-format mismatch. A consumer fake may demonstrate compatible use, but production query generation/ranking stays outside this story. Define a read-operation snapshot with a validated generation token; recheck on each operation, never allow a long-lived handle to silently follow a newer generation or continue after its authorization expires. Add manually invoked `context index build`, `status`, `verify` and `cleanup` commands with explicit config/candidate/profile/purpose options and documented exit codes; activation remains explicit or an explicit build option.

**Acceptance criteria.** CONTEXT-04 can discover a matching artifact and exact evidence references without reading storage internals or assuming latest. Wrong profile/purpose/settings or incompatible query identity fails before scores or text are returned. Historical inspection cannot be used as a current-use handle. Model outage/corruption is distinct from a valid empty index or no term matches. CLI status exposes IDs/counts/versions, not private text/vectors, and commands work from another working directory. No C09, relevance score or mandatory-context decision is produced.

**Tests.** Reader binding matrix; obsolete open handle after activation/permission change; authorized frozen reference versus unauthorized historical use; malformed query vector/identity; bounded enumeration; close/reopen; zero-hit/empty/failure distinction; hostile terms as data; CLI exits/config paths; safe stdout/stderr/logs including upstream exception sentinels. Fake consumer proves both representations use one generation.

**Migration/configuration impact and handoff.** Publish exact public signatures, C09 artifact-version mapping, snapshot/read-pin rules and failure codes for CONTEXT-04. Do not add a pipeline scheduler, profile watcher, query embedding model choice or application-wide lock implementation belonging to RUN-01.

### CONTEXT-03-S08 — Verify offline behavior with fake embeddings on Windows

**Objective/references.** Demonstrate persistence, reproducibility, compatibility and stale removal without a model runtime. R06/R14/R15/R16; blueprint §8 verification discipline.

**Dependencies.** S01–S07. Actual CONTEXT-02 integration additionally requires its implemented handoff; substitute contracts only in explicitly named fake tests.

**Inputs → outputs.** Synthetic multi-version profiles/chunks, deterministic fake embeddings and failure-injection fixtures → recorded unit/contract/local-storage/Windows results and a draft CONTEXT-03 handoff with pending live checks.

**Owned files.** `tests/context/{test_index_lifecycle,test_index_reproducibility,test_index_windows_paths,test_index_windows_restart}.py`; `tests/fixtures/context/indexes/README.md` and synthetic fixtures; `tests/fakes/index_embeddings.py`; `docs/components/CONTEXT-03.md` verification sections. Earlier story files may change only to correct demonstrated defects.

**Tasks.** Build twice in fresh processes from identical exports and fake vectors; compare logical fingerprints, ordered bindings, matrix bytes and canonical postings while separating variable audit data. Publish synthetic corrected/removed/permission-changed profiles through PROFILE-01 and use actual CONTEXT-02 when available. Exercise migrations, restart, corrupt payloads, failover refusal and cleanup in real local storage. Run focused and affected suites, then full regression once. Record environment/commands/results rather than reusing old handoff counts.

**Acceptance criteria.** Deterministic fake inputs reproduce exact canonical content. Both indexes survive close/reopen, exclude stale target evidence and reject incompatible spaces. Failed rebuilds have no partial active state. Space/Unicode paths and a different working directory pass on native Windows; any unavailable case is marked pending. Fake vectors demonstrate mechanics only, not semantic quality, actual embedding dimension, memory fit or model determinism.

**Tests and proposed commands.** These test files do not exist yet. Commands are future implementation checks, not results of this planning task:

```powershell
$repo = 'C:\Path To Checkout\Job Automation Prüfung'
$python = Join-Path $repo '.venv\Scripts\python.exe'
Set-Location -LiteralPath $repo
& $python --version
& $python -m job_automation.contracts.export_schemas
& $python -m pytest tests/context tests/models tests/storage tests/profile tests/contracts tests/test_configuration.py
& $python -m pytest

Push-Location -LiteralPath $env:TEMP
try {
    & $python -m pytest (Join-Path $repo 'tests\context\test_index_windows_paths.py') (Join-Path $repo 'tests\context\test_index_windows_restart.py')
} finally {
    Pop-Location
}
```

**Migration/configuration impact and handoff.** Use only test-owned temporary data roots. Record fake-provider tests, actual LLM-01 with fake transport, real local SQLite/file integration, actual versus fake CONTEXT-02, and native Windows checks separately. Component live verification remains pending S09.

### CONTEXT-03-S09 — Verify the measured real model and publish the handoff

**Objective/references.** Verify the chosen local embedding configuration with the actual index implementation without inventing benchmark evidence. R06/R07/R14/R16.

**Dependencies.** S08; implemented CONTEXT-02; MODEL-01 runtime/identity/capability handoff; **MODEL-02 measured embedding configuration**; LLM-01 real-provider readiness and any identity/no-truncation gaps closed. Absent prerequisites leave this story pending; offline passes do not satisfy it.

**Inputs → outputs.** Frozen synthetic chunk corpus, measured recommendation and explicitly selected installed local model → opt-in verification record, actual persisted/reopened index and `docs/components/CONTEXT-03.md` with precise acceptance status.

**Owned files.** `tests/manual/context_index_smoke.py` outside default pytest collection; synthetic live-check corpus under `tests/fixtures/context/indexes/`; `docs/components/CONTEXT-03.md`; concise README instructions. MODEL-02 benchmark artifacts remain owned by MODEL-02.

**Tasks.** Require explicit config/model/report references; never copy the existing model smoke script's first-installed-model selection. Record Windows/Python/runtime/provider versions, model digest verification, dimension, preprocessing, batch/input limits, matrix/analyzer settings and report hash. Build, reopen and verify both representations; repeat a cold rebuild with identical frozen inputs. Compare actual vector differences against MODEL-02's documented tolerance, retaining each payload hash. Measure application plus runtime peak RAM, available headroom, VRAM/placement where observable, elapsed time, batch behavior and disk/staging usage under the declared ceilings. Verify boundary-length inputs are rejected rather than truncated, and removal/rebuild and mismatch handling still work. If measurements exceed the recommendation, record the failure and return to MODEL-02 for revised settings; do not quietly choose a different model.

**Acceptance criteria.** Every real response is attributable to the configured immutable model and dimension. Reopened indexes resolve correct synthetic row/fact references; removed target evidence is absent from both. Repeated builds meet the documented reproducibility criterion and remain within the measured machine envelope with headroom. Unavailable telemetry is recorded as unavailable, and any required unverified limit remains pending. No real candidate evidence is needed. This verifies integration/resource behavior, not broad retrieval quality or end-to-end RAG usefulness.

**Verification procedure.** The future manual script accepts absolute `--config`, `--model-config` and synthetic `--chunk-set` paths plus a local `--data-root`; exact arguments are frozen in S07/S09. It emits a structured `passed`, `failed` or `pending_prerequisite` result with distinct exit behavior. It must not install/pull models, contact hosted APIs, run automatically under pytest or report a skipped check as success. List actual commands and observations in the handoff. Real model outage/mismatch tests must use the selected configuration or controlled injected faults and label the latter as simulated.

**Migration/configuration impact and handoff.** Close measured decisions with source report references and exact effective values. Record unit/fake, local integration, native Windows and real-model results in separate sections. Use `IMPLEMENTED — live verification pending` if appropriate; mark `VERIFIED` only when declared component acceptance is demonstrated. Hand off to CONTEXT-04 with the read/compatibility contract and to RUN-01/GEN-02/OPS-01 with activation, pin, recovery and retention obligations.

## Missing decisions and configuration gates

Resolve each choice before accepting its dependent behavior. Proposed defaults are engineering choices, not model benchmarks or user facts.

| ID | Missing decision | Owner / required evidence | Proposed boundary and gate |
|---|---|---|---|
| D01 | Final CONTEXT-02 export API, schemas, canonical bytes and validity signatures | CONTEXT-02 + S01; implemented handoff and contract fixtures | Consume complete purpose-bound exports and preserve source mappings; do not turn planned names into claims of available code. Blocks actual integration, not explicit fake tests. |
| D02 | Exact embedding model/digest/revision, dimension, input-format/prefix rules, provider/runtime compatibility, repeated-run tolerance | MODEL-02 with MODEL-01/LLM-01 + S01/S02/S04/S09 | **No measured configuration available at planning time.** Null digest is not sufficient. Require verified immutable binding and drift detection; same tag/dimension is not compatibility. Blocks real acceptance. |
| D03 | Matrix dtype, metric, normalization, zero-vector policy and numeric tolerances | S01/S05 with MODEL-02; vector semantics and real repeatability evidence | Flat little-endian float32 is proposed, checked for overflow; no ANN. Freeze metric/normalization explicitly, including query expectations. Any output-affecting change isolates/rebuilds generations. |
| D04 | Maximum chunks/dimension/text size, batch counts/bytes/tokens, total build time/memory, disk ceiling/free-space margin and retained-generation allowance | S02/S09 with MODEL-02 measurements and local storage availability | Finite settings, serialized inference and OS/application headroom. Hardware totals and LLM-01 defaults are not safe measured allocations. Fail visibly when exceeded. |
| D05 | Local index directory/layout and operational configuration entry point | S02/S03 with DATA-01 | Reuse `indexes_dir`; separate main-database metadata from immutable payloads. Reject network/escaped/repository targets. No paid or external storage service. |
| D06 | Proven no-truncation behavior, model-specific token counting and durable identity/audit completeness | LLM-01/MODEL-01/02 with S04/S09 | Existing character estimate and `model`/`input` wire payload do not establish this. Track narrowly scoped prerequisite fixes; never bypass the provider or silently shorten chunks. Oversized whole-fact chunks require a CONTEXT-02 policy revision. |
| D07 | Keyword analyzer, case/diacritic/punctuation rules, term positions and FTS5 versus explicit postings | S01/S05 with CONTEXT-04 consumer contract | Explicit local SQLite postings proposed; no stemming/stopwords/aliases by default. Golden German/English and punctuation-sensitive skill fixtures. If FTS5 is selected, verify capability and schema/migration support first. |
| D08 | Activation token scope, current versus frozen authorization, reader pins and cross-process locking integration | S03/S06/S07 with PROFILE-01/RUN-01/GEN-02 | Exact expected bindings and transactional activation; no implicit old-profile fallback. Worker orchestration and revocation policy remain with their owners. Unsupported frozen use fails closed until policy is defined. |
| D09 | Retired payload retention, cleanup retry limits, pinned work, backup references and stronger power-loss durability if required | S06 with DATA-01/OPS-01/RUN-01/GEN-02 | Remove unpinned superseded payloads after safe publication; retain compact audit/source history. Report blocked cleanup; do not promise secure erasure or delete referenced inputs. |
| D10 | Full rebuild versus incremental embedding reuse | S05/S06; small-corpus measurements if optimization is proposed | Full rebuild with no embedding cache for v1. Reuse is optional and requires complete compatibility/binding/removal tests; no unversioned text-only cache. |

## Completion and handoff checklist

- Report CONTEXT-03 and each story's status, actual files changed, requirement/dependency versions and unresolved gates.
- Publish exact build/read/manifest/error contracts, canonical projections, schema/format versions, migration numbers and C09 artifact-version mapping.
- Cite MODEL-02's measured configuration and MODEL-01/LLM-01 capabilities, or explicitly mark real verification pending. Preserve requested/observed/verified model identity distinctly.
- Demonstrate one complete permitted chunk universe across vector rows, keyword documents and exact profile/fact/parent bindings; record private-evidence exclusion and empty-index behavior.
- Demonstrate reproducibility, incompatible-space rejection, profile/chunk/settings invalidation, full stale membership removal, physical cleanup status, atomic activation and restart recovery.
- Record finite configured limits and separate estimates from measured RAM/VRAM/disk/latency; document combined model/application headroom and unavailable telemetry.
- Separate fake embeddings, fake transport through LLM-01, actual local storage, actual CONTEXT-02 integration, native Windows and real-model checks. Do not claim retrieval quality, benchmarks or pipeline completion from fake tests.
- Hand off guarded read primitives to CONTEXT-04 and lifecycle/retention obligations to RUN-01/GEN-02/OPS-01. Leave model selection, query construction, ranking, mandatory context and evaluation with their owners.

Planning result: **nine ordered stories, all PLANNED**. This task creates only `docs/stories/CONTEXT-03.md`; it does not implement application code, schemas, migrations, configuration, fixtures or component handoffs.
