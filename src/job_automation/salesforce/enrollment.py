"""One-time interactive OAuth enrollment and token provisioning for SF-02.

Implements:
- PKCE S256 code verifier and challenge generation (RFC 7636).
- Transient HTTP loopback listener on http://localhost:1717/OauthRedirect.
- CSRF state token verification.
- Single-use code exchange for refresh_token without client secret.
- Expected Org ID and User ID validation.
- Native Windows DPAPI encrypted storage via WindowsDpapiCredentialStore.
- Remote token revocation via /services/oauth2/revoke and local cleanup.
- Strict suppression of tokens, codes, and secrets from logs and diagnostics.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import sys
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from job_automation.configuration import load_config
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.salesforce.configuration import (
    SalesforceSettings,
    load_salesforce_settings,
    validate_https_url,
)
from job_automation.salesforce.credentials import (
    WindowsDpapiCredentialStore,
)
from job_automation.salesforce.ports import CredentialStore, HttpTransport
from job_automation.salesforce.transport import UrllibHttpTransport

LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = 1717
CALLBACK_PATH = "/OauthRedirect"
EXACT_CALLBACK_URL = f"http://localhost:{LOOPBACK_PORT}{CALLBACK_PATH}"


class EnrollmentError(Exception):
    """Exception raised during OAuth enrollment."""


def generate_pkce_pair() -> tuple[str, str]:
    """Generate RFC 7636 PKCE code_verifier and S256 code_challenge.

    Verifier: high-entropy cryptographic random string (43-128 chars).
    Challenge: BASE64URL-ENCODE(SHA256(code_verifier)) without padding.
    """
    raw_verifier = secrets.token_bytes(32)
    code_verifier = base64.urlsafe_b64encode(raw_verifier).decode("ascii").rstrip("=")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


def generate_state_token() -> str:
    """Generate high-entropy cryptographic random state token for CSRF defense."""
    return secrets.token_urlsafe(32)


def normalize_salesforce_id(sf_id: str | None) -> str | None:
    """Normalize and clean a 15-char or 18-char Salesforce ID."""
    if not sf_id:
        return None
    cleaned = sf_id.strip()
    return cleaned


def are_salesforce_ids_equal(id_a: str | None, id_b: str | None) -> bool:
    """Compare two Salesforce IDs safely handling 15-char vs 18-char forms."""
    if not id_a or not id_b:
        return False
    a = id_a.strip()
    b = id_b.strip()
    if len(a) == 18 and len(b) == 18:
        return a.lower() == b.lower()
    # If one or both is 15-chars, compare the first 15 characters case-sensitively
    return a[:15] == b[:15]


def build_authorization_url(
    settings: SalesforceSettings,
    client_id: str,
    code_challenge: str,
    state: str,
    redirect_uri: str = EXACT_CALLBACK_URL,
) -> str:
    """Construct authorization URL for OAuth 2.0 Web Server Flow with PKCE."""
    # Base authorization endpoint
    base_auth = f"{settings.instance_url.rstrip('/')}/services/oauth2/authorize"
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "scope": "api refresh_token",
        "prompt": "login consent",
    }
    return f"{base_auth}?{urllib.parse.urlencode(params)}"


@dataclass
class CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None
    error_description: str | None = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Single-request HTTP handler for OAuth loopback redirect."""

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress logging to prevent printing codes or states to console
        pass

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        qs = parse_qs(parsed.query)
        code = qs.get("code", [None])[0]
        state = qs.get("state", [None])[0]
        error = qs.get("error", [None])[0]
        error_desc = qs.get("error_description", [None])[0]

        self.server.result = CallbackResult(  # type: ignore[attr-defined]
            code=code,
            state=state,
            error=error,
            error_description=error_desc,
        )

        if error:
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            body = (
                "<html><body><h2>Salesforce Authorization Failed</h2>"
                f"<p>Error: {error}</p>"
                "<p>You can close this browser tab.</p></body></html>"
            )
            self.wfile.write(body.encode("utf-8"))
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            body = (
                "<html><body><h2>Salesforce Authorization Successful!</h2>"
                "<p>Credentials received and protected via Windows DPAPI.</p>"
                "<p>You can safely close this browser tab and return to the terminal.</p></body></html>"
            )
            self.wfile.write(body.encode("utf-8"))


class LoopbackServer(http.server.HTTPServer):
    def __init__(self, host: str, port: int) -> None:
        super().__init__((host, port), _CallbackHandler)
        self.result: CallbackResult | None = None


def is_port_available(host: str, port: int) -> bool:
    """Check if the designated loopback port is available."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def wait_for_callback(
    server: LoopbackServer, timeout_seconds: float = 120.0
) -> CallbackResult:
    """Wait for incoming loopback callback within timeout."""
    server.timeout = 1.0
    elapsed = 0.0
    while elapsed < timeout_seconds and server.result is None:
        server.handle_request()
        elapsed += 1.0

    if server.result is None:
        raise EnrollmentError(
            f"Timed out waiting for Salesforce browser callback after {timeout_seconds} seconds."
        )
    return server.result


def exchange_code_for_tokens(
    settings: SalesforceSettings,
    transport: HttpTransport,
    client_id: str,
    code: str,
    code_verifier: str,
    redirect_uri: str = EXACT_CALLBACK_URL,
) -> dict[str, Any]:
    """Exchange authorization code with PKCE verifier for refresh and access tokens."""
    payload_params = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    body_bytes = urllib.parse.urlencode(payload_params).encode("utf-8")
    headers = {
        "content-type": "application/x-www-form-urlencoded",
        "accept": "application/json",
        "user-agent": "job-automation/0.1 (SF-02; Enrollment)",
    }

    try:
        resp = transport.request(
            method="POST",
            url=settings.token_url,
            headers=headers,
            body=body_bytes,
            timeout=settings.connect_timeout_seconds + settings.read_timeout_seconds,
        )
    except Exception as exc:
        raise EnrollmentError(f"Network error contacting token endpoint: {exc}") from exc

    if resp.status_code != 200:
        error_code = f"HTTP_{resp.status_code}"
        try:
            err_data = json.loads(resp.body.decode("utf-8"))
            if isinstance(err_data, dict):
                error_code = str(err_data.get("error", error_code))
        except Exception:
            pass
        raise EnrollmentError(
            f"Token exchange rejected by Salesforce (safe_code={error_code})."
        )

    try:
        data = json.loads(resp.body.decode("utf-8"))
    except Exception as exc:
        raise EnrollmentError("Malformed JSON response from token endpoint.") from exc

    if not isinstance(data, dict):
        raise EnrollmentError("Invalid token response payload shape.")

    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    instance_url = data.get("instance_url")

    if not access_token or not refresh_token or not instance_url:
        raise EnrollmentError(
            "Token response missing required access_token, refresh_token, or instance_url."
        )

    # Origin verification
    if not settings.is_origin_approved(instance_url):
        raise EnrollmentError(
            f"Token response returned instance_url with unapproved origin: '{instance_url}'."
        )

    return data


def extract_identity_from_id_url(id_url: str) -> tuple[str | None, str | None]:
    """Parse org_id and user_id from Salesforce identity URL (https://login.salesforce.com/id/00D.../005...)."""
    try:
        p = urlparse(id_url)
        parts = [seg for seg in p.path.split("/") if seg]
        if len(parts) >= 3 and parts[0] == "id":
            return parts[1], parts[2]
    except Exception:
        pass
    return None, None


def verify_identity_binding(
    settings: SalesforceSettings,
    token_data: dict[str, Any],
) -> tuple[str, str]:
    """Verify that returned token identity matches configured expected_org_id and expected_user_id."""
    id_url = token_data.get("id", "")
    returned_org_id, returned_user_id = extract_identity_from_id_url(id_url)

    if settings.expected_org_id:
        if not returned_org_id or not are_salesforce_ids_equal(returned_org_id, settings.expected_org_id):
            raise EnrollmentError(
                f"Org ID mismatch: authenticated org '{returned_org_id}' does not match expected '{settings.expected_org_id}'."
            )

    if settings.expected_user_id:
        if not returned_user_id or not are_salesforce_ids_equal(returned_user_id, settings.expected_user_id):
            raise EnrollmentError(
                f"User ID mismatch: authenticated user '{returned_user_id}' does not match expected '{settings.expected_user_id}'."
            )

    return returned_org_id or "unknown_org", returned_user_id or "unknown_user"


def execute_enrollment(
    settings: SalesforceSettings,
    store: CredentialStore,
    transport: HttpTransport,
    client_id: str,
    timeout_seconds: float = 120.0,
    open_browser: bool = True,
) -> tuple[str, str]:
    """Execute complete interactive OAuth authorization code flow with PKCE."""
    if not is_port_available(LOOPBACK_HOST, LOOPBACK_PORT):
        raise EnrollmentError(
            f"Loopback port {LOOPBACK_PORT} on {LOOPBACK_HOST} is currently in use by another process."
        )

    if not settings.client_id_ref or not settings.credential_ref:
        raise EnrollmentError(
            "SalesforceSettings missing client_id_ref or credential_ref."
        )

    code_verifier, code_challenge = generate_pkce_pair()
    state_token = generate_state_token()

    auth_url = build_authorization_url(
        settings=settings,
        client_id=client_id,
        code_challenge=code_challenge,
        state=state_token,
    )

    server = LoopbackServer(LOOPBACK_HOST, LOOPBACK_PORT)
    try:
        if open_browser:
            print("\nOpening system browser for Salesforce interactive authentication...")
            print(f"Target Instance: {settings.instance_url}")
            print("Please sign in and approve access in the browser window.\n")
            webbrowser.open(auth_url)

        cb_result = wait_for_callback(server, timeout_seconds=timeout_seconds)
    finally:
        server.server_close()

    if cb_result.error:
        raise EnrollmentError(f"OAuth error from Salesforce: {cb_result.error}")

    if not cb_result.code or not cb_result.state:
        raise EnrollmentError("Missing code or state in authorization callback.")

    if not secrets.compare_digest(cb_result.state, state_token):
        raise EnrollmentError(
            "State parameter mismatch in callback (possible CSRF or concurrent session)."
        )

    # Code exchange
    token_data = exchange_code_for_tokens(
        settings=settings,
        transport=transport,
        client_id=client_id,
        code=cb_result.code,
        code_verifier=code_verifier,
    )

    # Identity check
    org_id, user_id = verify_identity_binding(settings, token_data)

    # Persist credentials into protected store
    refresh_token = token_data["refresh_token"]
    store.set_credential(settings.client_id_ref, client_id)
    store.set_credential(settings.credential_ref, refresh_token)

    return org_id, user_id


def revoke_salesforce_tokens(
    settings: SalesforceSettings,
    store: CredentialStore,
    transport: HttpTransport,
) -> bool:
    """Revoke refresh token with Salesforce and remove protected credentials from local store."""
    if not settings.credential_ref:
        return False

    refresh_token = store.get_credential(settings.credential_ref)
    remote_success = False

    if refresh_token:
        revoke_url = f"{settings.instance_url.rstrip('/')}/services/oauth2/revoke"
        params = {
            "token": refresh_token,
            "token_type_hint": "refresh_token",
        }
        body_bytes = urllib.parse.urlencode(params).encode("utf-8")
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "accept": "application/json",
            "user-agent": "job-automation/0.1 (SF-02; Revocation)",
        }
        try:
            resp = transport.request(
                method="POST",
                url=revoke_url,
                headers=headers,
                body=body_bytes,
                timeout=settings.connect_timeout_seconds + settings.read_timeout_seconds,
            )
            remote_success = resp.status_code == 200
        except Exception:
            remote_success = False

    # In either case, remove credentials from local store
    store.delete_credential(settings.credential_ref)
    if settings.client_id_ref:
        store.delete_credential(settings.client_id_ref)

    return remote_success


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Salesforce OAuth 2.0 PKCE Enrollment and Credential Provisioning (SF-02)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to configuration JSON (salesforce.json or app.json)",
    )
    parser.add_argument(
        "--client-id",
        type=str,
        default=None,
        help="Salesforce External Client App Consumer Key (Client ID)",
    )
    parser.add_argument(
        "--revoke",
        action="store_true",
        help="Revoke existing refresh token and remove local credentials",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Timeout in seconds for interactive browser authorization",
    )

    args = parser.parse_args()

    # Resolve settings and credential directory
    settings: SalesforceSettings | None = None
    credential_dir: Path | None = None

    if args.config and args.config.is_file():
        try:
            with open(args.config, "r", encoding="utf-8") as f:
                content = f.read()
            if "salesforce_settings_ref" in content or "data_root" in content:
                app_config, paths = load_config(args.config)
                credential_dir = paths.data_root / "credentials"
                if paths.salesforce_settings_path and paths.salesforce_settings_path.is_file():
                    settings = load_salesforce_settings(paths.salesforce_settings_path)
            else:
                settings = load_salesforce_settings(args.config)
                credential_dir = args.config.parent / "credentials"
        except Exception as exc:
            print(f"[ERROR] Failed to load configuration: {exc}")
            sys.exit(2)
    else:
        # Check standard default path
        local_app = Path(os.environ.get("LOCALAPPDATA", "")) / "JobAutomation"
        std_app_config = local_app / "config" / "app.json"
        std_sf_config = Path("config") / "salesforce.json"

        if std_sf_config.is_file():
            settings = load_salesforce_settings(std_sf_config)
            credential_dir = local_app / "credentials"
        elif std_app_config.is_file():
            app_config, paths = load_config(std_app_config)
            credential_dir = paths.data_root / "credentials"
            if paths.salesforce_settings_path and paths.salesforce_settings_path.is_file():
                settings = load_salesforce_settings(paths.salesforce_settings_path)

    if not settings or not credential_dir:
        print("[ERROR] Could not resolve SalesforceSettings or credential directory.")
        print("Please specify --config pointing to a valid salesforce.json or app.json.")
        sys.exit(2)

    store = WindowsDpapiCredentialStore(credential_dir)
    transport = UrllibHttpTransport(settings)

    if args.revoke:
        print("=== Salesforce Token Revocation ===")
        success = revoke_salesforce_tokens(settings, store, transport)
        if success:
            print("[PASSED] Remote token revoked successfully and local DPAPI credentials deleted.")
        else:
            print("[NOTICE] Remote token revocation was unreachable or failed, but local DPAPI credentials were removed.")
        sys.exit(0)

    # Enrollment
    print("=== Salesforce OAuth PKCE Enrollment (SF-02) ===")
    client_id = args.client_id
    if not client_id and settings.client_id_ref:
        client_id = store.get_credential(settings.client_id_ref)

    if not client_id:
        print("[ERROR] Client ID (Consumer Key) must be provided via --client-id or pre-stored.")
        sys.exit(2)

    try:
        org_id, user_id = execute_enrollment(
            settings=settings,
            store=store,
            transport=transport,
            client_id=client_id,
            timeout_seconds=args.timeout,
        )
        print("\n=== Enrollment Successful ===")
        print(f"Org ID: {org_id}")
        print(f"User ID: {user_id}")
        print("Credentials protected using native Windows DPAPI.")
        print(f"Credential Store: {credential_dir}")
        sys.exit(0)
    except EnrollmentError as err:
        print(f"\n[FAILED] Enrollment failed: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()

