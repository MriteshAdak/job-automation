"""Scripted and programmable fake HTTP transport for Salesforce client testing (SFCLIENT-01-S01).

Enables tests to:
- Enqueue scripted HTTP responses (status, headers, body, uncertain_transmission).
- Inject transport exceptions (socket timeouts, connection resets, TLS failures).
- Inspect request history (method, URL, headers, payload bytes).
- Verify that credentials, authorization headers, and body bytes match expectations.
"""

from __future__ import annotations

from typing import Any, Callable

from job_automation.contracts.errors import ErrorCategory
from job_automation.salesforce.ports import HttpResponse, HttpTransport
from job_automation.salesforce.transport import TransportError


class RecordedRequest:
    """Captured details of an outbound HTTP request."""

    def __init__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> None:
        self.method = method
        self.url = url
        self.headers = headers
        self.body = body
        self.timeout = timeout


class FakeSalesforceTransport:
    """Scripted in-memory HTTP transport conforming to HttpTransport protocol."""

    def __init__(self) -> None:
        self.requests: list[RecordedRequest] = []
        self._responses: list[HttpResponse | Exception | Callable[[RecordedRequest], HttpResponse]] = []

    def queue_response(
        self,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
        uncertain_transmission: bool = False,
    ) -> None:
        """Enqueue an HttpResponse to return for the next request."""
        h = {k.lower(): v for k, v in (headers or {}).items()}
        self._responses.append(
            HttpResponse(
                status_code=status_code,
                headers=h,
                body=body,
                uncertain_transmission=uncertain_transmission,
            )
        )

    def queue_error(
        self,
        exc: Exception,
    ) -> None:
        """Enqueue an exception to raise on the next request."""
        self._responses.append(exc)

    def queue_handler(
        self,
        fn: Callable[[RecordedRequest], HttpResponse],
    ) -> None:
        """Enqueue a dynamic callable handler for the next request."""
        self._responses.append(fn)

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        """Capture request and return next scripted response or raise error."""
        recorded = RecordedRequest(
            method=method,
            url=url,
            headers={k.lower(): v for k, v in headers.items()},
            body=body,
            timeout=timeout,
        )
        self.requests.append(recorded)

        if not self._responses:
            # Default fallback 200 OK
            return HttpResponse(
                status_code=200,
                headers={"content-type": "application/json"},
                body=b"{}",
                uncertain_transmission=False,
            )

        next_item = self._responses.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        elif callable(next_item):
            return next_item(recorded)
        else:
            return next_item

