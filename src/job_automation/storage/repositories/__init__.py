"""Typed SQLite storage repositories."""

from __future__ import annotations

from job_automation.storage.repositories.artifacts import ArtifactRepository
from job_automation.storage.repositories.assessments import AssessmentRepository
from job_automation.storage.repositories.availability import AvailabilityRepository
from job_automation.storage.repositories.canonical_jobs import CanonicalJobRepository
from job_automation.storage.repositories.context_indexes import ContextIndexRepository
from job_automation.storage.repositories.generation_requests import GenerationRequestRepository
from job_automation.storage.repositories.identity import IdentityRepository
from job_automation.storage.repositories.profiles import ProfileRepository
from job_automation.storage.repositories.raw_postings import RawPostingRepository
from job_automation.storage.repositories.runs import RunLedgerRepository
from job_automation.storage.repositories.sync_outbox import SyncOutboxRepository
from job_automation.storage.repositories.sync_state import SyncStateRepository
from job_automation.storage.repositories.candidate_snapshots import CandidateSnapshotRepository
from job_automation.storage.repositories.pipeline_work import PipelineWorkRepository
from job_automation.storage.repositories.operations import OperationsRepository
from job_automation.storage.repositories.draft_content import DraftContentRepository
from job_automation.storage.repositories.document_validations import DocumentValidationRepository
from job_automation.storage.repositories.render_artifacts import RenderArtifactRepository
from job_automation.storage.repositories.artifact_deliveries import ArtifactDeliveryRepository
from job_automation.storage.repositories.run_summary_deliveries import RunSummaryDeliveryRepository

__all__ = [
    "ArtifactDeliveryRepository",
    "ArtifactRepository",
    "AssessmentRepository",
    "AvailabilityRepository",
    "CanonicalJobRepository",
    "CandidateSnapshotRepository",
    "ContextIndexRepository",
    "DocumentValidationRepository",
    "DraftContentRepository",
    "GenerationRequestRepository",
    "IdentityRepository",
    "OperationsRepository",
    "PipelineWorkRepository",
    "ProfileRepository",
    "RawPostingRepository",
    "RenderArtifactRepository",
    "RunLedgerRepository",
    "RunSummaryDeliveryRepository",
    "SyncOutboxRepository",
    "SyncStateRepository",
]

