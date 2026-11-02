"""Tests for Salesforce request polling, pagination, and observation mapping (GEN-01-S04)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.identity import CanonicalJob
from job_automation.generation.polling import SalesforceGenerationRequestSource
from job_automation.generation.records import ObservationIssueCategory
from job_automation.generation.request_mapping import RequestFieldMapping
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


@pytest.fixture
def engine(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "polling_test.db"
    eng = StorageEngine(db_path=db_path, raw_dir=tmp_path / "raw", artifacts_dir=tmp_path / "art")
    eng.initialize_schema()
    return eng


def _create_canonical_job(engine: StorageEngine, job_id: uuid.UUID) -> None:
    now_utc = datetime.now(timezone.utc)
    cjob = CanonicalJob(
        canonical_job_id=job_id,
        company_name="Acme Corp",
        availability=PostingAvailability.ACTIVE,
        current_revision_id=uuid.uuid4(),
        first_seen_at=now_utc,
        last_seen_at=now_utc,
    )
    engine.canonical_jobs.save_canonical_job(cjob)


class TestRequestPolling:
    def test_poll_pending_lane_maps_observations(self, engine: StorageEngine) -> None:
        gateway = FakeSalesforceGatewayV2(org_id="00D000000000001EAA")
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        # Seed two Generation_Request__c records in fake gateway
        gateway.records["Generation_Request__c"] = {
            "a00111111111111": {
                "Id": "a00111111111111",
                "Job__c": str(job_id),
                "Document_Type__c": "cv",
                "Language__c": "de",
                "Template_Id__c": "template_standard",
                "Context_Strategy__c": "json",
                "Allow_Unavailable_Job__c": False,
                "Status__c": "Pending",
                "CreatedDate": datetime.now(timezone.utc).isoformat(),
            },
            "a00222222222222": {
                "Id": "a00222222222222",
                "Job__c": str(job_id),
                "Document_Type__c": "cover_letter",
                "Language__c": "en",
                "Template_Id__c": "template_modern",
                "Context_Strategy__c": "rag",
                "Allow_Unavailable_Job__c": True,
                "Status__c": "Pending",
                "CreatedDate": datetime.now(timezone.utc).isoformat(),
            },
        }

        source = SalesforceGenerationRequestSource(
            gateway=gateway,
            org_id="00D000000000001EAA",
            engine=engine,
        )

        observations, next_token, err = source.poll_requests(lane="pending", limit=10)
        assert err is None
        assert len(observations) == 2
        assert next_token is None

        obs1 = next(o for o in observations if o.salesforce_request_id == "a00111111111111")
        assert obs1.canonical_job_id == job_id
        assert obs1.issue_category is None
        assert obs1.canonical_salesforce_id == "a00111111111111AAA"

        # Verify observations are persisted in DB
        saved1 = engine.generation_work.get_observation(obs1.observation_id)
        assert saved1 is not None
        assert saved1.salesforce_request_id == "a00111111111111"

    def test_unmapped_job_is_quarantined_without_blocking_valid_neighbor(self, engine: StorageEngine) -> None:
        gateway = FakeSalesforceGatewayV2(org_id="00D000000000001EAA")
        valid_job_id = uuid.uuid4()
        missing_job_id = uuid.uuid4()
        _create_canonical_job(engine, valid_job_id)

        gateway.records["Generation_Request__c"] = {
            "a00111111111111": {
                "Id": "a00111111111111",
                "Job__c": str(missing_job_id),
                "Document_Type__c": "cv",
                "Status__c": "Pending",
                "CreatedDate": datetime.now(timezone.utc).isoformat(),
            },
            "a00222222222222": {
                "Id": "a00222222222222",
                "Job__c": str(valid_job_id),
                "Document_Type__c": "cv",
                "Status__c": "Pending",
                "CreatedDate": datetime.now(timezone.utc).isoformat(),
            },
        }

        source = SalesforceGenerationRequestSource(
            gateway=gateway,
            org_id="00D000000000001EAA",
            engine=engine,
        )

        observations, _, err = source.poll_requests(lane="pending")
        assert err is None
        assert len(observations) == 2

        bad_obs = next(o for o in observations if o.salesforce_request_id == "a00111111111111")
        assert bad_obs.issue_category == ObservationIssueCategory.UNMAPPED_JOB
        assert "not found in database" in bad_obs.issue_message

        good_obs = next(o for o in observations if o.salesforce_request_id == "a00222222222222")
        assert good_obs.issue_category is None
        assert good_obs.canonical_job_id == valid_job_id

    def test_invalid_identifier_rejected_on_source_creation(self) -> None:
        gateway = FakeSalesforceGatewayV2()
        bad_mapping = RequestFieldMapping(request_object="Generation_Request__c; DROP TABLE runs;")
        with pytest.raises(ValueError, match="Invalid Salesforce request_object"):
            SalesforceGenerationRequestSource(gateway=gateway, mapping=bad_mapping)

