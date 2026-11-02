"""Tests for field-level source mapping and traceability verification (CONTEXT-02-S03)."""

from __future__ import annotations

import uuid

import pytest

from job_automation.context.chunk_builder import ChunkBuilder
from job_automation.context.chunk_errors import ChunkValidationError
from job_automation.context.chunk_preparation import ChunkEvidencePreparer
from job_automation.context.chunk_traceability import ChunkTraceabilityValidator
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.evidence import CandidateEvidenceReference
from job_automation.contracts.evidence_chunks import (
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
from tests.context.chunk_test_helpers import make_approval


def create_traceable_snapshot() -> tuple[ProfileSnapshot, uuid.UUID]:
    cid = uuid.uuid4()
    fid = uuid.uuid4()
    fact = CandidateFact(
        fact_id=fid,
        kind=EvidenceFactKind.EMPLOYMENT,
        title="Staff Engineer",
        organization="FinTech GmbH",
        start_date=PrecisionDate(value="2021-01", precision="month"),
        end_date=PrecisionDate(value="2023-06", precision="month"),
        skills=["Kotlin", "Kafka"],
        claims=["Scaled payment processing pipelines to 10k tx/sec"],
        metrics=["99.999% reliability"],
        provenance="zeugnis_2023.pdf",
        allowed_uses=["assessment", "cv"],
    )
    snap = ProfileSnapshot(
        candidate_id=cid,
        profile_version="v1",
        approval_metadata=make_approval(approved_by="tester@example.com"),
        explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
        evidence_records=[fact],
    )
    return snap, fid


class TestChunkTraceability:
    def test_complete_source_mapping_and_verification(self) -> None:
        snap, fid = create_traceable_snapshot()
        preparer = ChunkEvidencePreparer()
        prep_data = preparer.prepare(snap, purpose="cv", settings=ChunkingSettings())

        builder = ChunkBuilder()
        chunk = builder.build_chunk(snap.candidate_id, "v1", "cv", prep_data.prepared_facts[0], ChunkingSettings())

        # Verify all expected field paths are mapped
        mapped_paths = {sm.field_path for sm in chunk.sources}
        assert "title" in mapped_paths
        assert "organization" in mapped_paths
        assert "start_date" in mapped_paths
        assert "end_date" in mapped_paths
        assert "claims[0]" in mapped_paths
        assert "skills[0]" in mapped_paths
        assert "skills[1]" in mapped_paths
        assert "metrics[0]" in mapped_paths
        assert "provenance" in mapped_paths

        # Traceability verification succeeds against original snapshot
        ChunkTraceabilityValidator.verify_chunk_traceability(chunk, snap)

    def test_tampered_mapping_value_fails_traceability_verification(self) -> None:
        snap, fid = create_traceable_snapshot()
        preparer = ChunkEvidencePreparer()
        prep_data = preparer.prepare(snap, purpose="cv", settings=ChunkingSettings())

        builder = ChunkBuilder()
        chunk = builder.build_chunk(snap.candidate_id, "v1", "cv", prep_data.prepared_facts[0], ChunkingSettings())

        # Tamper with a source mapping
        tampered_sources = list(chunk.sources)
        tampered_sources[0] = ChunkSourceMapping(
            reference=tampered_sources[0].reference,
            field_path="title",
            exact_value="FABRICATED_TITLE",
        )
        tampered_chunk = EvidenceChunk.model_validate({
            **chunk.model_dump(mode="python"),
            "sources": [s.model_dump(mode="python") for s in tampered_sources],
        })

        with pytest.raises(ChunkValidationError) as exc_info:
            ChunkTraceabilityValidator.verify_chunk_traceability(tampered_chunk, snap)

        assert "Source mapping value mismatch" in str(exc_info.value)

    def test_cited_fact_not_in_snapshot_fails_verification(self) -> None:
        snap, fid = create_traceable_snapshot()
        preparer = ChunkEvidencePreparer()
        prep_data = preparer.prepare(snap, purpose="cv", settings=ChunkingSettings())

        builder = ChunkBuilder()
        chunk = builder.build_chunk(snap.candidate_id, "v1", "cv", prep_data.prepared_facts[0], ChunkingSettings())

        foreign_fact_id = uuid.uuid4()
        foreign_sources = [
            ChunkSourceMapping(
                reference=CandidateEvidenceReference(profile_version="v1", fact_id=foreign_fact_id),
                field_path="title",
                exact_value="Some Title",
            )
        ]
        tampered_chunk = EvidenceChunk.model_validate({
            **chunk.model_dump(mode="python"),
            "sources": [s.model_dump(mode="python") for s in foreign_sources],
        })

        with pytest.raises(ChunkValidationError) as exc_info:
            ChunkTraceabilityValidator.verify_chunk_traceability(tampered_chunk, snap)

        assert f"Cited fact '{foreign_fact_id}' not found" in str(exc_info.value)
