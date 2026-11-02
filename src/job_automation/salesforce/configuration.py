"""Salesforce configuration and URL validation (SFCLIENT-01-S02).

Enforces:
- Strict HTTPS origins without userinfo, query params, or fragments.
- Explicit API version in 'NN.0' / 'vNN.0' format (embedded in '/services/data/vNN.0/').
- Finite positive timeouts, retry ceilings, and response size bounds.
- Secret-free configuration referencing protected credentials via opaque references.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from job_automation.contracts.base import ContractModel

# TODO(SF-01/SF-00): Verify the selected org (currently alias dev-main).
# Resolve its org ID, endpoint and supported API version; inspect object/field
# names, External IDs, lookup targets, picklists, required fields and defaults.
# Supply verified values through SalesforceSettings and SyncMappingConfig.
# Revalidate mappings and migration needs whenever the target org changes.

API_VERSION_PATTERN = re.compile(r"^v?([1-9][0-9]*)\.0$")

SALESFORCE_HOSTNAME_SUFFIXES: tuple[str, ...] = (
    ".salesforce.com",
    ".my.salesforce.com",
    ".force.com",
    ".develop.my.salesforce.com",
    ".sandbox.my.salesforce.com",
)


def validate_https_url(
    url_str: str,
    desc: str = "URL",
    allow_localhost_for_tests: bool = False,
) -> str:
    """Validate that a URL is a valid, secure HTTPS origin or endpoint."""
    if not isinstance(url_str, str) or not url_str.strip():
        raise ValueError(f"{desc} must be a non-empty string.")

    cleaned = url_str.strip()
    parsed = urlparse(cleaned)

    if parsed.scheme != "https":
        if allow_localhost_for_tests and parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}:
            pass
        else:
            raise ValueError(f"{desc} scheme must be 'https', got '{parsed.scheme}'.")

    if parsed.username or parsed.password:
        raise ValueError(f"{desc} must not contain userinfo or credentials.")

    if parsed.query:
        raise ValueError(f"{desc} must not contain query parameters.")

    if parsed.fragment:
        raise ValueError(f"{desc} must not contain fragment identifier.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError(f"{desc} must contain a valid hostname.")

    if parsed.port is not None and parsed.port not in {443, 8443}:
        if not (allow_localhost_for_tests and parsed.hostname in {"127.0.0.1", "localhost"}):
            raise ValueError(f"{desc} uses non-standard HTTPS port '{parsed.port}'.")

    return cleaned


def normalize_api_version(v: str) -> str:
    """Normalize and validate API version into 'vNN.0' format."""
    if not isinstance(v, str) or not v.strip():
        raise ValueError("Invalid Salesforce API version. Must be specified as 'NN.0' or 'vNN.0'.")
    cleaned = v.strip().lower()
    m = API_VERSION_PATTERN.match(cleaned)
    if not m:
        raise ValueError(
            f"Invalid Salesforce API version '{v}'. Must match 'NN.0' or 'vNN.0' format (e.g. 'v60.0')."
        )
    major = m.group(1)
    return f"v{major}.0"


class SalesforceSettings(ContractModel):
    """Non-secret configuration settings for Salesforce REST gateway."""

    instance_url: str = Field(
        description="Base origin URL of the Salesforce instance (e.g. 'https://example.my.salesforce.com')"
    )
    api_version: str = Field(
        default="v60.0",
        description="Explicit REST API version in 'vNN.0' format (e.g. 'v60.0')",
    )
    auth_flow: str = Field(
        default="refresh_token",
        description="OAuth flow type (e.g. 'refresh_token', 'jwt_bearer', 'client_credentials')",
    )
    client_id_ref: str | None = Field(
        default=None,
        description="Opaque reference or key name for OAuth Connected App client ID",
    )
    credential_ref: str | None = Field(
        default=None,
        description="Opaque reference for protected refresh token or credential secret",
    )
    token_url: str = Field(
        default="https://login.salesforce.com/services/oauth2/token",
        description="OAuth token exchange endpoint URL",
    )
    expected_org_id: str | None = Field(
        default=None,
        description="Expected Salesforce Organization ID (15 or 18 chars)",
    )
    expected_user_id: str | None = Field(
        default=None,
        description="Expected Salesforce User ID (15 or 18 chars)",
    )
    approved_origins: list[str] = Field(
        default_factory=list,
        description="Explicit list of approved HTTPS origins; instance_url and token_url origins are added automatically",
    )
    connect_timeout_seconds: float = Field(
        default=10.0, gt=0, le=60, description="TCP connect timeout in seconds"
    )
    read_timeout_seconds: float = Field(
        default=20.0, gt=0, le=120, description="Read idle timeout in seconds"
    )
    total_call_timeout_seconds: float = Field(
        default=60.0, gt=0, le=300, description="Monotonic logical operation deadline in seconds"
    )
    max_total_sends: int = Field(
        default=6, ge=1, le=20, description="Maximum total HTTP requests per logical operation"
    )
    max_resource_sends: int = Field(
        default=3, ge=1, le=10, description="Maximum resource HTTP requests per logical operation"
    )
    max_token_sends: int = Field(
        default=2, ge=1, le=5, description="Maximum token acquisition/renewal requests per logical operation"
    )
    initial_backoff_seconds: float = Field(
        default=1.0, gt=0, le=10, description="Initial backoff delay in seconds"
    )
    max_backoff_seconds: float = Field(
        default=8.0, gt=0, le=60, description="Maximum backoff ceiling in seconds"
    )
    max_response_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=1024,
        le=50 * 1024 * 1024,
        description="Maximum allowable response payload size in bytes (10 MiB default)",
    )

    @field_validator("instance_url")
    @classmethod
    def _validate_instance_url(cls, v: str) -> str:
        return validate_https_url(v, "instance_url")

    @field_validator("token_url")
    @classmethod
    def _validate_token_url(cls, v: str) -> str:
        return validate_https_url(v, "token_url")

    @field_validator("api_version")
    @classmethod
    def _validate_api_version(cls, v: str) -> str:
        return normalize_api_version(v)

    @field_validator("expected_org_id")
    @classmethod
    def _validate_org_id(cls, v: str | None) -> str | None:
        if v is not None:
            cleaned = v.strip()
            if not re.match(r"^00D[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?$", cleaned):
                raise ValueError(f"Invalid Salesforce Org ID format: '{v}'")
            return cleaned
        return None

    @field_validator("expected_user_id")
    @classmethod
    def _validate_user_id(cls, v: str | None) -> str | None:
        if v is not None:
            cleaned = v.strip()
            if not re.match(r"^005[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?$", cleaned):
                raise ValueError(f"Invalid Salesforce User ID format: '{v}'")
            return cleaned
        return None

    @model_validator(mode="after")
    def _populate_approved_origins(self) -> SalesforceSettings:
        origins = set(self.approved_origins)
        # Add instance_url origin
        p_inst = urlparse(self.instance_url)
        inst_origin = f"{p_inst.scheme}://{p_inst.netloc}"
        origins.add(inst_origin)

        # Add token_url origin
        p_tok = urlparse(self.token_url)
        tok_origin = f"{p_tok.scheme}://{p_tok.netloc}"
        origins.add(tok_origin)

        # Validate that all approved origins are https
        for o in origins:
            validate_https_url(o, "approved_origin")

        # Object is frozen, so return updated self with populated approved_origins
        object.__setattr__(self, "approved_origins", sorted(origins))
        return self

    def build_resource_path(self, subpath: str) -> str:
        """Construct a versioned REST resource URL."""
        cleaned_sub = subpath.lstrip("/")
        base = self.instance_url.rstrip("/")
        return f"{base}/services/data/{self.api_version}/{cleaned_sub}"

    def is_origin_approved(self, url: str) -> bool:
        """Check whether target URL origin is in approved origins list."""
        try:
            p = urlparse(url)
            origin = f"{p.scheme}://{p.netloc}"
            return origin in self.approved_origins
        except Exception:
            return False


def load_salesforce_settings(settings_path: Path) -> SalesforceSettings:
    """Load and validate SalesforceSettings from a JSON file."""
    import json

    resolved = settings_path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Salesforce settings file not found: {resolved}")

    try:
        with open(resolved, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as err:
        raise ValueError(f"Malformed JSON in Salesforce settings: {err}") from err

    return SalesforceSettings.model_validate(data)
