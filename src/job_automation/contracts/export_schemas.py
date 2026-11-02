"""Deterministic schema exporter for all FND-01 contracts.

Generates versioned JSON Schemas under schemas/v1/ using Pydantic model_json_schema().
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Type

from pydantic import BaseModel

from job_automation.configuration import AppConfig
from job_automation.assessment.llm_records import AssessmentProposal
from job_automation.salesforce.configuration import SalesforceSettings
from job_automation.salesforce.sync_settings import SyncMappingConfig
from job_automation.salesforce.sync_records import (
    CandidateBackupResult,
    CandidateFieldSnapshot,
    DrainResult,
    ReconciliationResult,
    RemoteEntityMapping,
    SyncPlan,
    SyncPlanResult,
    SyncSubmission,
    SyncWriteStep,
)
from job_automation.contracts.salesforce import (
    AttemptSummary,
    ConnectionCheckRequest,
    ConnectionCheckResult,
    DescribeFieldResult,
    DescribeObjectRequest,
    DescribeObjectResult,
    GatewayFailure,
    GetRecordRequest,
    GetRecordResult,
    LimitsRequest,
    LimitsResult,
    QueryPageRequest,
    QueryPageResult,
    UpdateRequest,
    UpdateResult,
    UpsertRequest,
    UpsertResult,
)
from job_automation.models.configuration import ModelProviderSettings
from job_automation.context.retrieval_settings import RetrievalSettings
from job_automation.contracts.adapter_results import (
    AdapterPage,
    Continuation,
    DraftResult,
    RecordIssue,
)
from job_automation.contracts.artifacts import Artifact, DraftDocument
from job_automation.contracts.draft_content import DraftContentProposal, DraftDocumentV2
from job_automation.generation.draft_prompts import DraftRecipe
from job_automation.generation.draft_records import DraftGenerationReceipt
from job_automation.contracts.assessment import Assessment
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.errors import ClassifiedError, ValidationIssue
from job_automation.contracts.evidence import (
    CandidateEvidenceReference,
    JobEvidenceReference,
)
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
from job_automation.contracts.retrieval_index import (
    EmbeddingConfiguration,
    IndexBuildRecord,
    IndexBuildRequest,
    IndexBuildResult,
    IndexManifest,
    IndexReadRequest,
    IndexSettings,
)
from job_automation.contracts.generation import GenerationRequest
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.models import ModelCall, ModelResult
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import (
    FetchManifest,
    NormalizedPosting,
    RawPosting,
    SourceJobDraft,
)
from job_automation.contracts.primitives import MoneyAmount, PrecisionDate, SourceKey
from job_automation.contracts.profile import ProfileSnapshot
from job_automation.contracts.sources import SourceConfig
from job_automation.contracts.sync import SyncOperation
from job_automation.contracts.runs import RunSummary
from job_automation.operations.records import (
    BackupManifest,
    CapacityReport,
    CleanupPlan,
    CleanupResult,
    MaintenanceReport,
    OperationsSettings,
    RemoteRecoveryExport,
    RestorePlan,
    RestoreResult,
    RetentionInventory,
)
from job_automation.generation.input_records import (
    AvailabilityCheck,
    FrozenContextReceipt,
    FrozenContextRecipe,
    FrozenGenerationOptions,
    FrozenJobSnapshot,
    FrozenProfileSnapshot,
    FrozenSeal,
    GenerationInputSettings,
    PreflightReceipt,
)
from job_automation.generation.validation_records import (
    DocumentValidationIssue,
    DocumentValidationReport,
    DocumentValidationSettings,
    ValidatedDraftForRendering,
    ValidationContentRequirements,
    ValidationInputBinding,
)

CONTRACT_MODELS: dict[str, Type[BaseModel]] = {
    "C01_profile_snapshot": ProfileSnapshot,
    "C02_search_policy": SearchPolicy,
    "C03_source_config": SourceConfig,
    "C04_fetch_manifest": FetchManifest,
    "C05_raw_posting": RawPosting,
    "C05_source_job_draft": SourceJobDraft,
    "C06_normalized_posting": NormalizedPosting,
    "C07_canonical_job": CanonicalJob,
    "C07_posting_revision": PostingRevision,
    "C08_candidate_evidence_reference": CandidateEvidenceReference,
    "C08_job_evidence_reference": JobEvidenceReference,
    "C09_context_bundle": ContextBundle,
    "C10_model_call": ModelCall,
    "C10_model_result": ModelResult,
    "C11_assessment": Assessment,
    "C12_sync_operation": SyncOperation,
    "C13_generation_request": GenerationRequest,
    "C14_draft_document": DraftDocument,
    "C14_artifact": Artifact,
    "C15_run_summary": RunSummary,
    "app_config": AppConfig,
    "model_provider_settings": ModelProviderSettings,
    "adapter_page": AdapterPage,
    "continuation": Continuation,
    "record_issue": RecordIssue,
    "draft_result": DraftResult,
    "chunk_build_request": ChunkBuildRequest,
    "chunking_settings": ChunkingSettings,
    "evidence_chunk": EvidenceChunk,
    "chunk_source_mapping": ChunkSourceMapping,
    "ancestor_context": AncestorContext,
    "chunk_set": ChunkSet,
    "binding_transition": BindingTransition,
    "chunk_change_set": ChunkChangeSet,
    "index_settings": IndexSettings,
    "embedding_configuration": EmbeddingConfiguration,
    "index_manifest": IndexManifest,
    "index_build_request": IndexBuildRequest,
    "index_build_record": IndexBuildRecord,
    "index_build_result": IndexBuildResult,
    "index_read_request": IndexReadRequest,
    "retrieval_settings": RetrievalSettings,
    "assessment_proposal": AssessmentProposal,
    "salesforce_settings": SalesforceSettings,
    "salesforce_attempt_summary": AttemptSummary,
    "salesforce_gateway_failure": GatewayFailure,
    "salesforce_connection_check_request": ConnectionCheckRequest,
    "salesforce_connection_check_result": ConnectionCheckResult,
    "salesforce_limits_request": LimitsRequest,
    "salesforce_limits_result": LimitsResult,
    "salesforce_describe_object_request": DescribeObjectRequest,
    "salesforce_describe_field_result": DescribeFieldResult,
    "salesforce_describe_object_result": DescribeObjectResult,
    "salesforce_get_record_request": GetRecordRequest,
    "salesforce_get_record_result": GetRecordResult,
    "salesforce_query_page_request": QueryPageRequest,
    "salesforce_query_page_result": QueryPageResult,
    "salesforce_upsert_request": UpsertRequest,
    "salesforce_upsert_result": UpsertResult,
    "salesforce_update_request": UpdateRequest,
    "salesforce_update_result": UpdateResult,
    "sync_submission": SyncSubmission,
    "sync_mapping_config": SyncMappingConfig,
    "sync_write_step": SyncWriteStep,
    "sync_plan": SyncPlan,
    "sync_remote_mapping": RemoteEntityMapping,
    "sync_candidate_field_snapshot": CandidateFieldSnapshot,
    "sync_plan_result": SyncPlanResult,
    "sync_drain_result": DrainResult,
    "sync_reconciliation_result": ReconciliationResult,
    "sync_candidate_backup_result": CandidateBackupResult,
    "ops_settings": OperationsSettings,
    "ops_retention_inventory": RetentionInventory,
    "ops_capacity_report": CapacityReport,
    "ops_cleanup_plan": CleanupPlan,
    "ops_cleanup_result": CleanupResult,
    "ops_remote_recovery_export": RemoteRecoveryExport,
    "ops_backup_manifest": BackupManifest,
    "ops_restore_plan": RestorePlan,
    "ops_restore_result": RestoreResult,
    "ops_maintenance_report": MaintenanceReport,
    "frozen_generation_options": FrozenGenerationOptions,
    "frozen_job_snapshot": FrozenJobSnapshot,
    "frozen_profile_snapshot": FrozenProfileSnapshot,
    "availability_check": AvailabilityCheck,
    "frozen_context_recipe": FrozenContextRecipe,
    "frozen_seal": FrozenSeal,
    "preflight_receipt": PreflightReceipt,
    "frozen_context_receipt": FrozenContextReceipt,
    "generation_input_settings": GenerationInputSettings,
    "draft_content_proposal": DraftContentProposal,
    "draft_recipe": DraftRecipe,
    "draft_generation_receipt": DraftGenerationReceipt,
    "document_validation_report": DocumentValidationReport,
    "document_validation_issue": DocumentValidationIssue,
    "validation_input_binding": ValidationInputBinding,
    "validation_content_requirements": ValidationContentRequirements,
    "document_validation_settings": DocumentValidationSettings,
    "validated_draft_for_rendering": ValidatedDraftForRendering,
}


def export_schemas(output_dir: Path) -> None:
    """Export all contract JSON schemas to the target directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for name, model_cls in CONTRACT_MODELS.items():
        schema = model_cls.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://job-automation.local/schemas/v1/{name}.schema.json"

        dest = output_dir / f"{name}.schema.json"
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)
            f.write("\n")

    v2_dir = output_dir.parent / "v2"
    v2_dir.mkdir(parents=True, exist_ok=True)
    schema = DraftDocumentV2.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://job-automation.local/schemas/v2/draft_document.schema.json"
    (v2_dir / "draft_document.schema.json").write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    schemas_dir = Path(__file__).resolve().parent.parent.parent.parent / "schemas" / "v1"
    export_schemas(schemas_dir)
    print(f"Exported {len(CONTRACT_MODELS)} schemas to {schemas_dir}")
