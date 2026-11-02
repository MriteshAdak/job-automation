"""Low-level loopback HTTP transport implementation (LLM-01-S02).

Enforces:
- Direct loopback connection without environment proxy interception.
- Strict loopback DNS verification.
- Finite connect and read timeouts.
- Maximum response size enforcement.
- Prohibition of auto-following redirects.
- Clean resource closure on all execution paths.
"""

from __future__ import annotations

import http.client
import json
from typing import Any
from urllib.parse import urlparse

from job_automation.models.configuration import (
    validate_loopback_url,
    verify_resolved_loopback,
)


class LoopbackHttpTransport:
    """Standard HTTP transport targeting local model runtime over loopback."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        max_response_bytes: int = 10 * 1024 * 1024,
        verify_dns: bool = True,
    ) -> None:
        self.base_url = validate_loopback_url(base_url)
        self.max_response_bytes = max_response_bytes
        self.verify_dns = verify_dns

        parsed = urlparse(self.base_url)
        self.scheme = parsed.scheme
        self.hostname = (parsed.hostname or "127.0.0.1").lower()
        self.port = parsed.port or (443 if self.scheme == "https" else 80)
        self.base_path = parsed.path.rstrip("/")

        if self.verify_dns and self.hostname == "localhost":
            verify_resolved_loopback("localhost")

    def post(
        self,
        path: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple[int, dict[str, str], bytes]:
        """Execute HTTP POST with JSON body and finite timeout.

        Returns (status_code, headers_dict, body_bytes).
        """
        if ".." in path:
            raise ValueError("Path must not contain directory traversal")

        full_path = f"{self.base_path}/{path.lstrip('/')}"
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body_bytes)),
            "Accept": "application/json",
            "User-Agent": "JobAutomation-LLMClient/1.0",
        }

        conn: http.client.HTTPConnection | None = None
        try:
            if self.scheme == "https":
                conn = http.client.HTTPSConnection(
                    self.hostname,
                    self.port,
                    timeout=timeout_seconds,
                )
            else:
                conn = http.client.HTTPConnection(
                    self.hostname,
                    self.port,
                    timeout=timeout_seconds,
                )

            conn.request("POST", full_path, body=body_bytes, headers=headers)
            response = conn.getresponse()

            status = response.status
            resp_headers: dict[str, str] = {
                k.lower(): v for k, v in response.getheaders()
            }

            # Check declared content-length ceiling
            cl_header = resp_headers.get("content-length")
            if cl_header:
                try:
                    declared_len = int(cl_header)
                    if declared_len > self.max_response_bytes:
                        raise ValueError(
                            f"Response Content-Length {declared_len} exceeds maximum allowed {self.max_response_bytes} bytes"
                        )
                except ValueError as err:
                    if "exceeds maximum allowed" in str(err):
                        raise

            # Read response stream incrementally to bound memory and enforce size limits
            chunks: list[bytes] = []
            total_read = 0
            chunk_size = 64 * 1024

            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > self.max_response_bytes:
                    raise ValueError(
                        f"Response body exceeded maximum allowed {self.max_response_bytes} bytes"
                    )
                chunks.append(chunk)

            return status, resp_headers, b"".join(chunks)

        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

