"""IdentityService coordinating matching, revision creation, persistence, and review."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.interfaces import ExistingIdentityView, IdentityMatchDecision
from job_automation.contracts.postings import NormalizedPosting
from job_automation.identity.companies import resolve_company_identity
from job_automation.identity.hashing import compute_revision_content_hash
from job_automation.identity.matching import find_review_candidates, find_strong_job_match
from job_automation.identity.merges import execute_merge, execute_reversal
from job_automation.identity.models import (
    IdentityResolutionResult,
    MatchOutcome,
    MergeOperation,
    ReversalOperation,
    ReviewCase,
)
from job_automation.identity.review import create_review_case, decide_review_case, list_review_cases
from job_automation.identity.revisions import (
    create_posting_revision,
    select_current_revision,
    update_revision_observation,
)

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine


class IdentityService:
    """Production service for identity resolution, revisions, review, and merge reversal."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine

    # -------------------------------------------------------------------------
    # IdentityResolver Protocol Implementation
    # -------------------------------------------------------------------------

    def resolve(
        self,
        normalized: NormalizedPosting,
        existing: ExistingIdentityView | None = None,
    ) -> tuple[uuid.UUID, PostingRevision, IdentityMatchDecision]:
        """Boundary 3: Canonical identity resolution and revision tracking."""
        res = self.resolve_and_commit(normalized)
        return res.canonical_job_id, res.revision, res.decision

    # -------------------------------------------------------------------------
    # Full Atomic Resolution & Persistence
    # -------------------------------------------------------------------------

    def resolve_and_commit(self, normalized: NormalizedPosting) -> IdentityResolutionResult:
        """Resolve posting identity and atomically commit all changes to durable storage."""
        with self.engine.transaction():
            content_hash = compute_revision_content_hash(normalized)
            comp_id, comp_name = resolve_company_identity(
                company_name_hint=normalized.company_name_hint,
                company_id_hint=normalized.company_id_hint,
                provider=normalized.source_key.provider,
                board_id=normalized.source_key.board_id,
                identity_repo=self.engine.identity,
            )

            # Persist raw normalized posting record (idempotent / ignore duplicates)
            try:
                self.engine.canonical_jobs.save_normalized_posting(normalized)
            except Exception:
                pass  # Normalized posting already saved for this key

            observation_id = uuid.uuid4()

            # -----------------------------------------------------------------
            # 1. Exact Source Identity Match
            # -----------------------------------------------------------------
            existing_job = self.engine.canonical_jobs.find_by_source_key(normalized.source_key)
            if existing_job is not None:
                # Find matching revision by content hash
                matching_rev = next(
                    (
                        r
                        for r in existing_job.revisions
                        if r.source_key == normalized.source_key and r.content_hash == content_hash
                    ),
                    None,
                )

                if matching_rev is not None:
                    # Content unchanged: advance observation metadata on existing revision
                    updated_rev = update_revision_observation(
                        revision=matching_rev,
                        observed_at=normalized.observed_at,
                        source_url=normalized.source_url,
                        application_url=normalized.application_url,
                    )
                    new_revisions = [
                        updated_rev if r.revision_id == updated_rev.revision_id else r
                        for r in existing_job.revisions
                    ]
                    updated_job = existing_job.model_copy(
                        update={
                            "revisions": new_revisions,
                            "last_seen_at": max(existing_job.last_seen_at, normalized.observed_at),
                        }
                    )
                    self.engine.canonical_jobs.save_canonical_job(updated_job)
                    self.engine.identity.save_source_identity(
                        source_key=normalized.source_key,
                        canonical_job_id=updated_job.canonical_job_id,
                        first_seen_at=updated_job.first_seen_at,
                        last_seen_at=updated_job.last_seen_at,
                    )
                    self.engine.identity.save_observation(
                        observation_id=observation_id,
                        canonical_job_id=updated_job.canonical_job_id,
                        revision_id=updated_rev.revision_id,
                        source_key=normalized.source_key,
                        raw_reference=normalized.raw_reference,
                        raw_content_hash=normalized.raw_content_hash,
                        observed_at=normalized.observed_at,
                    )

                    decision = IdentityMatchDecision(
                        match_type=MatchOutcome.EXACT_SOURCE_SAME_CONTENT.value,
                        matched_canonical_id=updated_job.canonical_job_id,
                        confidence=1.0,
                        rationale="Re-observed existing posting with unchanged content",
                    )
                    return IdentityResolutionResult(
                        canonical_job_id=updated_job.canonical_job_id,
                        revision=updated_rev,
                        decision=decision,
                        outcome=MatchOutcome.EXACT_SOURCE_SAME_CONTENT,
                        is_new_canonical=False,
                        is_new_revision=False,
                        observation_id=observation_id,
                    )

                # Content changed: create new revision snapshot under same canonical job
                new_rev = create_posting_revision(
                    canonical_job_id=existing_job.canonical_job_id,
                    normalized=normalized,
                    content_hash=content_hash,
                )
                # Carry forward prior URLs for this source so cumulative links remain accessible
                for r in existing_job.revisions:
                    if r.source_key == normalized.source_key:
                        for u in r.source_urls:
                            if u not in new_rev.source_urls:
                                new_rev.source_urls.append(u)
                        for u in r.application_urls:
                            if u not in new_rev.application_urls:
                                new_rev.application_urls.append(u)
                new_revisions = list(existing_job.revisions) + [new_rev]
                new_cur_rev_id = select_current_revision(new_revisions)
                updated_job = existing_job.model_copy(
                    update={
                        "revisions": new_revisions,
                        "current_revision_id": new_cur_rev_id,
                        "last_seen_at": max(existing_job.last_seen_at, normalized.observed_at),
                    }
                )
                self.engine.canonical_jobs.save_canonical_job(updated_job)
                self.engine.identity.save_source_identity(
                    source_key=normalized.source_key,
                    canonical_job_id=updated_job.canonical_job_id,
                    first_seen_at=updated_job.first_seen_at,
                    last_seen_at=updated_job.last_seen_at,
                )
                self.engine.identity.save_observation(
                    observation_id=observation_id,
                    canonical_job_id=updated_job.canonical_job_id,
                    revision_id=new_rev.revision_id,
                    source_key=normalized.source_key,
                    raw_reference=normalized.raw_reference,
                    raw_content_hash=normalized.raw_content_hash,
                    observed_at=normalized.observed_at,
                )

                decision = IdentityMatchDecision(
                    match_type=MatchOutcome.EXACT_SOURCE_NEW_REVISION.value,
                    matched_canonical_id=updated_job.canonical_job_id,
                    confidence=1.0,
                    rationale=f"Updated posting content created new revision {new_rev.revision_id}",
                )
                return IdentityResolutionResult(
                    canonical_job_id=updated_job.canonical_job_id,
                    revision=new_rev,
                    decision=decision,
                    outcome=MatchOutcome.EXACT_SOURCE_NEW_REVISION,
                    is_new_canonical=False,
                    is_new_revision=True,
                    observation_id=observation_id,
                )

            # -----------------------------------------------------------------
            # 2. Strong Cross-Source Key Match (Requisition / Application URL)
            # -----------------------------------------------------------------
            strong_match_job, strong_reason = find_strong_job_match(
                normalized=normalized,
                canonical_company_id=comp_id,
                canonical_repo=self.engine.canonical_jobs,
            )
            if strong_match_job is not None:
                # Add as alternate source to matched job
                new_rev = create_posting_revision(
                    canonical_job_id=strong_match_job.canonical_job_id,
                    normalized=normalized,
                    content_hash=content_hash,
                )
                new_sources = list(strong_match_job.linked_source_keys)
                if normalized.source_key not in new_sources:
                    new_sources.append(normalized.source_key)

                new_revisions = list(strong_match_job.revisions) + [new_rev]
                new_cur_rev_id = select_current_revision(new_revisions)
                updated_job = strong_match_job.model_copy(
                    update={
                        "linked_source_keys": new_sources,
                        "revisions": new_revisions,
                        "current_revision_id": new_cur_rev_id,
                        "last_seen_at": max(strong_match_job.last_seen_at, normalized.observed_at),
                    }
                )
                self.engine.canonical_jobs.save_canonical_job(updated_job)
                self.engine.identity.save_source_identity(
                    source_key=normalized.source_key,
                    canonical_job_id=updated_job.canonical_job_id,
                    first_seen_at=normalized.observed_at,
                    last_seen_at=normalized.observed_at,
                )
                self.engine.identity.save_observation(
                    observation_id=observation_id,
                    canonical_job_id=updated_job.canonical_job_id,
                    revision_id=new_rev.revision_id,
                    source_key=normalized.source_key,
                    raw_reference=normalized.raw_reference,
                    raw_content_hash=normalized.raw_content_hash,
                    observed_at=normalized.observed_at,
                )

                decision = IdentityMatchDecision(
                    match_type=MatchOutcome.STRONG_KEY_MATCH.value,
                    matched_canonical_id=updated_job.canonical_job_id,
                    confidence=1.0,
                    rationale=f"Strong evidence match ({strong_reason}) linked as alternate source",
                )
                return IdentityResolutionResult(
                    canonical_job_id=updated_job.canonical_job_id,
                    revision=new_rev,
                    decision=decision,
                    outcome=MatchOutcome.STRONG_KEY_MATCH,
                    is_new_canonical=False,
                    is_new_revision=True,
                    observation_id=observation_id,
                )

            # -----------------------------------------------------------------
            # 3. Fuzzy Text Similarity Check (Propose Review, Do Not Merge)
            # -----------------------------------------------------------------
            review_candidates = find_review_candidates(
                normalized=normalized,
                canonical_company_id=comp_id,
                canonical_repo=self.engine.canonical_jobs,
            )
            if review_candidates:
                best_cand_job, sim_score, rationale = review_candidates[0]
                # Maintain separate canonical identity for the new job
                new_job_id = uuid.uuid4()
                new_rev = create_posting_revision(
                    canonical_job_id=new_job_id,
                    normalized=normalized,
                    content_hash=content_hash,
                )
                new_job = CanonicalJob(
                    canonical_job_id=new_job_id,
                    canonical_company_id=comp_id,
                    company_name=comp_name,
                    linked_source_keys=[normalized.source_key],
                    revisions=[new_rev],
                    current_revision_id=new_rev.revision_id,
                    first_seen_at=normalized.observed_at,
                    last_seen_at=normalized.observed_at,
                    duplicate_proposal_reason=rationale,
                )
                self.engine.canonical_jobs.save_canonical_job(new_job)
                self.engine.identity.save_source_identity(
                    source_key=normalized.source_key,
                    canonical_job_id=new_job_id,
                    first_seen_at=normalized.observed_at,
                    last_seen_at=normalized.observed_at,
                )
                self.engine.identity.save_observation(
                    observation_id=observation_id,
                    canonical_job_id=new_job_id,
                    revision_id=new_rev.revision_id,
                    source_key=normalized.source_key,
                    raw_reference=normalized.raw_reference,
                    raw_content_hash=normalized.raw_content_hash,
                    observed_at=normalized.observed_at,
                )

                # Create durable review case
                review_case = create_review_case(
                    candidate_job_ids=[best_cand_job.canonical_job_id],
                    source_key=normalized.source_key,
                    reason=rationale,
                    evidence={
                        "title": normalized.title,
                        "similarity_score": round(sim_score, 3),
                        "candidate_title": best_cand_job.revisions[0].title
                        if best_cand_job.revisions
                        else "",
                    },
                    identity_repo=self.engine.identity,
                )

                decision = IdentityMatchDecision(
                    match_type=MatchOutcome.REVIEW_CANDIDATE.value,
                    matched_canonical_id=best_cand_job.canonical_job_id,
                    confidence=round(sim_score, 3),
                    rationale=f"Review candidate proposed ({rationale}); allocated separate canonical {new_job_id}",
                )
                return IdentityResolutionResult(
                    canonical_job_id=new_job_id,
                    revision=new_rev,
                    decision=decision,
                    outcome=MatchOutcome.REVIEW_CANDIDATE,
                    is_new_canonical=True,
                    is_new_revision=True,
                    review_case_id=review_case.case_id,
                    observation_id=observation_id,
                )

            # -----------------------------------------------------------------
            # 4. New Canonical Job Opportunity
            # -----------------------------------------------------------------
            new_job_id = uuid.uuid4()
            new_rev = create_posting_revision(
                canonical_job_id=new_job_id,
                normalized=normalized,
                content_hash=content_hash,
            )
            new_job = CanonicalJob(
                canonical_job_id=new_job_id,
                canonical_company_id=comp_id,
                company_name=comp_name,
                linked_source_keys=[normalized.source_key],
                revisions=[new_rev],
                current_revision_id=new_rev.revision_id,
                first_seen_at=normalized.observed_at,
                last_seen_at=normalized.observed_at,
            )
            self.engine.canonical_jobs.save_canonical_job(new_job)
            self.engine.identity.save_source_identity(
                source_key=normalized.source_key,
                canonical_job_id=new_job_id,
                first_seen_at=normalized.observed_at,
                last_seen_at=normalized.observed_at,
            )
            self.engine.identity.save_observation(
                observation_id=observation_id,
                canonical_job_id=new_job_id,
                revision_id=new_rev.revision_id,
                source_key=normalized.source_key,
                raw_reference=normalized.raw_reference,
                raw_content_hash=normalized.raw_content_hash,
                observed_at=normalized.observed_at,
            )

            decision = IdentityMatchDecision(
                match_type=MatchOutcome.NEW_CANONICAL.value,
                matched_canonical_id=None,
                confidence=1.0,
                rationale="Registered new canonical job opportunity",
            )
            return IdentityResolutionResult(
                canonical_job_id=new_job_id,
                revision=new_rev,
                decision=decision,
                outcome=MatchOutcome.NEW_CANONICAL,
                is_new_canonical=True,
                is_new_revision=True,
                observation_id=observation_id,
            )

    # -------------------------------------------------------------------------
    # Merges & Reversal
    # -------------------------------------------------------------------------

    def merge_canonical_jobs(
        self,
        surviving_id: uuid.UUID,
        merged_id: uuid.UUID,
        actor: str,
        reason: str,
    ) -> MergeOperation:
        """Merge merged_id into surviving_id with complete audit lineage."""
        return execute_merge(
            surviving_id=surviving_id,
            merged_id=merged_id,
            actor=actor,
            reason=reason,
            canonical_repo=self.engine.canonical_jobs,
            identity_repo=self.engine.identity,
        )

    def reverse_merge(
        self,
        operation_id: str,
        actor: str,
        reason: str,
    ) -> ReversalOperation:
        """Reverse a prior merge operation restoring original identities and links."""
        return execute_reversal(
            operation_id=operation_id,
            actor=actor,
            reason=reason,
            canonical_repo=self.engine.canonical_jobs,
            identity_repo=self.engine.identity,
        )

    # -------------------------------------------------------------------------
    # Review Management
    # -------------------------------------------------------------------------

    def list_review_cases(self, status: str | None = None) -> list[ReviewCase]:
        """List review cases."""
        return list_review_cases(self.engine.identity, status=status)

    def decide_review_case(
        self,
        case_id: str,
        decision: str,
        actor: str,
        reason: str,
    ) -> ReviewCase:
        """Record human decision on a review case."""
        return decide_review_case(
            case_id=case_id,
            decision=decision,
            actor=actor,
            reason=reason,
            identity_repo=self.engine.identity,
            canonical_repo=self.engine.canonical_jobs,
        )
