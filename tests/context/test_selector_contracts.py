"""Tests for CONTEXT-04 selector and retrieval contracts (S01)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from job_automation.context.retrieval_settings import (
    DEFAULT_RETRIEVAL_SETTINGS,
    RetrievalSettings,
)
from job_automation.context.selector_ports import (
    ContextSelectorV2Port,
    QueryBuilderPort,
    RAGContextBuilderPort,
)
from job_automation.context.selector_records import (
    ContextSelectionRequest,
    ContextSelectionResult,
    FusedCandidate,
    RequirementQuery,
    RequirementQuerySet,
    RetrievalHit,
    RetrievalTrace,
)
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import ContextStrategy, EvidenceFactKind
from job_automation.contracts.interfaces import ContextSelector, ContextSelectorV2
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import PrecisionDate, SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.context.records import RenderedPrompt


def _make_snapshot(candidate_id: uuid.UUID) -> ProfileSnapshot:
    return ProfileSnapshot(
        candidate_id=candidate_id,
        profile_version="v1",
        approval_metadata=ProfileApprovalMetadata(
            is_approved=True,
            approved_by="tester@example.com",
            approved_at=datetime.now(timezone.utc),
        ),
        explicit_eligibility=CandidateEligibility(
            work_authorization_countries=["DE"],
            remote_eligible=True,
        ),
        evidence_records=[
            CandidateFact(
                fact_id=uuid.uuid4(),
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Software Engineer",
                organization="Tech GmbH",
                start_date=PrecisionDate(value="2020-01-01", precision="day"),
                claims=["Developed high-performance services"],
                skills=["Python", "C++"],
                provenance="cv_2026.pdf",
                allowed_uses=["assessment", "cv", "cover_letter"],
            )
        ],
    )


def _make_posting() -> NormalizedPosting:
    return NormalizedPosting(
        source_key=SourceKey(provider="test", board_id="board1", source_posting_id="p1"),
        normalizer_version="1.0",
        raw_reference="raw_ref_1",
        raw_content_hash="sha256:" + "a" * 64,
        company_name_hint="Tech AG",
        title="Senior Developer",
        description_clean="Looking for Python and C++ developer.",
        source_url="https://example.com/jobs/1",
        observed_at=datetime.now(timezone.utc),
    )


def test_retrieval_settings_defaults_and_validation() -> None:
    settings = RetrievalSettings()
    assert settings.top_k == 8
    assert settings.per_channel_limit == 20
    assert settings.rrf_k == 60
    assert settings.fusion_method == "rrf"
    assert settings.multi_query_aggregation == "max"

    # top_k can be 0
    zero_top_k = RetrievalSettings(top_k=0)
    assert zero_top_k.top_k == 0

    # top_k cannot exceed per_channel_limit
    with pytest.raises(ValidationError, match="top_k .* cannot exceed per_channel_limit"):
        RetrievalSettings(top_k=25, per_channel_limit=20)


def test_retrieval_settings_fingerprint_determinism() -> None:
    s1 = RetrievalSettings(top_k=5, per_channel_limit=15)
    s2 = RetrievalSettings(top_k=5, per_channel_limit=15)
    s3 = RetrievalSettings(top_k=6, per_channel_limit=15)

    fp1 = s1.compute_settings_fingerprint()
    fp2 = s2.compute_settings_fingerprint()
    fp3 = s3.compute_settings_fingerprint()

    assert fp1 == fp2
    assert fp1 != fp3
    assert len(fp1) == 64


def test_context_selection_request_json_and_rag() -> None:
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()
    snap = _make_snapshot(cand_id)
    posting = _make_posting()

    # JSON selection request
    req_json = ContextSelectionRequest(
        strategy=ContextStrategy.JSON,
        snapshot=snap,
        purpose="assessment",
        canonical_job_id=job_id,
        posting_revision="rev-001",
        job_content=posting,
        model_identifier="test-model",
        context_limit=4096,
    )
    assert req_json.strategy == ContextStrategy.JSON
    assert req_json.retrieval_settings is None

    # Conversion to JsonContextRequest
    json_req = req_json.to_json_context_request()
    assert json_req.snapshot.candidate_id == cand_id
    assert json_req.purpose == "assessment"
    assert json_req.canonical_job_id == job_id
    assert json_req.context_limit == 4096

    # RAG selection request defaults retrieval_settings
    req_rag = ContextSelectionRequest(
        strategy=ContextStrategy.RAG,
        snapshot=snap,
        purpose="assessment",
        canonical_job_id=job_id,
        posting_revision="rev-001",
        job_content=posting,
        model_identifier="test-model",
        context_limit=4096,
    )
    assert req_rag.strategy == ContextStrategy.RAG
    assert req_rag.retrieval_settings is not None
    assert req_rag.retrieval_settings.top_k == 8


def test_retrieval_trace_and_result_envelope() -> None:
    fact_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    hit = RetrievalHit(
        chunk_id=chunk_id,
        fact_id=fact_id,
        channel="keyword",
        score=2.0,
        rank=1,
        query_id="q_0",
    )
    fused = FusedCandidate(
        fact_id=fact_id,
        fused_score=0.01639,
        channel_hits=[hit],
        query_count=1,
        best_channel_rank=1,
        selection_reason="fused_score",
        is_admitted=True,
    )
    trace = RetrievalTrace(
        query_version="v1:hash123",
        index_version="gen_0001",
        channel_statuses={"keyword": "ok", "semantic": "ok"},
        retrieved_hits=[hit],
        fused_candidates=[fused],
        selected_fact_ids=[fact_id],
        retrieved_fact_ids=[fact_id],
        mandatory_fact_ids=[],
        warnings=[],
    )
    assert len(trace.retrieved_hits) == 1
    assert trace.selected_fact_ids == [fact_id]

    bundle = ContextBundle(
        strategy=ContextStrategy.RAG,
        profile_version="v1",
        posting_revision="rev-001",
        token_budget=2000,
        estimated_tokens=500,
        selected_fact_ids=[fact_id],
        retrieval_audit={"trace": trace.model_dump()},
    )
    prompt = RenderedPrompt(
        full_prompt="System: ... User: ...",
        job_text="Job: Senior Dev",
        candidate_json="{}",
    )

    result = ContextSelectionResult(
        bundle=bundle,
        rendered_prompt=prompt,
        trace=trace,
        construction_fingerprint="sha256:" + "0" * 64,
    )
    assert result.bundle.strategy == ContextStrategy.RAG
    assert result.trace is not None
    assert result.bundle.retrieval_audit is not None


def test_protocol_conformance() -> None:
    # Verifies that protocol definitions exist and can be checked
    assert issubclass(ContextSelectorV2Port, object)
    assert issubclass(QueryBuilderPort, object)
    assert issubclass(RAGContextBuilderPort, object)
    assert issubclass(ContextSelectorV2, object)
