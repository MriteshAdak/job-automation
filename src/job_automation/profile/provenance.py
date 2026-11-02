"""Helpers for creating and managing candidate evidence provenance records."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from job_automation.profile.models import ProvenanceRecord


def create_provenance_record(
    candidate_id: uuid.UUID,
    source_type: Literal["document", "attestation", "import"],
    locator: str,
    provenance_id: str | None = None,
    content_hash: str | None = None,
    file_path: str | None = None,
    notes: str | None = None,
    captured_at: datetime | None = None,
) -> ProvenanceRecord:
    """Create a structured, validated ProvenanceRecord."""
    now_utc = captured_at or datetime.now(timezone.utc)
    pid = provenance_id or f"prov_{uuid.uuid4().hex[:12]}"

    return ProvenanceRecord(
        provenance_id=pid,
        candidate_id=candidate_id,
        source_type=source_type,
        locator=locator,
        content_hash=content_hash,
        file_path=file_path,
        captured_at=now_utc,
        notes=notes,
    )

