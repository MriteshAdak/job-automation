"""Candidate eligibility verification comparing candidate truth with job requirements."""

from __future__ import annotations

from job_automation.assessment.evidence import build_candidate_evidence, build_job_evidence
from job_automation.assessment.models import FactualOutcome
from job_automation.contracts.enums import WorkplaceType
from job_automation.contracts.evidence import CandidateEvidenceReference, JobEvidenceReference
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.profile import CandidateEligibility, CandidateFact
from job_automation.policy.vocabulary import normalize_lookup


class CandidateEligibilityCheckResult:
    """Result of comparing candidate eligibility against job constraints."""

    def __init__(
        self,
        check_name: str,
        factual_result: FactualOutcome,
        reason: str,
        candidate_evidence: CandidateEvidenceReference | None = None,
        job_evidence: JobEvidenceReference | None = None,
    ) -> None:
        self.check_name = check_name
        self.factual_result = factual_result
        self.reason = reason
        self.candidate_evidence = candidate_evidence
        self.job_evidence = job_evidence


def evaluate_candidate_eligibility(
    posting: NormalizedPosting,
    posting_revision: str,
    eligibility: CandidateEligibility,
    profile_version: str,
    permitted_facts: list[CandidateFact],
) -> list[CandidateEligibilityCheckResult]:
    """Evaluate candidate explicit eligibility against posting constraints.

    Separates candidate truth (work authorization, remote eligibility) from
    job criteria. Omitted facts are treated as unknown, never as negative proof.
    """
    results: list[CandidateEligibilityCheckResult] = []

    # 1. Remote eligibility check
    if posting.workplace_type == WorkplaceType.REMOTE:
        job_ev = build_job_evidence(
            posting,
            posting_revision,
            "workplace_type",
            quotation="workplace_type: remote",
        )
        if not eligibility.remote_eligible:
            results.append(
                CandidateEligibilityCheckResult(
                    check_name="candidate_remote_eligible",
                    factual_result=FactualOutcome.FAIL,
                    reason="Job is remote, but candidate is marked not eligible for remote work",
                    job_evidence=job_ev,
                )
            )
        else:
            # Check remote restrictions
            restr = posting.remote_eligibility_restrictions
            if not restr:
                results.append(
                    CandidateEligibilityCheckResult(
                        check_name="remote_restrictions_applicable",
                        factual_result=FactualOutcome.UNKNOWN,
                        reason="Job is remote but remote eligibility restrictions are unstated in posting",
                        job_evidence=job_ev,
                    )
                )
            else:
                norm_restr = {normalize_lookup(r) for r in restr}
                # Check candidate's authorized countries against remote restrictions
                norm_auth = {normalize_lookup(c) for c in eligibility.work_authorization_countries}
                if any(r in norm_auth for r in norm_restr):
                    results.append(
                        CandidateEligibilityCheckResult(
                            check_name="remote_restrictions_applicable",
                            factual_result=FactualOutcome.PASS,
                            reason=f"Candidate authorization matches remote restrictions [{', '.join(restr)}]",
                            job_evidence=build_job_evidence(
                                posting,
                                posting_revision,
                                "remote_eligibility_restrictions",
                                quotation=f"[{', '.join(restr)}]",
                            ),
                        )
                    )
                else:
                    results.append(
                        CandidateEligibilityCheckResult(
                            check_name="remote_restrictions_applicable",
                            factual_result=FactualOutcome.UNKNOWN,
                            reason=(
                                f"Candidate authorized countries [{', '.join(eligibility.work_authorization_countries)}] "
                                f"do not clearly satisfy posting remote restrictions [{', '.join(restr)}]"
                            ),
                            job_evidence=build_job_evidence(
                                posting,
                                posting_revision,
                                "remote_eligibility_restrictions",
                                quotation=f"[{', '.join(restr)}]",
                            ),
                        )
                    )

    # 2. Geographic work authorization check
    if posting.locations:
        posting_countries = [loc.country for loc in posting.locations if loc.country]
        if posting_countries:
            norm_job_countries = {normalize_lookup(c) for c in posting_countries}
            norm_auth_countries = {normalize_lookup(c) for c in eligibility.work_authorization_countries}

            # Check if candidate has authorization in at least one job country
            overlap = norm_job_countries.intersection(norm_auth_countries)
            if overlap:
                # Find candidate fact if any cites authorization
                cand_ev: CandidateEvidenceReference | None = None
                for fact in permitted_facts:
                    for claim in fact.claims:
                        if "authorization" in claim.lower() or "authorized" in claim.lower():
                            cand_ev = build_candidate_evidence(profile_version, fact.fact_id)
                            break
                    if cand_ev:
                        break

                results.append(
                    CandidateEligibilityCheckResult(
                        check_name="work_authorization",
                        factual_result=FactualOutcome.PASS,
                        reason=f"Candidate confirmed work authorization in posting country [{', '.join(overlap)}]",
                        candidate_evidence=cand_ev,
                        job_evidence=build_job_evidence(
                            posting,
                            posting_revision,
                            "locations.country",
                            quotation=", ".join(posting_countries),
                        ),
                    )
                )
            else:
                # Absence from authorization list is unknown, not proof of inability
                results.append(
                    CandidateEligibilityCheckResult(
                        check_name="work_authorization",
                        factual_result=FactualOutcome.UNKNOWN,
                        reason=(
                            f"Posting is in [{', '.join(posting_countries)}], but candidate profile "
                            f"does not record explicit work authorization for these countries"
                        ),
                        job_evidence=build_job_evidence(
                            posting,
                            posting_revision,
                            "locations.country",
                            quotation=", ".join(posting_countries),
                        ),
                    )
                )

    return results

