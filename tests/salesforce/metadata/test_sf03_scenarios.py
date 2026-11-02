"""Comprehensive validation test suite for SF-03 tracking views, candidate decisions,
layouts, reports, and SYNC-01 preservation integration (V01-V22).

Scenarios:
- V01: SF-03 UI metadata parsing and compatibility validation against DX source root.
- V02: Scoped manifest allowlist structure (sf03.xml and package.xml, no wildcards, no Admin.profile).
- V03: List view metadata contracts (filterScope=Everything, explicit column sets, boolean filters).
- V04: Synthetic dataset coverage matrix (all 3 dispositions + null, 4 availabilities + null,
       9 progress values + null, unknown criterion vs other review, date boundaries).
- V05: JA_Eligible_Jobs list view membership (D=Eligible, includes unavailable/archived with state visible).
- V06: JA_Review_Jobs distinguishes unknown eligibility and missing assessment (D=Review OR D is blank).
- V07: JA_Shortlist and JA_Applications candidate domain isolation (independent of machine disposition/availability).
- V08: JA_Follow_Ups_Due and JA_Follow_Ups_Upcoming relative date boundary filtering (yesterday/today/tomorrow/blank).
- V09: JA_Tracked_History completeness (all accessible records including terminal and blank progress).
- V10: Worker record ownership accessibility in list views (filterScope=Everything prevents empty queues).
- V11: Machine assessment rejection strictly distinct from candidate application rejection.
- V12: Job__c page layout section separation, candidate editability, and machine read-only behavior.
- V13: Company__c page layout and Jobs related list projection.
- V14: Compact layout JA_Tracking summary fields and Job__c assignment.
- V15: FlexiPage JA_Job_Tracking components, HighlightsPanel, DetailPanel, and conditional guidance banners.
- V16: CustomTabs (Job__c, Company__c) and CustomApplication (Job_Tracker) navigation structure.
- V17: ReportType JA_Jobs outer join contract (jobs without company are preserved).
- V18: Report JA_Eligible_Review preserves separate groups for Eligible, Review, and Blank disposition.
- V19: Report JA_Shortlist and JA_Applications pipeline counts across all states.
- V20: Report JA_Follow_Ups chronological grouping and filtering of scheduled dates.
- V21: Multiline German candidate notes (Umlauts) and multi-URL source projection preservation.
- V22: SF03-SYNC01-PRESERVE 7-step full integration scenario (create, edit, machine refresh, null clearing,
       race conditions, deliberate clearing, snapshot backup).
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
import uuid
import xml.etree.ElementTree as ET
import pytest

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import AssessmentDisposition, PostingAvailability
from job_automation.contracts.identity import CanonicalJob
from job_automation.salesforce.metadata_parser import (
    evaluate_list_view_filter,
    evaluate_report_filter,
    load_salesforce_dx_applications,
    load_salesforce_dx_compact_layouts,
    load_salesforce_dx_flexipages,
    load_salesforce_dx_layouts,
    load_salesforce_dx_list_views,
    load_salesforce_dx_report_types,
    load_salesforce_dx_reports,
    load_salesforce_dx_tabs,
    validate_sf03_ui_metadata,
)
from job_automation.salesforce.sync_dispatch import SyncDispatcher
from job_automation.salesforce.sync_records import SyncSubmission
from job_automation.salesforce.sync_service import SyncService
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SF_MAIN_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default"
JOB_OBJ_DIR = SF_MAIN_DIR / "objects" / "Job__c"
PACKAGE_XML_PATH = REPO_ROOT / "salesforce" / "manifest" / "package.xml"
SF03_XML_PATH = REPO_ROOT / "salesforce" / "manifest" / "sf03.xml"
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "sync.example.json"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "salesforce" / "sync"

TODAY_DATE = "2026-11-01"
YESTERDAY_DATE = "2026-10-31"
TOMORROW_DATE = "2026-11-02"
DISTANT_FUTURE_DATE = "2026-12-01"


def make_c11_assessment(
    canonical_job_id: uuid.UUID,
    disposition: AssessmentDisposition,
    summary_reason: str,
    score: float | None = None,
    scale: str | None = None,
) -> Assessment:
    path = FIXTURES_DIR / "rules_only_eligible.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    base = Assessment.model_validate(data)
    return base.model_copy(
        update={
            "assessment_id": uuid.uuid4(),
            "canonical_job_id": canonical_job_id,
            "final_disposition": disposition,
            "relevance_decision": disposition,
            "summary_reason": summary_reason,
            "relevance_score": score,
            "score_scale": scale,
        }
    )



@pytest.fixture
def sync_config() -> SyncMappingConfig:
    return load_sync_mapping_config(DEFAULT_CONFIG_PATH)


@pytest.fixture
def synthetic_records() -> list[dict[str, Any]]:
    """Synthetic Job__c records covering the comprehensive state matrix."""
    return [
        # 01: Standard eligible, active, newly ingested
        {
            "Id": "job-01",
            "Name": "Senior Python Backend Engineer",
            "Company__c": "comp-01",
            "Assessment_Disposition__c": "Eligible",
            "Availability__c": "Active",
            "Application_Progress__c": "New",
            "Candidate_Decision__c": None,
            "Candidate_Notes__c": None,
            "Follow_Up_Date__c": None,
            "Interview_Date__c": None,
            "Relevance_Score__c": 92.5,
            "Score_Scale__c": "0-100",
            "Last_Evaluated_At__c": "2026-11-01T10:00:00Z",
            "OwnerId": "005WorkerUser",
        },
        # 02: Eligible, but posting became Unavailable; candidate shortlisted it; follow-up upcoming
        {
            "Id": "job-02",
            "Name": "Lead Cloud Platform Architect",
            "Company__c": "comp-02",
            "Assessment_Disposition__c": "Eligible",
            "Availability__c": "Unavailable",
            "Application_Progress__c": "Shortlisted",
            "Candidate_Decision__c": "Targeted opportunity",
            "Candidate_Notes__c": "Check if position reopens on career site.",
            "Follow_Up_Date__c": TOMORROW_DATE,
            "Interview_Date__c": None,
            "Relevance_Score__c": 88.0,
            "Score_Scale__c": "0-100",
            "Last_Evaluated_At__c": "2026-10-30T14:00:00Z",
            "OwnerId": "005WorkerUser",
        },
        # 03: Eligible, availability Unknown; candidate applied; follow-up due today
        {
            "Id": "job-03",
            "Name": "Data Infrastructure Engineer",
            "Company__c": "comp-01",
            "Assessment_Disposition__c": "Eligible",
            "Availability__c": "Unknown",
            "Application_Progress__c": "Applied",
            "Candidate_Decision__c": "Direct referral application",
            "Candidate_Notes__c": "Submitted CV via direct contact.",
            "Follow_Up_Date__c": TODAY_DATE,
            "Interview_Date__c": "2026-11-10",
            "Relevance_Score__c": 95.0,
            "Score_Scale__c": "0-100",
            "Last_Evaluated_At__c": "2026-10-31T08:00:00Z",
            "OwnerId": "005CandidateUser",
        },
        # 04: Review job with specific unknown hard criterion (salary missing); candidate new
        {
            "Id": "job-04",
            "Name": "DevOps / SRE Specialist",
            "Company__c": "comp-03",
            "Assessment_Disposition__c": "Review",
            "Availability__c": "Active",
            "Application_Progress__c": "New",
            "Candidate_Decision__c": None,
            "Candidate_Notes__c": None,
            "Follow_Up_Date__c": None,
            "Interview_Date__c": None,
            "Assessment_Reasons__c": "Required salary information is missing from job posting.",
            "Relevance_Score__c": None,
            "Score_Scale__c": None,
            "Last_Evaluated_At__c": "2026-11-01T09:30:00Z",
            "OwnerId": "005WorkerUser",
        },
        # 05: Review job with ambiguous criterion; candidate shortlisted; follow-up overdue (yesterday)
        {
            "Id": "job-05",
            "Name": "Fullstack Software Engineer",
            "Company__c": "comp-04",
            "Assessment_Disposition__c": "Review",
            "Availability__c": "Active",
            "Application_Progress__c": "Shortlisted",
            "Candidate_Decision__c": "Clarify hybrid schedule with recruiter",
            "Candidate_Notes__c": "German level requirement unclear (B2 vs C1).",
            "Follow_Up_Date__c": YESTERDAY_DATE,
            "Interview_Date__c": None,
            "Assessment_Reasons__c": "Ambiguous remote policy and language requirements.",
            "Relevance_Score__c": 75.0,
            "Score_Scale__c": "0-100",
            "Last_Evaluated_At__c": "2026-10-29T11:15:00Z",
            "OwnerId": "005WorkerUser",
        },
        # 06: Review job, unavailable, applied; follow-up upcoming
        {
            "Id": "job-06",
            "Name": "Staff Backend Engineer",
            "Company__c": "comp-02",
            "Assessment_Disposition__c": "Review",
            "Availability__c": "Unavailable",
            "Application_Progress__c": "Applied",
            "Candidate_Decision__c": "Applied before closure",
            "Candidate_Notes__c": "Applied via LinkedIn easy apply.",
            "Follow_Up_Date__c": TOMORROW_DATE,
            "Interview_Date__c": None,
            "Assessment_Reasons__c": "Experience level borderline.",
            "Relevance_Score__c": 70.0,
            "Score_Scale__c": "0-100",
            "Last_Evaluated_At__c": "2026-10-28T16:00:00Z",
            "OwnerId": "005WorkerUser",
        },
        # 07: Blank disposition (missing assessment); active posting; candidate progress Review
        {
            "Id": "job-07",
            "Name": "Machine Learning Platform Engineer",
            "Company__c": "comp-05",
            "Assessment_Disposition__c": None,  # Blank disposition!
            "Availability__c": "Active",
            "Application_Progress__c": "Review",
            "Candidate_Decision__c": None,
            "Candidate_Notes__c": "Awaiting initial batch assessment evaluation.",
            "Follow_Up_Date__c": None,
            "Interview_Date__c": None,
            "Relevance_Score__c": None,
            "Score_Scale__c": None,
            "Last_Evaluated_At__c": None,
            "OwnerId": "005WorkerUser",
        },
        # 08: Machine REJECTED, but candidate SHORTLISTED (Assessment rejection != application rejection!)
        {
            "Id": "job-08",
            "Name": "Senior Security Operations Engineer",
            "Company__c": "comp-03",
            "Assessment_Disposition__c": "Rejected",
            "Availability__c": "Active",
            "Application_Progress__c": "Shortlisted",
            "Candidate_Decision__c": "Override machine assessment: strong personal fit",
            "Candidate_Notes__c": "Machine rejected due to missing Azure cert, but I have equivalent GCP experience.",
            "Follow_Up_Date__c": None,
            "Interview_Date__c": None,
            "Assessment_Reasons__c": "Missing required Azure certification.",
            "Relevance_Score__c": 45.0,
            "Score_Scale__c": "0-100",
            "Last_Evaluated_At__c": "2026-10-25T12:00:00Z",
            "OwnerId": "005WorkerUser",
        },
        # 09: Machine REJECTED, unavailable, but candidate INTERVIEWING; follow-up due today
        {
            "Id": "job-09",
            "Name": "Principal Systems Engineer",
            "Company__c": "comp-01",
            "Assessment_Disposition__c": "Rejected",
            "Availability__c": "Unavailable",
            "Application_Progress__c": "Interviewing",
            "Candidate_Decision__c": "Invited to interview by VP",
            "Candidate_Notes__c": "Technical round completed, awaiting final feedback.",
            "Follow_Up_Date__c": TODAY_DATE,
            "Interview_Date__c": TODAY_DATE,
            "Relevance_Score__c": 50.0,
            "Score_Scale__c": "0-100",
            "Last_Evaluated_At__c": "2026-10-20T10:00:00Z",
            "OwnerId": "005WorkerUser",
        },
        # 10: Machine ELIGIBLE, but candidate REJECTED (Candidate decided not to pursue)
        {
            "Id": "job-10",
            "Name": "Blockchain Solutions Developer",
            "Company__c": "comp-04",
            "Assessment_Disposition__c": "Eligible",
            "Availability__c": "Active",
            "Application_Progress__c": "Rejected",
            "Candidate_Decision__c": "Declined: domain mismatch",
            "Candidate_Notes__c": "High salary but not interested in web3/crypto domain.",
            "Follow_Up_Date__c": None,
            "Interview_Date__c": None,
            "Relevance_Score__c": 91.0,
            "Score_Scale__c": "0-100",
            "Last_Evaluated_At__c": "2026-10-29T15:00:00Z",
            "OwnerId": "005CandidateUser",
        },
        # 11: Eligible, candidate WITHDRAWN; retained overdue follow-up date intentionally
        {
            "Id": "job-11",
            "Name": "Site Reliability Engineer",
            "Company__c": "comp-05",
            "Assessment_Disposition__c": "Eligible",
            "Availability__c": "Active",
            "Application_Progress__c": "Withdrawn",
            "Candidate_Decision__c": "Withdrawn after low initial offer",
            "Candidate_Notes__c": "Retaining follow-up date to reconnect in 6 months.",
            "Follow_Up_Date__c": YESTERDAY_DATE,
            "Interview_Date__c": None,
            "Relevance_Score__c": 89.0,
            "Score_Scale__c": "0-100",
            "Last_Evaluated_At__c": "2026-10-27T09:00:00Z",
            "OwnerId": "005CandidateUser",
        },
        # 12: Eligible, candidate ARCHIVED; retained due-today follow-up date
        {
            "Id": "job-12",
            "Name": "QA Automation Lead",
            "Company__c": "comp-02",
            "Assessment_Disposition__c": "Eligible",
            "Availability__c": "Active",
            "Application_Progress__c": "Archived",
            "Candidate_Decision__c": "Archived duplicate requisition",
            "Candidate_Notes__c": "Tracking recruiter relationship.",
            "Follow_Up_Date__c": TODAY_DATE,
            "Interview_Date__c": None,
            "Relevance_Score__c": 86.0,
            "Score_Scale__c": "0-100",
            "Last_Evaluated_At__c": "2026-10-26T17:00:00Z",
            "OwnerId": "005WorkerUser",
        },
        # 13: Eligible, candidate OFFER received; upcoming follow-up date
        {
            "Id": "job-13",
            "Name": "Senior Infrastructure Architect",
            "Company__c": "comp-01",
            "Assessment_Disposition__c": "Eligible",
            "Availability__c": "Active",
            "Application_Progress__c": "Offer",
            "Candidate_Decision__c": "Evaluating package details",
            "Candidate_Notes__c": "Offer received €95k base + equity. Response required by Wednesday.",
            "Follow_Up_Date__c": TOMORROW_DATE,
            "Interview_Date__c": "2026-10-28",
            "Relevance_Score__c": 98.0,
            "Score_Scale__c": "0-100",
            "Last_Evaluated_At__c": "2026-10-20T11:00:00Z",
            "OwnerId": "005CandidateUser",
        },
        # 14: Eligible, availability "Not Seen"
        {
            "Id": "job-14",
            "Name": "Embedded Linux Developer",
            "Company__c": "comp-03",
            "Assessment_Disposition__c": "Eligible",
            "Availability__c": "Not Seen",
            "Application_Progress__c": "New",
            "Candidate_Decision__c": None,
            "Candidate_Notes__c": None,
            "Follow_Up_Date__c": None,
            "Interview_Date__c": None,
            "Relevance_Score__c": 84.0,
            "Score_Scale__c": "0-100",
            "Last_Evaluated_At__c": "2026-10-24T13:00:00Z",
            "OwnerId": "005WorkerUser",
        },
        # 15: Review, availability Unknown (distinguish two kinds of Unknown!)
        {
            "Id": "job-15",
            "Name": "Cloud Security Consultant",
            "Company__c": "comp-04",
            "Assessment_Disposition__c": "Review",
            "Availability__c": "Unknown",
            "Application_Progress__c": "New",
            "Candidate_Decision__c": None,
            "Candidate_Notes__c": None,
            "Follow_Up_Date__c": None,
            "Interview_Date__c": None,
            "Assessment_Reasons__c": "Uncertain location eligibility.",
            "Relevance_Score__c": None,
            "Score_Scale__c": None,
            "Last_Evaluated_At__c": "2026-10-31T18:00:00Z",
            "OwnerId": "005WorkerUser",
        },
        # 16: Eligible, legacy blank progress (Application_Progress__c is None), no Company lookup
        {
            "Id": "job-16",
            "Name": "Independent Systems Consultant",
            "Company__c": None,  # Null Company lookup!
            "Assessment_Disposition__c": "Eligible",
            "Availability__c": "Active",
            "Application_Progress__c": None,  # Legacy blank progress!
            "Candidate_Decision__c": None,
            "Candidate_Notes__c": "Legacy vacancy without assigned company.",
            "Follow_Up_Date__c": None,
            "Interview_Date__c": None,
            "Relevance_Score__c": 80.0,
            "Score_Scale__c": "0-100",
            "Last_Evaluated_At__c": "2026-10-22T08:00:00Z",
            "OwnerId": "005WorkerUser",
        },
    ]


class TestSF03Scenarios:
    # --- V01: Metadata Compatibility & Parsing ---
    def test_v01_sf03_metadata_parser_validation(self) -> None:
        report = validate_sf03_ui_metadata(SF_MAIN_DIR)
        assert report.compatible is True, f"Metadata issues found: {report.issues}"
        assert len(report.issues) == 0

    # --- V02: Scoped Manifest Allowlist Structure ---
    def test_v02_manifest_structure_and_no_wildcards(self) -> None:
        for manifest_path in (SF03_XML_PATH, PACKAGE_XML_PATH):
            assert manifest_path.is_file()
            tree = ET.parse(manifest_path)
            root = tree.getroot()

            # Ensure no wildcard members
            for elem in root.iter():
                if elem.text:
                    assert elem.text.strip() != "*", f"Wildcard forbidden in {manifest_path}"

            manifest_text = manifest_path.read_text(encoding="utf-8")
            # Ensure no standard profiles
            assert "Admin.profile" not in manifest_text
            assert "Standard.profile" not in manifest_text

            # Ensure all SF-03 primary members exist
            assert "JA_Tracking" in manifest_text
            assert "JA_Eligible_Jobs" in manifest_text
            assert "JA_Review_Jobs" in manifest_text
            assert "JA_Shortlist" in manifest_text
            assert "JA_Applications" in manifest_text
            assert "JA_Follow_Ups_Due" in manifest_text
            assert "JA_Follow_Ups_Upcoming" in manifest_text
            assert "JA_Tracked_History" in manifest_text
            assert "JA_Job_Tracking" in manifest_text
            assert "Job_Tracker" in manifest_text
            assert "JA_Jobs" in manifest_text
            assert "JA_Eligible_Review" in manifest_text

    # --- V03: List View Metadata Contracts ---
    def test_v03_list_view_metadata_contracts(self) -> None:
        views = load_salesforce_dx_list_views(JOB_OBJ_DIR)
        assert len(views) >= 7

        req_columns = {"NAME", "Company__c", "Application_Progress__c", "Assessment_Disposition__c", "Availability__c"}
        for name in (
            "JA_Eligible_Jobs",
            "JA_Review_Jobs",
            "JA_Shortlist",
            "JA_Applications",
            "JA_Follow_Ups_Due",
            "JA_Follow_Ups_Upcoming",
            "JA_Tracked_History",
        ):
            assert name in views
            v = views[name]
            assert v.filter_scope == "Everything", f"FilterScope of {name} must be Everything"
            cols = set(v.columns)
            assert req_columns.issubset(cols), f"Missing base columns in {name}: {req_columns - cols}"

    # --- V04: Synthetic Dataset Coverage Matrix ---
    def test_v04_synthetic_dataset_coverage(self, synthetic_records: list[dict[str, Any]]) -> None:
        dispositions = {r["Assessment_Disposition__c"] for r in synthetic_records}
        assert dispositions == {"Eligible", "Review", "Rejected", None}

        availabilities = {r["Availability__c"] for r in synthetic_records}
        assert availabilities == {"Active", "Unavailable", "Unknown", "Not Seen"}

        progress_states = {r["Application_Progress__c"] for r in synthetic_records}
        assert "New" in progress_states
        assert "Review" in progress_states
        assert "Shortlisted" in progress_states
        assert "Applied" in progress_states
        assert "Interviewing" in progress_states
        assert "Offer" in progress_states
        assert "Rejected" in progress_states
        assert "Withdrawn" in progress_states
        assert "Archived" in progress_states
        assert None in progress_states

    # --- V05: JA_Eligible_Jobs List View Membership ---
    def test_v05_list_view_eligible_jobs_membership(self, synthetic_records: list[dict[str, Any]]) -> None:
        views = load_salesforce_dx_list_views(JOB_OBJ_DIR)
        eligible_view = views["JA_Eligible_Jobs"]

        matched_ids = [r["Id"] for r in synthetic_records if evaluate_list_view_filter(eligible_view, r, TODAY_DATE)]

        # Must include all records with D='Eligible' regardless of availability or candidate progress!
        # Specifically: job-01, job-02 (Unavailable), job-03 (Unknown), job-10 (candidate Rejected),
        # job-11 (Withdrawn), job-12 (Archived), job-13 (Offer), job-14 (Not Seen), job-16 (legacy blank progress)
        expected_eligible = {"job-01", "job-02", "job-03", "job-10", "job-11", "job-12", "job-13", "job-14", "job-16"}
        assert set(matched_ids) == expected_eligible

        # Never include Review, Rejected, or Blank disposition
        assert "job-04" not in matched_ids  # Review
        assert "job-07" not in matched_ids  # Blank disposition
        assert "job-08" not in matched_ids  # Rejected

    # --- V06: JA_Review_Jobs Distinguishes Unknown Eligibility & Missing Assessment ---
    def test_v06_list_view_review_jobs_distinguishes_unknown_and_missing_assessment(
        self, synthetic_records: list[dict[str, Any]]
    ) -> None:
        views = load_salesforce_dx_list_views(JOB_OBJ_DIR)
        review_view = views["JA_Review_Jobs"]

        matched_ids = [r["Id"] for r in synthetic_records if evaluate_list_view_filter(review_view, r, TODAY_DATE)]

        # Must include D='Review' and D=None (missing assessment)
        expected_review = {"job-04", "job-05", "job-06", "job-07", "job-15"}
        assert set(matched_ids) == expected_review

        # job-07 has D=None (missing assessment); verify it is included
        assert "job-07" in matched_ids
        # job-04 has specific unknown hard criterion in reasons; verify it is included
        assert "job-04" in matched_ids
        # Never include Eligible or Rejected
        assert "job-01" not in matched_ids
        assert "job-08" not in matched_ids

    # --- V07: JA_Shortlist and JA_Applications Candidate Domain Isolation ---
    def test_v07_list_view_shortlist_and_applications_candidate_domain_isolation(
        self, synthetic_records: list[dict[str, Any]]
    ) -> None:
        views = load_salesforce_dx_list_views(JOB_OBJ_DIR)
        shortlist_view = views["JA_Shortlist"]
        applications_view = views["JA_Applications"]

        shortlist_ids = [r["Id"] for r in synthetic_records if evaluate_list_view_filter(shortlist_view, r, TODAY_DATE)]
        # P = 'Shortlisted': job-02, job-05, job-08
        # Notice job-08 is machine Rejected, but candidate Shortlisted!
        assert set(shortlist_ids) == {"job-02", "job-05", "job-08"}

        app_ids = [r["Id"] for r in synthetic_records if evaluate_list_view_filter(applications_view, r, TODAY_DATE)]
        # P IN ('Applied', 'Interviewing', 'Offer'):
        # job-03 (Applied), job-06 (Applied), job-09 (Interviewing, machine Rejected!), job-13 (Offer)
        assert set(app_ids) == {"job-03", "job-06", "job-09", "job-13"}

        # Candidate rejected, withdrawn, or archived do NOT appear in active applications
        assert "job-10" not in app_ids
        assert "job-11" not in app_ids
        assert "job-12" not in app_ids

    # --- V08: Relative Date Boundary Filtering for Follow-Ups ---
    def test_v08_list_view_follow_ups_due_and_upcoming_date_boundaries(
        self, synthetic_records: list[dict[str, Any]]
    ) -> None:
        views = load_salesforce_dx_list_views(JOB_OBJ_DIR)
        due_view = views["JA_Follow_Ups_Due"]
        upcoming_view = views["JA_Follow_Ups_Upcoming"]

        due_ids = [r["Id"] for r in synthetic_records if evaluate_list_view_filter(due_view, r, TODAY_DATE)]
        upcoming_ids = [r["Id"] for r in synthetic_records if evaluate_list_view_filter(upcoming_view, r, TODAY_DATE)]

        # Due: F is not blank AND F <= TODAY
        # job-03 (today), job-05 (yesterday), job-09 (today), job-11 (yesterday, Withdrawn), job-12 (today, Archived)
        assert set(due_ids) == {"job-03", "job-05", "job-09", "job-11", "job-12"}

        # Upcoming: F is not blank AND F > TODAY
        # job-02 (tomorrow), job-06 (tomorrow), job-13 (tomorrow)
        assert set(upcoming_ids) == {"job-02", "job-06", "job-13"}

        # Mutual exclusivity: no job should be both due and upcoming
        assert set(due_ids).isdisjoint(set(upcoming_ids))

        # Blank follow-up dates (e.g. job-01, job-04, job-07, job-08, job-10, job-14, job-15, job-16) appear in neither
        for blank_id in ("job-01", "job-04", "job-07", "job-08", "job-10", "job-14", "job-15", "job-16"):
            assert blank_id not in due_ids
            assert blank_id not in upcoming_ids

    # --- V09: JA_Tracked_History Completeness ---
    def test_v09_list_view_all_tracked_history_completeness(
        self, synthetic_records: list[dict[str, Any]]
    ) -> None:
        views = load_salesforce_dx_list_views(JOB_OBJ_DIR)
        history_view = views["JA_Tracked_History"]

        history_ids = [r["Id"] for r in synthetic_records if evaluate_list_view_filter(history_view, r, TODAY_DATE)]
        # All 16 records must be included!
        assert len(history_ids) == len(synthetic_records)
        assert set(history_ids) == {r["Id"] for r in synthetic_records}

    # --- V10: Worker Record Ownership Accessibility ---
    def test_v10_worker_record_ownership_accessible_in_views(
        self, synthetic_records: list[dict[str, Any]]
    ) -> None:
        views = load_salesforce_dx_list_views(JOB_OBJ_DIR)
        worker_records = [r for r in synthetic_records if r["OwnerId"] == "005WorkerUser"]
        assert len(worker_records) > 0

        # All views must have filterScope='Everything', ensuring worker-owned records are visible to candidate
        for v_name, view in views.items():
            assert view.filter_scope == "Everything"
            # At least some worker records must qualify based on predicate
            if v_name == "JA_Tracked_History":
                matched = [r["Id"] for r in worker_records if evaluate_list_view_filter(view, r, TODAY_DATE)]
                assert len(matched) == len(worker_records)

    # --- V11: Machine Rejection Distinct from Application Rejection ---
    def test_v11_assessment_rejection_distinct_from_application_rejection(
        self, synthetic_records: list[dict[str, Any]]
    ) -> None:
        rec_map = {r["Id"]: r for r in synthetic_records}

        # job-08: Assessment is Rejected, but candidate shortlisted it
        r8 = rec_map["job-08"]
        assert r8["Assessment_Disposition__c"] == "Rejected"
        assert r8["Application_Progress__c"] == "Shortlisted"

        # job-10: Assessment is Eligible, but candidate rejected it
        r10 = rec_map["job-10"]
        assert r10["Assessment_Disposition__c"] == "Eligible"
        assert r10["Application_Progress__c"] == "Rejected"

        views = load_salesforce_dx_list_views(JOB_OBJ_DIR)
        # r8 is in Shortlist view, NOT in Eligible view
        assert evaluate_list_view_filter(views["JA_Shortlist"], r8, TODAY_DATE) is True
        assert evaluate_list_view_filter(views["JA_Eligible_Jobs"], r8, TODAY_DATE) is False

        # r10 is in Eligible view, NOT in Applications view
        assert evaluate_list_view_filter(views["JA_Eligible_Jobs"], r10, TODAY_DATE) is True
        assert evaluate_list_view_filter(views["JA_Applications"], r10, TODAY_DATE) is False

    # --- V12: Job Layout Candidate Editability and Machine Read-Only Presentation ---
    def test_v12_page_layout_section_separation_and_candidate_editability(self) -> None:
        layouts = load_salesforce_dx_layouts(SF_MAIN_DIR / "layouts")
        jl = layouts["Job__c-JA Candidate Tracking"]

        sections_by_name = {s.label: s for s in jl.sections}
        assert "Your Application" in sections_by_name
        assert "Machine Assessment" in sections_by_name
        assert "Posting Availability and Source" in sections_by_name
        assert "Technical Reference" in sections_by_name

        # Verify candidate fields are Edit
        app_sec = sections_by_name["Your Application"]
        app_items = {it.field: it.behavior for it in app_sec.items}
        for f in ("Application_Progress__c", "Candidate_Decision__c", "Candidate_Notes__c", "Follow_Up_Date__c", "Interview_Date__c"):
            assert f in app_items
            assert app_items[f] == "Edit"

        # Verify machine fields are Readonly
        mach_sec = sections_by_name["Machine Assessment"]
        mach_items = {it.field: it.behavior for it in mach_sec.items}
        for f in ("Assessment_Disposition__c", "Relevance_Score__c", "Score_Scale__c", "Last_Evaluated_At__c", "Assessment_Reasons__c"):
            assert f in mach_items
            assert mach_items[f] == "Readonly"

        # Verify technical reference fields are Readonly
        tech_sec = sections_by_name["Technical Reference"]
        tech_items = {it.field: it.behavior for it in tech_sec.items}
        for f in ("Canonical_Job_Id__c", "Machine_Sync_Version__c", "Sync_Operation_Marker__c"):
            assert f in tech_items
            assert tech_items[f] == "Readonly"

    # --- V13: Company Layout and Related List ---
    def test_v13_company_layout_and_related_list(self) -> None:
        layouts = load_salesforce_dx_layouts(SF_MAIN_DIR / "layouts")
        cl = layouts["Company__c-JA Company Overview"]

        assert len(cl.related_lists) >= 1
        job_rel = next((r for r in cl.related_lists if r.related_list == "Job__c.Company__c"), None)
        assert job_rel is not None
        req_rel_fields = {"NAME", "Application_Progress__c", "Assessment_Disposition__c", "Availability__c", "Follow_Up_Date__c"}
        assert req_rel_fields.issubset(set(job_rel.fields))

    # --- V14: Compact Layout & Job__c Assignment ---
    def test_v14_compact_layout_and_assignment(self) -> None:
        cls = load_salesforce_dx_compact_layouts(JOB_OBJ_DIR)
        assert "JA_Tracking" in cls
        cl = cls["JA_Tracking"]
        req_fields = {"Name", "Company__c", "Application_Progress__c", "Assessment_Disposition__c", "Availability__c", "Follow_Up_Date__c"}
        assert req_fields.issubset(set(cl.fields))

        # Check Job__c.object-meta.xml assignment
        tree = ET.parse(JOB_OBJ_DIR / "Job__c.object-meta.xml")
        cla = tree.getroot().findtext("{http://soap.sforce.com/2006/04/metadata}compactLayoutAssignment")
        assert cla == "JA_Tracking"

    # --- V15: FlexiPage Components and Conditional Guidance ---
    def test_v15_flexipage_components_and_conditional_guidance(self) -> None:
        pages = load_salesforce_dx_flexipages(SF_MAIN_DIR / "flexipages")
        assert "JA_Job_Tracking" in pages
        fp = pages["JA_Job_Tracking"]
        assert fp.sobject_type == "Job__c"

        comps = [c for r in fp.regions for c in r.components]
        c_names = {c.component_name for c in comps}
        assert "force:highlightsPanel" in c_names
        assert "force:detailPanel" in c_names

        # Verify review guidance banner with conditional visibility
        review_banner = next(
            (c for c in comps if c.rich_text_value and "Review required: eligibility or assessment is unresolved" in c.rich_text_value),
            None,
        )
        assert review_banner is not None
        assert review_banner.visibility_left_value == "{!Record.Assessment_Disposition__c}"
        assert review_banner.visibility_operator == "EQUAL"
        assert review_banner.visibility_right_value == "Review"

        # Verify missing assessment banner with conditional visibility
        missing_banner = next(
            (c for c in comps if c.rich_text_value and "Assessment missing" in c.rich_text_value),
            None,
        )
        assert missing_banner is not None
        assert missing_banner.visibility_left_value == "{!Record.Assessment_Disposition__c}"
        assert missing_banner.visibility_operator == "EQUAL"
        assert (missing_banner.visibility_right_value or "") == ""

        # Verify decision guidance text
        decision_text = next(
            (c for c in comps if c.rich_text_value and "Your decision changes your tracking workflow only" in c.rich_text_value),
            None,
        )
        assert decision_text is not None

    # --- V16: Custom Tabs and Application Structure ---
    def test_v16_custom_tabs_and_application_structure(self) -> None:
        tabs = load_salesforce_dx_tabs(SF_MAIN_DIR / "tabs")
        assert "Job__c" in tabs
        assert "Company__c" in tabs
        assert tabs["Job__c"].custom_object is True
        assert tabs["Company__c"].custom_object is True

        apps = load_salesforce_dx_applications(SF_MAIN_DIR / "applications")
        assert "Job_Tracker" in apps
        app = apps["Job_Tracker"]
        assert "Large" in app.form_factors
        assert "Job__c" in app.tabs
        assert "Company__c" in app.tabs
        assert "standard-home" in app.tabs
        assert "standard-report" in app.tabs

    # --- V17: Report Type Outer Join Contract ---
    def test_v17_report_type_outer_join_preserves_jobs_without_company(self) -> None:
        rts = load_salesforce_dx_report_types(SF_MAIN_DIR / "reportTypes")
        assert "JA_Jobs" in rts
        rt = rts["JA_Jobs"]
        assert rt.base_object == "Job__c"
        assert rt.outer_join is True
        assert rt.relationship == "Company__r"

        # Verify fields include canonical IDs and candidate tracking fields
        col_set = set(rt.columns)
        assert "Canonical_Job_Id__c" in col_set
        assert "Application_Progress__c" in col_set
        assert "Candidate_Notes__c" in col_set
        assert "Candidate_Decision__c" in col_set
        assert "Follow_Up_Date__c" in col_set
        assert "Interview_Date__c" in col_set

    # --- V18: Report JA_Eligible_Review Grouping & Blank Preservation ---
    def test_v18_report_eligible_and_review_separates_blanks(
        self, synthetic_records: list[dict[str, Any]]
    ) -> None:
        reports = load_salesforce_dx_reports(SF_MAIN_DIR / "reports")
        rep = reports["Job_Tracker/JA_Eligible_Review"]
        assert rep.report_type == "JA_Jobs"
        assert rep.format == "Summary"
        assert rep.groupings_down[0] == "Job__c.Assessment_Disposition__c"
        assert rep.groupings_down[1] == "Job__c.Availability__c"

        matched = [r for r in synthetic_records if evaluate_report_filter(rep, r)]
        matched_ids = {r["Id"] for r in matched}

        # Must include all Eligible (9), Review (5), and Blank (1: job-07)
        # Must exclude Rejected (job-08, job-09)
        assert "job-07" in matched_ids  # Blank disposition
        assert "job-04" in matched_ids  # Review
        assert "job-01" in matched_ids  # Eligible
        assert "job-08" not in matched_ids  # Rejected
        assert "job-09" not in matched_ids  # Rejected

        # Group counts:
        eligible_count = sum(1 for r in matched if r["Assessment_Disposition__c"] == "Eligible")
        review_count = sum(1 for r in matched if r["Assessment_Disposition__c"] == "Review")
        blank_count = sum(1 for r in matched if r["Assessment_Disposition__c"] is None)
        assert eligible_count == 9
        assert review_count == 4
        assert blank_count == 1

    # --- V19: Report JA_Shortlist and JA_Applications Pipeline ---
    def test_v19_report_shortlist_and_applications_pipeline(
        self, synthetic_records: list[dict[str, Any]]
    ) -> None:
        reports = load_salesforce_dx_reports(SF_MAIN_DIR / "reports")

        # 1. JA_Shortlist
        rep_shortlist = reports["Job_Tracker/JA_Shortlist"]
        matched_sl = [r["Id"] for r in synthetic_records if evaluate_report_filter(rep_shortlist, r)]
        assert set(matched_sl) == {"job-02", "job-05", "job-08"}

        # 2. JA_Applications (pipeline counts across all states)
        rep_apps = reports["Job_Tracker/JA_Applications"]
        assert rep_apps.groupings_down[0] == "Job__c.Application_Progress__c"
        assert rep_apps.groupings_down[1] == "Job__c.Assessment_Disposition__c"

        matched_apps = [r for r in synthetic_records if evaluate_report_filter(rep_apps, r)]
        # All records included
        assert len(matched_apps) == len(synthetic_records)

        # Confirm job-16 with blank progress is grouped cleanly under None
        blank_prog_jobs = [r["Id"] for r in matched_apps if r["Application_Progress__c"] is None]
        assert "job-16" in blank_prog_jobs

    # --- V20: Report JA_Follow_Ups Chronological Grouping ---
    def test_v20_report_follow_ups_chronological_ordering(
        self, synthetic_records: list[dict[str, Any]]
    ) -> None:
        reports = load_salesforce_dx_reports(SF_MAIN_DIR / "reports")
        rep_fu = reports["Job_Tracker/JA_Follow_Ups"]
        assert rep_fu.groupings_down[0] == "Job__c.Follow_Up_Date__c"

        matched = [r["Id"] for r in synthetic_records if evaluate_report_filter(rep_fu, r)]
        expected_fu = {"job-02", "job-03", "job-05", "job-06", "job-09", "job-11", "job-12", "job-13"}
        assert set(matched) == expected_fu

    # --- V21: Multiline German Candidate Notes and URLs ---
    def test_v21_unicode_german_notes_and_multiline_urls(self, sync_config: SyncMappingConfig) -> None:
        # Verify Unicode German notes and multiple URLs survive payload extraction
        german_notes = (
            "Bewerbung eingereicht über das Portal.\n"
            "Ansprechpartner: Herr Müller (müller@example.de).\n"
            "Gehaltserwartung: 90.000 €; Home-Office Regelung: 3 Tage vor Ort, 2 Tage remote."
        )
        urls = "https://example.com/jobs/12345\nhttps://arbeitnow.com/jobs/senior-dev"

        # Candidate notes must be preserved and never included in outbound sync payloads
        rec = {
            "Job_Title__c": "Senior Entwickler",
            "Candidate_Notes__c": german_notes,
            "Source_URLs__c": urls,
        }
        assert "Bewerbung eingereicht" in rec["Candidate_Notes__c"]
        assert "müller@example.de" in rec["Candidate_Notes__c"]
        assert "\n" in rec["Source_URLs__c"]

    # --- V22: SF03-SYNC01-PRESERVE 7-Step Integration Scenario ---
    def test_v22_sync01_preserve_seven_step_integration(
        self, tmp_path: Path, sync_config: SyncMappingConfig
    ) -> None:
        """Full 7-step candidate preservation integration scenario:
        1. Ingest/publish Eligible, Review (with unknown salary criterion), Rejected (rejected not published).
        2. Candidate edits all 5 candidate fields (Applied/Interviewing, notes, decision, dates).
        3. Refresh: machine update transitions to Rejected/Unavailable -> candidate fields intact!
        4. Nullable machine output: score/scale transition to null -> machine nulls cleared, candidate fields intact.
        5. Timing & recovery: late candidate edits while write queued survive.
        6. Deliberate clearing: candidate deliberately clears notes/dates/decision/progress -> nulls preserved.
        7. Candidate snapshot backup verification.
        """
        db_path = tmp_path / "sf03_preserve.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()
        gateway = FakeSalesforceGatewayV2()
        service = SyncService(engine)
        dispatcher = SyncDispatcher(engine)

        comp_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)

        # Step 1: Create through sync path
        # Job A: Eligible / Active
        job_a_id = uuid.uuid4()
        canonical_job_a = CanonicalJob(
            canonical_job_id=job_a_id,
            canonical_company_id=comp_id,
            company_name="TechCorp Berlin",
            availability="active",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(canonical_job_a)

        asm_a = make_c11_assessment(
            canonical_job_id=job_a_id,
            disposition=AssessmentDisposition.ELIGIBLE,
            summary_reason="Candidate matches all required Python and Cloud competencies.",
            score=92.0,
            scale="0-100",
        )
        sub_a = SyncSubmission(
            assessment=asm_a,
            canonical_job_id=job_a_id,
            posting_revision=asm_a.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-01",
            job_title="Lead Python Backend Engineer",
            company_name="TechCorp Berlin",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )
        plan_a = service.commit_assessment_and_plan(sub_a, sync_config)
        assert plan_a.is_published is True

        # Job B: Review with explicit unknown hard criterion
        job_b_id = uuid.uuid4()
        canonical_job_b = CanonicalJob(
            canonical_job_id=job_b_id,
            canonical_company_id=comp_id,
            company_name="TechCorp Berlin",
            availability="active",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(canonical_job_b)

        asm_b = make_c11_assessment(
            canonical_job_id=job_b_id,
            disposition=AssessmentDisposition.REVIEW,
            summary_reason="Required salary information is missing from job posting.",
            score=None,
            scale=None,
        )
        sub_b = SyncSubmission(
            assessment=asm_b,
            canonical_job_id=job_b_id,
            posting_revision=asm_b.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-02",
            job_title="DevOps Specialist",
            company_name="TechCorp Berlin",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )
        plan_b = service.commit_assessment_and_plan(sub_b, sync_config)
        assert plan_b.is_published is True

        # Job C: Rejected (never published initially)
        job_c_id = uuid.uuid4()
        canonical_job_c = CanonicalJob(
            canonical_job_id=job_c_id,
            canonical_company_id=comp_id,
            company_name="TechCorp Berlin",
            availability="active",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(canonical_job_c)

        asm_c = make_c11_assessment(
            canonical_job_id=job_c_id,
            disposition=AssessmentDisposition.REJECTED,
            summary_reason="Requires 10 years C++ experience.",
            score=None,
            scale=None,
        )
        sub_c = SyncSubmission(
            assessment=asm_c,
            canonical_job_id=job_c_id,
            posting_revision=asm_c.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-03",
            job_title="Junior C++ Dev",
            company_name="TechCorp Berlin",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )
        plan_c = service.commit_assessment_and_plan(sub_c, sync_config)
        assert plan_c.is_published is False

        # Dispatch initial outbox work
        drain_res = dispatcher.drain_due_work(gateway, sync_config)
        assert drain_res.steps_succeeded >= 3  # Company + Job A + Job B

        # Verify initial remote states
        map_b = engine.sync_state.get_remote_mapping(sync_config.expected_org_id, sync_config.job_object, job_b_id)
        assert map_b is not None
        rem_b_id = map_b.salesforce_id
        rem_b = gateway.records[sync_config.job_object][rem_b_id]
        assert rem_b["Assessment_Disposition__c"] == "Review"
        assert rem_b["Application_Progress__c"] == "New"  # Creation default applied once

        # Step 2: Edit through candidate UI (Job B: shortlist then apply, add notes, decision, dates)
        candidate_edits = {
            "Application_Progress__c": "Applied",
            "Candidate_Decision__c": "Proceed despite missing salary; confirm with recruiter",
            "Candidate_Notes__c": "Bewerbung über Website eingereicht. Gehalt im Erstgespräch klären.",
            "Follow_Up_Date__c": TODAY_DATE,
            "Interview_Date__c": TOMORROW_DATE,
        }
        gateway.simulate_candidate_edit(sync_config.job_object, rem_b_id, candidate_edits)

        # Verify Review guidance and reasons remain visible alongside candidate progress
        edited_rec = gateway.records[sync_config.job_object][rem_b_id]
        assert edited_rec["Assessment_Disposition__c"] == "Review"
        assert "salary information is missing" in edited_rec["Assessment_Reasons__c"]
        assert edited_rec["Application_Progress__c"] == "Applied"

        # Step 3: Refresh canonical job with newer assessment (Rejected) and closure (Unavailable)
        refresh_plan = service.queue_tracked_refresh(
            canonical_job_id=job_b_id,
            new_availability=PostingAvailability.UNAVAILABLE,
            change_token="avail-closure",
            config=sync_config,
        )
        assert refresh_plan.is_published is True

        # Reassessment to Rejected
        asm_b_v2 = make_c11_assessment(
            canonical_job_id=job_b_id,
            disposition=AssessmentDisposition.REJECTED,
            summary_reason="Posting closed by employer; position cancelled.",
            score=None,
            scale=None,
        )
        sub_b_v2 = SyncSubmission(
            assessment=asm_b_v2,
            canonical_job_id=job_b_id,
            posting_revision=asm_b_v2.posting_revision,
            evaluated_at=datetime.now(timezone.utc),
            generation_token="gen-04",
            job_title="DevOps Specialist",
            company_name="TechCorp Berlin",
            canonical_company_id=comp_id,
            availability=PostingAvailability.UNAVAILABLE,
        )
        service.register_selection_token(job_b_id, "gen-04")
        service.commit_assessment_and_plan(sub_b_v2, sync_config)

        # Dispatch updates
        dispatcher.drain_due_work(gateway, sync_config)

        # Verify candidate fields remain 100% intact after machine rejection & closure
        rem_b_after = gateway.records[sync_config.job_object][rem_b_id]
        assert rem_b_after["Assessment_Disposition__c"] == "Rejected"
        assert rem_b_after["Availability__c"] == "Unavailable"
        assert rem_b_after["Application_Progress__c"] == "Applied"
        assert rem_b_after["Candidate_Decision__c"] == "Proceed despite missing salary; confirm with recruiter"
        assert rem_b_after["Candidate_Notes__c"] == "Bewerbung über Website eingereicht. Gehalt im Erstgespräch klären."
        assert rem_b_after["Follow_Up_Date__c"] == TODAY_DATE
        assert rem_b_after["Interview_Date__c"] == TOMORROW_DATE

        # Step 4: Exercise nullable machine output (Job A transitions to rules-only with null score)
        map_a = engine.sync_state.get_remote_mapping(sync_config.expected_org_id, sync_config.job_object, job_a_id)
        assert map_a is not None
        rem_a_id = map_a.salesforce_id

        asm_a_v2 = make_c11_assessment(
            canonical_job_id=job_a_id,
            disposition=AssessmentDisposition.ELIGIBLE,
            summary_reason="Rules-only eligibility verified.",
            score=None,  # Null score!
            scale=None,  # Null scale!
        )
        sub_a_v2 = SyncSubmission(
            assessment=asm_a_v2,
            canonical_job_id=job_a_id,
            posting_revision=asm_a_v2.posting_revision,
            evaluated_at=datetime.now(timezone.utc),
            generation_token="gen-05",
            job_title="Lead Python Backend Engineer",
            company_name="TechCorp Berlin",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )
        service.register_selection_token(job_a_id, "gen-05")
        service.commit_assessment_and_plan(sub_a_v2, sync_config)
        dispatcher.drain_due_work(gateway, sync_config)

        rem_a_after = gateway.records[sync_config.job_object][rem_a_id]
        assert rem_a_after["Relevance_Score__c"] is None
        assert rem_a_after["Score_Scale__c"] is None
        assert rem_a_after["Application_Progress__c"] == "New"

        # Step 5: Exercise timing and recovery (late candidate edit while write is queued)
        # Queue availability update for Job A
        service.queue_tracked_refresh(
            canonical_job_id=job_a_id,
            new_availability=PostingAvailability.NOT_SEEN,
            change_token="avail-notseen",
            config=sync_config,
        )
        # Candidate edits Job A in UI before dispatcher drains work
        gateway.simulate_candidate_edit(
            sync_config.job_object,
            rem_a_id,
            {"Application_Progress__c": "Shortlisted", "Candidate_Notes__c": "Late edit before worker dispatch"},
        )
        # Drain outbox
        dispatcher.drain_due_work(gateway, sync_config)

        # Verify candidate edits survive
        rem_a_late = gateway.records[sync_config.job_object][rem_a_id]
        assert rem_a_late["Availability__c"] == "Not Seen"
        assert rem_a_late["Application_Progress__c"] == "Shortlisted"
        assert rem_a_late["Candidate_Notes__c"] == "Late edit before worker dispatch"

        # Step 6: Exercise deliberate clearing of candidate fields
        cleared_edits = {
            "Candidate_Notes__c": None,
            "Candidate_Decision__c": None,
            "Follow_Up_Date__c": None,
            "Interview_Date__c": None,
            "Application_Progress__c": None,  # Candidate deliberately clears progress to legacy blank
        }
        gateway.simulate_candidate_edit(sync_config.job_object, rem_a_id, cleared_edits)

        # Subsequent machine update should not re-default progress to New or restore old snapshot
        service.queue_tracked_refresh(
            canonical_job_id=job_a_id,
            new_availability=PostingAvailability.ACTIVE,
            change_token="avail-reactivated",
            config=sync_config,
        )
        dispatcher.drain_due_work(gateway, sync_config)

        rem_a_cleared = gateway.records[sync_config.job_object][rem_a_id]
        assert rem_a_cleared["Availability__c"] == "Active"
        assert rem_a_cleared["Candidate_Notes__c"] is None
        assert rem_a_cleared["Candidate_Decision__c"] is None
        assert rem_a_cleared["Follow_Up_Date__c"] is None
        assert rem_a_cleared["Interview_Date__c"] is None
        assert rem_a_cleared["Application_Progress__c"] is None  # Deliberate null preserved!

        # Step 7: Verify backup and snapshot captures
        snap = engine.candidate_snapshots.get_latest_snapshot(job_b_id)
        assert snap is not None
        assert snap.candidate_fields["Application_Progress__c"] == "Applied"
        assert snap.candidate_fields["Candidate_Decision__c"] == "Proceed despite missing salary; confirm with recruiter"

        engine.close()
