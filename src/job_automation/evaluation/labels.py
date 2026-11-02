"""Gold label verification and model finding alignment (EVAL-01-S02).

Enforces:
- Every gold candidate fact ID exists in the candidate profile snapshot.
- Every gold fact has 'assessment' in allowed_uses (restricted facts cannot be gold for assessment).
- No orphan parent facts.
- Source spans in job evidence exist as verbatim substrings in the posting text.
- Rigorous scoring of sufficient evidence sets (multi-fact conjunctions) vs partial or unsupported citations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence
from pydantic import Field

from job_automation.contracts.assessment import RequirementFinding
from job_automation.contracts.enums import FindingStatus
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.profile import ProfileSnapshot
from job_automation.evaluation.errors import InvalidCorpusError
from job_automation.evaluation.records import (
    GoldLabelRevision,
    GoldRequirementLabel,
)


@dataclass
class FindingAlignmentResult:
    """Detailed evaluation of a model finding against a gold requirement label."""

    requirement_id: str
    gold_status: FindingStatus
    model_status: FindingStatus | None
    status_matches: bool
    cited_fact_ids: list[str]
    has_sufficient_support: bool
    sufficient_set_matched: list[str] | None
    has_contradiction: bool
    has_unadmitted_or_unknown_citation: bool
    is_unsupported_claim: bool
    notes: list[str] = field(default_factory=list)


def validate_gold_label_integrity(
    gold_label: GoldLabelRevision,
    profile: ProfileSnapshot,
    posting: NormalizedPosting,
) -> None:
    """Validate that gold annotations strictly respect profile truth and posting text.

    Raises InvalidCorpusError if:
    - Any cited fact ID is unknown in candidate profile.
    - Any cited fact is restricted (lacks 'assessment' in allowed_uses).
    - An evidence fact has an orphan parent.
    - A source span quotation is absent from posting description/title.
    """
    known_facts = {str(f.fact_id): f for f in profile.evidence_records}

    # Verify profile facts
    for req in gold_label.requirements:
        for s_set in req.sufficient_evidence_sets:
            for fid in s_set:
                if fid not in known_facts:
                    raise InvalidCorpusError(
                        f"Gold label for requirement '{req.requirement_id}' cites unknown fact '{fid}'"
                    )
                fact = known_facts[fid]
                if "assessment" not in fact.allowed_uses:
                    raise InvalidCorpusError(
                        f"Gold label cites fact '{fid}' which lacks 'assessment' in allowed_uses (allowed: {fact.allowed_uses})"
                    )
                if fact.parent_id is not None and str(fact.parent_id) not in known_facts:
                    raise InvalidCorpusError(
                        f"Fact '{fid}' has orphan parent_id '{fact.parent_id}' not found in profile"
                    )

        for fid in req.contradictory_fact_ids:
            if fid not in known_facts:
                raise InvalidCorpusError(
                    f"Gold label contradictory fact '{fid}' unknown in candidate profile"
                )

        # Verify source spans in posting text
        posting_text = f"{posting.title}\n{posting.description_clean}"
        for span in req.source_spans:
            if span.quotation and span.quotation not in posting_text:
                raise InvalidCorpusError(
                    f"Job evidence quotation '{span.quotation}' for requirement '{req.requirement_id}' "
                    f"not found in posting '{posting.title}'"
                )


def align_finding_to_gold(
    finding: RequirementFinding | None,
    gold_req: GoldRequirementLabel,
    admitted_fact_ids: set[str] | None = None,
) -> FindingAlignmentResult:
    """Align a model requirement finding against the gold ground truth label."""
    if finding is None:
        return FindingAlignmentResult(
            requirement_id=gold_req.requirement_id,
            gold_status=gold_req.gold_status,
            model_status=None,
            status_matches=False,
            cited_fact_ids=[],
            has_sufficient_support=False,
            sufficient_set_matched=None,
            has_contradiction=False,
            has_unadmitted_or_unknown_citation=False,
            is_unsupported_claim=False,
            notes=["No finding returned by model for requirement"],
        )

    model_status = finding.status
    status_matches = (model_status == gold_req.gold_status)
    cited_ids = [str(ev.fact_id) for ev in finding.candidate_evidence]
    cited_set = set(cited_ids)

    # Check sufficient evidence sets
    has_sufficient = False
    matched_set: list[str] | None = None

    if gold_req.sufficient_evidence_sets:
        for s_set in gold_req.sufficient_evidence_sets:
            # All facts in the set must be cited
            if set(s_set).issubset(cited_set):
                has_sufficient = True
                matched_set = s_set
                break
    elif gold_req.gold_status == FindingStatus.GAP and not cited_set:
        # Expected gap with no evidence cited is sufficient
        has_sufficient = True
    elif gold_req.gold_status == FindingStatus.UNKNOWN and not cited_set:
        # Expected unknown with no evidence cited is sufficient
        has_sufficient = True

    # Check contradictory facts cited
    has_contradiction = any(fid in cited_set for fid in gold_req.contradictory_fact_ids)

    # Check unadmitted facts
    has_unadmitted = False
    if admitted_fact_ids is not None:
        has_unadmitted = any(fid not in admitted_fact_ids for fid in cited_set)

    # Unsupported claim: claiming MATCH without any evidence or citing completely unadmitted facts
    is_unsupported = False
    if model_status == FindingStatus.MATCH:
        if not cited_set or has_unadmitted:
            is_unsupported = True

    notes = []
    if not status_matches:
        notes.append(f"Status mismatch: expected {gold_req.gold_status.value}, got {model_status.value}")
    if model_status == FindingStatus.MATCH and not has_sufficient:
        notes.append("Incomplete evidence: cited facts do not satisfy any sufficient evidence set")
    if has_contradiction:
        notes.append("Contradictory evidence: model cited facts that contradict the requirement")
    if has_unadmitted:
        notes.append("Unadmitted citation: cited facts were not admitted into context bundle")

    return FindingAlignmentResult(
        requirement_id=gold_req.requirement_id,
        gold_status=gold_req.gold_status,
        model_status=model_status,
        status_matches=status_matches,
        cited_fact_ids=cited_ids,
        has_sufficient_support=has_sufficient and status_matches and not has_contradiction,
        sufficient_set_matched=matched_set,
        has_contradiction=has_contradiction,
        has_unadmitted_or_unknown_citation=has_unadmitted,
        is_unsupported_claim=is_unsupported,
        notes=notes,
    )
