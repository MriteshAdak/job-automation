"""Tests for request admission, deliberate regeneration, and preflight availability checks (GEN-01-S05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import (
    GenerationProcessing,
    PostingAvailability,
)
from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.identity import CanonicalJob
from job_automation.generation.admission import GenerationAdmitter
from job_automation.generation.records import (
    GenerationRequestObservation,
    ObservationIssueCategory,
)
from job_automation.generation.request_mapping import (
    RequestFieldMapping,
    canonicalize_salesforce_id,
    derive_local_request_id,
)
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def engine(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "admission_test.db"
    eng = StorageEngine(db_path=db_path, raw_dir=tmp_path / "raw", artifacts_dir=tmp_path / "art")
    eng.initialize_schema()
    return eng


def _create_canonical_job(
    engine: StorageEngine,
    job_id: uuid.UUID,
    availability: PostingAvailability = PostingAvailability.ACTIVE,
) -> None:
    now_utc = datetime.now(timezone.utc)
    cjob = CanonicalJob(
        canonical_job_id=job_id,
        company_name="Acme Corp",
        availability=availability,
        current_revision_id=uuid.uuid4(),
        first_seen_at=now_utc,
        last_seen_at=now_utc,
    )
    engine.canonical_jobs.save_canonical_job(cjob)


class TestRequestAdmission:
    def test_admit_valid_observation_creates_pending_c13(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id, PostingAvailability.ACTIVE)
        admitter = GenerationAdmitter(engine=engine)

        sf_id = "a00111111111111"
        canon_sf_id = canonicalize_salesforce_id(sf_id)
        local_id = derive_local_request_id("00D000000000001EAA", canon_sf_id)

        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id,
            canonical_salesforce_id=canon_sf_id,
            client_request_key="client-1",
            local_request_id=local_id,
            canonical_job_id=job_id,
            remote_state="Pending",
            observed_at=datetime.now(timezone.utc),
            raw_record={
                "Id": sf_id,
                "Job__c": str(job_id),
                "Document_Type__c": "cv",
                "Language__c": "de",
                "Template_Id__c": "tmpl-1",
                "Context_Strategy__c": "json",
                "Allow_Unavailable_Job__c": False,
                "Status__c": "Pending",
            },
        )

        req, err = admitter.admit_observation(obs)
        assert err is None
        assert req is not None
        assert req.request_id == local_id
        assert req.state == GenerationProcessing.PENDING
        assert req.salesforce_request_id == canon_sf_id
        assert req.frozen_input_versions is None

    def test_repeated_admission_is_idempotent(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id, PostingAvailability.ACTIVE)
        admitter = GenerationAdmitter(engine=engine)

        sf_id = "a00111111111111"
        canon_sf_id = canonicalize_salesforce_id(sf_id)
        local_id = derive_local_request_id("00D000000000001EAA", canon_sf_id)

        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id,
            canonical_salesforce_id=canon_sf_id,
            local_request_id=local_id,
            canonical_job_id=job_id,
            remote_state="Pending",
            observed_at=datetime.now(timezone.utc),
            raw_record={
                "Id": sf_id,
                "Job__c": str(job_id),
                "Document_Type__c": "cv",
                "Status__c": "Pending",
            },
        )

        req1, err1 = admitter.admit_observation(obs)
        req2, err2 = admitter.admit_observation(obs)
        assert err1 is None
        assert err2 is None
        assert req1.request_id == req2.request_id

    def test_deliberate_regeneration_creates_distinct_request_with_linked_predecessor(
        self, engine: StorageEngine
    ) -> None:
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id, PostingAvailability.ACTIVE)
        admitter = GenerationAdmitter(engine=engine)

        # 1. First request
        sf_1 = "a00111111111111"
        canon_1 = canonicalize_salesforce_id(sf_1)
        obs1 = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_1,
            canonical_salesforce_id=canon_1,
            local_request_id=derive_local_request_id("00D000000000001EAA", canon_1),
            canonical_job_id=job_id,
            remote_state="Pending",
            observed_at=datetime.now(timezone.utc),
            raw_record={"Id": sf_1, "Job__c": str(job_id), "Document_Type__c": "cv"},
        )
        req1, _ = admitter.admit_observation(obs1)
        assert req1 is not None

        # 2. Deliberate regeneration (new remote record with Predecessor_Request__c pointing to first request)
        sf_2 = "a00222222222222"
        canon_2 = canonicalize_salesforce_id(sf_2)
        obs2 = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_2,
            canonical_salesforce_id=canon_2,
            local_request_id=derive_local_request_id("00D000000000001EAA", canon_2),
            canonical_job_id=job_id,
            remote_state="Pending",
            observed_at=datetime.now(timezone.utc),
            raw_record={
                "Id": sf_2,
                "Job__c": str(job_id),
                "Document_Type__c": "cv",
                "Predecessor_Request__c": canon_1,
            },
        )
        req2, _ = admitter.admit_observation(obs2)
        assert req2 is not None
        assert req2.request_id != req1.request_id
        assert req2.predecessor_request_id == req1.request_id

    def test_preflight_availability_failure_transitions_to_failed_without_running(
        self, engine: StorageEngine
    ) -> None:
        job_id = uuid.uuid4()
        # Job is confirmed UNAVAILABLE
        _create_canonical_job(engine, job_id, PostingAvailability.UNAVAILABLE)
        admitter = GenerationAdmitter(engine=engine)

        sf_id = "a00333333333333"
        canon_sf_id = canonicalize_salesforce_id(sf_id)
        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id,
            canonical_salesforce_id=canon_sf_id,
            local_request_id=derive_local_request_id("00D000000000001EAA", canon_sf_id),
            canonical_job_id=job_id,
            remote_state="Pending",
            observed_at=datetime.now(timezone.utc),
            raw_record={
                "Id": sf_id,
                "Job__c": str(job_id),
                "Document_Type__c": "cv",
                "Allow_Unavailable_Job__c": False,
            },
        )

        req, err = admitter.admit_observation(obs)
        assert req is not None
        assert req.state == GenerationProcessing.FAILED
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert err.details.get("reason_code") == "job_unavailable"

        # Check intent: must project Failed, never Running!
        intent = engine.generation_work.get_active_projection_intent(req.request_id)
        assert intent is not None
        assert intent.desired_remote_state == "Failed"
        assert intent.payload.get("Error_Reason__c") == "job_unavailable"

    def test_preflight_override_permits_unavailable_job(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id, PostingAvailability.UNAVAILABLE)
        admitter = GenerationAdmitter(engine=engine)

        sf_id = "a00444444444444"
        canon_sf_id = canonicalize_salesforce_id(sf_id)
        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id,
            canonical_salesforce_id=canon_sf_id,
            local_request_id=derive_local_request_id("00D000000000001EAA", canon_sf_id),
            canonical_job_id=job_id,
            remote_state="Pending",
            observed_at=datetime.now(timezone.utc),
            raw_record={
                "Id": sf_id,
                "Job__c": str(job_id),
                "Document_Type__c": "cv",
                "Allow_Unavailable_Job__c": True,  # Explicit candidate override!
            },
        )

        req, err = admitter.admit_observation(obs)
        assert err is None
        assert req is not None
        assert req.state == GenerationProcessing.PENDING
        assert req.allow_unavailable_job is True
