"""Unit tests for dataset split assignment and leakage prevention (EVAL-01-S02)."""

import pytest

from job_automation.evaluation.corpus import build_canonical_synthetic_cases
from job_automation.evaluation.errors import CorpusSplitLeakageError
from job_automation.evaluation.records import EvaluationCase
from job_automation.evaluation.split import (
    partition_cases_by_group,
    validate_no_split_leakage,
)


def test_validate_no_split_leakage_passes_on_canonical_cases():
    """Verify canonical synthetic cases do not leak across development and held_out splits."""
    cases = build_canonical_synthetic_cases()
    validate_no_split_leakage(cases)


def test_validate_no_split_leakage_detects_group_split():
    """Verify error is raised if two cases with the same opportunity_group_id are in different splits."""
    cases = build_canonical_synthetic_cases()
    # case_01 is in "development", case_07 is a variant sharing opportunity_group_id "opp_apex_cpp_01"
    # Artificially move case_07 to "held_out"
    c7_dict = cases[6].model_dump()
    assert c7_dict["opportunity_group_id"] == "opp_apex_cpp_01"
    c7_dict["split_assignment"] = "held_out"
    c7_dict["case_fingerprint"] = ""
    modified_c7 = EvaluationCase.model_validate(c7_dict)

    leaking_cases = list(cases)
    leaking_cases[6] = modified_c7

    with pytest.raises(CorpusSplitLeakageError, match="Cross-split leakage detected"):
        validate_no_split_leakage(leaking_cases)


def test_partition_cases_by_group_respects_grouping():
    """Verify partition_cases_by_group groups variants together and produces zero leakage."""
    cases = build_canonical_synthetic_cases()
    dev_cases, held_cases = partition_cases_by_group(cases, dev_ratio=0.5, seed=123)

    assert len(dev_cases) + len(held_cases) == len(cases)
    validate_no_split_leakage(dev_cases + held_cases)

    # Verify variants of apex cpp stay together
    apex_splits = {c.split_assignment for c in (dev_cases + held_cases) if c.opportunity_group_id == "opp_apex_cpp_01"}
    assert len(apex_splits) == 1

