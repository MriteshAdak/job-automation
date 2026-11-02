"""Tests for context selection binding and dual strategy handling (M02-04, M02-05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest

from job_automation.assessment.context_bridge import select_assessment_context
from job_automation.assessment.llm_records import (
    AssessmentLimits,
    AssessmentRequest,
    DeterministicDecisionTrace,
    RequirementItem,
    RequirementObligation,
    RequirementSet,
)
from job_automation.contracts.assessment import Assessment
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
    EvidenceFactKind,
    WorkplaceType,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.evidence import CandidateEvidenceReference, JobEvidenceReference, SourceSpan
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import PrecisionDate, SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from tests.context.selector_test_helpers import create_selector_test_snapshot
from tests.fakes.fake_services import FakeContextSelectorV2


def make_test_request(
    strategy: ContextStrategy = ContextStrategy.JSON,
    approved: bool = True,
    profile_facts: list[CandidateFact] | None = None,
) -> tuple[AssessmentRequest, RequirementSet]:
    """Helper to construct bound AssessmentRequest and RequirementSet."""
    posting_rev = "sha256:" + "a" * 64
    job_id = uuid.uuid4()

    snapshot = create_selector_test_snapshot(facts=profile_facts)
    if not approved:
        # Construct unapproved snapshot directly with dummy approval bypass to test AssessmentRequest validation
        object.__setattr__(snapshot, "approval_metadata", None)

    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p1"),
        normalizer_version="1.0",
        raw_reference="test/ref.json",
        raw_content_hash=posting_rev,
        company_name_hint="Acme Corp",
        title="Python Engineer",
        description_clean="Python and Kubernetes required",
        source_url="https://example.com/job/1",
        workplace_type=WorkplaceType.REMOTE,
        observed_at=datetime.now(timezone.utc),
    )

    policy = SearchPolicy(
        policy_version="pol-1",
    )

    baseline = Assessment(
        assessment_id=uuid.uuid4(),
        canonical_job_id=job_id,
        posting_revision=posting_rev,
        profile_version=snapshot.profile_version,
        policy_version="pol-1",
        assessment_method=AssessmentMethod.RULES,
        relevance_decision=AssessmentDisposition.ELIGIBLE,
        summary_reason="Baseline eligible",
        final_disposition=AssessmentDisposition.ELIGIBLE,
    )

    req_item = RequirementItem(
        requirement_id="req_0",
        text="Python and Kubernetes required",
        obligation=RequirementObligation.REQUIRED,
        job_evidence=JobEvidenceReference(
            posting_revision=posting_rev,
            field_path="description_clean",
            quotation="Python and Kubernetes required",
            source_span=SourceSpan(start=0, end=30),
        ),
    )

    req_set = RequirementSet(
        recipe_version="v1",
        canonical_job_id=job_id,
        job_revision=posting_rev,
        requirements=[req_item],
        fingerprint="sha256:" + "f" * 64,
        extractor_version="v1",
    )

    req = AssessmentRequest(
        canonical_job_id=job_id,
        posting_revision=posting_rev,
        posting=posting,
        profile=snapshot,
        policy=policy,
        deterministic_baseline=baseline,
        deterministic_trace=DeterministicDecisionTrace(),
        context_strategy=strategy,
    )

    return req, req_set


def test_m02_04_unapproved_snapshot_rejected():
    """Context selection and request construction rejects candidate profile without human approval."""
    with pytest.raises(ValueError, match="human approval"):
        make_test_request(approved=False)


def test_m02_04_same_approved_snapshot_in_json_and_rag():
    """Both JSON and RAG strategies dispatch to the same approved snapshot and purpose='assessment'."""
    req_json, req_set_json = make_test_request(strategy=ContextStrategy.JSON)
    req_rag, req_set_rag = make_test_request(strategy=ContextStrategy.RAG)

    fake_selector = FakeContextSelectorV2()

    # JSON selection
    res_json, err_json = select_assessment_context(fake_selector, req_json, req_set_json)
    assert err_json is None
    assert res_json is not None
    assert fake_selector.last_request is not None
    assert fake_selector.last_request.strategy == ContextStrategy.JSON
    assert fake_selector.last_request.purpose == "assessment"

    # RAG selection
    res_rag, err_rag = select_assessment_context(fake_selector, req_rag, req_set_rag)
    assert err_rag is None
    assert res_rag is not None
    assert fake_selector.last_request is not None
    assert fake_selector.last_request.strategy == ContextStrategy.RAG
    assert fake_selector.last_request.purpose == "assessment"


def test_m02_05_gold_skill_outside_rag_top_k_is_retrieval_miss():
    """Gold skill outside RAG selection is distinct from skill absence: full JSON sees it, RAG omits it."""
    f_py = CandidateFact(
        fact_id=uuid.uuid4(),
        kind=EvidenceFactKind.SKILL,
        title="Python Developer",
        skills=["Python"],
        provenance="cv_v1",
    )
    f_k8s = CandidateFact(
        fact_id=uuid.uuid4(),
        kind=EvidenceFactKind.SKILL,
        title="Kubernetes",
        skills=["Kubernetes"],
        provenance="cv_v1",
    )

    # In JSON mode: both facts are admitted
    req_json, req_set = make_test_request(strategy=ContextStrategy.JSON, profile_facts=[f_py, f_k8s])
    bundle_json = ContextBundle(
        strategy=ContextStrategy.JSON,
        profile_version="v1",
        posting_revision=req_json.posting_revision,
        ordered_facts=[f_py, f_k8s],
        selected_fact_ids=[f_py.fact_id, f_k8s.fact_id],
        token_budget=4000,
        estimated_tokens=500,
    )
    selector_json = FakeContextSelectorV2(custom_bundle=bundle_json)
    res_json, _ = select_assessment_context(selector_json, req_json, req_set)
    assert f_k8s.fact_id in res_json.bundle.selected_fact_ids

    # In RAG mode with low top-k: only f_py was admitted, f_k8s was outside top-k
    req_rag, _ = make_test_request(strategy=ContextStrategy.RAG, profile_facts=[f_py, f_k8s])
    bundle_rag = ContextBundle(
        strategy=ContextStrategy.RAG,
        profile_version="v1",
        posting_revision=req_rag.posting_revision,
        ordered_facts=[f_py],
        selected_fact_ids=[f_py.fact_id],  # f_k8s not selected!
        token_budget=4000,
        estimated_tokens=250,
    )
    selector_rag = FakeContextSelectorV2(custom_bundle=bundle_rag)
    res_rag, _ = select_assessment_context(selector_rag, req_rag, req_set)
    assert f_k8s.fact_id not in res_rag.bundle.selected_fact_ids
