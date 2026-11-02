"""Tests for evaluation input controls and arm symmetry verification (EVAL-01-S04)."""

import pytest

from job_automation.evaluation.corpus import build_canonical_synthetic_cases
from job_automation.evaluation.errors import MismatchedArmControlError
from job_automation.evaluation.manifest_validation import (
    extract_arm_controls,
    validate_pair_arm_symmetry,
)
from job_automation.evaluation.records import ExperimentManifest


def test_validate_pair_arm_symmetry_passes_on_identical_controls():
    """Verify identical arm controls pass symmetry validation."""
    cases = build_canonical_synthetic_cases()
    manifest = ExperimentManifest(
        experiment_name="symmetry_test",
        case_ids=[cases[0].case_id],
        profile_snapshot_hash="hash1",
        search_policy_fingerprint="fp1",
        model_identifier="test-model",
        model_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
    )
    controls = extract_arm_controls(manifest)
    validate_pair_arm_symmetry(manifest, cases[0], controls, controls)


def test_validate_pair_arm_symmetry_detects_mismatch():
    """Verify MismatchedArmControlError is raised when any control differs between arms."""
    cases = build_canonical_synthetic_cases()
    manifest = ExperimentManifest(
        experiment_name="symmetry_test",
        case_ids=[cases[0].case_id],
        profile_snapshot_hash="hash1",
        search_policy_fingerprint="fp1",
        model_identifier="test-model",
        model_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
    )
    ctrl_json = extract_arm_controls(manifest)
    ctrl_rag = dict(ctrl_json)
    ctrl_rag["model_identifier"] = "different-model-id"

    with pytest.raises(MismatchedArmControlError, match="Control 'model_identifier' mismatch"):
        validate_pair_arm_symmetry(manifest, cases[0], ctrl_json, ctrl_rag)

