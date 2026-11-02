# JSON Schemas — Version 1 (v1)

This directory contains versioned JSON Schemas (Draft 2020-12) for all shared contracts defined by FND-01:

| Schema File | Contract | Model Class | Owning Story |
|---|---|---|---|
| `common.schema.json` | Primitives & Enums | Primitive definitions & enums | FND-01-S02 |
| `C01_profile_snapshot.schema.json` | C01 | `ProfileSnapshot` | FND-01-S03 |
| `C02_search_policy.schema.json` | C02 | `SearchPolicy` | FND-01-S03 |
| `C03_source_config.schema.json` | C03 | `SourceConfig` | FND-01-S04 |
| `C04_fetch_manifest.schema.json` | C04 | `FetchManifest` | FND-01-S04 |
| `C05_raw_posting.schema.json` | C05 | `RawPosting` | FND-01-S04 |
| `C05_source_job_draft.schema.json` | C05 | `SourceJobDraft` | FND-01-S04 |
| `C06_normalized_posting.schema.json` | C06 | `NormalizedPosting` | FND-01-S04 |
| `C07_canonical_job.schema.json` | C07 | `CanonicalJob` | FND-01-S04 |
| `C07_posting_revision.schema.json` | C07 | `PostingRevision` | FND-01-S04 |
| `C08_candidate_evidence_reference.schema.json` | C08 | `CandidateEvidenceReference` | FND-01-S03 |
| `C08_job_evidence_reference.schema.json` | C08 | `JobEvidenceReference` | FND-01-S03 |
| `C09_context_bundle.schema.json` | C09 | `ContextBundle` | FND-01-S05 |
| `C10_model_call.schema.json` | C10 | `ModelCall` | FND-01-S05 |
| `C10_model_result.schema.json` | C10 | `ModelResult` | FND-01-S05 |
| `C11_assessment.schema.json` | C11 | `Assessment` | FND-01-S05 |
| `C12_sync_operation.schema.json` | C12 | `SyncOperation` | FND-01-S06 |
| `C13_generation_request.schema.json` | C13 | `GenerationRequest` | FND-01-S06 |
| `C14_draft_document.schema.json` | C14 | `DraftDocument` | FND-01-S06 |
| `C14_artifact.schema.json` | C14 | `Artifact` | FND-01-S06 |
| `C15_run_summary.schema.json` | C15 | `RunSummary` | FND-01-S06 |
| `app_config.schema.json` | App Configuration | `AppConfig` | FND-01-S08 |
| `chunk_build_request.schema.json` | Context Auxiliary | `ChunkBuildRequest` | CONTEXT-02-S01 |
| `chunking_settings.schema.json` | Context Auxiliary | `ChunkingSettings` | CONTEXT-02-S01 |
| `evidence_chunk.schema.json` | Context Auxiliary | `EvidenceChunk` | CONTEXT-02-S01 |
| `chunk_source_mapping.schema.json` | Context Auxiliary | `ChunkSourceMapping` | CONTEXT-02-S01 |
| `ancestor_context.schema.json` | Context Auxiliary | `AncestorContext` | CONTEXT-02-S01 |
| `chunk_set.schema.json` | Context Auxiliary | `ChunkSet` | CONTEXT-02-S01 |
| `binding_transition.schema.json` | Context Auxiliary | `BindingTransition` | CONTEXT-02-S01 |
| `chunk_change_set.schema.json` | Context Auxiliary | `ChunkChangeSet` | CONTEXT-02-S01 |
| `index_settings.schema.json` | Context Auxiliary | `IndexSettings` | CONTEXT-03-S01 |
| `embedding_configuration.schema.json` | Context Auxiliary | `EmbeddingConfiguration` | CONTEXT-03-S01 |
| `index_manifest.schema.json` | Context Auxiliary | `IndexManifest` | CONTEXT-03-S01 |
| `index_build_request.schema.json` | Context Auxiliary | `IndexBuildRequest` | CONTEXT-03-S01 |
| `index_build_record.schema.json` | Context Auxiliary | `IndexBuildRecord` | CONTEXT-03-S01 |
| `index_build_result.schema.json` | Context Auxiliary | `IndexBuildResult` | CONTEXT-03-S01 |
| `index_read_request.schema.json` | Context Auxiliary | `IndexReadRequest` | CONTEXT-03-S01 |

## Deterministic Generation

These schemas are generated deterministically from the Pydantic contract definitions using:

```powershell
.\.venv\Scripts\python.exe -m job_automation.contracts.export_schemas
```

Do not edit generated schemas manually. Modify the Pydantic models in `src/job_automation/contracts/` and regenerate schemas.

