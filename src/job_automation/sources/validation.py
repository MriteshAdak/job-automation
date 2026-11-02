"""Semantic validation coordinator for individual C03 SourceConfig records (SOURCE-01).

Validates:
- Exact provider, board, and source_key identity invariants.
- Access authorization and documented evidence.
- Attribution requirements and notices.
- Bounded request policy and endpoint security.
- Inventory coverage semantics and scope identity.
"""

from __future__ import annotations

import re

from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.access import (
    validate_access_review,
    validate_attribution_review,
)
from job_automation.sources.errors import ERR_INVALID_IDENTITY, make_issue
from job_automation.sources.inventory import validate_inventory_scope
from job_automation.sources.models import (
    AccessReviewStatus,
    AttributionStatus,
    EffectiveSource,
)
from job_automation.sources.request_policy import validate_request_policy

WHITESPACE_PATTERN = re.compile(r"\s")


def validate_source_identity(config: SourceConfig) -> list[ValidationIssue]:
    """Validate identity fields: source_key, provider, board_id."""
    issues: list[ValidationIssue] = []

    # source_key: no leading/trailing whitespace, no internal whitespace
    if config.source_key != config.source_key.strip():
        issues.append(
            make_issue(
                code=ERR_INVALID_IDENTITY,
                message="source_key must not contain leading or trailing whitespace",
                field_path="source_key",
            )
        )
    elif WHITESPACE_PATTERN.search(config.source_key):
        issues.append(
            make_issue(
                code=ERR_INVALID_IDENTITY,
                message="source_key must not contain whitespace characters",
                field_path="source_key",
            )
        )

    # provider: non-empty, no leading/trailing whitespace
    if config.provider != config.provider.strip() or not config.provider.strip():
        issues.append(
            make_issue(
                code=ERR_INVALID_IDENTITY,
                message="provider must be a non-empty string without leading/trailing whitespace",
                field_path="provider",
            )
        )

    # board_id: non-empty, preserves exact leading zeros and casing, no padding
    if config.board_id != config.board_id.strip() or not config.board_id.strip():
        issues.append(
            make_issue(
                code=ERR_INVALID_IDENTITY,
                message="board_id must be a non-empty string without leading/trailing whitespace",
                field_path="board_id",
            )
        )

    return issues


def validate_source_config(config: SourceConfig) -> EffectiveSource:
    """Validate a C03 SourceConfig and return a comprehensive EffectiveSource."""
    all_issues: list[ValidationIssue] = []

    # 1. Identity validation
    id_issues = validate_source_identity(config)
    all_issues.extend(id_issues)

    # 2. Access review validation
    access_review, access_issues = validate_access_review(config)
    all_issues.extend(access_issues)

    # 3. Attribution review validation
    attrib_review, attrib_issues = validate_attribution_review(config)
    all_issues.extend(attrib_issues)

    # 4. Request policy validation
    effective_policy, policy_issues = validate_request_policy(config)
    all_issues.extend(policy_issues)

    # 5. Inventory scope validation
    scope, scope_issues = validate_inventory_scope(config, effective_policy)
    all_issues.extend(scope_issues)

    has_errors = any(issue.severity == "error" for issue in all_issues)
    is_valid = not has_errors

    # Compile human-readable readiness blockers
    readiness_blockers: list[str] = []
    if not config.enabled:
        readiness_blockers.append("Source is disabled (enabled=false)")
    if access_review.status != AccessReviewStatus.PERMITTED:
        readiness_blockers.append(
            f"Access review status is '{access_review.status.value}', requires 'permitted'"
        )
    if attrib_review.status == AttributionStatus.UNKNOWN:
        readiness_blockers.append("Attribution requirements are unknown")
    for issue in all_issues:
        if issue.severity == "error":
            readiness_blockers.append(f"[{issue.code}] {issue.message}")

    is_runnable = (
        is_valid
        and config.enabled
        and access_review.status == AccessReviewStatus.PERMITTED
        and attrib_review.status != AttributionStatus.UNKNOWN
        and len([b for b in readiness_blockers if not b.startswith("Source is disabled")]) == 0
    )

    return EffectiveSource(
        config=config,
        access_review=access_review,
        attribution_review=attrib_review,
        request_policy=effective_policy,
        inventory_scope=scope,
        is_valid=is_valid,
        is_runnable=is_runnable,
        issues=all_issues,
        readiness_blockers=readiness_blockers,
    )
