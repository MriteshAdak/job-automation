"""Tests for safe diagnostic redaction and inspectable availability outputs (IDENTITY-02-S07)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.inspection import CanonicalAvailabilitySummary
from job_automation.identity.availability.models import (
    AvailabilityDecision,
    SourcePostingAvailability,
)


class TestSafeDiagnostics:
    def test_canonical_availability_summary_redacts_credentials(self) -> None:
        now = datetime.now(timezone.utc)
        cid = uuid.uuid4()
        sk = SourceKey(provider="gh", board_id="acme", source_posting_id="101")
        item = SourcePostingAvailability(
            source_key=sk,
            scope_id="gh_acme",
            canonical_job_id=cid,
            availability=PostingAvailability.ACTIVE,
            first_seen_at=now,
            last_seen_at=now,
        )
        decision = AvailabilityDecision(
            source_key=sk,
            canonical_job_id=cid,
            scope_id="gh_acme",
            from_availability=PostingAvailability.UNKNOWN,
            to_availability=PostingAvailability.ACTIVE,
            reason="sighting_observed",
            miss_count=0,
            event_time=now,
        )

        summary = CanonicalAvailabilitySummary(
            canonical_job_id=cid,
            company_name="Acme Corp",
            canonical_availability=PostingAvailability.ACTIVE,
            first_seen_at=now,
            last_seen_at=now,
            explanation="linked_source_active (1/1 active)",
            linked_sources_count=1,
            active_sources_count=1,
            source_states=[item],
            recent_decisions=[decision],
        )

        dumped_json = summary.model_dump_json()
        assert "password" not in dumped_json
        assert "api_key" not in dumped_json
        assert "secret" not in dumped_json
        assert summary.explanation == "linked_source_active (1/1 active)"

