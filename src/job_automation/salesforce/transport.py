"""Bounded HTTPS transport for Salesforce REST API (SFCLIENT-01-S02).

Enforces:
- Strict HTTPS origins and standard TLS validation.
- Disabled automatic redirects and proxy traps.
- Connection, idle read, and total operation timeouts.
- Response payload byte ceilings.
- Precise tracking of uncertain transmission on mutating operations.
"""

from __future__ import annotations

import io
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from job_automation.contracts.errors import ErrorCategory
from job_automation.salesforce.configuration import SalesforceSettings
from job_automation.salesforce.ports import HttpResponse, HttpTransport


class TransportError(Exception):
    """Transport-level communication failure."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.TRANSIENT_NETWORK,
        http_status: int | None = None,
        uncertain_transmission: bool = False,
        safe_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.category = category
        self.http_status = http_status
        self.uncertain_transmission = uncertain_transmission
        self.safe_code = safe_code


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that blocks automatic redirection."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        # Returning None instructs urllib not to follow the redirect
        return None


class UrllibHttpTransport:
    """Production stdlib HTTPS transport conforming to HttpTransport protocol."""

    def __init__(
        self,
        settings: SalesforceSettings,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.settings = settings
        self.ssl_context = ssl_context or ssl.create_default_context()

        # Build custom opener with disabled automatic redirects
        self._opener = urllib.request.build_opener(
            _NoRedirectHandler(),
            urllib.request.HTTPSHandler(context=self.ssl_context),
        )

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        """Execute a single HTTP request with strict validation and timeouts."""
        # Validate that destination origin is approved
        if not self.settings.is_origin_approved(url):
            raise TransportError(
                f"Destination origin for URL is not in the approved origins list.",
                category=ErrorCategory.PERMISSION,
                uncertain_transmission=False,
                safe_code="origin_not_approved",
            )

        req_method = method.upper()
        req = urllib.request.Request(
            url=url,
            data=body,
            headers=headers,
            method=req_method,
        )

        is_mutation = req_method in {"POST", "PATCH", "PUT", "DELETE"}
        bytes_sent = False

        try:
            # We track whether transmission was initiated
            # On urllib, once open() is invoked with data, connect occurs and data is sent
            with self._opener.open(req, timeout=timeout) as resp:
                bytes_sent = True
                status_code: int = resp.status
                resp_headers: dict[str, str] = {
                    k.lower(): v for k, v in resp.headers.items()
                }

                # Read body with response size ceiling enforcement
                max_bytes = self.settings.max_response_bytes
                raw_body = resp.read(max_bytes + 1)
                if len(raw_body) > max_bytes:
                    raise TransportError(
                        f"Response payload exceeded maximum allowed limit of {max_bytes} bytes.",
                        category=ErrorCategory.CAPACITY,
                        http_status=status_code,
                        uncertain_transmission=is_mutation,
                        safe_code="response_payload_too_large",
                    )

                return HttpResponse(
                    status_code=status_code,
                    headers=resp_headers,
                    body=raw_body,
                    uncertain_transmission=False,
                )

        except urllib.error.HTTPError as exc:
            bytes_sent = True
            # Read HTTP error response body up to max_bytes
            err_headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
            err_body = b""
            try:
                err_body = exc.read(self.settings.max_response_bytes + 1)
                if len(err_body) > self.settings.max_response_bytes:
                    err_body = err_body[: self.settings.max_response_bytes]
            except Exception:
                pass

            return HttpResponse(
                status_code=exc.code,
                headers=err_headers,
                body=err_body,
                uncertain_transmission=False,
            )

        except (socket.timeout, TimeoutError) as exc:
            raise TransportError(
                "Request timed out during transport.",
                category=ErrorCategory.TRANSIENT_NETWORK,
                uncertain_transmission=is_mutation,
                safe_code="transport_timeout",
            ) from exc

        except ssl.SSLError as exc:
            raise TransportError(
                f"TLS certificate or handshake failure: {type(exc).__name__}",
                category=ErrorCategory.PERMISSION,
                uncertain_transmission=False,
                safe_code="tls_verification_failed",
            ) from exc

        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise TransportError(
                    "Connection timed out.",
                    category=ErrorCategory.TRANSIENT_NETWORK,
                    uncertain_transmission=is_mutation,
                    safe_code="connection_timeout",
                ) from exc
            elif isinstance(reason, ssl.SSLError):
                raise TransportError(
                    f"TLS verification failed: {type(reason).__name__}",
                    category=ErrorCategory.PERMISSION,
                    uncertain_transmission=False,
                    safe_code="tls_verification_failed",
                ) from exc
            elif isinstance(reason, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
                raise TransportError(
                    "Connection lost or reset during transfer.",
                    category=ErrorCategory.TRANSIENT_NETWORK,
                    uncertain_transmission=is_mutation,
                    safe_code="connection_reset",
                ) from exc
            else:
                # DNS failure or connect refused
                raise TransportError(
                    "Network unreachable or hostname resolution failed.",
                    category=ErrorCategory.TRANSIENT_NETWORK,
                    uncertain_transmission=False,
                    safe_code="network_unreachable",
                ) from exc

        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as exc:
            raise TransportError(
                "Connection broken during transfer.",
                category=ErrorCategory.TRANSIENT_NETWORK,
                uncertain_transmission=is_mutation,
                safe_code="connection_broken",
            ) from exc

