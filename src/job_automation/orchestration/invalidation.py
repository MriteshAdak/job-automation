"""Input-version invalidation and cache reuse evaluator (RUN-01-S03, S06).

Enforces:
- Exact composite fingerprint matching over revision, profile, policy, and model inputs.
- Unchanged inputs reuse stable C11 assessment and evaluation timestamp with zero evaluator calls.
- Profile changes, policy edits, or job revision updates trigger targeted re-evaluation.
- Distinguishes discovery candidates from global input invalidation across retained jobs.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from job_automation.contracts.assessment import Assessment
from job_automation.orchestration.fingerprints import compute_assessment_composite_fingerprint
from job_automation.orchestration.records import AssessmentSelection
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class InvalidationEvaluator:
    """Evaluates input fingerprints to determine whether existing assessments remain valid."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine

    def check_invalidation(
        self,
        canonical_job_id: uuid.UUID,
        revision_content_hash: str,
        profile_snapshot_hash: str,
        policy_fingerprint: str,
        assessment_mode: str,
        strategy: str | None = None,
        model_identifier: str | None = None,
        prompt_version: str | None = None,
    ) -> tuple[bool, str, AssessmentSelection | None, Assessment | None]:
        """Check if job requires re-assessment.

        Returns (requires_reassessment, target_fingerprint, active_selection, existing_assessment).
        """
        target_fp = compute_assessment_composite_fingerprint(
            revision_content_hash=revision_content_hash,
            profile_snapshot_hash=profile_snapshot_hash,
            policy_fingerprint=policy_fingerprint,
            assessment_mode=assessment_mode,
            strategy=strategy,
            model_identifier=model_identifier,
            prompt_version=prompt_version,
        )

        active_sel = self.engine.pipeline_work.get_active_selection(canonical_job_id)
        if active_sel is None:
            return True, target_fp, None, None

        if active_sel.input_fingerprint != target_fp:
            # Inputs have changed -> invalidated
            return True, target_fp, None, None

        # Verify that referenced C11 assessment exists in durable storage
        existing_asmt = self.engine.assessments.get_assessment(active_sel.assessment_id)
        if existing_asmt is None:
            # Assessment missing from storage -> must re-evaluate
            return True, target_fp, None, None

        # Unchanged: reuse valid assessment
        return False, target_fp, active_sel, existing_asmt

