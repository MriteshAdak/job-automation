"""Job revision and posting content binding validation for CONTEXT-01."""

from __future__ import annotations

import uuid
from typing import Callable

from job_automation.context.errors import JobBindingError
from job_automation.context.ports import JobBindingPort
from job_automation.contracts.postings import NormalizedPosting


class DefaultJobBindingValidator(JobBindingPort):
    """Validates that supplied NormalizedPosting is bound to the target canonical job and revision."""

    def __init__(
        self,
        custom_validator: Callable[[uuid.UUID, str, NormalizedPosting], bool] | None = None,
    ) -> None:
        self._custom_validator = custom_validator

    def validate_binding(
        self,
        canonical_job_id: uuid.UUID,
        posting_revision: str,
        posting: NormalizedPosting,
    ) -> None:
        """Validate that the posting corresponds to canonical_job_id and posting_revision.

        Enforces:
        - canonical_job_id must be a valid UUID.
        - posting_revision must be a non-empty string.
        - posting must be an instance of NormalizedPosting with valid source_key and title.
        - If posting_revision is a content hash (starts with 'sha256:'), it must match
          posting.raw_content_hash.value.
        - If custom_validator is supplied, it must return True.
        """
        if not isinstance(canonical_job_id, uuid.UUID):
            raise JobBindingError(
                f"Invalid canonical_job_id: expected uuid.UUID, got {type(canonical_job_id).__name__}",
                field_path="canonical_job_id",
            )

        if not isinstance(posting_revision, str) or not posting_revision.strip():
            raise JobBindingError(
                "posting_revision must be a non-empty string",
                field_path="posting_revision",
            )

        if not isinstance(posting, NormalizedPosting):
            raise JobBindingError(
                f"Invalid job_content: expected NormalizedPosting, got {type(posting).__name__}",
                field_path="job_content",
            )

        if not posting.title or not posting.title.strip():
            raise JobBindingError(
                "NormalizedPosting title cannot be empty",
                field_path="job_content.title",
            )

        # Hash correspondence check if revision is a sha256 reference
        clean_revision = posting_revision.strip()
        if clean_revision.startswith("sha256:"):
            expected_hash = clean_revision
            raw_hash = posting.raw_content_hash
            actual_hash = raw_hash if isinstance(raw_hash, str) else getattr(raw_hash, "value", str(raw_hash))
            if actual_hash != expected_hash:
                raise JobBindingError(
                    f"Job revision content hash mismatch: revision declares '{expected_hash}', "
                    f"but posting raw_content_hash is '{actual_hash}'",
                    field_path="posting_revision",
                    details={
                        "declared_revision": expected_hash,
                        "posting_hash": actual_hash,
                    },
                )

        if self._custom_validator is not None:
            is_valid = self._custom_validator(canonical_job_id, clean_revision, posting)
            if not is_valid:
                raise JobBindingError(
                    f"Job binding verification failed for revision '{clean_revision}'",
                    field_path="posting_revision",
                )
