"""Acquisition endpoints and bounded request policy validation (SOURCE-01-S04).

Enforces:
- Method-specific endpoint checking: HTTPS default for automated acquisition,
  rejection of URL userinfo/fragments, and safe provenance for manual imports.
- Finite request vocabulary with explicit units and bounds:
  timeout (> 0), request spacing (>= 0), max attempts (>= 1), backoff factor/cap.
- Safe legacy alias resolution ('timeout' -> 'timeout_seconds').
- Rejection of unknown policy keys to catch typos.
- Rejection of inline credentials, userinfo, and secret-bearing headers/params.
- No network requests, sleeps, or credential lookups during validation.
"""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlparse

from job_automation.contracts.enums import AcquisitionMethod
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.errors import (
    ERR_CONFLICTING_POLICY,
    ERR_DISALLOWED_CREDENTIAL,
    ERR_INVALID_ENDPOINT,
    ERR_INVALID_REQUEST_POLICY,
    make_issue,
)
from job_automation.sources.models import EffectiveRequestPolicy

ALLOWED_REQUEST_POLICY_KEYS = {
    "timeout",
    "timeout_seconds",
    "request_spacing_seconds",
    "rate_limit_per_second",
    "requests_per_minute",
    "max_attempts",
    "backoff_factor",
    "backoff_max_seconds",
    "max_pages",
    "headers",
    "params",
    "query_params",
    "credential_ref",
    "access_review",
    "scope_filters",
}

DISALLOWED_HEADER_NAMES = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "apikey",
    "token",
    "secret",
    "proxy-authorization",
}

DISALLOWED_PARAM_NAMES = {
    "key",
    "api_key",
    "token",
    "secret",
    "password",
    "auth",
    "access_token",
}


def _validate_endpoint(config: SourceConfig) -> list[ValidationIssue]:
    """Validate base_url syntax, scheme, and absence of userinfo credentials."""
    issues: list[ValidationIssue] = []
    raw_url = config.base_url

    if raw_url.strip() != raw_url:
        issues.append(
            make_issue(
                code=ERR_INVALID_ENDPOINT,
                message="base_url must not contain leading or trailing whitespace",
                field_path="base_url",
            )
        )

    parsed = urlparse(raw_url)

    # Check for forbidden credentials in URL userinfo
    if parsed.username or parsed.password:
        issues.append(
            make_issue(
                code=ERR_DISALLOWED_CREDENTIAL,
                message="base_url contains forbidden embedded credentials / userinfo",
                field_path="base_url",
            )
        )

    if parsed.fragment:
        issues.append(
            make_issue(
                code=ERR_INVALID_ENDPOINT,
                message="base_url must not contain URL fragments ('#')",
                field_path="base_url",
            )
        )

    if config.acquisition_method in (
        AcquisitionMethod.API,
        AcquisitionMethod.PERMITTED_SCRAPING,
    ):
        scheme = (parsed.scheme or "").lower()
        if scheme not in {"https", "http"}:
            issues.append(
                make_issue(
                    code=ERR_INVALID_ENDPOINT,
                    message=f"Automated acquisition requires 'https' or 'http' endpoint, got '{scheme}'",
                    field_path="base_url",
                )
            )
        elif scheme == "http":
            hostname = (parsed.hostname or "").lower()
            if hostname not in {"127.0.0.1", "localhost", "::1"}:
                issues.append(
                    make_issue(
                        code=ERR_INVALID_ENDPOINT,
                        message=f"Insecure 'http' endpoint is only permitted for loopback testing, got '{hostname}'",
                        field_path="base_url",
                    )
                )

        if not parsed.hostname:
            issues.append(
                make_issue(
                    code=ERR_INVALID_ENDPOINT,
                    message="base_url lacks a valid hostname",
                    field_path="base_url",
                )
            )

    return issues


def validate_request_policy(
    config: SourceConfig,
) -> tuple[EffectiveRequestPolicy, list[ValidationIssue]]:
    """Validate request policy dictionary and construct EffectiveRequestPolicy."""
    issues = _validate_endpoint(config)
    policy_dict = config.request_policy or {}

    # Reject unknown keys (prevent silently ignoring typos like 'timeuot')
    for key in sorted(policy_dict.keys()):
        if key not in ALLOWED_REQUEST_POLICY_KEYS:
            issues.append(
                make_issue(
                    code=ERR_INVALID_REQUEST_POLICY,
                    message=f"Unknown request_policy key '{key}'; unrecognized keys are forbidden",
                    field_path=f"request_policy.{key}",
                )
            )

    # Timeout validation and legacy alias handling
    has_legacy = "timeout" in policy_dict
    has_canonical = "timeout_seconds" in policy_dict
    timeout_val = 30.0

    if has_legacy and has_canonical:
        leg_val = policy_dict["timeout"]
        can_val = policy_dict["timeout_seconds"]
        try:
            if float(leg_val) != float(can_val):
                issues.append(
                    make_issue(
                        code=ERR_CONFLICTING_POLICY,
                        message=f"Conflicting timeout values: legacy 'timeout'={leg_val} vs 'timeout_seconds'={can_val}",
                        field_path="request_policy.timeout_seconds",
                    )
                )
        except (ValueError, TypeError):
            pass

    raw_timeout = (
        policy_dict.get("timeout_seconds")
        if has_canonical
        else policy_dict.get("timeout", 30.0)
    )

    if isinstance(raw_timeout, bool):
        issues.append(
            make_issue(
                code=ERR_INVALID_REQUEST_POLICY,
                message="timeout_seconds must be a number, not boolean",
                field_path="request_policy.timeout_seconds",
            )
        )
    else:
        try:
            t = float(raw_timeout)
            if math.isnan(t) or math.isinf(t) or t <= 0:
                issues.append(
                    make_issue(
                        code=ERR_INVALID_REQUEST_POLICY,
                        message=f"timeout_seconds must be a finite positive number, got {raw_timeout}",
                        field_path="request_policy.timeout_seconds",
                    )
                )
            else:
                timeout_val = t
        except (ValueError, TypeError):
            issues.append(
                make_issue(
                    code=ERR_INVALID_REQUEST_POLICY,
                    message=f"timeout_seconds must be numeric, got {type(raw_timeout).__name__}",
                    field_path="request_policy.timeout_seconds",
                )
            )

    # Request spacing
    spacing_val: float | None = None
    if "requests_per_minute" in policy_dict:
        raw_rpm = policy_dict["requests_per_minute"]
        if isinstance(raw_rpm, bool):
            issues.append(
                make_issue(
                    code=ERR_INVALID_REQUEST_POLICY,
                    message="requests_per_minute must be numeric, not boolean",
                    field_path="request_policy.requests_per_minute",
                )
            )
        else:
            try:
                rpm = float(raw_rpm)
                if math.isnan(rpm) or math.isinf(rpm) or rpm <= 0:
                    issues.append(
                        make_issue(
                            code=ERR_INVALID_REQUEST_POLICY,
                            message=f"requests_per_minute must be finite and > 0, got {raw_rpm}",
                            field_path="request_policy.requests_per_minute",
                        )
                    )
                else:
                    spacing_val = 60.0 / rpm
            except (ValueError, TypeError):
                issues.append(
                    make_issue(
                        code=ERR_INVALID_REQUEST_POLICY,
                        message="requests_per_minute must be numeric",
                        field_path="request_policy.requests_per_minute",
                    )
                )
    elif "rate_limit_per_second" in policy_dict:
        raw_rps = policy_dict["rate_limit_per_second"]
        if isinstance(raw_rps, bool):
            issues.append(
                make_issue(
                    code=ERR_INVALID_REQUEST_POLICY,
                    message="rate_limit_per_second must be numeric, not boolean",
                    field_path="request_policy.rate_limit_per_second",
                )
            )
        else:
            try:
                rps = float(raw_rps)
                if math.isnan(rps) or math.isinf(rps) or rps <= 0:
                    issues.append(
                        make_issue(
                            code=ERR_INVALID_REQUEST_POLICY,
                            message=f"rate_limit_per_second must be finite and > 0, got {raw_rps}",
                            field_path="request_policy.rate_limit_per_second",
                        )
                    )
                else:
                    spacing_val = 1.0 / rps
            except (ValueError, TypeError):
                issues.append(
                    make_issue(
                        code=ERR_INVALID_REQUEST_POLICY,
                        message="rate_limit_per_second must be numeric",
                        field_path="request_policy.rate_limit_per_second",
                    )
                )
    elif "request_spacing_seconds" in policy_dict:
        raw_sp = policy_dict["request_spacing_seconds"]
        if isinstance(raw_sp, bool):
            issues.append(
                make_issue(
                    code=ERR_INVALID_REQUEST_POLICY,
                    message="request_spacing_seconds must be numeric, not boolean",
                    field_path="request_policy.request_spacing_seconds",
                )
            )
        else:
            try:
                sp = float(raw_sp)
                if math.isnan(sp) or math.isinf(sp) or sp < 0:
                    issues.append(
                        make_issue(
                            code=ERR_INVALID_REQUEST_POLICY,
                            message=f"request_spacing_seconds must be finite and >= 0, got {raw_sp}",
                            field_path="request_policy.request_spacing_seconds",
                        )
                    )
                else:
                    spacing_val = sp
            except (ValueError, TypeError):
                issues.append(
                    make_issue(
                        code=ERR_INVALID_REQUEST_POLICY,
                        message="request_spacing_seconds must be numeric",
                        field_path="request_policy.request_spacing_seconds",
                    )
                )

    # Max attempts
    max_attempts_val = 1
    if "max_attempts" in policy_dict:
        raw_att = policy_dict["max_attempts"]
        if isinstance(raw_att, bool) or not isinstance(raw_att, int):
            issues.append(
                make_issue(
                    code=ERR_INVALID_REQUEST_POLICY,
                    message="max_attempts must be an integer, not boolean or float",
                    field_path="request_policy.max_attempts",
                )
            )
        elif raw_att < 1 or raw_att > 10:
            issues.append(
                make_issue(
                    code=ERR_INVALID_REQUEST_POLICY,
                    message=f"max_attempts must be between 1 and 10, got {raw_att}",
                    field_path="request_policy.max_attempts",
                )
            )
        else:
            max_attempts_val = raw_att

    # Backoff factor & max seconds
    backoff_factor_val = 1.0
    if "backoff_factor" in policy_dict:
        raw_bf = policy_dict["backoff_factor"]
        if isinstance(raw_bf, bool):
            issues.append(
                make_issue(
                    code=ERR_INVALID_REQUEST_POLICY,
                    message="backoff_factor must be numeric, not boolean",
                    field_path="request_policy.backoff_factor",
                )
            )
        else:
            try:
                bf = float(raw_bf)
                if math.isnan(bf) or math.isinf(bf) or bf < 0:
                    issues.append(
                        make_issue(
                            code=ERR_INVALID_REQUEST_POLICY,
                            message=f"backoff_factor must be finite and >= 0, got {raw_bf}",
                            field_path="request_policy.backoff_factor",
                        )
                    )
                else:
                    backoff_factor_val = bf
            except (ValueError, TypeError):
                issues.append(
                    make_issue(
                        code=ERR_INVALID_REQUEST_POLICY,
                        message="backoff_factor must be numeric",
                        field_path="request_policy.backoff_factor",
                    )
                )

    backoff_max_val = 30.0
    if "backoff_max_seconds" in policy_dict:
        raw_bm = policy_dict["backoff_max_seconds"]
        if isinstance(raw_bm, bool):
            issues.append(
                make_issue(
                    code=ERR_INVALID_REQUEST_POLICY,
                    message="backoff_max_seconds must be numeric, not boolean",
                    field_path="request_policy.backoff_max_seconds",
                )
            )
        else:
            try:
                bm = float(raw_bm)
                if math.isnan(bm) or math.isinf(bm) or bm < backoff_factor_val:
                    issues.append(
                        make_issue(
                            code=ERR_INVALID_REQUEST_POLICY,
                            message=f"backoff_max_seconds must be >= backoff_factor ({backoff_factor_val}), got {raw_bm}",
                            field_path="request_policy.backoff_max_seconds",
                        )
                    )
                else:
                    backoff_max_val = bm
            except (ValueError, TypeError):
                issues.append(
                    make_issue(
                        code=ERR_INVALID_REQUEST_POLICY,
                        message="backoff_max_seconds must be numeric",
                        field_path="request_policy.backoff_max_seconds",
                    )
                )

    # Max pages budget
    max_pages_val: int | None = None
    if "max_pages" in policy_dict:
        raw_mp = policy_dict["max_pages"]
        if isinstance(raw_mp, bool) or not isinstance(raw_mp, int) or raw_mp < 1:
            issues.append(
                make_issue(
                    code=ERR_INVALID_REQUEST_POLICY,
                    message=f"max_pages must be an integer >= 1, got {raw_mp}",
                    field_path="request_policy.max_pages",
                )
            )
        else:
            max_pages_val = raw_mp

    # Headers validation and secret check
    headers_dict: dict[str, str] = {}
    if "headers" in policy_dict:
        raw_headers = policy_dict["headers"]
        if not isinstance(raw_headers, dict):
            issues.append(
                make_issue(
                    code=ERR_INVALID_REQUEST_POLICY,
                    message="headers must be a dictionary of strings",
                    field_path="request_policy.headers",
                )
            )
        else:
            for hk, hv in raw_headers.items():
                hk_str = str(hk).strip()
                if hk_str.lower() in DISALLOWED_HEADER_NAMES:
                    issues.append(
                        make_issue(
                            code=ERR_DISALLOWED_CREDENTIAL,
                            message=f"Forbidden credential/authentication header '{hk_str}' in request_policy.headers",
                            field_path=f"request_policy.headers.{hk_str}",
                        )
                    )
                else:
                    headers_dict[hk_str] = str(hv)

    # Query params validation and secret check
    params_dict: dict[str, Any] = {}
    raw_params = policy_dict.get("params", policy_dict.get("query_params"))
    if raw_params is not None:
        if not isinstance(raw_params, dict):
            issues.append(
                make_issue(
                    code=ERR_INVALID_REQUEST_POLICY,
                    message="params must be a dictionary",
                    field_path="request_policy.params",
                )
            )
        else:
            for pk, pv in raw_params.items():
                pk_str = str(pk).strip()
                if pk_str.lower() in DISALLOWED_PARAM_NAMES:
                    issues.append(
                        make_issue(
                            code=ERR_DISALLOWED_CREDENTIAL,
                            message=f"Forbidden credential parameter '{pk_str}' in request_policy.params",
                            field_path=f"request_policy.params.{pk_str}",
                        )
                    )
                else:
                    params_dict[pk_str] = pv

    # Credential reference
    credential_ref_val: str | None = None
    if "credential_ref" in policy_dict:
        raw_cr = policy_dict["credential_ref"]
        if not isinstance(raw_cr, str) or not raw_cr.strip():
            issues.append(
                make_issue(
                    code=ERR_INVALID_REQUEST_POLICY,
                    message="credential_ref must be a non-empty string identifier",
                    field_path="request_policy.credential_ref",
                )
            )
        else:
            credential_ref_val = raw_cr.strip()

    policy = EffectiveRequestPolicy(
        timeout_seconds=timeout_val,
        request_spacing_seconds=spacing_val,
        max_attempts=max_attempts_val,
        backoff_factor=backoff_factor_val,
        backoff_max_seconds=backoff_max_val,
        max_pages=max_pages_val,
        headers=headers_dict,
        params=params_dict,
        credential_ref=credential_ref_val,
    )
    return policy, issues

