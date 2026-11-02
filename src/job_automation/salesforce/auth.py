"""OAuth token lifecycle and authenticated session management (SFCLIENT-01-S03).

Enforces:
- In-memory caching with clock-skew aware expiration.
- Single renewal on invalid session (401).
- Atomic rotation of replacement refresh tokens.
- Safe handling of interrupted token exchanges without infinite loops.
- Actionable missing_configuration failures when SF-02 prerequisites are absent.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.salesforce.configuration import SalesforceSettings
from job_automation.salesforce.ports import (
    Clock,
    CredentialStore,
    DefaultClock,
    HttpResponse,
    HttpTransport,
    SalesforceSession,
    TokenProvider,
)
from job_automation.salesforce.transport import TransportError


class OAuthTokenProvider:
    """Production OAuth token provider implementing TokenProvider protocol."""

    def __init__(
        self,
        settings: SalesforceSettings,
        store: CredentialStore,
        transport: HttpTransport,
        clock: Clock | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.transport = transport
        self.clock: Clock = clock or DefaultClock()

        self._cached_session: SalesforceSession | None = None
        self._renewal_count_for_current_call: int = 0

    def reset_call_budget(self) -> None:
        """Reset call-specific renewal counters for a new logical operation."""
        self._renewal_count_for_current_call = 0

    def invalidate_session(self) -> None:
        """Clear cached session following explicit 401 rejection."""
        self._cached_session = None

    def get_session(
        self,
        force_refresh: bool = False,
    ) -> tuple[SalesforceSession | None, ClassifiedError | None]:
        """Obtain a valid authenticated session, reusing cache or refreshing."""
        now = self.clock.monotonic()

        # 1. Check in-memory cached session
        if not force_refresh and self._cached_session is not None:
            # If expires_at is known, verify we have at least 60 seconds remaining
            if self._cached_session.expires_at is not None:
                if now < (self._cached_session.expires_at - 60.0):
                    return self._cached_session, None
                # Expired or close to expiry
                self._cached_session = None
            else:
                # Expiry unknown; reuse until explicit 401 invalidation
                return self._cached_session, None

        # 2. Check prerequisites and stored credentials
        if not self.settings.client_id_ref or not self.settings.credential_ref:
            return None, ClassifiedError.from_category(
                ErrorCategory.MISSING_CONFIGURATION,
                "Salesforce OAuth configuration incomplete: client_id_ref or credential_ref not configured.",
                details={"status": "missing_prerequisite", "prerequisite": "SF-02"},
            )

        client_id = self.store.get_credential(self.settings.client_id_ref)
        if not client_id:
            return None, ClassifiedError.from_category(
                ErrorCategory.MISSING_CONFIGURATION,
                f"Client ID credential reference '{self.settings.client_id_ref}' not found in credential store.",
                details={"ref": self.settings.client_id_ref, "prerequisite": "SF-02"},
            )

        refresh_token = self.store.get_credential(self.settings.credential_ref)
        if not refresh_token:
            return None, ClassifiedError.from_category(
                ErrorCategory.MISSING_CONFIGURATION,
                f"Refresh token credential reference '{self.settings.credential_ref}' not found in credential store.",
                details={"ref": self.settings.credential_ref, "prerequisite": "SF-02"},
            )

        # 3. Check for interrupted rotation exchange marker
        # If hasattr check is used in case a custom CredentialStore doesn't implement progress markers
        if hasattr(self.store, "is_exchange_in_progress"):
            if self.store.is_exchange_in_progress(self.settings.credential_ref):
                return None, ClassifiedError.from_category(
                    ErrorCategory.AUTHENTICATION,
                    "Previous refresh token exchange was interrupted before commit. Reauthorization required.",
                    details={"safe_code": "interrupted_rotation_recovery_required"},
                )

        # 4. Enforce renewal limit
        if force_refresh:
            if self._renewal_count_for_current_call >= 1:
                return None, ClassifiedError.from_category(
                    ErrorCategory.AUTHENTICATION,
                    "Session renewal rejected: maximum renewal attempts (1) exceeded for this call.",
                    details={"safe_code": "token_renewal_limit_exceeded"},
                )
            self._renewal_count_for_current_call += 1

        # 5. Execute token exchange
        session, error = self._exchange_refresh_token(client_id, refresh_token)
        if error is not None:
            return None, error

        self._cached_session = session
        return session, None

    def _exchange_refresh_token(
        self,
        client_id: str,
        refresh_token: str,
    ) -> tuple[SalesforceSession | None, ClassifiedError | None]:
        """Perform OAuth refresh token POST request."""
        # Mark exchange in progress if supported
        has_progress = hasattr(self.store, "mark_exchange_in_progress") and hasattr(
            self.store, "clear_exchange_in_progress"
        )
        if has_progress:
            self.store.mark_exchange_in_progress(self.settings.credential_ref)  # type: ignore[union-attr]

        payload_params = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        }
        body_bytes = urllib.parse.urlencode(payload_params).encode("utf-8")
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "accept": "application/json",
            "user-agent": "job-automation/0.1 (SalesforceGatewayV2; SFCLIENT-01)",
        }

        try:
            resp = self.transport.request(
                method="POST",
                url=self.settings.token_url,
                headers=headers,
                body=body_bytes,
                timeout=self.settings.connect_timeout_seconds + self.settings.read_timeout_seconds,
            )
        except TransportError as err:
            if has_progress:
                # Do NOT clear progress marker if transmission was uncertain!
                if not err.uncertain_transmission:
                    self.store.clear_exchange_in_progress(self.settings.credential_ref)  # type: ignore[union-attr]
            return None, ClassifiedError.from_category(
                err.category,
                "Failed to contact Salesforce OAuth token endpoint.",
                details={"safe_code": err.safe_code or "token_transport_failure"},
            )

        # Parse token response
        if resp.status_code != 200:
            if has_progress:
                # Definite server response received; clear progress marker
                self.store.clear_exchange_in_progress(self.settings.credential_ref)  # type: ignore[union-attr]

            error_code = "oauth_error"
            error_desc = "Authentication failed at OAuth token endpoint."
            try:
                err_data = json.loads(resp.body.decode("utf-8"))
                if isinstance(err_data, dict):
                    error_code = str(err_data.get("error", "oauth_error"))
                    error_desc = f"OAuth error: {error_code}"
            except Exception:
                pass

            return None, ClassifiedError.from_category(
                ErrorCategory.AUTHENTICATION,
                f"Salesforce OAuth token request rejected (HTTP {resp.status_code}): {error_desc}",
                details={"http_status": resp.status_code, "safe_code": error_code},
            )

        # Parse successful response
        try:
            data = json.loads(resp.body.decode("utf-8"))
        except Exception:
            return None, ClassifiedError.from_category(
                ErrorCategory.TRANSIENT_SERVICE,
                "Malformed JSON received from Salesforce OAuth token endpoint.",
                details={"safe_code": "malformed_token_response"},
            )

        access_token = data.get("access_token")
        instance_url = data.get("instance_url")
        token_type = data.get("token_type", "Bearer")
        expires_in = data.get("expires_in")
        new_refresh_token = data.get("refresh_token")

        if not access_token or not instance_url:
            return None, ClassifiedError.from_category(
                ErrorCategory.TRANSIENT_SERVICE,
                "Salesforce OAuth response missing required access_token or instance_url.",
                details={"safe_code": "invalid_token_payload"},
            )

        # Origin verification: returned instance origin must be approved
        if not self.settings.is_origin_approved(instance_url):
            return None, ClassifiedError.from_category(
                ErrorCategory.PERMISSION,
                "Salesforce OAuth returned instance_url with unapproved origin.",
                details={"safe_code": "unapproved_token_instance_origin"},
            )

        # If token rotation returned a new refresh token, atomically update it
        if new_refresh_token and isinstance(new_refresh_token, str):
            self.store.set_credential(self.settings.credential_ref, new_refresh_token)  # type: ignore[arg-type]

        # Clear progress marker upon successful commit
        if has_progress:
            self.store.clear_exchange_in_progress(self.settings.credential_ref)  # type: ignore[union-attr]

        now = self.clock.monotonic()
        expires_at: float | None = None
        if expires_in is not None:
            try:
                expires_at = now + float(expires_in)
            except (ValueError, TypeError):
                expires_at = None

        return SalesforceSession(
            access_token=access_token,
            instance_url=instance_url,
            token_type=token_type,
            issued_at=now,
            expires_at=expires_at,
            refresh_token=new_refresh_token,
        ), None
