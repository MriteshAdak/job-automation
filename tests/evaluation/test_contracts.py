"""Contract, validator, and boundary tests for EVAL-01-S01."""

import uuid
from datetime import datetime, timezone
import pytest

from job_automation.contracts.enums import (
    AssessmentDisposition,
    ContextStrategy,
    FindingStatus,
    RequirementCategory,
    RequirementObligation,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.profile import ProfileSnapshot
from job_automation.contracts.evidence import CandidateEvidenceReference, JobEvidenceReference
from job_automation.evaluation.errors import (
    MismatchedArmControlError,
    PublicationAttemptBlockedError,
)
from job_automation.evaluation.ports import (
    assert_no_publication_authority,
    sanitize_case_for_model_input,
)
from job_automation.evaluation.records import (
    ArmAttempt,
    DependencyGateRegister,
    EvaluationCase,
    ExperimentManifest,
    GoldLabelRevision,
    GoldRequirementLabel,
    PairResult,
)
from job_automation.evaluation.settings import (
    EvaluationSettings,
    PHASE1_EXTENSIONS_STATUS,
    PROPOSED_TARGETS,
)


def test_dependency_gates_default_status():
    """Verify default dependency gate register states."""
    reg = DependencyGateRegister()
    assert reg.eg1_exact_frozen_inputs.status == "SATISFIED_OFFLINE"
    assert reg.eg2_comparable_model_execution.status == "SATISFIED_OFFLINE"
    assert reg.eg3_observable_evidence.status == "SATISFIED_OFFLINE"
    assert reg.eg4_run_integration_and_isolation.status == "SATISFIED_OFFLINE"
    assert reg.eg5_live_execution.status == "PENDING_LIVE"


def test_phase1_status_is_deferred():
    """Verify Phase 1 extensions are explicitly documented as DEFERRED."""
    assert PHASE1_EXTENSIONS_STATUS == "DEFERRED"


def test_proposed_targets_labeled_as_proposed():
    """Verify proposed targets are marked PROPOSED and never as measured facts."""
    assert PROPOSED_TARGETS["target_status"] == "PROPOSED"
    assert "PROPOSED" in PROPOSED_TARGETS["target_status"]
    assert "max_false_negative_rate" in PROPOSED_TARGETS["targets"]


def test_evaluation_settings_rejects_sync():
    """Verify EvaluationSettings forbids enable_sync=True."""
    with pytest.raises(ValueError, match="enable_sync=True is strictly forbidden"):
        EvaluationSettings(
            eval_root=r"C:\fake\eval",
            enable_sync=True,
        )


def test_evaluation_settings_requires_absolute_path():
    """Verify EvaluationSettings enforces absolute eval_root path."""
    with pytest.raises(ValueError, match="must be an absolute path"):
        EvaluationSettings(
            eval_root="relative/path",
        )


def test_sanitize_case_strips_gold_labels():
    """Verify gold labels and reviewer notes are completely stripped before model execution."""
    class DummyCase:
        case_id = "case_01"
        canonical_job_id = uuid.uuid4()
        posting_revision = "rev1"
        posting = {"title": "Engineer"}
        profile = {"candidate_id": "c1"}
        policy = {"policy_version": "v1"}
        gold_label = {"disposition": "eligible"}
        tags = ["confidential"]
        notes = "Reviewer secret notes"

    sanitized = sanitize_case_for_model_input(DummyCase())
    assert "case_id" in sanitized
    assert "gold_label" not in sanitized
    assert "tags" not in sanitized
    assert "notes" not in sanitized


def test_assert_no_publication_authority():
    """Verify publication authority check triggers on sync or salesforce objects."""
    class SafeRunner:
        pass

    assert_no_publication_authority(SafeRunner())

    class UnsafeRunner:
        salesforce_gateway = object()

    with pytest.raises(PublicationAttemptBlockedError, match="unauthorized publication attribute"):
        assert_no_publication_authority(UnsafeRunner())

