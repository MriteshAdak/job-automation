"""Service-independent interface boundaries (Protocols).

Defines stable Python Protocols for all 10 component boundaries (Blueprint §4):
1. Adapter
2. Normalizer
3. IdentityResolver
4. RuleEvaluator
5. ContextSelector
6. ModelProvider
7. Assessor
8. SalesforceGateway
9. Generator
10. RendererDelivery

Keeps callers dependent strictly on typed contracts, not concrete databases,
HTTP clients, or model runtimes.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from job_automation.assessment.llm_records import (
        AssessmentRequest,
        AssessmentRunResult,
    )
    from job_automation.context.selector_records import (
        ContextSelectionRequest,
        ContextSelectionResult,
    )

from job_automation.contracts.adapter_results import (
    AdapterPage,
    Continuation,
    DraftResult,
    RecordIssue,
)
from job_automation.contracts.artifacts import Artifact, DraftDocument
from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.contracts.assessment import Assessment, RuleOutcome
from job_automation.contracts.base import ContractModel
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import (
    ContextStrategy,
    FetchOutcome,
)
from job_automation.contracts.errors import ClassifiedError, ValidationIssue
from job_automation.contracts.generation import GenerationRequest
from job_automation.contracts.identity import PostingRevision
from job_automation.contracts.models import ModelCall, ModelResult, TokenUsage
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
from job_automation.contracts.salesforce import (
    ConnectionCheckRequest,
    ConnectionCheckResult,
    DescribeObjectRequest,
    DescribeObjectResult,
    GatewayResult,
    GetRecordRequest,
    GetRecordResult,
    LimitsRequest,
    LimitsResult,
    QueryPageRequest,
    QueryPageResult,
    UpdateRequest,
    UpdateResult,
    UpsertRequest,
    UpsertResult,
)


# ===================================================================
# Auxiliary data types for interface boundaries
# ===================================================================


class IdentityMatchDecision(ContractModel):
    """Decision produced by the IdentityResolver."""

    match_type: str = "new_canonical_job"  # new_canonical_job, exact_source_match, duplicate_candidate
    matched_canonical_id: uuid.UUID | None = None
    confidence: float = 1.0
    rationale: str = "New source posting registered"


class ExistingIdentityView(ContractModel):
    """Read-only lookup view for identity resolution."""

    source_key_to_canonical: dict[str, uuid.UUID] = {}
    known_companies: dict[str, uuid.UUID] = {}


class EmbeddingResponse(ContractModel):
    """Vectors and metadata returned from text embedding."""

    vectors: list[list[float]]
    model_identifier: str
    dimension: int
    call_id: uuid.UUID | None = None
    model_digest: str | None = None
    token_usage: TokenUsage | None = None


# ===================================================================
# 10 Service Protocols
# ===================================================================


@runtime_checkable
class Adapter(Protocol):
    """Boundary 1: Source acquisition and raw drafting."""

    def fetch_page(
        self,
        config: SourceConfig,
        continuation: Continuation | None = None,
    ) -> AdapterPage:
        """Fetch a page of raw postings from the source."""
        ...

    def draft_posting(self, raw: RawPosting) -> DraftResult:
        """Parse raw posting structure into a DraftResult."""
        ...


@runtime_checkable
class Normalizer(Protocol):
    """Boundary 2: Common normalization and structural validation."""

    def normalize(
        self,
        draft: SourceJobDraft,
    ) -> tuple[NormalizedPosting | None, list[ValidationIssue]]:
        """Normalize a source draft into C06 or report validation issues."""
        ...


@runtime_checkable
class IdentityResolver(Protocol):
    """Boundary 3: Canonical identity resolution and revision tracking."""

    def resolve(
        self,
        normalized: NormalizedPosting,
        existing: ExistingIdentityView,
    ) -> tuple[uuid.UUID, PostingRevision, IdentityMatchDecision]:
        """Resolve canonical job UUID, revision record, and matching decision."""
        ...


@runtime_checkable
class RuleEvaluator(Protocol):
    """Boundary 4: Deterministic hard criterion evaluation."""

    def evaluate_rules(
        self,
        revision: PostingRevision,
        policy: SearchPolicy,
        eligibility: CandidateEligibility,
    ) -> Assessment:
        """Evaluate deterministic rules and return a rules-only Assessment."""
        ...


@runtime_checkable
class ContextSelector(Protocol):
    """Boundary 5 (Legacy): Context bundle construction (JSON or RAG).

    Deprecated: Use ContextSelectorV2 with ContextSelectionRequest.
    """

    def select_context(
        self,
        requirements: list[str],
        profile: ProfileSnapshot,
        strategy: ContextStrategy,
        token_budget: int,
    ) -> tuple[ContextBundle | None, ClassifiedError | None]:
        """Build C09 ContextBundle within token budget or return ClassifiedError."""
        ...


@runtime_checkable
class ContextSelectorV2(Protocol):
    """Boundary 5 (V2): Versioned context selection (JSON or RAG) with full request envelope."""

    def select_context(
        self,
        request: ContextSelectionRequest,
    ) -> tuple[ContextSelectionResult | None, ClassifiedError | None]:
        """Build ContextSelectionResult within token budget or return ClassifiedError."""
        ...


@runtime_checkable
class ModelProvider(Protocol):
    """Boundary 6: Local inference and embedding provider."""

    def generate(self, call: ModelCall) -> ModelResult:
        """Execute structured local model generation."""
        ...

    def embed(
        self,
        texts: list[str],
        model: str,
    ) -> tuple[EmbeddingResponse | None, ClassifiedError | None]:
        """Generate vector embeddings with local embedding model."""
        ...


@runtime_checkable
class Assessor(Protocol):
    """Boundary 7 (Legacy): Model-assisted relevance assessment."""

    def assess(
        self,
        rule_outcomes: list[RuleOutcome],
        revision: PostingRevision,
        context: ContextBundle,
    ) -> Assessment:
        """Perform full assessment incorporating rule outcomes and candidate context."""
        ...


@runtime_checkable
class AssessorV2(Protocol):
    """Boundary 7 (V2): Versioned model-assisted relevance assessment with full request envelope."""

    def assess(
        self,
        request: AssessmentRequest,
    ) -> AssessmentRunResult:
        """Perform full assessment incorporating rule outcomes, requirements, and candidate context."""
        ...


@runtime_checkable
class SalesforceGateway(Protocol):
    """Boundary 8 (Legacy): Salesforce API gateway and synchronization."""

    def execute_sync(
        self,
        operation: SyncOperation,
    ) -> tuple[str | None, ClassifiedError | None]:
        """Execute sync operation, returning remote Salesforce record ID or ClassifiedError."""
        ...


@runtime_checkable
class SalesforceGatewayV2(Protocol):
    """Boundary 8 (V2): Typed, versioned Salesforce REST gateway (SFCLIENT-01)."""

    def check_connection(
        self,
        request: ConnectionCheckRequest,
    ) -> GatewayResult[ConnectionCheckResult]:
        """Verify connectivity and identity with Salesforce org."""
        ...

    def get_limits(
        self,
        request: LimitsRequest,
    ) -> GatewayResult[LimitsResult]:
        """Retrieve organization API limits."""
        ...

    def describe_object(
        self,
        request: DescribeObjectRequest,
    ) -> GatewayResult[DescribeObjectResult]:
        """Retrieve sObject metadata capabilities."""
        ...

    def get_record(
        self,
        request: GetRecordRequest,
    ) -> GatewayResult[GetRecordResult]:
        """Retrieve selected fields of a record by ID or External ID."""
        ...

    def query_page(
        self,
        request: QueryPageRequest,
    ) -> GatewayResult[QueryPageResult]:
        """Execute SOQL query page or fetch next page via continuation."""
        ...

    def upsert_by_external_id(
        self,
        request: UpsertRequest,
    ) -> GatewayResult[UpsertResult]:
        """Upsert an sObject record by External ID."""
        ...

    def update_record(
        self,
        request: UpdateRequest,
    ) -> GatewayResult[UpdateResult]:
        """Update an sObject record by known Record ID."""
        ...


@runtime_checkable
class Generator(Protocol):
    """Boundary 9: Document content drafting."""

    def generate_draft(
        self,
        request: GenerationRequest,
        context: ContextBundle,
    ) -> tuple[DraftDocument | DraftDocumentV2 | None, ClassifiedError | None]:
        """Generate structured draft document with typed evidence references."""
        ...


@runtime_checkable
class RendererDelivery(Protocol):
    """Boundary 10: Document rendering and file delivery."""

    def render(
        self,
        draft: DraftDocument | DraftDocumentV2,
        output_format: str,
        destination_path: str,
    ) -> tuple[Artifact | None, ClassifiedError | None]:
        """Render draft into local physical file (DOCX or PDF)."""
        ...

    def deliver(
        self,
        artifact: Artifact,
        gateway: SalesforceGateway,
    ) -> tuple[Artifact, ClassifiedError | None]:
        """Deliver artifact to remote Salesforce Files."""
        ...

