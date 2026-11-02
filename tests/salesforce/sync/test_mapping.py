"""Field mapping tests for SYNC-01 (SYNC-01-S02)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    PostingAvailability,
)
from job_automation.salesforce.sync_mapping import (
    build_company_external_id,
    build_company_payload,
    build_job_external_id,
    build_job_payload,
    build_sync_payload,
)
from job_automation.salesforce.sync_records import (
    PublicationPurpose,
    SyncSubmission,
)
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "salesforce" / "sync"
CONFIG_FILE = Path(__file__).resolve().parent.parent.parent.parent / "config" / "sync.example.json"


def load_c11_fixture(filename: str) -> Assessment:
    path = FIXTURES_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Assessment.model_validate(data)


class TestSyncMapping:
    @pytest.fixture
    def default_config(self) -> SyncMappingConfig:
        return load_sync_mapping_config(CONFIG_FILE)

    def test_load_example_config(self, default_config: SyncMappingConfig) -> None:
        assert default_config.job_object == "Job__c"
        assert default_config.company_object == "Company__c"
        assert default_config.title_field == "Name"
        assert default_config.availability_field == "Availability__c"
        assert default_config.disposition_field == "Assessment_Disposition__c"
        assert len(default_config.candidate_fields) >= 4
        assert default_config.compute_hash() is not None

    def test_build_sync_payload(self) -> None:
        asm = load_c11_fixture("rules_only_eligible.json")
        now_dt = datetime.now(timezone.utc)
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-1",
            job_title="Full Stack Engineer",
            company_name="Innovatech GmbH",
            canonical_company_id=uuid.uuid4(),
            source_urls=["https://example.com/posting/1", "https://example.com/posting/2"],
            availability=PostingAvailability.ACTIVE,
        )

        payload = build_sync_payload(sub)
        assert payload.canonical_job_id == asm.canonical_job_id
        assert payload.job_title == "Full Stack Engineer"
        assert payload.company_name == "Innovatech GmbH"
        assert payload.availability == PostingAvailability.ACTIVE
        assert payload.assessment_disposition == AssessmentDisposition.ELIGIBLE
        assert payload.relevance_score is None
        assert payload.score_scale is None
        assert len(payload.source_urls) == 2

    def test_build_company_payload(self, default_config: SyncMappingConfig) -> None:
        asm = load_c11_fixture("rules_only_eligible.json")
        now_dt = datetime.now(timezone.utc)
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-1",
            job_title="Dev",
            company_name="MegaCorp AG",
            canonical_company_id=uuid.uuid4(),
        )

        comp_payload = build_company_payload(sub, default_config)
        assert comp_payload == {"Name": "MegaCorp AG"}

    def test_build_job_payload_with_rules_assessment_clears_score(
        self, default_config: SyncMappingConfig
    ) -> None:
        asm = load_c11_fixture("rules_only_eligible.json")
        now_dt = datetime.now(timezone.utc)
        comp_id = uuid.uuid4()
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-1",
            job_title="Senior Python Architect",
            company_name="Innovatech GmbH",
            canonical_company_id=comp_id,
            source_urls=["https://example.com/jobs/1"],
            availability=PostingAvailability.ACTIVE,
        )

        job_payload = build_job_payload(
            submission=sub,
            config=default_config,
            sequence_number=1,
            marker="marker-job-001",
            company_salesforce_id="001000000000001AAA",
        )

        assert job_payload[default_config.title_field] == "Senior Python Architect"
        assert job_payload[default_config.availability_field] == "Active"
        assert job_payload[default_config.disposition_field] == "Eligible"
        assert job_payload[default_config.reason_field] == "All deterministic hard criteria passed"
        # Crucial for LLM -> rules transitions: score must be explicitly cleared to None
        assert job_payload[default_config.score_field] is None
        assert job_payload[default_config.score_scale_field] is None
        assert job_payload[default_config.sync_marker_field] == "marker-job-001"
        assert job_payload[default_config.sync_version_field] == 1
        assert job_payload[default_config.job_company_lookup_field] == "001000000000001AAA"

    def test_build_job_payload_with_llm_assessment_sets_score(
        self, default_config: SyncMappingConfig
    ) -> None:
        asm = load_c11_fixture("llm_eligible.json")
        now_dt = datetime.now(timezone.utc)
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-2",
            job_title="Lead AI Engineer",
            company_name="NextGen Labs",
            canonical_company_id=uuid.uuid4(),
            source_urls=["https://example.com/jobs/ai"],
            availability=PostingAvailability.ACTIVE,
        )

        job_payload = build_job_payload(
            submission=sub,
            config=default_config,
            sequence_number=2,
            marker="marker-job-002",
        )

        assert job_payload[default_config.score_field] == 92.5
        assert job_payload[default_config.score_scale_field] == "0-100"
        assert job_payload[default_config.sync_version_field] == 2

    def test_picklist_mappings_review_and_unavailable(
        self, default_config: SyncMappingConfig
    ) -> None:
        asm = load_c11_fixture("rules_only_rejected.json")
        now_dt = datetime.now(timezone.utc)
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-3",
            job_title="Job",
            company_name="Company",
            canonical_company_id=uuid.uuid4(),
            availability=PostingAvailability.UNAVAILABLE,
        )

        job_payload = build_job_payload(
            submission=sub,
            config=default_config,
            sequence_number=3,
            marker="marker-job-003",
        )

        assert job_payload[default_config.disposition_field] == "Rejected"
        assert job_payload[default_config.availability_field] == "Unavailable"

    def test_external_id_builders(self) -> None:
        cid = uuid.uuid4()
        jid = uuid.uuid4()
        assert build_company_external_id(cid) == str(cid)
        assert build_job_external_id(jid) == str(jid)

