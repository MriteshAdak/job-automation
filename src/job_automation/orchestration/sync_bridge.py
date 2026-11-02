"""Sync bridge adapting orchestration domain entities to SYNC-01 contracts (RUN-01-S07).

Translates (PostingBinding, AssessmentSelection, CanonicalJob, Assessment) into
validated SyncSubmission envelopes without placeholder titles, empty URLs,
or freshly synthesized evaluation timestamps.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.postings import NormalizedPosting
from job_automation.identity.companies import resolve_company_identity
from job_automation.orchestration.records import AssessmentSelection, PostingBinding
from job_automation.salesforce.sync_errors import SyncValidationError
from job_automation.salesforce.sync_records import (
    PublicationPurpose,
    SyncSubmission,
)


def _extract_job_title(
    canonical_job: CanonicalJob,
    binding: PostingBinding | None = None,
    assessment: Assessment | None = None,
) -> str:
    """Extract authoritative job title, rejecting empty or placeholder titles."""
    # 1. Prefer binding's C06 title if available
    if binding and binding.c06_snapshot and binding.c06_snapshot.title:
        title = binding.c06_snapshot.title.strip()
        if title:
            return title

    # 2. Look up matching revision in canonical_job
    if assessment and canonical_job.revisions:
        for rev in canonical_job.revisions:
            if rev.content_hash == assessment.posting_revision and rev.title:
                title = rev.title.strip()
                if title:
                    return title

    # 3. Fall back to current revision
    if canonical_job.revisions:
        for rev in canonical_job.revisions:
            if rev.revision_id == canonical_job.current_revision_id and rev.title:
                title = rev.title.strip()
                if title:
                    return title

    raise SyncValidationError(
        f"Cannot build SyncSubmission for canonical job {canonical_job.canonical_job_id}: "
        f"job title is empty or missing"
    )


def _extract_source_urls(
    canonical_job: CanonicalJob,
    binding: PostingBinding | None = None,
    assessment: Assessment | None = None,
) -> list[str]:
    """Extract non-empty source URLs from binding and canonical revisions."""
    urls: list[str] = []

    # 1. Add binding C06 source URL if available
    if binding and binding.c06_snapshot and binding.c06_snapshot.source_url:
        u = binding.c06_snapshot.source_url.strip()
        if u and u not in urls:
            urls.append(u)

    # 2. Add URLs from matching revision
    if assessment and canonical_job.revisions:
        for rev in canonical_job.revisions:
            if rev.content_hash == assessment.posting_revision:
                for u in rev.source_urls:
                    u_clean = u.strip()
                    if u_clean and u_clean not in urls:
                        urls.append(u_clean)

    # 3. Add URLs from current revision if still empty
    if not urls and canonical_job.revisions:
        for rev in canonical_job.revisions:
            if rev.revision_id == canonical_job.current_revision_id:
                for u in rev.source_urls:
                    u_clean = u.strip()
                    if u_clean and u_clean not in urls:
                        urls.append(u_clean)

    if not urls:
        raise SyncValidationError(
            f"Cannot build SyncSubmission for canonical job {canonical_job.canonical_job_id}: "
            f"source URLs list is empty"
        )

    return urls


def _resolve_company_id(
    canonical_job: CanonicalJob,
    binding: PostingBinding | None = None,
) -> uuid.UUID:
    """Resolve or guarantee stable canonical company UUID."""
    if canonical_job.canonical_company_id:
        return canonical_job.canonical_company_id

    # Fallback resolution from company name
    comp_name = canonical_job.company_name.strip()
    if not comp_name:
        raise SyncValidationError(
            f"Cannot build SyncSubmission for canonical job {canonical_job.canonical_job_id}: "
            f"company name is empty"
        )

    # Generate deterministic UUID5 namespace identity if unmapped
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"company.{comp_name.lower()}")


def build_sync_submission(
    selection: AssessmentSelection,
    assessment: Assessment,
    canonical_job: CanonicalJob,
    binding: PostingBinding | None = None,
    run_id: str | uuid.UUID | None = None,
    publication_purpose: PublicationPurpose = PublicationPurpose.PRIMARY_FINAL,
) -> SyncSubmission:
    """Build a validated SyncSubmission from frozen domain records.

    Guarantees:
    - Never uses placeholder title.
    - Never supplies empty source URLs.
    - Preserves exact frozen selection.evaluated_at timestamp (never fresh now()).
    - Preserves exact generation_token.
    - Requires matching canonical_job_id across selection, assessment, and job.
    """
    if selection.canonical_job_id != assessment.canonical_job_id:
        raise SyncValidationError(
            f"Selection canonical_job_id '{selection.canonical_job_id}' != "
            f"assessment canonical_job_id '{assessment.canonical_job_id}'"
        )
    if selection.canonical_job_id != canonical_job.canonical_job_id:
        raise SyncValidationError(
            f"Selection canonical_job_id '{selection.canonical_job_id}' != "
            f"canonical_job.canonical_job_id '{canonical_job.canonical_job_id}'"
        )
    if assessment.assessment_id != selection.assessment_id:
        raise SyncValidationError(
            f"Assessment ID '{assessment.assessment_id}' != selection assessment_id '{selection.assessment_id}'"
        )

    title = _extract_job_title(canonical_job, binding=binding, assessment=assessment)
    source_urls = _extract_source_urls(canonical_job, binding=binding, assessment=assessment)
    company_id = _resolve_company_id(canonical_job, binding=binding)

    comp_name = canonical_job.company_name.strip()
    if not comp_name and binding and binding.c06_snapshot and binding.c06_snapshot.company_name_hint:
        comp_name = binding.c06_snapshot.company_name_hint.strip()

    if not comp_name:
        raise SyncValidationError(
            f"Cannot build SyncSubmission for canonical job {canonical_job.canonical_job_id}: "
            f"company name cannot be empty"
        )

    return SyncSubmission(
        submission_id=uuid.uuid4(),
        assessment=assessment,
        canonical_job_id=canonical_job.canonical_job_id,
        posting_revision=assessment.posting_revision,
        evaluated_at=selection.evaluated_at,  # Exact frozen timestamp!
        generation_token=selection.generation_token,  # Exact frozen token!
        run_id=str(run_id) if run_id is not None else None,
        publication_purpose=publication_purpose,
        job_title=title,
        company_name=comp_name,
        canonical_company_id=company_id,
        source_urls=source_urls,
        availability=canonical_job.availability,
    )


def build_refresh_submission(
    selection: AssessmentSelection,
    assessment: Assessment,
    canonical_job: CanonicalJob,
    run_id: str | uuid.UUID | None = None,
) -> SyncSubmission:
    """Build a complete SyncSubmission for an already-tracked job refresh.

    Addresses DG4 by passing the explicitly selected C11 and real canonical projection,
    rather than falling back to placeholder titles or empty URLs.
    """
    return build_sync_submission(
        selection=selection,
        assessment=assessment,
        canonical_job=canonical_job,
        binding=None,
        run_id=run_id,
        publication_purpose=PublicationPurpose.PRIMARY_FINAL,
    )

