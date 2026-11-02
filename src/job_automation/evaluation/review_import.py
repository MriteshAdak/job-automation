"""Review correction import and validation (EVAL-01-S06).

Enforces:
- Candidate profile truth is IMMUTABLE: new facts require PROFILE-01 approval.
- Search policy is IMMUTABLE: preference changes require POLICY-01 approval.
- Supporting evidence citations must reference approved facts with 'assessment' allowed_uses.
- Idempotency: re-importing the same correction does not duplicate records.
- Conflict detection: conflicting edits on the same target require explicit adjudication.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from job_automation.contracts.profile import ProfileSnapshot
from job_automation.contracts.policy import SearchPolicy
from job_automation.evaluation.errors import (
    InputTamperingError,
    InvalidCorpusError,
    UnadjudicatedReviewError,
)
from job_automation.evaluation.records import ReviewCorrection
from job_automation.evaluation.repository import EvaluationRepository


def import_review_corrections(
    corrections_source: list[dict[str, Any]] | Path | str,
    repository: EvaluationRepository,
    profile: ProfileSnapshot,
    policy: SearchPolicy,
) -> list[ReviewCorrection]:
    """Import and validate human reviewer corrections.

    Raises:
    - InputTamperingError: If an import attempts to mutate profile facts or search policy.
    - InvalidCorpusError: If supporting evidence references unknown/restricted facts or wrong profile version.
    - UnadjudicatedReviewError: If conflicting edits exist without explicit adjudication.
    """
    if isinstance(corrections_source, (Path, str)):
        path = Path(corrections_source)
        with open(path, "r", encoding="utf-8") as f:
            raw_content = json.load(f)
            if isinstance(raw_content, dict) and "corrections" in raw_content:
                items = raw_content["corrections"]
            elif isinstance(raw_content, list):
                items = raw_content
            else:
                items = [raw_content]
    else:
        items = corrections_source

    known_facts = {str(f.fact_id): f for f in profile.evidence_records}
    imported_corrections: list[ReviewCorrection] = []

    for item in items:
        # 1. Guard against candidate truth tampering
        if any(k in item for k in ("mutate_profile", "profile_update", "add_candidate_fact")):
            raise InputTamperingError(
                "Review corrections cannot mutate candidate profile truth. Fact additions require PROFILE-01 approval."
            )
        if item.get("target_type") in ("profile_fact", "candidate_profile"):
            raise InputTamperingError(
                "Direct profile modifications via review import are forbidden. Candidate facts must be approved in PROFILE-01."
            )

        # 2. Guard against search policy tampering
        if any(k in item for k in ("mutate_policy", "policy_update", "update_rules")):
            raise InputTamperingError(
                "Review corrections cannot mutate search policy. Policy updates require POLICY-01 approval."
            )
        if item.get("target_type") in ("policy_rule", "search_policy"):
            raise InputTamperingError(
                "Direct policy modifications via review import are forbidden. Changes require POLICY-01 approval."
            )

        correction = ReviewCorrection.model_validate(item)

        # 3. Validate supporting candidate evidence citations
        for ev in correction.supporting_evidence:
            if ev.profile_version != profile.profile_version:
                raise InvalidCorpusError(
                    f"Evidence citation uses profile version '{ev.profile_version}', "
                    f"but active profile version is '{profile.profile_version}'"
                )
            fid_str = str(ev.fact_id)
            if fid_str not in known_facts:
                raise InvalidCorpusError(
                    f"Supporting evidence cites unknown candidate fact ID '{fid_str}'"
                )
            fact = known_facts[fid_str]
            if "assessment" not in fact.allowed_uses:
                raise InvalidCorpusError(
                    f"Supporting evidence cites fact '{fid_str}' which lacks 'assessment' in allowed_uses"
                )

        # 4. Check idempotency & conflict resolution against existing records
        existing = repository.list_corrections(case_id=correction.case_id)
        is_duplicate = False
        for ex in existing:
            if ex.correction_id == correction.correction_id:
                is_duplicate = True
                break
            if (
                ex.case_id == correction.case_id
                and ex.target_type == correction.target_type
            ):
                if ex.new_value == correction.new_value:
                    is_duplicate = True
                    break
                # Conflicting edits
                if (
                    ex.adjudication_status != "adjudicated"
                    and correction.adjudication_status != "adjudicated"
                ):
                    raise UnadjudicatedReviewError(
                        f"Conflicting unadjudicated corrections detected for case '{correction.case_id}' "
                        f"and target '{correction.target_type}'. Explicit adjudication is required."
                    )

        if not is_duplicate:
            repository.save_correction(correction)
            imported_corrections.append(correction)

    return imported_corrections
