"""Snapshot-aware job binding validator for GEN-02 context construction."""

from __future__ import annotations

import uuid
from typing import Callable

from job_automation.context.errors import JobBindingError
from job_automation.context.ports import JobBindingPort
from job_automation.contracts.postings import NormalizedPosting
from job_automation.identity.hashing import compute_revision_content_hash


class FrozenJobBindingValidator(JobBindingPort):
    """Snapshot-aware validator binding NormalizedPosting to target canonical job and revision."""

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
        """Validate that the frozen posting corresponds to canonical_job_id and posting_revision.

        Enforces:
        - canonical_job_id must be a valid UUID.
        - posting_revision must be a non-empty string.
        - posting must be an instance of NormalizedPosting with non-empty title.
        - If posting_revision starts with 'sha256:', it is validated against IDENTITY-01's material
          content hash (compute_revision_content_hash) as well as C06 raw_content_hash.
        - Verifies the frozen membership without querying current live identity mappings.
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

        clean_revision = posting_revision.strip()
        if clean_revision.startswith("sha256:"):
            material_hash = compute_revision_content_hash(posting)
            raw_hash_val = posting.raw_content_hash
            raw_hash = raw_hash_val if isinstance(raw_hash_val, str) else getattr(raw_hash_val, "value", str(raw_hash_val))

            if clean_revision != material_hash and clean_revision != raw_hash:
                raise JobBindingError(
                    f"Job revision content hash mismatch: revision declares '{clean_revision}', "
                    f"material hash is '{material_hash}', raw hash is '{raw_hash}'",
                    field_path="posting_revision",
                    details={
                        "declared_revision": clean_revision,
                        "material_content_hash": material_hash,
                        "raw_content_hash": raw_hash,
                    },
                )

        if self._custom_validator is not None:
            is_valid = self._custom_validator(canonical_job_id, clean_revision, posting)
            if not is_valid:
                raise JobBindingError(
                    f"Job binding verification failed for revision '{clean_revision}'",
                    field_path="posting_revision",
                )

