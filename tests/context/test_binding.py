"""Tests for job revision and content binding validation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from job_automation.context.binding import DefaultJobBindingValidator
from job_automation.context.errors import JobBindingError
from job_automation.contracts.enums import WorkplaceType
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey


def create_sample_posting(hash_str: str = "sha256:" + "a" * 64, title: str = "Lead Architect") -> NormalizedPosting:
    return NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p-100"),
        normalizer_version="1.0",
        raw_reference="raw_ref_100",
        raw_content_hash=hash_str,
        company_name_hint="Acme Tech",
        title=title,
        description_clean="Responsible for scalable backend systems.",
        workplace_type=WorkplaceType.REMOTE,
        source_url="https://example.com/job/100",
        observed_at=datetime.now(timezone.utc),
    )


class TestJobBinding:
    def test_valid_binding_with_matching_content_hash(self) -> None:
        validator = DefaultJobBindingValidator()
        job_id = uuid.uuid4()
        rev_hash = "sha256:" + "a" * 64
        posting = create_sample_posting(hash_str=rev_hash)

        # Should succeed without raising
        validator.validate_binding(job_id, rev_hash, posting)

    def test_valid_binding_with_opaque_revision_label(self) -> None:
        validator = DefaultJobBindingValidator()
        job_id = uuid.uuid4()
        posting = create_sample_posting()

        # Non-hash revision strings (e.g. 'rev-2026-10-01') succeed
        validator.validate_binding(job_id, "rev-2026-10-01", posting)

    def test_content_hash_mismatch_rejected(self) -> None:
        validator = DefaultJobBindingValidator()
        job_id = uuid.uuid4()
        declared_hash = "sha256:" + "b" * 64
        actual_hash = "sha256:" + "a" * 64
        posting = create_sample_posting(hash_str=actual_hash)

        with pytest.raises(JobBindingError, match="content hash mismatch"):
            validator.validate_binding(job_id, declared_hash, posting)

    def test_empty_or_invalid_revision_rejected(self) -> None:
        validator = DefaultJobBindingValidator()
        job_id = uuid.uuid4()
        posting = create_sample_posting()

        with pytest.raises(JobBindingError, match="non-empty string"):
            validator.validate_binding(job_id, "   ", posting)

    def test_invalid_canonical_job_id_type(self) -> None:
        validator = DefaultJobBindingValidator()
        posting = create_sample_posting()

        with pytest.raises(JobBindingError, match="expected uuid.UUID"):
            validator.validate_binding("not-a-uuid", "rev-1", posting)  # type: ignore

    def test_custom_validator_hook(self) -> None:
        def reject_all(cid: uuid.UUID, rev: str, post: NormalizedPosting) -> bool:
            return False

        validator = DefaultJobBindingValidator(custom_validator=reject_all)
        job_id = uuid.uuid4()
        posting = create_sample_posting()

        with pytest.raises(JobBindingError, match="verification failed"):
            validator.validate_binding(job_id, "rev-1", posting)

