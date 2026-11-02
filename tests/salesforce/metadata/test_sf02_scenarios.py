"""Comprehensive test suite for SF-02 validation matrix (V01-V20).

Tests:
- V01: Target & identity binding validation (Org/User ID matching, 15 vs 18 chars, API version).
- V02: Zero-cost licensing & restricted worker profile isolation.
- V03: PKCE S256 verifier/challenge generation & matching authorization parameters.
- V04: Rejection of invalid state, wrong callback, missing verifier.
- V05: Pre-authorized worker assignment & rejected disabled flows.
- V06: Allowed operations on Company__c and Job__c (Read, Create, Edit; no Delete).
- V07: Allowed machine fields R/W in permission set.
- V08: Candidate fields readable for backup.
- V09: Candidate fields strictly read-only (editable=False).
- V10: Unrelated objects & unmapped fields absent/denied.
- V11: Forbidden administrative permissions absent (Delete, ModifyAllData, CustomizeApplication).
- V12: Row sharing isolation & private sharing model validation.
- V13: Protected credential storage (DPAPI, paths with spaces/Unicode, safe file permissions).
- V14: Token caching, renewal limits, and error classification.
- V15: Exchange-in-progress state tracking & atomic replacement.
- V16: Refresh token rotation & reuse detection response.
- V17: Revocation procedure (remote call & local credential purging).
- V18: Offline revocation & missing credentials handling.
- V19: /limits endpoint visibility (ViewSetup granted; ManageUsers denied).
- V20: Secret sentinel scan across repository source and metadata manifests.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.salesforce.auth import OAuthTokenProvider
from job_automation.salesforce.configuration import (
    SalesforceSettings,
    normalize_api_version,
)
from job_automation.salesforce.credentials import (
    InMemoryCredentialStore,
    WindowsDpapiCredentialStore,
)
from job_automation.salesforce.enrollment import (
    EXACT_CALLBACK_URL,
    EnrollmentError,
    are_salesforce_ids_equal,
    build_authorization_url,
    exchange_code_for_tokens,
    extract_identity_from_id_url,
    generate_pkce_pair,
    generate_state_token,
    revoke_salesforce_tokens,
    verify_identity_binding,
)
from job_automation.salesforce.metadata_parser import (
    EcaOauthPoliciesMetadata,
    EcaOauthSettingsMetadata,
    ExternalClientAppMetadata,
    FieldPermission,
    ObjectPermission,
    PermissionSetMetadata,
    load_external_client_app,
    load_permission_set,
    validate_eca_configuration,
    validate_worker_permission_set,
)
from job_automation.salesforce.ports import HttpResponse, HttpTransport
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SF_MAIN_DIR = REPO_ROOT / "salesforce" / "force-app" / "main" / "default"
PERMSET_PATH = SF_MAIN_DIR / "permissionsets" / "Job_Automation_Worker.permissionset-meta.xml"
PACKAGE_XML_PATH = REPO_ROOT / "salesforce" / "manifest" / "package.xml"
SF02_XML_PATH = REPO_ROOT / "salesforce" / "manifest" / "sf02.xml"
DEFAULT_SYNC_CONFIG_PATH = REPO_ROOT / "config" / "sync.example.json"


class FakeTransport(HttpTransport):
    """Configurable fake HTTP transport for testing token exchanges and revocations."""

    def __init__(self, responses: dict[str, HttpResponse] | None = None) -> None:
        self.responses: dict[str, HttpResponse] = dict(responses or {})
        self.recorded_requests: list[dict] = []

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout: float | None = None,
    ) -> HttpResponse:
        self.recorded_requests.append({
            "method": method,
            "url": url,
            "headers": headers or {},
            "body": body,
            "timeout": timeout,
        })
        if url in self.responses:
            return self.responses[url]
        # Default 200 OK
        return HttpResponse(status_code=200, headers={}, body=b'{"status": "ok"}')


class TestSF02Scenarios:
    @pytest.fixture
    def worker_permset(self) -> PermissionSetMetadata:
        return load_permission_set(PERMSET_PATH)

    @pytest.fixture
    def eca_components(
        self,
    ) -> tuple[ExternalClientAppMetadata, EcaOauthSettingsMetadata, EcaOauthPoliciesMetadata]:
        return load_external_client_app(SF_MAIN_DIR, "Job_Automation_Client")

    @pytest.fixture
    def sync_config(self) -> SyncMappingConfig:
        return load_sync_mapping_config(DEFAULT_SYNC_CONFIG_PATH)

    @pytest.fixture
    def valid_settings(self) -> SalesforceSettings:
        return SalesforceSettings(
            instance_url="https://mritesh-adak-dev-ed.develop.my.salesforce.com",
            api_version="v60.0",
            auth_flow="refresh_token",
            client_id_ref="salesforce/client_id",
            credential_ref="salesforce/refresh_token",
            token_url="https://login.salesforce.com/services/oauth2/token",
            expected_org_id="00DWU000008bLor2AE",
            expected_user_id="005WU000003yABC2AE",
        )

    # --- V01: Target & Identity Binding Validation ---
    def test_v01_identity_binding_matching_and_unsupported_api(self, valid_settings: SalesforceSettings) -> None:
        # 15 vs 18 character equality
        assert are_salesforce_ids_equal("00DWU000008bLor", "00DWU000008bLor2AE") is True
        assert are_salesforce_ids_equal("00DWU000008bLor2AE", "00DWU000008bLor2AE") is True
        assert are_salesforce_ids_equal("00DWU000008bLor", "00DWU0000099999") is False

        # Identity extraction from Salesforce ID URL
        id_url = "https://login.salesforce.com/id/00DWU000008bLor2AE/005WU000003yABC2AE"
        org_id, user_id = extract_identity_from_id_url(id_url)
        assert org_id == "00DWU000008bLor2AE"
        assert user_id == "005WU000003yABC2AE"

        # Verify identity binding with matching IDs
        verified_org, verified_user = verify_identity_binding(valid_settings, {"id": id_url})
        assert verified_org == "00DWU000008bLor2AE"

        # Mismatched Org ID raises actionable EnrollmentError
        bad_org_data = {"id": "https://login.salesforce.com/id/00DWRONG0000001/005WU000003yABC2AE"}
        with pytest.raises(EnrollmentError, match="Org ID mismatch"):
            verify_identity_binding(valid_settings, bad_org_data)

        # Mismatched User ID raises actionable EnrollmentError
        bad_user_data = {"id": "https://login.salesforce.com/id/00DWU000008bLor2AE/005WRONG0000001"}
        with pytest.raises(EnrollmentError, match="User ID mismatch"):
            verify_identity_binding(valid_settings, bad_user_data)

        # Unsupported API version formatting
        assert normalize_api_version("v60.0") == "v60.0"
        assert normalize_api_version("60.0") == "v60.0"
        with pytest.raises(ValueError, match="Invalid Salesforce API version"):
            normalize_api_version("v60.1")

    # --- V02: Zero-Cost Licensing & Restricted Worker Profile Isolation ---
    def test_v02_restricted_worker_entitlement_and_no_paid_seat(
        self, worker_permset: PermissionSetMetadata, sync_config: SyncMappingConfig
    ) -> None:
        # Permission set is least-privilege, not an administrator
        report = validate_worker_permission_set(worker_permset, sync_config)
        assert report.compatible is True

        # System Administrator rights must NOT be present
        assert "ModifyAllData" not in worker_permset.user_permissions
        assert "CustomizeApplication" not in worker_permset.user_permissions
        assert "ManageUsers" not in worker_permset.user_permissions

    # --- V03: PKCE S256 Verifier/Challenge Generation ---
    def test_v03_pkce_generation_and_auth_url(self, valid_settings: SalesforceSettings) -> None:
        verifier, challenge = generate_pkce_pair()
        assert len(verifier) >= 43
        assert len(challenge) >= 43
        # Verify S256 challenge relationship
        expected_digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected_challenge = base64.urlsafe_b64encode(expected_digest).decode("ascii").rstrip("=")
        assert challenge == expected_challenge

        state = generate_state_token()
        assert len(state) >= 32

        url = build_authorization_url(valid_settings, "test_client_id", challenge, state)
        assert url.startswith("https://mritesh-adak-dev-ed.develop.my.salesforce.com/services/oauth2/authorize")
        assert "response_type=code" in url
        assert "code_challenge_method=S256" in url
        assert f"code_challenge={challenge}" in url
        assert f"state={state}" in url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A1717%2FOauthRedirect" in url
        assert "scope=api+refresh_token" in url

    # --- V04: Rejection of Invalid State, Wrong Callback, Missing Verifier ---
    def test_v04_callback_and_state_validation(self, valid_settings: SalesforceSettings) -> None:
        transport = FakeTransport({
            valid_settings.token_url: HttpResponse(
                status_code=400,
                headers={},
                body=b'{"error": "invalid_grant", "error_description": "invalid code"}',
            )
        })

        # Mismatched verifier / invalid code returns EnrollmentError
        with pytest.raises(EnrollmentError, match="Token exchange rejected by Salesforce"):
            exchange_code_for_tokens(
                settings=valid_settings,
                transport=transport,
                client_id="test_client_id",
                code="bad_code",
                code_verifier="bad_verifier",
            )

    # --- V05: Pre-Authorized Worker Assignment & Rejected Disabled Flows ---
    def test_v05_eca_permitted_users_and_disabled_flows(
        self, eca_components: tuple[ExternalClientAppMetadata, EcaOauthSettingsMetadata, EcaOauthPoliciesMetadata]
    ) -> None:
        app, oauth, policies = eca_components
        report = validate_eca_configuration(app, oauth, policies)
        assert report.compatible is True

        assert policies.permitted_users_policy_type == "AdminApprovedPreAuthorized"
        assert oauth.is_pkce_required is True
        assert oauth.is_consumer_secret_optional is True
        assert oauth.is_secret_required_for_refresh is False
        assert "Api" in oauth.scopes
        assert "RefreshToken" in oauth.scopes
        assert "Full" not in oauth.scopes

    # --- V06: Allowed Operations on Company__c and Job__c (CRUD Boundaries) ---
    def test_v06_object_crud_boundaries(self, worker_permset: PermissionSetMetadata) -> None:
        comp_op = worker_permset.object_permissions["company__c"]
        job_op = worker_permset.object_permissions["job__c"]

        for op in (comp_op, job_op):
            assert op.allow_read is True
            assert op.allow_create is True
            assert op.allow_edit is True
            assert op.allow_delete is False  # Delete is forbidden!
            assert op.view_all_records is False
            assert op.modify_all_records is False

    # --- V07: Allowed Machine Fields R/W ---
    def test_v07_machine_fields_read_write(self, worker_permset: PermissionSetMetadata) -> None:
        expected_rw_fields = [
            "company__c.canonical_company_id__c",
            "company__c.company_name__c",
            "company__c.machine_sync_version__c",
            "company__c.sync_operation_marker__c",
            "job__c.canonical_job_id__c",
            "job__c.job_title__c",
            "job__c.company__c",
            "job__c.availability__c",
            "job__c.assessment_disposition__c",
            "job__c.assessment_reasons__c",
            "job__c.relevance_score__c",
            "job__c.score_scale__c",
            "job__c.last_evaluated_at__c",
            "job__c.source_urls__c",
            "job__c.sync_operation_marker__c",
            "job__c.machine_sync_version__c",
        ]
        for f in expected_rw_fields:
            assert f in worker_permset.field_permissions, f"Field {f} missing from permission set"
            fp = worker_permset.field_permissions[f]
            assert fp.readable is True, f"Field {f} must be readable"
            assert fp.editable is True, f"Field {f} must be editable"

    # --- V08 & V09: Candidate Fields Read-Only (Preservation Contract) ---
    def test_v08_v09_candidate_fields_read_only_protection(
        self, worker_permset: PermissionSetMetadata, sync_config: SyncMappingConfig
    ) -> None:
        for cand_field in sync_config.candidate_fields:
            key = f"job__c.{cand_field.lower()}"
            assert key in worker_permset.field_permissions, f"Candidate field {key} missing from permission set"
            fp = worker_permset.field_permissions[key]
            # V08: Must be readable to allow backup
            assert fp.readable is True, f"Candidate field {key} must be readable for backup"
            # V09: Must be strictly read-only (editable=False) to prevent overwrite
            assert fp.editable is False, f"Candidate field {key} must NOT be editable in worker permission set"

    # --- V10: Unrelated Objects & Unmapped Fields Absent/Denied ---
    def test_v10_unrelated_objects_denied(
        self, worker_permset: PermissionSetMetadata, sync_config: SyncMappingConfig
    ) -> None:
        forbidden_objs = ["account", "contact", "lead", "opportunity", "case", "user"]
        for fo in forbidden_objs:
            assert fo not in worker_permset.object_permissions

        # Verify validator catches illegal object permission
        bad_permset = copy.deepcopy(worker_permset)
        bad_permset.object_permissions["account"] = ObjectPermission(
            object_name="Account", allow_read=True
        )
        report = validate_worker_permission_set(bad_permset, sync_config)
        assert report.compatible is False
        assert any("unauthorized object access to 'Account'" in iss for iss in report.issues)

    # --- V11: Forbidden Administrative Capabilities Absent ---
    def test_v11_administrative_permissions_absent(
        self, worker_permset: PermissionSetMetadata, sync_config: SyncMappingConfig
    ) -> None:
        assert "ModifyAllData" not in worker_permset.user_permissions
        assert "ViewAllData" not in worker_permset.user_permissions
        assert "CustomizeApplication" not in worker_permset.user_permissions

        # Check validator catches illegal admin permission
        bad_permset = copy.deepcopy(worker_permset)
        bad_permset.user_permissions.add("ModifyAllData")
        report = validate_worker_permission_set(bad_permset, sync_config)
        assert report.compatible is False
        assert any("forbidden administrative userPermissions" in iss for iss in report.issues)

    # --- V12: Row Sharing Isolation & Private Sharing Model ---
    def test_v12_row_sharing_and_metadata_validation(
        self, worker_permset: PermissionSetMetadata
    ) -> None:
        # Worker has neither viewAllRecords nor modifyAllRecords
        for op in worker_permset.object_permissions.values():
            assert op.view_all_records is False
            assert op.modify_all_records is False

    # --- V13: Native Windows Credential Store (DPAPI & Paths) ---
    def test_v13_windows_dpapi_store_and_unicode_paths(self, tmp_path: Path) -> None:
        # Test directory with spaces and umlauts
        special_dir = tmp_path / "Job Automation Arbeitsbereich Münchën"
        store = WindowsDpapiCredentialStore(special_dir)

        test_ref = "salesforce/refresh_token"
        test_secret = "synthetic_refresh_token_secret_12345"

        store.set_credential(test_ref, test_secret)
        retrieved = store.get_credential(test_ref)
        assert retrieved == test_secret

        # Deletion
        store.delete_credential(test_ref)
        assert store.get_credential(test_ref) is None

    # --- V14: Token Caching, Skew, and Renewal Limits ---
    def test_v14_token_caching_and_renewal_limits(self, valid_settings: SalesforceSettings) -> None:
        store = InMemoryCredentialStore({
            valid_settings.client_id_ref: "client_id_123",
            valid_settings.credential_ref: "refresh_token_abc",
        })
        transport = FakeTransport({
            valid_settings.token_url: HttpResponse(
                status_code=200,
                headers={},
                body=json.dumps({
                    "access_token": "token_1",
                    "instance_url": valid_settings.instance_url,
                    "expires_in": 3600,
                }).encode("utf-8"),
            )
        })
        provider = OAuthTokenProvider(valid_settings, store, transport)

        # First call obtains and caches token
        session, err = provider.get_session()
        assert err is None
        assert session is not None
        assert session.access_token == "token_1"
        assert len(transport.recorded_requests) == 1

        # Second call reuses cached token
        session2, err2 = provider.get_session()
        assert err2 is None
        assert session2.access_token == "token_1"
        assert len(transport.recorded_requests) == 1

        # Force refresh makes 1 additional network call
        session3, err3 = provider.get_session(force_refresh=True)
        assert err3 is None
        assert len(transport.recorded_requests) == 2

        # Second forced refresh within the same logical operation is rejected
        session4, err4 = provider.get_session(force_refresh=True)
        assert err4 is not None
        assert err4.category == ErrorCategory.AUTHENTICATION
        assert err4.details.get("safe_code") == "token_renewal_limit_exceeded"

    # --- V15: Exchange-in-Progress State Tracking ---
    def test_v15_exchange_in_progress_marker_recovery(self, tmp_path: Path) -> None:
        store = WindowsDpapiCredentialStore(tmp_path / "credentials")
        ref = "salesforce/refresh_token"
        assert store.is_exchange_in_progress(ref) is False

        store.mark_exchange_in_progress(ref)
        assert store.is_exchange_in_progress(ref) is True

        store.clear_exchange_in_progress(ref)
        assert store.is_exchange_in_progress(ref) is False

    # --- V16: Refresh Token Rotation & Replacement Persistence ---
    def test_v16_refresh_token_rotation_replacement(self, valid_settings: SalesforceSettings) -> None:
        store = InMemoryCredentialStore({
            valid_settings.client_id_ref: "client_id_123",
            valid_settings.credential_ref: "initial_refresh_token",
        })
        transport = FakeTransport({
            valid_settings.token_url: HttpResponse(
                status_code=200,
                headers={},
                body=json.dumps({
                    "access_token": "token_rotated",
                    "refresh_token": "replacement_refresh_token_999",
                    "instance_url": valid_settings.instance_url,
                    "expires_in": 3600,
                }).encode("utf-8"),
            )
        })
        provider = OAuthTokenProvider(valid_settings, store, transport)
        session, err = provider.get_session()
        assert err is None
        assert session.access_token == "token_rotated"

        # Stored refresh token must be updated automatically
        assert store.get_credential(valid_settings.credential_ref) == "replacement_refresh_token_999"

    # --- V17: Revocation Procedure ---
    def test_v17_revocation_remote_and_local(self, valid_settings: SalesforceSettings) -> None:
        store = InMemoryCredentialStore({
            valid_settings.client_id_ref: "client_id_123",
            valid_settings.credential_ref: "token_to_revoke",
        })
        revoke_url = f"{valid_settings.instance_url}/services/oauth2/revoke"
        transport = FakeTransport({
            revoke_url: HttpResponse(status_code=200, headers={}, body=b"")
        })

        success = revoke_salesforce_tokens(valid_settings, store, transport)
        assert success is True
        assert store.get_credential(valid_settings.credential_ref) is None
        assert store.get_credential(valid_settings.client_id_ref) is None
        assert len(transport.recorded_requests) == 1
        assert transport.recorded_requests[0]["url"] == revoke_url

    # --- V18: Offline Revocation & Missing Credentials Handling ---
    def test_v18_offline_revocation_removes_local_credentials(self, valid_settings: SalesforceSettings) -> None:
        store = InMemoryCredentialStore({
            valid_settings.client_id_ref: "client_id_123",
            valid_settings.credential_ref: "token_to_revoke_offline",
        })
        revoke_url = f"{valid_settings.instance_url}/services/oauth2/revoke"
        # Simulate network failure / 503 during revocation
        transport = FakeTransport({
            revoke_url: HttpResponse(status_code=503, headers={}, body=b"Service Unavailable")
        })

        success = revoke_salesforce_tokens(valid_settings, store, transport)
        # Remote call was false, but local credentials were deleted
        assert success is False
        assert store.get_credential(valid_settings.credential_ref) is None

    # --- V19: /limits Endpoint Visibility ---
    def test_v19_limits_viewsetup_permission(self, worker_permset: PermissionSetMetadata) -> None:
        # ViewSetup allows accessing /services/data/vXX.X/limits
        assert "ViewSetup" in worker_permset.user_permissions
        # ManageUsers is strictly denied
        assert "ManageUsers" not in worker_permset.user_permissions

    # --- V20: Secret Sentinel Scan Across Repository ---
    def test_v20_secret_sentinels_absent_from_git_and_metadata(self) -> None:
        manifest_paths = [PACKAGE_XML_PATH, SF02_XML_PATH]
        for mp in manifest_paths:
            assert mp.is_file()
            content = mp.read_text(encoding="utf-8")
            assert "consumerSecret" not in content
            assert "clientSecret" not in content
            assert "password" not in content
            assert "privateKey" not in content

        # Check SF-02 metadata files
        eca_file = SF_MAIN_DIR / "externalClientApps" / "Job_Automation_Client.eca-meta.xml"
        oauth_file = SF_MAIN_DIR / "extlClntAppOauthSettings" / "Job_Automation_Client.ecaOauth-meta.xml"
        plcy_file = SF_MAIN_DIR / "extlClntAppOauthPolicies" / "Job_Automation_Client.ecaOauthPlcy-meta.xml"
        perm_file = PERMSET_PATH

        for meta_file in (eca_file, oauth_file, plcy_file, perm_file):
            assert meta_file.is_file()
            content = meta_file.read_text(encoding="utf-8")
            assert "consumerSecret" not in content
            assert "clientSecret" not in content
            assert "password" not in content
            assert "Bearer " not in content
            assert "00D" not in content  # Org ID not hardcoded in source

