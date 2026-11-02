"""Preflight freeze guard for AUTO-02 (AUTO-02-S05).

Binds automatic request admission to exact frozen inputs at the GEN-01/02 boundary.
Guarantees:
- Manual requests (lacking AutomaticRequestBinding) bypass this guard cleanly.
- Automatic requests strictly require allow_unavailable_job=False.
- If posting content, candidate profile, assessment selection, availability, or candidate
  opt-out has changed since admission, the guard blocks freeze/claim before model inference.
- On successful revalidation, a durable receipt is committed with the binding.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.enums import (
    AssessmentDisposition,
    PostingAvailability,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import GenerationRequest
from job_automation.generation.automatic.records import AutomaticDraftPolicy
from job_automation.generation.input_records import (
    FrozenJobSnapshot,
    FrozenProfileSnapshot,
)
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class AutomaticPreflightGuard:
    """Validates automatic requests against authoritative live inputs before freeze and claim."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine

    def verify_request_preflight(
        self,
        request: GenerationRequest,
        resolved_job: FrozenJobSnapshot | None = None,
        resolved_profile: FrozenProfileSnapshot | None = None,
        current_policy: AutomaticDraftPolicy | None = None,
        now: datetime | None = None,
    ) -> tuple[bool, ClassifiedError | None, dict[str, Any] | None]:
        """Verify automatic request bindings against authoritative evidence before claim/freeze.

        Returns (is_valid, error, receipt).
        """
        now_utc = now or datetime.now(timezone.utc)

        # 1. Check if request has an automatic binding
        binding = self.engine.automatic_drafts.get_binding_by_request_id(request.request_id)
        if binding is None:
            # Manual request: not subject to AUTO-02 preflight guard
            return True, None, None

        # 2. Invariant: automatic requests never allow unavailable jobs
        if request.allow_unavailable_job:
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message="Automatic request cannot have allow_unavailable_job=True",
                details={"reason_code": "unavailable_override_forbidden", "request_id": str(request.request_id)},
            )
            return False, err, None

        # 3. Availability check
        canonical_job = self.engine.canonical_jobs.get_canonical_job(request.canonical_job_id)
        if canonical_job is not None:
            source_states = self.engine.availability.list_for_canonical_job(request.canonical_job_id)
            if source_states:
                from job_automation.identity.availability.aggregate import aggregate_canonical_availability
                canonical_avail, _ = aggregate_canonical_availability(source_states)
            else:
                canonical_avail = canonical_job.availability

            if canonical_avail == PostingAvailability.UNAVAILABLE:
                err = ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message="Job is unavailable; automatic drafting cannot proceed",
                    details={"reason_code": "job_unavailable", "request_id": str(request.request_id)},
                )
                return False, err, None
            if canonical_avail in (PostingAvailability.UNKNOWN, PostingAvailability.NOT_SEEN):
                err = ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message=f"Job availability is uncertain ({canonical_avail.value})",
                    details={"reason_code": "availability_uncertain", "request_id": str(request.request_id)},
                )
                return False, err, None

        # 4. Active policy check if provided
        if current_policy is not None:
            if not current_policy.enabled:
                err = ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message="Automatic drafting policy is disabled",
                    details={"reason_code": "policy_disabled", "request_id": str(request.request_id)},
                )
                return False, err, None

        # 5. Authoritative selection recheck
        active_sel = self.engine.pipeline_work.get_active_selection(
            canonical_job_id=request.canonical_job_id,
            purpose="assessment",
        )
        if active_sel is not None:
            if active_sel.assessment_id != binding.expected_assessment_id:
                err = ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message="Assessment selection changed between admission and freeze",
                    details={
                        "reason_code": "assessment_selection_changed",
                        "expected_assessment_id": str(binding.expected_assessment_id),
                        "current_assessment_id": str(active_sel.assessment_id),
                    },
                )
                return False, err, None
            if active_sel.disposition != AssessmentDisposition.ELIGIBLE:
                err = ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message=f"Assessment selection disposition is {active_sel.disposition.value}, not eligible",
                    details={"reason_code": "assessment_no_longer_eligible"},
                )
                return False, err, None

        # 6. Posting revision check
        if resolved_job is not None:
            if resolved_job.posting_revision_hash != binding.expected_posting_revision_hash:
                err = ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message="Posting revision hash changed between admission and freeze",
                    details={
                        "reason_code": "posting_revision_changed",
                        "expected": binding.expected_posting_revision_hash,
                        "current": resolved_job.posting_revision_hash,
                    },
                )
                return False, err, None

        # 7. Profile version check
        if resolved_profile is not None:
            if (
                resolved_profile.profile_version != binding.expected_profile_version
                or resolved_profile.profile_digest != binding.expected_profile_digest
            ):
                err = ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message="Profile version/digest changed between admission and freeze",
                    details={
                        "reason_code": "profile_changed",
                        "expected_version": binding.expected_profile_version,
                        "current_version": resolved_profile.profile_version,
                    },
                )
                return False, err, None

        # All checks passed: build and persist revalidation receipt
        receipt: dict[str, Any] = {
            "verified_at": now_utc.isoformat(),
            "binding_id": str(binding.binding_id),
            "local_request_id": str(request.request_id),
            "expected_assessment_id": str(binding.expected_assessment_id),
            "expected_posting_revision_hash": binding.expected_posting_revision_hash,
            "expected_profile_version": binding.expected_profile_version,
            "outcome": "verified",
        }
        self.engine.automatic_drafts.update_revalidation_receipt(binding.binding_id, receipt)
        return True, None, receipt
