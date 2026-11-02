"""Shared test helper functions for CONTEXT-03 indexing tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.context.chunk_builder import ChunkBuilder
from job_automation.context.chunk_preparation import ChunkEvidencePreparer
from job_automation.context.chunk_settings import DEFAULT_CHUNKING_SETTINGS
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.evidence_chunks import (
    ChunkBuildRequest,
    ChunkSet,
)
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.contracts.retrieval_index import (
    EmbeddingConfiguration,
    IndexBuildRequest,
    IndexSettings,
)


def make_test_approval() -> ProfileApprovalMetadata:
    return ProfileApprovalMetadata(
        is_approved=True,
        approved_by="tester@example.com",
        approved_at=datetime.now(timezone.utc),
        notes="Approved test snapshot",
    )


def create_test_profile_snapshot(
    candidate_id: uuid.UUID | None = None,
    profile_version: str = "v1",
    facts: list[CandidateFact] | None = None,
) -> ProfileSnapshot:
    cand_id = candidate_id or uuid.uuid4()
    if facts is None:
        fact1_id = uuid.uuid4()
        fact2_id = uuid.uuid4()
        facts = [
            CandidateFact(
                fact_id=fact1_id,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Senior C++ Software Engineer",
                organization="Tech GmbH",
                start_date=PrecisionDate(value="2020-01-01", precision="day"),
                skills=["C++", "C#", ".NET", "Docker"],
                claims=["Designed high-performance trading engine in München"],
                metrics=["Processed 1M ops/sec with <1ms latency"],
                provenance="cv_2026.pdf",
                allowed_uses=["assessment", "cv", "cover_letter"],
            ),
            CandidateFact(
                fact_id=fact2_id,
                kind=EvidenceFactKind.SKILL,
                parent_id=fact1_id,
                title="Distributed Systems and CI/CD",
                skills=["Kubernetes", "CI/CD", "Python"],
                claims=["Automated zero-downtime deployment pipelines"],
                provenance="cv_2026.pdf",
                allowed_uses=["assessment", "cv", "cover_letter"],
            ),
        ]

    return ProfileSnapshot(
        candidate_id=cand_id,
        profile_version=profile_version,
        approval_metadata=make_test_approval(),
        explicit_eligibility=CandidateEligibility(
            work_authorization_countries=["DE"],
            target_locations=["Berlin", "München"],
            remote_eligible=True,
        ),
        evidence_records=facts,
    )


def create_test_chunk_set(
    snapshot: ProfileSnapshot | None = None,
    purpose: str = "assessment",
) -> ChunkSet:
    snap = snapshot or create_test_profile_snapshot()
    from job_automation.context.chunk_service import EvidenceChunker

    chunker = EvidenceChunker()
    req = ChunkBuildRequest(snapshot=snap, purpose=purpose)
    res, err = chunker.build(req)
    if err is not None or res is None:
        raise RuntimeError(f"Failed to build test chunk set: {err}")
    return res


def create_test_embedding_config(
    dimension: int = 8,
    model_identifier: str = "fake-embedder",
    model_digest: str | None = "fake-digest-v1",
) -> EmbeddingConfiguration:
    return EmbeddingConfiguration(
        schema_version="1.0",
        configuration_version="v1",
        model_identifier=model_identifier,
        dimension=dimension,
        model_digest=model_digest,
        expected_digest=model_digest,
        verification_provenance="synthetic_fake",
        runtime_version="1.0",
        provider_version="1.0",
        document_prefix="",
        query_prefix="",
        max_batch_items=16,
        max_batch_bytes=65536,
    )


def create_test_index_settings(
    dimension: int = 64,
    max_chunks: int = 100,
) -> IndexSettings:
    return IndexSettings(
        schema_version="1.0",
        index_version="v1",
        algorithm_version="v1",
        format_version="v1",
        canonicalization_version="v1",
        dtype="float32",
        byte_order="little_endian",
        metric="cosine",
        normalization="l2",
        analyzer_version="v1",
        max_chunks=max_chunks,
        max_dimension=dimension,
        max_text_bytes=65536,
        max_build_memory_bytes=104857600,
        max_disk_bytes=1048576000,
        max_build_time_seconds=30.0,
        cleanup_retained_generations=2,
    )


def create_test_build_request(
    chunk_set: ChunkSet | None = None,
    dimension: int = 8,
    purpose: str = "assessment",
) -> IndexBuildRequest:
    cs = chunk_set or create_test_chunk_set(purpose=purpose)
    emb_config = create_test_embedding_config(dimension=dimension)
    settings = create_test_index_settings(dimension=max(dimension, 64))

    return IndexBuildRequest(
        candidate_id=cs.candidate_id,
        profile_version=cs.profile_version,
        purpose=purpose,
        chunk_set=cs,
        embedding_config=emb_config,
        settings=settings,
    )
