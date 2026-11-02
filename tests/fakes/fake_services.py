"""Deterministic in-memory fakes for all 10 service interfaces.

Used strictly in tests to verify contract conformance without contacting
real external networks, Salesforce, local Ollama, or SQLite.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.assessment.llm_records import (
    AssessmentRequest,
    AssessmentRunResult,
)
from job_automation.contracts.adapter_results import AdapterPage, Continuation, DraftResult
from job_automation.contracts.artifacts import Artifact, DraftDocument
from job_automation.contracts.assessment import Assessment, RuleOutcome
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
    DocumentApproval,
    FetchOutcome,
    HardCriterionResult,
    PostingAvailability,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory, ValidationIssue
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.contracts.identity import PostingRevision
from job_automation.contracts.interfaces import (
    Adapter,
    Assessor,
    AssessorV2,
    ContextSelector,
    EmbeddingResponse,
    ExistingIdentityView,
    Generator,
    IdentityMatchDecision,
    IdentityResolver,
    ModelProvider,
    Normalizer,
    RendererDelivery,
    RuleEvaluator,
    SalesforceGateway,
)
from job_automation.contracts.models import ModelCall, ModelResult
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import (
    NormalizedPosting,
    RawPosting,
    SourceJobDraft,
)
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.profile import CandidateEligibility, ProfileSnapshot
from job_automation.contracts.sources import SourceConfig
from job_automation.contracts.sync import SyncOperation


class FakeAdapter:
    """Fake source adapter."""

    def __init__(self, raw_postings: list[RawPosting] | None = None) -> None:
        self.raw_postings = raw_postings or []

    def fetch_page(
        self,
        config: SourceConfig,
        continuation: Continuation | None = None,
    ) -> AdapterPage:
        # Return scripted or provided postings
        cont_out = Continuation(
            kind="cursor",
            value="cursor_next",
            source_key=config.source_key,
            scope_id="scope-v1:test",
            adapter_name="fake_adapter",
        ) if self.raw_postings else None
        return AdapterPage(
            items=self.raw_postings,
            continuation_in=continuation,
            continuation_out=cont_out,
            exhausted=cont_out is None,
        )

    def draft_posting(self, raw: RawPosting) -> DraftResult:
        draft = SourceJobDraft(
            raw_reference=raw.raw_payload_ref,
            source_key=raw.source_key,
            fetch_time=raw.fetch_time,
            original_fields={"raw": raw.raw_payload},
            source_mapped_fields={"title": "Draft Title"},
        )
        return DraftResult(raw_reference=raw.raw_payload_ref, draft=draft, issues=[])


class FakeNormalizer:
    """Fake normalizer."""

    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail

    def normalize(
        self,
        draft: SourceJobDraft,
    ) -> tuple[NormalizedPosting | None, list[ValidationIssue]]:
        if self.should_fail:
            return None, [
                ValidationIssue(
                    field_path="title",
                    code="missing_required_field",
                    message="Job title is required",
                )
            ]

        now = datetime.now(timezone.utc)
        np = NormalizedPosting(
            source_key=draft.source_key,
            normalizer_version="1.0-fake",
            raw_reference=draft.raw_reference,
            raw_content_hash="sha256:" + "f" * 64,
            company_name_hint="Acme Corp",
            title="Software Engineer",
            description_clean="Clean job description text",
            source_url="https://example.com/job/1",
            observed_at=now,
        )
        return np, []


class FakeIdentityResolver:
    """Fake identity resolver."""

    def resolve(
        self,
        normalized: NormalizedPosting,
        existing: ExistingIdentityView,
    ) -> tuple[uuid.UUID, PostingRevision, IdentityMatchDecision]:
        can_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        rev = PostingRevision(
            revision_id=uuid.uuid4(),
            canonical_job_id=can_id,
            source_key=normalized.source_key,
            content_hash=normalized.raw_content_hash,
            title=normalized.title,
            first_seen_at=now,
            last_seen_at=now,
            availability=PostingAvailability.ACTIVE,
        )
        decision = IdentityMatchDecision(
            match_type="new_canonical_job",
            matched_canonical_id=can_id,
            confidence=1.0,
            rationale="Registered new canonical job",
        )
        return can_id, rev, decision


class FakeRuleEvaluator:
    """Fake deterministic rule evaluator."""

    def evaluate_rules(
        self,
        revision: PostingRevision,
        policy: SearchPolicy,
        eligibility: CandidateEligibility,
    ) -> Assessment:
        return Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=revision.canonical_job_id,
            posting_revision=revision.content_hash,
            profile_version="v2026.1",
            policy_version=policy.policy_version,
            assessment_method=AssessmentMethod.RULES,
            rule_outcomes=[
                RuleOutcome(
                    criterion_id="crit_1",
                    criterion_name="Work Authorization",
                    result=HardCriterionResult.PASS,
                    reason="Authorized",
                )
            ],
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            summary_reason="Rules evaluation passed",
            final_disposition=AssessmentDisposition.ELIGIBLE,
            model_metadata=None,
        )


class FakeContextSelector:
    """Fake context selector."""

    def __init__(self, budget_overflow: bool = False) -> None:
        self.budget_overflow = budget_overflow

    def select_context(
        self,
        requirements: list[str],
        profile: ProfileSnapshot,
        strategy: ContextStrategy,
        token_budget: int,
    ) -> tuple[ContextBundle | None, ClassifiedError | None]:
        if self.budget_overflow:
            return None, ClassifiedError.from_category(
                ErrorCategory.CONTEXT_BUDGET,
                f"Full JSON context exceeds token budget of {token_budget}",
            )

        bundle = ContextBundle(
            strategy=strategy,
            profile_version=profile.profile_version,
            posting_revision="rev-001",
            ordered_facts=profile.evidence_records,
            selected_fact_ids=[f.fact_id for f in profile.evidence_records],
            token_budget=token_budget,
            estimated_tokens=500,
        )
        return bundle, None


class FakeContextSelectorV2:
    """Fake V2 context selector for testing downstream consumers."""

    def __init__(
        self,
        budget_overflow: bool = False,
        custom_bundle: ContextBundle | None = None,
    ) -> None:
        self.budget_overflow = budget_overflow
        self.custom_bundle = custom_bundle
        self.recorded_requests: list[Any] = []

    def select_context(
        self,
        request: Any,
    ) -> tuple[Any | None, ClassifiedError | None]:
        from job_automation.context.records import RenderedPrompt
        from job_automation.context.selector_records import ContextSelectionResult

        self.recorded_requests.append(request)
        self.last_request = request
        if self.budget_overflow:
            return None, ClassifiedError.from_category(
                ErrorCategory.CONTEXT_BUDGET,
                f"Context exceeds model window {request.context_limit}",
            )

        if self.custom_bundle is not None:
            bundle = self.custom_bundle
        else:
            bundle = ContextBundle(
                strategy=request.strategy,
                profile_version=request.snapshot.profile_version,
                posting_revision=request.posting_revision,
                ordered_facts=request.snapshot.evidence_records,
                selected_fact_ids=[f.fact_id for f in request.snapshot.evidence_records],
                token_budget=request.context_limit - (request.output_reserve + request.safety_allowance),
                estimated_tokens=500,
            )

        prompt = RenderedPrompt(
            full_prompt="System: ... User: ...",
            job_text=request.job_content.description_clean,
            candidate_json="{}",
        )
        result = ContextSelectionResult(
            bundle=bundle,
            rendered_prompt=prompt,
            trace=None,
            construction_fingerprint="sha256:" + "f" * 64,
        )
        return result, None


class FakeModelProvider:
    """Fake local model provider."""

    def __init__(self, simulate_transient_error: bool = False) -> None:
        self.simulate_transient_error = simulate_transient_error

    def generate(self, call: ModelCall) -> ModelResult:
        if self.simulate_transient_error:
            return ModelResult(
                call_id=call.call_id,
                model_identifier=call.model_identifier,
                error=ClassifiedError.from_category(
                    ErrorCategory.TRANSIENT_SERVICE,
                    "Local model service connection refused",
                ),
                latency_ms=10.0,
            )

        return ModelResult(
            call_id=call.call_id,
            model_identifier=call.model_identifier,
            output_text='{"disposition": "eligible", "score": 88}',
            parsed_output={"disposition": "eligible", "score": 88},
            latency_ms=450.0,
        )

    def embed(
        self,
        texts: list[str],
        model: str,
    ) -> tuple[EmbeddingResponse | None, ClassifiedError | None]:
        vectors = [[0.1] * 384 for _ in texts]
        return EmbeddingResponse(
            vectors=vectors,
            model_identifier=model,
            dimension=384,
        ), None


class FakeAssessor:
    """Fake assessor combining rules and context."""

    def assess(
        self,
        rule_outcomes: list[RuleOutcome],
        revision: PostingRevision,
        context: ContextBundle,
    ) -> Assessment:
        return Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=revision.canonical_job_id,
            posting_revision=revision.content_hash,
            profile_version=context.profile_version,
            policy_version="pol-1.0",
            assessment_method=AssessmentMethod.RULES,
            rule_outcomes=rule_outcomes,
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            summary_reason="Combined assessment complete",
            final_disposition=AssessmentDisposition.ELIGIBLE,
        )


class FakeAssessorV2:
    """Fake AssessorV2 for testing consumers of Boundary 7."""

    def __init__(
        self,
        simulated_result: AssessmentRunResult | None = None,
        should_fail: bool = False,
        error_category: ErrorCategory = ErrorCategory.TRANSIENT_SERVICE,
    ) -> None:
        self.simulated_result = simulated_result
        self.should_fail = should_fail
        self.error_category = error_category
        self.last_request: AssessmentRequest | None = None

    def assess(self, request: AssessmentRequest) -> AssessmentRunResult:
        self.last_request = request
        if self.should_fail:
            return AssessmentRunResult(
                status="pending",
                failed_stage="inference",
                error=ClassifiedError.from_category(
                    self.error_category,
                    "Simulated assessor failure",
                ),
                input_fingerprint="sha256:" + "0" * 64,
                deterministic_baseline=request.deterministic_baseline,
                retryable=True,
            )
        if self.simulated_result is not None:
            return self.simulated_result

        # Default simulated success
        c11 = Assessment(
            assessment_id=request.assessment_id,
            canonical_job_id=request.canonical_job_id,
            posting_revision=request.posting_revision,
            profile_version=request.profile.profile_version,
            policy_version="pol-1.0",
            assessment_method=AssessmentMethod.LLM,
            rule_outcomes=list(request.deterministic_baseline.rule_outcomes),
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            relevance_score=85.0,
            score_scale="0-100",
            summary_reason="Fake assessor proposal eligible",
            final_disposition=AssessmentDisposition.ELIGIBLE,
            model_metadata=None,
        )
        return AssessmentRunResult(
            status="success",
            assessment=c11,
            input_fingerprint="sha256:" + "1" * 64,
            audit_references={"simulated": True},
        )


class FakeSalesforceGateway:
    """Fake Salesforce gateway."""

    def __init__(self, return_error: bool = False) -> None:
        self.return_error = return_error
        self.last_operation_id: uuid.UUID | None = None

    def execute_sync(
        self,
        operation: SyncOperation,
    ) -> tuple[str | None, ClassifiedError | None]:
        self.last_operation_id = operation.operation_id
        if self.return_error:
            return None, ClassifiedError.from_category(
                ErrorCategory.AUTHENTICATION,
                "Salesforce OAuth token expired",
            )
        return "a00XXXXXXXXXXXXXXX", None


class FakeGenerator:
    """Fake document generator."""

    def generate_draft(
        self,
        request: GenerationRequest,
        context: ContextBundle,
    ) -> tuple[DraftDocument | None, ClassifiedError | None]:
        draft = DraftDocument(
            request_id=request.request_id,
            document_type=request.document_type,
            document_version="draft-v1",
            title="Generated Document",
            candidate_name="Max Mustermann",
            target_role="Software Engineer",
            target_company="Acme Corp",
            frozen_inputs=request.frozen_input_versions or FrozenInputVersions(
                posting_revision="rev-1",
                profile_version="v1",
                policy_version="p1",
                template_version="t1",
            ),
        )
        return draft, None


class FakeRendererDelivery:
    """Fake renderer and delivery."""

    def render(
        self,
        draft: DraftDocument,
        output_format: str,
        destination_path: str,
    ) -> tuple[Artifact | None, ClassifiedError | None]:
        artifact = Artifact(
            artifact_id=uuid.uuid4(),
            request_id=draft.request_id,
            artifact_version=1,
            format="docx" if output_format == "docx" else "pdf",
            local_path=destination_path,
            content_hash="sha256:" + "0" * 64,
            size_bytes=12345,
            delivery_status="local_only",
            approval_status=DocumentApproval.DRAFT,
            created_at=datetime.now(timezone.utc),
        )
        return artifact, None

    def deliver(
        self,
        artifact: Artifact,
        gateway: SalesforceGateway,
    ) -> tuple[Artifact, ClassifiedError | None]:
        # Simulate delivery acknowledgment
        delivered = artifact.model_copy(
            update={
                "delivery_status": "delivered",
                "remote_file_id": "069XXXXXXXXXXXXXXX",
            }
        )
        return delivered, None
