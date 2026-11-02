"""Tests for CONTEXT-02 evidence chunk contracts, schemas, and immutability."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from datetime import datetime, timezone

from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.evidence import CandidateEvidenceReference, SourceSpan
from job_automation.contracts.evidence_chunks import (
    AncestorContext,
    BindingTransition,
    ChunkBuildRequest,
    ChunkChangeSet,
    ChunkSet,
    ChunkSourceMapping,
    ChunkingSettings,
    EvidenceChunk,
)
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)


def create_minimal_snapshot(cid: uuid.UUID | None = None) -> ProfileSnapshot:
    cand_id = cid or uuid.uuid4()
    return ProfileSnapshot(
        candidate_id=cand_id,
        profile_version="v1",
        approval_metadata=ProfileApprovalMetadata(
            is_approved=True,
            approved_by="reviewer@example.com",
            approved_at=datetime.now(timezone.utc),
            notes="Approved synthetic snapshot",
        ),
        explicit_eligibility=CandidateEligibility(
            work_authorization_countries=["DE"],
            target_locations=["Berlin"],
            remote_eligible=True,
        ),
        evidence_records=[],
    )


class TestChunkContracts:
    def test_chunking_settings_defaults_and_immutability(self) -> None:
        settings = ChunkingSettings()
        assert settings.granularity == "whole_fact"
        assert settings.algorithm_version == "v1"
        assert settings.max_chunk_chars is None
        assert settings.strict_parents is False
        assert settings.size_unit == "chars"
        assert settings.overflow_behavior == "error"

        # Immutability check
        with pytest.raises(ValidationError):
            settings.granularity = "split_claims"  # type: ignore

    def test_chunking_settings_rejects_unsupported_granularity(self) -> None:
        with pytest.raises(ValidationError):
            ChunkingSettings(granularity="sub_sentence")  # type: ignore

    def test_chunking_settings_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ChunkingSettings(vector_dimensions=1536)  # type: ignore

    def test_ancestor_context_validation(self) -> None:
        fid = uuid.uuid4()
        anc = AncestorContext(
            fact_id=fid,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Senior Architect",
            organization="Cloud GmbH",
            start_date=PrecisionDate(value="2020-01", precision="month"),
            end_date=PrecisionDate(value="2023-01", precision="month"),
            provenance="work_certificate.pdf",
            allowed_uses=["assessment", "cv"],
        )
        assert anc.fact_id == fid
        assert anc.organization == "Cloud GmbH"

        # Extra fields forbidden
        with pytest.raises(ValidationError):
            AncestorContext(
                fact_id=fid,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Arch",
                extra_data="invalid",  # type: ignore
            )

    def test_chunk_source_mapping_validation(self) -> None:
        ref = CandidateEvidenceReference(profile_version="v1", fact_id=uuid.uuid4())
        mapping = ChunkSourceMapping(
            reference=ref,
            field_path="claims[0]",
            list_index=0,
            exact_value="Migrated core databases",
            is_ancestor_context=False,
        )
        assert mapping.reference.profile_version == "v1"
        assert mapping.exact_value == "Migrated core databases"

        # Extra fields forbidden
        with pytest.raises(ValidationError):
            ChunkSourceMapping(
                reference=ref,
                field_path="title",
                unsupported_extra=True,  # type: ignore
            )

    def test_evidence_chunk_round_trip(self) -> None:
        cid = uuid.uuid4()
        fid = uuid.uuid4()
        chunk_id = uuid.uuid4()
        ref = CandidateEvidenceReference(profile_version="v1", fact_id=fid)

        chunk = EvidenceChunk(
            chunk_id=chunk_id,
            chunk_version="hash123",
            candidate_id=cid,
            profile_version="v1",
            purpose="assessment",
            primary_fact_id=fid,
            primary_kind=EvidenceFactKind.PROJECT,
            title="Database Redesign",
            organization="Tech AG",
            start_date=PrecisionDate(value="2022", precision="year"),
            skills=["PostgreSQL", "Python"],
            claims=["Improved query latency by 50%"],
            metrics=["p99 < 10ms"],
            provenance="report.pdf",
            primary_allowed_uses=["assessment", "cv"],
            effective_allowed_uses=["assessment"],
            sources=[
                ChunkSourceMapping(
                    reference=ref,
                    field_path="title",
                    exact_value="Database Redesign",
                )
            ],
            retrieval_text="[Evidence]\nKind: project\nTitle: Database Redesign",
            binding_fingerprint="bind_hash_456",
        )

        dumped = chunk.model_dump(mode="json")
        reloaded = EvidenceChunk.model_validate(dumped)
        assert reloaded == chunk

    def test_chunk_set_manifest_consistency(self) -> None:
        cid = uuid.uuid4()
        fid = uuid.uuid4()
        chunk_id = uuid.uuid4()

        chunk = EvidenceChunk(
            chunk_id=chunk_id,
            chunk_version="cv_abc",
            candidate_id=cid,
            profile_version="v1",
            purpose="cv",
            primary_fact_id=fid,
            primary_kind=EvidenceFactKind.EMPLOYMENT,
            title="Lead Developer",
            provenance="cert.pdf",
            primary_allowed_uses=["cv"],
            effective_allowed_uses=["cv"],
            retrieval_text="Lead Developer at Tech",
            binding_fingerprint="bind_xyz",
        )

        # Valid manifest with exact coverage
        cset = ChunkSet(
            candidate_id=cid,
            profile_version="v1",
            purpose="cv",
            snapshot_fingerprint="snap_123",
            settings_fingerprint="set_456",
            chunks=[chunk],
            eligible_fact_ids=[fid],
            coverage_fact_ids=[fid],
            manifest_fingerprint="man_789",
        )
        assert len(cset.chunks) == 1

        # Inconsistent coverage fails validation
        with pytest.raises(ValidationError):
            ChunkSet(
                candidate_id=cid,
                profile_version="v1",
                purpose="cv",
                snapshot_fingerprint="snap_123",
                settings_fingerprint="set_456",
                chunks=[chunk],
                eligible_fact_ids=[fid, uuid.uuid4()],  # missing coverage
                coverage_fact_ids=[fid],
                manifest_fingerprint="man_789",
            )

    def test_chunk_change_set_validation(self) -> None:
        cid = uuid.uuid4()
        ch_id = uuid.uuid4()
        trans = BindingTransition(
            chunk_id=ch_id,
            old_binding=None,
            new_binding="new_bind_123",
            reason_code="added",
        )
        change_set = ChunkChangeSet(
            candidate_id=cid,
            purpose="assessment",
            base_manifest_fingerprint=None,
            target_manifest_fingerprint="target_man_123",
            added_chunk_ids=[ch_id],
            binding_transitions=[trans],
            reasons=["initial_build"],
            replacement_required=True,
        )
        assert change_set.replacement_required is True
        assert len(change_set.added_chunk_ids) == 1

    def test_chunk_build_request_validation(self) -> None:
        snap = create_minimal_snapshot()
        req = ChunkBuildRequest(
            snapshot=snap,
            purpose="assessment",
        )
        assert req.purpose == "assessment"
        assert req.settings.granularity == "whole_fact"
