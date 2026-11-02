"""Deterministic fingerprint computation and canonical payload export for C02 SearchPolicy."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from job_automation.contracts.policy import HardCriterion, SearchPolicy
from job_automation.policy.models import (
    CANONICALIZATION_VERSION,
    NORMALIZATION_VERSION,
    POLICY_SCHEMA_VERSION,
    POLICY_SEMANTICS_VERSION,
    EffectiveMissingAction,
)
from job_automation.policy.vocabulary import (
    NormalizedVocabulary,
    normalize_display,
    normalize_lookup,
)


def _canonicalize_value(val: Any) -> Any:
    """Recursively canonicalize expected_value for deterministic JSON representation."""
    if isinstance(val, (int, float, Decimal)):
        if isinstance(val, (float, Decimal)):
            # Normalize float/decimal representation
            return float(val)
        return val
    elif isinstance(val, str):
        return normalize_display(val)
    elif isinstance(val, list):
        canonical_items = [_canonicalize_value(x) for x in val]
        # Sort if all items are strings for set-like collections
        if all(isinstance(x, str) for x in canonical_items):
            return sorted(canonical_items)
        return canonical_items
    elif isinstance(val, dict):
        return {k: _canonicalize_value(v) for k, v in sorted(val.items())}
    return val


def build_canonical_payload(
    policy: SearchPolicy,
    effective_missing: dict[str, EffectiveMissingAction],
    vocabulary: NormalizedVocabulary,
) -> dict[str, Any]:
    """Construct deterministic dictionary of all effective policy configuration.
    
    Excludes the authored policy_version label, file paths, mtimes, and timestamps.
    Includes effective materialized missing actions, version bindings, and sorted collections.
    """
    # Canonical role aliases by normalized canonical lookup
    role_aliases_canonical: dict[str, list[str]] = {}
    for group in sorted(vocabulary.role_groups.values(), key=lambda g: g.canonical_lookup):
        role_aliases_canonical[group.canonical_lookup] = sorted(group.aliases_lookup)

    # Canonical skill aliases by normalized canonical lookup
    skill_aliases_canonical: dict[str, list[str]] = {}
    for group in sorted(vocabulary.skill_groups.values(), key=lambda g: g.canonical_lookup):
        skill_aliases_canonical[group.canonical_lookup] = sorted(group.aliases_lookup)

    # Sorted hard criteria with effective on_missing actions
    hard_criteria_canonical: list[dict[str, Any]] = []
    for crit in sorted(policy.hard_criteria, key=lambda c: c.criterion_id):
        action = (
            effective_missing[crit.criterion_id].action
            if crit.criterion_id in effective_missing
            else crit.on_missing
        )
        hard_criteria_canonical.append(
            {
                "criterion_id": crit.criterion_id,
                "name": crit.name.strip(),
                "field": crit.field.strip(),
                "operator": crit.operator.strip().lower(),
                "expected_value": _canonicalize_value(crit.expected_value),
                "effective_on_missing": action,
            }
        )

    # Sorted preferences
    preferences_canonical: list[dict[str, Any]] = []
    for pref in sorted(policy.preferences, key=lambda p: p.rule_id):
        pref_vals = sorted({normalize_display(v) for v in pref.preferred_values if isinstance(v, str) and v.strip()})
        preferences_canonical.append(
            {
                "rule_id": pref.rule_id,
                "name": pref.name.strip(),
                "field": pref.field.strip(),
                "weight": round(float(pref.weight), 4),
                "preferred_values": pref_vals,
            }
        )

    # Sorted exclusions
    exclusions_canonical = sorted(
        {normalize_lookup(x) for x in policy.exclusions if isinstance(x, str) and x.strip()}
    )

    # Missing behavior
    missing_behavior_canonical = {
        k.strip(): v for k, v in sorted(policy.missing_information_behavior.items())
    }

    # Relevance configuration
    rel = policy.relevance_configuration
    broad_kws = sorted(
        {normalize_lookup(k) for k in rel.broad_keywords if isinstance(k, str) and k.strip()}
    )
    neg_kws = sorted(
        {normalize_lookup(k) for k in rel.negative_keywords if isinstance(k, str) and k.strip()}
    )
    rel_canonical = {
        "score_scale": rel.score_scale,
        "min_score_threshold": round(float(rel.min_score_threshold), 4) if rel.min_score_threshold is not None else None,
        "broad_keywords": broad_kws,
        "negative_keywords": neg_kws,
    }

    strategy = (
        policy.primary_context_strategy.value
        if hasattr(policy.primary_context_strategy, "value")
        else str(policy.primary_context_strategy)
    )

    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "policy_semantics_version": POLICY_SEMANTICS_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "regions": sorted({normalize_display(r) for r in policy.regions if isinstance(r, str) and r.strip()}),
        "role_aliases": role_aliases_canonical,
        "skill_aliases": skill_aliases_canonical,
        "hard_criteria": hard_criteria_canonical,
        "preferences": preferences_canonical,
        "exclusions": exclusions_canonical,
        "missing_information_behavior": missing_behavior_canonical,
        "relevance_configuration": rel_canonical,
        "primary_context_strategy": strategy,
    }


def compute_policy_fingerprint(
    policy: SearchPolicy,
    effective_missing: dict[str, EffectiveMissingAction],
    vocabulary: NormalizedVocabulary,
) -> tuple[str, bytes]:
    """Compute tagged SHA-256 fingerprint over canonical UTF-8 JSON bytes.
    
    Returns (fingerprint, canonical_bytes) where fingerprint has format:
    'policy-v1:sha256:<hex64>'
    """
    payload = build_canonical_payload(policy, effective_missing, vocabulary)
    canonical_bytes = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    digest = hashlib.sha256(canonical_bytes).hexdigest()
    fingerprint = f"policy-v1:sha256:{digest}"
    return fingerprint, canonical_bytes

