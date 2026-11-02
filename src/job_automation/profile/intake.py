"""Intake processing for manual candidate history, corrections, and provenance.

Enforces:
- Stable candidate and fact UUID assignments.
- Preservation of fact IDs across corrections.
- Rejection of imported approval authority (intake produces unapproved drafts only).
- Immutable content digest calculation.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.primitives import MoneyAmount, PrecisionDate
from job_automation.contracts.profile import CandidateEligibility
from job_automation.profile.errors import ProfileValidationError
from job_automation.profile.models import (
    DraftFact,
    DraftProfile,
    ProvenanceRecord,
)
from job_automation.profile.validation import validate_draft


def parse_draft_intake(
    data: dict[str, Any] | str,
    candidate_id_override: uuid.UUID | None = None,
    draft_id_override: uuid.UUID | None = None,
) -> DraftProfile:
    """Parse raw structured input into an unapproved DraftProfile.

    Any 'is_approved' or approval metadata in the payload is deliberately ignored:
    intake can never produce an approved profile snapshot.
    """
    if isinstance(data, str):
        try:
            raw_dict = json.loads(data)
        except Exception as err:
            raise ProfileValidationError(
                f"Malformed JSON in profile intake: {err}",
                code="MALFORMED_JSON",
            ) from err
    else:
        raw_dict = data

    if not isinstance(raw_dict, dict):
        raise ProfileValidationError(
            "Profile intake data must be a JSON object / dict",
            code="INVALID_ROOT_TYPE",
        )

    # 1. Resolve candidate UUID
    if candidate_id_override is not None:
        candidate_id = candidate_id_override
    elif "candidate_id" in raw_dict and raw_dict["candidate_id"]:
        try:
            candidate_id = uuid.UUID(str(raw_dict["candidate_id"]))
        except ValueError as err:
            raise ProfileValidationError(
                f"Invalid candidate_id UUID format: '{raw_dict['candidate_id']}'",
                field_path="candidate_id",
                code="INVALID_UUID",
            ) from err
    else:
        candidate_id = uuid.uuid4()

    draft_id = draft_id_override or (
        uuid.UUID(str(raw_dict["draft_id"]))
        if "draft_id" in raw_dict and raw_dict["draft_id"]
        else uuid.uuid4()
    )

    base_version = raw_dict.get("base_profile_version")

    # 2. Parse eligibility
    elig_raw = raw_dict.get("proposed_eligibility") or raw_dict.get("explicit_eligibility") or {}
    try:
        eligibility = CandidateEligibility.model_validate(elig_raw)
    except Exception as err:
        raise ProfileValidationError(
            f"Invalid candidate eligibility format: {err}",
            field_path="proposed_eligibility",
            code="INVALID_ELIGIBILITY",
        ) from err

    # 3. Parse facts with stable ID logic
    facts_raw = raw_dict.get("facts") or raw_dict.get("evidence_records") or []
    if not isinstance(facts_raw, list):
        raise ProfileValidationError(
            "'facts' must be a list of candidate fact records",
            field_path="facts",
            code="INVALID_FACTS_TYPE",
        )

    seen_fids: set[uuid.UUID] = set()
    parsed_facts: list[DraftFact] = []

    for idx, f_data in enumerate(facts_raw):
        if not isinstance(f_data, dict):
            raise ProfileValidationError(
                f"Fact at index {idx} must be a dictionary",
                field_path=f"facts[{idx}]",
                code="INVALID_FACT_ITEM",
            )

        # Stable fact UUID: preserve existing if present, assign new if absent
        if "fact_id" in f_data and f_data["fact_id"]:
            try:
                fid = uuid.UUID(str(f_data["fact_id"]))
            except ValueError as err:
                raise ProfileValidationError(
                    f"Invalid fact_id UUID at index {idx}: '{f_data['fact_id']}'",
                    field_path=f"facts[{idx}].fact_id",
                    code="INVALID_UUID",
                ) from err
        else:
            fid = uuid.uuid4()

        if fid in seen_fids:
            raise ProfileValidationError(
                f"Duplicate fact_id '{fid}' in intake payload",
                field_path=f"facts[{idx}].fact_id",
                code="DUPLICATE_FACT_ID",
            )
        seen_fids.add(fid)

        parent_id: uuid.UUID | None = None
        if f_data.get("parent_id"):
            try:
                parent_id = uuid.UUID(str(f_data["parent_id"]))
            except ValueError as err:
                raise ProfileValidationError(
                    f"Invalid parent_id UUID at index {idx}: '{f_data['parent_id']}'",
                    field_path=f"facts[{idx}].parent_id",
                    code="INVALID_UUID",
                ) from err

        # Kind
        kind_str = f_data.get("kind", "employment")
        try:
            kind = EvidenceFactKind(kind_str)
        except ValueError as err:
            raise ProfileValidationError(
                f"Unknown EvidenceFactKind '{kind_str}' at index {idx}",
                field_path=f"facts[{idx}].kind",
                code="INVALID_KIND",
            ) from err

        # Dates
        start_date = (
            PrecisionDate.model_validate(f_data["start_date"])
            if f_data.get("start_date")
            else None
        )
        end_date = (
            PrecisionDate.model_validate(f_data["end_date"])
            if f_data.get("end_date")
            else None
        )

        # Allowed uses: defaults to empty list (no downstream use) if not explicitly supplied
        allowed_uses = list(f_data.get("allowed_uses") or [])

        # Build DraftFact
        try:
            draft_fact = DraftFact(
                fact_id=fid,
                kind=kind,
                parent_id=parent_id,
                title=str(f_data.get("title", "")).strip(),
                organization=f_data.get("organization"),
                start_date=start_date,
                end_date=end_date,
                is_ongoing=bool(f_data.get("is_ongoing", False)),
                claims=list(f_data.get("claims") or []),
                skills=list(f_data.get("skills") or []),
                metrics=list(f_data.get("metrics") or []),
                provenance_id=f_data.get("provenance_id"),
                provenance_summary=str(f_data.get("provenance_summary") or f_data.get("provenance") or ""),
                allowed_uses=allowed_uses,
            )
            parsed_facts.append(draft_fact)
        except Exception as err:
            raise ProfileValidationError(
                f"Failed to validate fact at index {idx}: {err}",
                field_path=f"facts[{idx}]",
                code="FACT_VALIDATION_ERROR",
            ) from err

    # 4. Parse provenance records if present
    prov_raw = raw_dict.get("provenance_records") or []
    parsed_prov: list[ProvenanceRecord] = []
    for idx, p_data in enumerate(prov_raw):
        if isinstance(p_data, dict):
            try:
                p_copy = dict(p_data)
                if "candidate_id" not in p_copy:
                    p_copy["candidate_id"] = candidate_id
                parsed_prov.append(ProvenanceRecord.model_validate(p_copy))
            except Exception as err:
                raise ProfileValidationError(
                    f"Invalid provenance record at index {idx}: {err}",
                    field_path=f"provenance_records[{idx}]",
                    code="INVALID_PROVENANCE",
                ) from err

    now_utc = datetime.now(timezone.utc)
    notes = raw_dict.get("notes")

    draft = DraftProfile(
        draft_id=draft_id,
        candidate_id=candidate_id,
        base_profile_version=base_version,
        proposed_eligibility=eligibility,
        facts=parsed_facts,
        provenance_records=parsed_prov,
        notes=notes,
        created_at=now_utc,
        updated_at=now_utc,
    )
    # 5. Invariant validation
    validate_draft(draft)
    return draft
