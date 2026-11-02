"""Inventory semantics validation and deterministic scope identity (SOURCE-01-S05).

Enforces:
- Three inventory semantics: complete_board, filtered_feed, and search_results.
- Contradiction detection: whole-board inventory cannot specify search/filter queries.
- Deterministic canonical scope identity (scope-v1:sha256:<hex64>).
- Invariance of scope_id to transport/pagination changes (timeouts, retries, cursors, headers).
- Sensitivity of scope_id to membership-affecting query parameters, filters, board, and provider.
"""

from __future__ import annotations

import hashlib
import json
from urllib.parse import parse_qs, urlparse

from job_automation.contracts.enums import InventorySemantics
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.errors import ERR_SCOPE_CONTRADICTION, make_issue
from job_automation.sources.models import EffectiveRequestPolicy, InventoryScope

TRANSIENT_PAGINATION_KEYS = {
    "page",
    "offset",
    "cursor",
    "limit",
    "page_size",
    "per_page",
    "timestamp",
    "ts",
    "_",
    "t",
}

FILTER_CONTRADICTION_KEYS = {
    "q",
    "query",
    "search",
    "filter",
    "department",
    "category",
    "role",
    "title",
}


def compute_scope_id(
    provider: str,
    board_id: str,
    acquisition_method: str,
    inventory_semantics: str,
    base_url: str,
    membership_params: dict[str, Any],
    scope_filters: dict[str, Any],
) -> str:
    """Compute a deterministic SHA-256 scope identity over canonical membership fields."""
    parsed = urlparse(base_url)
    clean_scheme = (parsed.scheme or "").lower()
    clean_netloc = (parsed.netloc or "").lower()
    clean_path = parsed.path.rstrip("/") if parsed.path else ""
    normalized_endpoint = f"{clean_scheme}://{clean_netloc}{clean_path}" if clean_scheme else base_url

    payload = {
        "algorithm_version": "scope-v1",
        "provider": provider.strip(),
        "board_id": board_id.strip(),
        "acquisition_method": acquisition_method,
        "inventory_semantics": inventory_semantics,
        "endpoint": normalized_endpoint,
        "membership_params": {k: membership_params[k] for k in sorted(membership_params.keys())},
        "scope_filters": {k: scope_filters[k] for k in sorted(scope_filters.keys())},
    }

    canonical_bytes = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    digest = hashlib.sha256(canonical_bytes).hexdigest()
    return f"scope-v1:sha256:{digest}"


def validate_inventory_scope(
    config: SourceConfig,
    policy: EffectiveRequestPolicy,
) -> tuple[InventoryScope, list[ValidationIssue]]:
    """Validate inventory semantics and derive stable scope identity."""
    issues: list[ValidationIssue] = []

    # Extract query params from base_url query string
    parsed = urlparse(config.base_url)
    url_params_raw = parse_qs(parsed.query)
    membership_params: dict[str, Any] = {}

    for k, v in url_params_raw.items():
        k_clean = k.strip()
        if k_clean.lower() not in TRANSIENT_PAGINATION_KEYS:
            # Flatten single-item lists for clean canonicalization
            membership_params[k_clean] = v[0] if len(v) == 1 else v

    # Add non-transient params from request_policy
    for pk, pv in policy.params.items():
        pk_clean = pk.strip()
        if pk_clean.lower() not in TRANSIENT_PAGINATION_KEYS:
            membership_params[pk_clean] = pv

    # Scope filters from request_policy
    scope_filters: dict[str, Any] = {}
    raw_filters = config.request_policy.get("scope_filters") if isinstance(config.request_policy, dict) else None
    if isinstance(raw_filters, dict):
        scope_filters = {str(k).strip(): v for k, v in raw_filters.items()}

    # Check complete_board contradiction
    if config.inventory_semantics == InventorySemantics.COMPLETE_BOARD:
        contradictory_keys = [
            k for k in membership_params.keys() if k.lower() in FILTER_CONTRADICTION_KEYS
        ]
        if contradictory_keys or scope_filters:
            issues.append(
                make_issue(
                    code=ERR_SCOPE_CONTRADICTION,
                    message=(
                        f"complete_board semantics contradicts search/filter parameters "
                        f"{contradictory_keys or list(scope_filters.keys())}; whole-board coverage cannot specify search queries"
                    ),
                    field_path="inventory_semantics",
                )
            )

    scope_id = compute_scope_id(
        provider=config.provider,
        board_id=config.board_id,
        acquisition_method=config.acquisition_method.value,
        inventory_semantics=config.inventory_semantics.value,
        base_url=config.base_url,
        membership_params=membership_params,
        scope_filters=scope_filters,
    )

    completeness_evidence = None
    if config.inventory_semantics == InventorySemantics.COMPLETE_BOARD:
        if isinstance(config.request_policy, dict):
            completeness_evidence = config.request_policy.get("completeness_evidence")

    scope = InventoryScope(
        scope_id=scope_id,
        semantics=config.inventory_semantics,
        provider=config.provider.strip(),
        board_id=config.board_id.strip(),
        acquisition_method=config.acquisition_method,
        base_url=config.base_url,
        query_params=membership_params,
        scope_filters=scope_filters,
        completeness_evidence=completeness_evidence,
    )
    return scope, issues

