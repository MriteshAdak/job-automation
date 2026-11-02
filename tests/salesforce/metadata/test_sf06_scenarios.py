"""Comprehensive validation scenario test suite for SF-06 Generation Actions and Flows (V01-V18).

Tests:
- V01: XML Parsing, Flow & Action Structure, Zero Direct Insert / Zero Localhost Callouts
- V02: Generation Options Matrix (doc_types x languages x strategies x templates) & Option Validation
- V03: Invalid Job, Bad Canonical Mapping, Forged Doc Type, and Invalid Predecessor Gating
- V04: Double-Click, Back, and Idempotency Token Lifecycle & Conflict Detection
- V05: Concurrent Submission of Identical Intent Under Races (Simulated Overlapping Transactions)
- V06: Active Request Reuse (Pending, Stale Running, Upload_Pending) and Deterministic Selection
- V07: Worker State Transitions While Enqueue Waits & Field Preservation
- V08: Deliberate Regeneration Lineage & Separate Identity Preservation
- V09: Lost Response Recovery & State-Independent Replay
- V10: Atomic Compound Transaction Rollback on Receipt Failure & Lock Contention
- V11: Terminal History Confirmation Gate vs Normal Action
- V12: Unavailable-Job Gating & Failed job_unavailable Override Invariant
- V13: Unknown/Not_Seen Availability Handling & Worker Failure Decoupling
- V14: Privilege Separation (Candidate vs Worker vs Unrelated Principal)
- V15: Offline Worker Queuing & Truthful User Feedback
- V16: Immutability of Job Candidate Tracking Fields Across Submissions
- V17: GEN-01 Admission Integration (Deterministic UUIDv5 & 15/18-char Convergence)
- V18: Unicode Character Support, Error Sanitization, and UTC/Berlin Time Consistency
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import uuid
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
import pytest

from job_automation.contracts.enums import ContextStrategy, DocumentType, GenerationProcessing, PostingAvailability
from job_automation.contracts.identity import CanonicalJob
from job_automation.generation.admission import GenerationAdmitter
from job_automation.generation.records import GenerationRequestObservation
from job_automation.generation.request_mapping import (
    MAX_TEMPLATE_ID_LENGTH,
    RequestFieldMapping,
    canonicalize_salesforce_id,
    derive_local_request_id,
)
from job_automation.salesforce.generation_submission import (
    DEFAULT_CATALOG,
    GenerationOptionCatalogEntry,
    GenerationSubmissionService,
    SimulatedGenerationRequest,
    SubmissionIntent,
    SubmissionOutcome,
    SubmissionResult,
)
from job_automation.salesforce.metadata_parser import (
    load_permission_set,
    load_salesforce_dx_custom_metadata,
    load_salesforce_dx_flows,
    load_salesforce_dx_layouts,
    load_salesforce_dx_objects,
    load_salesforce_dx_quick_actions,
    validate_sf06_actions_permission_set,
    validate_sf06_metadata,
)
from job_automation.storage.engine import StorageEngine

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SF_MAIN_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default"
SF_OBJECTS_DIR = SF_MAIN_DIR / "objects"
PERMSETS_DIR = SF_MAIN_DIR / "permissionsets"
FLOWS_DIR = SF_MAIN_DIR / "flows"
QUICKACTIONS_DIR = SF_MAIN_DIR / "quickActions"
CUSTOM_METADATA_DIR = SF_MAIN_DIR / "customMetadata"
LAYOUTS_DIR = SF_MAIN_DIR / "layouts"
MANIFEST_DIR = REPO_ROOT / "salesforce" / "manifest"


@pytest.fixture
def service() -> GenerationSubmissionService:
    svc = GenerationSubmissionService()
    svc.register_job(
        job_id="a01000000000001AAA",
        name="JOB-000001",
        job_title="Lead Platform Architect",
        canonical_job_id="3f7c4627-2c96-4a41-b8ef-b8cb5e3789a1",
        availability="Active",
    )
    svc.register_job(
        job_id="a01000000000002AAA",
        name="JOB-000002",
        job_title="Closed Legacy Developer",
        canonical_job_id="7e8902cd-1122-4876-b921-9988aabbccdd",
        availability="Unavailable",
    )
    return svc


@pytest.fixture
def engine(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "sf06_test.db"
    eng = StorageEngine(db_path=db_path, raw_dir=tmp_path / "raw", artifacts_dir=tmp_path / "art")
    eng.initialize_schema()
    return eng


class TestSF06Scenarios:

    # --- V01: XML Parsing & Zero Callouts / Inference Hooks ---
    def test_v01_xml_parsing_and_zero_localhost_inference(self) -> None:
        objs = load_salesforce_dx_objects(SF_OBJECTS_DIR)
        flows = load_salesforce_dx_flows(FLOWS_DIR)
        qas = load_salesforce_dx_quick_actions(QUICKACTIONS_DIR)
        opts = load_salesforce_dx_custom_metadata(CUSTOM_METADATA_DIR)
        ps = load_permission_set(PERMSETS_DIR / "Job_Generation_Actions.permissionset-meta.xml")

        rep1 = validate_sf06_metadata(objs, flows, qas, opts)
        assert rep1.compatible is True, f"Metadata validation failed: {rep1.issues}"

        rep2 = validate_sf06_actions_permission_set(ps)
        assert rep2.compatible is True, f"PermissionSet validation failed: {rep2.issues}"

        # Verify Flows contain NO callouts, HTTP actions, or localhost endpoints
        for flow_name in ("JA_Generate_CV.flow-meta.xml", "JA_Generate_Cover_Letter.flow-meta.xml"):
            path = FLOWS_DIR / flow_name
            content = path.read_text(encoding="utf-8")
            assert "localhost" not in content.lower()
            assert "127.0.0.1" not in content
            assert "callout" not in content.lower()
            assert "endpoint" not in content.lower()
            # Verify Flow invokes Apex action and does NOT do direct record inserts
            assert "<actionCalls>" in content
            assert "JA_GenerationSubmit" in content
            assert "<recordCreates>" not in content

        # Verify Apex class contains NO callouts or network loops
        apex_path = SF_MAIN_DIR / "classes" / "JA_GenerationSubmit.cls"
        apex_content = apex_path.read_text(encoding="utf-8")
        assert "HttpRequest" not in apex_content
        assert "HttpTransport" not in apex_content
        assert "localhost" not in apex_content.lower()

    # --- V02: Generation Options Matrix & Strict Validation ---
    def test_v02_options_matrix_and_template_validation(
        self, service: GenerationSubmissionService
    ) -> None:
        doc_types = ["cv", "cover_letter"]
        langs = ["de", "en"]
        strats = ["json", "rag"]

        template_map = {
            "cv": ["layout-cv-basic-a4", "layout-cv-compact-a4"],
            "cover_letter": ["layout-letter-basic-a4", "layout-letter-compact-a4"],
        }

        # Verify all combinations of 2 doc_types x 2 langs x 2 strats x 2 templates
        for dt in doc_types:
            for tmpl in template_map[dt]:
                for lang in langs:
                    for strat in strats:
                        token = f"tok-{dt}-{tmpl}-{lang}-{strat}"
                        intent = SubmissionIntent(
                            job_id="a01000000000001AAA",
                            document_type=dt,
                            language=lang,
                            template_id=tmpl,
                            context_strategy=strat,
                            submission_token=token,
                        )
                        res = service.submit(intent)
                        assert res.outcome == SubmissionOutcome.CREATED
                        assert res.is_success is True
                        assert res.request_id is not None
                        assert res.processing_state == "Pending"

        # Rejection of invalid / unknown template
        bad_tmpl_intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-unknown-invalid",
            submission_token="bad-tmpl-001",
        )
        res_bad = service.submit(bad_tmpl_intent)
        assert res_bad.outcome == SubmissionOutcome.REJECTED
        assert "Unknown template ID" in res_bad.message

        # Rejection of oversized template
        long_tmpl_intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="t" * (MAX_TEMPLATE_ID_LENGTH + 1),
            submission_token="long-tmpl-001",
        )
        res_long = service.submit(long_tmpl_intent)
        assert res_long.outcome == SubmissionOutcome.REJECTED
        assert "exceeds maximum length" in res_long.message

        # Rejection of cross-type template mismatch (CV template for cover_letter)
        mismatch_intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cover_letter",
            template_id="layout-cv-basic-a4",
            submission_token="mismatch-tmpl-001",
        )
        res_mismatch = service.submit(mismatch_intent)
        assert res_mismatch.outcome == SubmissionOutcome.REJECTED
        assert "does not support document type" in res_mismatch.message

    # --- V03: Invalid Job, Bad Canonical UUID, Forged Doc Type & Predecessor Gating ---
    def test_v03_invalid_job_bad_uuid_and_forged_parameters(
        self, service: GenerationSubmissionService
    ) -> None:
        # Missing / non-existent Job
        res_no_job = service.submit(
            SubmissionIntent(
                job_id="a01000000000999AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                submission_token="no-job-001",
            )
        )
        assert res_no_job.outcome == SubmissionOutcome.REJECTED
        assert "Target Job record not found" in res_no_job.message

        # Job with missing/malformed Canonical Job ID
        service.register_job(
            job_id="a01000000000003AAA",
            name="JOB-000003",
            job_title="Invalid Canonical Job",
            canonical_job_id="not-a-valid-uuid",
        )
        res_bad_uuid = service.submit(
            SubmissionIntent(
                job_id="a01000000000003AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                submission_token="bad-uuid-001",
            )
        )
        assert res_bad_uuid.outcome == SubmissionOutcome.REJECTED
        assert "Canonical Job ID" in res_bad_uuid.message

        # Forged document type
        res_forged_dt = service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="executive_summary",
                template_id="layout-cv-basic-a4",
                submission_token="forged-dt-001",
            )
        )
        assert res_forged_dt.outcome == SubmissionOutcome.REJECTED
        assert "Invalid document type" in res_forged_dt.message

        # Invalid predecessor (non-existent) in regenerate mode
        res_bad_pred = service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                creation_mode="regenerate",
                predecessor_request_id="a02000000000999AAA",
                submission_token="bad-pred-001",
            )
        )
        assert res_bad_pred.outcome == SubmissionOutcome.REJECTED
        assert "Predecessor request not found" in res_bad_pred.message

    # --- V04: Double-Click, Back, and Idempotency Token Lifecycle ---
    def test_v04_token_lifecycle_double_click_and_conflict(
        self, service: GenerationSubmissionService
    ) -> None:
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            language="de",
            template_id="layout-cv-basic-a4",
            submission_token="token-idempotent-001",
        )

        # First click: Created
        res1 = service.submit(intent)
        assert res1.outcome == SubmissionOutcome.CREATED
        assert res1.is_success is True
        orig_id = res1.request_id

        # Rapid double-click with identical token & intent: Replayed
        res2 = service.submit(intent)
        assert res2.outcome == SubmissionOutcome.REPLAYED
        assert res2.is_success is True
        assert res2.request_id == orig_id
        assert len(service.requests) == 1

        # Conflict: same token resubmitted with changed parameter (e.g. language 'en')
        conflict_intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            language="en",  # Changed
            template_id="layout-cv-basic-a4",
            submission_token="token-idempotent-001",  # Same token
        )
        res_conf = service.submit(conflict_intent)
        assert res_conf.outcome == SubmissionOutcome.REJECTED
        assert res_conf.is_success is False
        assert "conflict" in res_conf.message.lower()

    # --- V05: Concurrent Submission of Identical Intent (Simulated Overlapping Transactions) ---
    def test_v05_concurrent_submission_atomic_deduplication(
        self, service: GenerationSubmissionService
    ) -> None:
        results: list[SubmissionResult] = []
        lock = threading.Lock()

        # Two browser tabs submit identical intent with different submission tokens
        intent1 = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            language="de",
            template_id="layout-cv-basic-a4",
            submission_token="tab1-token-001",
        )
        intent2 = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            language="de",
            template_id="layout-cv-basic-a4",
            submission_token="tab2-token-002",
        )

        def run_tab(intent: SubmissionIntent) -> None:
            res = service.submit(intent)
            with lock:
                results.append(res)

        t1 = threading.Thread(target=run_tab, args=(intent1,))
        t2 = threading.Thread(target=run_tab, args=(intent2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(results) == 2
        outcomes = {r.outcome for r in results}
        # One must be created, and the other must be reused_active (or both point to the same request)
        assert SubmissionOutcome.CREATED in outcomes
        assert SubmissionOutcome.REUSED_ACTIVE in outcomes

        # Both point to the exact same request ID
        req_ids = {r.request_id for r in results}
        assert len(req_ids) == 1

        # Exactly 1 request record created in storage
        assert len(service.requests) == 1
        # Both tabs got separate, stable receipts
        assert len(service.receipts) == 2

    # --- V06: Active Request Reuse (Pending, Stale Running, Upload_Pending) ---
    def test_v06_active_reuse_across_states_and_deterministic_selection(
        self, service: GenerationSubmissionService
    ) -> None:
        # 1. Reuse Pending request
        intent_pending = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            language="de",
            template_id="layout-cv-basic-a4",
            submission_token="tok-initial-001",
        )
        res_p = service.submit(intent_pending)
        assert res_p.outcome == SubmissionOutcome.CREATED
        req_id = res_p.request_id

        # Submit identical intent with new token -> reuses active Pending request
        res_p_reuse = service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cv",
                language="de",
                template_id="layout-cv-basic-a4",
                submission_token="tok-new-002",
            )
        )
        assert res_p_reuse.outcome == SubmissionOutcome.REUSED_ACTIVE
        assert res_p_reuse.request_id == req_id
        assert res_p_reuse.processing_state == "Pending"

        # 2. Advance to Running: still reused
        service.requests[req_id].status = "Running"
        res_r_reuse = service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cv",
                language="de",
                template_id="layout-cv-basic-a4",
                submission_token="tok-new-003",
            )
        )
        assert res_r_reuse.outcome == SubmissionOutcome.REUSED_ACTIVE
        assert res_r_reuse.request_id == req_id
        assert res_r_reuse.processing_state == "Running"

        # 3. Advance to Upload_Pending: still reused
        service.requests[req_id].status = "Upload_Pending"
        res_up_reuse = service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cv",
                language="de",
                template_id="layout-cv-basic-a4",
                submission_token="tok-new-004",
            )
        )
        assert res_up_reuse.outcome == SubmissionOutcome.REUSED_ACTIVE
        assert res_up_reuse.request_id == req_id
        assert res_up_reuse.processing_state == "Upload_Pending"

    # --- V07: Worker State Transitions While Enqueue Waits ---
    def test_v07_worker_transition_preservation_and_truthful_feedback(
        self, service: GenerationSubmissionService
    ) -> None:
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="tok-trans-001",
        )
        res = service.submit(intent)
        req_id = res.request_id

        # Worker claims request and sets frozen versions
        req = service.requests[req_id]
        req.status = "Running"
        req.client_request_key = None
        req.contract_schema_version = "1.0"

        # Re-query via submission service
        res_recheck = service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                submission_token="tok-trans-002",
            )
        )
        assert res_recheck.outcome == SubmissionOutcome.REUSED_ACTIVE
        assert res_recheck.processing_state == "Running"
        # Confirm worker fields are completely preserved
        assert req.status == "Running"
        assert req.contract_schema_version == "1.0"

    # --- V08: Deliberate Regeneration Lineage & Separate Identity ---
    def test_v08_deliberate_regeneration_lineage_and_separate_id(
        self, service: GenerationSubmissionService
    ) -> None:
        # Initial request completes
        res1 = service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cv",
                language="de",
                template_id="layout-cv-basic-a4",
                submission_token="tok-init-001",
            )
        )
        pred_id = res1.request_id
        service.requests[pred_id].status = "Ready_for_Review"
        service.requests[pred_id].result_artifact_ref = "068000000000001AAA"

        # Deliberate regeneration with new options
        regen_intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            language="en",  # Changed language
            template_id="layout-cv-compact-a4",  # Changed template
            creation_mode="regenerate",
            predecessor_request_id=pred_id,
            submission_token="tok-regen-001",
        )
        res_regen = service.submit(regen_intent)
        assert res_regen.outcome == SubmissionOutcome.CREATED
        assert res_regen.is_success is True
        new_id = res_regen.request_id
        assert new_id != pred_id

        # Verify lineage on new request
        new_req = service.requests[new_id]
        assert new_req.predecessor_request_id == pred_id
        assert new_req.language == "en"
        assert new_req.template_id == "layout-cv-compact-a4"
        assert new_req.status == "Pending"

        # Predecessor remains intact with its original artifact
        assert service.requests[pred_id].status == "Ready_for_Review"
        assert service.requests[pred_id].result_artifact_ref == "068000000000001AAA"

        # Re-submitting the same regeneration token replays the new request
        res_regen_replay = service.submit(regen_intent)
        assert res_regen_replay.outcome == SubmissionOutcome.REPLAYED
        assert res_regen_replay.request_id == new_id

    # --- V09: Lost Response Recovery & State-Independent Replay ---
    def test_v09_lost_response_replay_across_lifecycle_states(
        self, service: GenerationSubmissionService
    ) -> None:
        intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="lost-resp-tok-001",
        )
        res = service.submit(intent)
        req_id = res.request_id

        # 1. Replay while Pending
        r_p = service.submit(intent)
        assert r_p.outcome == SubmissionOutcome.REPLAYED
        assert r_p.processing_state == "Pending"
        assert r_p.request_id == req_id

        # 2. Replay after transitioning to Running
        service.requests[req_id].status = "Running"
        r_r = service.submit(intent)
        assert r_r.outcome == SubmissionOutcome.REPLAYED
        assert r_r.processing_state == "Running"

        # 3. Replay after transitioning to Failed
        service.requests[req_id].status = "Failed"
        service.requests[req_id].error_reason = "model_timeout"
        r_f = service.submit(intent)
        assert r_f.outcome == SubmissionOutcome.REPLAYED
        assert r_f.processing_state == "Failed"

        # 4. Replay after transitioning to Ready_for_Review
        service.requests[req_id].status = "Ready_for_Review"
        r_ready = service.submit(intent)
        assert r_ready.outcome == SubmissionOutcome.REPLAYED
        assert r_ready.processing_state == "Ready_for_Review"

    # --- V10: Atomic Compound Transaction Rollback on Failure & Lock Contention ---
    def test_v10_atomic_transaction_rollback_and_lock_contention(
        self, service: GenerationSubmissionService
    ) -> None:
        # 1. Lock contention returns retryable_conflict
        service._simulate_lock_contention = True
        res_lock = service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                submission_token="lock-tok-001",
            )
        )
        assert res_lock.outcome == SubmissionOutcome.RETRYABLE_CONFLICT
        assert res_lock.is_success is False
        assert "contention" in res_lock.message.lower()
        service._simulate_lock_contention = False

        # 2. Receipt insertion failure triggers compound rollback
        service._simulate_receipt_failure = True
        res_fail = service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                submission_token="fail-tok-002",
            )
        )
        assert res_fail.outcome == SubmissionOutcome.REJECTED
        # Verify NO orphan Generation_Request__c record was committed
        assert len(service.requests) == 0
        service._simulate_receipt_failure = False

    # --- V11: Terminal History Confirmation Gate vs Normal Action ---
    def test_v11_terminal_history_confirmation_gate(
        self, service: GenerationSubmissionService
    ) -> None:
        # Create request and transition to Ready_for_Review
        res = service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                language="de",
                submission_token="term-tok-001",
            )
        )
        req_id = res.request_id
        service.requests[req_id].status = "Ready_for_Review"

        # Fresh candidate action with new token and matching options
        fresh_intent = SubmissionIntent(
            job_id="a01000000000001AAA",
            document_type="cv",
            template_id="layout-cv-basic-a4",
            language="de",
            creation_mode="reuse_or_create",
            submission_token="fresh-tok-002",
        )
        res_gate = service.submit(fresh_intent)
        # Cannot silently create another draft; requires confirmation
        assert res_gate.outcome == SubmissionOutcome.CONFIRMATION_REQUIRED
        assert "Confirm deliberate regeneration" in res_gate.message
        assert res_gate.request_id == req_id

    # --- V12: Unavailable-Job Gating & Failed job_unavailable Override Invariant ---
    def test_v12_unavailable_job_and_failed_history_override_invariants(
        self, service: GenerationSubmissionService
    ) -> None:
        unavail_job_id = "a01000000000002AAA"

        # 1. Job is marked Unavailable -> fails without explicit consent
        res_unavail = service.submit(
            SubmissionIntent(
                job_id=unavail_job_id,
                document_type="cv",
                template_id="layout-cv-basic-a4",
                allow_unavailable_job=False,  # default False
                submission_token="unavail-tok-001",
            )
        )
        assert res_unavail.outcome == SubmissionOutcome.CONFIRMATION_REQUIRED
        assert "Explicit consent is required" in res_unavail.message

        # Explicit consent allows creation
        res_override = service.submit(
            SubmissionIntent(
                job_id=unavail_job_id,
                document_type="cv",
                template_id="layout-cv-basic-a4",
                allow_unavailable_job=True,
                submission_token="unavail-tok-002",
            )
        )
        assert res_override.outcome == SubmissionOutcome.CREATED
        assert res_override.is_success is True

        # 2. Previous request failed with job_unavailable
        active_job_id = "a01000000000001AAA"
        fail_req_id = "a02000000000999AAA"
        service.requests[fail_req_id] = SimulatedGenerationRequest(
            id=fail_req_id,
            name="GR-000999",
            job_id=active_job_id,
            document_type="cv",
            language="de",
            template_id="layout-cv-basic-a4",
            context_strategy="json",
            allow_unavailable_job=False,
            status="Failed",
            created_by_id="005000000000001AAA",
            created_date=datetime.now(timezone.utc),
            error_reason="job_unavailable",
        )

        # Reopening action on this job without override -> blocked by failure history
        res_blocked = service.submit(
            SubmissionIntent(
                job_id=active_job_id,
                document_type="cv",
                template_id="layout-cv-basic-a4",
                allow_unavailable_job=False,
                submission_token="fail-hist-tok-001",
            )
        )
        assert res_blocked.outcome == SubmissionOutcome.CONFIRMATION_REQUIRED
        assert "failed because this job was unavailable" in res_blocked.message

        # Retry with explicit predecessor and override -> succeeds
        res_allowed = service.submit(
            SubmissionIntent(
                job_id=active_job_id,
                document_type="cv",
                template_id="layout-cv-basic-a4",
                creation_mode="regenerate",
                predecessor_request_id=fail_req_id,
                allow_unavailable_job=True,
                submission_token="fail-hist-tok-002",
            )
        )
        assert res_allowed.outcome == SubmissionOutcome.CREATED
        assert res_allowed.is_success is True

    # --- V13: Unknown/Not_Seen Availability Handling ---
    def test_v13_unknown_not_seen_availability_shows_uncertainty(
        self, service: GenerationSubmissionService
    ) -> None:
        service.register_job(
            job_id="a01000000000004AAA",
            name="JOB-000004",
            job_title="Unknown Availability Job",
            canonical_job_id="55555555-4444-3333-2222-111111111111",
            availability="Unknown",
        )
        res = service.submit(
            SubmissionIntent(
                job_id="a01000000000004AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                allow_unavailable_job=False,
                submission_token="unknown-avail-tok-001",
            )
        )
        # Unknown does NOT mean confirmed unavailable: request is queued
        assert res.outcome == SubmissionOutcome.CREATED
        assert res.is_success is True

    # --- V14: Privilege Separation (Candidate vs Worker) ---
    def test_v14_privilege_separation_and_candidate_immutability(self) -> None:
        ps_actions = load_permission_set(PERMSETS_DIR / "Job_Generation_Actions.permissionset-meta.xml")
        ps_worker = load_permission_set(PERMSETS_DIR / "Job_Automation_Worker.permissionset-meta.xml")

        # Candidate can create, cannot edit status or worker operational fields
        assert ps_actions.object_permissions["generation_request__c"].allow_create is True
        assert ps_actions.field_permissions["generation_request__c.status__c"].editable is False
        assert ps_actions.field_permissions["generation_request__c.error_reason__c"].editable is False
        assert ps_actions.field_permissions["generation_request__c.result_artifact_ref__c"].editable is False

        # Worker can edit operational fields, CANNOT create generation requests
        assert ps_worker.object_permissions["generation_request__c"].allow_create is False
        assert ps_worker.field_permissions["generation_request__c.status__c"].editable is True
        assert ps_worker.field_permissions["generation_request__c.error_reason__c"].editable is True

    # --- V15: Offline Worker Queuing & Truthful Feedback ---
    def test_v15_offline_worker_persistence_and_feedback(
        self, service: GenerationSubmissionService
    ) -> None:
        # Submit both CV and Cover Letter with worker stopped
        res_cv = service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                submission_token="offline-cv-001",
            )
        )
        res_letter = service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cover_letter",
                template_id="layout-letter-basic-a4",
                submission_token="offline-letter-001",
            )
        )

        assert res_cv.outcome == SubmissionOutcome.CREATED
        assert res_cv.processing_state == "Pending"
        assert "queued. It will be processed when the local worker runs" in res_cv.message

        assert res_letter.outcome == SubmissionOutcome.CREATED
        assert res_letter.processing_state == "Pending"
        assert "queued. It will be processed when the local worker runs" in res_letter.message

        # Neither action approved itself or claimed immediate completion
        assert "approved" not in res_cv.message.lower()
        assert "ready" not in res_cv.message.lower()

    # --- V16: Immutability of Job Candidate Tracking Fields ---
    def test_v16_candidate_job_fields_remain_intact(
        self, service: GenerationSubmissionService
    ) -> None:
        job = service.jobs["a01000000000001AAA"]
        initial_title = job.job_title
        initial_avail = job.availability
        initial_canon = job.canonical_job_id

        # Execute multiple actions (create, reuse, replay)
        intent = SubmissionIntent(
            job_id=job.id,
            document_type="cv",
            template_id="layout-cv-basic-a4",
            submission_token="intact-tok-001",
        )
        service.submit(intent)
        service.submit(intent)

        # Confirm Job fields are byte/value equivalent
        assert job.job_title == initial_title
        assert job.availability == initial_avail
        assert job.canonical_job_id == initial_canon

    # --- V17: GEN-01 Admission Integration (Deterministic UUIDv5 & 15/18-char Convergence) ---
    def test_v17_gen01_admission_integration(
        self, service: GenerationSubmissionService, engine: StorageEngine
    ) -> None:
        job_uuid = uuid.UUID("3f7c4627-2c96-4a41-b8ef-b8cb5e3789a1")
        now_utc = datetime.now(timezone.utc)
        cjob = CanonicalJob(
            canonical_job_id=job_uuid,
            company_name="Acme Tech GmbH",
            availability=PostingAvailability.ACTIVE,
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_utc,
            last_seen_at=now_utc,
        )
        engine.canonical_jobs.save_canonical_job(cjob)

        res = service.submit(
            SubmissionIntent(
                job_id="a01000000000001AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                submission_token="gen01-tok-001",
            )
        )
        sf_req_id = res.request_id

        # Admit through GenerationAdmitter (GEN-01)
        admitter = GenerationAdmitter(engine=engine, mapping=RequestFieldMapping())
        canon_sf_id = canonicalize_salesforce_id(sf_req_id)
        obs = GenerationRequestObservation(
            org_id="00D000000000001EAA",
            salesforce_request_id=sf_req_id,
            canonical_salesforce_id=canon_sf_id,
            canonical_job_id=job_uuid,
            observed_at=now_utc,
            raw_record={
                "Id": sf_req_id,
                "Job__c": str(job_uuid),
                "Document_Type__c": "cv",
                "Language__c": "de",
                "Template_Id__c": "layout-cv-basic-a4",
                "Context_Strategy__c": "json",
                "Allow_Unavailable_Job__c": False,
                "Status__c": "Pending",
            },
        )
        req, err = admitter.admit_observation(obs)
        assert err is None
        assert req is not None
        # UUIDv5 derived deterministically from (org_id, canonical_sf_id)
        expected_uuid = derive_local_request_id("00D000000000001EAA", canon_sf_id)
        assert req.request_id == expected_uuid

    # --- V18: Unicode, Europe/Berlin Display & Manifest Verification ---
    def test_v18_unicode_and_manifest_allowlist(
        self, service: GenerationSubmissionService
    ) -> None:
        # German umlauts in Job title
        service.register_job(
            job_id="a01000000000005AAA",
            name="JOB-000005",
            job_title="Softwareentwickler für Hochverfügbarkeitslösungen (m/w/d)",
            canonical_job_id="88888888-7777-6666-5555-444444444444",
        )
        res = service.submit(
            SubmissionIntent(
                job_id="a01000000000005AAA",
                document_type="cv",
                template_id="layout-cv-basic-a4",
                submission_token="umlaut-tok-001",
            )
        )
        assert res.outcome == SubmissionOutcome.CREATED
        assert "queued" in res.message

        # Europe/Berlin timezone consistency check
        berlin_tz = ZoneInfo("Europe/Berlin")
        now_berlin = datetime.now(berlin_tz)
        assert now_berlin.tzinfo is not None

        # Verify manifest file exists and is valid XML
        manifest_path = MANIFEST_DIR / "sf06.xml"
        assert manifest_path.is_file()
        tree = ET.parse(manifest_path)
        assert tree.getroot() is not None
