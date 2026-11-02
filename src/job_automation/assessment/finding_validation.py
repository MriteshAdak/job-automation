"""Validation of model assessment proposals into typed findings (MATCH-02-S04).

Enforces:
- Exactly one finding per admitted requirement
- Rejection of invented requirement IDs or duplicate findings
- Matches must cite admitted candidate evidence
- Job evidence references must resolve against posting text
- Unknowns must not cite invented candidate evidence
- Application-derived unknowns fill omitted requirements
- Mechanically detectable contradictions trigger validation warnings
"""

from __future__ import annotations

import re

from job_automation.assessment.llm_records import (
    AssessmentProposal,
    FindingStatus,
    RequirementItem,
    RequirementObligation,
    RequirementSet,
)
from job_automation.assessment.reference_validation import (
    validate_candidate_reference,
    validate_job_reference,
)
from job_automation.contracts.assessment import RequirementFinding
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.profile import ProfileSnapshot


def validate_proposal_findings(
    proposal: AssessmentProposal,
    requirement_set: RequirementSet,
    profile: ProfileSnapshot,
    posting: NormalizedPosting,
    posting_revision: str,
    bundle: ContextBundle,
) -> tuple[list[RequirementFinding], list[ValidationIssue]]:
    """Validate model proposal findings and convert to application-owned RequirementFinding list.

    Returns:
    - List of validated RequirementFinding records (one per admitted requirement)
    - List of ValidationIssue records (fatal errors and review warnings)
    """
    issues: list[ValidationIssue] = []
    admitted_reqs: dict[str, RequirementItem] = {
        r.requirement_id: r for r in requirement_set.requirements
    }

    seen_proposal_ids: set[str] = set()
    proposal_by_req_id: dict[str, Any] = {}

    # 1. Inspect proposal findings
    for prop in proposal.findings:
        req_id = prop.requirement_id

        # Check for unknown requirement ID invented by model
        if req_id not in admitted_reqs:
            issues.append(
                ValidationIssue(
                    field_path="findings",
                    code="unknown_requirement_id",
                    message=f"Model proposed finding for unknown requirement ID '{req_id}'",
                )
            )
            continue

        # Check for duplicate findings in proposal
        if req_id in seen_proposal_ids:
            issues.append(
                ValidationIssue(
                    field_path="findings",
                    code="duplicate_requirement_finding",
                    message=f"Model produced duplicate findings for requirement ID '{req_id}'",
                )
            )
            continue

        seen_proposal_ids.add(req_id)
        proposal_by_req_id[req_id] = prop

    validated_findings: list[RequirementFinding] = []

    # Fact text lookup for contradiction checking
    fact_text_map: dict[uuid.UUID, str] = {}
    for f in profile.evidence_records:
        parts = [f.title]
        parts.extend(f.claims)
        parts.extend(f.skills)
        parts.extend(f.metrics)
        fact_text_map[f.fact_id] = " ".join(parts)

    # 2. Validate findings for each admitted requirement in order
    for req in requirement_set.requirements:
        prop = proposal_by_req_id.get(req.requirement_id)

        if prop is None:
            # Model omitted this requirement! Default to application-owned UNKNOWN
            issues.append(
                ValidationIssue(
                    field_path="findings",
                    code="missing_requirement_coverage",
                    message=f"Model omitted finding for requirement '{req.requirement_id}'; defaulted to unknown",
                )
            )
            validated_findings.append(
                RequirementFinding(
                    requirement_id=req.requirement_id,
                    requirement_text=req.text,
                    obligation=req.obligation,
                    category=req.category,
                    status=FindingStatus.UNKNOWN,
                    job_evidence=req.job_evidence,
                    reason="Omitted from model assessment; defaulted to unknown",
                    score=None,
                )
            )
            continue

        # Validate candidate citations
        valid_cand_refs = []
        for cand_ref in prop.candidate_evidence:
            cand_issues = validate_candidate_reference(
                ref=cand_ref,
                profile=profile,
                bundle=bundle,
                context_prefix=f"Finding '{req.requirement_id}' candidate evidence",
            )
            issues.extend(cand_issues)
            if not cand_issues:
                valid_cand_refs.append(cand_ref)

        # Validate job citation if model supplied one, otherwise use requirement's job evidence
        effective_job_ev = prop.job_evidence or req.job_evidence
        if prop.job_evidence is not None:
            job_issues = validate_job_reference(
                ref=prop.job_evidence,
                posting=posting,
                posting_revision=posting_revision,
                context_prefix=f"Finding '{req.requirement_id}' job evidence",
            )
            issues.extend(job_issues)
            if job_issues:
                effective_job_ev = req.job_evidence

        # Semantic status invariants
        finding_status = prop.status

        if prop.status == FindingStatus.MATCH:
            if not valid_cand_refs:
                issues.append(
                    ValidationIssue(
                        field_path="candidate_evidence",
                        code="match_missing_candidate_evidence",
                        message=f"Finding '{req.requirement_id}' marked MATCH has no valid candidate evidence; downgraded to unknown",
                    )
                )
                finding_status = FindingStatus.UNKNOWN
            else:
                # Contradiction check: inspect cited fact statements for explicit limitations
                for cand_ref in valid_cand_refs:
                    stmt = fact_text_map.get(cand_ref.fact_id, "").lower()
                    if "introductory exposure only" in stmt or "grundkenntnisse" in stmt:
                        # If requirement is German C1 / fluent or senior experience, flag contradiction
                        req_lower = req.text.lower()
                        if "c1" in req_lower or "fluent" in req_lower or "fließend" in req_lower or "senior" in req_lower:
                            issues.append(
                                ValidationIssue(
                                    field_path="candidate_evidence",
                                    code="semantic_contradiction",
                                    message=f"Finding '{req.requirement_id}' claims MATCH but cited fact indicates introductory exposure only: '{stmt[:50]}'",
                                )
                            )

        elif prop.status == FindingStatus.UNKNOWN:
            if prop.candidate_evidence:
                issues.append(
                    ValidationIssue(
                        field_path="candidate_evidence",
                        code="invented_evidence_for_unknown",
                        message=f"Finding '{req.requirement_id}' marked UNKNOWN must not cite candidate evidence",
                    )
                )
                valid_cand_refs = []

        validated_findings.append(
            RequirementFinding(
                requirement_id=req.requirement_id,
                requirement_text=req.text,
                obligation=req.obligation,
                category=req.category,
                status=finding_status,
                candidate_evidence=valid_cand_refs,
                job_evidence=effective_job_ev,
                reason=prop.reason,
                score=prop.score,
            )
        )

    return validated_findings, issues
