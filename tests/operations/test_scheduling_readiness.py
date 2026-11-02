"""Unit tests for model supervisor readiness probing and cold-start timeout handling (AUTO-01-T04, T05)."""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from job_automation.operations.scheduling.readiness import (
    is_loopback_url,
    probe_model_readiness,
    wait_for_model_readiness,
)
from job_automation.operations.scheduling.records import BootstrapCategory


def test_loopback_url_validation():
    """T04: Prohibits non-loopback URLs for local inference."""
    assert is_loopback_url("http://127.0.0.1:11434") is True
    assert is_loopback_url("http://localhost:11434") is True
    assert is_loopback_url("http://[::1]:11434") is True

    assert is_loopback_url("http://192.168.1.100:11434") is False
    assert is_loopback_url("https://remote-llm.example.com") is False
    assert is_loopback_url("ftp://localhost") is True  # hostname check


def test_probe_rejects_non_loopback():
    """T04: Probe rejects non-loopback URL with ACCESS_DENIED."""
    res = probe_model_readiness(url="http://10.0.0.5:11434")
    assert res.is_ready is False
    assert res.category == BootstrapCategory.ACCESS_DENIED
    assert "Loopback security violation" in res.details


def test_probe_offline_runtime():
    """T04: Probing offline endpoint returns RUNTIME_OFFLINE cleanly without exception."""
    res = probe_model_readiness(url="http://127.0.0.1:49999", timeout_seconds=0.1)
    assert res.is_ready is False
    assert res.category == BootstrapCategory.RUNTIME_OFFLINE
    assert "offline or unreachable" in res.details


def test_probe_model_present():
    """T04: Probing online runtime with matching model returns OK."""
    fake_body = json.dumps({"models": [{"name": "llama3:8b-instruct-q4_K_M"}, {"name": "nomic-embed-text"}]}).encode("utf-8")

    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.read.return_value = fake_body
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=fake_resp):
        res = probe_model_readiness(url="http://127.0.0.1:11434", required_model="llama3:8b-instruct-q4_K_M")
        assert res.is_ready is True
        assert res.category == BootstrapCategory.OK
        assert "llama3:8b-instruct-q4_K_M" in res.installed_models


def test_probe_model_missing():
    """T04: Runtime online but missing required model returns MODEL_MISSING."""
    fake_body = json.dumps({"models": [{"name": "mistral:latest"}]}).encode("utf-8")

    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.read.return_value = fake_body
    fake_resp.__enter__.return_value = fake_resp
    fake_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=fake_resp):
        res = probe_model_readiness(url="http://127.0.0.1:11434", required_model="llama3:8b-instruct-q4_K_M")
        assert res.is_ready is False
        assert res.category == BootstrapCategory.MODEL_MISSING
        assert "not installed" in res.details
        assert res.installed_models == ["mistral:latest"]


def test_wait_for_readiness_timeout():
    """T04: Cold-start deadline expiry returns TIMEOUT."""
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        res = wait_for_model_readiness(
            url="http://127.0.0.1:11434",
            required_model="llama3",
            deadline_seconds=0.1,
            poll_interval=0.05,
        )
        assert res.is_ready is False
        assert res.category == BootstrapCategory.TIMEOUT
        assert "Cold-start deadline" in res.details

