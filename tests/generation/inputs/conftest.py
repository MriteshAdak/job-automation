"""Common fixtures and helpers for GEN-02 input service and context tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pytest

from job_automation.context.chunk_service import EvidenceChunker
from job_automation.context.index_builder import IndexBuilder
from job_automation.contracts.enums import (
    ContextStrategy,
    DocumentType,
    EvidenceFactKind,
    GenerationProcessing,
    PostingAvailability,
)
from job_automation.contracts.evidence_chunks import ChunkBuildRequest
from job_automation.contracts.generation import GenerationRequest
from job_automation.contracts.identity import CanonicalJob, PostingRevision
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
    IndexSettings,
)
from job_automation.generation.input_records import GenerationInputSettings
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.identity.hashing import compute_revision_content_hash
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def engine(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "test_gen02.db"
    raw_dir = tmp_path / "raw"
    art_dir = tmp_path / "artifacts"
    prof_dir = tmp_path / "profiles"
    idx_dir = tmp_path / "indexes"

    eng = StorageEngine(
        db_path=db_path,
        raw_dir=raw_dir,
        artifacts_dir=art_dir,
        profiles_dir=prof_dir,
        indexes_dir=idx_dir,
    )
    eng.initialize_schema()
    return eng


def make_posting(
    source_key: SourceKey,
    title: str = "Senior Python Engineer",
    company_name: str = "Acme Corp",
    description: str = "We are seeking a senior Python developer with PostgreSQL and Docker experience in Berlin.",
    observed_at: datetime | None = None,
) -> NormalizedPosting:
    now_utc = observed_at or datetime.now(timezone.utc)
    return NormalizedPosting(
        source_key=source_key,
        normalizer_version="v1.0",
        raw_reference="test_ref_001",
        raw_content_hash="sha256:" + "a" * 64,
        title=title,
        company_name_hint=company_name,
        observed_at=now_utc,
        description_clean=description,
        source_url="https://example.com/job/123",
        application_url="https://example.com/apply/123",
    )


def create_job_with_posting(
    engine: StorageEngine,
    job_id: uuid.UUID | None = None,
    availability: PostingAvailability = PostingAvailability.ACTIVE,
    title: str = "Senior Python Engineer",
    company_name: str = "Acme Corp",
    description: str = "Requirements:\n- 5+ years Python\n- Docker & Kubernetes\n- Fluent English & German",
) -> tuple[CanonicalJob, PostingRevision, NormalizedPosting]:
    c_job_id = job_id or uuid.uuid4()
    now_utc = datetime.now(timezone.utc)
    rev_id = uuid.uuid4()
    sk = SourceKey(provider="arbeitnow", board_id="default", source_posting_id=f"job-{c_job_id}")

    posting = make_posting(
        source_key=sk,
        title=title,
        company_name=company_name,
        description=description,
        observed_at=now_utc,
    )
    engine.canonical_jobs.save_normalized_posting(posting)

    material_hash = compute_revision_content_hash(posting)
    rev = PostingRevision(
        revision_id=rev_id,
        canonical_job_id=c_job_id,
        source_key=sk,
        content_hash=material_hash,
        title=title,
        availability=availability,
        first_seen_at=now_utc,
        last_seen_at=now_utc,
    )
    job = CanonicalJob(
        canonical_job_id=c_job_id,
        company_name=company_name,
        availability=availability,
        current_revision_id=rev_id,
        revisions=[rev],
        linked_source_keys=[sk],
        first_seen_at=now_utc,
        last_seen_at=now_utc,
    )
    engine.canonical_jobs.save_canonical_job(job)

    return job, rev, posting


def publish_approved_profile(
    engine: StorageEngine,
    candidate_id: uuid.UUID | None = None,
    profile_version: str = "v1",
    facts: list[CandidateFact] | None = None,
    is_current: bool = True,
    approved_by: str = "candidate",
    approved_at: datetime | None = None,
) -> ProfileSnapshot:
    cand_id = candidate_id or uuid.uuid4()
    now_utc = approved_at or datetime.now(timezone.utc)

    if facts is None:
        f1 = uuid.uuid4()
        f2 = uuid.uuid4()
        facts = [
            CandidateFact(
                fact_id=f1,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Lead Software Engineer",
                organization="Tech GmbH",
                start_date=PrecisionDate(value="2021-03", precision="month"),
                skills=["Python", "Docker", "PostgreSQL"],
                claims=["Built scalable web services in Berlin with 99.9% uptime"],
                metrics=["Scaled system to 500k monthly active users"],
                provenance="cv_master.pdf",
                allowed_uses=["assessment", "cv", "cover_letter"],
            ),
            CandidateFact(
                fact_id=f2,
                kind=EvidenceFactKind.SKILL,
                parent_id=f1,
                title="Kubernetes & CI/CD",
                skills=["Kubernetes", "Helm", "GitLab CI"],
                claims=["Designed multi-cluster deployment pipeline"],
                provenance="cv_master.pdf",
                allowed_uses=["assessment", "cv", "cover_letter"],
            ),
        ]

    snapshot = ProfileSnapshot(
        candidate_id=cand_id,
        profile_version=profile_version,
        approval_metadata=ProfileApprovalMetadata(
            is_approved=True,
            approved_by=approved_by,
            approved_at=now_utc,
        ),
        explicit_eligibility=CandidateEligibility(
            work_authorization_countries=["DE"],
            target_locations=["Berlin"],
            remote_eligible=True,
        ),
        evidence_records=facts,
    )

    engine.profiles.publish_snapshot(
        snapshot=snapshot,
        version_sequence=1 if profile_version == "v1" else 2,
        predecessor_version=None if profile_version == "v1" else "v1",
        content_hash="sha256:" + "b" * 64,
        approved_by=approved_by,
        approved_at=now_utc,
        is_current=is_current,
    )

    return snapshot


def build_and_activate_test_rag_index(
    engine: StorageEngine,
    snapshot: ProfileSnapshot,
    purpose: str = "cv",
    dimension: int = 8,
) -> uuid.UUID:
    """Build, persist, and activate a real test RAG index for candidate and purpose."""
    from tests.context.index_test_helpers import create_test_build_request
    from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider

    chunker = EvidenceChunker()
    chunk_req = ChunkBuildRequest(snapshot=snapshot, purpose=purpose)
    chunk_set, c_err = chunker.build(chunk_req)
    assert c_err is None and chunk_set is not None

    embedder = DeterministicFakeEmbeddingProvider(dimension=dimension)
    builder = IndexBuilder(engine.indexes_dir, embedder, engine.context_indexes)
    build_req = create_test_build_request(chunk_set=chunk_set, purpose=purpose)
    result, b_err = builder.build(build_req)
    assert b_err is None and result is not None

    engine.context_indexes.set_active_generation(
        candidate_id=snapshot.candidate_id,
        purpose=purpose,
        generation_id=result.generation_id,
        profile_version=snapshot.profile_version,
        activation_token=f"token-{result.generation_id}",
    )

    return result.generation_id


def make_request(
    job_id: uuid.UUID,
    req_id: uuid.UUID | None = None,
    doc_type: DocumentType = DocumentType.CV,
    strategy: ContextStrategy = ContextStrategy.JSON,
    allow_unavailable: bool = False,
    template_id: str = "tmpl-1",
    lang: str = "de",
    sf_id: str | None = "a00111111111111AAA",
) -> GenerationRequest:
    r_id = req_id or uuid.uuid4()
    now_utc = datetime.now(timezone.utc)
    return GenerationRequest(
        request_id=r_id,
        salesforce_request_id=sf_id,
        canonical_job_id=job_id,
        document_type=doc_type,
        target_language=lang,
        template_id=template_id,
        context_strategy=strategy,
        allow_unavailable_job=allow_unavailable,
        state=GenerationProcessing.PENDING,
        created_at=now_utc,
    )

