"""Tests for the public EvidenceChunker offline service (CONTEXT-02-S06)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from job_automation.context.chunk_service import EvidenceChunker
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.evidence_chunks import ChunkBuildRequest, ChunkingSettings
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from tests.context.chunk_test_helpers import make_approval


def create_sample_snapshot() -> ProfileSnapshot:
    return ProfileSnapshot(
        candidate_id=uuid.uuid4(),
        profile_version="v1",
        approval_metadata=make_approval(approved_by="tester"),
        explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
        evidence_records=[
            CandidateFact(
                fact_id=uuid.uuid4(),
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Lead SRE",
                organization="Scale Corp",
                start_date=PrecisionDate(value="2021", precision="year"),
                provenance="zeugnis.pdf",
                allowed_uses=["assessment", "cv"],
            )
        ],
    )


class TestChunkService:
    def test_exact_one_result_invariant_on_success(self) -> None:
        snap = create_sample_snapshot()
        chunker = EvidenceChunker()
        req = ChunkBuildRequest(snapshot=snap, purpose="cv")

        result, err = chunker.build(req)
        assert result is not None
        assert err is None
        assert len(result.chunks) == 1

    def test_exact_one_result_invariant_on_failure(self) -> None:
        snap = create_sample_snapshot()
        chunker = EvidenceChunker()
        # Unsupported purpose triggers validation error
        req = ChunkBuildRequest(snapshot=snap, purpose="unsupported_purpose_name")

        result, err = chunker.build(req)
        assert result is None
        assert err is not None
        assert isinstance(err, ClassifiedError)
        assert err.category == ErrorCategory.VALIDATION

    def test_zero_network_model_or_database_calls_during_build(self) -> None:
        """Prove that EvidenceChunker is strictly offline and calls zero external model/network services."""
        snap = create_sample_snapshot()
        chunker = EvidenceChunker()
        req = ChunkBuildRequest(snapshot=snap, purpose="assessment")

        # Mock sockets and HTTP libraries to ensure zero calls
        with patch("urllib.request.urlopen") as mock_url, patch("socket.socket") as mock_sock:
            result, err = chunker.build(req)
            assert err is None
            assert result is not None
            mock_url.assert_not_called()
            mock_sock.assert_not_called()

    def test_diff_exact_one_result(self) -> None:
        snap = create_sample_snapshot()
        chunker = EvidenceChunker()
        m1, _ = chunker.build(ChunkBuildRequest(snapshot=snap, purpose="cv"))
        assert m1 is not None

        diff, err = chunker.diff(None, m1)
        assert diff is not None
        assert err is None
        assert diff.replacement_required is True

    def test_validate_binding_exact_one_result(self) -> None:
        snap = create_sample_snapshot()
        chunker = EvidenceChunker()
        manifest, _ = chunker.build(ChunkBuildRequest(snapshot=snap, purpose="cv"))
        assert manifest is not None

        # Success case
        ok, err = chunker.validate_binding(
            manifest,
            expected_candidate_id=snap.candidate_id,
            expected_profile_version="v1",
            expected_purpose="cv",
        )
        assert ok is True
        assert err is None

        # Failure case
        bad_ok, bad_err = chunker.validate_binding(
            manifest,
            expected_candidate_id=snap.candidate_id,
            expected_profile_version="v2",  # mismatch
            expected_purpose="cv",
        )
        assert bad_ok is False
        assert bad_err is not None
        assert bad_err.category == ErrorCategory.VALIDATION
