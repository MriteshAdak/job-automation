"""Tests for assessment input fingerprint determinism and sensitivity (M02-11)."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone

from job_automation.assessment.llm_inputs import compute_assessment_input_fingerprint
from job_automation.assessment.llm_records import (
    AssessmentLimits,
    AssessmentRequest,
    DeterministicDecisionTrace,
    RequirementItem,
    RequirementObligation,
    RequirementSet,
)
from job_automation.context.retrieval_settings import RetrievalSettings
from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
    WorkplaceType,
)
from job_automation.contracts.evidence import JobEvidenceReference, SourceSpan
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from tests.context.selector_test_helpers import create_selector_test_snapshot


def make_sample_request_and_requirements():
    posting_rev = "sha256:" + "1" * 64
    job_id = uuid.uuid4()
    snapshot = create_selector_test_snapshot()

    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p1"),
        normalizer_version="1.0",
        raw_reference="test/ref.json",
        raw_content_hash=posting_rev,
        company_name_hint="Acme Corp",
        title="Python Engineer",
        description_clean="Python required",
        source_url="https://example.com/job/1",
        workplace_type=WorkplaceType.REMOTE,
        observed_at=datetime.now(timezone.utc),
    )

    policy = SearchPolicy(policy_version="pol-1.0")

    baseline = Assessment(
        assessment_id=uuid.uuid4(),
        canonical_job_id=job_id,
        posting_revision=posting_rev,
        profile_version=snapshot.profile_version,
        policy_version="pol-1.0",
        assessment_method=AssessmentMethod.RULES,
        relevance_decision=AssessmentDisposition.ELIGIBLE,
        summary_reason="Baseline eligible",
        final_disposition=AssessmentDisposition.ELIGIBLE,
    )

    req_item = RequirementItem(
        requirement_id="req_0",
        text="Python required",
        obligation=RequirementObligation.REQUIRED,
        job_evidence=JobEvidenceReference(
            posting_revision=posting_rev,
            field_path="description_clean",
            quotation="Python required",
            source_span=SourceSpan(start=0, end=15),
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
        context_strategy=ContextStrategy.JSON,
    )

    return req, req_set


def test_m02_11_fingerprint_determinism_and_uuid_invariance():
    """Identical inputs produce identical fingerprints; execution UUID changes do not alter input fingerprint."""
    req1, req_set1 = make_sample_request_and_requirements()
    fp1 = compute_assessment_input_fingerprint(req1, req_set1)

    # Compute again with identical data
    req2 = req1.model_copy()
    req_set2 = req_set1.model_copy()
    fp2 = compute_assessment_input_fingerprint(req2, req_set2)
    assert fp1 == fp2

    # Changing execution UUID must NOT change input fingerprint
    req3 = req1.model_copy(update={"assessment_id": uuid.uuid4()})
    fp3 = compute_assessment_input_fingerprint(req3, req_set1)
    assert fp1 == fp3


def test_m02_11_fingerprint_sensitivity_to_material_changes():
    """Changing any output-affecting field produces a different assessment input fingerprint."""
    req, req_set = make_sample_request_and_requirements()
    base_fp = compute_assessment_input_fingerprint(req, req_set)

    # 1. Change policy version
    req_policy = req.model_copy(update={"policy": SearchPolicy(policy_version="pol-2.0")})
    assert compute_assessment_input_fingerprint(req_policy, req_set) != base_fp

    # 2. Change context strategy
    req_strat = req.model_copy(update={"context_strategy": ContextStrategy.RAG})
    assert compute_assessment_input_fingerprint(req_strat, req_set) != base_fp

    # 3. Change model identifier
    req_model = req.model_copy(update={"model_identifier": "llama3:70b"})
    assert compute_assessment_input_fingerprint(req_model, req_set) != base_fp

    # 4. Change prompt version
    req_prompt = req.model_copy(update={"prompt_version": "v2"})
    assert compute_assessment_input_fingerprint(req_prompt, req_set) != base_fp

    # 5. Change context limit
    req_limit = req.model_copy(update={"limits": AssessmentLimits(context_limit=4096)})
    assert compute_assessment_input_fingerprint(req_limit, req_set) != base_fp

    # 6. Change requirements fingerprint
    req_set_alt = req_set.model_copy(update={"fingerprint": "sha256:" + "e" * 64})
    assert compute_assessment_input_fingerprint(req, req_set_alt) != base_fp

    # 7. Change retrieval settings in RAG mode
    req_rag = req.model_copy(
        update={
            "context_strategy": ContextStrategy.RAG,
            "retrieval_settings": RetrievalSettings(top_k=5),
        }
    )
    fp_rag_5 = compute_assessment_input_fingerprint(req_rag, req_set)
    req_rag_10 = req.model_copy(
        update={
            "context_strategy": ContextStrategy.RAG,
            "retrieval_settings": RetrievalSettings(top_k=10),
        }
    )
    fp_rag_10 = compute_assessment_input_fingerprint(req_rag_10, req_set)
    assert fp_rag_5 != fp_rag_10
