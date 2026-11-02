"""Resolution of exact historical C08 candidate evidence references.

Guarantees:
- Resolves citations against the exact historical snapshot version cited.
- Never falls back to the current version or fuzzy matches.
- Strict discrimination between candidate and job evidence references.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from job_automation.contracts.evidence import CandidateEvidenceReference, JobEvidenceReference
from job_automation.contracts.profile import CandidateFact
from job_automation.profile.errors import FactNotFoundError, ProfileNotFoundError, ProfileValidationError

if TYPE_CHECKING:
    from job_automation.storage.repositories.profiles import ProfileRepository


def resolve_candidate_evidence_reference(
    repo: ProfileRepository,
    reference: CandidateEvidenceReference | dict[str, Any] | tuple[str, uuid.UUID],
) -> CandidateFact:
    """Resolve a candidate evidence citation to the exact approved fact in that version."""
    if isinstance(reference, JobEvidenceReference):
        raise ProfileValidationError(
            "Cannot resolve job evidence reference via candidate profile resolver",
            code="INVALID_REFERENCE_TYPE",
        )

    if isinstance(reference, CandidateEvidenceReference):
        version = reference.profile_version
        fact_id = reference.fact_id
    elif isinstance(reference, tuple):
        version, fact_id = reference
    elif isinstance(reference, dict):
        if reference.get("source_kind") == "job":
            raise ProfileValidationError(
                "Cannot resolve job evidence reference via candidate profile resolver",
                code="INVALID_REFERENCE_TYPE",
            )
        try:
            version = str(reference["profile_version"])
            fact_id = (
                reference["fact_id"]
                if isinstance(reference["fact_id"], uuid.UUID)
                else uuid.UUID(str(reference["fact_id"]))
            )
        except (KeyError, ValueError) as err:
            raise ProfileValidationError(
                f"Malformed candidate evidence reference dict: {err}",
                code="MALFORMED_REFERENCE",
            ) from err
    else:
        raise ProfileValidationError(
            f"Unsupported reference format: {type(reference).__name__}",
            code="UNSUPPORTED_REFERENCE_FORMAT",
        )

    # 1. Verify version exists
    snapshot = repo.get_snapshot(version)
    if snapshot is None:
        raise ProfileNotFoundError(f"Referenced profile version '{version}' does not exist")

    # 2. Look up exact fact in that version
    fact = repo.get_fact(version, fact_id)
    if fact is None:
        raise FactNotFoundError(
            f"Fact '{fact_id}' not found in referenced profile version '{version}'"
        )

    return fact
