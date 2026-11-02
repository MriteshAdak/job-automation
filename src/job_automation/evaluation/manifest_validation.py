"""Control validation and arm symmetry verification for evaluation pairs (EVAL-01-S04).

Enforces:
- Profile, model, prompt, and decoding parameters are 100% identical between arms.
- Only the context strategy (JSON vs RAG) may differ.
- Any control drift raises MismatchedArmControlError before execution.
"""

from __future__ import annotations

from typing import Any

from job_automation.evaluation.errors import MismatchedArmControlError
from job_automation.evaluation.records import (
    EvaluationCase,
    ExperimentManifest,
)


def validate_pair_arm_symmetry(
    manifest: ExperimentManifest,
    case: EvaluationCase,
    json_arm_controls: dict[str, Any],
    rag_arm_controls: dict[str, Any],
) -> None:
    """Verify that both arms in a pair hold identical shared controls.

    Raises MismatchedArmControlError if any control differs.
    """
    keys_to_match = [
        "profile_snapshot_hash",
        "search_policy_fingerprint",
        "model_identifier",
        "model_digest",
        "prompt_version",
        "prompt_template_hash",
        "effective_decoding_settings",
        "schema_version",
        "context_limit",
        "output_reserve",
        "safety_allowance",
        "extractor_mode",
    ]

    for key in keys_to_match:
        val_json = json_arm_controls.get(key)
        val_rag = rag_arm_controls.get(key)
        if val_json != val_rag:
            raise MismatchedArmControlError(
                f"Control '{key}' mismatch between arms: JSON arm has '{val_json}', RAG arm has '{val_rag}'"
            )


def extract_arm_controls(manifest: ExperimentManifest) -> dict[str, Any]:
    """Extract standard control dictionary from ExperimentManifest."""
    return {
        "profile_snapshot_hash": manifest.profile_snapshot_hash,
        "search_policy_fingerprint": manifest.search_policy_fingerprint,
        "model_identifier": manifest.model_identifier,
        "model_digest": manifest.model_digest,
        "prompt_version": manifest.prompt_version,
        "prompt_template_hash": manifest.prompt_template_hash,
        "effective_decoding_settings": manifest.effective_decoding_settings,
        "schema_version": manifest.schema_version,
        "context_limit": manifest.context_limit,
        "output_reserve": manifest.output_reserve,
        "safety_allowance": manifest.safety_allowance,
        "extractor_mode": manifest.extractor_mode,
    }

