"""Comprehensive validation scenario test suite for SF-05 Generation Request metadata (V01-V12).

Tests:
- V01: Metadata Parsing & C13 Schema Compatibility
- V02: Request Options Matrix & Strict Boolean Handling
- V03: Stable Identity, Multiple UI Null Keys & 15/18-char Convergence
- V04: External Client Key Idempotency, Replay & Conflict Detection
- V05: Deliberate Regeneration vs Retry & Lineage Preservation
- V06: State Transition Invariants & Frozen Version Atomicity
- V07: Remote CreatedDate Preservation & UTC Timezone Consistency
- V08: Error & Result Visibility Without Falsified Approval
- V09: Least Privilege & Ownership Separation
- V10: Field Length Bounds, Preflight Validation & Error Sanitization
- V11: Offline-Worker Inspectability & Lifecycle Persistence
- V12: Scoped Manifest Allowlist & Upgrade Preservation
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import uuid
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
import pytest

from job_automation.contracts.enums import (
    ContextStrategy,
    DocumentType,
    GenerationProcessing,
    PostingAvailability,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.contracts.identity import CanonicalJob
from job_automation.generation.admission import GenerationAdmitter, _parse_bool_strict
from job_automation.generation.records import (
    GenerationRequestObservation,
    ObservationIssueCategory,
)
from job_automation.generation.request_mapping import (
    MAX_CLIENT_KEY_LENGTH,
    MAX_ERROR_MESSAGE_LENGTH,
    MAX_TEMPLATE_ID_LENGTH,
    RequestFieldMapping,
    canonicalize_salesforce_id,
    compute_options_digest,
    derive_local_request_id,
    sanitize_error_message,
    validate_request_field_lengths,
)
from job_automation.salesforce.metadata_parser import (
    CustomObjectMetadata,
    evaluate_list_view_filter,
    load_permission_set,
    load_salesforce_dx_list_views,
    load_salesforce_dx_objects,
    validate_generation_request_metadata,
    validate_generation_requester_permission_set,
    validate_worker_permission_set,
)
from job_automation.salesforce.sync_settings import load_sync_mapping_config
from job_automation.storage.engine import StorageEngine

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SF_MAIN_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default"
SF_OBJECTS_DIR = SF_MAIN_DIR / "objects"
PERMSETS_DIR = SF_MAIN_DIR / "permissionsets"
MANIFEST_DIR = REPO_ROOT / "salesforce" / "manifest"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "salesforce" / "sf05"
CONFIG_PATH = REPO_ROOT / "config" / "sync.example.json"


@pytest.fixture
def metadata_objects() -> dict[str, CustomObjectMetadata]:
    return load_salesforce_dx_objects(SF_OBJECTS_DIR)


@pytest.fixture
def mapping() -> RequestFieldMapping:
    return RequestFieldMapping()


@pytest.fixture
def engine(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "sf05_test.db"
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
        company_name="Tech Solutions GmbH",
        availability=availability,
        current_revision_id=uuid.uuid4(),
        first_seen_at=now_utc,
        last_seen_at=now_utc,
    )
    engine.canonical_jobs.save_canonical_job(cjob)


class TestSF05Scenarios:
    # --- V01: Metadata Parsing & C13 Schema Compatibility ---
    def test_v01_actual_xml_parsing_against_mapping_and_c13(
        self, metadata_objects: dict[str, CustomObjectMetadata], mapping: RequestFieldMapping
    ) -> None:
        report = validate_generation_request_metadata(metadata_objects, mapping)
        assert report.compatible is True, f"Validation issues: {report.issues}"
        assert len(report.issues) == 0

        req_obj = metadata_objects["generation_request__c"]
        assert req_obj.sharing_model == "Private"
        assert req_obj.name_field_type == "AutoNumber"
        assert req_obj.name_field_display_format == "GR-{000000}"

        # Verify all 23 expected fields exist and have correct metadata attributes
        assert len(req_obj.fields) >= 23
        assert req_obj.fields["client_request_key__c"].unique is True
        assert req_obj.fields["client_request_key__c"].case_sensitive is True
        assert req_obj.fields["client_request_key__c"].external_id is True
        assert req_obj.fields["job__c"].delete_constraint == "Restrict"
        assert req_obj.fields["predecessor_request__c"].delete_constraint == "Restrict"
        assert req_obj.fields["status__c"].default_picklist_value == "Pending"
        assert req_obj.fields["language__c"].default_picklist_value == "de"
        assert req_obj.fields["context_strategy__c"].default_picklist_value == "json"

        # Verify all 13 validation rules exist and are active
        assert len(req_obj.validation_rules) >= 13
        for rname, rule in req_obj.validation_rules.items():
            assert rule.active is True
            assert len(rule.error_condition_formula) > 0

    # --- V02: Request Options Matrix & Strict Boolean Handling ---
    def test_v02_request_options_matrix_and_strict_booleans(
        self, engine: StorageEngine, mapping: RequestFieldMapping
    ) -> None:
        admitter = GenerationAdmitter(engine=engine, mapping=mapping)

        # Matrix: 2 document types x 2 languages x 2 strategies
        doc_types = ["cv", "cover_letter"]
        langs = ["de", "en"]
        strats = ["json", "rag"]

        for dt in doc_types:
            for lang in langs:
                for strat in strats:
                    job_id = uuid.uuid4()
                    _create_canonical_job(engine, job_id, PostingAvailability.ACTIVE)
                    sf_id = "a01" + uuid.uuid4().hex[:12]
                    canon_sf_id = canonicalize_salesforce_id(sf_id)

                    obs = GenerationRequestObservation(
                        org_id="00D000000000001EAA",
                        salesforce_request_id=sf_id,
                        canonical_salesforce_id=canon_sf_id,
                        canonical_job_id=job_id,
                        observed_at=datetime.now(timezone.utc),
                        raw_record={
                            "Id": sf_id,
                            "Job__c": str(job_id),
                            "Document_Type__c": dt,
                            "Language__c": lang,
                            "Template_Id__c": f"tmpl_{dt}_{lang}",
                            "Context_Strategy__c": strat,
                            "Allow_Unavailable_Job__c": False,
                            "Status__c": "Pending",
                        },
                    )
                    req, err = admitter.admit_observation(obs)
                    assert err is None
                    assert req is not None
                    assert req.document_type.value == dt
                    assert req.target_language == lang
                    assert req.context_strategy.value == strat
                    assert req.allow_unavailable_job is False

        # Test strict boolean parsing: omitted, false, "false", "0", malformed -> False
        assert _parse_bool_strict(False) is False
        assert _parse_bool_strict("false") is False
        assert _parse_bool_strict("False") is False
        assert _parse_bool_strict("0") is False
        assert _parse_bool_strict("") is False
        assert _parse_bool_strict(None) is False
        assert _parse_bool_strict("malformed_string") is False
        assert _parse_bool_strict(True) is True
        assert _parse_bool_strict("true") is True
        assert _parse_bool_strict("True") is True
        assert _parse_bool_strict("1") is True

    # --- V03: Stable Identity, Multiple UI Null Keys & 15/18-char Convergence ---
    def test_v03_stable_identity_ui_null_keys_and_15_18_convergence(
        self, engine: StorageEngine, mapping: RequestFieldMapping
    ) -> None:
        admitter = GenerationAdmitter(engine=engine, mapping=mapping)
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id, PostingAvailability.ACTIVE)

        # Two UI requests with null client keys
        sf_id1 = "a01000000000001"
        canon1 = canonicalize_salesforce_id(sf_id1)
        sf_id2 = "a01000000000002"
        canon2 = canonicalize_salesforce_id(sf_id2)

        obs1 = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id1,
            canonical_salesforce_id=canon1,
            client_request_key=None,
            canonical_job_id=job_id,
            observed_at=datetime.now(timezone.utc),
            raw_record={"Id": sf_id1, "Job__c": str(job_id), "Template_Id__c": "t1"},
        )
        obs2 = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id2,
            canonical_salesforce_id=canon2,
            client_request_key=None,
            canonical_job_id=job_id,
            observed_at=datetime.now(timezone.utc),
            raw_record={"Id": sf_id2, "Job__c": str(job_id), "Template_Id__c": "t1"},
        )

        req1, err1 = admitter.admit_observation(obs1)
        req2, err2 = admitter.admit_observation(obs2)
        assert err1 is None and err2 is None
        assert req1 is not None and req2 is not None
        assert req1.request_id != req2.request_id
        assert req1.client_request_key is None
        assert req2.client_request_key is None

        # 15 and 18-char Salesforce ID convergence
        local_id_15 = derive_local_request_id("00D000000000001", sf_id1)
        local_id_18 = derive_local_request_id("00D000000000001EAA", canon1)
        assert local_id_15 == local_id_18 == req1.request_id

        # Different org yields different remote identity
        diff_org_id = derive_local_request_id("00D000000000002EAA", canon1)
        assert diff_org_id != req1.request_id

        # Malformed ID raises ValueError
        with pytest.raises(ValueError, match="Invalid Salesforce ID"):
            canonicalize_salesforce_id("invalid-id-too-short")

    # --- V04: External Client Key Idempotency, Replay & Conflict Detection ---
    def test_v04_external_client_key_replay_and_conflict(
        self, engine: StorageEngine, mapping: RequestFieldMapping
    ) -> None:
        admitter = GenerationAdmitter(engine=engine, mapping=mapping)
        job_id1 = uuid.uuid4()
        job_id2 = uuid.uuid4()
        _create_canonical_job(engine, job_id1, PostingAvailability.ACTIVE)
        _create_canonical_job(engine, job_id2, PostingAvailability.ACTIVE)

        client_key = "producer:ext-key-001"
        sf_id1 = "a01000000000003AAA"

        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id1,
            canonical_salesforce_id=sf_id1,
            client_request_key=client_key,
            canonical_job_id=job_id1,
            observed_at=datetime.now(timezone.utc),
            raw_record={"Id": sf_id1, "Job__c": str(job_id1), "Template_Id__c": "t1"},
        )
        req1, err1 = admitter.admit_observation(obs)
        assert err1 is None and req1 is not None
        assert req1.client_request_key == client_key

        # Replay: exact same key and same payload returns same request
        req_replay, err_replay = admitter.admit_observation(obs)
        assert err_replay is None
        assert req_replay.request_id == req1.request_id

        # Conflict: same client key across differing remote Salesforce record ID
        sf_id2 = "a01000000000004AAA"
        obs_conflict = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id2,
            canonical_salesforce_id=sf_id2,
            client_request_key=client_key,
            canonical_job_id=job_id2,
            observed_at=datetime.now(timezone.utc),
            raw_record={"Id": sf_id2, "Job__c": str(job_id2), "Template_Id__c": "t2"},
        )
        req_bad, err_bad = admitter.admit_observation(obs_conflict)
        assert req_bad is None
        assert err_bad is not None
        assert err_bad.category == ErrorCategory.VALIDATION
        assert "already mapped" in err_bad.message

    # --- V05: Deliberate Regeneration vs Retry & Lineage Preservation ---
    def test_v05_deliberate_regeneration_vs_retry(
        self, engine: StorageEngine, mapping: RequestFieldMapping
    ) -> None:
        admitter = GenerationAdmitter(engine=engine, mapping=mapping)
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id, PostingAvailability.ACTIVE)

        # Original request
        sf_id1 = "a01000000000005AAA"
        obs1 = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id1,
            canonical_salesforce_id=sf_id1,
            canonical_job_id=job_id,
            observed_at=datetime.now(timezone.utc),
            raw_record={"Id": sf_id1, "Job__c": str(job_id), "Template_Id__c": "t1"},
        )
        req1, _ = admitter.admit_observation(obs1)
        assert req1 is not None

        # Deliberate regeneration referencing req1 as predecessor
        sf_id2 = "a01000000000006AAA"
        obs2 = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id2,
            canonical_salesforce_id=sf_id2,
            canonical_job_id=job_id,
            observed_at=datetime.now(timezone.utc),
            raw_record={
                "Id": sf_id2,
                "Job__c": str(job_id),
                "Template_Id__c": "t1",
                "Predecessor_Request__c": sf_id1,
            },
        )
        req2, _ = admitter.admit_observation(obs2)
        assert req2 is not None
        assert req2.request_id != req1.request_id
        assert req2.predecessor_request_id == req1.request_id

        # Retry of req1 preserves original request_id
        req1_retry, _ = admitter.admit_observation(obs1)
        assert req1_retry.request_id == req1.request_id

    # --- V06: State Transition Invariants & Frozen Version Atomicity ---
    def test_v06_state_transition_invariants_and_atomic_freeze(
        self, engine: StorageEngine, mapping: RequestFieldMapping
    ) -> None:
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id, PostingAvailability.ACTIVE)
        now_utc = datetime.now(timezone.utc)

        # 1. Pending record has null worker evidence
        pending_req = GenerationRequest(
            request_id=uuid.uuid4(),
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            target_language="de",
            template_id="t1",
            state=GenerationProcessing.PENDING,
            created_at=now_utc,
            claimed_at=None,
            completed_at=None,
            frozen_input_versions=None,
        )
        assert pending_req.claimed_at is None
        assert pending_req.frozen_input_versions is None

        # 2. Running state requires all four frozen versions
        with pytest.raises(ValueError, match="must have frozen_input_versions"):
            GenerationRequest(
                request_id=uuid.uuid4(),
                canonical_job_id=job_id,
                document_type=DocumentType.CV,
                target_language="de",
                template_id="t1",
                state=GenerationProcessing.RUNNING,
                created_at=now_utc,
                claimed_at=now_utc,
                frozen_input_versions=None,  # Missing!
            )

        # 3. Complete atomic frozen versions passes
        frozen = FrozenInputVersions(
            posting_revision="rev-hash-1",
            profile_version="prof-v1",
            policy_version="pol-v1",
            template_version="tmpl-v1",
        )
        running_req = GenerationRequest(
            request_id=uuid.uuid4(),
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            target_language="de",
            template_id="t1",
            state=GenerationProcessing.RUNNING,
            created_at=now_utc,
            claimed_at=now_utc,
            frozen_input_versions=frozen,
        )
        assert running_req.state == GenerationProcessing.RUNNING
        assert running_req.frozen_input_versions == frozen

        # 4. Preflight failure (job_unavailable) transitions directly to Failed with NO versions
        _create_canonical_job(engine, job_id, PostingAvailability.UNAVAILABLE)
        admitter = GenerationAdmitter(engine=engine, mapping=mapping)
        sf_id = "a01000000000007AAA"
        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id,
            canonical_salesforce_id=sf_id,
            canonical_job_id=job_id,
            observed_at=now_utc,
            raw_record={
                "Id": sf_id,
                "Job__c": str(job_id),
                "Template_Id__c": "t1",
                "Allow_Unavailable_Job__c": False,
            },
        )
        failed_req, err = admitter.admit_observation(obs)
        assert failed_req is not None
        assert failed_req.state == GenerationProcessing.FAILED
        assert failed_req.claimed_at is None
        assert failed_req.frozen_input_versions is None
        assert failed_req.completed_at is not None

    # --- V07: Remote CreatedDate Preservation & UTC Timezone Consistency ---
    def test_v07_remote_created_date_preservation(
        self, engine: StorageEngine, mapping: RequestFieldMapping
    ) -> None:
        admitter = GenerationAdmitter(engine=engine, mapping=mapping)
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id, PostingAvailability.ACTIVE)

        # Explicit remote CreatedDate 2 hours in the past
        remote_created_str = "2026-10-31T08:30:00.000+0000"
        sf_id = "a01000000000008AAA"

        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_id,
            canonical_salesforce_id=sf_id,
            canonical_job_id=job_id,
            observed_at=datetime.now(timezone.utc),
            raw_record={
                "Id": sf_id,
                "Job__c": str(job_id),
                "Template_Id__c": "t1",
                "CreatedDate": remote_created_str,
            },
        )
        req, err = admitter.admit_observation(obs)
        assert err is None
        assert req is not None
        # CreatedDate preserved exactly
        expected_dt = datetime(2026, 10, 31, 8, 30, tzinfo=timezone.utc)
        assert req.created_at == expected_dt

        # Verify time zone conversion to Europe/Berlin displays correctly (+1 in standard time)
        berlin_tz = ZoneInfo("Europe/Berlin")
        berlin_dt = req.created_at.astimezone(berlin_tz)
        assert berlin_dt.hour == 9
        assert berlin_dt.minute == 30

    # --- V08: Error & Result Visibility Without Falsified Approval ---
    def test_v08_error_and_result_visibility_without_approval(self) -> None:
        upload_path = FIXTURES_DIR / "upload_pending_payload.json"
        ready_path = FIXTURES_DIR / "ready_for_review_payload.json"

        upload_data = json.loads(upload_path.read_text(encoding="utf-8"))
        assert upload_data["Status__c"] == "Upload_Pending"
        assert upload_data["Error_Category__c"] == "capacity"
        assert upload_data["Local_Artifact_Ref__c"] == "c14_art_777888"
        # Upload pending never claims ready or approved
        assert "Approved" not in upload_data
        assert upload_data.get("Result_Artifact_Ref__c") is None

        ready_data = json.loads(ready_path.read_text(encoding="utf-8"))
        assert ready_data["Status__c"] == "Ready_for_Review"
        assert ready_data["Completed_At__c"] is not None
        assert ready_data["Result_Artifact_Ref__c"] == "069000000000001AAA"
        # Ready for review never implies approved!
        assert "Approved" not in ready_data

    # --- V09: Least Privilege & Ownership Separation ---
    def test_v09_least_privilege_and_candidate_protection(self) -> None:
        # Requester Permission Set
        req_ps = load_permission_set(PERMSETS_DIR / "Job_Generation_Requester.permissionset-meta.xml")
        assert req_ps.object_permissions["generation_request__c"].allow_create is True
        assert req_ps.object_permissions["generation_request__c"].allow_edit is False
        assert req_ps.field_permissions["generation_request__c.status__c"].editable is False

        # Worker Permission Set
        worker_ps = load_permission_set(PERMSETS_DIR / "Job_Automation_Worker.permissionset-meta.xml")
        assert worker_ps.object_permissions["generation_request__c"].allow_create is False
        assert worker_ps.object_permissions["generation_request__c"].allow_edit is True
        assert worker_ps.field_permissions["generation_request__c.job__c"].editable is False
        assert worker_ps.field_permissions["generation_request__c.status__c"].editable is True

        # Existing candidate tracking fields on Job__c remain strictly protected from worker write
        job_candidate_fields = [
            "application_progress__c",
            "candidate_notes__c",
            "candidate_decision__c",
            "follow_up_date__c",
            "interview_date__c",
        ]
        for cf in job_candidate_fields:
            full = f"job__c.{cf}"
            assert worker_ps.field_permissions[full].readable is True
            assert worker_ps.field_permissions[full].editable is False

    # --- V10: Field Length Bounds, Preflight Validation & Error Sanitization ---
    def test_v10_field_length_bounds_and_error_sanitization(
        self, mapping: RequestFieldMapping
    ) -> None:
        # Overlength client key detection
        overlength_payload = {
            mapping.client_key_field: "x" * (MAX_CLIENT_KEY_LENGTH + 1),
            mapping.template_id_field: "tmpl-1",
        }
        issues = validate_request_field_lengths(overlength_payload, mapping)
        assert len(issues) == 1
        assert "Client Request Key" in issues[0]
        assert "exceeds maximum remote length" in issues[0]

        # Sanitization: credentials and Windows absolute paths are stripped
        raw_err = "Failed accessing C:\\Users\\secret\\token.txt with password=SuperSecret123 and bearer eyJhbGci"
        sanitized = sanitize_error_message(raw_err)
        assert "SuperSecret123" not in sanitized
        assert "C:\\Users" not in sanitized
        assert "[REDACTED]" in sanitized

        # Unicode umlauts (München, Zürich) survive sanitization
        unicode_err = "Fehler beim Verarbeiten für Bewerbung München & Zürich"
        assert sanitize_error_message(unicode_err) == unicode_err

    # --- V11: Offline-Worker Inspectability & Lifecycle Persistence ---
    def test_v11_offline_worker_inspectability(self) -> None:
        # Load ListViews and verify all states can be filtered and inspected offline
        views = load_salesforce_dx_list_views(SF_OBJECTS_DIR / "Generation_Request__c")
        in_prog_view = views["In_Progress"]
        failed_view = views["Failed_Requests"]
        ready_view = views["Ready_Requests"]

        # Pending record is visible in In_Progress
        rec_pending = {"Status__c": "Pending"}
        assert evaluate_list_view_filter(in_prog_view, rec_pending, "2026-11-01") is True
        assert evaluate_list_view_filter(failed_view, rec_pending, "2026-11-01") is False

        # Running record is visible in In_Progress
        rec_running = {"Status__c": "Running"}
        assert evaluate_list_view_filter(in_prog_view, rec_running, "2026-11-01") is True

        # Failed record is visible in Failed_Requests
        rec_failed = {"Status__c": "Failed"}
        assert evaluate_list_view_filter(failed_view, rec_failed, "2026-11-01") is True
        assert evaluate_list_view_filter(in_prog_view, rec_failed, "2026-11-01") is False

        # Ready record is visible in Ready_Requests
        rec_ready = {"Status__c": "Ready_for_Review"}
        assert evaluate_list_view_filter(ready_view, rec_ready, "2026-11-01") is True

    # --- V12: Scoped Manifest Allowlist & Upgrade Preservation ---
    def test_v12_manifest_allowlist_and_upgrade_preservation(self) -> None:
        sf05_path = MANIFEST_DIR / "sf05.xml"
        assert sf05_path.is_file()
        tree = ET.parse(sf05_path)
        root = tree.getroot()
        ns = {"ns": "http://soap.sforce.com/2006/04/metadata"}

        # Manifest must not contain wildcards
        members = [m.text for m in root.findall(".//ns:members", ns)]
        assert "*" not in members
        assert "Generation_Request__c" in members
        assert "Job_Generation_Requester" in members
        assert "Job_Automation_Worker" in members

        # Profiles must not be in sf05.xml
        type_names = [n.text for n in root.findall(".//ns:name", ns)]
        assert "Profile" not in type_names
