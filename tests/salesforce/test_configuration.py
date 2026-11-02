"""Tests for Salesforce settings, URL validation, and AppConfig integration (SFCLIENT-01-S02)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from job_automation.configuration import AppConfig, load_config
from job_automation.salesforce.configuration import (
    SalesforceSettings,
    load_salesforce_settings,
    normalize_api_version,
    validate_https_url,
)


def test_api_version_normalization_and_validation() -> None:
    """Verify that API versions normalize strictly to 'vNN.0' format."""
    assert normalize_api_version("60.0") == "v60.0"
    assert normalize_api_version("v60.0") == "v60.0"
    assert normalize_api_version("59.0") == "v59.0"

    # Rejection of invalid versions
    with pytest.raises(ValueError, match="Invalid Salesforce API version"):
        normalize_api_version("latest")

    with pytest.raises(ValueError, match="Invalid Salesforce API version"):
        normalize_api_version("60")

    with pytest.raises(ValueError, match="Invalid Salesforce API version"):
        normalize_api_version("v60.1")

    with pytest.raises(ValueError, match="Invalid Salesforce API version"):
        normalize_api_version("")


def test_https_url_validation() -> None:
    """Verify strict HTTPS URL validation without credentials, queries, or fragments."""
    # Valid
    assert (
        validate_https_url("https://mycompany.my.salesforce.com")
        == "https://mycompany.my.salesforce.com"
    )

    # Reject http
    with pytest.raises(ValueError, match="scheme must be 'https'"):
        validate_https_url("http://mycompany.my.salesforce.com")

    # Reject userinfo
    with pytest.raises(ValueError, match="must not contain userinfo"):
        validate_https_url("https://admin:secret@mycompany.my.salesforce.com")

    # Reject query
    with pytest.raises(ValueError, match="must not contain query parameters"):
        validate_https_url("https://mycompany.my.salesforce.com?foo=bar")

    # Reject fragment
    with pytest.raises(ValueError, match="must not contain fragment"):
        validate_https_url("https://mycompany.my.salesforce.com#section")


def test_approved_origins_and_resource_path() -> None:
    """Verify that instance_url and token_url origins are approved automatically."""
    settings = SalesforceSettings(
        instance_url="https://acme.my.salesforce.com",
        token_url="https://login.salesforce.com/services/oauth2/token",
        api_version="60.0",
    )
    assert settings.api_version == "v60.0"
    assert settings.is_origin_approved("https://acme.my.salesforce.com/services/data/v60.0/sobjects")
    assert settings.is_origin_approved("https://login.salesforce.com/services/oauth2/token")
    assert not settings.is_origin_approved("https://evil.attacker.com/steal")

    resource_path = settings.build_resource_path("sobjects/Job__c/describe")
    assert (
        resource_path
        == "https://acme.my.salesforce.com/services/data/v60.0/sobjects/Job__c/describe"
    )


def test_load_salesforce_example_settings() -> None:
    """Verify loading config/salesforce.example.json directly."""
    example_path = Path(__file__).resolve().parent.parent.parent / "config" / "salesforce.example.json"
    settings = load_salesforce_settings(example_path)
    assert settings.instance_url == "https://example-dev-ed.develop.my.salesforce.com"
    assert settings.api_version == "v60.0"
    assert settings.client_id_ref == "salesforce/client_id"
    assert settings.credential_ref == "salesforce/refresh_token"
    assert settings.max_total_sends == 6
    assert settings.max_resource_sends == 3
    assert settings.max_token_sends == 2


def test_app_config_integration_with_salesforce_ref(tmp_path: Path) -> None:
    """Verify AppConfig resolves salesforce_settings_ref relative to config directory."""
    sf_cfg_path = tmp_path / "sf.json"
    sf_cfg_path.write_text(
        json.dumps({
            "schema_version": "1.0",
            "instance_url": "https://sample.my.salesforce.com",
            "api_version": "v60.0",
        }),
        encoding="utf-8",
    )

    app_cfg_path = tmp_path / "app.json"
    app_cfg_path.write_text(
        json.dumps({
            "schema_version": "1.0",
            "app_name": "JobAutomationTest",
            "data_root": str(tmp_path / "runtime_data"),
            "salesforce_settings_ref": "sf.json",
        }),
        encoding="utf-8",
    )

    config, paths = load_config(app_cfg_path)
    assert config.salesforce_settings_ref == "sf.json"
    assert paths.salesforce_settings_path == sf_cfg_path.resolve()


def test_app_config_without_salesforce_ref_remains_valid() -> None:
    """Verify that omitting salesforce_settings_ref keeps existing app configs 100% valid."""
    example_path = Path(__file__).resolve().parent.parent.parent / "config" / "app.example.json"
    config, paths = load_config(example_path)
    assert config.salesforce_settings_ref is None
    assert paths.salesforce_settings_path is None

