"""Tests for IDENTITY-01 contract boundaries and Protocol conformance."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.identity import PostingRevision
from job_automation.contracts.interfaces import (
    ExistingIdentityView,
    IdentityMatchDecision,
    IdentityResolver,
)
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.identity import (
    IdentityError,
    IdentityResolutionResult,
    IdentityService,
    InvalidOperationError,
    MatchOutcome,
    MergeError,
    ReversalError,
)
from job_automation.storage.engine import StorageEngine


def make_sample_normalized(
    provider: str = "arbeitnow",
    board_id: str = "berlin",
    posting_id: str = "101",
    title: str = "Senior Backend Engineer",
    company: str = "Alpha Tech GmbH",
    description: str = "Python and cloud engineering role",
    source_url: str = "https://example.com/jobs/101",
    application_url: str | None = None,
) -> NormalizedPosting:
    return NormalizedPosting(
        source_key=SourceKey(provider=provider, board_id=board_id, source_posting_id=posting_id),
        normalizer_version="1.0-test",
        raw_reference=f"raw/{posting_id}.json",
        raw_content_hash="sha256:" + "0" * 64,
        company_name_hint=company,
        title=title,
        description_clean=description,
        source_url=source_url,
        application_url=application_url,
        observed_at=datetime.now(timezone.utc),
    )


class TestContractBoundary:
    def test_protocol_isinstance_conformance(self, tmp_path: Path) -> None:
        db_path = tmp_path / "protocol_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)
            assert isinstance(service, IdentityResolver)

    def test_resolve_returns_protocol_tuple(self, tmp_path: Path) -> None:
        db_path = tmp_path / "protocol_tuple_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            np = make_sample_normalized()
            existing_view = ExistingIdentityView()
            can_id, rev, decision = service.resolve(np, existing_view)

            assert isinstance(can_id, uuid.UUID)
            assert isinstance(rev, PostingRevision)
            assert isinstance(decision, IdentityMatchDecision)
            assert decision.match_type == MatchOutcome.NEW_CANONICAL.value
            assert decision.confidence == 1.0

    def test_identity_resolution_result_envelope(self, tmp_path: Path) -> None:
        db_path = tmp_path / "envelope_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            np = make_sample_normalized()
            result = service.resolve_and_commit(np)

            assert isinstance(result, IdentityResolutionResult)
            assert result.is_new_canonical is True
            assert result.is_new_revision is True
            assert result.outcome == MatchOutcome.NEW_CANONICAL
            assert result.canonical_job_id == result.revision.canonical_job_id

    def test_error_hierarchy(self) -> None:
        assert issubclass(InvalidOperationError, IdentityError)
        assert issubclass(MergeError, IdentityError)
        assert issubclass(ReversalError, IdentityError)

    def test_integration_with_default_normalizer(self, tmp_path: Path) -> None:
        from job_automation.ingestion.normalization.ports import InMemoryRawProvenanceReader
        from job_automation.ingestion.normalization.service import DefaultNormalizer
        from tests.fakes.normalization_inputs import create_sample_draft

        reader = InMemoryRawProvenanceReader()
        draft = create_sample_draft(reader=reader)
        normalizer = DefaultNormalizer(raw_reader=reader)
        normalized, issues = normalizer.normalize(draft)

        assert normalized is not None
        assert not any(i.severity.value == "error" for i in issues)

        db_path = tmp_path / "normalizer_integration.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)
            result = service.resolve_and_commit(normalized)

            assert result.outcome == MatchOutcome.NEW_CANONICAL
            assert result.is_new_canonical is True
            job = engine.canonical_jobs.get_canonical_job(result.canonical_job_id)
            assert job is not None
            assert job.company_name == "Beispiel GmbH"
            assert result.revision.title == "Sachbearbeiter (m/w/d)"
