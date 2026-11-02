"""Tests for error classification across HTTP status codes and transport errors (LLM-01-S06)."""

from __future__ import annotations

import socket

import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.models.errors import (
    classify_http_status,
    classify_transport_error,
)


class TestErrorClassification:
    def test_transport_exception_classification(self) -> None:
        # Connection refused -> TRANSIENT_NETWORK
        err = classify_transport_error(ConnectionRefusedError("Connection refused on 127.0.0.1:11434"))
        assert err.category == ErrorCategory.TRANSIENT_NETWORK
        assert err.recoverable is True

        # Socket timeout -> TRANSIENT_NETWORK
        err = classify_transport_error(socket.timeout("timed out"))
        assert err.category == ErrorCategory.TRANSIENT_NETWORK
        assert err.recoverable is True

        # Size limit ValueError -> MODEL_OUTPUT
        err = classify_transport_error(ValueError("Response body exceeded maximum allowed 100 bytes"))
        assert err.category == ErrorCategory.MODEL_OUTPUT
        assert err.recoverable is False

    @pytest.mark.parametrize(
        "status,body,expected_category,recoverable",
        [
            (400, b'{"error": "prompt exceeds context length of 2048"}', ErrorCategory.CONTEXT_BUDGET, False),
            (400, b'{"error": "invalid parameter temperature"}', ErrorCategory.VALIDATION, False),
            (401, b'{"error": "unauthorized"}', ErrorCategory.AUTHENTICATION, False),
            (403, b'{"error": "forbidden"}', ErrorCategory.PERMISSION, False),
            (404, b'{"error": "model \'missing\' not found"}', ErrorCategory.MISSING_CONFIGURATION, False),
            (429, b'{"error": "too many requests"}', ErrorCategory.RATE_LIMIT, True),
            (502, b'{"error": "bad gateway"}', ErrorCategory.TRANSIENT_SERVICE, True),
            (503, b'{"error": "service unavailable"}', ErrorCategory.TRANSIENT_SERVICE, True),
            (504, b'{"error": "gateway timeout"}', ErrorCategory.TRANSIENT_SERVICE, True),
            (507, b'{"error": "insufficient storage"}', ErrorCategory.CAPACITY, True),
            (500, b'{"error": "CUDA out of memory in VRAM allocation"}', ErrorCategory.CAPACITY, True),
            (500, b'{"error": "generic internal error"}', ErrorCategory.TRANSIENT_SERVICE, True),
        ],
    )
    def test_http_status_classification_table(
        self,
        status: int,
        body: bytes,
        expected_category: ErrorCategory,
        recoverable: bool,
    ) -> None:
        err = classify_http_status(status, body)
        assert err.category == expected_category
        assert err.recoverable == recoverable

