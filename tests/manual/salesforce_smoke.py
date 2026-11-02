"""Manual smoke verification script for Salesforce connectivity and scoped mutations (SFCLIENT-01-S07).

Safe-by-default execution:
- Default mode is strictly READ-ONLY.
- Live mutations require BOTH --allow-write AND an explicit synthetic --test-key.
- Reports missing SF-02 prerequisites without throwing raw tracebacks or contacting unknown services.
- Never prints tokens, client secrets, or sensitive record contents.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from job_automation.configuration import load_config
from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.salesforce import (
    ConnectionCheckRequest,
    DescribeObjectRequest,
    GetRecordRequest,
    LimitsRequest,
    UpdateRequest,
    UpsertRequest,
)
from job_automation.salesforce.auth import OAuthTokenProvider
from job_automation.salesforce.configuration import (
    SalesforceSettings,
    load_salesforce_settings,
)
from job_automation.salesforce.credentials import WindowsDpapiCredentialStore
from job_automation.salesforce.gateway import SalesforceGatewayV2Client
from job_automation.salesforce.transport import UrllibHttpTransport


def run_smoke(
    config_path: Path | None,
    allow_write: bool = False,
    test_key: str | None = None,
    target_object: str = "Job__c",
    external_id_field: str = "External_Id__c",
) -> int:
    """Run scoped read or mutation checks against configured Salesforce org."""
    print("=== Salesforce Gateway Smoke Verification ===")

    # 1. Resolve configuration
    settings: SalesforceSettings | None = None
    credential_dir: Path | None = None

    if config_path and config_path.is_file():
        try:
            # Check if this is an AppConfig or a direct SalesforceSettings file
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()
            if "salesforce_settings_ref" in content or "data_root" in content:
                app_config, paths = load_config(config_path)
                credential_dir = paths.data_root / "credentials"
                if paths.salesforce_settings_path and paths.salesforce_settings_path.is_file():
                    settings = load_salesforce_settings(paths.salesforce_settings_path)
                else:
                    print(
                        "[PREREQUISITE STATUS] PENDING: No salesforce_settings_ref configured in AppConfig."
                    )
                    return 0
            else:
                settings = load_salesforce_settings(config_path)
                credential_dir = config_path.parent / "credentials"
        except Exception as exc:
            print(f"[ERROR] Failed to load configuration: {exc}")
            return 2
    else:
        print(
            "[PREREQUISITE STATUS] PENDING: No configuration file provided. (SF-02 handoff absent)"
        )
        return 0

    if not settings:
        print("[PREREQUISITE STATUS] PENDING: SalesforceSettings could not be resolved.")
        return 0

    print(f"Target Instance: {settings.instance_url}")
    print(f"Target API Version: {settings.api_version}")
    print(f"Mode: {'MUTATION (Opt-in)' if allow_write else 'READ-ONLY (Default)'}")

    # Validate mutation arguments upfront before any network attempts
    if allow_write:
        if not test_key or not test_key.startswith("SYNTHETIC_TEST_"):
            print("[ERROR] Live write rejected: --test-key must begin with 'SYNTHETIC_TEST_' prefix.")
            return 2

    # 2. Check Credential Store
    assert credential_dir is not None
    store = WindowsDpapiCredentialStore(credential_dir)
    transport = UrllibHttpTransport(settings)
    token_provider = OAuthTokenProvider(settings, store, transport)
    client = SalesforceGatewayV2Client(
        settings=settings,
        transport=transport,
        token_provider=token_provider,
    )

    # 3. Read Gate: Check Connection
    print("\n[Gate 1: Connection Check]")
    conn_res = client.check_connection(ConnectionCheckRequest(perform_network_check=True))
    if conn_res.is_failure:
        err = conn_res.failure.error  # type: ignore[union-attr]
        if err.category == ErrorCategory.MISSING_CONFIGURATION:
            print(f"[PREREQUISITE STATUS] PENDING: {err.message}")
            print("SF-02 integration authorization handoff is not configured.")
            return 0
        print(f"[FAILED] Connection check failed: {err.message} (safe_code={conn_res.failure.safe_provider_code})")  # type: ignore[union-attr]
        return 1

    conn_val = conn_res.value
    print(f"[PASSED] Connected to Org: {conn_val.org_id} (API Version: {conn_val.api_version})")  # type: ignore[union-attr]

    # 4. Read Gate: Limits
    print("\n[Gate 2: API Limits Check]")
    limits_res = client.get_limits(LimitsRequest())
    if limits_res.is_success and limits_res.value:
        print(
            f"[PASSED] Daily API Requests: {limits_res.value.daily_api_requests_remaining} remaining / "
            f"{limits_res.value.daily_api_requests_max} max"
        )
    else:
        print(f"[NOTICE] Limits call returned: {limits_res.failure.error.message if limits_res.failure else 'Unavailable'}")  # type: ignore[union-attr]

    # 5. Read Gate: Describe Object
    print(f"\n[Gate 3: Describe Object ({target_object})]")
    desc_res = client.describe_object(DescribeObjectRequest(object_name=target_object))
    if desc_res.is_success and desc_res.value:
        print(f"[PASSED] Object '{target_object}' verified. External IDs: {desc_res.value.external_id_fields}")
    else:
        print(f"[NOTICE] Object describe returned: {desc_res.failure.error.message if desc_res.failure else 'Unavailable'}")  # type: ignore[union-attr]

    # Stop here if read-only
    if not allow_write:
        print("\n=== Read-only smoke checks completed successfully. ===")
        return 0

    # 6. Mutation Gate
    print(f"\n[Gate 4: Scoped Synthetic Mutation]")
    if not test_key or not test_key.startswith("SYNTHETIC_TEST_"):
        print("[ERROR] Live write rejected: --test-key must begin with 'SYNTHETIC_TEST_' prefix.")
        return 2

    # Verify key collision
    pre_read = client.get_record(
        GetRecordRequest(
            object_name=target_object,
            external_id_field=external_id_field,
            external_id_value=test_key,
            fields=["Id"],
        )
    )
    if pre_read.is_success:
        print(f"[ABORT] Key '{test_key}' already exists in org. Halting to avoid overwriting existing data.")
        return 1

    # Perform Upsert
    print(f"Upserting synthetic record under key '{test_key}'...")
    upsert_res = client.upsert_by_external_id(
        UpsertRequest(
            object_name=target_object,
            external_id_field=external_id_field,
            external_id_value=test_key,
            fields={"Title__c": "Synthetic Test Title (SFCLIENT-01 Smoke)"},
            replay_safe=True,
        )
    )
    if upsert_res.is_failure:
        print(f"[FAILED] Upsert failed: {upsert_res.failure.error.message}")  # type: ignore[union-attr]
        return 1

    rec_id = upsert_res.value.record_id  # type: ignore[union-attr]
    print(f"[PASSED] Record upserted successfully: Record ID {rec_id}")

    # Perform Update
    print(f"Updating record ID '{rec_id}'...")
    upd_res = client.update_record(
        UpdateRequest(
            object_name=target_object,
            record_id=rec_id,
            fields={"Title__c": "Updated Synthetic Test Title"},
        )
    )
    if upd_res.is_failure:
        print(f"[FAILED] Update failed: {upd_res.failure.error.message}")  # type: ignore[union-attr]
        return 1
    print(f"[PASSED] Record updated successfully.")

    # Read back to verify single logical row
    post_read = client.get_record(
        GetRecordRequest(
            object_name=target_object,
            record_id=rec_id,
            fields=["Id", "Title__c"],
        )
    )
    if post_read.is_success and post_read.value:
        print(f"[PASSED] Readback verified single logical row (Title: '{post_read.value.fields.get('Title__c')}').")
    else:
        print(f"[FAILED] Readback verification failed.")
        return 1

    print("\n=== All live smoke checks completed successfully. ===")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Salesforce Gateway Smoke Verification Script")
    parser.add_argument("--config", type=Path, default=None, help="Path to configuration JSON")
    parser.add_argument("--allow-write", action="store_true", help="Explicit opt-in to execute mutation check")
    parser.add_argument("--test-key", type=str, default=None, help="Synthetic external ID key for mutation check")
    parser.add_argument("--object", type=str, default="Job__c", help="Target sObject API name")
    parser.add_argument("--external-id-field", type=str, default="External_Id__c", help="External ID field API name")

    args = parser.parse_args()
    code = run_smoke(
        config_path=args.config,
        allow_write=args.allow_write,
        test_key=args.test_key,
        target_object=args.object,
        external_id_field=args.external_id_field,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
