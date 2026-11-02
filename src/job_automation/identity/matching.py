"""Job identity matching rules, strong evidence validation, and review candidate detection."""

from __future__ import annotations

import difflib
import uuid
from typing import TYPE_CHECKING, Any

from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.postings import NormalizedPosting
from job_automation.identity.urls import are_urls_equivalent, is_job_specific_url

if TYPE_CHECKING:
    from job_automation.storage.repositories.canonical_jobs import CanonicalJobRepository
    from job_automation.storage.repositories.identity import IdentityRepository


def extract_requisition_hint(normalized: NormalizedPosting) -> str | None:
    """Extract explicit requisition or vacancy reference from posting metadata if present."""
    # Check field provenance or known metadata mappings
    if "requisition_id" in normalized.field_provenance:
        return normalized.field_provenance["requisition_id"].strip()
    return None


def calculate_text_similarity(text1: str, text2: str) -> float:
    """Calculate token-normalized SequenceMatcher similarity between two text strings."""
    if not text1 or not text2:
        return 0.0
    t1 = " ".join(text1.lower().split())
    t2 = " ".join(text2.lower().split())
    if t1 == t2:
        return 1.0
    # Quick length ratio check
    len_ratio = min(len(t1), len(t2)) / max(len(t1), len(t2))
    if len_ratio < 0.6:
        return 0.0
    return difflib.SequenceMatcher(None, t1[:2000], t2[:2000]).ratio()


def find_strong_job_match(
    normalized: NormalizedPosting,
    canonical_company_id: uuid.UUID | None,
    canonical_repo: CanonicalJobRepository,
) -> tuple[CanonicalJob | None, str | None]:
    """Find existing canonical job with strong corroborating evidence (requisition, job URL).

    Returns (matched_job, reason) or (None, None).
    """
    if canonical_company_id is None:
        return None, None

    req_hint = extract_requisition_hint(normalized)
    has_job_url = is_job_specific_url(normalized.application_url or "")

    # Inspect all existing jobs for this company
    all_jobs = canonical_repo.list_jobs()
    for existing_job in all_jobs:
        if existing_job.canonical_company_id != canonical_company_id:
            continue

        # Check existing job's current revision
        current_rev = next(
            (r for r in existing_job.revisions if r.revision_id == existing_job.current_revision_id),
            existing_job.revisions[0] if existing_job.revisions else None,
        )
        if not current_rev:
            continue

        # 1. Matching requisition under same employer
        if req_hint:
            # If existing job has an explicit requisition recorded in provenance
            existing_norm = canonical_repo.get_normalized_posting(current_rev.source_key)
            if existing_norm:
                existing_req = extract_requisition_hint(existing_norm)
                if existing_req and existing_req != req_hint:
                    # Explicitly differing requisitions block merging!
                    continue
                if existing_req and existing_req == req_hint:
                    return existing_job, f"matching_requisition:{req_hint}"

        # 2. Matching job-specific application URL under same employer
        if has_job_url and normalized.application_url:
            for app_url in current_rev.application_urls:
                if are_urls_equivalent(normalized.application_url, app_url):
                    # Ensure no differing requisition contradicts
                    existing_norm = canonical_repo.get_normalized_posting(current_rev.source_key)
                    if existing_norm and req_hint:
                        existing_req = extract_requisition_hint(existing_norm)
                        if existing_req and existing_req != req_hint:
                            continue  # Differing requisition vetoes URL match
                    return existing_job, "matching_job_specific_application_url"

    return None, None


def find_review_candidates(
    normalized: NormalizedPosting,
    canonical_company_id: uuid.UUID | None,
    canonical_repo: CanonicalJobRepository,
    title_threshold: float = 0.85,
    desc_threshold: float = 0.85,
) -> list[tuple[CanonicalJob, float, str]]:
    """Detect fuzzy / text similarity candidates for human review.

    Never auto-merges; returns candidate jobs with similarity score and rationale.
    """
    candidates: list[tuple[CanonicalJob, float, str]] = []
    all_jobs = canonical_repo.list_jobs()

    req_hint = extract_requisition_hint(normalized)

    for job in all_jobs:
        current_rev = next(
            (r for r in job.revisions if r.revision_id == job.current_revision_id),
            job.revisions[0] if job.revisions else None,
        )
        if not current_rev:
            continue

        # If different explicit requisitions exist, record that reason for review
        existing_norm = canonical_repo.get_normalized_posting(current_rev.source_key)
        if existing_norm and req_hint:
            existing_req = extract_requisition_hint(existing_norm)
            if existing_req and existing_req != req_hint:
                # Explicitly differing requisitions must not be merged
                continue

        title_sim = calculate_text_similarity(normalized.title, current_rev.title)
        if title_sim < title_threshold:
            continue

        # Compare descriptions if available
        desc_sim = 0.0
        if existing_norm and normalized.description_clean:
            desc_sim = calculate_text_similarity(
                normalized.description_clean, existing_norm.description_clean
            )
            if desc_sim < desc_threshold:
                continue

        avg_score = (title_sim + desc_sim) / 2.0 if desc_sim > 0.0 else title_sim
        candidates.append(
            (
                job,
                avg_score,
                f"High text similarity (title={title_sim:.2f}, desc={desc_sim:.2f})",
            )
        )

    # Sort descending by score
    candidates.sort(key=lambda c: c[1], reverse=True)
    return candidates

