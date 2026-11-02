"""Consumer validity verification for CONTEXT-02 evidence chunks."""

from __future__ import annotations

import uuid

from job_automation.contracts.evidence_chunks import ChunkSet


def validate_chunk_binding(
    chunk_set: ChunkSet,
    expected_candidate_id: uuid.UUID,
    expected_profile_version: str,
    expected_purpose: str,
    expected_settings_fingerprint: str | None = None,
) -> tuple[bool, str | None]:
    """Verify that a ChunkSet satisfies exact consumer binding expectations.

    Prevents downstream consumers from serving manifests built for a different
    candidate, an older profile version, or an incompatible purpose.
    """
    if chunk_set.candidate_id != expected_candidate_id:
        return (
            False,
            f"Candidate mismatch: manifest is for '{chunk_set.candidate_id}', expected '{expected_candidate_id}'",
        )

    if chunk_set.profile_version != expected_profile_version:
        return (
            False,
            f"Profile version mismatch: manifest is for '{chunk_set.profile_version}', expected '{expected_profile_version}'",
        )

    if chunk_set.purpose != expected_purpose:
        return (
            False,
            f"Purpose mismatch: manifest is for '{chunk_set.purpose}', expected '{expected_purpose}'",
        )

    if expected_settings_fingerprint is not None:
        if chunk_set.settings_fingerprint != expected_settings_fingerprint:
            return (
                False,
                f"Settings fingerprint mismatch: manifest has '{chunk_set.settings_fingerprint}', expected '{expected_settings_fingerprint}'",
            )

    return (True, None)

