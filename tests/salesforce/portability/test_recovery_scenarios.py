"""Tests for candidate recovery package generation, replacement-org remapping, and conflict reconciliation (SF-04-S05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest

from job_automation.contracts.identity import CanonicalJob
from job_automation.operations.remote_recovery import (
    generate_candidate_recovery_package,
    reconcile_recovery_conflicts,
)
from job_automation.salesforce.sync_records import CandidateFieldSnapshot
from job_automation.salesforce.sync_settings import SyncMappingConfig
from job_automation.storage.engine import StorageEngine


class TestRecoveryScenarios:
    @pytest.fixture
    def populated_engine(self, tmp_path: Path) -> dict[str, Any]:
        db_path = tmp_path / "recovery_test.db"
        engine = StorageEngine(db_path=db_path)
        engine.migrate()

        c_uuid = uuid.uuid4()
        j_uuid = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)

        engine.canonical_jobs.save_canonical_job(
            CanonicalJob(
                canonical_job_id=j_uuid,
                canonical_company_id=c_uuid,
                company_name="Bosch GmbH",
                current_revision_id=uuid.uuid4(),
                first_seen_at=now_dt,
                last_seen_at=now_dt,
            )
        )

        engine.candidate_snapshots.save_snapshot(
            CandidateFieldSnapshot(
                snapshot_id=uuid.uuid4(),
                org_id="00D000000000001",
                canonical_job_id=j_uuid,
                remote_record_id="a00Job001AAA",
                mapping_version="1.0",
                snapshot_hash="sha256:111",
                candidate_fields={
                    "Application_Progress__c": "Interviewing",
                    "Candidate_Notes__c": "Zweites Interview am Freitag (Vorbereitung nötig).",
                    "Candidate_Decision__c": "Top 1",
                    "Follow_Up_Date__c": "2026-11-06",
                    "Interview_Date__c": "2026-11-06T10:00:00Z",
                },
                source_modification_token="2026-11-01T10:00:00Z",
                observed_at=now_dt,
                created_at=now_dt,
            )
        )

        config = SyncMappingConfig(expected_org_id="00D000000000001")
        return {"engine": engine, "config": config, "job_uuid": j_uuid, "comp_uuid": c_uuid}

    def test_same_org_recovery_preserves_remote_ids_and_companies(
        self, populated_engine: dict[str, Any]
    ) -> None:
        """Same-org recovery includes Company parents and retains remote Salesforce record IDs."""
        engine = populated_engine["engine"]
        config = populated_engine["config"]
        j_uuid = str(populated_engine["job_uuid"])
        c_uuid = str(populated_engine["comp_uuid"])

        pkg = generate_candidate_recovery_package(engine, config)

        assert pkg["is_replacement_org"] is False
        assert pkg["source_org_id"] == "00D000000000001"
        assert pkg["target_org_id"] == "00D000000000001"
        assert pkg["total_records"] == 1
        assert pkg["total_companies"] == 1

        comp_entry = pkg["companies"][0]
        assert comp_entry["canonical_company_id"] == c_uuid
        assert comp_entry["company_name"] == "Bosch GmbH"

        job_entry = pkg["records"][0]
        assert job_entry["canonical_job_id"] == j_uuid
        assert job_entry["canonical_company_id"] == c_uuid
        assert job_entry["remote_record_id"] == "a00Job001AAA"
        assert "Vorbereitung nötig" in job_entry["candidate_fields"]["Candidate_Notes__c"]

    def test_replacement_org_recovery_clears_remote_ids(
        self, populated_engine: dict[str, Any]
    ) -> None:
        """Replacement-org recovery marks remote IDs as None while preserving canonical UUIDs."""
        engine = populated_engine["engine"]
        config = populated_engine["config"]
        j_uuid = str(populated_engine["job_uuid"])
        c_uuid = str(populated_engine["comp_uuid"])

        pkg = generate_candidate_recovery_package(
            engine, config, target_org_id="00DReplacementOrg01"
        )

        assert pkg["is_replacement_org"] is True
        assert pkg["source_org_id"] == "00D000000000001"
        assert pkg["target_org_id"] == "00DReplacementOrg01"
        assert pkg["records"][0]["canonical_job_id"] == j_uuid
        assert pkg["records"][0]["canonical_company_id"] == c_uuid
        assert pkg["records"][0]["remote_record_id"] is None

    def test_reconcile_newer_remote_edit_takes_precedence(
        self, populated_engine: dict[str, Any]
    ) -> None:
        """When candidate made newer edits in Salesforce, conflict is flagged with retain_newer_remote_edit."""
        engine = populated_engine["engine"]
        config = populated_engine["config"]
        j_uuid = str(populated_engine["job_uuid"])

        pkg = generate_candidate_recovery_package(engine, config)

        # Simulate remote record with newer SystemModstamp
        current_remote = {
            j_uuid: {
                "Id": "a00Job001AAA",
                "SystemModstamp": "2026-11-01T14:30:00Z",  # Newer than 10:00:00Z
                "Application_Progress__c": "Offer",
                "Candidate_Notes__c": "Angebot erhalten! Details prüfen.",
                "Candidate_Decision__c": "Angenommen",
                "Follow_Up_Date__c": "2026-11-08",
                "Interview_Date__c": "2026-11-06T10:00:00Z",
            }
        }

        report = reconcile_recovery_conflicts(pkg, current_remote)

        assert report["conflicts_retained_remote"] == 1
        assert report["records_to_restore"] == 0
        assert report["unchanged_records"] == 0
        detail = report["conflict_details"][0]
        assert detail["canonical_job_id"] == j_uuid
        assert detail["resolution"] == "retain_newer_remote_edit"
        assert detail["remote_fields"]["Application_Progress__c"] == "Offer"

    def test_reconcile_equal_token_diverging_fields_requires_review(
        self, populated_engine: dict[str, Any]
    ) -> None:
        """When tokens are identical but fields diverge, conflict is flagged for review."""
        engine = populated_engine["engine"]
        config = populated_engine["config"]
        j_uuid = str(populated_engine["job_uuid"])

        pkg = generate_candidate_recovery_package(engine, config)

        # Same token, but differing notes
        current_remote = {
            j_uuid: {
                "Id": "a00Job001AAA",
                "SystemModstamp": "2026-11-01T10:00:00Z",  # Identical token
                "Application_Progress__c": "Interviewing",
                "Candidate_Notes__c": "Diverging notes modified concurrently",
                "Candidate_Decision__c": "Top 1",
                "Follow_Up_Date__c": "2026-11-06",
                "Interview_Date__c": "2026-11-06T10:00:00Z",
            }
        }

        report = reconcile_recovery_conflicts(pkg, current_remote)
        assert len(report["conflict_details"]) == 1
        assert report["conflict_details"][0]["resolution"] == "requires_review_diverging_fields"

