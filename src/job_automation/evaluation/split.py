"""Dataset splitting and leakage prevention (EVAL-01-S02).

Enforces:
- Group-aware partitioning: duplicate revisions, alternate source feeds, and company variants
  of the same canonical opportunity are strictly bound to one split.
- Deterministic hashing and pseudo-random seed assignment.
- Validation rejecting any cross-split leakage.
"""

from __future__ import annotations

import random
from typing import Sequence
from job_automation.evaluation.errors import CorpusSplitLeakageError
from job_automation.evaluation.records import EvaluationCase


def validate_no_split_leakage(cases: Sequence[EvaluationCase]) -> None:
    """Validate that no opportunity group or canonical job appears in multiple splits.

    Raises CorpusSplitLeakageError if leakage is detected.
    """
    group_to_splits: dict[str, set[str]] = {}
    for case in cases:
        grp = case.opportunity_group_id
        if grp not in group_to_splits:
            group_to_splits[grp] = set()
        group_to_splits[grp].add(case.split_assignment)

    leakage_groups = {grp: splits for grp, splits in group_to_splits.items() if len(splits) > 1}
    if leakage_groups:
        err_msg = ", ".join(f"Group '{g}' in {s}" for g, s in leakage_groups.items())
        raise CorpusSplitLeakageError(
            f"Cross-split leakage detected! Opportunities must not cross split boundaries: {err_msg}"
        )


def partition_cases_by_group(
    cases: Sequence[EvaluationCase],
    dev_ratio: float = 0.7,
    seed: int = 42,
) -> tuple[list[EvaluationCase], list[EvaluationCase]]:
    """Partition cases into (dev_cases, held_out_cases) by opportunity group.

    Guarantees:
    - Identical groups stay together in the same split.
    - Zero data leakage between development and held_out sets.
    """
    groups: dict[str, list[EvaluationCase]] = {}
    for c in cases:
        groups.setdefault(c.opportunity_group_id, []).append(c)

    # Sort group keys for determinism across platforms
    sorted_group_keys = sorted(groups.keys())
    rng = random.Random(seed)
    rng.shuffle(sorted_group_keys)

    num_dev_groups = int(len(sorted_group_keys) * dev_ratio)
    dev_group_set = set(sorted_group_keys[:num_dev_groups])

    dev_cases: list[EvaluationCase] = []
    held_out_cases: list[EvaluationCase] = []

    for grp_key, grp_cases in groups.items():
        target_split = "development" if grp_key in dev_group_set else "held_out"
        for c in grp_cases:
            # Create a copy with the updated split assignment
            c_dict = c.model_dump()
            c_dict["split_assignment"] = target_split
            c_dict["case_fingerprint"] = ""  # Recompute on creation
            updated_case = EvaluationCase.model_validate(c_dict)
            if target_split == "development":
                dev_cases.append(updated_case)
            else:
                held_out_cases.append(updated_case)

    # Sanity check
    all_assigned = dev_cases + held_out_cases
    validate_no_split_leakage(all_assigned)

    return dev_cases, held_out_cases

