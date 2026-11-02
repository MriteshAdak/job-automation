"""Tests for LoopbackHttpTransport enforcement and finite I/O bounds (LLM-01-S02)."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from job_automation.models.transport import LoopbackHttpTransport


class FakeHttpResponse:
    def __init__(self, status: int, headers: list[tuple[str, str]], body_chunks: list[bytes]) -> None:
        self.status = status
        self._headers = headers
        self._chunks = list(body_chunks)

    def getheaders(self) -> list[tuple[str, str]]:
        return self._headers

    def read(self, amt: int | None = None) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        return b""


class TestLocalTransport:
    def test_transport_headers_and_payload(self) -> None:
        """Transport sets standard headers and encodes JSON body."""
        transport = LoopbackHttpTransport("http://127.0.0.1:11434")

        mock_conn = MagicMock()
        mock_resp = FakeHttpResponse(200, [("Content-Type", "application/json")], [b'{"ok": true}'])
        mock_conn.getresponse.return_value = mock_resp

        with patch("http.client.HTTPConnection", return_value=mock_conn):
            status, headers, body = transport.post(
                "/api/test",
                {"test": 123},
                timeout_seconds=5.0,
            )

        assert status == 200
        assert body == b'{"ok": true}'
        mock_conn.request.assert_called_once()
        req_args = mock_conn.request.call_args[0]
        req_kwargs = mock_conn.request.call_args[1]
        assert req_args[0] == "POST"
        assert req_args[1] == "/api/test"
        body_sent = req_kwargs.get("body", req_args[2] if len(req_args) > 2 else b"")
        assert b'"test": 123' in body_sent or b'"test":123' in body_sent
        mock_conn.close.assert_called_once()

    def test_oversized_declared_content_length_rejected(self) -> None:
        """Response with Content-Length exceeding max_response_bytes is rejected before reading."""
        transport = LoopbackHttpTransport("http://127.0.0.1:11434", max_response_bytes=1000)

        mock_conn = MagicMock()
        mock_resp = FakeHttpResponse(
            200,
            [("Content-Type", "application/json"), ("Content-Length", "50000")],
            [b"start"],
        )
        mock_conn.getresponse.return_value = mock_resp

        with patch("http.client.HTTPConnection", return_value=mock_conn):
            with pytest.raises(ValueError, match="exceeds maximum allowed 1000 bytes"):
                transport.post("/api/test", {}, timeout_seconds=5.0)

        mock_conn.close.assert_called_once()

    def test_trickling_oversized_response_rejected(self) -> None:
        """Response stream exceeding max_response_bytes during chunked read is terminated."""
        transport = LoopbackHttpTransport("http://127.0.0.1:11434", max_response_bytes=100)

        mock_conn = MagicMock()
        # Stream 3 chunks of 50 bytes = 150 bytes > 100 max
        mock_resp = FakeHttpResponse(
            200,
            [("Content-Type", "application/json")],
            [b"x" * 50, b"x" * 50, b"x" * 50],
        )
        mock_conn.getresponse.return_value = mock_resp

        with patch("http.client.HTTPConnection", return_value=mock_conn):
            with pytest.raises(ValueError, match="exceeded maximum allowed 100 bytes"):
                transport.post("/api/test", {}, timeout_seconds=5.0)

        mock_conn.close.assert_called_once()

    def test_path_traversal_rejected(self) -> None:
        """Paths containing .. are rejected."""
        transport = LoopbackHttpTransport("http://127.0.0.1:11434")
        with pytest.raises(ValueError, match="directory traversal"):
            transport.post("/../secret", {}, timeout_seconds=5.0)
