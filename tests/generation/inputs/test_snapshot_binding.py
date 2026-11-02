"""Tests for snapshot-aware job binding validation and material vs raw hash handling."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from job_automation.context.errors import JobBindingError
from job_automation.contracts.primitives import SourceKey
from job_automation.generation.input_binding import FrozenJobBindingValidator
from job_automation.identity.hashing import compute_revision_content_hash
from tests.generation.inputs.conftest import make_posting


class TestSnapshotBinding:
    def test_validator_accepts_material_revision_hash(self) -> None:
        c_job_id = uuid.uuid4()
        sk = SourceKey(provider="arbeitnow", board_id="b", source_posting_id="1")
        posting = make_posting(source_key=sk)
        material_hash = compute_revision_content_hash(posting)

        validator = FrozenJobBindingValidator()
        # Must not raise JobBindingError
        validator.validate_binding(
            canonical_job_id=c_job_id,
            posting_revision=material_hash,
            posting=posting,
        )

    def test_validator_accepts_raw_content_hash(self) -> None:
        c_job_id = uuid.uuid4()
        sk = SourceKey(provider="arbeitnow", board_id="b", source_posting_id="1")
        posting = make_posting(source_key=sk)

        validator = FrozenJobBindingValidator()
        validator.validate_binding(
            canonical_job_id=c_job_id,
            posting_revision=posting.raw_content_hash,
            posting=posting,
        )

    def test_validator_rejects_mismatched_hash(self) -> None:
        c_job_id = uuid.uuid4()
        sk = SourceKey(provider="arbeitnow", board_id="b", source_posting_id="1")
        posting = make_posting(source_key=sk)

        validator = FrozenJobBindingValidator()
        with pytest.raises(JobBindingError, match="Job revision content hash mismatch"):
            validator.validate_binding(
                canonical_job_id=c_job_id,
                posting_revision="sha256:" + "9" * 64,
                posting=posting,
            )

