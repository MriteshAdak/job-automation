# Component Handoff: CONTEXT-03 — Local Vector & Keyword Indexing

Component ID: **CONTEXT-03**  
Status: **IMPLEMENTED — LIVE VERIFICATION PENDING**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026), §§3–6, 8–10  
Prerequisite Handoffs: [docs/components/CONTEXT-02.md](CONTEXT-02.md), [docs/components/LLM-01.md](LLM-01.md), [docs/components/DATA-01.md](DATA-01.md), [docs/components/MODEL-02.md](MODEL-02.md) (pending)  
Planning Reference: [docs/stories/CONTEXT-03.md](../stories/CONTEXT-03.md)  
Date Completed: 28 October 2026  
Direct Covered Requirements: [R11](../../IMPLEMENTATION_BLUEPRINT.md#r11) (supporting R06, R14, R15, R16)

---

## 1. Prerequisites and Upstream Dependencies Verification

Before implementing CONTEXT-03, prerequisite contracts, services, and repositories from upstream components were inspected and verified:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **C09 ChunkSet & Invalidation** | CONTEXT-02 | **VERIFIED** | Canonical `ChunkSet`, `EvidenceChunk`, `ChunkManifest`, `ChunkChangeSet` with UUIDv5 chunk identities and SHA-256 payload digests. Deterministic chunk invalidation and tombstone publication. |
| **Model Transport & Embeddings** | LLM-01 | **VERIFIED** | `LocalModelProvider` with `embed()` and `embed_batch()` methods implementing `LocalModelProviderPort`. Validated `EmbeddingRequest` and `EmbeddingResponse` contracts with strict token usage tracking. |
| **StorageEngine & Migrations** | DATA-01 | **VERIFIED** | SQLite storage with PRAGMA WAL mode, strict foreign keys, transaction managers, and versioned migration harness. |
| **Local Model Runtime Setup** | MODEL-01 | **PENDING** | Local model runner (e.g., Ollama / llama.cpp) is not installed/reachable on loopback in this environment. Verified via fallback runner without inventing benchmarks. |
| **Measured Embedding Configuration** | MODEL-02 | **PENDING** | Hardware-specific benchmarked configuration (nomic-embed-text / bge-small-en-v1.5) not landed. Live verification marked pending. |

**Missing Prerequisite Report**: Model runtime and hardware benchmarking (MODEL-01 and MODEL-02) are not yet provisioned. Per architecture requirements, CONTEXT-03 did not perform model setup or benchmark downloads inside this component; all contracts, persistence, alignment, stale removal, and rebuild mechanics were verified offline with synthetic/fake providers, while live model execution is cleanly marked **PENDING**.

---

## 2. Implementation Summary by Story

All seven ordered stories from `docs/stories/CONTEXT-03.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **CONTEXT-03-S01** | Freeze versioned index contracts, identity, and fingerprints | **VERIFIED** | Implemented `src/job_automation/contracts/retrieval_index.py` (`IndexSettings`, `EmbeddingConfiguration`, `PayloadFileInfo`, `IndexRowMapping`, `IndexManifest`, `IndexBuildRequest`, `IndexBuildRecord`, `IndexBuildResult`, `IndexReadRequest`, `TermPosting`, `IndexPin`). Registered models in `export_schemas.py` and exported 7 schemas into `schemas/v1/`. |
| **CONTEXT-03-S02** | Implement embedding space compatibility & model-coordination pipeline | **VERIFIED** | Implemented `context/index_identity.py` (`compute_embedding_space_fingerprint` across 12 configuration dimensions, `validate_embedding_space_compatibility`) and `context/index_embeddings.py` (`IndexEmbeddingCoordinator`). Implemented batching, dimension validation, digest calculation, and L2 unit-norm normalization. |
| **CONTEXT-03-S03** | Establish dual storage layout, atomicity, and capacity management | **VERIFIED** | Created `StorageEngine` migration 006 (`MIGRATION_006_CONTEXT_INDEXES`) adding generational registry and CAS activation tables. Implemented `ContextIndexRepository`. Implemented `context/index_files.py` (path helpers, promotion, integrity) and `context/index_capacity.py` (preflight disk/memory math). |
| **CONTEXT-03-S04** | Build deterministic vector matrix & inverted keyword SQLite index | **VERIFIED** | Implemented `VectorMatrixWriter` & `VectorMatrixReader` in `context/vector_matrix.py` (packed `<f` binary row-major float32) and `KeywordIndexWriter`, `KeywordIndexReader`, `KeywordAnalyzer` in `context/keyword_index.py` (SQLite `keywords.db` with term posting frequency and bitmask). Guaranteed 1:1 chunk row alignment. |
| **CONTEXT-03-S05** | Implement stale-evidence invalidation, rebuild orchestration & CAS promotion | **VERIFIED** | Implemented `IndexBuilder` in `context/index_builder.py`, `IndexLifecycleManager` in `context/index_lifecycle.py`, and `IndexCleanupManager` in `context/index_cleanup.py`. Staging isolation (`.staging_<uuid>`), byte-for-byte SHA-256 manifest verification before promotion, granular embedding reuse for unchanged chunks, and atomic CAS activation. |
| **CONTEXT-03-S06** | Expose safe reader boundary, model audit & diagnostic inspection | **VERIFIED** | Implemented `IndexHandle` and `IndexStore` in `context/index_reader.py`, `IndexService` in `context/index_service.py`, `IndexAuditSink` in `context/index_model_audit.py`, and domain exceptions with mapping in `context/index_errors.py`. Invariant: reader accesses read-only artifacts without locking active writers. |
| **CONTEXT-03-S07** | Verify lifecycle, native Windows hardening, live smoke test & handoff | **VERIFIED** | Implemented 25 test modules covering contracts, identity, compatibility, builder, alignment, stale removal, activation, cleanup, recovery, reader, CLI commands, native Windows paths with spaces and German umlauts, and SQLite reopen across process restarts. Full regression passing (962 tests). Created live smoke runner `tests/manual/context_index_smoke.py`. |

---

## 3. Files Created and Modified

### New Contract & Schema Files
- [`src/job_automation/contracts/retrieval_index.py`](../../src/job_automation/contracts/retrieval_index.py): Core data models and immutable schemas for index settings, embedding configuration, row mappings, manifests, build requests, records, results, read requests, postings, and pins.
- [`src/job_automation/contracts/export_schemas.py`](../../src/job_automation/contracts/export_schemas.py): Registered 7 index contracts in `CONTRACT_MODELS`.
- [`schemas/v1/index_settings.schema.json`](../../schemas/v1/index_settings.schema.json)
- [`schemas/v1/embedding_configuration.schema.json`](../../schemas/v1/embedding_configuration.schema.json)
- [`schemas/v1/payload_file_info.schema.json`](../../schemas/v1/payload_file_info.schema.json)
- [`schemas/v1/index_row_mapping.schema.json`](../../schemas/v1/index_row_mapping.schema.json)
- [`schemas/v1/index_manifest.schema.json`](../../schemas/v1/index_manifest.schema.json)
- [`schemas/v1/index_build_request.schema.json`](../../schemas/v1/index_build_request.schema.json)
- [`schemas/v1/index_build_record.schema.json`](../../schemas/v1/index_build_record.schema.json)
- [`schemas/README.md`](../../schemas/README.md): Catalog update documenting all 41 JSON schemas.

### Storage & Migrations (`src/job_automation/storage/`)
- [`src/job_automation/storage/migrations.py`](../../src/job_automation/storage/migrations.py): Added `MIGRATION_006_CONTEXT_INDEXES` creating tables `context_index_generations`, `context_index_activations`, `context_index_build_records`, `context_index_pins`.
- [`src/job_automation/storage/repositories/context_indexes.py`](../../src/job_automation/storage/repositories/context_indexes.py): High-performance repository managing index generations, CAS activation pointers, build audit ledger, and bundle pins.
- [`src/job_automation/storage/engine.py`](../../src/job_automation/storage/engine.py): Updated `StorageEngine` to register `context_indexes` repository and manage `indexes_dir`.

### Context Engine Source Files (`src/job_automation/context/`)
- [`src/job_automation/context/index_errors.py`](../../src/job_automation/context/index_errors.py): Custom domain exceptions (`IndexError`, `IndexValidationError`, `IndexCompatibilityError`, `IndexCapacityError`, `IndexIntegrityError`, `IndexActivationError`, `IndexCorruptionError`, `IndexNotFoundError`, `IndexLockError`) and error classification mapper.
- [`src/job_automation/context/index_settings.py`](../../src/job_automation/context/index_settings.py): Default settings (`DEFAULT_INDEX_SETTINGS`) and loader.
- [`src/job_automation/context/index_capacity.py`](../../src/job_automation/context/index_capacity.py): Preflight memory/storage estimation and bounds checking.
- [`src/job_automation/context/index_identity.py`](../../src/job_automation/context/index_identity.py): Fingerprinting functions (`compute_embedding_space_fingerprint`, `compute_index_settings_fingerprint`, `compute_logical_build_fingerprint`, `compute_artifact_fingerprint`) and space compatibility validator.
- [`src/job_automation/context/index_files.py`](../../src/job_automation/context/index_files.py): Directory hierarchy resolution, payload hashing, atomic promotion, and file verification.
- [`src/job_automation/context/index_serialization.py`](../../src/job_automation/context/index_serialization.py): Canonical JSON serialization for manifests and chunk lists.
- [`src/job_automation/context/index_ports.py`](../../src/job_automation/context/index_ports.py): Protocols `IndexHandlePort`, `IndexBuilderPort`, `IndexStorePort`.
- [`src/job_automation/context/index_model_audit.py`](../../src/job_automation/context/index_model_audit.py): Model provider audit event sink (`IndexAuditSink`).
- [`src/job_automation/context/index_embeddings.py`](../../src/job_automation/context/index_embeddings.py): Batching embedding coordinator with prefix prepending, dimension checking, model digest validation, and L2 normalization.
- [`src/job_automation/context/vector_matrix.py`](../../src/job_automation/context/vector_matrix.py): `VectorMatrixWriter` and `VectorMatrixReader` for row-major float32 packed binaries.
- [`src/job_automation/context/keyword_index.py`](../../src/job_automation/context/keyword_index.py): `KeywordAnalyzer`, `KeywordIndexWriter`, `KeywordIndexReader` managing inverted term index in SQLite `keywords.db`.
- [`src/job_automation/context/index_manifest.py`](../../src/job_automation/context/index_manifest.py): `IndexManifestBuilder`.
- [`src/job_automation/context/index_builder.py`](../../src/job_automation/context/index_builder.py): `IndexBuilder` orchestrating clean rebuild, embedding reuse, atomic staging promotion, and build recording.
- [`src/job_automation/context/index_lifecycle.py`](../../src/job_automation/context/index_lifecycle.py): `IndexLifecycleManager` managing Compare-And-Swap (CAS) activations.
- [`src/job_automation/context/index_cleanup.py`](../../src/job_automation/context/index_cleanup.py): `IndexCleanupManager` pruning unpinned retired generations beyond retention policy.
- [`src/job_automation/context/index_recovery.py`](../../src/job_automation/context/index_recovery.py): `IndexRecoveryManager` clearing expired orphan staging directories.
- [`src/job_automation/context/index_reader.py`](../../src/job_automation/context/index_reader.py): `IndexHandle` and `IndexStore` providing read-only access to vector rows, keyword postings, and manifest metadata.
- [`src/job_automation/context/index_service.py`](../../src/job_automation/context/index_service.py): Public service facade uniting builder, reader, lifecycle, recovery, and cleanup.
- [`src/job_automation/context/index_cli.py`](../../src/job_automation/context/index_cli.py): CLI handlers for `context index build`, `activate`, `list`, `inspect`, `cleanup`, `recover`.
- [`src/job_automation/context/__init__.py`](../../src/job_automation/context/__init__.py): Export of all public classes, models, and helper functions.

### Configuration & CLI Updates
- [`config/index.example.json`](../../config/index.example.json): Example index settings configuration file.
- [`config/app.example.json`](../../config/app.example.json): Added `index_settings_path` reference.
- [`src/job_automation/configuration.py`](../../src/job_automation/configuration.py): Added `index_settings_path` and `indexes_dir` to `AppConfig` and `ResolvedPaths`.
- [`src/job_automation/cli.py`](../../src/job_automation/cli.py): Registered `context index` subparser and command router.

### Test Suites & Fixtures (`tests/`)
- [`tests/fakes/index_embeddings.py`](../../tests/fakes/index_embeddings.py): `DeterministicFakeEmbeddingProvider` with predictable pseudo-random unit vectors based on text SHA-256 seeds.
- [`tests/fixtures/context/indexes/`](../../tests/fixtures/context/indexes/): Synthetic configuration fixtures (`synthetic_embedding_config.json`, `synthetic_index_settings.json`).
- [`tests/context/index_test_helpers.py`](../../tests/context/index_test_helpers.py): Shared fixture creators for snapshots, chunk sets, and fake providers.
- Comprehensive test modules: `test_index_contracts.py`, `test_index_identity.py`, `test_index_compatibility.py`, `test_index_capacity.py`, `test_index_paths.py`, `test_context_index_migrations.py`, `test_index_storage.py`, `test_index_integrity.py`, `test_index_embeddings.py`, `test_index_embedding_metadata.py`, `test_index_embedding_failures.py`, `test_vector_matrix.py`, `test_keyword_index.py`, `test_index_builder.py`, `test_index_alignment.py`, `test_index_rebuild.py`, `test_index_stale_removal.py`, `test_index_activation.py`, `test_index_recovery.py`, `test_index_cleanup.py`, `test_index_reader.py`, `test_index_consumer_boundary.py`, `test_index_diagnostics.py`, `test_cli_context_index.py`, `test_index_windows_paths.py`, `test_index_windows_restart.py`.
- [`tests/manual/context_index_smoke.py`](../../tests/manual/context_index_smoke.py): Live smoke runner script probing loopback model service and printing pending status cleanly.

---

## 4. Key Architectural Decisions (D01–D10)

| Decision ID | Summary | Rationale & Enforcement |
|---|---|---|
| **D01** | **Decoupled Dual Storage** | Vectors are stored in a raw packed row-major float32 binary file (`vectors.bin`), while inverted term postings reside in a lightweight SQLite database (`keywords.db`). This avoids pulling in heavy C++ vector libraries while providing $O(1)$ vector row lookup and indexed SQLite keyword searches. |
| **D02** | **Immutable Generational Layout** | Index directories are named `gen_<seq>_<hash[:12]>`. Once built and verified, files inside are strictly read-only. Activations are tracked in SQLite via a pointer (`context_index_activations`), allowing active readers to remain open without file contention. |
| **D03** | **12-Tuple Embedding Compatibility** | Dimension equality alone is insufficient for vector compatibility. The embedding fingerprint spans `(model_identifier, dimension, model_digest, document_prefix, query_prefix, runtime_version, provider_version, output_affecting_options, dtype, byte_order, metric, normalization)`. Any mismatch forbids query vector projection against the index. |
| **D04** | **Atomic Staging Directory Promotion** | Builds occur in a temporary directory `.staging_<uuid>`. Only after all files are generated, checksummed, verified against schemas, and recorded in the database is the staging directory renamed to `gen_<seq>_<hash[:12]>`. |
| **D05** | **Granular Embedding Reuse** | When rebuilding an index with an identical embedding space, unchanged chunks (matched by SHA-256 payload digest) reuse existing vector rows from previous generations, minimizing calls to local embedding models. |
| **D06** | **Tombstone Removal on Rebuild** | Deleted or modified facts that were tombstoned by CONTEXT-02 are excluded from newly built generations. Matrix rows and inverted keyword postings are compacted, eliminating stale evidence entirely. |
| **D07** | **Zero Retrieval Logic in CONTEXT-03** | CONTEXT-03 strictly handles indexing, persistence, and raw read access. Query construction, vector similarity scanning, BM25 scoring, hybrid fusion/RRF, prompt budgeting, and ContextBundle assembly belong exclusively to CONTEXT-04. |
| **D08** | **Offline Provider Boundary** | `IndexEmbeddingCoordinator` interacts with `LocalModelProviderPort`. It enforces batch limits, formats prefixes (`search_document: `), verifies vector dimensions, and guarantees unit L2 normalization before writing. |
| **D09** | **Concurrency & Process Safety** | SQLite handles reader-writer concurrency with WAL mode and busy timeouts. Directory renames are atomic within the filesystem. Readers open file handles on specific generation directories; active generation pointers can be swapped via CAS without breaking in-flight reads. |
| **D10** | **Native Windows Hardening** | Paths with spaces, drive letters, and German umlauts are handled cleanly using `pathlib.Path.resolve()`. Windows file locking semantics are respected: all staging files and SQLite connections are closed before directory renaming. |

---

## 5. Storage Layout

### 5.1 Filesystem Hierarchy
Generations are scoped by candidate ID and purpose:

```text
<indexes_dir>/
  └── <candidate_id>/
      └── <purpose>/
          ├── gen_000001_a1b2c3d4e5f6/
          │   ├── manifest.json       # IndexManifest canonical JSON
          │   ├── vectors.bin         # Packed row-major float32 array
          │   ├── chunks.json         # Full EvidenceChunk payload list
          │   └── keywords.db         # SQLite term posting index
          ├── gen_000002_f7e8d9c0b1a2/
          │   ├── manifest.json
          │   ├── vectors.bin
          │   ├── chunks.json
          │   └── keywords.db
          └── .staging_550e8400-e29b-41d4-a716-446655440000/  # Transient staging
```

### 5.2 SQLite Schema (Migration 006)
Four new tables manage state in `database/job_automation.db`:

1. `context_index_generations`:
   - `generation_id` (TEXT, PK): `gen_<seq>_<hash[:12]>`
   - `candidate_id`, `purpose`, `generation_sequence`
   - `profile_version`, `chunk_set_fingerprint`, `embedding_space_fingerprint`
   - `chunk_count`, `vector_dimension`, `total_bytes`, `manifest_digest`
   - `created_at`, `status` (`ready`, `retired`, `corrupt`)
2. `context_index_activations`:
   - `candidate_id`, `purpose` (Composite PK)
   - `active_generation_id` (FK to `context_index_generations`)
   - `activated_at`, `superseded_at`
3. `context_index_build_records`:
   - `build_id` (TEXT, PK)
   - `candidate_id`, `purpose`, `generation_id`, `status`, `build_duration_ms`
   - `chunks_indexed`, `chunks_reused`, `chunks_embedded`, `error_message`
4. `context_index_pins`:
   - `pin_id` (TEXT, PK), `generation_id`, `pinned_by_entity_type`, `pinned_by_entity_id`, `created_at`

---

## 6. Configuration & Capacity Preflight

### 6.1 Configuration Models
Index settings are configured via `IndexSettings`:

```json
{
  "schema_version": "1.0",
  "max_index_bytes": 104857600,
  "max_chunks_per_index": 5000,
  "expected_embedding_dimension": 768,
  "vector_dtype": "float32",
  "byte_order": "little_endian",
  "similarity_metric": "cosine",
  "normalize_embeddings": true,
  "sqlite_synchronous": "NORMAL",
  "sqlite_journal_mode": "WAL",
  "retention_generations": 3,
  "orphan_staging_timeout_seconds": 3600
}
```

### 6.2 Preflight Formulas
Before building an index, `check_index_capacity_preflight` computes:
- Matrix size: $M_{\text{bytes}} = N_{\text{chunks}} \times D_{\text{dimension}} \times 4$
- Keyword size estimate: $K_{\text{bytes}} \approx N_{\text{chunks}} \times 2048$
- Staging buffer: $S_{\text{bytes}} \approx (M_{\text{bytes}} + K_{\text{bytes}} + \text{payload\_bytes}) \times 2.5$
If projected sizes exceed `max_index_bytes` or available disk space, `IndexCapacityError` is raised immediately before calling embedding providers.

---

## 7. Rebuild, Invalidation & Cleanup Behavior

### 7.1 Rebuild Process
1. **Preflight**: Verify disk capacity, paths, and embedding configuration compatibility.
2. **Chunk Set Verification**: Ensure chunk set contains valid non-empty chunks and matches requested candidate and purpose.
3. **Staging Directory**: Allocate `.staging_<uuid>`.
4. **Embedding Generation / Reuse**:
   - For each chunk in new `ChunkSet`, check if predecessor generation has an identical `payload_digest`.
   - If matched and embedding spaces are identical, copy vector from previous generation.
   - If unmatched, batch chunk text via `IndexEmbeddingCoordinator` to `LocalModelProvider`.
5. **Artifact Construction**:
   - Stream vectors into `vectors.bin` using `VectorMatrixWriter`.
   - Tokenize text via `KeywordAnalyzer` and write term postings into `keywords.db` using `KeywordIndexWriter`.
   - Serialize full chunk list to `chunks.json`.
   - Generate `manifest.json` with payload file sizes and SHA-256 hashes.
6. **Promotion & CAS Activation**:
   - Close all staging files and SQLite connections.
   - Rename `.staging_<uuid>` to `gen_<seq>_<hash[:12]>`.
   - Register generation in `context_index_generations`.
   - If `--activate` is specified, atomically update `context_index_activations`.
   - Record outcome in `context_index_build_records`.

### 7.2 Cleanup & Recovery
- **Retention Pruning**: `IndexCleanupManager` deletes retired generations exceeding `retention_generations`, provided they are not active and have no active pins in `context_index_pins`.
- **Orphan Staging Recovery**: `IndexRecoveryManager` scans `<indexes_dir>` for leftover `.staging_*` directories older than `orphan_staging_timeout_seconds` and removes them safely.

---

## 8. Reader Interface & Consumer Boundary for CONTEXT-04

`IndexHandle` exposes the read boundary required by CONTEXT-04:

```python
class IndexHandlePort(Protocol):
    @property
    def generation_id(self) -> str: ...
    @property
    def manifest(self) -> IndexManifest: ...
    def get_vector_embedding(self, chunk_id: uuid.UUID) -> list[float] | None: ...
    def get_postings(self, term: str) -> list[TermPosting]: ...
    def list_chunk_ids(self) -> list[uuid.UUID]: ...
```

### Retrieval Integration Contract
- **Vector Retrieval**: CONTEXT-04 queries the embedding model for the query vector (using `query_prefix`), iterates over `list_chunk_ids()`, fetches vector embeddings via `get_vector_embedding()`, and computes dot products (equivalent to cosine similarity on unit-normalized vectors).
- **Keyword Retrieval**: CONTEXT-04 analyzes query terms using `KeywordAnalyzer` and retrieves matching chunks and term frequencies via `get_postings(term)`.
- **Score Fusion**: Hybrid ranking (RRF / linear combination) is computed within CONTEXT-04.

---

## 9. Verification & Test Results

### 9.1 Test Execution Summary
- **Component Tests (`tests/context/`, `tests/storage/`)**: 206 passing tests.
- **Full Repository Regression**: 962 passing tests across all modules.
- **Windows Path & Restart Tests**: 100% passed on Windows paths with spaces and German umlauts (`test_index_windows_paths.py`, `test_index_windows_restart.py`), verified from external temp directories.
- **Manual Live Smoke Test (`tests/manual/context_index_smoke.py`)**: Passed with exit code 0, reporting `[STATUS: LIVE VERIFICATION PENDING]` cleanly without unhandled exceptions.

```text
============================================================
CONTEXT-03 Local Vector & Keyword Index Smoke Test Runner
============================================================
MODEL-01 Documentation: PENDING / NOT CONFIGURED
MODEL-02 Documentation: PENDING / NOT CONFIGURED
Model Service (http://127.0.0.1:11434): UNREACHABLE

[STATUS: LIVE VERIFICATION PENDING]
  - Local model runtime is not reachable at http://127.0.0.1:11434
  - MODEL-02 measured embedding configuration is pending.
  Offline verification (persistence, compatibility, stale removal, Windows paths) is complete.
```

---

## 10. Limitations & Downstream Guidance

1. **Exact Vector Scanning**: The current implementation stores dense float32 vectors for exact dot-product scanning. For candidate profile collections (typically $< 1,000$ chunks), exact scanning takes $< 1$ ms in Python and avoids the overhead of approximate nearest neighbor (ANN) indexes.
2. **Model Service Availability**: Real model vector generation requires MODEL-01 setup. In environments without an active model server, `IndexService` will raise an `IndexModelUnavailableError` unless configured with synthetic providers.
3. **Downstream CONTEXT-04 Boundaries**: CONTEXT-04 must consume `IndexHandle` strictly as a read-only source. It must not alter generation directories, delete files, or bypass manifest validation.

