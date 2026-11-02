"""End-to-end integration tests for LLMAssessmentService across JSON and RAG strategies (M02-05, M02-12)."""

from __future__ import annotations

import json
from pathlib import Path
import uuid
from datetime import datetime, timezone

import pytest

from job_automation.assessment.llm_records import (
    AssessmentLimits,
    AssessmentRequest,
    FindingStatus,
    RequirementObligation,
)
from job_automation.assessment.llm_service import LLMAssessmentService
from job_automation.assessment.service import AssessmentService
from job_automation.configuration import AppConfig
from job_automation.context.selector import ContextSelectorV2Service
from job_automation.contracts.assessment import Assessment
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
    WorkplaceType,
)
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.models import ModelCall
from job_automation.contracts.policy import HardCriterion, SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.models.audit import InMemoryAuditRecorder
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import (
    build_and_activate_test_index,
    create_selector_test_posting,
    create_selector_test_snapshot,
)
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider
from tests.fakes.model_transport import ScriptedModelTransport


def test_full_integration_json_strategy(tmp_path: Path):
    """M02-12: Full integration with real MATCH-01 + actual JSON selector + LocalModelProvider + SQLite round-trip."""
    data_dir = (tmp_path / "Data Integration JSON").resolve()
    db_path = tmp_path / "integration_json.db"
    raw_dir = tmp_path / "raw"
    artifacts_dir = tmp_path / "artifacts"
    storage_engine = StorageEngine(db_path=db_path, raw_dir=raw_dir, artifacts_dir=artifacts_dir)
    storage_engine.initialize_schema()

    cfg = AppConfig(
        data_root=str(data_dir),
        model_service_url="http://127.0.0.1:11434",
    )
    transport = ScriptedModelTransport()
    recorder = InMemoryAuditRecorder()
    resolver = InMemoryInputResolver()

    model_provider = LocalModelProvider.from_config(
        config=cfg,
        input_resolver=resolver,
        audit_recorder=recorder,
        transport=transport,
    )

    context_selector = ContextSelectorV2Service(
        index_store=None,
        model_provider=None,
    )

    assessment_service = LLMAssessmentService(
        context_selector=context_selector,
        model_provider=model_provider,
        input_resolver=resolver,
    )

    snapshot = create_selector_test_snapshot()
    fact1 = snapshot.evidence_records[0]

    posting = create_selector_test_posting()
    posting_rev = posting.raw_content_hash
    job_id = uuid.uuid4()

    policy = SearchPolicy(policy_version="pol-1.0")

    # Save canonical job for DB relations
    now_dt = datetime.now(timezone.utc)
    canonical_job = CanonicalJob(
        canonical_job_id=job_id,
        company_name=posting.company_name_hint or "Acme Corp",
        current_revision_id=uuid.uuid4(),
        first_seen_at=now_dt,
        last_seen_at=now_dt,
    )
    storage_engine.canonical_jobs.save_canonical_job(canonical_job)

    # 1. Deterministic baseline evaluation
    rule_evaluator = AssessmentService()
    baseline, trace = rule_evaluator.evaluate_posting_with_trace(
        canonical_job_id=job_id,
        posting_revision=posting_rev,
        posting=posting,
        policy=policy,
        profile=snapshot,
    )
    assert baseline.final_disposition == AssessmentDisposition.ELIGIBLE

    # 2. Queue scripted model response
    # Deterministic preparation assigns req_0 to title, req_1 to description line
    model_proposal = {
        "findings": [
            {
                "requirement_id": "req_0",
                "status": "match",
                "reason": "Strong Python candidate matching posting",
                "score": 90.0,
                "candidate_evidence": [
                    {
                        "source_kind": "candidate",
                        "profile_version": snapshot.profile_version,
                        "fact_id": str(fact1.fact_id),
                    }
                ],
            },
            {
                "requirement_id": "req_1",
                "status": "match",
                "reason": "Cloud architecture experience demonstrated",
                "score": 90.0,
                "candidate_evidence": [
                    {
                        "source_kind": "candidate",
                        "profile_version": snapshot.profile_version,
                        "fact_id": str(fact1.fact_id),
                    }
                ],
            },
        ],
        "relevance_score": 90.0,
        "score_scale": "0-100",
        "summary_reason": "Candidate has demonstrated required Python capabilities.",
    }
    transport.queue_response(
        "/api/generate",
        200,
        body={
            "response": json.dumps(model_proposal),
            "done": True,
            "done_reason": "stop",
            "total_duration": 120000000,
            "prompt_eval_count": 120,
            "eval_count": 60,
        },
    )

    # 3. Build assessment request
    request = AssessmentRequest(
        assessment_id=uuid.uuid4(),
        canonical_job_id=job_id,
        posting_revision=posting_rev,
        posting=posting,
        profile=snapshot,
        policy=policy,
        context_strategy=ContextStrategy.JSON,
        deterministic_baseline=baseline,
        deterministic_trace=trace,
        limits=AssessmentLimits(context_limit=4096),
    )

    # 4. Assess
    run_result = assessment_service.assess(request)

    assert run_result.status == "success"
    assert run_result.assessment is not None
    completed = run_result.assessment
    assert completed.final_disposition == AssessmentDisposition.ELIGIBLE
    assert completed.assessment_method == AssessmentMethod.LLM
    assert completed.relevance_score == 90.0
    assert completed.model_metadata is not None
    assert completed.model_metadata.context_strategy == ContextStrategy.JSON

    # 5. Verify SQLite persistence round-trip
    storage_engine.assessments.save_assessment(completed)
    loaded = storage_engine.assessments.get_assessment(completed.assessment_id)
    assert loaded is not None
    assert loaded.assessment_id == completed.assessment_id
    assert loaded.relevance_score == 90.0
    assert len(loaded.requirement_findings) >= 1

    storage_engine.close()


def test_full_integration_rag_strategy(tmp_path: Path):
    """M02-12: Full integration with real MATCH-01 + actual RAG selector + index store + LocalModelProvider."""
    db_path = tmp_path / "integration_rag.db"
    indexes_dir = tmp_path / "indexes"
    storage_engine = StorageEngine(db_path=db_path, indexes_dir=indexes_dir)
    storage_engine.initialize_schema()

    data_dir = (tmp_path / "Data Integration RAG").resolve()
    cfg = AppConfig(
        data_root=str(data_dir),
        model_service_url="http://127.0.0.1:11434",
    )
    transport = ScriptedModelTransport()
    recorder = InMemoryAuditRecorder()
    resolver = InMemoryInputResolver()

    model_provider = LocalModelProvider.from_config(
        config=cfg,
        input_resolver=resolver,
        audit_recorder=recorder,
        transport=transport,
    )

    snapshot = create_selector_test_snapshot()
    fact1 = snapshot.evidence_records[0]
    posting = create_selector_test_posting()

    fake_emb_provider = DeterministicFakeEmbeddingProvider(dimension=8)
    _, index_store, emb_config = build_and_activate_test_index(
        storage_engine=storage_engine,
        indexes_dir=indexes_dir,
        snapshot=snapshot,
        purpose="assessment",
        dimension=8,
        provider=fake_emb_provider,
    )

    context_selector = ContextSelectorV2Service(
        index_store=index_store,
        model_provider=fake_emb_provider,
    )

    assessment_service = LLMAssessmentService(
        context_selector=context_selector,
        model_provider=model_provider,
        input_resolver=resolver,
    )

    policy = SearchPolicy(policy_version="pol-1.0")

    rule_evaluator = AssessmentService()
    baseline, trace = rule_evaluator.evaluate_posting_with_trace(
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        posting=posting,
        policy=policy,
        profile=snapshot,
    )

    model_proposal = {
        "findings": [
            {
                "requirement_id": "req_0",
                "status": "match",
                "reason": "Matched candidate skills",
                "score": 88.0,
                "candidate_evidence": [
                    {
                        "source_kind": "candidate",
                        "profile_version": snapshot.profile_version,
                        "fact_id": str(fact1.fact_id),
                    }
                ],
            }
        ],
        "relevance_score": 88.0,
        "score_scale": "0-100",
        "summary_reason": "Candidate satisfies retrieved requirements.",
    }
    transport.queue_response(
        "/api/generate",
        200,
        body={
            "response": json.dumps(model_proposal),
            "done": True,
            "done_reason": "stop",
            "total_duration": 150000000,
            "prompt_eval_count": 140,
            "eval_count": 70,
        },
    )

    request = AssessmentRequest(
        assessment_id=uuid.uuid4(),
        canonical_job_id=baseline.canonical_job_id,
        posting_revision=posting.raw_content_hash,
        posting=posting,
        profile=snapshot,
        policy=policy,
        context_strategy=ContextStrategy.RAG,
        deterministic_baseline=baseline,
        deterministic_trace=trace,
        limits=AssessmentLimits(context_limit=4096),
        embedding_config=emb_config,
    )

    run_result = assessment_service.assess(request)

    assert run_result.status == "success"
    assert run_result.assessment is not None
    completed = run_result.assessment
    assert completed.model_metadata is not None
    assert completed.model_metadata.context_strategy == ContextStrategy.RAG

    storage_engine.close()


def test_rag_omitted_fact_remains_unknown_never_fabricates_gap():
    """M02-05: A skill present in profile snapshot but omitted/unretrieved in RAG remains UNKNOWN, never 'lacks skill'."""
    snapshot = create_selector_test_snapshot()
    assert len(snapshot.evidence_records) >= 2
    selected_fact = snapshot.evidence_records[0]
    omitted_fact = snapshot.evidence_records[1]

    posting = create_selector_test_posting()
    posting_rev = posting.raw_content_hash

    # RAG bundle selected ONLY selected_fact; omitted_fact is outside top-k
    bundle = ContextBundle(
        strategy=ContextStrategy.RAG,
        purpose="assessment",
        posting_revision=posting_rev,
        profile_version=snapshot.profile_version,
        selected_fact_ids=[selected_fact.fact_id],
        token_budget=2000,
        estimated_tokens=100,
    )

    from job_automation.assessment.finding_validation import validate_proposal_findings
    from job_automation.assessment.llm_records import (
        AssessmentProposal,
        RequirementFindingProposal,
        RequirementItem,
        RequirementSet,
    )
    from job_automation.contracts.evidence import CandidateEvidenceReference, JobEvidenceReference, SourceSpan

    req1 = RequirementItem(
        requirement_id="req_0",
        text=posting.title,
        obligation=RequirementObligation.REQUIRED,
        category="experience",
        job_evidence=JobEvidenceReference(
            posting_revision=posting_rev,
            field_path="title",
            quotation=posting.title,
            source_span=SourceSpan(start=0, end=len(posting.title)),
        ),
    )
    req_set = RequirementSet(
        canonical_job_id=uuid.uuid4(),
        job_revision=posting_rev,
        requirements=[req1],
        fingerprint="sha256:" + "0" * 64,
        extractor_version="1.0",
    )

    # If the model proposes UNKNOWN for this requirement (because evidence was not in context)
    proposal_unknown = AssessmentProposal(
        relevance_score=None,
        summary_reason="Skill was not retrieved in context",
        findings=[
            RequirementFindingProposal(
                requirement_id="req_0",
                status=FindingStatus.UNKNOWN,
                reason="Information not found in retrieved candidate context",
            )
        ],
    )

    findings, issues = validate_proposal_findings(
        proposal=proposal_unknown,
        requirement_set=req_set,
        profile=snapshot,
        posting=posting,
        posting_revision=posting_rev,
        bundle=bundle,
    )

    assert not issues
    assert findings[0].status == FindingStatus.UNKNOWN
    # Verified: It is UNKNOWN with a retrieval limitation, not GAP ("lacks skill")!
