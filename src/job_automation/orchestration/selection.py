"""Authoritative assessment selection and token registration management (RUN-01-S06)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import AssessmentDisposition
from job_automation.orchestration.records import AssessmentSelection
from job_automation.storage.engine import StorageEngine

if TYPE_CHECKING:
    from job_automation.salesforce.sync_service import SyncService

logger = logging.getLogger(__name__)


class SelectionManager:
    """Manages authoritative assessment selection manifests and sync token registration."""

    def __init__(self, engine: StorageEngine, sync_service: SyncService | None = None) -> None:
        self.engine = engine
        self.sync_service = sync_service

    def build_generation_token(self, input_fingerprint: str) -> str:
        """Construct a stable, deterministic selection generation token from input fingerprint."""
        return f"gen_{input_fingerprint[:16]}"

    def register_selection_token(
        self,
        canonical_job_id: uuid.UUID,
        generation_token: str,
    ) -> None:
        """Register the active generation token in sync state."""
        if self.sync_service:
            self.sync_service.register_selection_token(canonical_job_id, generation_token)
        else:
            self.engine.sync_state.register_selection_token(canonical_job_id, generation_token)

    def get_active_selection(
        self,
        canonical_job_id: uuid.UUID,
        purpose: str = "assessment",
    ) -> AssessmentSelection | None:
        """Retrieve the current active selection for a canonical job."""
        return self.engine.pipeline_work.get_active_selection(canonical_job_id, purpose=purpose)

    def select_and_persist(
        self,
        canonical_job_id: uuid.UUID,
        candidate_id: uuid.UUID,
        assessment: Assessment,
        input_fingerprint: str,
        generation_token: str,
        purpose: str = "assessment",
    ) -> AssessmentSelection:
        """Register token, mark selection authoritative, and persist selection manifest."""
        self.register_selection_token(canonical_job_id, generation_token)

        selection = AssessmentSelection(
            canonical_job_id=canonical_job_id,
            candidate_id=candidate_id,
            purpose=purpose,
            input_fingerprint=input_fingerprint,
            assessment_id=assessment.assessment_id,
            evaluated_at=datetime.now(timezone.utc),
            generation_token=generation_token,
            is_selected_final=True,
            disposition=assessment.final_disposition,
        )
        self.engine.pipeline_work.save_assessment_selection(selection)
        return selection
