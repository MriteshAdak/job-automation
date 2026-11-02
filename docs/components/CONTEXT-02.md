# Component Handoff: CONTEXT-02 — Versioned Retrieval Evidence Preparation

Component ID: **CONTEXT-02**  
Status: **VERIFIED**  
Phase: **Phase 0**  
Baseline: [IMPLEMENTATION_BLUEPRINT.md](../../IMPLEMENTATION_BLUEPRINT.md) (v1.0, 26 October 2026), especially §§4–6, 8, 9  
Prerequisite Handoffs: [docs/components/PROFILE-01.md](PROFILE-01.md), [docs/components/FND-01.md](FND-01.md), [docs/components/CONTEXT-01.md](CONTEXT-01.md)  
Planning Reference: [docs/stories/CONTEXT-02.md](../stories/CONTEXT-02.md)  
Date Completed: 28 October 2026  
Direct Covered Requirements: [R06](../../IMPLEMENTATION_BLUEPRINT.md#r06) (supporting R11, R14, R15, R16)  

---

## 1. Prerequisites and Upstream Dependencies Verification

Before implementing CONTEXT-02, all prerequisite contracts and services from **PROFILE-01**, **FND-01**, and **DATA-01** were inspected and verified:

| Dependency | Component | Status | Verification Summary |
|---|---|---|---|
| **C01 ProfileSnapshot** | FND-01 / PROFILE-01 | **VERIFIED** | `validate_snapshot` validates snapshot schema, explicit human approval (`is_approved=True`), and fact graph integrity (cycle detection, precision dates). |
| **Shared Inclusion Rules** | PROFILE-01 | **VERIFIED** | `InclusionRules` in `profile/inclusion.py` enforces purpose filtering (`assessment`, `cv`, `cover_letter`), parent privacy protection, and deterministic sorting. |
| **C08 EvidenceReference** | FND-01 / PROFILE-01 | **VERIFIED** | `CandidateEvidenceReference` resolves historical `(profile_version, fact_id)` pairs via `ProfileService.resolve_candidate_reference`. |
| **Shared Preparation Alignment** | CONTEXT-01 | **VERIFIED** | Both JSON context (CONTEXT-01) and evidence chunking (CONTEXT-02) evaluate permissions before expansion, enforce the same purpose matrix, and see the identical eligible fact universe. |
| **StorageEngine & Migrations** | DATA-01 | **VERIFIED** | SQLite storage with PRAGMA WAL mode preserves snapshots across restarts and enables multi-version lifecycle verification. |

**Missing Prerequisite Report**: Zero missing prerequisites. All upstream dependencies are active and verified.

---

## 2. Implementation Summary by Story

All seven ordered stories from `docs/stories/CONTEXT-02.md` have been implemented and verified:

| Story ID | Description | Status | Verification Summary |
|---|---|---|---|
| **CONTEXT-02-S01** | Freeze chunk, settings, manifest & change contracts | **VERIFIED** | Implemented `src/job_automation/contracts/evidence_chunks.py` defining `ChunkingSettings`, `AncestorContext`, `ChunkSourceMapping`, `EvidenceChunk`, `ChunkSet`, `BindingTransition`, `ChunkChangeSet`, `ChunkBuildRequest`. Exported auxiliary models and generated schemas in `schemas/v1/`. |
| **CONTEXT-02-S02** | Prepare permitted facts & traceable parent context | **VERIFIED** | Implemented `ChunkEvidencePreparer` in `context/chunk_preparation.py`. Enforces purpose permissions, walks full permitted ancestor chains without depth truncation, retains opaque parent references for optional restricted parents with explicit contextual limitations, and raises `ChunkPermissionError` for required restricted context. |
| **CONTEXT-02-S03** | Assemble lossless chunks with field-level traceability | **VERIFIED** | Implemented `DefaultChunkRenderer` in `context/chunk_rendering.py`, `ChunkTraceabilityValidator` in `context/chunk_traceability.py`, and `ChunkBuilder` in `context/chunk_builder.py`. One primary fact per chunk; all approved primary fields (claims, skills, metrics, precision dates, organization, provenance, allowed uses) preserved verbatim. Every assertion links to a C08 field mapping. Visible `ChunkCapacityError` on `max_chunk_chars` overflow. |
| **CONTEXT-02-S04** | Assign stable identities & immutable version bindings | **VERIFIED** | Implemented `context/chunk_identity.py`, `context/chunk_manifest.py`, and `context/chunk_serialization.py`. Deterministic UUIDv5 `chunk_id` derived from stable candidate/purpose/fact/slot keys. Content version `chunk_version` computed over canonical projection excluding profile version and timestamps. Separate `binding_fingerprint` and `manifest_fingerprint`. |
| **CONTEXT-02-S05** | Detect stale dependencies & publish invalidation results | **VERIFIED** | Implemented `compare_chunk_manifests` in `context/chunk_changes.py` and `validate_chunk_binding` in `context/chunk_validity.py`. Compares base and target manifests: detects additions, removals (tombstones), content updates, unchanged rebinding, reparenting, and settings changes. Consumer binding check rejects cross-candidate, cross-purpose, or stale profile versions. |
| **CONTEXT-02-S06** | Expose offline chunking service & consumer boundary | **VERIFIED** | Implemented `EvidenceChunker` in `context/chunk_service.py` and error classification in `context/chunk_errors.py`. Invariant: exactly one of `(result, error)` is non-null. Zero network, embedding, model, or database calls. Created `FakeIndexConsumer` in `tests/fakes/chunk_consumer.py`. |
| **CONTEXT-02-S07** | Verify lifecycle, native Windows behavior & handoff | **VERIFIED** | Implemented comprehensive test suites (63 tests) covering contract validation, parent privacy, fact traceability, stable identity, byte reproducibility, invalidation matrix, consumer boundaries, multi-version profile lifecycle, Windows paths with spaces and German umlauts, and SQLite reopen across process restart. Full regression passing (897 tests). |

---

## 3. Files Created and Modified

### New Contract & Schema Files
- [`src/job_automation/contracts/evidence_chunks.py`](../../src/job_automation/contracts/evidence_chunks.py): Versioned Pydantic contract models for chunking requests, settings, source mappings, chunks, manifests, and change sets.
- [`src/job_automation/contracts/export_schemas.py`](../../src/job_automation/contracts/export_schemas.py): Registered auxiliary chunk contracts in `CONTRACT_MODELS` for deterministic schema generation.
- [`schemas/v1/chunk_build_request.schema.json`](../../schemas/v1/chunk_build_request.schema.json)
- [`schemas/v1/chunking_settings.schema.json`](../../schemas/v1/chunking_settings.schema.json)
- [`schemas/v1/evidence_chunk.schema.json`](../../schemas/v1/evidence_chunk.schema.json)
- [`schemas/v1/chunk_source_mapping.schema.json`](../../schemas/v1/chunk_source_mapping.schema.json)
- [`schemas/v1/ancestor_context.schema.json`](../../schemas/v1/ancestor_context.schema.json)
- [`schemas/v1/chunk_set.schema.json`](../../schemas/v1/chunk_set.schema.json)
- [`schemas/v1/binding_transition.schema.json`](../../schemas/v1/binding_transition.schema.json)
- [`schemas/v1/chunk_change_set.schema.json`](../../schemas/v1/chunk_change_set.schema.json)
- [`schemas/README.md`](../../schemas/README.md): Updated catalog table documenting the new schema files.

### Context Source Files (`src/job_automation/context/`)
- [`src/job_automation/context/chunk_errors.py`](../../src/job_automation/context/chunk_errors.py): Custom domain exceptions (`ChunkError`, `ChunkValidationError`, `ChunkPermissionError`, `ChunkCapacityError`, `ChunkBindingError`, `ChunkConfigurationError`, `ChunkUnsupportedError`) and `map_chunk_exception_to_classified_error`.
- [`src/job_automation/context/chunk_ports.py`](../../src/job_automation/context/chunk_ports.py): Protocols `EvidenceChunkerPort` and `ChunkRendererPort`.
- [`src/job_automation/context/chunk_settings.py`](../../src/job_automation/context/chunk_settings.py): Default settings constant `DEFAULT_CHUNKING_SETTINGS`.
- [`src/job_automation/context/chunk_preparation.py`](../../src/job_automation/context/chunk_preparation.py): `ChunkEvidencePreparer`, `PreparedChunkFact`, `PreparedChunkData`.
- [`src/job_automation/context/chunk_rendering.py`](../../src/job_automation/context/chunk_rendering.py): `DefaultChunkRenderer`.
- [`src/job_automation/context/chunk_traceability.py`](../../src/job_automation/context/chunk_traceability.py): `ChunkTraceabilityValidator`.
- [`src/job_automation/context/chunk_identity.py`](../../src/job_automation/context/chunk_identity.py): UUIDv5 identity derivation and canonical fingerprinting functions (`generate_chunk_id`, `compute_fact_dependency_fingerprint`, `compute_chunk_content_version`, `compute_binding_fingerprint`, `compute_snapshot_fingerprint`, `compute_settings_fingerprint`, `compute_manifest_fingerprint`).
- [`src/job_automation/context/chunk_builder.py`](../../src/job_automation/context/chunk_builder.py): `ChunkBuilder`.
- [`src/job_automation/context/chunk_serialization.py`](../../src/job_automation/context/chunk_serialization.py): Canonical JSON serialization and round-trip parsing helpers.
- [`src/job_automation/context/chunk_manifest.py`](../../src/job_automation/context/chunk_manifest.py): `ChunkManifestBuilder`.
- [`src/job_automation/context/chunk_changes.py`](../../src/job_automation/context/chunk_changes.py): `compare_chunk_manifests`.
- [`src/job_automation/context/chunk_validity.py`](../../src/job_automation/context/chunk_validity.py): `validate_chunk_binding`.
- [`src/job_automation/context/chunk_service.py`](../../src/job_automation/context/chunk_service.py): `EvidenceChunker` public offline facade.
- [`src/job_automation/context/__init__.py`](../../src/job_automation/context/__init__.py): Exported all CONTEXT-02 classes, models, and functions.

### Fixtures and Test Suites (`tests/`)
- [`tests/fakes/chunk_consumer.py`](../../tests/fakes/chunk_consumer.py): `FakeIndexConsumer` simulating downstream vector/keyword index ingestion.
- [`tests/fixtures/context/chunks/README.md`](../../tests/fixtures/context/chunks/README.md): Fixture catalog documentation.
- [`tests/fixtures/context/chunks/synthetic_chunk_request.json`](../../tests/fixtures/context/chunks/synthetic_chunk_request.json): Synthetic request fixture.
- [`tests/context/chunk_test_helpers.py`](../../tests/context/chunk_test_helpers.py): Shared synthetic profile builders.
- [`tests/context/test_chunk_contracts.py`](../../tests/context/test_chunk_contracts.py): Contract models, schemas, immutability, extra-field rejection.
- [`tests/context/test_chunk_preparation.py`](../../tests/context/test_chunk_preparation.py): Purpose matrix, multi-level hierarchy, private parents, required parents, order stability.
- [`tests/context/test_chunk_builder.py`](../../tests/context/test_chunk_builder.py): One fact per chunk, full-field fidelity, qualifiers, negation, null end dates, size guard overflow.
- [`tests/context/test_chunk_parent_context.py`](../../tests/context/test_chunk_parent_context.py): Parent context anchors, non-role parents, sentinel secret isolation.
- [`tests/context/test_chunk_traceability.py`](../../tests/context/test_chunk_traceability.py): Source mappings, complete eligible coverage, tampered mapping detection.
- [`tests/context/test_chunk_identity.py`](../../tests/context/test_chunk_identity.py): Stable UUIDv5, content version stability, binding fingerprint sensitivity.
- [`tests/context/test_chunk_serialization.py`](../../tests/context/test_chunk_serialization.py): Deterministic JSON formatting, unescaped Unicode, round trips.
- [`tests/context/test_chunk_reproducibility.py`](../../tests/context/test_chunk_reproducibility.py): Byte reproducibility, input order independence.
- [`tests/context/test_chunk_invalidation.py`](../../tests/context/test_chunk_invalidation.py): Invalidation matrix (additions, tombstones, updates, rebinding, settings changes).
- [`tests/context/test_chunk_validity.py`](../../tests/context/test_chunk_validity.py): Consumer binding validation against expected candidate, profile version, purpose, settings.
- [`tests/context/test_chunk_service.py`](../../tests/context/test_chunk_service.py): Public service facade, exact-one-result invariant, zero-external-calls spy.
- [`tests/context/test_chunk_consumer_boundary.py`](../../tests/context/test_chunk_consumer_boundary.py): Downstream consumer ingestion, tombstone application, active binding updates.
- [`tests/context/test_chunk_errors.py`](../../tests/context/test_chunk_errors.py): Error classification and safe diagnostics.
- [`tests/context/test_chunk_lifecycle.py`](../../tests/context/test_chunk_lifecycle.py): Full multi-version lifecycle (v1 -> v2 -> historical C08 resolution) using real `StorageEngine` and `ProfileService`.
- [`tests/context/test_chunk_windows_paths.py`](../../tests/context/test_chunk_windows_paths.py): Execution and file persistence on Windows paths with spaces and German umlauts.
- [`tests/context/test_chunk_windows_restart.py`](../../tests/context/test_chunk_windows_restart.py): SQLite storage reopen across process restarts and byte-for-byte rebuilt manifest match.

---

## 4. Key Architectural Decisions (D01–D08)

1. **D01: Auxiliary Chunk Contracts without Overloading C08/C09**:
   Chunking contracts (`ChunkingSettings`, `EvidenceChunk`, `ChunkSourceMapping`, `ChunkSet`, `ChunkChangeSet`, `ChunkBuildRequest`) are defined in `evidence_chunks.py`. They reference existing `C08` (`CandidateEvidenceReference`) without modifying its schema or overloading `C09` (`ContextBundle`).
2. **D02: Whole-Fact Granularity with Strict Size Guards**:
   Granularity is strictly `whole_fact` (one approved fact per primary chunk). Every eligible fact, including title-only facts, receives a chunk. If configured, `max_chunk_chars` enforces an explicit character limit; overflow raises a visible `ChunkCapacityError` (mapped to `ErrorCategory.CONTEXT_BUDGET`). No unmeasured token guessing, silent truncation, or cross-fact merging is permitted.
3. **D03: Full Permitted Ancestor Chains & Parent Privacy Boundaries**:
   Ancestor resolution walks the complete permitted parent chain without arbitrary depth truncation.
   - If an ancestor is permitted: structured `AncestorContext` anchors are included with exact kind, title, organization, dates, and provenance.
   - If an ancestor is restricted:
     - Under `strict_parents=False` (default): the child retains its opaque `parent_id`, restricted parent text is omitted, an explicit limitation `restricted_parent_omitted:<parent_id>` is recorded on the chunk, and a deterministic warning is added.
     - Under `strict_parents=True` or if the ancestor was in `explicit_required_fact_ids`: an explicit `ChunkPermissionError` is raised.
4. **D04: Persistent UUIDv5 Identity Derived from Stable Keys**:
   Logical chunk identity `chunk_id` is a deterministic UUIDv5 generated in namespace `context.evidence.job-automation.local` from:
   `(identity_scheme_version, candidate_id, purpose, primary_fact_id, slot="whole_fact")`.
   It is independent of profile version, claim text, dates, parent text, and timestamps. Correcting an assertion retains its logical identity; allocating a new fact UUID creates a new identity.
5. **D05: Separate Content Version and Snapshot-Bound Fingerprints**:
   - `chunk_version`: SHA-256 over a canonical projection of payload, primary metadata, dependency fact fingerprints, parent relationships, source mappings, effective permissions, and settings versions. It excludes profile version and timestamps. An unchanged fact in v2 retains its v1 `chunk_version`.
   - `binding_fingerprint`: SHA-256 binding `(candidate_id, profile_version, purpose, chunk_id, chunk_version, sources, retrieval_text)`. Any profile version bump requires a new binding.
   - `manifest_fingerprint`: SHA-256 covering candidate, profile version, purpose, snapshot fingerprint, settings fingerprint, ordered chunk bindings, coverage, and warnings.
6. **D06: Verbatim Fidelity & Upstream Truth Preservation**:
   All approved strings (titles, organizations, claims, skills, metrics, provenance) are preserved verbatim, including qualifiers, negation, list order, duplicates, and German umlauts. Precision dates retain exact `value` and `precision`; null end dates are never rendered as "present" and employment duration is not calculated.
7. **D07: Complete Manifest Comparison & Invalidation Tracking**:
   Invalidation compares complete base and target manifests. Downstream consumers receive an explicit `ChunkChangeSet` detailing `added_chunk_ids`, `removed_chunk_ids` (tombstones), `content_changed_chunk_ids`, `rebound_unchanged_chunk_ids`, per-chunk `binding_transitions`, reason codes, and `replacement_required`.
8. **D08: Consumer Expected-Binding Enforcement**:
   `validate_chunk_binding` prevents serving a manifest built for a different candidate, an older profile version, or an incompatible purpose. A target build failure never authorizes fallback to an older manifest.

---

## 5. Invalidation Behavior & Downstream Contract (CONTEXT-03 Handoff)

The downstream index owner (**CONTEXT-03**) must honor the following contract:
1. **Target Authority**: The target `ChunkSet` is the sole authoritative definition of active evidence for `(candidate_id, profile_version, purpose)`.
2. **Tombstone Application**: Chunks in `removed_chunk_ids` must be removed from the downstream index.
3. **Content Updates**: Chunks in `content_changed_chunk_ids` require re-embedding and index replacement.
4. **Rebound Reuse**: Chunks in `rebound_unchanged_chunk_ids` retain their `chunk_version`. Downstream consumers may reuse existing embeddings while updating their stored citation binding to the new `profile_version`.
5. **Strict Consumer Binding Check**: Before serving retrieval results, the consumer must verify `(candidate_id, profile_version, purpose, settings_fingerprint)`. Stale manifests must fail visibly rather than serving outdated evidence.

---

## 6. Upstream Source Limitations & Boundaries

The following known boundaries remain the responsibility of upstream or downstream components:
1. **C01 Provenance Granularity**: C01 provides a single string provenance field (e.g. filename or summary) rather than structured document offsets. Character spans in `ChunkSourceMapping` refer to offsets within approved C01 fields, not original raw document bytes.
2. **Lost Ongoing Status in C01**: As documented in PROFILE-01, draft `is_ongoing=True` is not represented as an explicit boolean in C01; ongoing roles have null `end_date`. Chunking preserves null end dates without synthesizing "present".
3. **No Embedded Vectors or Similarity Scores**: CONTEXT-02 does not generate embeddings, perform vector math, create indexes, or call model endpoints.

---

## 7. Verification Commands and Actual Results

### 1. Evidence Chunking & Context Unit Tests with Coverage
```powershell
& ".\.venv\Scripts\python.exe" -m pytest --cov=job_automation.context tests\context
```
Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.7.0
rootdir: C:\Users\mrite\Projects\job-search
configfile: pyproject.toml
plugins: cov-6.3.0
collected 109 items

tests\context\test_binding.py ......                                     [  5%]
tests\context\test_budget.py ....                                        [  9%]
tests\context\test_chunk_builder.py ....                                 [ 12%]
tests\context\test_chunk_consumer_boundary.py .                          [ 13%]
tests\context\test_chunk_contracts.py .........                          [ 22%]
tests\context\test_chunk_errors.py ......                                [ 27%]
tests\context\test_chunk_identity.py ....                                [ 31%]
tests\context\test_chunk_invalidation.py ....                            [ 34%]
tests\context\test_chunk_lifecycle.py .                                  [ 35%]
tests\context\test_chunk_parent_context.py ...                           [ 38%]
tests\context\test_chunk_preparation.py ...........                      [ 48%]
tests\context\test_chunk_reproducibility.py ..                           [ 50%]
tests\context\test_chunk_serialization.py ...                            [ 53%]
tests\context\test_chunk_service.py .....                                [ 57%]
tests\context\test_chunk_traceability.py ...                             [ 60%]
tests\context\test_chunk_validity.py .....                               [ 65%]
tests\context\test_chunk_windows_paths.py .                              [ 66%]
tests\context\test_chunk_windows_restart.py .                            [ 66%]
tests\context\test_contract_boundary.py .....                            [ 71%]
tests\context\test_integration.py .                                      [ 72%]
tests\context\test_json_builder.py ......                                [ 77%]
tests\context\test_measurement.py .....                                  [ 82%]
tests\context\test_preparation.py .........                              [ 90%]
tests\context\test_safe_diagnostics.py ...                               [ 93%]
tests\context\test_serialization.py .....                                [ 98%]
tests\context\test_windows_paths.py .                                    [ 99%]
tests\context\test_windows_restart.py .                                  [100%]

=============================== tests coverage ================================
TOTAL                                                 967     61    94%
============================= 109 passed in 2.05s =============================
```

### 2. Execution from Outside Working Directory ($env:TEMP)
```powershell
Push-Location -LiteralPath $env:TEMP
try {
    & "c:\Users\mrite\Projects\job-search\.venv\Scripts\python.exe" -m pytest "c:\Users\mrite\Projects\job-search\tests\context\test_chunk_windows_paths.py" "c:\Users\mrite\Projects\job-search\tests\context\test_chunk_windows_restart.py"
} finally {
    Pop-Location
}
```
Output:
```text
============================== 2 passed in 0.51s ==============================
```

### 3. Full Repository Regression Suite
```powershell
& ".\.venv\Scripts\python.exe" -m pytest
```
Output:
```text
============================ 897 passed in 17.17s =============================
```
Zero regressions across all existing components (FND-01, DATA-01, PROFILE-01, INGEST-01/02, SOURCE-01/02/03, POLICY-01, IDENTITY-01/02, MATCH-01, LLM-01, CONTEXT-01).

