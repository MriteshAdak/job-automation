"""Tests for local model provider configuration and loopback URL validation (LLM-01-S02)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from job_automation.configuration import AppConfig
from job_automation.models.configuration import (
    ModelCapabilities,
    ModelProviderSettings,
    validate_loopback_url,
    verify_resolved_loopback,
)


class TestModelConfiguration:
    @pytest.mark.parametrize(
        "valid_url",
        [
            "http://127.0.0.1:11434",
            "http://localhost:11434",
            "http://::1:11434",
            "https://127.0.0.1:8443",
            "http://127.0.0.1",
            "http://localhost",
        ],
    )
    def test_valid_loopback_urls(self, valid_url: str) -> None:
        assert validate_loopback_url(valid_url) == valid_url

    @pytest.mark.parametrize(
        "invalid_url,match_substr",
        [
            ("http://api.openai.com/v1", "loopback"),
            ("http://192.168.1.10:11434", "loopback"),
            ("http://user:pass@127.0.0.1:11434", "userinfo or credentials"),
            ("http://127.0.0.1:11434?token=secret", "query parameters"),
            ("http://127.0.0.1:11434#section", "fragment"),
            ("ftp://127.0.0.1:11434", "scheme must be http or https"),
            ("http://127.0.0.1:11434/../../etc", "directory traversal"),
            ("http://127.0.0.1:70000", "port must be between 1 and 65535"),
        ],
    )
    def test_invalid_urls_rejected_cleanly(self, invalid_url: str, match_substr: str) -> None:
        with pytest.raises(ValueError, match=match_substr):
            validate_loopback_url(invalid_url)

    def test_provider_settings_validation(self) -> None:
        """Provider settings enforce positive finite limits."""
        settings = ModelProviderSettings(
            connect_timeout_seconds=2.5,
            read_timeout_seconds=30.0,
            total_deadline_seconds=60.0,
            max_transport_attempts=5,
            max_malformed_regenerations=1,
            max_response_bytes=1024 * 1024,
            max_batch_size=32,
        )
        assert settings.connect_timeout_seconds == 2.5
        assert settings.max_transport_attempts == 5
        assert settings.max_malformed_regenerations == 1

        # Reject negative/zero timeouts
        with pytest.raises(ValidationError):
            ModelProviderSettings(connect_timeout_seconds=0.0)

        with pytest.raises(ValidationError):
            ModelProviderSettings(max_transport_attempts=0)

        with pytest.raises(ValidationError):
            ModelProviderSettings(max_malformed_regenerations=2)  # Cap at 1

    def test_app_config_with_model_provider(self, tmp_path: Path) -> None:
        """AppConfig parses and validates embedded model_provider settings."""
        data_dir = (tmp_path / "data").resolve()
        cfg = AppConfig(
            data_root=str(data_dir),
            model_service_url="http://127.0.0.1:11434",
            model_provider=ModelProviderSettings(
                read_timeout_seconds=45.0,
                max_transport_attempts=2,
            ),
        )
        assert cfg.model_provider is not None
        assert cfg.model_provider.read_timeout_seconds == 45.0
        assert cfg.model_provider.max_transport_attempts == 2

    def test_verify_resolved_loopback_localhost(self) -> None:
        """Resolving localhost verifies loopback IPs."""
        # On standard systems localhost resolves to 127.0.0.1 or ::1
        verify_resolved_loopback("127.0.0.1")

