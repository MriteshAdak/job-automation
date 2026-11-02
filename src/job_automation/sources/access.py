"""Access review and attribution validation for source configurations (SOURCE-01-S03).

Enforces:
- Documented authorization / access conditions separate from reachability.
- Scoped access review matching the exact provider, board, endpoint, and acquisition method.
- Rejection of public-only or robots-only claims as sufficient permission evidence.
- Detection of explicit denial and expired reviews.
- Preservation of attribution requirements and distinction between unknown vs none_required.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.enums import AcquisitionMethod
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.errors import (
    ERR_ACCESS_DENIED,
    ERR_ACCESS_EXPIRED,
    ERR_ACCESS_METHOD_MISMATCH,
    ERR_ACCESS_UNREVIEWED,
    ERR_ATTRIBUTION_MISSING_NOTICE,
    ERR_ATTRIBUTION_UNKNOWN,
    make_issue,
)
from job_automation.sources.models import (
    AccessReview,
    AccessReviewStatus,
    AttributionReview,
    AttributionStatus,
)


def _parse_iso_datetime(dt_str: str) -> datetime | None:
    """Parse an ISO 8601 datetime string into a UTC datetime."""
    try:
        clean_str = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def validate_access_review(
    config: SourceConfig,
) -> tuple[AccessReview, list[ValidationIssue]]:
    """Validate access review metadata for a source configuration.

    A source cannot be considered PERMITTED without structured evidence, a valid review
    timestamp, and matching acquisition method scope.
    """
    issues: list[ValidationIssue] = []

    # Check for structured review in access_rules (JSON string) or request_policy (nested dict)
    review_data: dict[str, Any] | None = None
    prose_notes: str | None = None

    if config.access_rules:
        raw = config.access_rules.strip()
        if raw.lower() == "denied":
            issue = make_issue(
                code=ERR_ACCESS_DENIED,
                message=f"Access is explicitly recorded as denied for source '{config.source_key}'",
                field_path="access_rules",
            )
            issues.append(issue)
            return (
                AccessReview(
                    status=AccessReviewStatus.DENIED,
                    notes=raw,
                ),
                issues,
            )

        if raw.startswith("{") and raw.endswith("}"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    review_data = parsed
            except json.JSONDecodeError:
                prose_notes = raw
        else:
            prose_notes = raw

    # Fallback to request_policy["access_review"] if access_rules was prose or missing
    if review_data is None and isinstance(config.request_policy, dict):
        policy_review = config.request_policy.get("access_review")
        if isinstance(policy_review, dict):
            review_data = policy_review

    if review_data is None:
        # Prose notes alone or missing review is UNREVIEWED
        notes_msg = (
            f" (prose notes: '{prose_notes}')"
            if prose_notes
            else " (access_rules is unconfigured)"
        )
        issue = make_issue(
            code=ERR_ACCESS_UNREVIEWED,
            message=(
                f"Source '{config.source_key}' lacks structured permission evidence{notes_msg}. "
                "Public accessibility or robots.txt rules do not establish access permission."
            ),
            field_path="access_rules",
            severity="warning" if not config.enabled else "error",
        )
        issues.append(issue)
        return (
            AccessReview(
                status=AccessReviewStatus.UNREVIEWED,
                notes=prose_notes,
            ),
            issues,
        )

    # Validate structured review dictionary
    raw_status = str(review_data.get("status", "unreviewed")).lower()
    try:
        status = AccessReviewStatus(raw_status)
    except ValueError:
        status = AccessReviewStatus.UNREVIEWED

    evidence_ref = review_data.get("evidence_ref")
    reviewed_at_str = review_data.get("reviewed_at")
    expires_at_str = review_data.get("expires_at")
    restrictions_raw = review_data.get("restrictions", [])
    restrictions = [str(r) for r in restrictions_raw] if isinstance(restrictions_raw, list) else []
    notes = review_data.get("notes", prose_notes)

    permitted_methods_raw = review_data.get("permitted_methods", [])
    permitted_methods: list[AcquisitionMethod] = []
    if isinstance(permitted_methods_raw, list):
        for m in permitted_methods_raw:
            try:
                permitted_methods.append(AcquisitionMethod(str(m).lower()))
            except ValueError:
                pass

    if status == AccessReviewStatus.DENIED:
        issues.append(
            make_issue(
                code=ERR_ACCESS_DENIED,
                message=f"Access is explicitly recorded as denied for source '{config.source_key}'",
                field_path="access_rules.status",
            )
        )
    elif status == AccessReviewStatus.UNREVIEWED:
        issues.append(
            make_issue(
                code=ERR_ACCESS_UNREVIEWED,
                message=f"Source '{config.source_key}' has not completed access authorization review",
                field_path="access_rules.status",
                severity="warning" if not config.enabled else "error",
            )
        )
    elif status == AccessReviewStatus.PERMITTED:
        # Validate evidence reference
        if not evidence_ref or not str(evidence_ref).strip():
            status = AccessReviewStatus.UNREVIEWED
            issues.append(
                make_issue(
                    code=ERR_ACCESS_UNREVIEWED,
                    message="Permitted access review requires a non-empty evidence_ref",
                    field_path="access_rules.evidence_ref",
                )
            )

        # Validate review timestamp
        if not reviewed_at_str or _parse_iso_datetime(str(reviewed_at_str)) is None:
            status = AccessReviewStatus.UNREVIEWED
            issues.append(
                make_issue(
                    code=ERR_ACCESS_UNREVIEWED,
                    message="Permitted access review requires a valid ISO-8601 reviewed_at timestamp",
                    field_path="access_rules.reviewed_at",
                )
            )

        # Validate acquisition method scope
        if permitted_methods and config.acquisition_method not in permitted_methods:
            status = AccessReviewStatus.UNREVIEWED
            issues.append(
                make_issue(
                    code=ERR_ACCESS_METHOD_MISMATCH,
                    message=(
                        f"Configured acquisition method '{config.acquisition_method.value}' "
                        f"is not in reviewed permitted_methods {[m.value for m in permitted_methods]}"
                    ),
                    field_path="access_rules.permitted_methods",
                )
            )

        # Validate expiration if provided
        if expires_at_str:
            exp_dt = _parse_iso_datetime(str(expires_at_str))
            if exp_dt is None:
                issues.append(
                    make_issue(
                        code=ERR_ACCESS_EXPIRED,
                        message=f"Invalid ISO-8601 expires_at timestamp: '{expires_at_str}'",
                        field_path="access_rules.expires_at",
                    )
                )
            else:
                rev_dt = _parse_iso_datetime(str(reviewed_at_str)) if reviewed_at_str else None
                if rev_dt and exp_dt <= rev_dt:
                    status = AccessReviewStatus.DENIED
                    issues.append(
                        make_issue(
                            code=ERR_ACCESS_EXPIRED,
                            message=f"Access review expired on {expires_at_str} (before or at reviewed_at)",
                            field_path="access_rules.expires_at",
                        )
                    )

    review = AccessReview(
        status=status,
        reviewed_at=str(reviewed_at_str) if reviewed_at_str else None,
        evidence_ref=str(evidence_ref).strip() if evidence_ref else None,
        permitted_methods=permitted_methods,
        restrictions=restrictions,
        notes=str(notes) if notes else None,
    )
    return review, issues


def validate_attribution_review(
    config: SourceConfig,
) -> tuple[AttributionReview, list[ValidationIssue]]:
    """Validate attribution and licensing notices for a source configuration.

    Preserves exact notices and credits for downstream presentation.
    """
    issues: list[ValidationIssue] = []

    if config.attribution_rules is None or not config.attribution_rules.strip():
        # Unknown attribution
        issue = make_issue(
            code=ERR_ATTRIBUTION_UNKNOWN,
            message=f"Source '{config.source_key}' attribution requirements are unknown (attribution_rules is null)",
            field_path="attribution_rules",
            severity="warning" if not config.enabled else "error",
        )
        issues.append(issue)
        return AttributionReview(status=AttributionStatus.UNKNOWN), issues

    raw = config.attribution_rules.strip()
    raw_lower = raw.lower()

    if raw_lower in {"none", "none_required", "none required", "no attribution required"}:
        return (
            AttributionReview(
                status=AttributionStatus.NONE_REQUIRED,
                notes=raw,
            ),
            issues,
        )

    # Check for structured JSON attribution
    if raw.startswith("{") and raw.endswith("}"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                status_str = str(parsed.get("status", "required")).lower()
                status = (
                    AttributionStatus(status_str)
                    if status_str in {e.value for e in AttributionStatus}
                    else AttributionStatus.REQUIRED
                )
                notice = parsed.get("notice")
                link = parsed.get("link")
                notes = parsed.get("notes")

                if status == AttributionStatus.REQUIRED and not notice:
                    issues.append(
                        make_issue(
                            code=ERR_ATTRIBUTION_MISSING_NOTICE,
                            message="Attribution status is 'required' but notice text is empty",
                            field_path="attribution_rules.notice",
                        )
                    )

                return (
                    AttributionReview(
                        status=status,
                        notice=str(notice).strip() if notice else None,
                        link=str(link).strip() if link else None,
                        notes=str(notes) if notes else None,
                    ),
                    issues,
                )
        except json.JSONDecodeError:
            pass

    # Standard plain-text attribution notice
    return (
        AttributionReview(
            status=AttributionStatus.REQUIRED,
            notice=raw,
        ),
        issues,
    )

