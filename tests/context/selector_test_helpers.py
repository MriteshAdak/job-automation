"""Test helpers for CONTEXT-04 selector and RAG retrieval tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.context.index_builder import IndexBuilder
from job_automation.context.index_reader import IndexStore
from job_automation.context.retrieval_settings import (
    DEFAULT_RETRIEVAL_SETTINGS,
    RetrievalSettings,
)
from job_automation.context.selector_records import ContextSelectionRequest
from job_automation.contracts.enums import ContextStrategy, EvidenceFactKind
from job_automation.contracts.evidence_chunks import ChunkBuildRequest
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import PrecisionDate, SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.contracts.retrieval_index import (
    EmbeddingConfiguration,
    IndexBuildRequest,
    IndexBuildResult,
    IndexSettings,
)
from job_automation.storage.engine import StorageEngine
from tests.context.index_test_helpers import (
    create_test_embedding_config,
    create_test_index_settings,
)
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def create_selector_test_snapshot(
    candidate_id: uuid.UUID | None = None,
    profile_version: str = "v1",
    facts: list[CandidateFact] | None = None,
    work_countries: list[str] | None = None,
    locations: list[str] | None = None,
) -> ProfileSnapshot:
    """Create approved profile snapshot with standard or customized evidence facts."""
    cand_id = candidate_id or uuid.uuid4()
    if facts is None:
        f1_id = uuid.uuid4()
        f2_id = uuid.uuid4()
        f3_id = uuid.uuid4()
        facts = [
            CandidateFact(
                fact_id=f1_id,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Lead Software Engineer",
                organization="Tech AG München",
                start_date=PrecisionDate(value="2019-03-01", precision="day"),
                end_date=PrecisionDate(value="2022-09-30", precision="day"),
                skills=["C++", "C#", ".NET", "Python"],
                claims=["Engineered low-latency matching engine in München"],
                metrics=["Achieved 500k ops/sec"],
                provenance="cv_2026.pdf",
                allowed_uses=["assessment", "cv", "cover_letter"],
            ),
            CandidateFact(
                fact_id=f2_id,
                parent_id=f1_id,
                kind=EvidenceFactKind.PROJECT,
                title="Algorithmic Trading Platform",
                start_date=PrecisionDate(value="2020-01-01", precision="day"),
                skills=["C++", "Kubernetes", "Linux"],
                claims=["Implemented sub-millisecond market data feed parser"],
                provenance="cv_2026.pdf",
                allowed_uses=["assessment", "cv", "cover_letter"],
            ),
            CandidateFact(
                fact_id=f3_id,
                kind=EvidenceFactKind.EDUCATION,
                title="M.Sc. Computer Science",
                organization="TU München",
                start_date=PrecisionDate(value="2016-10-01", precision="day"),
                end_date=PrecisionDate(value="2018-09-30", precision="day"),
                skills=["Algorithms", "Distributed Systems"],
                claims=["Graduated with distinction"],
                provenance="diploma.pdf",
                allowed_uses=["assessment", "cv", "cover_letter"],
            ),
        ]

    return ProfileSnapshot(
        candidate_id=cand_id,
        profile_version=profile_version,
        approval_metadata=ProfileApprovalMetadata(
            is_approved=True,
            approved_by="candidate@example.com",
            approved_at=datetime.now(timezone.utc),
            notes="Approved candidate profile",
        ),
        explicit_eligibility=CandidateEligibility(
            work_authorization_countries=work_countries or ["DE", "AT"],
            target_locations=locations or ["München", "Berlin"],
            remote_eligible=True,
        ),
        evidence_records=facts,
    )


def create_selector_test_posting(
    title: str = "Senior C++ Backend Developer",
    description: str = "We are seeking a senior C++ and .NET software engineer in München.",
    requirements: list[str] | None = None,
) -> NormalizedPosting:
    """Create normalized job posting with valid source key."""
    return NormalizedPosting(
        source_key=SourceKey(provider="test", board_id="board1", source_posting_id=str(uuid.uuid4())[:8]),
        normalizer_version="1.0",
        raw_reference="test_raw_ref",
        raw_content_hash="sha256:" + "d" * 64,
        company_name_hint="Fintech Innovations GmbH",
        title=title,
        description_clean=description,
        source_url="https://example.com/jobs/123",
        observed_at=datetime.now(timezone.utc),
    )


def build_and_activate_test_index(
    storage_engine: StorageEngine,
    indexes_dir: Path,
    snapshot: ProfileSnapshot,
    purpose: str = "assessment",
    dimension: int = 8,
    provider: DeterministicFakeEmbeddingProvider | None = None,
) -> tuple[IndexBuildResult, IndexStore, EmbeddingConfiguration]:
    """Helper to build chunks, construct vector/keyword index, and activate generation."""
    from job_automation.context.chunk_service import EvidenceChunker

    # 1. Build chunks
    chunker = EvidenceChunker()
    chunk_res, chunk_err = chunker.build(ChunkBuildRequest(snapshot=snapshot, purpose=purpose))
    if chunk_err is not None or chunk_res is None:
        raise RuntimeError(f"Chunk building failed: {chunk_err}")

    # 2. Setup provider and configs
    embed_provider = provider or DeterministicFakeEmbeddingProvider(dimension=dimension)
    emb_config = create_test_embedding_config(dimension=dimension)
    settings = create_test_index_settings(dimension=dimension)

    # 3. Build index
    builder = IndexBuilder(
        indexes_dir=indexes_dir,
        provider=embed_provider,
        repository=storage_engine.context_indexes,
    )
    build_req = IndexBuildRequest(
        candidate_id=snapshot.candidate_id,
        profile_version=snapshot.profile_version,
        purpose=purpose,
        chunk_set=chunk_res,
        embedding_config=emb_config,
        settings=settings,
    )
    result, err = builder.build(build_req)
    if err is not None or result is None:
        raise RuntimeError(f"Index build failed: {err}")

    # 4. Activate generation in SQLite repository
    storage_engine.context_indexes.set_active_generation(
        candidate_id=snapshot.candidate_id,
        purpose=purpose,
        generation_id=result.generation_id,
        profile_version=snapshot.profile_version,
        activation_token=result.activation_token,
    )

    store = IndexStore(
        indexes_dir=indexes_dir,
        repository=storage_engine.context_indexes,
    )
    return result, store, emb_config
