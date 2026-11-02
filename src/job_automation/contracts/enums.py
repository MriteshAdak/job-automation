"""State domain enums and classification enums for all contracts.

Eight independent state domains (blueprint §5) plus classification enums.
Wire values use snake_case except ApplicationProgress which uses
capitalized labels for Salesforce display mapping.
"""

from __future__ import annotations

from enum import StrEnum


# ===================================================================
# Eight state domains (blueprint §5)
# ===================================================================


class PipelineStage(StrEnum):
    """Pipeline processing stage. Authority: local application."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class HardCriterionResult(StrEnum):
    """Hard criterion evaluation result. Authority: deterministic rules."""

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class AssessmentDisposition(StrEnum):
    """Assessment outcome disposition. Authority: local assessment."""

    ELIGIBLE = "eligible"
    REVIEW = "review"
    REJECTED = "rejected"


class PostingAvailability(StrEnum):
    """Posting availability status. Authority: source observations."""

    ACTIVE = "active"
    NOT_SEEN = "not_seen"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ApplicationProgress(StrEnum):
    """Application tracking progress. Authority: candidate in Salesforce.

    Wire values use capitalized labels for Salesforce display mapping.
    """

    NEW = "New"
    REVIEW = "Review"
    SHORTLISTED = "Shortlisted"
    APPLIED = "Applied"
    INTERVIEWING = "Interviewing"
    OFFER = "Offer"
    REJECTED = "Rejected"
    WITHDRAWN = "Withdrawn"
    ARCHIVED = "Archived"


class SyncOperationState(StrEnum):
    """Salesforce sync operation state. Authority: local outbox/gateway."""

    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GenerationProcessing(StrEnum):
    """Document generation processing state. Authority: request workflow."""

    PENDING = "pending"
    RUNNING = "running"
    UPLOAD_PENDING = "upload_pending"
    READY_FOR_REVIEW = "ready_for_review"
    FAILED = "failed"


class DocumentApproval(StrEnum):
    """Document approval status. Authority: candidate; generation never approves."""

    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


# ===================================================================
# Classification and strategy enums
# ===================================================================


class ContextStrategy(StrEnum):
    """Context construction strategy for candidate evidence."""

    JSON = "json"
    RAG = "rag"


class FindingStatus(StrEnum):
    """Status of a requirement match finding."""

    MATCH = "match"
    GAP = "gap"
    UNKNOWN = "unknown"


class RequirementObligation(StrEnum):
    """Obligation level of an extracted job requirement."""

    REQUIRED = "required"
    PREFERRED = "preferred"
    UNCLEAR = "unclear"


class RequirementCategory(StrEnum):
    """Domain category of a job requirement."""

    SKILL = "skill"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    LANGUAGE = "language"
    CERTIFICATION = "certification"
    OTHER = "other"


class AssessmentMode(StrEnum):
    """Execution mode of the assessment run."""

    PRIMARY = "primary"
    COMPARISON = "comparison"


class AssessmentMethod(StrEnum):
    """Assessment method used to produce a C11 assessment."""

    RULES = "rules"
    LLM = "llm"


class WorkplaceType(StrEnum):
    """Workplace arrangement type."""

    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class InventorySemantics(StrEnum):
    """Source inventory completeness semantics.

    complete_board: all postings from the entire board/source.
    filtered_feed: subset from a configured filter/category.
    search_results: results from a query; absence does not imply closure.
    """

    COMPLETE_BOARD = "complete_board"
    FILTERED_FEED = "filtered_feed"
    SEARCH_RESULTS = "search_results"


class AcquisitionMethod(StrEnum):
    """How job data is acquired from a source."""

    API = "api"
    PERMITTED_SCRAPING = "permitted_scraping"
    MANUAL_IMPORT = "manual_import"


class FetchOutcome(StrEnum):
    """Outcome of a fetch operation for a source."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class CompensationProvenance(StrEnum):
    """Origin of compensation data."""

    EMPLOYER_PROVIDED = "employer_provided"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class DocumentType(StrEnum):
    """Type of generated document."""

    CV = "cv"
    COVER_LETTER = "cover_letter"


class EvidenceFactKind(StrEnum):
    """Kind of candidate evidence fact."""

    EMPLOYMENT = "employment"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    SKILL = "skill"
    LANGUAGE = "language"
    PROJECT = "project"
    PUBLICATION = "publication"
    AWARD = "award"
    VOLUNTEER = "volunteer"
    OTHER = "other"


class SalaryPeriod(StrEnum):
    """Salary payment period."""

    HOURLY = "hourly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class EmploymentType(StrEnum):
    """Employment arrangement type."""

    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    TEMPORARY = "temporary"
    UNKNOWN = "unknown"


class RunStatus(StrEnum):
    """Overall pipeline run status."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"

