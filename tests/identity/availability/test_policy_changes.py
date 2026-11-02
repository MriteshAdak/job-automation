"""Tests for policy changes, fingerprinting, and per-scope overrides (IDENTITY-02-S05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from job_automation.contracts.enums import FetchOutcome, InventorySemantics, PostingAvailability
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.service import AvailabilityService
from job_automation.identity.availability.settings import (
    AvailabilityPolicy,
    AvailabilityRuleSettings,
)
from job_automation.storage.engine import StorageEngine


class TestPolicyChanges:
    def test_scope_override_takes_effect_for_targeted_scope(self, tmp_path) -> None:
        db_path = tmp_path / "policy_override.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()

        # Custom policy: default threshold 5, but scope "fast_scope" has threshold 2 and grace 0
        policy = AvailabilityPolicy(
            default_rules=AvailabilityRuleSettings(consecutive_complete_misses=5, grace_seconds=86400.0),
            scope_overrides={
                "fast_scope": AvailabilityRuleSettings(consecutive_complete_misses=2, grace_seconds=0.0),
            },
        )
        service = AvailabilityService(storage=storage, policy=policy)

        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(hours=1)
        t2 = t0 + timedelta(hours=2)

        # Baseline with posting "99" in fast_scope
        m0 = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="fast_src",
            scope_id="fast_scope",
            start_time=t0,
            end_time=t0,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["99"],
        )
        service.process_manifest(m0)

        # Miss 1 at t1
        m1 = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="fast_src",
            scope_id="fast_scope",
            start_time=t1,
            end_time=t1,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=[],
        )
        service.process_manifest(m1)
        sk = SourceKey(provider="fast", board_id="src", source_posting_id="99")
        s1 = service.get_source_availability(sk, "fast_scope")
        assert s1 is not None
        assert s1.availability == PostingAvailability.NOT_SEEN
        assert s1.miss_count == 1

        # Miss 2 at t2: meets threshold 2 and grace 0 -> UNAVAILABLE!
        m2 = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="fast_src",
            scope_id="fast_scope",
            start_time=t2,
            end_time=t2,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=[],
        )
        service.process_manifest(m2)
        s2 = service.get_source_availability(sk, "fast_scope")
        assert s2 is not None
        assert s2.availability == PostingAvailability.UNAVAILABLE
        assert s2.miss_count == 2

