"""Context package for full-profile JSON context generation and budgeting (CONTEXT-01)."""

from __future__ import annotations

from job_automation.context.binding import DefaultJobBindingValidator
from job_automation.context.budget import BudgetEvaluator
from job_automation.context.errors import (
    ContextBudgetOverflowError,
    ContextConfigurationError,
    ContextError,
    ContextPermissionError,
    ContextUnsupportedError,
    ContextValidationError,
    JobBindingError,
    MeasurementError,
    RetrievalChannelError,
    RetrievalError,
    RetrievalIncompatibleError,
    RetrievalStaleError,
    map_context_exception_to_classified_error,
)
from job_automation.context.fusion import ReciprocalRankFuser
from job_automation.context.keyword_retrieval import KeywordRetriever
from job_automation.context.queries import DefaultQueryBuilder
from job_automation.context.query_embeddings import QueryEmbeddingCoordinator
from job_automation.context.rag_builder import RAGContextBuilder
from job_automation.context.retrieval_settings import (
    DEFAULT_RETRIEVAL_SETTINGS,
    RetrievalSettings,
)
from job_automation.context.semantic_retrieval import SemanticRetriever
from job_automation.context.selector import (
    ContextSelectorV2Service,
    LegacyContextSelectorAdapter,
)
from job_automation.context.selector_ports import (
    ContextSelectorV2Port,
    QueryBuilderPort,
    RAGContextBuilderPort,
)
from job_automation.context.selector_records import (
    ContextSelectionRequest,
    ContextSelectionResult,
    FusedCandidate,
    RequirementQuery,
    RequirementQuerySet,
    RetrievalHit,
    RetrievalTrace,
)
from job_automation.context.selector_validation import (
    validate_context_selection_request,
)
from job_automation.context.chunk_builder import ChunkBuilder
from job_automation.context.chunk_changes import compare_chunk_manifests
from job_automation.context.chunk_errors import (
    ChunkBindingError,
    ChunkCapacityError,
    ChunkConfigurationError,
    ChunkError,
    ChunkPermissionError,
    ChunkUnsupportedError,
    ChunkValidationError,
    map_chunk_exception_to_classified_error,
)
from job_automation.context.chunk_identity import (
    CHUNK_IDENTITY_NAMESPACE,
    compute_binding_fingerprint,
    compute_chunk_content_version,
    compute_fact_dependency_fingerprint,
    compute_manifest_fingerprint,
    compute_settings_fingerprint,
    compute_snapshot_fingerprint,
    generate_chunk_id,
)
from job_automation.context.chunk_manifest import ChunkManifestBuilder
from job_automation.context.chunk_ports import (
    ChunkRendererPort,
    EvidenceChunkerPort,
)
from job_automation.context.chunk_preparation import (
    ChunkEvidencePreparer,
    PreparedChunkData,
    PreparedChunkFact,
)
from job_automation.context.chunk_rendering import DefaultChunkRenderer
from job_automation.context.chunk_serialization import (
    deserialize_chunk_change_set_from_json,
    deserialize_chunk_set_from_json,
    serialize_chunk_change_set_to_json,
    serialize_chunk_set_to_json,
    serialize_chunk_to_json,
)
from job_automation.context.chunk_service import EvidenceChunker
from job_automation.context.chunk_settings import DEFAULT_CHUNKING_SETTINGS
from job_automation.context.chunk_traceability import ChunkTraceabilityValidator
from job_automation.context.chunk_validity import validate_chunk_binding
from job_automation.contracts.evidence_chunks import (
    AncestorContext,
    BindingTransition,
    ChunkBuildRequest,
    ChunkChangeSet,
    ChunkSet,
    ChunkSourceMapping,
    ChunkingSettings,
    EvidenceChunk,
)
from job_automation.context.json_builder import JsonContextBuilder
from job_automation.context.measurement import (
    ConservativeCharRatioEstimator,
    ExactTokenCounter,
)
from job_automation.context.ports import (
    JobBindingPort,
    JsonContextBuilderPort,
    PromptRendererPort,
    TokenCounterPort,
)
from job_automation.context.preparation import ProfileContextPreparer
from job_automation.context.records import (
    JsonContextRequest,
    MeasurementResult,
    PreparedProfileContext,
    RenderedPrompt,
    WholePromptMeasurement,
)
from job_automation.context.rendering import DefaultPromptRenderer
from job_automation.context.service import ContextService
from job_automation.context.settings import ContextSettings
from job_automation.contracts.retrieval_index import (
    EmbeddingConfiguration,
    IndexBuildRecord,
    IndexBuildRequest,
    IndexBuildResult,
    IndexManifest,
    IndexPin,
    IndexReadRequest,
    IndexRowMapping,
    IndexSettings,
    PayloadFileInfo,
    TermPosting,
)
from job_automation.context.index_capacity import (
    check_index_capacity_preflight,
    estimate_build_staging_bytes,
    estimate_matrix_bytes,
    validate_index_path,
)
from job_automation.context.index_errors import (
    IndexBindingError,
    IndexCapacityError,
    IndexConfigurationError,
    IndexCorruptionError,
    IndexError,
    IndexIncompatibleError,
    IndexPermissionError,
    IndexStaleError,
    IndexStorageError,
    IndexValidationError,
    map_index_exception_to_classified_error,
)
from job_automation.context.index_identity import (
    compute_artifact_fingerprint,
    compute_embedding_space_fingerprint,
    compute_index_settings_fingerprint,
    compute_logical_build_fingerprint,
    validate_embedding_space_compatibility,
)
from job_automation.context.index_ports import (
    IndexBuilderPort,
    IndexHandlePort,
    IndexStorePort,
)
from job_automation.context.index_settings import (
    DEFAULT_INDEX_SETTINGS,
    load_index_settings,
)
from job_automation.context.index_embeddings import IndexEmbeddingCoordinator
from job_automation.context.index_model_audit import IndexAuditSink
from job_automation.context.vector_matrix import VectorMatrixReader, VectorMatrixWriter
from job_automation.context.keyword_index import (
    KeywordAnalyzer,
    KeywordIndexReader,
    KeywordIndexWriter,
)
from job_automation.context.index_manifest import IndexManifestBuilder
from job_automation.context.index_builder import IndexBuilder
from job_automation.context.index_lifecycle import IndexLifecycleManager
from job_automation.context.index_cleanup import IndexCleanupManager
from job_automation.context.index_recovery import IndexRecoveryManager
from job_automation.context.index_reader import IndexHandle, IndexStore
from job_automation.context.index_service import IndexService

__all__ = [
    "ContextService",
    "JsonContextBuilder",
    "ProfileContextPreparer",
    "BudgetEvaluator",
    "ConservativeCharRatioEstimator",
    "ExactTokenCounter",
    "DefaultJobBindingValidator",
    "DefaultPromptRenderer",
    "JsonContextRequest",
    "PreparedProfileContext",
    "RenderedPrompt",
    "MeasurementResult",
    "WholePromptMeasurement",
    "ContextSettings",
    "JobBindingPort",
    "TokenCounterPort",
    "PromptRendererPort",
    "JsonContextBuilderPort",
    "ContextError",
    "ContextValidationError",
    "ContextPermissionError",
    "ContextBudgetOverflowError",
    "ContextConfigurationError",
    "ContextUnsupportedError",
    "JobBindingError",
    "MeasurementError",
    "map_context_exception_to_classified_error",
    # CONTEXT-02 Evidence Chunking
    "EvidenceChunker",
    "ChunkEvidencePreparer",
    "PreparedChunkData",
    "PreparedChunkFact",
    "DefaultChunkRenderer",
    "ChunkTraceabilityValidator",
    "ChunkBuilder",
    "ChunkManifestBuilder",
    "EvidenceChunkerPort",
    "ChunkRendererPort",
    "DEFAULT_CHUNKING_SETTINGS",
    "ChunkingSettings",
    "AncestorContext",
    "ChunkSourceMapping",
    "EvidenceChunk",
    "ChunkSet",
    "BindingTransition",
    "ChunkChangeSet",
    "ChunkBuildRequest",
    "compare_chunk_manifests",
    "validate_chunk_binding",
    "generate_chunk_id",
    "CHUNK_IDENTITY_NAMESPACE",
    "compute_fact_dependency_fingerprint",
    "compute_chunk_content_version",
    "compute_binding_fingerprint",
    "compute_snapshot_fingerprint",
    "compute_settings_fingerprint",
    "compute_manifest_fingerprint",
    "serialize_chunk_to_json",
    "serialize_chunk_set_to_json",
    "serialize_chunk_change_set_to_json",
    "deserialize_chunk_set_from_json",
    "deserialize_chunk_change_set_from_json",
    "ChunkError",
    "ChunkValidationError",
    "ChunkPermissionError",
    "ChunkCapacityError",
    "ChunkBindingError",
    "ChunkConfigurationError",
    "ChunkUnsupportedError",
    "map_chunk_exception_to_classified_error",
    # CONTEXT-03 Local Indexing
    "IndexService",
    "IndexBuilder",
    "IndexStore",
    "IndexHandle",
    "IndexLifecycleManager",
    "IndexCleanupManager",
    "IndexRecoveryManager",
    "IndexEmbeddingCoordinator",
    "IndexAuditSink",
    "VectorMatrixWriter",
    "VectorMatrixReader",
    "KeywordAnalyzer",
    "KeywordIndexWriter",
    "KeywordIndexReader",
    "IndexManifestBuilder",
    "DEFAULT_INDEX_SETTINGS",
    "load_index_settings",
    "estimate_matrix_bytes",
    "estimate_build_staging_bytes",
    "validate_index_path",
    "check_index_capacity_preflight",
    "IndexBuilderPort",
    "IndexStorePort",
    "IndexHandlePort",
    "IndexError",
    "IndexValidationError",
    "IndexIncompatibleError",
    "IndexBindingError",
    "IndexStaleError",
    "IndexPermissionError",
    "IndexCapacityError",
    "IndexConfigurationError",
    "IndexStorageError",
    "IndexCorruptionError",
    "map_index_exception_to_classified_error",
    "compute_embedding_space_fingerprint",
    "compute_index_settings_fingerprint",
    "compute_logical_build_fingerprint",
    "compute_artifact_fingerprint",
    "validate_embedding_space_compatibility",
    "IndexSettings",
    "EmbeddingConfiguration",
    "IndexManifest",
    "IndexRowMapping",
    "PayloadFileInfo",
    "IndexBuildRequest",
    "IndexBuildResult",
    "IndexBuildRecord",
    "IndexReadRequest",
    "TermPosting",
    "IndexPin",
    "RetrievalSettings",
    "DEFAULT_RETRIEVAL_SETTINGS",
    "ContextSelectionRequest",
    "ContextSelectionResult",
    "RequirementQuery",
    "RequirementQuerySet",
    "RetrievalHit",
    "FusedCandidate",
    "RetrievalTrace",
    "ContextSelectorV2Port",
    "QueryBuilderPort",
    "RAGContextBuilderPort",
    "ContextSelectorV2Service",
    "LegacyContextSelectorAdapter",
    "validate_context_selection_request",
    "DefaultQueryBuilder",
    "QueryEmbeddingCoordinator",
    "KeywordRetriever",
    "SemanticRetriever",
    "ReciprocalRankFuser",
    "RAGContextBuilder",
    "RetrievalError",
    "RetrievalIncompatibleError",
    "RetrievalStaleError",
    "RetrievalChannelError",
]

